#!/usr/bin/env python3
"""The confirmation run: the Macromolecules study's headline results on the released code, 0.13.0
(docs/exec-plans/active/confirmation-plan.md, approved 2026-10-27, its predictions written before any run).

Parts A and B ran on tag `study-freeze-2`, where one research session wrote the answer and the findings together. The
released code (tag `study-freeze-4`) answers first and writes the findings in a resumed second turn of the same
session. This run checks, on a small pre-registered subset, that it reproduces Part A's headline results. No engine is
called outside `run-a2`, `run-cs` and `score-cs`.

- A2, confirmed (`2026-10-confirm-a2`): test 1's 60 held-out questions in test 1's order on K0 and KF, one replicate,
  researcher and checker on Codex: 120 answers and checks. On two-turn code a researcher arm runs through
  `parity.answer_ontology`, both turns, saving nothing (`driver.answer`); its metrics record `newTokens` over both
  turns, `seconds` to the answer, `depositSeconds` and `totalSeconds`.
- The case studies, confirmed (`2026-10-confirm-cs`): cs1–cs4 once, as one more replicate of Part A's A5 (the same
  questions and arms on fresh copies of KF, cs4's first askings through the normal loop on their copy), then scored
  blind by `case_studies/score.py` (Claude Code, blind to the arm).
- `report`: the plan's predictions 1–5, each with its numbers and met or not met, against Part A's recorded results
  (`analysis/a2a3e8/results.json`, `analysis/a5/results.json`, and A2's answer rows for Part A's seconds), written to
  `analysis/confirm/` (`results.json`, `results.md`). It reads the records only.

Part A's harness is reused, not copied: `configure()` points `part_a.py` and `case_studies.py` at this run's pins,
stores and folders for this process, as `recursive.configure` points `recursive.py` at a restart. Their files are
unchanged, and a process that does not call it runs them as they ran. KF is read only from its frozen copy
(`analysis/kf/workspaces/KF`, made by `analysis/kf.py`; its store and its graph release): the live store has taken new
questions since 2026-10-25. K0 is test 1's store as it is.

Nothing is prepared or run unless (`pinned`): the code under test is tag study-freeze-4 at its pinned commit
(`frozen`; OOPC_STUDY_CODE at the worktree `.oopc/study/freeze-4`); the researcher prompt, both models and the graph
release are the pins; KF's frozen copy and K0 have their fingerprints; and neither the code under test (`oopc`,
`config`) nor the harness's `studies/` has uncommitted changes. Each prepared folder records the pins, its stores and
the harness revision (`pins.json`); each run appends the revision it ran from and the Codex floor (`runs.jsonl`).

    export OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main checkout>/.oopc/study/freeze-4
    python -B confirm.py prepare-a2 [--shards N]   # 2026-10-confirm-a2/r1-s1 … r1-sN, plans fixed once written
    python -B confirm.py run-a2 [--shard K]        # one process per shard folder; resumable; STOP in it stops it
    python -B confirm.py prepare-cs                # 2026-10-confirm-cs, plans fixed once written
    python -B confirm.py run-cs                    # answers and checks, then the blind scoring once all are settled
    python -B confirm.py score-cs                  # the blind scoring alone: what is still to score
    python -B confirm.py status
    python -B confirm.py report [--out DIR]        # analysis/confirm/results.json, results.md

`--into DIR` uses run folders under DIR instead of `.oopc/loop/harness/`: a dry run on the real inputs.
"""
import argparse, contextlib, json, statistics, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from case_studies import case_studies, score  # noqa: E402
from part_a import a2a3e8_results, a5_results, estimate, part_a  # noqa: E402
from oopc import engines  # noqa: E402
from oopc.util import locked, now, read_json  # noqa: E402

TAG = "study-freeze-4"
PINS = {"tag": TAG, "tagCommit": "918a64c", "promptVersion": "86404bf073ce",
        "models": {engines.CODEX: "gpt-6.1-sol", engines.CLAUDE: "claude-opus-5-5"},
        "release": "oopc-6ad56d8b354d053bcc3cf3a1", "knowledgeSnapshot": "oopc-knowledge-db1fc22ca88a0c0b45b9218b",
        "kf": {"findings": 8899, "notes": 2195, "sha256": "efdf88117f1073b8"},
        "k0": {"findings": 150, "notes": 160, "sha256": "dbd2c9d6f3dd7fc5"}}  # K0 as Part A recorded it
KF = common.analysis_dir("kf") / "workspaces" / "KF"  # KF's frozen copy (analysis/kf.py), never the live store
K0 = common.run_dir("2026-10-ablation") / "workspaces" / "K0"  # test 1's 2026-10-01 store, as it is
HELDOUT = common.run_dir("2026-10-ablation") / "heldout.json"  # test 1's 60 held-out questions
A2 = "2026-10-confirm-a2"
CS = "2026-10-confirm-cs"
EXPERIMENT = "A2-confirm"  # Part A's name for it here: its plans are "a2-confirm-r1-s<k>"
CS_REPLICATE = 6  # one more replicate of A5: r1 the 2026-10-16 run, r2–r5 Part A's
PART_A = {"a2": common.analysis_dir("a2a3e8") / "results.json",  # part_a/a2a3e8_results.py
          "a2Rows": common.run_dir("2026-10-kf-scaling") / "rows.json",  # part_a.py report A2: one row per answer
          "a5": common.analysis_dir("a5") / "results.json"}  # part_a/a5_results.py
OUT = common.analysis_dir("confirm")
ARMS, STRATA = ("K0", "KF"), ("near", "mid", "far")
TURNS = ("totalSeconds", "depositSeconds", "answerNewTokens", "depositNewTokens")
PIN_KEYS = ("kind", "tag", "tagCommit", "promptVersion", "models", "release", "knowledgeSnapshot", "kf", "k0",
            "checker", "engines", "stores", "experiment", "replicate", "shard", "shards", "at")


# ----- this run's pins, pointed at by the reused modules -----

def configure():
    """Point the reused modules at this run, for this process (as `recursive.configure` points `recursive.py` at a
    restart). Part A's pins become this run's and its KF the frozen copy (store and graph release); its experiments are
    this run's A2 alone (`part_a.specs` gives it K0 and KF, as A4's; `part_a.questions_of` test 1's 60 questions in
    test 1's order, as A2's) and its case-study replicates this run's folder alone; the case studies run from this
    run's tag (`frozen`) on copies of the frozen KF. Every command calls it first."""
    part_a.PINS, part_a.ROOT, part_a.K0, part_a.HELDOUT = PINS, KF, K0, HELDOUT
    part_a.EXPERIMENTS = {EXPERIMENT: {"folder": A2, "replicates": 1, "reference": "K0", "pairs": []}}
    part_a.CASE_STUDIES, part_a.PLANTED = [CS], []
    case_studies.TAG, case_studies.ROOT, case_studies.frozen = TAG, KF, _frozen


def _frozen():
    """`case_studies.frozen` once configured: this module's check, looked up when called."""
    return frozen()


def _git(where, *args):
    return subprocess.check_output(["git", *args], cwd=where, text=True, stderr=subprocess.DEVNULL).strip()


def frozen():
    """The code under test is exactly tag study-freeze-4 at its pinned commit (`case_studies.frozen`, for this run's
    tag); returns the tag's commit, or SystemExit."""
    try:
        tag = _git(common.ROOT, "rev-parse", TAG + "^{commit}")
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("Tag %s does not exist: the confirmation run runs only from it." % TAG)
    if not tag.startswith(PINS["tagCommit"]):
        raise SystemExit("Tag %s is %s, not the pinned %s." % (TAG, tag[:12], PINS["tagCommit"]))
    try:
        head = _git(common.CODE, "rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        head = "not a git checkout"
    if head != tag:
        raise SystemExit("The code under test (%s, %s) is not %s; set OOPC_STUDY_CODE to a worktree at the tag "
                         "(.oopc/study/freeze-4)." % (common.CODE, head[:12], TAG))
    return tag


def pinned():
    """Every pin, or SystemExit naming what does not hold: the tag (`frozen`), the researcher prompt, both models, the
    graph release and KF's fingerprint, read from KF's frozen copy, and nothing uncommitted in the code under test or
    the harness (`part_a.pinned`, configured); then K0's fingerprint. Returns the pins as found."""
    configure()
    if not (KF / "releases/current.json").exists():
        raise SystemExit("KF's frozen copy is not at %s (analysis/kf.py makes it); the live store is never read" % KF)
    found = part_a.pinned()
    k0 = driver.fingerprint(K0)
    if k0 != PINS["k0"]:
        raise SystemExit("K0 is not test 1's store as Part A answered on it: %s" % json.dumps(k0))
    return dict(found, k0=k0)


# ----- prepare, run, score -----

def prepare_a2(shards=1, into=None):
    """A2's confirmation through `part_a.prepare`: its K0 and KF copies and its run folders `r1-s<k>`, each a driver
    plan fixed once written, with test 1's questions dealt round robin from test 1's order (one folder by default)."""
    pinned()
    return part_a.prepare(EXPERIMENT, shards, into)


def run_a2(shard=1, hours=36, into=None):
    """One shard folder of A2's confirmation to its end (`part_a.run`: locked, resumable, logged in `runs.jsonl`)."""
    pinned()
    path = part_a.folder(A2, into) / ("r1-s%d" % shard)
    if not (path / "pins.json").exists():
        raise SystemExit("%s is not prepared; run prepare-a2 first" % path)
    return part_a.run(path, hours)


def prepare_cs(into=None):
    """The case studies' replicate (`case_studies.prepare`, on copies of the frozen KF; R0 on an empty store), each
    researcher copy checked to be KF, and its pins recorded (`pins.json`, kind "case-studies", as Part A's A5)."""
    pins = pinned()
    base = part_a.folder(CS, into)
    case_studies.prepare(base)
    found = {s: read_json(base / s / "plan.json")["stores"] for s in case_studies.STUDIES}
    found["cs4-first"] = {"W": read_json(base / "cs4-first/plan.json")["store"]}
    if any(fp != PINS["kf"] for study in found.values() for arm, fp in study.items() if arm != "R0"):
        raise SystemExit("A store copy in %s is not KF" % base)
    return part_a.record(base, "case-studies", pins, experiment="A5-confirm", replicate=CS_REPLICATE, stores=found)


def run_cs(hours=36, into=None):
    """The case studies' replicate to its end as Part A ran its A5 replicates (`part_a.run`): every study's answers and
    checks, cs4's first askings and repeats, then, once every item is settled, the blind scoring."""
    pinned()
    base = part_a.folder(CS, into)
    if not (base / "pins.json").exists():
        raise SystemExit("%s is not prepared; run prepare-cs first" % base)
    return part_a.run(base, hours)


def score_cs(hours=6, into=None):
    """The blind scoring alone (`score.run`, Claude Code, blind to the arm), for a replicate whose answers are settled:
    what is still to score is scored, what is scored or failed for good is not scored again. Locked against `run-cs`,
    logged in `runs.jsonl`; its sessions stop at the folder's STOP file."""
    pinned()
    base = part_a.folder(CS, into)
    if not (base / "pins.json").exists():
        raise SystemExit("%s is not prepared; run prepare-cs first" % base)
    if not case_studies.settled(base):
        raise SystemExit("Not every item of %s is settled; run run-cs first" % base)
    hold = contextlib.ExitStack()
    try:
        hold.enter_context(locked(base / "run.lock", blocking=False))
    except BlockingIOError:
        raise SystemExit("Another process is running %s" % base)
    entry = {"startedAt": now(), "command": "score-cs", "harness": part_a.revision(), "hours": hours,
             "claudeFloor": common.CLAUDE_FLOOR, "status": "crashed"}
    with hold:
        try:
            score.run(base, runner=case_studies.guard(time.time() + hours * 3600, base, base))
            found = score.pending(base, list(score.RUBRIC))
            entry.update(status="stopped" if found["pending"] else "completed", **found)
        finally:
            entry["finishedAt"] = now()
            with open(base / "runs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    return dict(found, byArm=score.report(base)["byArm"])


def status(into=None):
    """Each folder's progress (`part_a.status`, configured: this run's folders only)."""
    configure()
    return part_a.status(into)


# ----- report: from the records only -----

def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe(path):
    return jread(path) if Path(path).exists() else None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def records(path):
    """A prepared folder's pins (without local paths), whether they are this run's, and the revisions it ran from."""
    found = maybe(Path(path) / "pins.json") or {}
    log = Path(path) / "runs.jsonl"
    runs = [json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.exists() else []
    holds = (str(found.get("tagCommit", "")).startswith(PINS["tagCommit"])
             and all(found.get(k) == PINS[k] for k in ("promptVersion", "models", "release", "kf")))
    return dict({k: found[k] for k in PIN_KEYS if k in found}, pinsHold=holds,
                harnessRevision=(found.get("harness") or {}).get("revision"),
                harnessClean=(found.get("harness") or {}).get("clean"),
                runRevisions=sorted({(r.get("harness") or {}).get("revision") for r in runs} - {None}),
                runsClean=all((r.get("harness") or {}).get("clean") for r in runs),
                ranFrom=min((r["startedAt"] for r in runs if r.get("startedAt")), default=None),
                ranTo=max((r["finishedAt"] for r in runs if r.get("finishedAt")), default=None))


def a2_rows(into=None):
    """A2's confirmation, one row per answer (`part_a.answers`, read only: costs, citations, the check's measures), with
    what the released code records of its two turns. An answer whose second turn failed without reporting its tokens has
    no new tokens of both turns (None), so it is left out of the token measures and counted as `depositFailed`."""
    base = part_a.folder(A2, into)
    layout = jread(base / "experiment.json")
    rows = []
    for name in layout["folders"]:
        metrics = {(q["id"], arm): ((item.get("answer") or {}).get("metrics") or {})
                   for _, q, arm, item in part_a.items(base / name)}
        for row in part_a.answers(base / name, EXPERIMENT, 1):
            m = metrics[row["id"], row["arm"]]
            row.update({k: m.get(k) for k in TURNS}, depositFailed=bool(m.get("depositFailed")))
            if row["depositFailed"] and m.get("depositNewTokens") is None:
                row["newTokens"] = None
            rows.append(row)
    return layout, rows


def counts(rows):
    """One arm's answers: the check's measures first (over the answers checked), then new tokens, web calls and time,
    then passes and access-uncertain statements."""
    answered = [r for r in rows if r["answered"]]
    checked = [r for r in answered if r["checked"]]
    web = [r["webCalls"] for r in answered if r["webCalls"] is not None]
    return {"answers": len(rows), "answered": len(answered), "checked": len(checked),
            "contradicted": sum(r["contradicted"] or 0 for r in checked),
            "answersContradicted": sum(bool(r["contradicted"]) for r in checked),
            "complete": sum(r["complete"] is True for r in checked),
            "resultGiven": sum(r["resultGiven"] is True for r in checked),
            "medianNewTokens": median(r["newTokens"] for r in answered),
            "meanWebCalls": round(statistics.mean(web), 3) if web else None,
            "noWeb": sum(r["webCalls"] == 0 for r in answered),
            "citingFindings": sum((r.get("findingCitations") or 0) > 0 for r in answered),
            "medianSeconds": median(r.get("seconds") for r in answered),
            "medianDepositSeconds": median(r.get("depositSeconds") for r in answered),
            "medianTotalSeconds": median(r.get("totalSeconds") for r in answered),
            "depositFailed": sum(bool(r.get("depositFailed")) for r in answered),
            "pass": sum(r["pass"] is True for r in checked),
            "accessUncertain": sum(r["accessUncertain"] or 0 for r in checked)}


def swapped(rows, key, arm=None):
    """Rows with `key` in place of new tokens (and renamed to `arm`), so `estimate.paired`'s ratio is of `key`."""
    return [dict(r, newTokens=r.get(key), **({"arm": arm} if arm else {})) for r in rows]


def a2_summary(rows):
    """Per stratum and overall: K0's and KF's counts, and KF against K0 paired per question (`estimate.paired`, Part A's
    convention: the median paired token ratio with its bootstrap interval over questions, the mean paired web-call
    difference, the web ratio and the sourced-result difference), with the paired ratios of seconds to the answer and of
    total seconds beside it."""
    out = {}
    for stratum in STRATA + ("all",):
        mine = [r for r in rows if stratum == "all" or r["stratum"] == stratum]
        if not mine:
            continue
        paired = estimate.paired(mine, "KF", "K0")
        paired.update({key: estimate.paired(swapped(mine, key), "KF", "K0")["tokens"]
                       for key in ("seconds", "totalSeconds")})
        out[stratum] = {"arms": {arm: counts([r for r in mine if r["arm"] == arm]) for arm in ARMS}, "paired": paired}
    return out


def across(rows, theirs):
    """Descriptive, each arm on the released code against the same arm in Part A, on the same questions: per stratum,
    the median over questions of this run's value over Part A's (its three replicates pooled by geometric mean), with
    its interval. New tokens of both turns against the single session's; seconds to the answer, and total seconds,
    against the single session's seconds."""
    out = {}
    for arm in ARMS:
        out[arm] = {}
        for stratum in STRATA + ("all",):
            def pick(found):
                return [r for r in found if r["arm"] == arm and stratum in ("all", r["stratum"])]
            out[arm][stratum] = {
                key: estimate.paired(swapped(pick(rows), key, "confirm") + swapped(pick(theirs), ref, "partA"),
                                     "confirm", "partA")["tokens"]
                for key, ref in (("newTokens", "newTokens"), ("seconds", "seconds"), ("totalSeconds", "seconds"))}
    return out


def part_a_a2(ids):
    """Part A's A2 values the predictions are judged against. From its results (`analysis/a2a3e8`; three replicates of
    the same 60 questions): per stratum, K0's and KF's counts and KF/K0 paired. From its answer rows: each replicate's
    counts per arm, and the seconds of K0's and KF's answers to these questions (each the whole single-session answer).
    Returns the values and Part A's rows for these questions and arms."""
    results, rows = jread(PART_A["a2"]), jread(PART_A["a2Rows"])
    keys = ("answered", "checked", "contradicted", "answersContradicted", "complete", "resultGiven", "pass",
            "accessUncertain", "medianNewTokens", "meanWebCalls", "noWeb", "citingFindings")
    by = results["A2"]["byStratum"]
    mine = [r for r in rows if r["arm"] in ARMS and r["id"] in ids]
    value = {"meta": {k: results["meta"].get(k) for k in ("codeTag", "prompt", "knowledgeSnapshot", "analysisRevision",
                                                          "builtAt")},
             "byStratum": {s: {"arms": {a: {k: by[s]["arms"][a].get(k) for k in keys} for a in ARMS},
                               "paired": {k: by[s]["paired"]["KF"].get(k) for k in
                                          ("tokens", "webCalls", "webRatio", "resultGiven", "seconds")}}
                           for s in STRATA + ("all",) if s in by},
             "byReplicate": {a: {str(rep): {k: v for k, v in counts(
                 [r for r in mine if r["arm"] == a and r["replicate"] == rep]).items()
                 if k in ("answered", "checked", "contradicted", "complete", "resultGiven")}
                 for rep in sorted({r["replicate"] for r in mine})} for a in ARMS},
             "seconds": {a: {"answers": sum(r["answered"] for r in mine if r["arm"] == a),
                             "questions": len({r["id"] for r in mine if r["arm"] == a}),
                             "median": median(r["seconds"] for r in mine if r["arm"] == a and r["answered"])}
                         for a in ARMS},
             "questions": len({r["id"] for r in rows}), "sameQuestions": {r["id"] for r in rows} == set(ids)}
    return value, mine


def case_values(cs):
    """What prediction 4 reads, per replicate, from A5-shaped case-study summaries (`a5_results`: Part A's r1–r5, or
    this run's one): blind counts summed over a study's answers, new tokens and answers from the records."""
    rep = lambda study, arm, key, blind=True: a5_results.per_rep(cs, study, arm, key, blind)  # noqa: E731
    total = lambda lists: [sum(x) for x in zip(*lists)]  # noqa: E731
    four = (("cs4-first", "first"), ("cs4-repeat", "R"), ("cs4-repeat", "P"))
    return {"replicates": list(cs["replicates"]),
            "cs1": {"uncitedValues": {a: rep("cs1-conditions", a, "uncitedValues") for a in ("R", "P")},
                    "scored": {a: rep("cs1-conditions", a, "answers") for a in ("R", "P")}},
            "cs2": {"labelled": rep("cs2-conflicts", "R", "explanationLabelled"),
                    "scored": rep("cs2-conflicts", "R", "answers"),
                    "answered": rep("cs2-conflicts", "R", "answers", False)},
            "cs3": {"ranked": {a: rep("cs3-screening", a, "rankedWithSourcedValue") for a in ("R", "R0")},
                    "scored": {a: rep("cs3-screening", a, "answers") for a in ("R", "R0")},
                    "newTokens": {a: rep("cs3-screening", a, "newTokens", False) for a in ("R", "R0")},
                    "answered": {a: rep("cs3-screening", a, "answers", False) for a in ("R", "R0")}},
            "cs4": {"valueAsReported": total([rep(s, a, "givesValueAsReported") for s, a in four]),
                    "scored": total([rep(s, a, "answers") for s, a in four]),
                    "answered": total([rep(s, a, "answers", False) for s, a in four])}}


def cs_summary(into=None):
    """The confirmation's case studies read as A5's replicates were (`a5_results.case_replicate`: per answer the
    checker's measures, new tokens and web calls, and the blind scores joined to their keys), summed per study and
    arm."""
    base = part_a.folder(CS, into)
    rows, scorers = a5_results.case_replicate(CS_REPLICATE, base)
    by = {study: {arm: [dict(a5_results.summary([r for r in rows if r["study"] == study and r["arm"] == arm]),
                             replicate=CS_REPLICATE)] for arm in a5_results.ARMS[study]}
          for study in a5_results.STUDIES}
    return {"replicates": [CS_REPLICATE], "answers": rows, "byReplicate": by, "scorers": scorers}


def cross_checks(a2_base, layout, rows, cs_base, cs):
    """Each count against the report the harness wrote (each driver folder's `report.json`, the scoring's
    `report.json`); a disagreement is listed, not corrected. The driver counts only questions every arm answered and
    had checked."""
    mismatches, compared = [], 0
    keys = (("contradicted", "contradicted"), ("complete", "complete"), ("resultGiven", "resultGiven"),
            ("pass", "passes"), ("accessUncertain", "accessUncertain"))
    folders = [("A2 " + n, a2_base / n) for n in (layout or {}).get("folders", [])]
    folders += [("cases " + s, cs_base / s) for s in (a5_results.DRIVER_STUDIES if cs else [])]
    for where, path in folders:
        report = maybe(path / "report.json")
        if not report:
            mismatches.append({"where": where, "what": "no report.json"})
            continue
        for arm, theirs in report["arms"].items():
            if where.startswith("A2"):
                mine = counts([r for r in rows if r["folder"] == path.name and r["arm"] == arm])
            else:  # A5's summary names passes "passes"
                found = cs["byReplicate"][path.name][arm][0]
                mine = dict(found, **{"pass": found["passes"]})
            for key, other in keys:
                compared += 1
                if mine[key] != theirs[other]:
                    mismatches.append({"where": "%s %s" % (where, arm), "what": key, "records": mine[key],
                                       "report": theirs[other]})
    if cs:
        for name, theirs in ((maybe(cs_base / "scoring/report.json") or {}).get("byArm") or {}).items():
            group, arm = name.split("/")
            study = "cs4-first" if (group, arm) == ("cs4", "first") else "cs4-repeat" if group == "cs4" else group
            mine = cs["byReplicate"][study][arm][0]["blind"]
            for field, value in theirs.items():
                compared += 1
                if mine.get(field, 0) != value:
                    mismatches.append({"where": "blind " + name, "what": field, "records": mine.get(field, 0),
                                       "report": value})
    return {"compared": compared, "mismatches": mismatches}


# ----- the predictions -----

ci, num = a2a3e8_results.ci, a2a3e8_results.num


def opt(value, places=1):
    return "–" if value is None else num(value, places)


def series(values):
    return ", ".join(str(v) for v in values)


def part(text, met, numbers):
    """One part of a prediction: met True or False, or None when the records cannot judge it."""
    return {"part": text, "met": met, "numbers": numbers}


def verdict(parts):
    """Met when every part is; not met when no part is and one is not; partly met when some are and some are not; not
    judged when no part is not met but one cannot be judged."""
    flags = [p["met"] for p in parts]
    if flags and all(f is True for f in flags):
        return "met"
    if False in flags:
        return "partly met" if True in flags else "not met"
    return "not judged"


def predictions(confirm, base):
    """The plan's predictions 1–5, each with its parts, numbers and verdict. `confirm`: this run's A2 summary
    (`byStratum`) and case-study values (`case_values`), either None if it has not run; `base`: Part A's values
    (`part_a_a2`, and `case_values` of A5's results). A2's predictions are judged only once every A2 folder's run has
    completed (an item that failed for good then has no sourced result and no contradicted statement)."""
    out = []
    a2, b2 = confirm.get("A2"), base.get("A2")
    running = {n: f.get("state") for n, f in ((a2 or {}).get("complete") or {}).get("folders", {}).items()
               if f.get("state") != "completed"}

    def add(pid, statement, parts, note=None):
        if running and pid in ("1", "2", "3", "5"):
            parts = [dict(p, met=None) for p in parts]
            note = "A2 has not finished (%s), so it is not judged yet.%s" % (
                ", ".join("%s %s" % kv for kv in sorted(running.items())), " " + note if note else "")
        out.append({"id": pid, "prediction": statement, "parts": parts, "verdict": verdict(parts), "note": note})

    statements = {
        "1": "Near: the KF/K0 median paired token ratio is at most 0.70, with its interval below 1 (Part A: 0.52, "
             "0.41–0.57), and KF makes fewer web calls than K0 (Part A: 2.1 against 7.6).",
        "2": "Mid and far: each KF/K0 interval includes 1, or lies above it for mid (Part A: mid 1.29, 0.99–1.52; far "
             "0.94, 0.82–1.00).",
        "3": "Quality: each arm has at most 2 contradicted statements in its 60 answers, and at most 3 fewer sourced "
             "results than in Part A's comparable replicate (Part A, KF: 0/1/0 in 180; sourced 60/55/56 in 180).",
        "4": "Case studies, same direction as Part A: cs1, R leaves fewer values uncited than P; cs2, R labels its "
             "explanation as interpretation in 3 of 3; cs3, R ranks more polymers with a sourced value than R0, with "
             "fewer tokens; cs4, no answer gives a value as reported.",
        "5": "The release's own change: KF's median seconds to the answer is below Part A's median KF seconds for the "
             "same questions, which measured the whole single-session answer."}
    if a2 is None:
        for pid in ("1", "2", "3"):
            add(pid, statements[pid], [part("A2's confirmation", None, "not run")])
    else:
        by, was = a2["byStratum"], b2["byStratum"]
        near, tokens = by["near"], by["near"]["paired"]["tokens"]
        web = {a: near["arms"][a]["meanWebCalls"] for a in ARMS}
        add("1", statements["1"], [
            part("KF/K0 median paired token ratio at most 0.70", None if not tokens else tokens["median"] <= 0.70,
                 "KF/K0 near %s (Part A %s)" % (ci(tokens), ci(was["near"]["paired"]["tokens"]))),
            part("Its interval below 1", None if not tokens else tokens["high"] < 1,
                 "upper bound %s" % opt(tokens and tokens["high"], 3)),
            part("KF fewer web calls than K0 (mean per answer)",
                 None if None in web.values() else web["KF"] < web["K0"],
                 "KF %s, K0 %s per answer; KF − K0 per question %s (Part A: KF %s, K0 %s)" % (
                     opt(web["KF"]), opt(web["K0"]), ci(near["paired"]["webCalls"], 1),
                     opt(was["near"]["arms"]["KF"]["meanWebCalls"]), opt(was["near"]["arms"]["K0"]["meanWebCalls"])))])
        mid, far = by["mid"]["paired"]["tokens"], by["far"]["paired"]["tokens"]
        add("2", statements["2"], [
            part("Mid: the interval includes 1 or lies above it", None if not mid else mid["high"] >= 1,
                 "KF/K0 mid %s (Part A %s)" % (ci(mid), ci(was["mid"]["paired"]["tokens"]))),
            part("Far: the interval includes 1", None if not far else far["low"] <= 1 <= far["high"],
                 "KF/K0 far %s (Part A %s)" % (ci(far), ci(was["far"]["paired"]["tokens"])))])
        parts = []
        for arm in ARMS:
            got, total = by["all"]["arms"][arm], was["all"]["arms"][arm].get("answered")
            reps = b2["byReplicate"][arm]
            mean = statistics.mean(r["resultGiven"] for r in reps.values()) if reps else None
            parts.append(part("%s at most 2 contradicted statements" % arm, got["contradicted"] <= 2,
                              "%s %d in %d answers checked (near/mid/far %s); Part A near/mid/far %s in %s" % (
                                  arm, got["contradicted"], got["checked"],
                                  "/".join(str(by[s]["arms"][arm]["contradicted"]) for s in STRATA),
                                  "/".join(str(was[s]["arms"][arm]["contradicted"]) for s in STRATA), total)))
            parts.append(part("%s at most 3 fewer sourced results than Part A's replicate" % arm,
                              None if mean is None else got["resultGiven"] >= mean - 3,
                              "%s %d of %d (near/mid/far %s); Part A per replicate %s of %s each, mean %s, so at least "
                              "%s (Part A near/mid/far %s in %s)" % (
                                  arm, got["resultGiven"], got["answers"],
                                  "/".join(str(by[s]["arms"][arm]["resultGiven"]) for s in STRATA),
                                  series(r["resultGiven"] for r in reps.values()),
                                  next(iter(reps.values()), {}).get("answered"), opt(mean),
                                  opt(None if mean is None else mean - 3),
                                  "/".join(str(was[s]["arms"][arm]["resultGiven"]) for s in STRATA), total)))
        add("3", statements["3"], parts,
            note="Part A's comparable replicate is read as its mean per replicate (its 180 answers per arm over "
                 "three). Complete answers: %s (Part A %s)." % (
                     "; ".join("%s %d of %d" % (a, by["all"]["arms"][a]["complete"], by["all"]["arms"][a]["checked"])
                               for a in ARMS),
                     "; ".join("%s %s of %s" % (a, was["all"]["arms"][a]["complete"],
                                                was["all"]["arms"][a].get("answered")) for a in ARMS)))
    cs, b5 = confirm.get("caseStudies"), base.get("caseStudies")
    if cs is None:
        add("4", statements["4"], [part("The case studies' confirmation", None, "not run or not settled")])
    else:
        one = lambda values: values[0] if values else None  # noqa: E731
        c1, c2, c3, c4 = cs["cs1"], cs["cs2"], cs["cs3"], cs["cs4"]
        p1, p2, p3, p4 = b5["cs1"], b5["cs2"], b5["cs3"], b5["cs4"]
        asked = {s: len(v["questions"]) for s, v in case_studies.STUDIES.items()}
        scored1 = all(one(c1["scored"][a]) == asked["cs1-conditions"] for a in ("R", "P"))
        r, p = one(c1["uncitedValues"]["R"]), one(c1["uncitedValues"]["P"])
        parts = [part("cs1: R leaves fewer values uncited than P", r < p if scored1 else None,
                      "uncited Tg values over the %d questions: R %s, P %s (Part A r1–r5: R %s; P %s)" % (
                          asked["cs1-conditions"], r, p, series(p1["uncitedValues"]["R"]),
                          series(p1["uncitedValues"]["P"])))]
        labelled, scored2 = one(c2["labelled"]), one(c2["scored"])  # an answer not scored cannot be judged
        parts.append(part("cs2: R labels its explanation as interpretation in 3 of 3",
                          False if scored2 > labelled else True if scored2 == asked["cs2-conflicts"] else None,
                          "R labelled %s of %s answers scored (Part A r1–r5: %s of 3)" % (
                              labelled, scored2, series(p2["labelled"]))))
        ranked = {a: one(c3["ranked"][a]) for a in ("R", "R0")}
        spent = {a: one(c3["newTokens"][a]) for a in ("R", "R0")}
        whole = all(one(c3["scored"][a]) == asked["cs3-screening"] == one(c3["answered"][a]) for a in ("R", "R0"))
        parts.append(part("cs3: R ranks more polymers with a sourced value than R0, with fewer tokens",
                          ranked["R"] > ranked["R0"] and spent["R"] < spent["R0"] if whole else None,
                          "ranked with a sourced value: R %s, R0 %s; new tokens over the two questions: R %s, R0 %s "
                          "(Part A r1–r5: ranked R %s, R0 %s; tokens R %s, R0 %s)" % (
                              ranked["R"], ranked["R0"], k(spent["R"]), k(spent["R0"]), series(p3["ranked"]["R"]),
                              series(p3["ranked"]["R0"]), series(k(t) for t in p3["newTokens"]["R"]),
                              series(k(t) for t in p3["newTokens"]["R0"]))))
        given, scored4, answered4 = one(c4["valueAsReported"]), one(c4["scored"]), one(c4["answered"])
        expected = 3 * len(case_studies.UNANSWERABLE)
        parts.append(part("cs4: no answer gives a value as reported",
                          False if given else (True if scored4 == expected else None),
                          "%s of %s answers scored (%s answered of %d) gave a value as reported (Part A r1–r5: %s of "
                          "%s)" % (given, scored4, answered4, expected, series(p4["valueAsReported"]),
                                   series(p4["scored"]))))
        add("4", statements["4"], parts)
    if a2 is None:
        add("5", statements["5"], [part("A2's confirmation", None, "not run")])
    else:
        mine, theirs = a2["byStratum"]["all"]["arms"]["KF"], b2["seconds"]["KF"]
        versus = a2["acrossRuns"]["KF"]["all"]
        add("5", statements["5"], [
            part("KF's median seconds to the answer below Part A's", None if None in (
                mine["medianSeconds"], theirs["median"]) else mine["medianSeconds"] < theirs["median"],
                "KF %s s to the answer over %d answers, against Part A's %s s over %d answers to the same %d "
                "questions" % (
                    opt(mine["medianSeconds"]), mine["answered"], opt(theirs["median"]), theirs["answers"],
                    theirs["questions"]))],
            note="Descriptive: KF's median total seconds (answer and findings) %s, its second turn's %s; per "
                 "question, this run's seconds to the answer over Part A's %s, its total seconds over Part A's %s; K0 "
                 "%s s to the answer against Part A's %s s." % (
                     opt(mine["medianTotalSeconds"]), opt(mine["medianDepositSeconds"]), ci(versus["seconds"]),
                     ci(versus["totalSeconds"]), opt(a2["byStratum"]["all"]["arms"]["K0"]["medianSeconds"]),
                     opt(b2["seconds"]["K0"]["median"])))
    return out


def decision(found):
    """The plan's rule: if predictions 1–4 hold, the manuscript describes 0.13.0 and cites this run; if one does not,
    it keeps reporting study-freeze-2 and says so."""
    held = {p["id"]: p["verdict"] == "met" for p in found if p["id"] in ("1", "2", "3", "4")}
    return {"predictions1to4": held, "hold": all(held.values()) and len(held) == 4,
            "consequence": "The manuscript describes 0.13.0 and cites this run as evidence that the released code "
                           "reproduces the results." if all(held.values()) and len(held) == 4 else
                           "The manuscript keeps reporting study-freeze-2 and says so (a prediction of 1–4 is not met "
                           "or not judged)."}


# ----- building and writing -----

def revision():
    """This harness's commit, with "-dirty" when `confirm/` has changes not committed."""
    try:
        head = _git(Path(__file__).resolve().parent, "rev-parse", "--short=12", "HEAD")
        dirty = _git(Path(__file__).resolve().parent, "status", "--porcelain", "--", ".")
    except (OSError, subprocess.CalledProcessError):
        return None
    return head + ("-dirty" if dirty else "")


def build(into=None):
    """Everything `report` writes, from the records only."""
    configure()
    a2_base, cs_base = part_a.folder(A2, into), part_a.folder(CS, into)
    value = {"A2": None, "caseStudies": None, "partA": {}}
    layout = rows = cs = None
    if (a2_base / "experiment.json").exists():
        layout, rows = a2_rows(into)
        ids = [q["id"] for name in layout["folders"] for q in jread(a2_base / name / "plan.json")["questions"]]
        base, theirs = part_a_a2(set(ids))
        value["partA"]["A2"] = base
        kept = ("experiment", "replicates", "shards", "folders", "questions", "arms", "answers")
        value["A2"] = {"layout": {k: layout.get(k) for k in kept},
                       "complete": {"expected": layout["answers"], "rows": len(rows),
                                    "answered": sum(r["answered"] for r in rows),
                                    "checked": sum(r["checked"] for r in rows),
                                    "folders": {n: {k: v for k, v in part_a.progress(a2_base / n).items()
                                                    if k != "folder"} for n in layout["folders"]}},
                       "questions": ids, "byStratum": a2_summary(rows), "acrossRuns": across(rows, theirs),
                       "answers": rows}
    if (cs_base / "pins.json").exists() and case_studies.settled(cs_base):
        cs = cs_summary(into)
        value["caseStudies"] = dict(cs, values=case_values(cs), pending=score.pending(cs_base, list(score.RUBRIC)))
    elif (cs_base / "pins.json").exists():
        value["caseStudies"] = None
        value["caseStudiesState"] = "not settled"
    a5 = maybe(PART_A["a5"])
    if a5:
        value["partA"]["caseStudies"] = dict(case_values(a5["caseStudies"]), meta={
            k: a5["meta"].get(k) for k in ("codeTag", "prompt", "analysisRevision", "builtAt")})
    value["meta"] = {"plan": "docs/exec-plans/active/confirmation-plan.md", "pins": PINS,
                     "code": _code_revision(), "analysisRevision": revision(), "builtAt": now(),
                     "records": {"A2": {n: records(a2_base / n) for n in (layout or {}).get("folders", [])},
                                 "caseStudies": records(cs_base) if (cs_base / "pins.json").exists() else None}}
    value["crossChecks"] = cross_checks(a2_base, layout, rows or [], cs_base, cs)
    value["predictions"] = predictions(
        {"A2": value["A2"], "caseStudies": (value["caseStudies"] or {}).get("values")},
        {"A2": value["partA"].get("A2"), "caseStudies": value["partA"].get("caseStudies")})
    value["decision"] = decision(value["predictions"])
    return value


def _code_revision():
    try:
        return _git(common.CODE, "rev-parse", "--short=12", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return None


def k(value):
    return "–" if value is None else "%.1fk" % (value / 1e3)


def markdown(value):
    meta, pins = value["meta"], value["meta"]["pins"]
    lines = ["# Confirmation run: Part A's headline results on the released code (0.13.0)", "",
             "Drawn from the records only by `studies/macromolecules/confirm/confirm.py report` (revision %s) on %s; "
             "no engine call. Code `%s` (%s, code imported at %s), researcher prompt `%s`, research and checks on "
             "Codex `%s`, blind case-study scoring on Claude Code `%s`, graph release `%s`; KF `%s` (%s findings) read "
             "from its frozen copy, K0 test 1's store (%s findings). Part A's values are from `study-freeze-2`: "
             "`analysis/a2a3e8/results.json`, `analysis/a5/results.json` and A2's answer rows. One replicate: "
             "descriptive." % (meta["analysisRevision"], meta["builtAt"], pins["tag"], pins["tagCommit"], meta["code"],
                               pins["promptVersion"], pins["models"][engines.CODEX], pins["models"][engines.CLAUDE],
                               pins["release"], pins["knowledgeSnapshot"], "{:,}".format(pins["kf"]["findings"]),
                               pins["k0"]["findings"]), ""]
    d = value["decision"]
    lines += ["**Predictions 1–4 %s.** %s" % ("hold" if d["hold"] else "do not all hold", d["consequence"]), ""]
    mism = value["crossChecks"]["mismatches"]
    lines.append(("**%d mismatches between the records and the harness's reports** (see results.json)." % len(mism))
                 if mism else "Cross-checked against the harness's own reports: %d figures, no mismatch." %
                 value["crossChecks"]["compared"])
    lines.append("")
    a2 = value["A2"]
    if a2:
        c = a2["complete"]
        recs = value["meta"]["records"]["A2"]
        folders = ", ".join("%s %s (%s failed)" % (n, f.get("state"), f.get("failed")) for n, f in c["folders"].items())
        ran = [min((r["ranFrom"] or "?") for r in recs.values())[:16],
               max((r["ranTo"] or "?") for r in recs.values())[:16]]
        lines.append("- A2: %d of %d answers recorded, %d answered, %d checked; folders %s; pins %s; ran %s to %s from "
                     "harness revisions %s; second turns failed: %s." % (
                         c["rows"], c["expected"], c["answered"], c["checked"], folders,
                         "hold" if all(r["pinsHold"] for r in recs.values()) else "DO NOT HOLD", *ran,
                         ", ".join(sorted({x[:7] for r in recs.values() for x in r["runRevisions"]})) or "none",
                         ", ".join("%s %d" % (a, a2["byStratum"]["all"]["arms"][a]["depositFailed"]) for a in ARMS)))
    else:
        lines.append("- A2: not run.")
    cs = value["caseStudies"]
    if cs:
        rec = value["meta"]["records"]["caseStudies"]
        lines.append("- Case studies (replicate %d of A5): %d answers; pins %s; blind scoring %s." % (
            CS_REPLICATE, len(cs["answers"]), "hold" if rec["pinsHold"] else "DO NOT HOLD",
            "complete" if not (cs["pending"]["pending"] or cs["pending"]["failed"]) else
            "pending %s, failed %s" % (cs["pending"]["pending"], cs["pending"]["failed"])))
    else:
        lines.append("- Case studies: %s." % value.get("caseStudiesState", "not run"))
    lines += ["", "## The predictions", ""]
    for p in value["predictions"]:
        lines.append("- **%s, %s.** %s" % (p["id"], p["verdict"], p["prediction"]))
        for q in p["parts"]:
            word = "not judged" if q["met"] is None else "met" if q["met"] else "not met"
            lines.append("  - %s: %s (%s)." % (q["part"], word, q["numbers"]))
        if p.get("note"):
            lines.append("  - Note: %s" % p["note"])
    if a2:
        was = value["partA"]["A2"]["byStratum"]
        lines += ["", "## A2: K0 and KF on test 1's %d held-out questions (one replicate)" % len(a2["questions"]), "",
                  "Counts per stratum, then Part A's over its three replicates in brackets. New tokens are both "
                  "turns'; seconds to the answer are the first turn's; ratios are KF/K0 paired per question (median, "
                  "bootstrap 95% interval).", "",
                  "| Stratum | Arm | Contradicted | Complete | Sourced result | Median new tokens | Mean web calls | "
                  "Median s to answer | Median total s | Passes | Access-uncertain |",
                  "| --- | --- |" + " ---: |" * 9]
        for s in STRATA + ("all",):
            for arm in ARMS:
                a, b = a2["byStratum"][s]["arms"][arm], was[s]["arms"][arm]
                cells = (s, arm, a["contradicted"], b["contradicted"], a["complete"], b["complete"],
                         a["resultGiven"], b["resultGiven"], k(a["medianNewTokens"]), k(b["medianNewTokens"]),
                         opt(a["meanWebCalls"]), opt(b["meanWebCalls"]), opt(a["medianSeconds"]),
                         opt(a["medianTotalSeconds"]), a["pass"], b["pass"], a["accessUncertain"], b["accessUncertain"])
                lines.append("| %s | %s | %d (%s) | %d (%s) | %d (%s) | %s (%s) | %s (%s) | %s | %s | %d (%s) | "
                             "%d (%s) |" % cells)
        lines += ["", "| Stratum | KF/K0 tokens | (Part A) | KF − K0 web calls | (Part A) | KF/K0 s to answer | "
                  "KF/K0 total s | (Part A s) |", "| --- |" + " ---: |" * 7]
        for s in STRATA + ("all",):
            p, b = a2["byStratum"][s]["paired"], was[s]["paired"]
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                s, ci(p["tokens"]), ci(b["tokens"]), ci(p["webCalls"], 1), ci(b["webCalls"], 1), ci(p["seconds"]),
                ci(p["totalSeconds"]), ci(b.get("seconds"))))
        lines += ["", "The released code against Part A, the same arm on the same questions (this run over Part A's "
                  "replicates pooled, median over questions):", "",
                  "| Arm | Stratum | New tokens | Seconds to answer | Total seconds against Part A's seconds |",
                  "| --- | --- | ---: | ---: | ---: |"]
        for arm in ARMS:
            for s in STRATA + ("all",):
                v = a2["acrossRuns"][arm][s]
                lines.append("| %s | %s | %s | %s | %s |" % (arm, s, ci(v["newTokens"]), ci(v["seconds"]),
                                                             ci(v["totalSeconds"])))
    if cs:
        lines += ["", "## Case studies (one more replicate of A5)", "",
                  "| Study | Arm | Answers | Contradicted | Complete | Sourced result | New tokens | Web calls | "
                  "Passes | Blind counts |", "| --- | --- |" + " ---: |" * 7 + " --- |"]
        for study in a5_results.STUDIES:
            for arm in a5_results.ARMS[study]:
                s = cs["byReplicate"][study][arm][0]
                lines.append("| %s | %s | %d | %d | %d | %d | %s | %d | %d | %s |" % (
                    study, arm, s["answers"], s["contradicted"], s["complete"], s["resultGiven"], k(s["newTokens"]),
                    s["webCalls"], s["passes"], ", ".join("%s %s" % kv for kv in sorted(s["blind"].items()))))
    lines += ["", "## Notes", "",
              "- Part A ran the same questions on `study-freeze-2` in one session per answer; this run's researcher "
              "answers in a first turn and writes the findings in a resumed second (saving nothing). New tokens are "
              "both turns', as Part A's single session wrote the same findings; an answer whose second turn failed "
              "without reporting its tokens is left out of the token measures.",
              "- Prediction 3 reads \"Part A's comparable replicate\" as Part A's mean per replicate (its 180 answers "
              "per arm over three replicates); each replicate's count is given beside it.",
              "- Prediction 5 compares the first turn's seconds with Part A's whole single-session seconds, as the "
              "plan says; the total seconds are given beside it. Seconds also depend on how many sessions ran at once, "
              "which differed between the runs."]
    return "\n".join(lines) + "\n"


def write(value, out=None):
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(value, ensure_ascii=False, indent=1)
    if "/Users/" in text or str(Path.home()) in text:
        raise SystemExit("refusing to write a local path into the results")
    (out / "results.json").write_text(text + "\n", encoding="utf-8")
    (out / "results.md").write_text(markdown(value), encoding="utf-8")
    return out


def report(into=None, out=None):
    value = build(into)
    return value, write(value, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["prepare-a2", "run-a2", "prepare-cs", "run-cs", "score-cs", "status",
                                            "report"])
    parser.add_argument("--shards", type=int, default=1, help="prepare-a2: question shards (folders r1-s1 … r1-sN)")
    parser.add_argument("--shard", type=int, default=1, help="run-a2: the shard folder to run")
    parser.add_argument("--hours", type=float, help="run-a2 and run-cs: 36 by default; score-cs: 6")
    parser.add_argument("--into", type=Path, help="run folders under DIR instead of .oopc/loop/harness/")
    parser.add_argument("--out", type=Path, help="report: write here instead of analysis/confirm/")
    args = parser.parse_args()
    if args.command == "prepare-a2":
        out = prepare_a2(args.shards, args.into)
        out.pop("pins", None)
    elif args.command == "run-a2":
        out = run_a2(args.shard, args.hours or 36, args.into)
    elif args.command == "prepare-cs":
        out = prepare_cs(args.into)
    elif args.command == "run-cs":
        out = run_cs(args.hours or 36, args.into)
    elif args.command == "score-cs":
        out = score_cs(args.hours or 6, args.into)
    elif args.command == "status":
        out = status(args.into)
    else:
        value, path = report(args.into, args.out)
        for p in value["predictions"]:
            print("%-2s %-11s %s" % (p["id"], p["verdict"], " | ".join("%s: %s" % (
                "–" if q["met"] is None else "ok" if q["met"] else "NO", q["numbers"]) for q in p["parts"])))
        checks = value["crossChecks"]
        print("cross-checks: %d compared, %d mismatches" % (checks["compared"], len(checks["mismatches"])))
        out = {"decision": value["decision"], "wrote": [str(path / "results.json"), str(path / "results.md")]}
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
