#!/usr/bin/env python3
"""Part B's performance, from the final evaluation's records only (restart-study-plan.md, Measures "Performance" and
"Dose", Predictions 2, 3, the held-out half of 4, and 5, Analysis). No engine call and no network. Snapshot stores are
opened read only; no arm's store copy is opened at all.

What it reads (read only):

- `final/final.json` and `final/shard-1` … `shard-10`: each shard's driver `plan.json` (the 50 arms, their prompt
  versions and store fingerprints, its 6 of test 1's 60 held-out questions) and `items/NNNN-<arm>.json` (the answer:
  new tokens, web calls, seconds and knowledge lookups by freeze-2's `parity._metrics`, its citations; the check: its
  statements, verdict and whether the result was given). Each check's measures are recomputed from its statements as
  freeze-2's `reviewer.measures` does (`build_results.check_measures`) and compared with the stored ones.
- Each answer's session trace, `workspaces/<arm>/.oopc/runs/<runId>/events.jsonl` and `payloads/`: every
  `search_knowledge` call the researcher made, with the payload the tool returned. **Dose** is read from these
  recorded returns, not replayed: the distinct saved findings (Reviewed, Added, Needs checking; the search never
  returns Rejected ones) that the answer's searches returned, counted per answer. For the P0 arms there is one answer
  per question and store, so this is the plan's "number of findings its search returns" for that question and store;
  it saturates near 20–25, because one search returns at most 10–25 relevant findings plus 12 from the same sources.
  The first search's return and the notes returned are kept beside it. The number of searches in the trace must equal
  the answer's knowledge lookups.
- `R<n>/snapshots.json`, `R<n>/snapshots/S1`…`S5` (fingerprints recomputed as `driver.fingerprint` does and compared
  with the recorded ones and with each arm's in the plans; the findings' task and status), `R<n>/prompts/P0`…`P5`
  (versions compared with the arms'), `R<n>/eval/round-*/dev/decision.json` (which edits were adopted) and
  `R<n>/rounds.json` with each restart's workspace question states: for each near held-out question, the restart's
  own near-parent task (the campaign question it was drawn from, asked in its campaign wording) and that task's exact
  and reworded revisits. **The parent is in the store** at S<k> when S<k> holds at least one finding saved by one of
  those tasks that is not Rejected (findings a search can return).

Estimators (macromolecules-study-plan.md, Statistics; restart-study-plan.md, Analysis):

- Paired per question. Tokens and seconds: the median paired ratio, with a bootstrap 95% interval over questions
  within one restart (`ablation/analyze.ratio_ci`, 2,000 draws, seed 7, as test 1 and test 2); web calls: the mean
  paired difference (`analyze.diff_ci`).
- Across restarts: the same statistic over every (restart, question) pair, with a **hierarchical bootstrap**: each
  draw takes 5 restarts with replacement, then the stratum's questions with replacement (the questions are the same in
  every restart, so they are drawn once per draw and shared), and pools every drawn pair.
- The **mixed model** (statsmodels `MixedLM`, REML): log new tokens on log findings in the store, with stratum, and the
  question and the restart as crossed random intercepts, on the P0 arms on S1–S5 (S0 has no findings, so E0 cannot
  enter a log-findings fit); fitted as the plan writes it (one slope, stratum as a shift), with one slope per stratum,
  and with log(1 + dose) in place of log findings. Beside it, the within-(restart, question) slope with the
  hierarchical bootstrap.
- Quality first, then costs; passes second (CL-21: two checks of the same answers move passes; contradicted
  statements, completeness and sourced results barely). Contradicted statements are statements unsupported for a
  reason other than source access, completeness statements included, as freeze-2 counts them.

Rules for the predictions. The plan gives no thresholds; these were written by the analyst on 2026-10-21 before any
number of the final evaluation was computed. A prediction is met when every part holds, not met when none does,
partly met otherwise.

- 2. Knowledge alone, per restart, from P0 × S5 against E0 (= P0 × S0): near questions *fall* when the token ratio's
  interval lies below 1 and the web-call difference's interval below 0; far questions *stay flat* when the token
  ratio's interval contains 1 and the web-call difference's contains 0. Parts: near falls in all five restarts; far
  stays flat in all five; every P0 arm (E0 and each Rn-P0-Sk) has at most one contradicted statement per stratum.
- 3. The prompt alone, per restart over all 60 questions: |log(P5S0/E0 token ratio)| below |log(P0S5/E0 token
  ratio)|, and |P5S0 − E0 web-call difference| below |P0S5 − E0 difference|. Parts: tokens in all five restarts; web
  calls in all five.
- 4, held-out half. Every arm that carries adopted edits (Rn-Pk-Sk whose prompt is not P0, and Rn-P5-S0) against P0
  on the same store (Rn-P0-Sk, or E0): contradicted statements over the 60 answers. Met if none has more; partly met
  if each excess is a single statement (two checks of the same answers moved one answer's count by one, CL-21); not
  met if any has two or more.
- 5. The store effect is the knowledge effect on near questions (where the store is expected to act; far questions
  are the control), per restart. Parts: the five median log token ratios have one sign; their range is below the
  absolute mean; the five mean web-call differences have one sign; their range is below the absolute mean.

Writes `analysis/restarts-final/results.json` and `results.md`. Everything is descriptive: 20 questions per stratum
detect only large effects, and the same 60 questions serve every restart, so the restarts' intervals are not
independent.

    OOPC_STUDY_ROOT=<main checkout> python -B final_results.py [--base DIR] [--restarts DIR] [--out DIR]
"""
import argparse, collections, datetime as dt, json, math, os, random, re, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve()
_ROOT = Path(os.environ.get("OOPC_STUDY_ROOT") or HERE.parents[3]).resolve()
FREEZE2 = _ROOT / ".oopc/study/freeze-2"  # tag study-freeze-2, whose code wrote every record read here
if FREEZE2.exists():
    os.environ.setdefault("OOPC_STUDY_CODE", str(FREEZE2))
sys.path.insert(0, str(HERE.parents[1]))  # studies/macromolecules, for common, ablation and part_a
sys.path.insert(0, str(HERE.parent))  # recursive/, for build_results
import common  # noqa: E402  (puts the code that wrote the records first on sys.path)
import build_results as B  # noqa: E402
from ablation import analyze  # noqa: E402
from part_a import estimate  # noqa: E402

BASE = common.run_dir("2026-10-restarts")
FINAL = BASE / "final"
HELDOUT = common.run_dir("2026-10-ablation") / "heldout.json"
OUT = common.analysis_dir("restarts-final")
RESTARTS = ("R1", "R2", "R3", "R4", "R5")
ROUNDS = 5
STRATA = ("near", "mid", "far")
SUBSETS = ("all",) + STRATA
DRAWS, SEED = analyze.DRAWS, 7
ARM = re.compile(r"R(\d+)-P(\d+)-S(\d+)\Z")
COMPARISONS = (  # name, (arm, reference) by slot, what it isolates
    ("knowledge", ("P0S5", "P0S0"), "knowledge alone: P0 on S5 against E0"),
    ("prompt", ("P5S0", "P0S0"), "the prompt alone: P5 on S0 against E0"),
    ("system", ("P5S5", "P0S0"), "the system as it ended: P5 on S5 against E0"),
    ("promptOnGrown", ("P5S5", "P0S5"), "the prompt on the grown store: P5 against P0 on S5"),
    ("storeUnderP5", ("P5S5", "P5S0"), "the store under the final prompt: S5 against S0 with P5"),
)
COUNTS = ("contradicted", "answersContradicted", "complete", "resultGiven", "pass", "accessUncertain", "citing",
          "noWeb")


# ----------------------------------------------------------------------------------------------- small helpers

jread, maybe, median = B.jread, B.maybe, B.median


def r4(x):
    return None if x is None else round(x, 4)


def parse(name):
    """(restart, prompt k, store k) of an arm name; E0 is (None, 0, 0)."""
    if name == "E0":
        return None, 0, 0
    n, p, s = map(int, ARM.match(name).groups())
    return "R%d" % n, p, s


def slot(prompt, store):
    return "P%dS%d" % (prompt, store)


def gmean(values):
    values = [v for v in values if v]
    return math.exp(statistics.mean(map(math.log, values))) if values else None


def dose(run):
    """The findings and notes an answer's knowledge searches returned, from its trace (`run`: the run folder). Each
    `search_knowledge` access event names its payload, the tool's actual return."""
    findings, notes, first, searches = set(), set(), None, 0
    path = Path(run) / "events.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        event = json.loads(line)
        if event.get("operation") != "knowledge.search_knowledge":
            continue
        searches += 1
        result = (jread(Path(run) / "payloads" / (event["payload_hash"] + ".json")).get("result") or {}) \
            if event.get("status") == "ok" and event.get("payload_hash") else {}
        got = {f["id"] for k in ("reviewed", "added", "unreviewed") for f in result.get(k) or []}
        notes |= {n["id"] for n in result.get("notes") or []}
        if first is None:
            first = len(got)
        findings |= got
    return {"dose": len(findings), "doseFirst": first or 0, "doseNotes": len(notes), "searches": searches}


# ----------------------------------------------------------------------------------------------- the restarts

def restart_info(base, mismatches):
    """A restart's snapshots (fingerprints recomputed), prompt versions, adopted edits and, per snapshot, how many
    findings of each near question's parent tasks it holds."""
    base = Path(base)
    name = base.name
    recorded = jread(base / "snapshots.json")
    tasks = jread(base / "rounds.json")
    qdir = base / "workspace/.oopc/loop/questions"
    completed = {t["taskId"] for t in tasks
                 if (maybe(qdir / t["taskId"] / "question.json") or {}).get("status") == "completed"}
    parents = {}
    for t in tasks:
        if t.get("nearParentOf"):
            family = [t["taskId"]] + [x["taskId"] for x in tasks if x.get("parent") == t["taskId"]]
            parents[t["nearParentOf"]] = {"task": t["taskId"], "number": t["number"], "round": t["round"],
                                          "completed": t["taskId"] in completed, "family": family,
                                          "revisits": {x["revisit"]: x["round"] for x in tasks
                                                       if x.get("parent") == t["taskId"]}}
    snapshots = {"S0": {"findings": 0, "asTaken": recorded.get("S0") == B.fingerprint(None), "parents": {}}}
    for k in range(1, ROUNDS + 1):
        path = B.database(base / "snapshots" / ("S%d" % k))
        found = B.fingerprint(path)
        if found != recorded.get("S%d" % k):
            mismatches.append({"what": "%s S%d fingerprint" % (name, k), "expected": recorded.get("S%d" % k),
                               "got": found})
        db = B.connect(path)
        rows = db.execute("SELECT question_id, status FROM findings").fetchall()
        db.close()
        held = collections.Counter(q for q, status in rows if status != "unsupported")
        snapshots["S%d" % k] = {"findings": len(rows), "fingerprint": found, "asTaken": found == recorded.get("S%d" % k),
                                "parents": {h: sum(held[t] for t in p["family"]) for h, p in parents.items()}}
    snapshots["S0"]["fingerprint"] = recorded.get("S0")
    prompts = {k: B.version((base / "prompts" / ("P%d.txt" % k)).read_text()) for k in range(ROUNDS + 1)}
    adopted = [r for r in range(1, ROUNDS + 1)
               if jread(base / "eval" / ("round-%d" % r) / "dev" / "decision.json").get("adopted")]
    return {"snapshots": snapshots, "prompts": prompts, "adopted": adopted, "parents": parents,
            "recorded": recorded}


# ----------------------------------------------------------------------------------------------- the rows

def load(base=None, restarts=None):
    """One row per answer of the final evaluation, with its check's measures, its dose and, for near questions, whether
    the question's parent is in its store; the restarts' records; the cross-check mismatches."""
    base, rbase = Path(base or FINAL), Path(restarts or BASE)
    mismatches = []
    info = {name: restart_info(rbase / name, mismatches) for name in RESTARTS}
    final = jread(base / "final.json")
    names = [a["name"] for a in final["arms"]]
    heldout = jread(HELDOUT) if HELDOUT.exists() else None
    rows, rechecks, questions = [], [], {}
    shards = sorted(base.glob("shard-*"), key=lambda p: int(p.name.split("-")[1]))
    for shard in shards:
        plan = jread(shard / "plan.json")
        if [a["name"] for a in plan["arms"]] != names:
            mismatches.append({"what": "%s arms" % shard.name, "expected": "final.json's 50 arms in order",
                               "got": [a["name"] for a in plan["arms"]]})
        for arm in plan["arms"]:
            restart, p, s = parse(arm["name"])
            r = restart or RESTARTS[0]
            expected = info[r]["recorded"]["S%d" % s]
            if plan["stores"].get(arm["name"]) != expected:
                mismatches.append({"what": "%s %s store" % (shard.name, arm["name"]), "expected": expected,
                                   "got": plan["stores"].get(arm["name"])})
            version = arm.get("promptVersion") or plan.get("promptVersion")
            if version != info[r]["prompts"][p]:
                mismatches.append({"what": "%s %s prompt" % (shard.name, arm["name"]), "expected": info[r]["prompts"][p],
                                   "got": version})
        for i, q in enumerate(plan["questions"]):
            questions[q["id"]] = {"stratum": q["stratum"], "kind": q["kind"], "shard": shard.name, "index": i}
            for arm in plan["arms"]:
                item = jread(shard / "items" / ("%04d-%s.json" % (i, arm["name"])))
                rows.append(row(shard, arm["name"], q, item, info, mismatches))
                for old in item.get("previousChecks") or []:
                    before = B.check_measures(old)
                    if before:
                        rechecks.append({"question": q["id"], "arm": arm["name"], "first": before,
                                         "second": B.check_measures(item["check"])})
    if heldout is not None and sorted(questions) != sorted(q["id"] for q in heldout):
        mismatches.append({"what": "questions", "expected": "test 1's 60 held-out questions", "got": len(questions)})
    return {"final": final, "arms": names, "rows": rows, "info": info, "questions": questions, "rechecks": rechecks,
            "mismatches": mismatches, "shards": len(shards)}


def row(shard, name, question, item, info, mismatches):
    restart, p, s = parse(name)
    answer, check = item.get("answer") or {}, item.get("check") or {}
    ok = bool(answer) and "error" not in answer and bool(check) and "error" not in check
    measured = B.check_measures(check) if ok else None
    if measured and isinstance(check.get("measures"), dict):
        for k in ("contradicted", "complete", "resultGiven", "pass", "accessUncertain"):
            if check["measures"].get(k) != measured[k]:
                mismatches.append({"what": "%s %s %s measure %s" % (shard.name, name, question["id"][:8], k),
                                   "expected": check["measures"].get(k), "got": measured[k]})
    metrics = answer.get("metrics") or {}
    cited = [c for c in (answer.get("answer") or {}).get("citations") or [] if isinstance(c, str)]
    traced = dose(shard / "workspaces" / name / ".oopc/runs" / answer["runId"]) if answer.get("runId") else \
        {"dose": None, "doseFirst": None, "doseNotes": None, "searches": None}
    if ok and traced["searches"] != metrics.get("knowledgeLookups"):
        mismatches.append({"what": "%s %s %s searches in trace" % (shard.name, name, question["id"][:8]),
                           "expected": metrics.get("knowledgeLookups"), "got": traced["searches"]})
    snap = info[restart or RESTARTS[0]]["snapshots"]["S%d" % s]
    parent = None
    if question["stratum"] == "near":
        parent = {"asked": False, "findings": 0, "inStore": False} if s == 0 else None
        if s:
            p_info = info[restart]["parents"].get(question["id"])
            held = snap["parents"].get(question["id"], 0)
            parent = {"asked": bool(p_info and p_info["round"] <= s and p_info["completed"]), "findings": held,
                      "inStore": held > 0}
    value = {"question": question["id"], "stratum": question["stratum"], "kind": question["kind"], "arm": name,
             "restart": restart, "prompt": p, "store": s, "slot": slot(p, s), "ok": ok,
             "newTokens": metrics.get("newTokens"), "webCalls": metrics.get("webCalls"),
             "seconds": metrics.get("seconds"), "knowledgeLookups": metrics.get("knowledgeLookups"),
             "citations": len(cited), "findingCitations": sum(c.startswith("finding:") for c in cited),
             "storeFindings": snap["findings"], "answeredAt": answer.get("at"), "checkedAt": check.get("at"),
             "rechecked": bool(item.get("previousChecks")), "answeredAgain": bool(item.get("previousAnswers"))}
    value.update(traced)
    value.update({k: (measured or {}).get(k) for k in ("contradicted", "complete", "resultGiven", "pass",
                                                       "accessUncertain", "statements")})
    value["parentAsked"] = parent and parent["asked"]
    value["parentFindings"] = parent and parent["findings"]
    value["parentInStore"] = parent and parent["inStore"]
    return value


# ----------------------------------------------------------------------------------------------- per arm

def counts(rows):
    """Quality counts and costs of a set of answers."""
    rows = [r for r in rows if r["ok"]]
    tokens = [r["newTokens"] for r in rows if r["newTokens"]]
    web = [r["webCalls"] for r in rows if r["webCalls"] is not None]
    cites = sum(r["citations"] for r in rows)
    return {"answers": len(rows), "contradicted": sum(r["contradicted"] for r in rows),
            "answersContradicted": sum(bool(r["contradicted"]) for r in rows),
            "complete": sum(r["complete"] is True for r in rows), "resultGiven": sum(r["resultGiven"] is True for r in rows),
            "pass": sum(r["pass"] is True for r in rows), "accessUncertain": sum(r["accessUncertain"] for r in rows),
            "citing": sum(r["findingCitations"] > 0 for r in rows), "noWeb": sum(r["webCalls"] == 0 for r in rows),
            "findingCitationShare": B.share(sum(r["findingCitations"] for r in rows), cites),
            "medianTokens": median(tokens), "meanTokens": r4(statistics.mean(tokens)) if tokens else None,
            "geometricMeanTokens": r4(gmean(tokens)), "totalTokens": sum(tokens),
            "meanWebCalls": r4(statistics.mean(web)) if web else None, "medianWebCalls": median(web),
            "medianSeconds": median(r["seconds"] for r in rows), "medianDose": median(r["dose"] for r in rows),
            "medianSearches": median(r["searches"] for r in rows)}


def subset(rows, which):
    return rows if which == "all" else [r for r in rows if r["stratum"] == which]


def per_arm(rows, names):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    return {name: {"restart": parse(name)[0], "slot": slot(*parse(name)[1:]),
                   **{s: counts(subset(by[name], s)) for s in SUBSETS}} for name in names}


# ----------------------------------------------------------------------------------------------- paired comparisons

def index(rows):
    """{arm: {question: row}} over answered and checked rows."""
    out = collections.defaultdict(dict)
    for r in rows:
        if r["ok"]:
            out[r["arm"]][r["question"]] = r
    return out


def compare(idx, a, b, qids):
    """`a` against `b` paired per question within one restart: median paired token and time ratios and the mean paired
    web-call difference with bootstrap intervals over questions (test 1's estimators), and both arms' counts."""
    both = [{"a": idx[a][q], "b": idx[b][q]} for q in qids if q in idx[a] and q in idx[b]]
    if a == b:
        same = {"n": len(both), "median": 1.0, "low": 1.0, "high": 1.0}
        return {"tokens": same, "seconds": same, "webCalls": {"n": len(both), "mean": 0.0, "low": 0.0, "high": 0.0},
                "arm": counts([x["a"] for x in both]), "reference": counts([x["b"] for x in both])}
    return {"tokens": analyze.ratio_ci(both, "a", "b", "newTokens"),
            "seconds": analyze.ratio_ci(both, "a", "b", "seconds"),
            "webCalls": analyze.diff_ci(both, "a", "b", "webCalls"),
            "arm": counts([x["a"] for x in both]), "reference": counts([x["b"] for x in both])}


def hier(cells, restarts, qids, stat, back=lambda v: v):
    """`stat` over every (restart, question) cell, with a hierarchical bootstrap interval: each draw takes the restarts
    with replacement, then the questions with replacement (shared across restarts), and pools the drawn cells."""
    values = list(cells.values())
    if len(values) < 3:
        return None
    rng, draws = random.Random(SEED), []
    for _ in range(DRAWS):
        rs, qs = rng.choices(restarts, k=len(restarts)), rng.choices(qids, k=len(qids))
        drawn = [cells[(r, q)] for r in rs for q in qs if (r, q) in cells]
        if drawn:
            draws.append(stat(drawn))
    draws.sort()
    return {"n": len(values), "restarts": len({r for r, _ in cells}), "questions": len({q for _, q in cells}),
            "estimate": round(back(stat(values)), 3), "low": round(back(draws[int(0.025 * len(draws))]), 3),
            "high": round(back(draws[int(0.975 * len(draws))]), 3)}


def pooled(idx, pairs, qids):
    """Across restarts: `pairs` {restart: (arm, reference)}; the median paired token and time ratio and the mean paired
    web-call difference over every (restart, question) pair, each with its hierarchical bootstrap interval."""
    tokens, seconds, web = {}, {}, {}
    for r, (a, b) in pairs.items():
        for q in qids:
            x, y = idx[a].get(q), idx[b].get(q)
            if not x or not y:
                continue
            if x["newTokens"] and y["newTokens"]:
                tokens[(r, q)] = math.log(x["newTokens"] / y["newTokens"])
            if x["seconds"] and y["seconds"]:
                seconds[(r, q)] = math.log(x["seconds"] / y["seconds"])
            if x["webCalls"] is not None and y["webCalls"] is not None:
                web[(r, q)] = x["webCalls"] - y["webCalls"]
    rs = sorted(pairs)
    return {"tokens": hier(tokens, rs, qids, statistics.median, math.exp),
            "tokensGeometricMean": hier(tokens, rs, qids, statistics.mean, math.exp),
            "seconds": hier(seconds, rs, qids, statistics.median, math.exp),
            "webCalls": hier(web, rs, qids, statistics.mean)}


def arm_of(names, restart, prompt, store):
    """The arm that answered `prompt` on `store` in `restart`: E0 for P0 × S0; a prompt equal to P0 is P0's arm."""
    if store == 0 and prompt == 0:
        return "E0"
    name = "%s-P%d-S%d" % (restart, prompt, store)
    if name in names:
        return name
    return "%s-P0-S%d" % (restart, store) if store else None


def system_arm(names, restart, k):
    """The system as it was after round k: P<k> × S<k>, or P0's arm when P<k> equals P0 (not repeated)."""
    return "E0" if k == 0 else arm_of(names, restart, k, k)


def qids_of(questions, which):
    return sorted(q for q, v in questions.items() if which == "all" or v["stratum"] == which)


# ----------------------------------------------------------------------------------------------- curves

def curves(data, idx):
    """Per restart, the growth curve (P0 × S0…S5) and the system curve (P<k> × S<k>), each arm paired against E0 per
    question, by stratum; with each store's findings and the arms' dose. Then, per store, the mean and range of the
    five restarts."""
    names, info, questions = set(data["arms"]), data["info"], data["questions"]
    out = {"growth": {}, "system": {}}
    for kind, pick in (("growth", lambda r, k: arm_of(names, r, 0, k)), ("system", lambda r, k: system_arm(names, r, k))):
        for r in RESTARTS:
            points = []
            for k in range(ROUNDS + 1):
                arm = pick(r, k)
                point = {"store": k, "arm": arm, "findings": info[r]["snapshots"]["S%d" % k]["findings"]}
                for which in SUBSETS:
                    c = compare(idx, arm, "E0", qids_of(questions, which))
                    point[which] = {"tokens": c["tokens"], "webCalls": c["webCalls"], "seconds": c["seconds"],
                                    "counts": c["arm"]}
                points.append(point)
            out[kind][r] = points
    for kind in ("growth", "system"):
        mean = []
        for k in range(ROUNDS + 1):
            pts = [out[kind][r][k] for r in RESTARTS]
            entry = {"store": k, "findings": r4(statistics.mean(p["findings"] for p in pts))}
            for which in SUBSETS:
                logs = [math.log(p[which]["tokens"]["median"]) for p in pts]
                webs = [p[which]["counts"]["meanWebCalls"] for p in pts]
                diffs = [p[which]["webCalls"]["mean"] for p in pts]
                entry[which] = {"tokenRatio": {"mean": r4(math.exp(statistics.mean(logs))), "min": r4(math.exp(min(logs))),
                                               "max": r4(math.exp(max(logs)))},
                                "meanWebCalls": {"mean": r4(statistics.mean(webs)), "min": min(webs), "max": max(webs)},
                                "webDifference": {"mean": r4(statistics.mean(diffs)), "min": min(diffs), "max": max(diffs)},
                                "contradicted": sum(p[which]["counts"]["contradicted"] for p in pts),
                                "complete": sum(p[which]["counts"]["complete"] for p in pts),
                                "resultGiven": sum(p[which]["counts"]["resultGiven"] for p in pts),
                                "pass": sum(p[which]["counts"]["pass"] for p in pts),
                                "citing": sum(p[which]["counts"]["citing"] for p in pts),
                                "noWeb": sum(p[which]["counts"]["noWeb"] for p in pts),
                                "medianDose": median(p[which]["counts"]["medianDose"] for p in pts)}
            mean.append(entry)
        out[kind + "Mean"] = mean
    # pooled over restarts: each snapshot's P0 arm against E0, hierarchical intervals
    out["growthPooled"] = {}
    for k in range(1, ROUNDS + 1):
        out["growthPooled"]["S%d" % k] = {which: pooled(idx, {r: (arm_of(names, r, 0, k), "E0") for r in RESTARTS},
                                                        qids_of(questions, which)) for which in SUBSETS}
    return out


# ----------------------------------------------------------------------------------------------- the crossing

def crossing(data, idx):
    names, questions = set(data["arms"]), data["questions"]
    out = {}
    for key, (a_slot, b_slot), label in COMPARISONS:
        def arm(r, s):
            p, k = int(s[1]), int(s[3])
            return arm_of(names, r, p, k)
        pairs = {r: (arm(r, a_slot), arm(r, b_slot)) for r in RESTARTS}
        entry = {"label": label, "pairs": pairs, "perRestart": {}, "pooled": {}, "quality": {}}
        for which in SUBSETS:
            qids = qids_of(questions, which)
            per = {r: compare(idx, a, b, qids) for r, (a, b) in pairs.items()}
            entry["perRestart"][which] = per
            entry["pooled"][which] = pooled(idx, pairs, qids)
            entry["quality"][which] = {side: {k: sum(per[r][side][k] for r in RESTARTS) for k in COUNTS}
                                       for side in ("arm", "reference")}
        out[key] = entry
    return out


# ----------------------------------------------------------------------------------------------- scaling

def _block(values):
    means = [statistics.mean(c) for c in zip(*values)]
    centred = [[v - m for v, m in zip(row_, means)] for row_ in values]
    k = len(means)
    return [[sum(row_[i] * row_[j] for row_ in centred) for j in range(k)] for i in range(k)]


def within(rows, columns, predictors, label):
    """The within-(restart, question) least-squares coefficients of the first `predictors` columns on the last, with a
    hierarchical bootstrap over restarts, then questions."""
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["restart"], r["question"])].append(columns(r))
    blocks = {k: _block(v) for k, v in by.items() if len(v) >= 2}
    if len(blocks) < 3:
        return None
    found = estimate._solve(list(blocks.values()), predictors)
    restarts, qids = sorted({r for r, _ in blocks}), sorted({q for _, q in blocks})
    rng, draws = random.Random(SEED), []
    for _ in range(DRAWS):
        rs, qs = rng.choices(restarts, k=len(restarts)), rng.choices(qids, k=len(qids))
        chosen = [blocks[(r, q)] for r in rs for q in qs if (r, q) in blocks]
        got = estimate._solve(chosen, predictors) if chosen else None
        if got is not None:
            draws.append(got)
    value = []
    for i in range(predictors):
        column = sorted(d[i] for d in draws)
        value.append({"name": label[i], "estimate": round(found[i], 4), "low": round(column[int(0.025 * len(column))], 4),
                      "high": round(column[int(0.975 * len(column))], 4)})
    return {"blocks": len(blocks), "restarts": len(restarts), "questions": len(qids), "coefficients": value}


def growth_rows(rows):
    """The P0 arms on S1–S5: the growth curve at a fixed prompt, where log findings is defined."""
    return [r for r in rows if r["ok"] and r["restart"] and r["prompt"] == 0 and r["store"] > 0 and r["newTokens"]]


def mixed(rows):
    """log new tokens on log findings with stratum, question and restart crossed random intercepts (MixedLM, REML):
    as the plan writes it, with one slope per stratum, and with log(1 + dose)."""
    data = growth_rows(rows)
    try:
        import numpy, pandas
        import statsmodels.formula.api as smf
    except ImportError as error:
        return {"unavailable": str(error)}
    frame = pandas.DataFrame({"lt": [math.log(r["newTokens"]) for r in data],
                              "lf": [math.log(r["storeFindings"]) for r in data],
                              "ld": [math.log1p(r["dose"]) for r in data], "stratum": [r["stratum"] for r in data],
                              "question": [r["question"] for r in data], "restart": [r["restart"] for r in data]})
    vc = {"question": "0 + C(question)", "restart": "0 + C(restart)"}
    models = {"plan": "lt ~ lf + C(stratum, Treatment('far'))", "byStratum": "lt ~ 0 + C(stratum) + C(stratum):lf",
              "dose": "lt ~ 0 + C(stratum) + C(stratum):ld"}
    out = {"answers": len(frame), "questions": int(frame["question"].nunique()), "restarts": int(frame["restart"].nunique()),
           "rows": "P0 arms on S1–S5 (S0 has no findings)"}
    import warnings
    for name, formula in models.items():
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model = smf.mixedlm(formula, frame, groups=numpy.ones(len(frame)), re_formula="0", vc_formula=vc)
                fit = model.fit(reml=True)
            ci = fit.conf_int()
            coefficients = {}
            for term in fit.fe_params.index:
                label = (term.replace("C(stratum, Treatment('far'))[T.", "stratum ").replace("C(stratum)[", "")
                         .replace("]:lf", " · log findings").replace("]:ld", " · log(1 + dose)").replace("]", "")
                         .replace("lf", "log findings"))
                coefficients[label] = {"estimate": round(float(fit.fe_params[term]), 4),
                                       "low": round(float(ci.loc[term, 0]), 4), "high": round(float(ci.loc[term, 1]), 4)}
            out[name] = {"formula": formula, "coefficients": coefficients,
                         "variance": {"question": round(float(fit.vcomp[list(model.exog_vc.names).index("question")]), 4),
                                      "restart": round(float(fit.vcomp[list(model.exog_vc.names).index("restart")]), 4),
                                      "residual": round(float(fit.scale), 4)},
                         "converged": bool(fit.converged),
                         "warnings": sorted({str(w.message)[:160] for w in caught})}
        except Exception as error:  # a fit that fails is reported, not raised
            out[name] = {"formula": formula, "error": str(error)[:300]}
    return out


def scaling(rows):
    """Within-(restart, question) slopes of log tokens on log findings and on log(1 + dose), per stratum, and per
    restart; the near questions' coverage fit (log findings and the parent in the store together)."""
    data = growth_rows(rows)
    out = {"slope": {}, "doseSlope": {}, "perRestart": {}}
    for s in STRATA:
        mine = [r for r in data if r["stratum"] == s]
        out["slope"][s] = within(mine, lambda r: (math.log(r["storeFindings"]), math.log(r["newTokens"])), 1,
                                 ["log findings"])
        out["doseSlope"][s] = within(mine, lambda r: (math.log1p(r["dose"]), math.log(r["newTokens"])), 1,
                                     ["log(1 + dose)"])
        out["perRestart"][s] = {}
        for r in RESTARTS:  # one restart: estimate.slope's question bootstrap
            these = [dict(x, id=x["question"], answered=True) for x in mine if x["restart"] == r]
            out["perRestart"][s][r] = estimate.slope(these).get(s)
    near = [r for r in data if r["stratum"] == "near"]
    out["coverage"] = within(near, lambda r: (math.log(r["storeFindings"]), float(r["parentInStore"]),
                                              math.log(r["newTokens"])), 2, ["log findings", "parent in store"])
    if out["coverage"]:
        c = out["coverage"]["coefficients"][1]
        out["coverage"]["parentMultiplier"] = {k: round(math.exp(c[k]), 3) for k in ("estimate", "low", "high")}
    return out


# ----------------------------------------------------------------------------------------------- dose and parents

DOSE_BINS = ((0, 0), (1, 9), (10, 19), (20, 29), (30, None))


def bin_label(lo, hi):
    return "%d" % lo if hi == lo else "%d+" % lo if hi is None else "%d–%d" % (lo, hi)


def dose_summary(data, idx):
    """Per stratum and store, the P0 arms' dose (median, zero answers) across restarts; the paired token ratio against
    E0 by dose bin (P0 arms on S1–S5, every stratum), pooled over restarts with hierarchical intervals."""
    rows = [r for r in data["rows"] if r["ok"] and r["prompt"] == 0]
    by_store = {}
    for s in STRATA:
        by_store[s] = {}
        for k in range(ROUNDS + 1):
            these = [r for r in rows if r["stratum"] == s and r["store"] == k]
            by_store[s]["S%d" % k] = {"answers": len(these), "median": median(r["dose"] for r in these),
                                      "zero": sum(r["dose"] == 0 for r in these),
                                      "max": max((r["dose"] for r in these), default=None)}
    bins = []
    e0 = idx["E0"]
    for lo, hi in DOSE_BINS:
        cells, web, n_strata = {}, {}, collections.Counter()
        for r in rows:
            if not r["store"] or r["dose"] < lo or (hi is not None and r["dose"] > hi):
                continue
            ref = e0.get(r["question"])
            if not ref or not ref["newTokens"] or not r["newTokens"]:
                continue
            key = (r["restart"], r["question"], r["store"])
            cells[key] = math.log(r["newTokens"] / ref["newTokens"])
            web[key] = r["webCalls"] - ref["webCalls"]
            n_strata[r["stratum"]] += 1
        bins.append({"bin": bin_label(lo, hi), "answers": len(cells), "byStratum": dict(n_strata),
                     "tokens": hier3(cells, statistics.median, math.exp), "webCalls": hier3(web, statistics.mean)})
    return {"byStore": by_store, "bins": bins,
            "firstSearchMedian": {s: median(r["doseFirst"] for r in rows if r["stratum"] == s and r["store"] == ROUNDS)
                                  for s in STRATA}}


def hier3(cells, stat, back=lambda v: v):
    """`hier` for cells keyed (restart, question, store): a draw takes restarts, then questions, and keeps every store
    of a drawn pair."""
    if len(cells) < 3:
        return None
    grouped = collections.defaultdict(list)
    for (r, q, _), v in cells.items():
        grouped[(r, q)].append(v)
    restarts, qids = sorted({r for r, _ in grouped}), sorted({q for _, q in grouped})
    rng, draws = random.Random(SEED), []
    for _ in range(DRAWS):
        rs, qs = rng.choices(restarts, k=len(restarts)), rng.choices(qids, k=len(qids))
        drawn = [v for r in rs for q in qs for v in grouped.get((r, q), ())]
        if drawn:
            draws.append(stat(drawn))
    draws.sort()
    return {"n": len(cells), "estimate": round(back(stat(list(cells.values()))), 3),
            "low": round(back(draws[int(0.025 * len(draws))]), 3), "high": round(back(draws[int(0.975 * len(draws))]), 3)}


def parent_split(data, idx):
    """Near questions on P0 × S1…S5 against E0, split by whether the question's own campaign parent is in the store:
    per snapshot the number with it, and the median paired token ratio and mean web-call difference with and without,
    pooled over restarts (hierarchical intervals); the ratio of the two groups' medians."""
    rows = [r for r in data["rows"] if r["ok"] and r["prompt"] == 0 and r["store"] and r["stratum"] == "near"]
    e0 = idx["E0"]
    groups = {True: ({}, {}), False: ({}, {})}
    out_e0 = r4(statistics.mean(e0[q]["webCalls"] for q in {r["question"] for r in rows}))
    per_store = {}
    for r in rows:
        ref = e0[r["question"]]
        key = (r["restart"], r["question"], r["store"])
        groups[r["parentInStore"]][0][key] = math.log(r["newTokens"] / ref["newTokens"])
        groups[r["parentInStore"]][1][key] = r["webCalls"] - ref["webCalls"]
    for k in range(1, ROUNDS + 1):
        these = [r for r in rows if r["store"] == k]
        split = {}
        for flag, label in ((True, "with"), (False, "without")):
            tokens = {key: v for key, v in groups[flag][0].items() if key[2] == k}
            web = {key: v for key, v in groups[flag][1].items() if key[2] == k}
            split[label] = {"answers": len(tokens), "tokens": hier3(tokens, statistics.median, math.exp),
                            "webCalls": hier3(web, statistics.mean),
                            "meanWebCalls": r4(statistics.mean(x["webCalls"] for x in these if x["parentInStore"] is flag))
                            if tokens else None}
        per_store["S%d" % k] = {"split": split,
                                "withParent": {r: sum(x["parentInStore"] for x in these if x["restart"] == r)
                                               for r in RESTARTS},
                                "parentAsked": {r: sum(bool(x["parentAsked"]) for x in these if x["restart"] == r)
                                                for r in RESTARTS},
                                "citing": {flag: sum(x["findingCitations"] > 0 for x in these if x["parentInStore"] is flag)
                                           for flag in (True, False)},
                                "answers": {flag: sum(x["parentInStore"] is flag for x in these) for flag in (True, False)}}
    out = {"perStore": per_store, "e0MeanWebCalls": out_e0}
    for flag, label in ((True, "with"), (False, "without")):
        tokens, web = groups[flag]
        out[label] = {"answers": len(tokens), "tokens": hier3(tokens, statistics.median, math.exp),
                      "webCalls": hier3(web, statistics.mean),
                      "citing": sum(r["findingCitations"] > 0 for r in rows if r["parentInStore"] is flag),
                      "noWeb": sum(r["webCalls"] == 0 for r in rows if r["parentInStore"] is flag),
                      "contradicted": sum(r["contradicted"] for r in rows if r["parentInStore"] is flag),
                      "complete": sum(r["complete"] is True for r in rows if r["parentInStore"] is flag),
                      "resultGiven": sum(r["resultGiven"] is True for r in rows if r["parentInStore"] is flag)}
    w, wo = groups[True][0], groups[False][0]
    if len(w) >= 3 and len(wo) >= 3:
        rng, draws = random.Random(SEED), []
        wv, wov = list(w.values()), list(wo.values())
        for _ in range(DRAWS):
            draws.append(statistics.median(rng.choices(wv, k=len(wv))) - statistics.median(rng.choices(wov, k=len(wov))))
        draws.sort()
        out["ratioOfMedians"] = {"estimate": round(math.exp(statistics.median(wv) - statistics.median(wov)), 3),
                                 "low": round(math.exp(draws[int(0.025 * DRAWS)]), 3),
                                 "high": round(math.exp(draws[int(0.975 * DRAWS)]), 3),
                                 "note": "unpaired between groups, resampling answers within each (as estimate.split)"}
    return out


# ----------------------------------------------------------------------------------------------- spread, edits

def spread(cross):
    """Per comparison and stratum, the five restarts' effects (median log token ratio, mean web-call difference):
    whether they share a sign, their mean and range, and whether the range is below the absolute mean."""
    out = {}
    for key in ("knowledge", "prompt", "system", "promptOnGrown"):
        out[key] = {}
        for which in SUBSETS:
            per = cross[key]["perRestart"][which]
            logs = {r: math.log(per[r]["tokens"]["median"]) for r in RESTARTS}
            webs = {r: per[r]["webCalls"]["mean"] for r in RESTARTS}
            entry = {}
            for name, values, back in (("tokens", logs, math.exp), ("webCalls", webs, lambda v: v)):
                vs = list(values.values())
                mean, rng_ = statistics.mean(vs), max(vs) - min(vs)
                entry[name] = {"perRestart": {r: round(back(v), 3) for r, v in values.items()},
                               "mean": round(back(mean), 3), "min": round(back(min(vs)), 3), "max": round(back(max(vs)), 3),
                               "range": round(rng_, 4), "absMean": round(abs(mean), 4),
                               "sameSign": all(v < 0 for v in vs) or all(v > 0 for v in vs),
                               "rangeBelowEffect": rng_ < abs(mean), "scale": "log ratio" if name == "tokens" else "calls"}
            out[key][which] = entry
    return out


def edits(data, idx):
    """Every arm that carries adopted edits against P0 on the same store: contradicted statements (by stratum) and the
    other quality counts; the edits each carries."""
    names, info = set(data["arms"]), data["info"]
    out = []
    for r in RESTARTS:
        adopted = info[r]["adopted"]
        candidates = [("%s-P%d-S%d" % (r, k, k), k, k) for k in range(1, ROUNDS + 1)] + [("%s-P5-S0" % r, 5, 0)]
        for name, p, s in candidates:
            if name not in names:
                continue
            reference = arm_of(names, r, 0, s)
            carried = [k for k in adopted if k <= p]
            entry = {"arm": name, "reference": reference, "restart": r, "store": s,
                     "edits": ["%s r%d" % (r, k) for k in carried], "promptVersion": info[r]["prompts"][p]}
            for which in SUBSETS:
                c = compare(idx, name, reference, qids_of(data["questions"], which))
                entry[which] = {"arm": {k: c["arm"][k] for k in COUNTS}, "reference": {k: c["reference"][k] for k in COUNTS}}
            entry["excess"] = entry["all"]["arm"]["contradicted"] - entry["all"]["reference"]["contradicted"]
            out.append(entry)
    return out


def edit_alone(ed):
    """Each restart's first adopted edit on its own: the arms that carry it and no other, against P0 on their stores."""
    out = {}
    for r in RESTARTS:
        mine = [e for e in ed if e["restart"] == r and e["edits"]]
        if not mine:
            continue
        first = min(mine, key=lambda e: len(e["edits"]))["edits"][:1]
        only = [e for e in mine if e["edits"] == first]
        out[first[0]] = {"arms": len(only), "arm": sum(e["all"]["arm"]["contradicted"] for e in only),
                         "reference": sum(e["all"]["reference"]["contradicted"] for e in only),
                         "names": [e["arm"] for e in only]}
    return out


def contradicted_statements(base, data):
    """Every contradicted statement of the final evaluation (read from the items again, read only), with its arm,
    stratum, kind and category, and whether its answer cited a saved finding or used the web."""
    base = Path(base or FINAL)
    rows = {(r["question"], r["arm"]): r for r in data["rows"]}
    out = []
    for qid, q in sorted(data["questions"].items(), key=lambda kv: (kv[1]["shard"], kv[1]["index"])):
        shard = base / q["shard"]
        for name in data["arms"]:
            item = jread(shard / "items" / ("%04d-%s.json" % (q["index"], name)))
            for s in (item.get("check") or {}).get("statements") or []:
                if s.get("verdict") == "unsupported" and s.get("category") != "source-access":
                    r = rows[(qid, name)]
                    out.append({"arm": name, "stratum": q["stratum"], "kind": s.get("kind"),
                                "category": s.get("category"), "citesSaved": r["findingCitations"] > 0,
                                "webCalls": r["webCalls"], "statement": B.trim(s.get("statement"), 300),
                                "reason": B.trim(s.get("reason"), 300)})
    return out


def recheck_agreement(rechecks):
    """Answers checked twice in the final evaluation (a question whose check failed for good on one arm is checked
    again, all its arms together): how often the two checks agree."""
    pairs = [x for x in rechecks if x["second"]]
    agree = {k: sum(x["first"][k] == x["second"][k] for x in pairs) for k in ("contradicted", "complete", "resultGiven",
                                                                             "pass")}
    return {"answers": len(pairs), "agree": agree,
            "contradicted": [sum(x["first"]["contradicted"] for x in pairs), sum(x["second"]["contradicted"] for x in pairs)],
            "passes": [sum(x["first"]["pass"] for x in pairs), sum(x["second"]["pass"] for x in pairs)]}


# ----------------------------------------------------------------------------------------------- predictions

def part(text, met, numbers):
    return {"part": text, "met": met, "numbers": numbers}


def judge(parts):
    flags = [p["met"] for p in parts if p["met"] is not None]
    if not flags:
        return "not judged"
    return "met" if all(flags) else "not met" if not any(flags) else "partly met"


def below(ci, at):
    return ci is not None and ci["high"] < at


def contains(ci, at):
    return ci is not None and ci["low"] <= at <= ci["high"]


def num(x, places=2):
    """A number with a true minus sign; a value that rounds to zero is written without one."""
    x = 0.0 if round(x, places) == 0 else x
    return ("%.*f" % (places, x)).replace("-", "−")


def ci(v, places=2):
    """A ratio or difference with its interval: "0.52 (0.41–0.57)", "−5.4 (−7.2 to −3.6)"."""
    if not v or "low" not in v:
        return "–"
    centre = v.get("median", v.get("mean", v.get("estimate")))
    return "%s (%s%s%s)" % (num(centre, places), num(v["low"], places), " to " if v["low"] < 0 else "–",
                            num(v["high"], places))


def predictions(value):
    cross, arms, ed, sp = value["crossing"], value["arms"], value["edits"], value["spread"]
    out = []

    def add(pid, statement, parts, rule, note=None):
        out.append({"id": pid, "prediction": statement, "rule": rule, "parts": parts, "verdict": judge(parts),
                    "note": note})

    know = cross["knowledge"]["perRestart"]
    near_falls = {r: below(know["near"][r]["tokens"], 1) and below(know["near"][r]["webCalls"], 0) for r in RESTARTS}
    far_flat = {r: contains(know["far"][r]["tokens"], 1) and contains(know["far"][r]["webCalls"], 0) for r in RESTARTS}
    p0_arms = ["E0"] + ["%s-P0-S%d" % (r, k) for r in RESTARTS for k in range(1, ROUNDS + 1)]
    cells = {(a, s): arms[a][s]["contradicted"] for a in p0_arms for s in STRATA}
    over = sorted("%s %s %d" % (a, s, v) for (a, s), v in cells.items() if v > 1)
    by_store = {k: sum(cells[(a, s)] for a in p0_arms for s in STRATA if (a == "E0") == (k == 0)
                       and (a == "E0" or a.endswith("S%d" % k))) for k in range(ROUNDS + 1)}
    add("2", "Knowledge alone (P0 across S0 to S5): on near questions, tokens and web calls fall as the store grows in "
        "every restart; on far questions they stay flat. Contradicted statements do not rise with store size (at most "
        "one per arm per stratum, as in test 1).", [
            part("Near: P0S5/E0 token ratio below 1 and web-call difference below 0 (intervals) in every restart",
                 all(near_falls.values()),
                 "; ".join("%s tokens %s, web %s" % (r, ci(know["near"][r]["tokens"]), ci(know["near"][r]["webCalls"], 1))
                           for r in RESTARTS) + " (falls in %d of 5)" % sum(near_falls.values())),
            part("Far: both intervals include no change in every restart", all(far_flat.values()),
                 "; ".join("%s tokens %s, web %s" % (r, ci(know["far"][r]["tokens"]), ci(know["far"][r]["webCalls"], 1))
                           for r in RESTARTS) + " (flat in %d of 5)" % sum(far_flat.values())),
            part("Every P0 arm at most one contradicted statement per stratum (26 arms × 3 strata)", not over,
                 "cells above one: %s; contradicted by store, five restarts summed (E0 once): %s" % (
                     ", ".join(over) or "none", ", ".join("S%d %d" % kv for kv in by_store.items())))],
        "Analyst's rule, 2026-10-21, before any number was computed (module docstring).",
        note="Without E0, the within-question slope of log tokens on log findings over S1–S5 is negative in every "
             "restart on near questions (%s) and near zero on far questions (%s)." % (
                 ", ".join("%s %s" % (r, ci(value["scaling"]["perRestart"]["near"][r], 2)) for r in RESTARTS),
                 ", ".join("%s %s" % (r, ci(value["scaling"]["perRestart"]["far"][r], 2)) for r in RESTARTS)))

    prompt = cross["prompt"]["perRestart"]["all"]
    know_all = know["all"]
    tok = {r: abs(math.log(prompt[r]["tokens"]["median"])) < abs(math.log(know_all[r]["tokens"]["median"]))
           for r in RESTARTS}
    web = {r: abs(prompt[r]["webCalls"]["mean"]) < abs(know_all[r]["webCalls"]["mean"]) for r in RESTARTS}
    pp = cross["prompt"]["pooled"]["all"]
    add("3", "The prompt alone (P5 against P0 on S0): adopted edits change cost less than the store does. Test 2 found "
        "the final prompt equal on tokens, with about one fewer web call per answer.", [
            part("Tokens: the prompt's effect smaller than the store's in every restart (all 60 questions)",
                 all(tok.values()), "; ".join("%s P5S0/E0 %s against P0S5/E0 %s" % (
                     r, num(prompt[r]["tokens"]["median"]), num(know_all[r]["tokens"]["median"])) for r in RESTARTS)
                 + " (smaller in %d of 5)" % sum(tok.values())),
            part("Web calls: the prompt's effect smaller than the store's in every restart", all(web.values()),
                 "; ".join("%s %s against %s" % (r, num(prompt[r]["webCalls"]["mean"], 1),
                                                   num(know_all[r]["webCalls"]["mean"], 1)) for r in RESTARTS)
                 + " (smaller in %d of 5)" % sum(web.values()))],
        "Analyst's rule, 2026-10-21, before any number was computed (module docstring).",
        note="Pooled over restarts, the prompt alone: tokens %s, web calls %s; the store alone: tokens %s, web calls "
             "%s. On near questions, the prompt alone %s and %s against the store's %s and %s. The five P5 × S0 arms "
             "gave a sourced result in %s of 60 answers, against E0's %d." % (
                 ci(pp["tokens"]), ci(pp["webCalls"], 1), ci(cross["knowledge"]["pooled"]["all"]["tokens"]),
                 ci(cross["knowledge"]["pooled"]["all"]["webCalls"], 1), ci(cross["prompt"]["pooled"]["near"]["tokens"]),
                 ci(cross["prompt"]["pooled"]["near"]["webCalls"], 1), ci(cross["knowledge"]["pooled"]["near"]["tokens"]),
                 ci(cross["knowledge"]["pooled"]["near"]["webCalls"], 1),
                 ", ".join(str(prompt[r]["arm"]["resultGiven"]) for r in RESTARTS),
                 arms["E0"]["all"]["resultGiven"]))

    worst = max(e["excess"] for e in ed)
    raised = ["%s %d vs %s %d" % (e["arm"], e["all"]["arm"]["contradicted"], e["reference"],
                                   e["all"]["reference"]["contradicted"]) for e in ed if e["excess"] > 0]
    totals = [sum(e["all"]["arm"]["contradicted"] for e in ed), sum(e["all"]["reference"]["contradicted"] for e in ed)]
    alone = edit_alone(ed)
    out.append({"id": "4-heldout", "prediction": "No adopted edit raises contradicted statements on the held-out "
                "questions.", "rule": "Analyst's rule, 2026-10-21, before any number was computed: met if no arm "
                "carrying adopted edits has more contradicted statements than P0 on its store; partly met if each "
                "excess is one statement; not met if any is two or more.",
                "parts": [part("No arm carrying adopted edits has more contradicted statements than P0 on its store "
                               "(%d arms)" % len(ed), worst <= 0,
                               "more: %s; largest excess %s" % (", ".join(raised) or "none", "%+d" % worst))],
                "verdict": "met" if worst <= 0 else "partly met" if worst == 1 else "not met",
                "note": "Summed over the %d arms, %d contradicted statements against %d for P0 on the same stores; "
                        "each restart's first adopted edit alone (the arms carrying only it): %s." % (
                            len(ed), totals[0], totals[1], "; ".join(
                                "%s %d vs %d (%d arm%s)" % (k, v["arm"], v["reference"], v["arms"],
                                                            "" if v["arms"] == 1 else "s")
                                for k, v in alone.items()))})

    s5 = sp["knowledge"]["near"]
    add("5", "The store effect points the same way in all five restarts, and its spread across restarts is smaller "
        "than the effect itself.", [
            part("Near tokens (P0S5/E0): one sign in all five", s5["tokens"]["sameSign"],
                 ", ".join("%s %s" % (r, num(v)) for r, v in s5["tokens"]["perRestart"].items())),
            part("Near tokens: range below the effect (log scale)", s5["tokens"]["rangeBelowEffect"],
                 "range %s against |mean| %s (mean ratio %s, %s–%s)" % (
                     num(s5["tokens"]["range"], 3), num(s5["tokens"]["absMean"], 3), num(s5["tokens"]["mean"]),
                     num(s5["tokens"]["min"]), num(s5["tokens"]["max"]))),
            part("Near web calls (P0S5 − E0): one sign in all five", s5["webCalls"]["sameSign"],
                 ", ".join("%s %s" % (r, num(v, 1)) for r, v in s5["webCalls"]["perRestart"].items())),
            part("Near web calls: range below the effect", s5["webCalls"]["rangeBelowEffect"],
                 "range %s against |mean| %s" % (num(s5["webCalls"]["range"], 1), num(s5["webCalls"]["absMean"], 1)))],
        "Analyst's rule, 2026-10-21, before any number was computed (module docstring).")
    return out


# ----------------------------------------------------------------------------------------------- build

def build(base=None, restarts=None):
    data = load(base, restarts)
    idx = index(data["rows"])
    value = {"arms": per_arm(data["rows"], data["arms"])}
    value["curves"] = curves(data, idx)
    value["crossing"] = crossing(data, idx)
    value["edits"] = edits(data, idx)
    value["spread"] = spread(value["crossing"])
    value["mixedModel"] = mixed(data["rows"])
    value["scaling"] = scaling(data["rows"])
    value["dose"] = dose_summary(data, idx)
    value["parents"] = parent_split(data, idx)
    value["predictions"] = predictions(value)
    value["rechecks"] = recheck_agreement(data["rechecks"])
    statements = contradicted_statements(base, data)
    value["contradicted"] = {"total": len(statements),
                             "byKind": dict(collections.Counter("%s/%s" % (s["kind"], s["category"]) for s in statements)),
                             "inAnswersCitingSaved": sum(s["citesSaved"] for s in statements),
                             "inAnswersWithoutWeb": sum(s["webCalls"] == 0 for s in statements),
                             "answersCitingSaved": sum(r["ok"] and r["findingCitations"] > 0 for r in data["rows"]),
                             "answersWithoutWeb": sum(r["ok"] and r["webCalls"] == 0 for r in data["rows"]),
                             "statements": statements}
    e0 = value["arms"]["E0"]
    p0 = ["%s-P0-S%d" % (r, k) for r in RESTARTS for k in range(1, ROUNDS + 1)]
    value["reference"] = {s: {"e0MeanWebCalls": e0[s]["meanWebCalls"], "e0MedianTokens": e0[s]["medianTokens"],
                              "p0MeanWebCalls": [min(value["arms"][a][s]["meanWebCalls"] for a in p0),
                                                 max(value["arms"][a][s]["meanWebCalls"] for a in p0)],
                              "p0MedianTokens": [min(value["arms"][a][s]["medianTokens"] for a in p0),
                                                 max(value["arms"][a][s]["medianTokens"] for a in p0)]}
                          for s in SUBSETS}
    rows = data["rows"]
    final = data["final"]
    code = Path(B.knowledge.__file__).resolve()
    value["meta"] = {
        "builder": "studies/macromolecules/recursive/final_results.py", "analysisRevision": B.git_revision(HERE.parent),
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "records": ".oopc/loop/harness/2026-10-restarts/final (shard-1..10) and R1..R5 (read only)",
        "codeImported": "freeze-2 (tag study-freeze-2)" if code.is_relative_to(FREEZE2) else "not freeze-2",
        "doseSource": "the researcher's recorded search_knowledge returns in each answer's trace (no replay)",
        "pins": {"tag": final.get("tag"), "code": (final.get("provenance") or {}).get("code"),
                 "harness": (final.get("provenance") or {}).get("harness"), "preparedAt": final.get("at"),
                 "shards": final.get("shards"), "questions": final.get("questions"),
                 "promptP0": data["info"]["R1"]["prompts"][0],
                 "restarts": {r: {"snapshots": {k: v.get("fingerprint") for k, v in i["snapshots"].items()},
                                  "prompts": {"P%d" % k: v for k, v in i["prompts"].items()},
                                  "adoptedRounds": i["adopted"]} for r, i in data["info"].items()}},
        "answers": len(rows), "answeredAndChecked": sum(r["ok"] for r in rows), "arms": len(data["arms"]),
        "rechecked": sum(r["rechecked"] for r in rows), "answeredAgain": sum(r["answeredAgain"] for r in rows),
        "window": {"firstAnswer": min(r["answeredAt"] for r in rows if r["answeredAt"]),
                   "lastCheck": max(r["checkedAt"] for r in rows if r["checkedAt"])},
        "strata": dict(collections.Counter(v["stratum"] for v in data["questions"].values()))}
    plans = [jread(p / "plan.json") for p in sorted(Path(base or FINAL).glob("shard-*"))]
    value["meta"]["pins"].update(models=plans[0].get("models"), checker=plans[0].get("checker"))
    value["parentsByRestart"] = {r: {h: {k: p[k] for k in ("number", "round", "completed", "revisits")}
                                     for h, p in i["parents"].items()} for r, i in data["info"].items()}
    value["crossChecks"] = {"mismatches": data["mismatches"], "count": len(data["mismatches"])}
    value["rows"] = [{k: r[k] for k in ("question", "stratum", "arm", "restart", "prompt", "store", "newTokens", "webCalls",
                                        "seconds", "contradicted", "complete", "resultGiven", "pass", "accessUncertain",
                                        "findingCitations", "dose", "doseFirst", "searches", "storeFindings",
                                        "parentInStore")} for r in rows]
    return value


# ----------------------------------------------------------------------------------------------- report

def k1(v):
    return "–" if v is None else "%.1f" % (v / 1000)


def opt(v, places=2):
    return "–" if v is None else num(v, places)


def nmf(arms, name, key):
    return "/".join(str(arms[name][s][key]) for s in STRATA)


def markdown(v):
    out = []
    w = out.append
    meta, arms, cross, cur = v["meta"], v["arms"], v["crossing"], v["curves"]
    pins = meta["pins"]
    w("# Part B performance: the final evaluation of the five restarts")
    w("")
    w("Built %s by `%s` at `%s` from `.oopc/loop/harness/2026-10-restarts/final/` and `R1`–`R5` (read only; no engine, "
      "no network). Evaluation prepared %s from harness `%s` on tag `study-freeze-2` (`%s`); %d arms × %d held-out "
      "questions (near/mid/far %s) = %d answers, %d answered and checked, %d shards; checker %s (%s). First answer %s, "
      "last check %s. Each question's 50 arms were answered in turn and checked together. Dose: %s. Cross-check "
      "mismatches: %d." % (
          meta["builtAt"], meta["builder"], meta["analysisRevision"], pins["preparedAt"][:16].replace("T", " "),
          (pins["harness"] or "")[:7], (pins["code"] or "")[:7], meta["arms"], pins["questions"],
          "/".join(str(meta["strata"].get(s, 0)) for s in STRATA), meta["answers"], meta["answeredAndChecked"],
          pins["shards"], pins["checker"], ", ".join("%s %s" % kv for kv in (pins["models"] or {}).items()),
          meta["window"]["firstAnswer"][:16].replace("T", " "), meta["window"]["lastCheck"][:16].replace("T", " "),
          meta["doseSource"], v["crossChecks"]["count"]))
    w("")
    w("Contradicted statements are statements the checker found unsupported for a reason other than source access "
      "(an unsupported completeness statement counts, as freeze-2 counts it); complete: the completeness statement "
      "supported; sourced: a result reported from a source. Tokens are the answer's new tokens; web calls per answer. "
      "Ratios are medians of per-question paired ratios; web-call differences are means of paired differences; "
      "intervals are bootstrap 95% (over questions within a restart; over restarts, then questions, when pooled).")
    w("")
    # ---- the crossing
    w("## The crossing")
    w("")
    w("Pooled over the five restarts (every restart × question pair; hierarchical bootstrap), all 60 questions, then "
      "near, mid and far. Quality counts summed over the five restarts (300 answers per arm side, 100 per stratum; "
      "E0's 60 answers count once per restart).")
    w("")
    w("| Comparison | Questions | Tokens | Web calls | Time | Contradicted | Complete | Sourced | Passes |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for key, _, _ in COMPARISONS:
        c = cross[key]
        for which in SUBSETS:
            p, q = c["pooled"][which], c["quality"][which]
            w("| %s | %s | %s | %s | %s | %d vs %d | %d vs %d | %d vs %d | %d vs %d |" % (
                c["label"] if which == "all" else "", which, ci(p["tokens"]), ci(p["webCalls"], 1), ci(p["seconds"]),
                q["arm"]["contradicted"], q["reference"]["contradicted"], q["arm"]["complete"], q["reference"]["complete"],
                q["arm"]["resultGiven"], q["reference"]["resultGiven"], q["arm"]["pass"], q["reference"]["pass"]))
    w("")
    w("Per restart (all 60 questions; question bootstrap within the restart):")
    w("")
    w("| Comparison | " + " | ".join(RESTARTS) + " |")
    w("| --- |" + " --- |" * len(RESTARTS))
    for key, _, _ in COMPARISONS:
        per = cross[key]["perRestart"]["all"]
        w("| %s, tokens | %s |" % (key, " | ".join(ci(per[r]["tokens"]) for r in RESTARTS)))
        w("| %s, web calls | %s |" % (key, " | ".join(ci(per[r]["webCalls"], 1) for r in RESTARTS)))
        w("| %s, contradicted / complete / sourced / passes | %s |" % (key, " | ".join(
            "%d/%d/%d/%d vs %d/%d/%d/%d" % (per[r]["arm"]["contradicted"], per[r]["arm"]["complete"],
                                            per[r]["arm"]["resultGiven"], per[r]["arm"]["pass"],
                                            per[r]["reference"]["contradicted"], per[r]["reference"]["complete"],
                                            per[r]["reference"]["resultGiven"], per[r]["reference"]["pass"])
            for r in RESTARTS)))
    w("")
    w("Near questions per restart, knowledge alone (P0S5 vs E0): %s." % "; ".join(
        "%s tokens %s, web %s" % (r, ci(cross["knowledge"]["perRestart"]["near"][r]["tokens"]),
                                  ci(cross["knowledge"]["perRestart"]["near"][r]["webCalls"], 1)) for r in RESTARTS))
    w("")
    # ---- growth curves
    w("## The growth curve: P0 × S0…S5")
    w("")
    w("Per restart and stratum, each snapshot's P0 arm against E0 (S0): median paired token ratio · mean web calls per "
      "answer (E0: %s near, %s mid, %s far) at S1·S2·S3·S4·S5. Findings in the store beside the restart." % tuple(
          num(arms["E0"][s]["meanWebCalls"], 1) for s in STRATA))
    w("")
    w("| Restart | Findings S1…S5 | Near tokens | Near web | Mid tokens | Mid web | Far tokens | Far web |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in RESTARTS:
        pts = cur["growth"][r][1:]
        w("| %s | %s | %s |" % (r, "·".join("{:,}".format(p["findings"]) for p in pts), " | ".join(
            "%s | %s" % ("·".join(num(p[s]["tokens"]["median"]) for p in pts),
                         "·".join(num(p[s]["counts"]["meanWebCalls"], 1) for p in pts)) for s in STRATA)))
    gm = cur["growthMean"][1:]
    w("| mean of the five | %s | %s |" % ("·".join("{:,.0f}".format(p["findings"]) for p in gm), " | ".join(
        "%s | %s" % ("·".join(num(p[s]["tokenRatio"]["mean"]) for p in gm),
                     "·".join(num(p[s]["meanWebCalls"]["mean"], 1) for p in gm)) for s in STRATA)))
    w("")
    w("Token ratios of the mean row are geometric means of the five restarts' medians. Pooled over restarts (median over "
      "every restart × question pair, hierarchical intervals; then the geometric mean of the paired ratios):")
    w("")
    for s in STRATA:
        w("- %s: %s." % (s, "; ".join(
            "S%d tokens %s [geometric mean %s], web %s" % (
                k, ci(cur["growthPooled"]["S%d" % k][s]["tokens"]),
                num(cur["growthPooled"]["S%d" % k][s]["tokensGeometricMean"]["estimate"]),
                ci(cur["growthPooled"]["S%d" % k][s]["webCalls"], 1)) for k in range(1, ROUNDS + 1))))
    w("")
    w("Quality along the growth curve, five restarts summed (300 answers per store, 100 per stratum; the S0 row is E0's "
      "60 answers counted five times).")
    w("")
    w("| Store | Contradicted n/m/f | Complete | Sourced | Passes | Citing a saved finding | No web | Median dose n/m/f |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in cur["growthMean"]:
        w("| S%d%s | %s | %d | %d | %d | %d | %d | %s |" % (
            p["store"], " (E0 ×5)" if p["store"] == 0 else "", "/".join(str(p[s]["contradicted"]) for s in STRATA),
            p["all"]["complete"], p["all"]["resultGiven"], p["all"]["pass"], p["all"]["citing"], p["all"]["noWeb"],
            "/".join(opt(p[s]["medianDose"], 0) for s in STRATA)))
    w("")
    # ---- system curve
    w("## The system curve: P<k> × S<k>")
    w("")
    w("The arm as each restart actually was after round k (P0's arm where P<k> = P0), against E0: median paired token "
      "ratio · mean web calls at S1…S5, all 60 questions and near.")
    w("")
    w("| Restart | All tokens | All web | Near tokens | Near web | Contradicted S1…S5 |")
    w("| --- | --- | --- | --- | --- | --- |")
    for r in RESTARTS:
        pts = cur["system"][r][1:]
        w("| %s | %s | %s | %s | %s | %s |" % (
            r, "·".join(num(p["all"]["tokens"]["median"]) for p in pts),
            "·".join(num(p["all"]["counts"]["meanWebCalls"], 1) for p in pts),
            "·".join(num(p["near"]["tokens"]["median"]) for p in pts),
            "·".join(num(p["near"]["counts"]["meanWebCalls"], 1) for p in pts),
            "·".join(str(p["all"]["counts"]["contradicted"]) for p in pts)))
    w("")
    # ---- mixed model and slopes
    mm, sc = v["mixedModel"], v["scaling"]
    w("## Scaling with the store")
    w("")
    if "plan" in mm and "coefficients" in mm["plan"]:
        w("Mixed model on %d answers (%s; %d questions, %d restarts), REML, question and restart as crossed random "
          "intercepts, Wald 95%% intervals:" % (mm["answers"], mm["rows"], mm["questions"], mm["restarts"]))
        w("")
        for name in ("plan", "byStratum", "dose"):
            m = mm[name]
            if "coefficients" not in m:
                w("- `%s`: %s" % (m["formula"], m.get("error")))
                continue
            w("- `%s`: %s; variance question %s, restart %s, residual %s%s." % (
                m["formula"], "; ".join("%s %s" % (k, ci(c, 3)) for k, c in m["coefficients"].items()),
                num(m["variance"]["question"], 3), num(m["variance"]["restart"], 4), num(m["variance"]["residual"], 3),
                "" if m["converged"] else " (did not converge)"))
    else:
        w("Mixed model: %s" % mm)
    w("")
    w("Within-(restart, question) slope of log tokens on log findings, hierarchical bootstrap: %s. On log(1 + dose): %s." % (
        "; ".join("%s %s" % (s, ci(sc["slope"][s]["coefficients"][0], 3)) for s in STRATA),
        "; ".join("%s %s" % (s, ci(sc["doseSlope"][s]["coefficients"][0], 3)) for s in STRATA)))
    w("Per restart (question bootstrap), near: %s; far: %s." % (
        ", ".join("%s %s" % (r, ci(sc["perRestart"]["near"][r], 3)) for r in RESTARTS),
        ", ".join("%s %s" % (r, ci(sc["perRestart"]["far"][r], 3)) for r in RESTARTS)))
    if sc.get("coverage"):
        c = sc["coverage"]
        w("Near coverage fit (log findings and parent in store together, within restart × question): log findings %s; "
          "parent in store ×%s (%s–%s)." % (ci(c["coefficients"][0], 3), num(c["parentMultiplier"]["estimate"]),
                                           num(c["parentMultiplier"]["low"]), num(c["parentMultiplier"]["high"])))
    w("")
    # ---- dose
    d = v["dose"]
    w("## Dose: the findings the researcher's searches returned")
    w("")
    w("Median distinct findings returned per answer (P0 arms; answers with none) by store:")
    w("")
    w("| Stratum | " + " | ".join("S%d" % k for k in range(ROUNDS + 1)) + " |")
    w("| --- |" + " --- |" * (ROUNDS + 1))
    for s in STRATA:
        w("| %s | %s |" % (s, " | ".join("%s (%d of %d none)" % (opt(d["byStore"][s]["S%d" % k]["median"], 0),
                                                                  d["byStore"][s]["S%d" % k]["zero"],
                                                                  d["byStore"][s]["S%d" % k]["answers"])
                                        for k in range(ROUNDS + 1))))
    w("")
    w("P0 arms on S1–S5 against E0 by dose, pooled over strata and restarts (hierarchical bootstrap):")
    w("")
    w("| Dose | Answers (near/mid/far) | Tokens | Web calls |")
    w("| --- | --- | --- | --- |")
    for b in d["bins"]:
        w("| %s | %d (%s) | %s | %s |" % (b["bin"], b["answers"], "/".join(str(b["byStratum"].get(s, 0)) for s in STRATA),
                                         ci(b["tokens"]), ci(b["webCalls"], 1)))
    w("")
    # ---- parents
    pa = v["parents"]
    w("## Near questions: is the question's own parent in the store?")
    w("")
    w("Near questions whose campaign parent (asked by every restart in its campaign wording, 4 per round) has a finding "
      "in the store, per restart at S1…S5: %s." % "; ".join(
          "%s %s" % (r, "·".join(str(pa["perStore"]["S%d" % k]["withParent"][r]) for k in range(1, ROUNDS + 1)))
          for r in RESTARTS))
    w("")
    w("| Near, P0 × S1–S5 vs E0 | Answers | Tokens | Web calls | Citing a finding | No web | Contradicted | Complete | Sourced |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for label in ("with", "without"):
        g = pa[label]
        w("| parent %s | %d | %s | %s | %d | %d | %d | %d | %d |" % (
            "in the store" if label == "with" else "not in the store", g["answers"], ci(g["tokens"]), ci(g["webCalls"], 1),
            g["citing"], g["noWeb"], g["contradicted"], g["complete"], g["resultGiven"]))
    if pa.get("ratioOfMedians"):
        w("")
        w("Ratio of the two groups' median token ratios: %s (unpaired)." % ci(pa["ratioOfMedians"]))
    w("")
    w("By snapshot (pooled over restarts, answers in brackets): median paired token ratio · mean paired web-call "
      "difference against E0, parent in the store / not: %s." % "; ".join(
          "S%d %s · %s (%d) / %s · %s (%d)" % (
              k, opt((pa["perStore"]["S%d" % k]["split"]["with"]["tokens"] or {}).get("estimate")),
              opt((pa["perStore"]["S%d" % k]["split"]["with"]["webCalls"] or {}).get("estimate"), 1),
              pa["perStore"]["S%d" % k]["split"]["with"]["answers"],
              opt((pa["perStore"]["S%d" % k]["split"]["without"]["tokens"] or {}).get("estimate")),
              opt((pa["perStore"]["S%d" % k]["split"]["without"]["webCalls"] or {}).get("estimate"), 1),
              pa["perStore"]["S%d" % k]["split"]["without"]["answers"]) for k in range(1, ROUNDS + 1)))
    w("")
    # ---- spread
    sp = v["spread"]
    w("## Spread across restarts against the size of the effect")
    w("")
    w("| Effect | Questions | Tokens per restart | Mean (range) | Range < effect | Web per restart | Mean (range) | Range < effect |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for key in ("knowledge", "prompt", "system", "promptOnGrown"):
        for which in SUBSETS:
            t, wb = sp[key][which]["tokens"], sp[key][which]["webCalls"]
            w("| %s | %s | %s | %s (%s–%s) | %s | %s | %s (%s to %s) | %s |" % (
                key if which == "all" else "", which, "·".join(num(x) for x in t["perRestart"].values()), num(t["mean"]),
                num(t["min"]), num(t["max"]), "yes" if t["rangeBelowEffect"] else "no",
                "·".join(num(x, 1) for x in wb["perRestart"].values()), num(wb["mean"], 1), num(wb["min"], 1),
                num(wb["max"], 1), "yes" if wb["rangeBelowEffect"] else "no"))
    w("")
    # ---- edits
    w("## Arms carrying adopted edits against P0 on the same store")
    w("")
    w("| Arm | Edits carried | Against | Contradicted n/m/f | Complete | Sourced | Passes |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for e in v["edits"]:
        w("| %s | %s | %s | %s vs %s | %d vs %d | %d vs %d | %d vs %d |" % (
            e["arm"], ", ".join(e["edits"]), e["reference"],
            "/".join(str(e[s]["arm"]["contradicted"]) for s in STRATA),
            "/".join(str(e[s]["reference"]["contradicted"]) for s in STRATA),
            e["all"]["arm"]["complete"], e["all"]["reference"]["complete"], e["all"]["arm"]["resultGiven"],
            e["all"]["reference"]["resultGiven"], e["all"]["arm"]["pass"], e["all"]["reference"]["pass"]))
    w("")
    # ---- per arm
    w("## Every arm")
    w("")
    w("| Arm | Contradicted n/m/f | Complete | Sourced | Passes | Access-uncertain | Median tokens (k) | Mean web calls | "
      "No web | Median seconds | Citing | Median dose |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, a in arms.items():
        x = a["all"]
        w("| %s | %s | %d | %d | %d | %d | %s | %s | %d | %s | %d | %s |" % (
            name, nmf(arms, name, "contradicted"), x["complete"], x["resultGiven"], x["pass"], x["accessUncertain"],
            k1(x["medianTokens"]), opt(x["meanWebCalls"], 1), x["noWeb"], opt(x["medianSeconds"], 0), x["citing"],
            opt(x["medianDose"], 0)))
    w("")
    # ---- predictions
    w("## Against the predictions")
    w("")
    for p in v["predictions"]:
        w("**Prediction %s, %s.** %s" % (p["id"].replace("-heldout", " (held-out half)"), p["verdict"], p["prediction"]))
        w("")
        for x in p["parts"]:
            w("- %s: %s. %s." % (x["part"], "yes" if x["met"] else "no", x["numbers"]))
        if p.get("note"):
            w("- %s" % p["note"])
        w("- Rule: %s" % p["rule"])
        w("")
    # ---- detection and notes
    rc = v["rechecks"]
    widths = {}
    for which in SUBSETS:  # the factor high/low of the per-restart token intervals, median over comparisons and restarts
        spans = [c["perRestart"][which][r]["tokens"]["high"] / c["perRestart"][which][r]["tokens"]["low"]
                 for c in cross.values() for r in RESTARTS]
        pooled_spans = [c["pooled"][which]["tokens"]["high"] / c["pooled"][which]["tokens"]["low"] for c in cross.values()]
        widths[which] = (statistics.median(spans), statistics.median(pooled_spans))
    contra = [a["all"]["contradicted"] for a in arms.values()]
    ref = v["reference"]
    w("## What 60 questions can and cannot detect")
    w("")
    stratum_span = statistics.median(widths[s][0] for s in STRATA)
    w("- A per-restart median token ratio's 95%% interval spans a factor of %s on all 60 questions and %s on a stratum's "
      "20 (median over the crossing's comparisons and restarts); pooled over the five restarts, %s and %s. The same 60 "
      "questions serve every restart and the same E0 answers serve every comparison against S0, so pooling restarts "
      "does not shrink the part of the interval that comes from the choice of questions: on one restart's stratum, "
      "only a change of about %d%% or more in tokens is distinguishable from none." % (
          num(widths["all"][0]), num(stratum_span), num(widths["all"][1]),
          num(statistics.median(widths[s][1] for s in STRATA)), round(100 * (math.sqrt(stratum_span) - 1))))
    w("- E0 is one answer per question, shared by every restart: its own noise moves every comparison against it "
      "together and is absent from the spread across restarts. Far questions, for example: E0 made %s web calls per "
      "answer, the 25 P0 arms on S1–S5 %s–%s; E0's median far tokens %sk, the P0 arms' %sk–%sk." % (
          num(ref["far"]["e0MeanWebCalls"], 1), num(ref["far"]["p0MeanWebCalls"][0], 1),
          num(ref["far"]["p0MeanWebCalls"][1], 1), k1(ref["far"]["e0MedianTokens"]),
          k1(ref["far"]["p0MedianTokens"][0]), k1(ref["far"]["p0MedianTokens"][1])))
    w("- Contradicted statements run at %d–%d per arm in 60 answers (%d in all %s answers); differences of one or two "
      "between arms are within what two checks of the same answers produce. Passes move more (CL-21) and are reported "
      "second." % (min(contra), max(contra), v["contradicted"]["total"], "{:,}".format(meta["answers"])))
    w("- Dose saturates: one search returns at most 10–25 relevant findings plus 12 from the same sources, and most "
      "answers search twice, so the P0 arms' median dose on near and mid questions is %s and %s at S5, about what it "
      "is at S3 (%s, %s), although the stores grew from %s to %s findings on average. The count of findings returned "
      "is therefore a poor x-axis for cost: mid questions are returned as many findings as near ones and cost more." % (
          opt(v["dose"]["byStore"]["near"]["S5"]["median"], 0), opt(v["dose"]["byStore"]["mid"]["S5"]["median"], 0),
          opt(v["dose"]["byStore"]["near"]["S3"]["median"], 0), opt(v["dose"]["byStore"]["mid"]["S3"]["median"], 0),
          "{:,.0f}".format(cur["growthMean"][3]["findings"]), "{:,.0f}".format(cur["growthMean"][5]["findings"])))
    w("")
    w("## Contradicted statements")
    w("")
    c = v["contradicted"]
    w("%d in %s answers: %s. %d in answers citing a saved finding (%d answers cite one), %d in answers without the web "
      "(%d answers)." % (c["total"], "{:,}".format(meta["answers"]),
                         ", ".join("%s %d" % kv for kv in sorted(c["byKind"].items(), key=lambda kv: -kv[1])),
                         c["inAnswersCitingSaved"], c["answersCitingSaved"], c["inAnswersWithoutWeb"],
                         c["answersWithoutWeb"]))
    w("")
    for s in c["statements"]:
        w("- %s, %s (%s/%s; %s; %d web calls): \"%s\" — %s" % (
            s["arm"], s["stratum"], s["kind"], s["category"], "cites saved findings" if s["citesSaved"] else "no saved "
            "finding cited", s["webCalls"], s["statement"], s["reason"]))
    w("")
    w("## Notes on the records")
    w("")
    w("- %d answers were checked again: in shard 7, two questions' checks were redone together, all 50 arms, after "
      "one arm's check timed out twice (the driver's rule); the analysis uses the second checks. Of the %d with a "
      "completed first check, the two checks agree on contradicted statements in %d, completeness %d, sourced result "
      "%d, pass %d (contradicted %d → %d, passes %d → %d)." % (
          meta["rechecked"], rc["answers"], rc["agree"]["contradicted"], rc["agree"]["complete"],
          rc["agree"]["resultGiven"], rc["agree"]["pass"], rc["contradicted"][0], rc["contradicted"][1], rc["passes"][0],
          rc["passes"][1]))
    w("- No answer was answered again; every answer's trace records as many knowledge searches as its metrics count.")
    w("")
    w("## Cross-checks")
    w("")
    if v["crossChecks"]["mismatches"]:
        for x in v["crossChecks"]["mismatches"]:
            w("- %s: expected %s, got %s" % (x["what"], x["expected"], x["got"]))
    else:
        w("None: every snapshot's fingerprint equals the one recorded when it was taken and every arm's in the plans; "
          "every arm's prompt version equals its restart's prompt file; every check's stored measures equal those "
          "recomputed from its statements; every trace's searches equal the answer's knowledge lookups; the 60 "
          "questions are test 1's held-out set.")
    w("")
    return "\n".join(out) + "\n"


def write(value, out=None):
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(value, ensure_ascii=False, indent=1, default=dict)
    report = markdown(json.loads(text))
    for name, body in (("results.json", text + "\n"), ("results.md", report)):
        if B.LOCAL_PATH.search(body):
            raise SystemExit("%s would contain a local path; nothing written" % name)
    (out / "results.json").write_text(text + "\n", encoding="utf-8")
    (out / "results.md").write_text(report, encoding="utf-8")
    return out


def main():
    parser = argparse.ArgumentParser(description="Part B's performance from the final evaluation's records.")
    parser.add_argument("--base", type=Path, help="the final evaluation's folder (default 2026-10-restarts/final)")
    parser.add_argument("--restarts", type=Path, help="the restarts' folder (default .oopc/loop/harness/2026-10-restarts)")
    parser.add_argument("--out", type=Path, help="write here instead of .oopc/study/analysis/restarts-final")
    args = parser.parse_args()
    if not Path(B.knowledge.__file__).resolve().is_relative_to(FREEZE2):
        raise SystemExit("The records were written by tag study-freeze-2; run with its code (%s)." % FREEZE2)
    value = build(args.base, args.restarts)
    out = write(value, args.out)
    for p in value["predictions"]:
        print("prediction %s: %s" % (p["id"], p["verdict"]))
    print("cross-check mismatches:", value["crossChecks"]["count"])
    print("wrote", out / "results.json", out / "results.md")


if __name__ == "__main__":
    main()
