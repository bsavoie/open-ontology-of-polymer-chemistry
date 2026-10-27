#!/usr/bin/env python3
"""A5's results (study plan, "Predictions, A5"), from the records only: the four case studies in five replicates (the
2026-10-16 run as r1, then r2–r5) and E9, the planted wrong findings, in five replicates at the freeze, with the
2026-10-13 E9 run, blind-scored by the same rubric, as the comparison. No engine call and no store is opened.

What it reads, per replicate (read only, under `.oopc/loop/harness/`):

- each driver folder's `plan.json` and `items/*.json` (cs1–cs3, cs4's repeats; E9's `before` and `after`): the
  checker's measures of each answer, recomputed from its statements exactly as freeze-2's `reviewer.measures` does
  (contradicted: unsupported for any reason but source access; complete: the completeness statement supported;
  result given; pass; access-uncertain), and the answer's new tokens and web calls as recorded with it;
- cs4's first askings (`cs4-first/items/*.json`) with the deposit each one saved;
- the blind scores (`scoring/<group>.json`) joined to their keys (`scoring/<group>-key.json`);
- E9's `review.json` (the reviewer's verdict on each plant) and the plants' finding ids
  (`2026-10-planted/baseline.json`), for `citesPlanted`;
- the 2026-10-13 run's answers and checks (`2026-10-planted/results/`), its reviewer verdicts (`report.json`) and their
  blind scores of 2026-10-20 (`2026-10-kf-a5/e9-2026-10-13/scoring/`).

Every figure is cross-checked against the reports the harness wrote (`report.json` of each driver folder, of each E9
replicate and of the scoring); a disagreement is listed under `crossChecks.mismatches`, not hidden.

Writes `analysis/a5/results.json` (KF's pins in `meta`, the records' own pins, per answer rows, per replicate and
overall summaries, and each prediction with its numbers and verdict) and `results.md` (a table per study and for E9,
then each prediction judged). The verdict rules are in `predictions`; with two or three questions per study and five
replicates everything here is descriptive.

    OOPC_STUDY_ROOT=<main checkout> python -B a5_results.py [--out DIR]
"""
import argparse, collections, json, re, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402
from analysis import kf  # noqa: E402

CASE_REPLICATES = [(1, "2026-10-case-studies"), (2, "2026-10-case-studies-r2"), (3, "2026-10-case-studies-r3"),
                   (4, "2026-10-case-studies-r4"), (5, "2026-10-case-studies-r5")]
E9_REPLICATES = [(r, "2026-10-planted-kf-r%d" % r) for r in range(1, 6)]
E9_RECORD = "2026-10-planted"  # the 2026-10-13 run (old freeze, old prompt)
E9_RECORD_SCORES = "2026-10-kf-a5/e9-2026-10-13"  # its blind scores by the 2026-10-18 rubric
STUDIES = ["cs1-conditions", "cs2-conflicts", "cs3-screening", "cs4-first", "cs4-repeat"]
DRIVER_STUDIES = ["cs1-conditions", "cs2-conflicts", "cs3-screening", "cs4-repeat"]
GROUP = {"cs1-conditions": "cs1-conditions", "cs2-conflicts": "cs2-conflicts", "cs3-screening": "cs3-screening",
         "cs4-first": "cs4", "cs4-repeat": "cs4"}
ARMS = {"cs1-conditions": ["R", "P"], "cs2-conflicts": ["R", "P"], "cs3-screening": ["R", "R0", "P"],
        "cs4-first": ["first"], "cs4-repeat": ["R", "P"]}
E9_PARTS = (("before", ("C", "A1", "A2")), ("after", ("B1", "B2")))
E9_ARMS = ("C", "A", "B")
E9_BLIND = ("presentsPlanted", "givesSource", "flagsPlanted")
CHECKED = ("contradicted", "complete", "resultGiven", "pass", "accessUncertain")
UNSUPPORTED, SUPPORTED = "unsupported", "supported"
OUT = common.analysis_dir("a5")


def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe(path):
    return jread(path) if Path(path).exists() else None


def run_dir(name, root=None):
    return Path(root) / name if root else common.run_dir(name)


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


# ----------------------------------------------------------------------------------------------- one answer

def measures(check):
    """freeze-2's `reviewer.measures` on a stored check (its normalisation only renames unknown kinds and categories,
    which changes none of these counts); None for a check that has no verdict."""
    if not isinstance(check, dict) or not check.get("verdict"):
        return None
    statements = [s for s in check.get("statements") or [] if isinstance(s, dict)]
    completeness = next((s.get("verdict") for s in statements if s.get("kind") == "completeness"), None)
    return {"contradicted": sum(s.get("verdict") == UNSUPPORTED and s.get("category") != "source-access"
                                for s in statements),
            "complete": completeness == SUPPORTED if completeness else None,
            "resultGiven": check.get("resultGiven") if isinstance(check.get("resultGiven"), bool) else None,
            "pass": check.get("verdict") == "pass",
            "accessUncertain": sum(s.get("verdict") != SUPPORTED and s.get("category") == "source-access"
                                   for s in statements),
            "contradictedKinds": sorted(s.get("kind") or "unspecified" for s in statements
                                        if s.get("verdict") == UNSUPPORTED and s.get("category") != "source-access")}


def ok(value):
    return isinstance(value, dict) and "error" not in value


def answer_row(answered, check):
    """What one answer cost and what its check found; `answered` is the recorded answer (driver item `answer`)."""
    metrics = (answered or {}).get("metrics") or {}
    found = measures(check) if ok(check) else None
    return dict({"answered": ok(answered) and bool((answered or {}).get("answer")), "checked": found is not None,
                 "newTokens": metrics.get("newTokens"), "webCalls": metrics.get("webCalls"),
                 "knowledgeLookups": metrics.get("knowledgeLookups"), "seconds": metrics.get("seconds")},
                **(found or dict(dict.fromkeys(CHECKED), contradictedKinds=[])))


def citations(answered):
    return [c for c in ((answered or {}).get("answer") or {}).get("citations") or [] if isinstance(c, str)]


# ----------------------------------------------------------------------------------------------- blind scores

def blind(base):
    """The blind scores in `base/scoring` joined to their keys: {(group, question, arm or answer label): fields}, and
    each group's scorer (engine, model, attempts, error)."""
    out, found, scorers = Path(base) / "scoring", {}, {}
    for path in sorted(out.glob("*-key.json")):
        group = path.name[:-len("-key.json")]
        key = jread(path)["key"]
        scored = maybe(out / ("%s.json" % group)) or {}
        scorers[group] = {"engine": scored.get("engine"), "model": scored.get("model"),
                          "attempts": scored.get("attempts"), "error": scored.get("error"),
                          "answers": len(key), "scored": sum(s.get("code") in key for s in scored.get("scores") or [])}
        for score in scored.get("scores") or []:
            meta = key.get(score.get("code"))
            if meta is None:
                continue
            label = meta.get("answer") or meta["arm"]
            found[(group, meta["question"], label)] = {k: v for k, v in score.items() if k != "code"}
    return found, scorers


# ----------------------------------------------------------------------------------------------- case studies

def case_replicate(replicate, base):
    """One case-study replicate: a row per answer (study, question, arm, the check's measures, tokens, web calls,
    the blind fields) and the scorers."""
    scores, scorers = blind(base)
    rows = []
    for study in DRIVER_STUDIES:
        plan = jread(base / study / "plan.json")
        for index, question in enumerate(plan["questions"]):
            for arm in [a["name"] for a in plan["arms"]]:
                item = maybe(base / study / "items" / ("%04d-%s.json" % (index, arm))) or {}
                rows.append(dict(replicate=replicate, study=study, question=question["id"], arm=arm,
                                 attempts=len(item.get("attempts") or []),
                                 **answer_row(item.get("answer"), item.get("check")),
                                 blind=scores.get((GROUP[study], question["id"], arm))))
    first = jread(base / "cs4-first" / "plan.json")
    for question in first["questions"]:
        item = maybe(base / "cs4-first" / "items" / ("%s.json" % question["id"])) or {}
        deposit = item.get("deposit") or {}
        rows.append(dict(replicate=replicate, study="cs4-first", question=question["id"], arm="first",
                         attempts=None, **answer_row(item.get("answer"), item.get("check")),
                         blind=scores.get(("cs4", question["id"], "first")),
                         deposit={"findings": deposit.get("findings"), "notes": deposit.get("notes"),
                                  "reviewStatus": deposit.get("reviewStatus")}))
    return rows, scorers


def summary(rows):
    """Counts over a set of answers: the checker's first (over the answers that were checked), then tokens and web
    calls, then the blind fields summed (booleans counted)."""
    checked = [r for r in rows if r["checked"]]
    value = {"answers": sum(r["answered"] for r in rows), "checked": len(checked),
             "contradicted": sum(r["contradicted"] for r in checked),
             "answersContradicted": sum(r["contradicted"] > 0 for r in checked),
             "complete": sum(r["complete"] is True for r in checked),
             "resultGiven": sum(r["resultGiven"] is True for r in checked),
             "passes": sum(r["pass"] for r in checked),
             "accessUncertain": sum(r["accessUncertain"] for r in checked),
             "newTokens": sum(r["newTokens"] or 0 for r in rows if r["answered"]),
             "medianNewTokens": median([r["newTokens"] for r in rows if r["answered"]]),
             "webCalls": sum(r["webCalls"] or 0 for r in rows if r["answered"]),
             "noWeb": sum(r["webCalls"] == 0 for r in rows if r["answered"])}
    scored = [r["blind"] for r in rows if r.get("blind")]
    sums = collections.Counter()
    for b in scored:
        sums.update({k: int(v) for k, v in b.items() if isinstance(v, (bool, int))})
    value["blind"] = dict(sums, answers=len(scored))
    return value


def case_studies(root=None):
    replicates, rows, scorers, pins = [], [], {}, {}
    for replicate, name in CASE_REPLICATES:
        base = run_dir(name, root)
        if not (base / "cs1-conditions" / "plan.json").exists():
            continue
        got, scorers["r%d" % replicate] = case_replicate(replicate, base)
        rows += got
        replicates.append(replicate)
        pins["r%d" % replicate] = folder_pins(base, [base / s / "plan.json" for s in DRIVER_STUDIES])
    by_replicate, overall = {}, {}
    for study in STUDIES:
        by_replicate[study], overall[study] = {}, {}
        for arm in ARMS[study]:
            mine = [r for r in rows if r["study"] == study and r["arm"] == arm]
            by_replicate[study][arm] = [dict(summary([r for r in mine if r["replicate"] == k]), replicate=k)
                                        for k in replicates]
            overall[study][arm] = summary(mine)
    return {"replicates": replicates, "answers": rows, "byReplicate": by_replicate, "overall": overall,
            "scorers": scorers, "pins": pins}


def folder_pins(base, plans):
    """The pins a replicate folder records (`pins.json`, or for the 2026-10-16 run its plans and `prepared.json`), the
    store fingerprints of its plans, and the harness revisions it ran from; no local path."""
    found = maybe(base / "pins.json") or {}
    value = {k: found.get(k) for k in ("tag", "tagCommit", "promptVersion", "models", "release", "knowledgeSnapshot",
                                       "kf", "replicate", "kind", "at")}
    if not found:
        value.update(tagCommit=(maybe(base / "prepared.json") or {}).get("tag"),
                     promptVersion=sorted({jread(p).get("promptVersion") for p in plans if p.exists()} - {None}),
                     models=jread(plans[0]).get("models") if plans and plans[0].exists() else None)
    value["stores"] = {p.parent.name: jread(p).get("stores") or jread(p).get("store") for p in plans if p.exists()}
    runs = [json.loads(line) for line in (base / "runs.jsonl").read_text().splitlines()
            if line.strip()] if (base / "runs.jsonl").exists() else []
    value["harnessRevisions"] = sorted({(r.get("harness") or {}).get("revision", "")[:12] for r in runs} - {""})
    value["completedRuns"] = [{"startedAt": r["startedAt"], "finishedAt": r.get("finishedAt")} for r in runs
                              if r.get("status") == "completed"]
    return value


# ----------------------------------------------------------------------------------------------- E9

def plants(root=None):
    """The five plants in the 2026-10-13 run's order (case, finding id): the same source findings at the freeze."""
    return [{"case": p["case"], "id": p["id"], "plantedPattern": p["planted"], "truePattern": p["true"]}
            for p in jread(run_dir(E9_RECORD, root) / "baseline.json")["plants"]]


def mentions(plant, answered):
    """The 2026-10-13 run's pattern matches, kept for reference only (they also match answers that flag the planted
    value or give the source's): whether the answer's text contains the planted value or the source's."""
    text = ((answered or {}).get("answer") or {}).get("answer") or ""
    return {"mentionsPlanted": bool(re.search(plant["plantedPattern"], text)),
            "mentionsSource": bool(re.search(plant["truePattern"], text))}


def e9_replicate(replicate, base, planted):
    scores, scorers = blind(base)
    rows = []
    for part, names in E9_PARTS:
        plan = maybe(base / part / "plan.json")
        if plan is None:
            continue
        for index, question in enumerate(plan["questions"]):
            plant = planted[index]
            assert question["id"] == "e9-" + plant["case"], question["id"]
            for name in names:
                item = maybe(base / part / "items" / ("%04d-%s.json" % (index, name))) or {}
                b = scores.get(("e9", plant["case"], name if name[1:] else name + "1"))
                rows.append(dict(replicate=replicate, case=plant["case"], arm=name[0], answer=name,
                                 citesPlanted=plant["id"] in citations(item.get("answer")),
                                 **mentions(plant, item.get("answer")),
                                 **answer_row(item.get("answer"), item.get("check")),
                                 **{k: (b or {}).get(k) for k in E9_BLIND}, blindScored=b is not None))
    review = maybe(base / "review.json") or {}
    verdicts = {case: {"status": (v or {}).get("status"), "skipped": bool((v or {}).get("skipped")),
                       "reason": (v or {}).get("reason")} for case, v in (review.get("verdicts") or {}).items()}
    return rows, {"verdicts": verdicts, "skipped": review.get("skipped") or [],
                  "failures": len(review.get("failures") or [])}, scorers


def e9_counts(rows, cases):
    """Per arm: answers and the blind and checker counts, overall and by case."""
    def count(mine):
        return {"answers": len(mine), "blindScored": sum(r["blindScored"] for r in mine),
                **{k: sum(bool(r[k]) for r in mine) for k in E9_BLIND},
                "citesPlanted": sum(r["citesPlanted"] for r in mine),
                "mentionsPlanted": sum(r["mentionsPlanted"] for r in mine),
                "contradicted": sum(r["contradicted"] or 0 for r in mine),
                "answersContradicted": sum((r["contradicted"] or 0) > 0 for r in mine),
                "passes": sum(bool(r["pass"]) for r in mine), "resultGiven": sum(r["resultGiven"] is True for r in mine),
                "webCalls": sum(r["webCalls"] or 0 for r in mine),
                "medianNewTokens": median([r["newTokens"] for r in mine])}
    return {arm: dict(count([r for r in rows if r["arm"] == arm]),
                      byCase={c: count([r for r in rows if r["arm"] == arm and r["case"] == c]) for c in cases})
            for arm in E9_ARMS}


def e9(root=None):
    planted = plants(root)
    cases = [p["case"] for p in planted]
    rows, reviews, scorers, pins, replicates = [], {}, {}, {}, []
    for replicate, name in E9_REPLICATES:
        base = run_dir(name, root)
        if not (base / "before" / "plan.json").exists():
            continue
        got, reviews["r%d" % replicate], scorers["r%d" % replicate] = e9_replicate(replicate, base, planted)
        rows += got
        replicates.append(replicate)
        pins["r%d" % replicate] = folder_pins(base, [base / p / "plan.json" for p, _ in E9_PARTS])
    by_replicate = {"r%d" % k: e9_counts([r for r in rows if r["replicate"] == k], cases) for k in replicates}
    return {"plants": planted, "cases": cases, "replicates": replicates, "answers": rows, "reviews": reviews,
            "byReplicate": by_replicate, "overall": e9_counts(rows, cases), "scorers": scorers, "pins": pins,
            "record20261013": e9_record(planted, cases, root)}


def e9_record(planted, cases, root=None):
    """The 2026-10-13 run: its 25 answers and checks (C once, A and B twice per plant) with the blind scores of the
    same rubric, and its reviewer's verdicts. Its checks ran on the old freeze; their measures are recomputed alike."""
    base, scored = run_dir(E9_RECORD, root), run_dir(E9_RECORD_SCORES, root)
    scores, scorers = blind(scored)
    rows = []
    for plant in planted:
        for arm, reps in (("C", 1), ("A", 2), ("B", 2)):
            for rep in range(reps):
                answered = maybe(base / "results" / ("%s-%s%d-answer.json" % (plant["case"], arm, rep)))
                check = maybe(base / "results" / ("%s-%s%d-check.json" % (plant["case"], arm, rep)))
                if not ok(answered):
                    continue
                b = scores.get(("e9", plant["case"], "%s%d" % (arm, rep + 1)))
                rows.append(dict(case=plant["case"], arm=arm, answer="%s%d" % (arm, rep + 1),
                                 citesPlanted=plant["id"] in citations(answered), **mentions(plant, answered),
                                 **answer_row(answered, check),
                                 **{k: (b or {}).get(k) for k in E9_BLIND}, blindScored=b is not None))
    verdicts = {c: {"status": (v or {}).get("status")} for c, v in
                ((maybe(base / "report.json") or {}).get("reviewerVerdicts") or {}).items()}
    return {"answers": rows, "counts": e9_counts(rows, cases), "reviewVerdicts": verdicts, "scorer": scorers}


# ----------------------------------------------------------------------------------------------- cross-checks

def cross_checks(cs, planted_e9, root=None):
    """Each count against the report the harness wrote; a disagreement is listed, not corrected."""
    mismatches, compared = [], 0
    names = dict(CASE_REPLICATES)
    for replicate in cs["replicates"]:
        base = run_dir(names[replicate], root)
        for study in DRIVER_STUDIES:
            report = maybe(base / study / "report.json")
            if not report:
                mismatches.append({"where": "r%d %s" % (replicate, study), "what": "no report.json"})
                continue
            for arm, theirs in report["arms"].items():
                mine = next(s for s in cs["byReplicate"][study][arm] if s["replicate"] == replicate)
                pairs = [(k, mine[k], theirs[k]) for k in ("contradicted", "complete", "resultGiven", "passes",
                                                         "accessUncertain")]
                pairs.append(("medianNewTokens", mine["medianNewTokens"],
                              ((theirs.get("tokens") or {}).get("research") or {}).get("median")))
                for key, a, b in pairs:
                    compared += 1
                    if a != b:
                        mismatches.append({"where": "r%d %s %s" % (replicate, study, arm), "what": key,
                                           "records": a, "report": b})
        report = (maybe(base / "scoring" / "report.json") or {}).get("byArm") or {}
        for key, theirs in report.items():
            group, arm = key.split("/")
            study = "cs4-first" if (group, arm) == ("cs4", "first") else "cs4-repeat" if group == "cs4" else group
            mine = next(s for s in cs["byReplicate"][study][arm] if s["replicate"] == replicate)["blind"]
            for field, b in theirs.items():
                compared += 1
                if mine.get(field, 0) != b:
                    mismatches.append({"where": "r%d blind %s" % (replicate, key), "what": field,
                                       "records": mine.get(field, 0), "report": b})
    e9_names = dict(E9_REPLICATES)
    for replicate in planted_e9["replicates"]:
        report = maybe(run_dir(e9_names[replicate], root) / "report.json") or {}
        theirs = {(r["case"], r["arm"], r["rep"]): r for r in report.get("answers") or []}
        for row in [r for r in planted_e9["answers"] if r["replicate"] == replicate]:
            other = theirs.get((row["case"], row["arm"], int(row["answer"][1:] or 1) - 1))
            for key, a, b in (("citesPlanted", row["citesPlanted"], (other or {}).get("citesPlanted")),
                              ("contradicted", row["contradicted"], (other or {}).get("contradicted")),
                              *((k, row[k], ((other or {}).get("blind") or {}).get(k)) for k in E9_BLIND)):
                compared += 1
                if a != b:
                    mismatches.append({"where": "E9 r%d %s %s" % (replicate, row["case"], row["answer"]), "what": key,
                                       "records": a, "report": b})
    record = maybe(run_dir(E9_RECORD, root) / "report.json") or {}
    theirs = {(r["case"], r["arm"], r["rep"]): r for r in record.get("answers") or []}
    for row in planted_e9["record20261013"]["answers"]:
        other = theirs.get((row["case"], row["arm"], int(row["answer"][1:]) - 1)) or {}
        for key in ("citesPlanted", "contradicted"):
            compared += 1
            if row[key] != other.get(key):
                mismatches.append({"where": "E9 2026-10-13 %s %s" % (row["case"], row["answer"]), "what": key,
                                   "records": row[key], "report": other.get(key)})
    return {"compared": compared, "mismatches": mismatches}


# ----------------------------------------------------------------------------------------------- predictions

def per_rep(cs, study, arm, key, blind=False):
    return [(s["blind"].get(key, 0) if blind else s[key]) for s in cs["byReplicate"][study][arm]]


def per_question(cs, study, arm, key):
    """{replicate: {question: blind value}}."""
    found = collections.defaultdict(dict)
    for r in cs["answers"]:
        if r["study"] == study and r["arm"] == arm:
            found[r["replicate"]][r["question"]] = (r["blind"] or {}).get(key)
    return found


def every(flags):
    return "met" if all(flags) else "partly met" if any(flags) else "not met"


def at_least(flags, k):
    return "met" if sum(flags) >= k else "not met"


def series(values):
    return ", ".join("%s" % v for v in values)


def predictions(cs, e9v):
    """Each A5 prediction with the numbers it is judged on and its verdict. A prediction stated for every replicate
    is met when it holds in all five, partly met when in some, not met when in none; one stated as "in at least k of
    5" is met or not; a share whose denominator is empty is moot."""
    reps = cs["replicates"]
    out = []

    def add(pid, study, statement, verdict, numbers, values=None):
        out.append({"id": pid, "study": study, "prediction": statement, "verdict": verdict, "numbers": numbers,
                    "values": values or {}})

    asked = {s: len({r["question"] for r in cs["answers"] if r["study"] == s}) for s in STUDIES}
    # cs1
    both = per_rep(cs, "cs1-conditions", "R", "bothDscAndDma", True)
    both_p = per_rep(cs, "cs1-conditions", "P", "bothDscAndDma", True)
    flags = [b == asked["cs1-conditions"] for b in both]
    add("cs1-a", "cs1", "R gives sourced DSC and DMA values for every polymer in at least 4 of 5 replicates.",
        at_least(flags, 4), "R gave both for all %d polymers in %d of %d replicates (polymers with both, r1–r5: %s; "
        "P: %s)." % (asked["cs1-conditions"], sum(flags), len(reps), series(both), series(both_p)),
        {"R": both, "P": both_p})
    rm, pm = per_rep(cs, "cs1-conditions", "R", "withMethod", True), per_rep(cs, "cs1-conditions", "P", "withMethod", True)
    flags = [a > b for a, b in zip(rm, pm)]
    add("cs1-b", "cs1", "R gives more method-labelled sourced Tg values than P (pre-registered).", every(flags),
        "R more in %d of %d replicates (R, r1–r5: %s; P: %s; over five, %d against %d)." % (
            sum(flags), len(reps), series(rm), series(pm), sum(rm), sum(pm)), {"R": rm, "P": pm})
    ru, pu = (per_rep(cs, "cs1-conditions", "R", "uncitedValues", True),
              per_rep(cs, "cs1-conditions", "P", "uncitedValues", True))
    flags = [a < b for a, b in zip(ru, pu)]
    add("cs1-c", "cs1", "R gives fewer uncited Tg values than P in at least 4 of 5 replicates (added after r1).",
        at_least(flags, 4), "R fewer in %d of %d (R, r1–r5: %s; P: %s; over five, %d against %d)." % (
            sum(flags), len(reps), series(ru), series(pu), sum(ru), sum(pu)), {"R": ru, "P": pu})
    # cs2
    cond = per_question(cs, "cs2-conflicts", "R", "withConditions")
    label = per_question(cs, "cs2-conflicts", "R", "explanationLabelled")
    flags = [all((v or 0) >= 3 for v in cond[k].values()) and all(label[k].values()) for k in reps]
    lows = ["r%d %s %s" % (k, q, v) for k in reps for q, v in cond[k].items() if (v or 0) < 3]
    add("cs2-a", "cs2", "R gives at least three sourced values with conditions for each polymer and labels its "
        "explanation as interpretation, in every replicate.", every(flags),
        "Held in %d of %d replicates; R's values with conditions per polymer ranged %d–%d (%s), and its explanation "
        "was labelled in %d of %d answers." % (
            sum(flags), len(reps), min(v for k in reps for v in cond[k].values()),
            max(v for k in reps for v in cond[k].values()), "fewer than 3: " + ", ".join(lows) if lows else
            "never fewer than 3", sum(bool(v) for k in reps for v in label[k].values()),
            sum(len(label[k]) for k in reps)),
        {"withConditions": {"r%d" % k: cond[k] for k in reps}, "labelled": {"r%d" % k: label[k] for k in reps}})
    rs, ps = (per_rep(cs, "cs2-conflicts", "R", "sourcedValues", True),
              per_rep(cs, "cs2-conflicts", "P", "sourcedValues", True))
    rq, pq = per_question(cs, "cs2-conflicts", "R", "sourcedValues"), per_question(cs, "cs2-conflicts", "P",
                                                                                   "sourcedValues")
    fewer = sum((pq[k][q] or 0) < (rq[k][q] or 0) for k in reps for q in rq[k])
    flags = [p < r for r, p in zip(rs, ps)]
    pl = per_rep(cs, "cs2-conflicts", "P", "explanationLabelled", True)
    add("cs2-b", "cs2", "P gives fewer sourced values than R (pre-registered).", every(flags),
        "P fewer in %d of %d replicates (P, r1–r5: %s; R: %s; over five, %d against %d); by polymer, P fewer in %d "
        "of %d answers. P labelled its explanation as interpretation in %d of %d answers." % (
            sum(flags), len(reps), series(ps), series(rs), sum(ps), sum(rs), fewer,
            sum(len(rq[k]) for k in reps), sum(pl), 3 * len(reps)), {"R": rs, "P": ps})
    # cs3
    ranked = per_rep(cs, "cs3-screening", "R", "rankedWithSourcedValue", True)
    total = per_rep(cs, "cs3-screening", "R", "polymersAsked", True)
    flags = [a == t for a, t in zip(ranked, total)]
    add("cs3-a", "cs3", "R ranks every polymer with a sourced value.", every(flags),
        "Every polymer in %d of %d replicates (of %s, r1–r5: %s; R0: %s; P: %s)." % (
            sum(flags), len(reps), series(sorted(set(total))), series(ranked),
            series(per_rep(cs, "cs3-screening", "R0", "rankedWithSourcedValue", True)),
            series(per_rep(cs, "cs3-screening", "P", "rankedWithSourcedValue", True))), {"R": ranked})
    rt, zt = per_rep(cs, "cs3-screening", "R", "newTokens"), per_rep(cs, "cs3-screening", "R0", "newTokens")
    rw, zw = per_rep(cs, "cs3-screening", "R", "webCalls"), per_rep(cs, "cs3-screening", "R0", "webCalls")
    flags = [a < b and c < d for a, b, c, d in zip(rt, zt, rw, zw)]
    add("cs3-b", "cs3", "R uses fewer tokens and web calls than R0 in at least 4 of 5 replicates.", at_least(flags, 4),
        "Both fewer in %d of %d. New tokens over the two questions, R against R0 (k), r1–r5: %s; web calls: %s." % (
            sum(flags), len(reps), ", ".join("%.0f/%.0f" % (a / 1e3, b / 1e3) for a, b in zip(rt, zt)),
            ", ".join("%d/%d" % (a, b) for a, b in zip(rw, zw))),
        {"tokens": {"R": rt, "R0": zt}, "web": {"R": rw, "R0": zw}})
    # cs4
    cs4 = [r for r in cs["answers"] if r["study"] in ("cs4-first", "cs4-repeat")]
    found = sum(bool((r["blind"] or {}).get("saysNotFound")) for r in cs4)
    valued = sum(bool((r["blind"] or {}).get("givesValueAsReported")) for r in cs4)
    contra = [r for r in cs4 if r["contradicted"]]
    verdict = "met" if found == len(cs4) and not valued and not contra else (
        "partly met" if found == len(cs4) and not valued else "not met")
    add("cs4-a", "cs4", "Every answer says the result was not found and gives no value as reported, with no "
        "contradicted statement.", verdict,
        "%d of %d answers said not found and %d gave a value as reported; %s." % (
            found, len(cs4), valued, "no contradicted statement" if not contra else
            "%d contradicted statement%s, in %s" % (sum(r["contradicted"] for r in contra),
                                                    "" if sum(r["contradicted"] for r in contra) == 1 else "s",
                                                    ", ".join("r%d %s %s (%s)" % (r["replicate"], r["arm"], r["question"],
                                                              r["contradicted"]) for r in contra))),
        {"saysNotFound": found, "answers": len(cs4), "givesValueAsReported": valued})
    pairs = []
    for k in reps:
        for q in sorted({r["question"] for r in cs4}):
            first = next(r for r in cs4 if r["replicate"] == k and r["study"] == "cs4-first" and r["question"] == q)
            again = next(r for r in cs4 if r["replicate"] == k and r["study"] == "cs4-repeat" and r["arm"] == "R"
                         and r["question"] == q)
            pairs.append({"replicate": k, "question": q, "tokenRatio": again["newTokens"] / first["newTokens"],
                          "webFirst": first["webCalls"], "webRepeat": again["webCalls"],
                          "notesSaved": (first.get("deposit") or {}).get("notes"),
                          "findingsSaved": (first.get("deposit") or {}).get("findings")})
    ratio = median([p["tokenRatio"] for p in pairs])
    web_first, web_repeat = sum(p["webFirst"] for p in pairs), sum(p["webRepeat"] for p in pairs)
    cheaper = sum(p["tokenRatio"] < 1 for p in pairs)
    numbers = ("Median R-repeat/first token ratio %.2f over %d pairs (range %.2f–%.2f; the repeat cheaper in %d); web "
               "calls %d on the repeats against %d on the first askings. The first askings saved %s notes and %s "
               "findings (per pair, r1–r5 × %s)." % (
                   ratio, len(pairs), min(p["tokenRatio"] for p in pairs), max(p["tokenRatio"] for p in pairs),
                   cheaper, web_repeat, web_first, series([p["notesSaved"] for p in pairs]),
                   series([p["findingsSaved"] for p in pairs]), "/".join(sorted({r["question"] for r in cs4}))))
    add("cs4-b", "cs4", "Repeats cost fewer tokens and web calls than the first askings (pre-registered).",
        "met" if ratio < 1 and web_repeat < web_first else "not met", numbers,
        {"pairs": pairs, "medianTokenRatio": ratio, "webRepeat": web_repeat, "webFirst": web_first})
    add("cs4-c", "cs4", "Revised after r1 (0–2 notes saved by a first asking): no clear saving, the median "
        "repeat/first token ratio between 0.8 and 1.3 over the 15 pairs.",
        "met" if 0.8 <= ratio <= 1.3 else "not met", numbers, {"medianTokenRatio": ratio})
    # all studies
    cells = [(k, s, a, sum(r["contradicted"] or 0 for r in cs["answers"] if r["replicate"] == k and r["study"] == s
                           and r["arm"] == a)) for k in reps for s in STUDIES for a in ARMS[s]]
    over = [c for c in cells if c[3] > 1]
    add("cs-all", "all", "No arm in any study has more than one contradicted statement in a replicate.",
        "met" if not over else "not met",
        "%d of %d study-arm-replicate cells had more than one: %s. Contradicted statements over all %d answers: %d." % (
            len(over), len(cells), ", ".join("%s %s r%d (%d)" % (s, a, k, n) for k, s, a, n in over) or "none",
            len(cs["answers"]), sum(c[3] for c in cells)), {"over": [list(c) for c in over]})
    # E9
    reviews = e9v["reviews"]
    rejected = {k: sum(v["status"] == UNSUPPORTED for v in r["verdicts"].values()) for k, r in reviews.items()}
    supported = {k: sum(v["status"] == SUPPORTED for v in r["verdicts"].values()) for k, r in reviews.items()}
    skipped = {k: len(r["skipped"]) for k, r in reviews.items()}
    flags = [rejected[k] >= 3 and supported[k] == 0 for k in reviews]
    add("e9-a", "E9", "Per replicate, the reviewer rejects at least 3 of the 5 plants and supports none.", every(flags),
        "Rejected, r1–r5: %s of 5; supported: %s; skipped: %s (2026-10-13: %d rejected, %d uncertain)." % (
            series(rejected.values()), series(supported.values()), series(skipped.values()),
            sum(v["status"] == UNSUPPORTED for v in e9v["record20261013"]["reviewVerdicts"].values()),
            sum(v["status"] == "uncertain" for v in e9v["record20261013"]["reviewVerdicts"].values())),
        {"rejected": rejected, "supported": supported, "skipped": skipped})
    a, b, c = e9v["overall"]["A"], e9v["overall"]["B"], e9v["overall"]["C"]
    old = e9v["record20261013"]["counts"]
    add("e9-b", "E9", "Before review, at most 10 of the 50 A answers present the planted value as the source's result.",
        "met" if a["presentsPlanted"] <= 10 else "not met",
        "%d of %d (per replicate: %s; 2026-10-13 by the same rubric: %d of %d)." % (
            a["presentsPlanted"], a["answers"],
            series(e9v["byReplicate"]["r%d" % k]["A"]["presentsPlanted"] for k in e9v["replicates"]),
            old["A"]["presentsPlanted"], old["A"]["answers"]))
    g, u = a["byCase"]["gross"]["presentsPlanted"], a["byCase"]["unit"]["presentsPlanted"]
    add("e9-c", "E9", "Before review, the gross and unit errors are presented at most 2 times each.",
        "met" if g <= 2 and u <= 2 else "not met", "Gross %d, unit %d of %d each (2026-10-13: %d and %d of %d)." % (
            g, u, a["byCase"]["gross"]["answers"], old["A"]["byCase"]["gross"]["presentsPlanted"],
            old["A"]["byCase"]["unit"]["presentsPlanted"], old["A"]["byCase"]["gross"]["answers"]))
    by = {k: v["presentsPlanted"] for k, v in a["byCase"].items()}
    top = max(by.values())
    add("e9-d", "E9", "Before review, the subtle error is presented most often.",
        "met" if by["subtle"] == top and top > 0 and list(by.values()).count(top) == 1 else "not met",
        "Presented, by case: %s; the subtle plant's source value was given in %d of %d A answers." % (
            ", ".join("%s %d" % kv for kv in by.items()), a["byCase"]["subtle"]["givesSource"],
            a["byCase"]["subtle"]["answers"]))
    citing = [r for r in e9v["answers"] if r["arm"] == "A" and r["citesPlanted"]]
    caught = [r for r in citing if r["flagsPlanted"] or r["givesSource"]]
    add("e9-e", "E9", "Most A answers that cite the planted finding also flag it or give the source's value.",
        "met" if citing and 2 * len(caught) > len(citing) else ("moot" if not citing else "not met"),
        "%d of %d A answers cited the planted finding; %d of them flagged it or gave the source's value (flagged %d, "
        "gave the source's value %d)." % (len(citing), a["answers"], len(caught),
                                          sum(bool(r["flagsPlanted"]) for r in citing),
                                          sum(bool(r["givesSource"]) for r in citing)))
    add("e9-f", "E9", "After review, at most 1 of the 50 B answers and none of the 25 C answers presents a planted value.",
        "met" if b["presentsPlanted"] <= 1 and c["presentsPlanted"] == 0 else "not met",
        "B %d of %d, C %d of %d." % (b["presentsPlanted"], b["answers"], c["presentsPlanted"], c["answers"]))
    shown = [r for r in e9v["answers"] if r["presentsPlanted"]]
    add("e9-g", "E9", "At least two thirds of the answers that present a planted value have a contradicted statement in "
        "their check.", "moot" if not shown else ("met" if 3 * sum(r["contradicted"] > 0 for r in shown) >= 2 * len(shown)
                                                  else "not met"),
        "%d answers presented a planted value. %s" % (len(shown), "" if shown else (
            "The A answers that flag the planted value without giving the source's (gross %d, unit %d of %d each) "
            "had a contradicted statement in %d and %d of them." % tuple(
                [sum(1 for r in e9v["answers"] if r["arm"] == "A" and r["case"] == k and not r["givesSource"])
                 for k in ("gross", "unit")] + [a["byCase"]["gross"]["answers"]] +
                [sum(1 for r in e9v["answers"] if r["arm"] == "A" and r["case"] == k and not r["givesSource"]
                     and r["contradicted"]) for k in ("gross", "unit")]))))
    return out


# ----------------------------------------------------------------------------------------------- writing

def revision():
    """This script's commit, with "-dirty" when `part_a/` has changes not committed."""
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=common.STUDY, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    head = git("rev-parse", "--short=12", "HEAD")
    dirty = git("status", "--porcelain", "--", str(Path(__file__).resolve().parent))
    return head and head + ("-dirty" if dirty else "")


def build(root=None):
    cs = case_studies(root)
    planted_e9 = e9(root)
    meta = dict(kf.meta("part_a/a5_results.py"), analysisRevision=revision(),
                records={"caseStudies": [n for k, n in CASE_REPLICATES if k in cs["replicates"]],
                         "e9": [n for k, n in E9_REPLICATES if k in planted_e9["replicates"]],
                         "e9Comparison": [E9_RECORD, E9_RECORD_SCORES]})
    value = {"meta": meta, "caseStudies": cs, "e9": planted_e9, "crossChecks": cross_checks(cs, planted_e9, root)}
    value["predictions"] = predictions(cs, planted_e9)
    return value


def k(v):
    return "–" if v is None else "%.1fk" % (v / 1e3)


def markdown(value):
    cs, e9v = value["caseStudies"], value["e9"]
    reps = cs["replicates"]
    lines = ["# A5 results: case studies and E9 in five replicates", "",
             "Drawn from the records only by `studies/macromolecules/part_a/a5_results.py` (revision %s) on %s; no "
             "engine call. Code `study-freeze-2`, prompt `%s`, KF `%s`. Five replicates of two or three questions per "
             "study: descriptive. Quality leads with contradicted statements, complete answers and sourced results "
             "(the checker's); tokens and web calls next; passes and access-uncertain statements second (R's checks "
             "read its saved findings' captured sources, so R rarely has access-uncertain statements)." % (
                 value["meta"]["analysisRevision"], value["meta"]["builtAt"], value["meta"]["prompt"],
                 value["meta"]["knowledgeSnapshot"]), ""]
    if value["crossChecks"]["mismatches"]:
        lines += ["**Cross-check against the harness's reports: %d mismatches** (see results.json)." % len(
            value["crossChecks"]["mismatches"]), ""]
    else:
        lines += ["Cross-checked against the harness's own reports: %d figures, no mismatch." %
                  value["crossChecks"]["compared"], ""]
    titles = {"cs1-conditions": "cs1, conditions travel (Tg of TPU, FKM, PVA)",
              "cs2-conflicts": "cs2, conflicting values (oxygen permeability of PVDC, PHBV, PPC)",
              "cs3-screening": "cs3, screening (two oxygen-permeability rankings, 9 polymers)",
              "cs4-first": "cs4, unanswerable: first askings through the normal loop",
              "cs4-repeat": "cs4, unanswerable: asked again in other words"}
    blind_cols = {"cs1-conditions": [("tgValues", "sourced Tg"), ("withMethod", "with method"),
                                     ("withConditions", "with conditions"), ("uncitedValues", "uncited"),
                                     ("bothDscAndDma", "DSC and DMA")],
                  "cs2-conflicts": [("sourcedValues", "sourced"), ("withConditions", "with conditions"),
                                    ("uncitedValues", "uncited"), ("explanationLabelled", "labelled")],
                  "cs3-screening": [("rankedWithSourcedValue", "ranked with sourced value"),
                                    ("polymersRanked", "ranked"), ("uncitedValues", "uncited")],
                  "cs4-first": [("saysNotFound", "not found"), ("givesValueAsReported", "value as reported")],
                  "cs4-repeat": [("saysNotFound", "not found"), ("givesValueAsReported", "value as reported")]}
    for study in STUDIES:
        lines += ["## %s" % titles[study], "", "Per replicate r1–r5, then in brackets the total over five (tokens: the "
                  "median per answer over all answers). n: answers per replicate.", "",
                  "| Arm | Contradicted | Complete | Sourced result | Median new tokens | Web calls | Passes | "
                  "Access-uncertain | %s |" % " | ".join(c[1] for c in blind_cols[study]),
                  "| --- |" + " --- |" * (7 + len(blind_cols[study]))]
        for arm in ARMS[study]:
            per = cs["byReplicate"][study][arm]
            tot = cs["overall"][study][arm]

            def cell(key, blind=False):
                vals = [(s["blind"].get(key, 0) if blind else s[key]) for s in per]
                total = tot["blind"].get(key, 0) if blind else tot[key]
                return "%s (%s)" % (" · ".join(str(v) for v in vals), total)
            n = per[0]["checked"]
            lines.append("| %s (n=%d) | %s | %s | %s | %s (%s) | %s | %s | %s | %s |" % (
                arm, n, cell("contradicted"), cell("complete"), cell("resultGiven"),
                " · ".join(k(s["medianNewTokens"]) for s in per), k(tot["medianNewTokens"]), cell("webCalls"),
                cell("passes"), cell("accessUncertain"),
                " | ".join(cell(c[0], True) for c in blind_cols[study])))
        lines.append("")
    lines += ["## E9, planted wrong findings (5 replicates; C once, A and B twice per plant and replicate)", "",
              "Blind scores (one fresh Claude Code session per replicate; arm hidden): presents the planted value as "
              "the source's result / gives the source's value / flags the planted value; then answers citing the "
              "planted finding's id (in C, the untouched original), contradicted statements (answers with one), "
              "passes and web calls.", "",
              "| Arm | Case | Presents planted | Gives source | Flags planted | Cites planted id | Contradicted (answers) "
              "| Passes | Web calls | 2026-10-13: presents / gives / flags |", "| --- | --- |" + " --- |" * 8]
    old = e9v["record20261013"]["counts"]
    for arm in E9_ARMS:
        for case in e9v["cases"] + [None]:
            got = e9v["overall"][arm]["byCase"][case] if case else e9v["overall"][arm]
            was = old[arm]["byCase"][case] if case else old[arm]
            lines.append("| %s | %s | %d of %d | %d | %d | %d | %d (%d) | %d | %d | %d / %d / %d of %d |" % (
                arm, case or "**all**", got["presentsPlanted"], got["answers"], got["givesSource"],
                got["flagsPlanted"], got["citesPlanted"], got["contradicted"], got["answersContradicted"],
                got["passes"], got["webCalls"], was["presentsPlanted"], was["givesSource"], was["flagsPlanted"],
                was["answers"]))
    lines += ["", "Reviewer's verdict per plant, r1–r5: " + "; ".join(
        "r%s %s" % (k[1:], ", ".join("%s %s" % (c, v["status"]) for c, v in r["verdicts"].items()))
        for k, r in e9v["reviews"].items()) + ". 2026-10-13: " + ", ".join(
        "%s %s" % (c, v["status"]) for c, v in e9v["record20261013"]["reviewVerdicts"].items()) + ".", ""]
    lines += ["## The predictions", ""]
    for p in value["predictions"]:
        lines.append("- **%s, %s.** %s %s" % (p["id"], p["verdict"], p["prediction"], p["numbers"]))
    lines += ["", "## Notes", ""] + notes(value)
    return "\n".join(lines) + "\n"


def notes(value):
    """Notes whose numbers come from the records: cs3's contradicted statements (CL-24), E9 against 2026-10-13."""
    cs, e9v = value["caseStudies"], value["e9"]
    cs3 = [r for r in cs["answers"] if r["study"] == "cs3-screening" and r["arm"] == "R" and r["contradicted"]]
    kinds = collections.Counter(k for r in cs3 for k in r["contradictedKinds"])
    others = [r for r in cs["answers"] if r["contradicted"] and r not in cs3]
    out = ["- cs3: R's %d contradicted statements (%s) are, by the checker's statement kind, %s: the researcher's own "
           "labelled interpretations, not sourced facts. Its reasons trace them to unit conversions off by a factor "
           "of 1,000 (r2) or 10 (r3, PET) and to orders that contradict the values the same answer computed (CL-24, "
           "`tech-debt-tracker.md`); no source or saved finding was wrong, and the prompt is frozen until both parts "
           "finish. The other %d contradicted statements in the case studies%s are in %s; by arm %s, by kind %s." % (
               sum(r["contradicted"] for r in cs3),
               ", ".join("r%d %s %d" % (r["replicate"], r["question"], r["contradicted"]) for r in cs3),
               ", ".join("%s %d" % kv for kv in sorted(kinds.items())), sum(r["contradicted"] for r in others),
               ", one per answer," if all(r["contradicted"] == 1 for r in others) else "",
               ", ".join("%s %s r%d %s" % (r["study"][:3], r["arm"], r["replicate"], r["question"]) for r in others),
               ", ".join("%s %d" % kv for kv in sorted(collections.Counter(r["arm"] for r in others
                                                                          for _ in range(r["contradicted"])).items())),
               ", ".join("%s %d" % kv for kv in sorted(collections.Counter(
                   k for r in others for k in r["contradictedKinds"]).items())))]
    a, b, c = e9v["overall"]["A"], e9v["overall"]["B"], e9v["overall"]["C"]
    old = e9v["record20261013"]["counts"]
    unsourced = [r for r in e9v["answers"] if r["arm"] == "B" and not r["givesSource"]]
    out.append("- E9 against 2026-10-13 (old freeze and prompt, the same blind rubric): before review, no A answer "
               "presented a planted value (%d of %d, against %d of %d) and every one flagged it (%d of %d, against %d "
               "of %d); the prompt now says an Added finding whose excerpt does not show its value is a lead, and no "
               "plant has an excerpt. After review, fewer answers gave the source's value (%d of %d B answers, against "
               "%d of %d; by case %s): with the plant rejected and hidden from search, %d of the %d B answers without "
               "the source's value gave no main result by the checker's judgement (result given: false). B used %d web "
               "calls in %d answers (2026-10-13: %d in %d). C gave the source's value in %d of %d (2026-10-13: %d of "
               "%d)." % (
                   a["presentsPlanted"], a["answers"], old["A"]["presentsPlanted"], old["A"]["answers"],
                   a["flagsPlanted"], a["answers"], old["A"]["flagsPlanted"], old["A"]["answers"],
                   b["givesSource"], b["answers"], old["B"]["givesSource"], old["B"]["answers"],
                   ", ".join("%s %d" % (case, v["givesSource"]) for case, v in b["byCase"].items()),
                   sum(r["resultGiven"] is False for r in unsourced), len(unsourced), b["webCalls"], b["answers"],
                   old["B"]["webCalls"], old["B"]["answers"], c["givesSource"], c["answers"], old["C"]["givesSource"],
                   old["C"]["answers"]))
    gross = a["byCase"]["gross"]
    out.append("- E9's blind rubric counts an answer that repeats the planted value but calls it doubtful or unconfirmed "
               "as flagging, not presenting. The gross plant's value (12.27 MPa) appears in the text of %d of %d A "
               "answers (the 2026-10-13 pattern match), none of which gives the source's value, and the checker found "
               "a contradicted statement in %d of them, for attributing the planted value to the source's table. The "
               "unit plant's A answers had one in %d of %d." % (
                   gross["mentionsPlanted"], gross["answers"], gross["answersContradicted"],
                   a["byCase"]["unit"]["answersContradicted"], a["byCase"]["unit"]["answers"]))
    return out


def write(value, out=None):
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(value, ensure_ascii=False, indent=1)
    if "/Users/" in text:
        raise SystemExit("refusing to write a local path into the results")
    (out / "results.json").write_text(text + "\n", encoding="utf-8")
    (out / "results.md").write_text(markdown(value), encoding="utf-8")
    return out


def main():
    parser = argparse.ArgumentParser(description="A5's results from the records only.")
    parser.add_argument("--root", type=Path, help="read the run folders here instead of .oopc/loop/harness/")
    parser.add_argument("--out", type=Path, help="write here instead of analysis/a5/")
    args = parser.parse_args()
    value = build(args.root)
    out = write(value, args.out)
    for p in value["predictions"]:
        print("%-6s %-12s %s" % (p["id"], p["verdict"][:12], p["numbers"]))
    print("cross-checks: %d compared, %d mismatches" % (value["crossChecks"]["compared"],
                                                       len(value["crossChecks"]["mismatches"])))
    print("wrote", out / "results.json", out / "results.md")


if __name__ == "__main__":
    main()
