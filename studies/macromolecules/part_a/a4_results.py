#!/usr/bin/env python3
"""A4's results (study plan, "Predictions, A4"): the similarity ladder from the records only, read with A2's held-out
strata for Fig. 4b. No engine call. No store is opened, except each A4 folder's own copy of an arm's store, read
immutable, for the locators of the saved findings an answer with a contradicted statement cited.

A4 asked 30 campaign first asks with findings in KF exactly, in other words (paraphrase) and as a sibling; the
researcher answered each on K0 (the 2026-10-01 store, 150 findings) and on KF, in two replicates, and one Codex checker
checked a question's two answers together on the day they were given (`2026-10-kf-ladder/r1-s1`, `r2-s1`). What it
reads, read only, under `.oopc/loop/harness/`:

- each A4 folder's `plan.json`, `items/*.json`, `pins.json`, `runs.jsonl` and `state.json`: per answer, the checker's
  measures recomputed from its statements as freeze-2's `reviewer.measures` does (`a5_results.measures`), and the new
  tokens, web calls and citations recorded with it;
- A2's folders (`2026-10-kf-scaling`), its K0 and KF items only: the held-out strata near, mid and far, the ladder's
  upper rungs with the same estimand (KF against K0, paired per question, answered and checked on the same day);
- the `rows.json` and `report.json` that `part_a.py report` wrote for both experiments, to cross-check every row, count
  and estimate (a disagreement is listed under `crossChecks.mismatches`, not corrected; A2's report only if it was
  written after its last folder finished);
- `analysis/loop-kf/revisits.json` (A1): the campaign revisits against their first asks, a different estimand, for
  comparison only.

Estimators (`estimate.py`, as pre-registered): per question each arm's replicates pooled (geometric mean of new tokens,
mean web calls, share with a sourced result); the median paired KF/K0 token ratio, the mean paired web-call difference
and the mean paired sourced-result difference, each with a bootstrap 95% interval over questions (2,000 draws, seed 7);
the web ratio, KF's mean web calls over K0's. The web ratio's interval (questions resampled the same way) is added here
for Fig. 4b; the plan gives it none.

Writes `analysis/a4/results.json` (KF's pins in `meta`, the records' own pins, a row per answer, per rung and stratum
summaries, the contradicted statements, the cross-checks and each prediction with its numbers and verdict) and
`results.md`. Everything is descriptive.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main checkout>/.oopc/study/freeze-2 python -B a4_results.py \
        [--root DIR] [--analysis DIR] [--out DIR]
"""
import argparse, collections, datetime as dt, json, math, random, re, sqlite3, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402
from analysis import kf  # noqa: E402
from part_a import a5_results, estimate  # noqa: E402
from oopc import knowledge  # noqa: E402  (the status labels only; no store is opened through it)

LADDER, SCALING = "2026-10-kf-ladder", "2026-10-kf-scaling"
RUNGS, STRATA = ["exact", "paraphrase", "sibling"], ["near", "mid", "far"]
ARM, REFERENCE = "KF", "K0"
ARMS = (REFERENCE, ARM)
CHECKED = ("contradicted", "complete", "resultGiven", "pass", "accessUncertain")
MODELS = {"codex": "gpt-6.1-sol", "claude-code": "claude-opus-5-5"}
TAG_COMMIT = "1c06a7f"
HARNESS_CODE = ["studies/macromolecules/driver.py", "studies/macromolecules/common.py",
                "studies/macromolecules/part_a/part_a.py", "studies/macromolecules/part_a/stores.py"]
REVISITS = "loop-kf/revisits.json"
OUT = common.analysis_dir("a4")
jread, maybe, median = a5_results.jread, a5_results.maybe, a5_results.median


# ----------------------------------------------------------------------------------------------- rows

def cited(workspace, ids):
    """{id: (locator, status label)} of the saved findings `ids` in an arm's store copy, read immutable (plain sqlite,
    not through `oopc`); {} if the copy is not there."""
    path = Path(workspace) / ".oopc/loop/knowledge.sqlite"
    if not ids or not path.exists():
        return {}
    db = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
    try:
        found = db.execute("SELECT id, locator, status FROM findings WHERE id IN (%s)" % ",".join("?" * len(ids)),
                           list(ids)).fetchall()
    finally:
        db.close()
    labels = getattr(knowledge, "STATUS_LABELS", {})
    return {i: (loc, labels.get(status, status)) for i, loc, status in found}


def answers(experiment, base, arms=ARMS):
    """One row per answer of `arms` in an experiment's folders, read from the items themselves (as `part_a.answers`
    reads them, without opening a store), and every contradicted statement with what its answer cited."""
    rows, statements = [], []
    for name in jread(base / "experiment.json")["folders"]:
        plan = jread(base / name / "plan.json")
        replicate = int(name[1:].split("-")[0])
        for index, q in enumerate(plan["questions"]):
            for arm in arms:
                item = maybe(base / name / "items" / ("%04d-%s.json" % (index, arm))) or {}
                answered, check = item.get("answer"), item.get("check")
                listed = a5_results.citations(answered)
                found = [c for c in listed if c.startswith("finding:")]
                own = "finding:%s-" % q["parent"][:12] if q.get("parent") else None
                row = dict({k: q.get(k) for k in ("id", "stratum", "kind", "parent", "material", "property")},
                           experiment=experiment, replicate=replicate, folder=name, arm=arm,
                           storeFindings=(plan["stores"].get(arm) or {}).get("findings"),
                           findingCitations=len(found),
                           parentCitations=sum(c.startswith(own) for c in found) if own else None,
                           **a5_results.answer_row(answered, check))
                rows.append(row)
                if not row["contradicted"]:
                    continue
                where = cited(base / name / "workspaces" / arm, found)
                for s in check.get("statements") or []:
                    if s.get("verdict") == a5_results.UNSUPPORTED and s.get("category") != "source-access":
                        statements.append(dict({k: row[k] for k in ("experiment", "replicate", "folder", "arm", "id",
                                                                    "stratum", "parent", "material", "property",
                                                                    "webCalls", "findingCitations",
                                                                    "parentCitations")},
                                               **{k: s.get(k) for k in ("kind", "category", "evidence", "statement",
                                                                        "reason")},
                                               citedFindings={i: {"locator": loc, "status": st}
                                                              for i, (loc, st) in sorted(where.items())}))
    return rows, statements


# ----------------------------------------------------------------------------------------------- estimates

def counts(rows):
    """Per arm: the check's measures (contradicted statements, complete, sourced result first; passes and
    access-uncertain statements second), answers citing saved findings (and the parent's own) or using no web call,
    median new tokens, and web calls (median, mean, total)."""
    value = {}
    for arm in ARMS:
        mine = [r for r in rows if r["arm"] == arm and r["answered"]]
        checked = [r for r in mine if r["checked"]]
        tokens = [r["newTokens"] for r in mine if r["newTokens"] is not None]
        web = [r["webCalls"] for r in mine if r["webCalls"] is not None]
        value[arm] = {"answered": len(mine), "checked": len(checked),
                      "contradicted": sum(r["contradicted"] or 0 for r in checked),
                      "answersContradicted": sum(bool(r["contradicted"]) for r in checked),
                      **{k: sum(r[k] is True for r in checked) for k in ("complete", "resultGiven", "pass")},
                      "accessUncertain": sum(r["accessUncertain"] or 0 for r in checked),
                      "citingFindings": sum(r["findingCitations"] > 0 for r in mine),
                      "citingParentFindings": sum((r["parentCitations"] or 0) > 0 for r in mine),
                      "noWeb": sum(r["webCalls"] == 0 for r in mine),
                      "medianNewTokens": median(tokens), "medianWebCalls": median(web),
                      "meanWebCalls": round(statistics.mean(web), 3) if web else None, "webCalls": sum(web)}
    return value


def pooled_pairs(rows):
    return [r for r in estimate.pooled(rows) if r.get(ARM) and r.get(REFERENCE)]


def web_ratio(rows):
    """KF's mean web calls over K0's on the questions both answered (the plan's web ratio, as `estimate.paired`), with
    a bootstrap 95% interval over questions (2,000 draws, seed 7, as `estimate.py`)."""
    pairs = [(r[ARM]["webCalls"], r[REFERENCE]["webCalls"]) for r in pooled_pairs(rows)
             if r[ARM]["webCalls"] is not None and r[REFERENCE]["webCalls"] is not None]
    if len(pairs) < 3:
        return None

    def ratio(sample):
        below = sum(b for _, b in sample)
        return sum(a for a, _ in sample) / below if below else None
    rng = random.Random(estimate.SEED)
    draws = sorted(x for x in (ratio(rng.choices(pairs, k=len(pairs))) for _ in range(estimate.DRAWS)) if x is not None)
    return {"n": len(pairs), "ratio": round(ratio(pairs), 3), "low": round(draws[int(0.025 * len(draws))], 3),
            "high": round(draws[int(0.975 * len(draws))], 3)}


def paired(rows):
    """KF against K0 by `estimate.paired`, plus the web ratio's interval, the token ratio unrounded, each question's
    pooled token ratio (Fig. 4b's points) and the token ratio per replicate."""
    value = estimate.paired(rows, ARM, REFERENCE)
    both = [r for r in pooled_pairs(rows) if r[ARM]["newTokens"] and r[REFERENCE]["newTokens"]]
    ratios = [r[ARM]["newTokens"] / r[REFERENCE]["newTokens"] for r in both]
    value["tokensUnrounded"] = math.exp(statistics.median(map(math.log, ratios))) if ratios else None
    value["webRatioInterval"] = web_ratio(rows)
    value["questionTokenRatios"] = sorted(round(x, 4) for x in ratios)
    value["byReplicate"] = {
        "r%d" % k: estimate.paired([r for r in rows if r["replicate"] == k], ARM, REFERENCE)["tokens"]
        for k in sorted({r["replicate"] for r in rows})}
    return value


def summarise(rows, groups):
    by = {}
    for group in groups + ["all"]:
        mine = [r for r in rows if group == "all" or r["stratum"] == group]
        by[group] = {"questions": len({r["id"] for r in mine}), "answers": len(mine), "arms": counts(mine),
                     "paired": paired(mine)}
    return by


# ----------------------------------------------------------------------------------------------- records

def git(*args):
    try:
        found = subprocess.run(["git", *args], cwd=common.STUDY, capture_output=True, text=True, check=True)
        return found.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def harness_changes(revisions):
    """The commits between the first and last harness revision a run used that touched the code an A4 or A2 answer
    goes through (`HARNESS_CODE`); None if git cannot tell."""
    ordered = [r for r in revisions if r]
    if len(set(ordered)) < 2:
        return []
    first, last = ordered[0], ordered[-1]
    found = git("log", "--format=%h %s", "%s..%s" % (first, last), "--", *HARNESS_CODE)
    return None if found is None else [line for line in found.splitlines() if line]


def records(base, kind):
    """Each folder's pins, runs, state and integrity: answers and checks given on one UTC day, earlier answers replaced,
    slept or failed attempts, the longest gap between a question's two answers."""
    folders, revisions, problems = {}, [], []
    for name in jread(base / "experiment.json")["folders"]:
        pins = jread(base / name / "pins.json")
        runs = [json.loads(line) for line in (base / name / "runs.jsonl").read_text().splitlines() if line.strip()]
        state = maybe(base / name / "state.json") or {}
        revisions += [pins["harness"]["revision"]] + [r["harness"]["revision"] for r in runs]
        expected = {"promptVersion": kf.PROMPT, "release": kf.RELEASE_ID, "knowledgeSnapshot": kf.SNAPSHOT_ID,
                    "kf": kf.FINGERPRINT, "models": MODELS, "tag": kf.TAG, "checker": "codex"}
        for key, want in expected.items():
            if pins.get(key) != want:
                problems.append({"where": "%s %s" % (kind, name), "what": "pin " + key, "records": pins.get(key),
                                 "expected": want})
        if not str(pins.get("tagCommit")).startswith(TAG_COMMIT) or pins["stores"].get(ARM) != kf.FINGERPRINT:
            problems.append({"where": "%s %s" % (kind, name), "what": "pin tagCommit or KF store",
                             "records": [pins.get("tagCommit"), pins["stores"].get(ARM)]})
        items = [jread(p) for p in sorted((base / name / "items").glob("*.json"))
                 if p.stem.split("-", 1)[1] in ARMS]
        times = collections.defaultdict(list)
        for i in items:
            times[i["question"]].append(dt.datetime.fromisoformat(i["answer"]["at"]))
        folders[name] = {
            "stores": pins["stores"], "checker": pins.get("checker"), "engines": pins.get("engines"),
            "preparedAt": pins.get("at"), "preparedBy": pins["harness"]["revision"][:12],
            "runs": [{"startedAt": r["startedAt"], "finishedAt": r.get("finishedAt"), "status": r.get("status"),
                      "stopReason": r.get("stopReason"), "harness": r["harness"]["revision"][:12]} for r in runs],
            "state": {k: state.get(k) for k in ("status", "failedItems", "startedAt", "finishedAt")},
            "items": len(items),
            "sameDay": sum(i["answer"]["at"][:10] == i["check"]["at"][:10] for i in items),
            "answerDays": sorted({i["answer"]["at"][:10] for i in items}),
            "previousAnswers": sum(bool(i.get("previousAnswers")) for i in items),
            "sleptAttempts": sum(bool(a.get("slept")) for i in items for a in i.get("attempts") or []),
            "failedAttempts": sum(a.get("outcome") != "completed" for i in items for a in i.get("attempts") or []),
            "longestGapHours": round(max((max(t) - min(t)).total_seconds() / 3600 for t in times.values()), 2),
            "models": sorted({"%s/%s" % (i["answer"].get("engine"), i["answer"].get("model")) for i in items}),
            "checkEngines": sorted({str(i["check"].get("engine")) for i in items})}
    distinct = list(dict.fromkeys(r[:12] for r in revisions))
    return {"folders": folders, "harnessRevisions": distinct, "harnessCodeChanges": harness_changes(distinct),
            "problems": problems}


def fresh(base):
    """`part_a.py report`'s rows and report for an experiment if the report was written after every folder finished
    and every folder completed; else None and why."""
    report, rows = maybe(base / "report.json"), maybe(base / "rows.json")
    if not report or rows is None:
        return None, "no report"
    states = [maybe(base / n / "state.json") or {} for n in jread(base / "experiment.json")["folders"]]
    if any(s.get("status") != "completed" for s in states):
        return None, "a folder has not completed"
    last = max(s["finishedAt"] for s in states)
    if report["at"] < last:
        return None, "report written at %s, before the last folder finished at %s" % (report["at"], last)
    return (rows, report), "written %s, after the last folder finished (%s)" % (report["at"], last)


SUMMARY_KEYS = ("answered", "checked", "contradicted", "accessUncertain", "complete", "resultGiven", "pass",
                "citingFindings", "noWeb", "medianNewTokens", "medianWebCalls")
ROW_KEYS = ("answered", "checked", "newTokens", "webCalls", "findingCitations", "storeFindings") + CHECKED


def cross_check(kind, mine, groups, found, mismatches):
    """My rows, counts and paired estimates against `part_a.py report`'s; returns how many values were compared."""
    rows, report = found
    theirs = {(r["folder"], r["id"], r["arm"]): r for r in rows if r["arm"] in ARMS}
    compared = 0
    if len(theirs) != len(mine["rows"]):
        mismatches.append({"where": kind, "what": "rows", "records": len(mine["rows"]), "report": len(theirs)})
    for row in mine["rows"]:
        other = theirs.get((row["folder"], row["id"], row["arm"])) or {}
        for key in ROW_KEYS:
            compared += 1
            if row[key] != other.get(key):
                mismatches.append({"where": "%s %s %s %s" % (kind, row["folder"], row["id"], row["arm"]), "what": key,
                                   "records": row[key], "report": other.get(key)})
    for group in groups + ["all"]:
        part = report["byStratum"].get(group) or {}
        for arm in ARMS:
            for key in SUMMARY_KEYS:
                compared += 1
                a, b = mine["by"][group]["arms"][arm][key], ((part.get("arms") or {}).get(arm) or {}).get(key)
                if a != b:
                    mismatches.append({"where": "%s %s %s" % (kind, group, arm), "what": key, "records": a,
                                       "report": b})
        other = (part.get("paired") or {}).get(ARM) or {}
        for key in ("tokens", "webCalls", "webRatio", "resultGiven"):
            compared += 1
            if mine["by"][group]["paired"][key] != other.get(key):
                mismatches.append({"where": "%s %s KF/K0" % (kind, group), "what": key,
                                   "records": mine["by"][group]["paired"][key], "report": other.get(key)})
    return compared


# ----------------------------------------------------------------------------------------------- predictions

def verdict(flags):
    return "met" if all(flags) else "not met" if not any(flags) else "partly met"


def fmt(t):
    return "%.2f (%.2f–%.2f)" % (t["median"], t["low"], t["high"])


def signed(text):
    """A typeset minus sign for negative numbers in prose."""
    return text.replace("-", "−")


def diff(d, places=1):
    return signed("%.*f (%.*f to %.*f)" % (places, d["mean"], places, d["low"], places, d["high"]))


def campaign(analysis=None):
    """The campaign revisits against their first asks (A1's records, a different estimand), per rung; refused unless
    built on KF."""
    data = jread(Path(analysis) / REVISITS if analysis else common.analysis_dir(REVISITS))
    meta = data["meta"]
    if (meta.get("knowledgeSnapshot"), meta.get("storeFingerprint")) != (kf.SNAPSHOT_ID, kf.FINGERPRINT):
        raise SystemExit("%s is not built on KF" % REVISITS)
    by = data["summary"]["campaignByType"]
    keys = ("pairs", "medianTokenRatio", "medianWebRatio", "totalsTokenRatio", "totalsWebRatio", "noWeb",
            "citingFindings")
    return {"source": REVISITS, "builtAt": meta["builtAt"],
            "byRung": {rung: {k: by[rung][k] for k in keys} for rung in RUNGS}}


def predictions(a4, a2, past):
    out = []

    def add(pid, prediction, flags, numbers, rule, value=None):
        out.append({"id": pid, "prediction": prediction, "verdict": verdict(flags), "numbers": numbers, "rule": rule,
                    "value": value or {}})
    by, near = a4["by"], a2["by"]["near"]["paired"]
    # A4.1
    flags, parts = [], []
    for rung in RUNGS:
        k0, kf_ = by[rung]["arms"][REFERENCE], by[rung]["arms"][ARM]
        more, fewer = kf_["contradicted"] - k0["contradicted"], k0["resultGiven"] - kf_["resultGiven"]
        flags += [more <= 1, fewer <= 3]
        parts.append("%s: contradicted KF %d against K0 %d (%s), sourced results KF %d against K0 %d of %d" % (
            rung, kf_["contradicted"], k0["contradicted"], signed("%+d" % more), kf_["resultGiven"],
            k0["resultGiven"], kf_["checked"]))
    c = a4["carried"]
    add("A4.1", "KF has at most 1 more contradicted statement than K0 in each rung, and at most 3 fewer sourced "
        "results.", flags, "; ".join(parts) + "." + (
            " %d of KF's %d contradicted statements (%s) repeat one page number from the saved findings of one parent, "
            "%s; without them KF has %s." % (c["statements"], c["of"], ", ".join(c["where"]), c["material"],
                                            ", ".join("%s %d" % kv for kv in c["others"].items()))
            if c and c["statements"] > 1 else ""),
        "each rung: KF − K0 contradicted ≤ 1 and K0 − KF sourced results ≤ 3; met if all six hold, not met if none, "
        "partly otherwise")
    # A4.2
    flags, parts = [], []
    for rung in RUNGS:
        t = by[rung]["paired"]["tokens"]
        flags += [t["median"] <= 0.75, t["high"] < 1, t["median"] <= near["tokens"]["median"]]
        parts.append("%s %s" % (rung, fmt(t)))
    top = max(RUNGS, key=lambda r: by[r]["paired"]["tokensUnrounded"])
    add("A4.2", "KF/K0 tokens at most 0.75 in every rung, each interval below 1 and each rung's median at or below "
        "A2's near KF/K0 (no order among the rungs predicted).", flags,
        "KF/K0 median paired token ratio %s; A2 near %s (unrounded, %s %.4f against near %.4f). Order: %s; the "
        "campaign records' was %s." % (
            ", ".join(parts), fmt(near["tokens"]), top, by[top]["paired"]["tokensUnrounded"],
            near["tokensUnrounded"], " < ".join(sorted(RUNGS, key=lambda r: by[r]["paired"]["tokensUnrounded"])),
            " < ".join("%s %.2f" % (r, past["byRung"][r]["medianTokenRatio"])
                       for r in sorted(RUNGS, key=lambda r: past["byRung"][r]["medianTokenRatio"]))),
        "each rung: median ≤ 0.75, interval's upper end < 1, median ≤ A2's near median (both as `estimate.paired` "
        "reports them, 3 decimals)")
    # A4.3
    flags, parts = [], []
    for rung in RUNGS:
        p = by[rung]["paired"]
        flags.append(p["webRatio"] < p["tokens"]["median"])
        parts.append("%s web %.2f (%.2f–%.2f) against tokens %.2f; paired web difference %s; KF without web %d of "
                     "%d" % (rung, p["webRatio"], p["webRatioInterval"]["low"], p["webRatioInterval"]["high"],
                             p["tokens"]["median"], diff(p["webCalls"]), by[rung]["arms"][ARM]["noWeb"],
                             by[rung]["arms"][ARM]["answered"]))
    flags += [by["exact"]["arms"][ARM]["noWeb"] >= 20, by["sibling"]["arms"][ARM]["noWeb"] >= 20]
    add("A4.3", "Web calls fall more than tokens in every rung (the KF/K0 ratio of mean web calls below the token "
        "ratio); KF answers without web at least 20 of 60 for exact and sibling.", flags,
        "%s. Campaign revisits (records, revisit/first ask): web, median of pair ratios, %s; ratio of totals %s." % (
            "; ".join(parts), ", ".join("%.2f" % past["byRung"][r]["medianWebRatio"] for r in RUNGS),
            ", ".join("%.2f" % past["byRung"][r]["totalsWebRatio"] for r in RUNGS)),
        "each rung: web ratio < token ratio; KF no-web answers ≥ 20 in exact and in sibling")
    # A4.4
    ladder_ = {r: by[r]["paired"] for r in RUNGS}
    held = {s: a2["by"][s]["paired"] for s in STRATA}

    def order(get):
        """What breaks the predicted order of one series: rungs above near, and mid or far not toward 1."""
        near_ = get(held["near"])
        above = [r for r in RUNGS if get(ladder_[r]) > near_]
        away = [s for s in ("mid", "far") if not (get(held[s]) > near_ and
                                                  abs(math.log(get(held[s]))) < abs(math.log(near_)))]
        return (["%s above near" % ", ".join(above)] if above else []) + (
            ["%s not toward 1" % ", ".join(away)] if away else [])
    tokens_off, web_off = order(lambda p: p["tokens"]["median"]), order(lambda p: p["webRatio"])
    add("A4.4", "Fig. 4b, read with A2: the three rungs lowest, then near, with mid and far toward 1.",
        [not tokens_off, not web_off],
        "Tokens (KF/K0 median paired ratio): %s; near %s, mid %s, far %s. Web calls (ratio of means): %s; near %.2f, "
        "mid %.2f, far %.2f. The token order %s; the web order %s." % (
            ", ".join("%s %.2f" % (r, ladder_[r]["tokens"]["median"]) for r in RUNGS), fmt(held["near"]["tokens"]),
            fmt(held["mid"]["tokens"]), fmt(held["far"]["tokens"]),
            ", ".join("%s %.2f" % (r, ladder_[r]["webRatio"]) for r in RUNGS), held["near"]["webRatio"],
            held["mid"]["webRatio"], held["far"]["webRatio"],
            "does not hold (%s)" % "; ".join(tokens_off) if tokens_off else "holds",
            "does not hold (%s)" % "; ".join(web_off) if web_off else "holds"),
        "for tokens and for web calls (the two series Fig. 4b draws): every rung at or below near, and mid and far "
        "each above near and closer to 1 (in log) than near; met if both series, partly met if one, not met if neither")
    return out


# ----------------------------------------------------------------------------------------------- build and write

def experiment(kind, name, groups, root=None):
    base = a5_results.run_dir(name, root)
    rows, statements = answers(kind, base)
    return {"base": base, "rows": rows, "contradictedStatements": statements,
            "carried": carried(statements) if kind == "A4" else None,
            "by": summarise(rows, groups), "records": records(base, kind)}


def build(root=None, analysis=None):
    """Everything `write` writes: from the run folders under `root` (default .oopc/loop/harness/) and A1's
    revisits under `analysis` (default analysis/)."""
    a4 = experiment("A4", LADDER, RUNGS, root)
    a2 = experiment("A2", SCALING, STRATA, root)
    mismatches, compared, reports = list(a4["records"]["problems"] + a2["records"]["problems"]), 0, {}
    for kind, mine, groups in (("A4", a4, RUNGS), ("A2", a2, STRATA)):
        found, why = fresh(mine["base"])
        reports[kind] = why
        if found:
            compared += cross_check(kind, mine, groups, found, mismatches)
        elif kind == "A4":
            mismatches.append({"where": "A4", "what": "part_a report", "records": why})
    past = campaign(analysis)
    meta = dict(kf.meta("part_a/a4_results.py"), analysisRevision=a5_results.revision(),
                records={"A4": LADDER, "A2": SCALING + " (K0 and KF only)", "campaign": REVISITS})
    out = {"meta": meta}
    for kind, mine in (("A4", a4), ("A2", a2)):
        out[kind] = {k: v for k, v in mine.items() if k != "base"}
        out[kind]["by" + ("Rung" if kind == "A4" else "Stratum")] = out[kind].pop("by")
    out["campaign"] = past
    out["crossChecks"] = {"compared": compared, "mismatches": mismatches, "partAReports": reports}
    out["predictions"] = predictions(a4, a2, past)
    return out


def k(v):
    return "–" if v is None else "%.1fk" % (v / 1e3)


TABLE = ("| Arm | Answers | Contradicted (answers) | Complete | Sourced result | Citing findings (the parent's) | "
         "No web | Median new tokens | Web calls, mean (median) | Passes | Access-uncertain |")


def arm_rows(part):
    lines = [TABLE, "| --- |" + " ---: |" * 10]
    for arm in ARMS:
        s = part["arms"][arm]
        lines.append("| %s | %d | %d (%d) | %d | %d | %d (%d) | %d | %s | %.2f (%g) | %d | %d |" % (
            arm, s["answered"], s["contradicted"], s["answersContradicted"], s["complete"], s["resultGiven"],
            s["citingFindings"], s["citingParentFindings"], s["noWeb"], k(s["medianNewTokens"]), s["meanWebCalls"],
            s["medianWebCalls"], s["pass"], s["accessUncertain"]))
    p = part["paired"]
    lines += ["", "KF/K0, paired over %d questions: tokens %s (by replicate, r%s); web ratio %.2f (%.2f–%.2f); web "
              "difference %s calls per answer; sourced-result difference %s." % (
                  p["tokens"]["n"], fmt(p["tokens"]), ", r".join("%s %.2f" % (r[1:], t["median"])
                                                                 for r, t in p["byReplicate"].items()),
                  p["webRatio"], p["webRatioInterval"]["low"], p["webRatioInterval"]["high"], diff(p["webCalls"], 2),
                  signed("%+.3f (%.3f to %.3f)" % (p["resultGiven"]["mean"], p["resultGiven"]["low"],
                                                   p["resultGiven"]["high"]))), ""]
    return lines


def ladder_table(value):
    """Fig. 4b's data: A4's rungs and A2's strata, KF against K0."""
    lines = ["| Rung | Questions × replicates | KF/K0 tokens | Web ratio | Web difference | KF without web | "
             "Contradicted, K0 / KF | Sourced result, K0 / KF |", "| --- | --- |" + " ---: |" * 6]
    for kind, groups, key in (("A4", RUNGS, "byRung"), ("A2", STRATA, "byStratum")):
        for g in groups:
            part = value[kind][key][g]
            p, k0, kf_ = part["paired"], part["arms"][REFERENCE], part["arms"][ARM]
            lines.append("| %s (%s) | %d × %d | %s | %.2f (%.2f–%.2f) | %s | %d of %d | %d / %d | %d / %d |" % (
                g, kind, part["questions"], part["answers"] // (2 * part["questions"]), fmt(p["tokens"]),
                p["webRatio"], p["webRatioInterval"]["low"], p["webRatioInterval"]["high"], diff(p["webCalls"], 2),
                kf_["noWeb"], kf_["answered"], k0["contradicted"], kf_["contradicted"], k0["resultGiven"],
                kf_["resultGiven"]))
    return lines


def markdown(value):
    m, a4 = value["meta"], value["A4"]
    cc = value["crossChecks"]
    lines = ["# A4 results: the similarity ladder", "",
             "Drawn from the records only by `studies/macromolecules/part_a/a4_results.py` (revision %s) on %s; no "
             "engine call. Code `%s`, prompt `%s`, KF `%s`; researcher and checker Codex `%s`. 30 campaign first asks "
             "with findings in KF, each asked exactly, in other words and as a sibling, answered on K0 (150 findings) "
             "and KF (8,899), two replicates: 60 answers per rung and arm. Each question's two answers were given in "
             "turn and checked together the same day. Paired per question, replicates pooled first; intervals are "
             "bootstrap 95%% over questions. Quality leads with contradicted statements, complete answers and sourced "
             "results; passes and access-uncertain statements come second." % (
                 m["analysisRevision"], m["builtAt"], m["codeTag"], m["prompt"], m["knowledgeSnapshot"],
                 MODELS["codex"]), ""]
    if cc["mismatches"]:
        lines += ["**Cross-check against `part_a.py report`: %d mismatches** (see results.json)." % len(
            cc["mismatches"]), ""]
    else:
        lines += ["Cross-checked against `part_a.py report`'s rows, counts and estimates for A4 and A2: %d values, "
                  "no mismatch (A2's report %s)." % (cc["compared"], cc["partAReports"]["A2"]), ""]
    for rung in RUNGS:
        lines += ["## %s (%d questions)" % (rung.capitalize(), a4["byRung"][rung]["questions"]), ""] + arm_rows(
            a4["byRung"][rung])
    lines += ["## All three rungs (%d questions)" % a4["byRung"]["all"]["questions"], ""] + arm_rows(
        a4["byRung"]["all"])
    lines += ["## The ladder, KF against K0 (Fig. 4b): A4's rungs, then A2's held-out strata", "",
              "A2's rows are its K0 and KF arms only (answered beside six other arms, checked the same day). The web "
              "ratio is KF's mean web calls over K0's; its interval resamples questions as the others do.", ""]
    lines += ladder_table(value)
    lines += ["", "## The predictions", ""]
    for p in value["predictions"]:
        lines.append("- **%s, %s.** %s %s" % (p["id"], p["verdict"], p["prediction"], p["numbers"]))
    lines += ["", "Verdict rules: " + " ".join("%s: %s." % (p["id"], p["rule"]) for p in value["predictions"]), "",
              "## Notes", ""] + notes(value)
    return "\n".join(lines) + "\n"


def carried(statements):
    """KF's contradicted statements on the parent with most of them: where they fall, the saved findings their answers
    cited (distinct, with status), and how many of those findings' locators name the page a statement gives."""
    mine = [s for s in statements if s["arm"] == ARM]
    groups = collections.Counter((s["parent"], s["material"], s["property"]) for s in mine)
    if not groups:
        return None
    (parent, material, prop), n = groups.most_common(1)[0]
    same = [s for s in mine if s["parent"] == parent]
    findings = {i: f for s in same for i, f in s["citedFindings"].items()}
    pages = {m.group(1) for s in same for m in [re.search(r"(?:page|p\.)\s*(\d+)", s["statement"] or "")] if m}
    return {"parent": parent, "material": material, "property": prop, "statements": n, "of": len(mine),
            "where": ["%s r%d" % (s["stratum"], s["replicate"]) for s in same],
            "webCalls": [s["webCalls"] for s in same], "parentCitations": [s["parentCitations"] for s in same],
            "findings": len(findings), "statuses": dict(collections.Counter(f["status"] for f in findings.values())),
            "pages": sorted(pages), "locatorsNamingPage": sum(any(("p. %s" % p) in (f["locator"] or "") for p in pages)
                                                             for f in findings.values()),
            "reason": same[0]["reason"],
            "others": {r: sum(1 for s in mine if s["stratum"] == r and s["parent"] != parent) for r in RUNGS}}


def notes(value):
    a4, past = value["A4"], value["campaign"]
    out = []
    contra = a4["contradictedStatements"]
    by_arm = {arm: [s for s in contra if s["arm"] == arm] for arm in ARMS}
    kinds = {arm: collections.Counter("%s/%s" % (s["kind"], s["category"]) for s in v) for arm, v in by_arm.items()}
    c = a4["carried"]
    out.append("- Contradicted statements (the checker's kind/category): K0 %d (%s), KF %d (%s). %d of KF's %d are on "
               "one parent, %s (%s), in %s. Those answers made %s web calls and cited %s of that parent's saved "
               "findings; %d of the %d distinct findings they cited (%s) give page %s in their locator, the page each "
               "statement repeated, and the checker found the table on another page in all %d checks (first reason: "
               "“%s”). The page came from the saved findings, whose reviews did not catch it. Without that parent, "
               "KF has %s contradicted statements, against K0's %s." % (
                   len(by_arm[REFERENCE]), ", ".join("%s %d" % kv for kv in sorted(kinds[REFERENCE].items())),
                   len(by_arm[ARM]), ", ".join("%s %d" % kv for kv in sorted(kinds[ARM].items())), c["statements"],
                   c["of"], c["material"], c["property"], ", ".join(c["where"]), "/".join(map(str, c["webCalls"])),
                   "/".join(map(str, c["parentCitations"])), c["locatorsNamingPage"], c["findings"],
                   ", ".join("%s %d" % kv for kv in sorted(c["statuses"].items())), "/".join(c["pages"]),
                   c["statements"], c["reason"],
                   ", ".join("%s %d" % kv for kv in c["others"].items()),
                   ", ".join("%s %d" % (r, sum(1 for s in by_arm[REFERENCE] if s["stratum"] == r)) for r in RUNGS)))
    near = value["A2"]["byStratum"]["near"]["paired"]["tokens"]
    out.append("- Paraphrase and sibling sit with A2's near stratum (KF/K0 %s and %s against near %s; the intervals "
               "overlap), and the exact repeat is cheaper (%s). In the study plan every near held-out question has its "
               "campaign parent's findings in KF, so near questions are siblings of a kind." % (
                   fmt(a4["byRung"]["paraphrase"]["paired"]["tokens"]),
                   fmt(a4["byRung"]["sibling"]["paired"]["tokens"]),
                   fmt(near), fmt(a4["byRung"]["exact"]["paired"]["tokens"])))
    cr = past["byRung"]
    lower_tokens = [r for r in RUNGS if a4["byRung"][r]["paired"]["tokens"]["median"] < cr[r]["medianTokenRatio"]]
    lower_web = [r for r in RUNGS if a4["byRung"][r]["paired"]["webRatio"] < cr[r]["totalsWebRatio"]]
    out.append("- The campaign records (`%s`: each revisit against its own first ask, %s pairs, the first ask under an "
               "earlier prompt and on the store of its day) are a different estimand from A4's KF against K0, same "
               "day and prompt, and are not pooled with it: tokens %s (median of pair ratios), web %s (median of pair "
               "ratios) or %s (ratio of totals, A4's estimator), revisits without web %s. A4's token ratio is lower "
               "in %s of 3 rungs and its web ratio below the campaign's ratio of totals in %s of 3. The two differ in "
               "the reference arm's store and prompt, so the gap is not read as an effect of either." % (
                   past["source"], "/".join(str(cr[r]["pairs"]) for r in RUNGS),
                   ", ".join("%.2f" % cr[r]["medianTokenRatio"] for r in RUNGS),
                   ", ".join("%.2f" % cr[r]["medianWebRatio"] for r in RUNGS),
                   ", ".join("%.2f" % cr[r]["totalsWebRatio"] for r in RUNGS),
                   ", ".join("%d of %d" % (cr[r]["noWeb"], cr[r]["pairs"]) for r in RUNGS),
                   len(lower_tokens), len(lower_web)))
    rec = a4["records"]
    f = rec["folders"]
    out.append("- Records: %s. Every item answered and checked on one UTC day (%s); no answer replaced; %d slept "
               "and %d failed attempts, each retried; the longest gap between a question's two answers %s h. Harness "
               "revisions over the runs: %s; commits between them touching the driver or Part A's code: %s." % (
                   "; ".join("%s %s, %d items, failed %s, answered %s" % (name, v["state"]["status"], v["items"],
                                                                          v["state"]["failedItems"],
                                                                          "/".join(v["answerDays"]))
                             for name, v in f.items()),
                   ", ".join("%s %d of %d" % (name, v["sameDay"], v["items"]) for name, v in f.items()),
                   sum(v["sleptAttempts"] for v in f.values()), sum(v["failedAttempts"] for v in f.values()),
                   " and ".join("%.2f" % v["longestGapHours"] for v in f.values()),
                   ", ".join(rec["harnessRevisions"]),
                   "unknown" if rec["harnessCodeChanges"] is None else (
                       ", ".join(rec["harnessCodeChanges"]) or "none")))
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
    parser = argparse.ArgumentParser(description="A4's results from the records only.")
    parser.add_argument("--root", type=Path, help="read the run folders here instead of .oopc/loop/harness/")
    parser.add_argument("--analysis", type=Path, help="read A1's loop-kf/revisits.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write here instead of analysis/a4/")
    args = parser.parse_args()
    value = build(args.root, args.analysis)
    out = write(value, args.out)
    for p in value["predictions"]:
        print("%-5s %-11s %s" % (p["id"], p["verdict"], p["numbers"]))
    print("cross-checks: %d compared, %d mismatches" % (value["crossChecks"]["compared"],
                                                       len(value["crossChecks"]["mismatches"])))
    print("wrote", out / "results.json", out / "results.md")


if __name__ == "__main__":
    main()
