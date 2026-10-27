#!/usr/bin/env python3
"""A2, A3 and E8's results (study plan, "Predictions, A2", "Predictions, A3" and "Predictions, E8"), from the records
only: each experiment's pre-registered report (`part_a.py report`: `report.json`, with every estimator of
`estimate.py`, and `rows.json`, one row per answer), its layout (`experiment.json`) and each run folder's pins. No
engine call, no store is opened, and nothing under the run folders is written.

- A2 `2026-10-kf-scaling` (Fig. 4a, 4c): test 1's 60 held-out questions × P, K0, KF200, KF1, KF2, KF (web on) and MF1,
  MF (web off); three replicates.
- A3 `2026-10-kf-resampled` (Fig. 4c): the 60 questions on 20 resampled stores (100, 200, 400 and 800 of KF's
  questions × 5 seeds) with K0 and KF as same-day anchors; one replicate.
- E8 `2026-10-kf-e8` (Fig. 4a's cross-engine panel): the 20 near questions answered by the researcher on Claude Code,
  K0c and KFc, checked by the Codex checker; one replicate. It is set beside A2's Codex K0 and KF on the same 20
  questions (across days, descriptive).

Every number a prediction names is read from the reports, or computed from the rows with `estimate.py`'s estimators
unchanged. Three additions, none of which replaces a pre-registered estimator:

- *Time ratios* (Fig. 4a asks for "tokens (and time)"): `estimate.paired` with each answer's seconds in place of its
  new tokens, i.e. the same pooling (geometric mean over replicates) and median paired ratio with its interval.
- *Pass on store size, sensitivity*: the pre-registered fit is statsmodels' variational Bayes mixed logistic
  regression, whose posterior standard deviations are known to be too small. Beside it, a population-averaged logistic
  regression (GEE, exchangeable correlation within question, robust intervals) on the same answers, and the same fit on
  the answers without an access-uncertain statement, to show how much of a pass difference is source access.
- *Diagnostics read from the check items* (`items/*.json`, read only): the kind and category of each contradicted
  statement per arm, and the number of statements per check, for A2 and E8; they explain verdicts, they decide none.

Writes `analysis/a2a3e8/results.json` (KF's pins in `meta`, the records' own pins, per arm and stratum counts, every
paired comparison, the estimates, and each prediction with its parts, numbers and verdict) and `results.md` (tables,
then each prediction judged). A prediction is met when every part holds, not met when none does, partly met otherwise.
With 20 questions per stratum, only large effects are detectable; everything here is descriptive.

    OOPC_STUDY_ROOT=<main checkout> python -B a2a3e8_results.py [--root DIR] [--out DIR]
"""
import argparse, collections, json, math, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402
from analysis import kf  # noqa: E402
from part_a import estimate  # noqa: E402

FOLDERS = {"A2": "2026-10-kf-scaling", "A3": "2026-10-kf-resampled", "E8": "2026-10-kf-e8"}
STRATA = ("near", "mid", "far")
WEB_ON = ("K0", "KF200", "KF1", "KF2", "KF")  # A2's researcher arms with web on, one per store size
MEMORY = ("MF1", "MF")  # A2's researcher arms with web off, on KF1 and KF
A2_ARMS = ("P",) + WEB_ON + MEMORY
E8_ARMS = ("K0c", "KFc")
SIZES, SEEDS = (100, 200, 400, 800), (1, 2, 3, 4, 5)
COUNTED = ("contradicted", "complete", "resultGiven", "pass", "accessUncertain", "citingFindings", "noWeb")
PIN_KEYS = ("tag", "tagCommit", "promptVersion", "models", "release", "knowledgeSnapshot", "kf", "checker", "engines",
            "stores", "replicate", "shard", "at")
OUT = common.analysis_dir("a2a3e8")


def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe(path):
    return jread(path) if Path(path).exists() else None


def run_dir(name, root=None):
    return Path(root) / name if root else common.run_dir(name)


def store_name(size, seed):
    return "R%d-s%d" % (size, seed)


def r3(value):
    return None if value is None else round(value, 3)


# ----------------------------------------------------------------------------------------------- records

def load(experiment, root=None):
    """An experiment's layout, report, rows and each folder's pins (without local paths)."""
    base = run_dir(FOLDERS[experiment], root)
    layout, report, rows = jread(base / "experiment.json"), jread(base / "report.json"), jread(base / "rows.json")
    pins = {}
    for name in layout["folders"]:
        found = maybe(base / name / "pins.json") or {}
        runs = [json.loads(line) for line in (base / name / "runs.jsonl").read_text().splitlines() if line.strip()] \
            if (base / name / "runs.jsonl").exists() else []
        pins[name] = dict({k: found[k] for k in PIN_KEYS if k in found},
                          harnessRevision=(found.get("harness") or {}).get("revision"),
                          harnessClean=(found.get("harness") or {}).get("clean"),
                          runRevisions=sorted({(r.get("harness") or {}).get("revision") for r in runs} - {None}),
                          runsClean=all((r.get("harness") or {}).get("clean") for r in runs),
                          ranFrom=min((r["startedAt"] for r in runs if r.get("startedAt")), default=None),
                          ranTo=max((r["finishedAt"] for r in runs if r.get("finishedAt")), default=None))
    return {"base": base, "layout": layout, "report": report, "rows": rows, "pins": pins}


def completeness(data):
    """Whether every answer of the layout is in the rows, answered and checked, and every folder completed."""
    rows, folders = data["rows"], data["report"]["folders"]
    return {"expected": data["layout"]["answers"], "rows": len(rows), "answered": sum(r["answered"] for r in rows),
            "checked": sum(r["checked"] for r in rows),
            "folders": {name: {k: f.get(k) for k in ("items", "done", "failed", "state")} for name, f in folders.items()}}


def summary(rows):
    """Per arm, the report's counts recomputed from the rows (as `part_a.summary`), for the cross-check, with the mean
    web calls per answer (Fig. 4a's web calls) added."""
    value = {}
    for arm in dict.fromkeys(r["arm"] for r in rows):
        mine = [r for r in rows if r["arm"] == arm and r["answered"]]
        checked = [r for r in mine if r["checked"]]
        web = [r["webCalls"] for r in mine if r["webCalls"] is not None]
        value[arm] = {"answered": len(mine), "checked": len(checked),
                      **{k: sum(r[k] or 0 for r in checked) for k in ("contradicted", "accessUncertain")},
                      "answersContradicted": sum(bool(r["contradicted"]) for r in checked),
                      **{k: sum(r[k] is True for r in checked) for k in ("complete", "resultGiven", "pass")},
                      "citingFindings": sum(r["findingCitations"] > 0 for r in mine),
                      "noWeb": sum(r["webCalls"] == 0 for r in mine),
                      "medianNewTokens": statistics.median(r["newTokens"] for r in mine if r["newTokens"]) if mine else None,
                      "meanWebCalls": r3(statistics.mean(web)) if web else None,
                      "questions": len({r["id"] for r in mine})}
    return value


def arm_table(report_part, rows):
    """Per arm: the report's counts, with the mean web calls and questions from the rows; mismatches listed."""
    found, mismatches = summary(rows), []
    out = {}
    for arm, counts in report_part["arms"].items():
        mine = found.get(arm, {})
        for key in ("answered", "checked") + COUNTED + ("medianNewTokens",):
            if counts.get(key) != mine.get(key):
                mismatches.append({"arm": arm, "what": key, "report": counts.get(key), "rows": mine.get(key)})
        out[arm] = dict(counts, meanWebCalls=mine.get("meanWebCalls"), questions=mine.get("questions"),
                        answersContradicted=mine.get("answersContradicted"))
    return out, mismatches


def seconds_ratio(rows, arm, reference):
    """`estimate.paired`'s token ratio with each answer's seconds as its new tokens: the paired time ratio."""
    swapped = [dict(r, newTokens=r["seconds"]) for r in rows]
    return estimate.paired(swapped, arm, reference)["tokens"]


def by_stratum(data, arms, reference):
    """Per stratum and overall: each arm's counts, every arm paired against the reference and the report's further
    pairs, each with its time ratio added."""
    report, rows, out, mismatches = data["report"], data["rows"], {}, []
    for stratum in STRATA + ("all",):
        if stratum not in report["byStratum"]:
            continue
        part = report["byStratum"][stratum]
        mine = [r for r in rows if stratum == "all" or r["stratum"] == stratum]
        table, wrong = arm_table(part, mine)
        mismatches += [dict(m, stratum=stratum) for m in wrong]
        paired = {arm: dict(part["paired"][arm], seconds=seconds_ratio(mine, arm, reference))
                  for arm in arms if arm in part["paired"]}
        pairs = {name: dict(v, seconds=seconds_ratio(mine, *name.split("/"))) for name, v in part["pairs"].items()}
        out[stratum] = {"arms": {arm: table[arm] for arm in arms if arm in table}, "paired": paired, "pairs": pairs}
    return out, mismatches


def pass_sensitivity(rows):
    """Pass on log store findings, population-averaged (GEE, exchangeable within question, robust 95% intervals),
    stratum fixed; on all answers and on those without an access-uncertain statement."""
    try:
        import pandas
        import statsmodels.api as sm
        import statsmodels.formula.api as smf
    except ImportError as error:
        return {"unavailable": str(error)}
    import warnings
    data = [r for r in rows if r["checked"] and r.get("storeFindings")]
    out = {}
    for name, keep in (("all", lambda r: True), ("withoutAccessUncertain", lambda r: not r["accessUncertain"])):
        mine = [r for r in data if keep(r)]
        frame = pandas.DataFrame({"passed": [int(r["pass"] is True) for r in mine],
                                  "logf": [math.log(r["storeFindings"]) for r in mine],
                                  "stratum": [r["stratum"] for r in mine], "question": [r["id"] for r in mine]})
        formula = "passed ~ logf + C(stratum)" if frame["stratum"].nunique() > 1 else "passed ~ logf"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit = smf.gee(formula, "question", frame, family=sm.families.Binomial(),
                              cov_struct=sm.cov_struct.Exchangeable()).fit()
                low, high = fit.conf_int().loc["logf"].tolist()
            out[name] = {"answers": len(mine), "passes": int(frame["passed"].sum()),
                         "estimate": round(float(fit.params["logf"]), 4), "low": round(low, 4), "high": round(high, 4),
                         "method": "GEE Binomial, exchangeable, robust"}
        except Exception as error:  # a fit that does not converge is reported, not raised
            out[name] = {"error": str(error)[:300]}
    return out


def contradicted_kinds(base, folders):
    """Diagnostic, read from the check items (not the rows): per arm, the contradicted statements by the checker's
    statement kind and category, and the median number of statements per check."""
    kinds, statements = collections.defaultdict(collections.Counter), collections.defaultdict(list)
    for name in folders:
        for path in sorted((Path(base) / name / "items").glob("*.json")):
            arm = path.stem.split("-", 1)[1]
            check = (jread(path).get("check") or {})
            found = [s for s in check.get("statements") or [] if isinstance(s, dict)]
            if not check.get("verdict"):
                continue
            statements[arm].append(len(found))
            for s in found:
                if s.get("verdict") == "unsupported" and s.get("category") != "source-access":
                    kinds[arm]["%s/%s" % (s.get("kind") or "unspecified", s.get("category") or "unspecified")] += 1
    return {arm: {"medianStatements": statistics.median(v), "contradicted": dict(sorted(kinds[arm].items()))}
            for arm, v in statements.items()}


def spearman(xs, ys):
    """Spearman's rank correlation (average ranks for ties) over the pairs with both values; None when either side is
    constant."""
    kept = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    xs, ys = [x for x, _ in kept], [y for _, y in kept]
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out, i = [0.0] * len(values), 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    a, b = ranks(xs), ranks(ys)
    ma, mb = statistics.mean(a), statistics.mean(b)
    sa, sb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if not sa or not sb:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sa * sb), 3)


# ----------------------------------------------------------------------------------------------- A2

def passes_by_replicate(rows, arms):
    """Per stratum and replicate, each arm's passes (of 20), and the spread among A2's web-on researcher arms."""
    out = {}
    for stratum in STRATA:
        out[stratum] = {}
        for rep in sorted({r["replicate"] for r in rows}):
            cell = {arm: sum(r["pass"] is True for r in rows if r["stratum"] == stratum and r["replicate"] == rep
                             and r["arm"] == arm and r["checked"]) for arm in arms}
            web_on = [cell[a] for a in WEB_ON if a in cell]
            out[stratum][str(rep)] = dict(cell, spread=max(web_on) - min(web_on))
    return out


def non_passes(rows, arms):
    """Per arm and stratum, the answers that did not pass: with an access-uncertain statement and no contradicted
    one, with a contradicted statement, and the rest (incomplete or no sourced result alone)."""
    out = {}
    for arm in arms:
        out[arm] = {}
        for stratum in STRATA + ("all",):
            mine = [r for r in rows if r["arm"] == arm and r["checked"] and r["pass"] is not True
                    and (stratum == "all" or r["stratum"] == stratum)]
            access = sum(bool(r["accessUncertain"]) and not r["contradicted"] for r in mine)
            contra = sum(bool(r["contradicted"]) for r in mine)
            out[arm][stratum] = {"nonPasses": len(mine), "accessUncertainOnly": access, "contradicted": contra,
                                 "other": len(mine) - access - contra}
    return out


def geometric_ratio(rows, arm, reference):
    """Descriptive: the geometric mean over questions of `arm`'s pooled tokens over `reference`'s (beside the
    pre-registered median, which a two-group distribution such as KF2's near ratios can put between the groups)."""
    logs = [math.log(r[arm]["newTokens"] / r[reference]["newTokens"]) for r in estimate.pooled(rows)
            if (r.get(arm) or {}).get("newTokens") and (r.get(reference) or {}).get("newTokens")]
    return r3(math.exp(statistics.mean(logs))) if logs else None


def a2(data):
    rows = data["rows"]
    strata, mismatches = by_stratum(data, A2_ARMS, "K0")
    web_on = [r for r in rows if r["web"] and r["arm"] in WEB_ON and r["storeFindings"]]
    return {"arms": list(A2_ARMS), "replicates": data["layout"]["replicates"],
            "storeFindings": {arm: next((r["storeFindings"] for r in rows if r["arm"] == arm), None) for arm in A2_ARMS},
            "complete": completeness(data), "byStratum": strata,
            "estimates": data["report"]["estimates"], "passSensitivity": pass_sensitivity(web_on),
            "passesByReplicate": passes_by_replicate(rows, A2_ARMS), "nonPasses": non_passes(rows, A2_ARMS),
            "nearGeometricMeanRatio": {a: geometric_ratio([r for r in rows if r["stratum"] == "near"], a, "K0")
                                       for a in WEB_ON if a != "K0"},
            "contradictedKinds": contradicted_kinds(data["base"], data["layout"]["folders"])}, mismatches


# ----------------------------------------------------------------------------------------------- A3

def a3(data, a2v):
    report, rows = data["report"], data["rows"]
    strata, mismatches = by_stratum(data, ["K0", "KF"] + [store_name(z, s) for s in SEEDS for z in SIZES], "K0")
    findings = dict(report["storeFindings"],
                    **{arm: next(r["storeFindings"] for r in rows if r["arm"] == arm) for arm in ("K0", "KF")})
    stores = {}
    for arm in ["K0", "KF"] + [store_name(z, s) for z in SIZES for s in SEEDS]:
        size, seed = (None, None) if arm in ("K0", "KF") else (int(arm[1:].split("-")[0]), int(arm.split("-s")[1]))
        stores[arm] = {
            "findings": findings[arm], "size": size, "seed": seed,
            "nearParents": len({r["id"] for r in rows if r["arm"] == arm and r["stratum"] == "near" and r["parentInStore"]}),
            "byStratum": {s: dict(strata[s]["arms"][arm], tokensVsK0=(strata[s]["paired"].get(arm) or {}).get("tokens"),
                                  webVsK0=(strata[s]["paired"].get(arm) or {}).get("webCalls"))
                          for s in STRATA + ("all",)}}
    by_size = {}
    for z in SIZES:
        mine = [stores[store_name(z, s)] for s in SEEDS]
        by_size[str(z)] = {
            "findings": [m["findings"] for m in mine], "nearParents": [m["nearParents"] for m in mine],
            "nearCiting": [m["byStratum"]["near"]["citingFindings"] for m in mine],
            **{s: {k: sum(m["byStratum"][s][k] for m in mine) for k in COUNTED + ("answered",)} for s in STRATA + ("all",)}}
    spread = {}
    for key, medians in report["estimates"]["seedSpread"].items():
        spread[key] = {"medians": medians, "maxOverMin": r3(max(medians) / min(medians))}
    resampled = [store_name(z, s) for z in SIZES for s in SEEDS]
    parents = [stores[a]["nearParents"] for a in resampled]
    citing = [stores[a]["byStratum"]["near"]["citingFindings"] for a in resampled]
    near_ratio = [(stores[a]["byStratum"]["near"]["tokensVsK0"] or {}).get("median") for a in resampled]
    a2_reps = a2v["estimates"]["byReplicate"]
    anchors = {s: {"A3": strata[s]["paired"]["KF"]["tokens"],
                   "A2replicates": {rep: v["median"] for rep, v in a2_reps[s].items()},
                   "A2range": [min(v["median"] for v in a2_reps[s].values()),
                               max(v["median"] for v in a2_reps[s].values())]} for s in STRATA}
    return {"stores": stores, "bySize": by_size, "complete": completeness(data), "byStratum": strata,
            "estimates": dict(report["estimates"], seedSpread=spread),
            "passSensitivity": pass_sensitivity([r for r in rows if r["web"] and r["storeFindings"]]),
            "track": {"parentsVsCiting": spearman(parents, citing),
                      "parentsVsNearTokenRatio": spearman(parents, near_ratio)},
            "anchors": anchors}, mismatches


# ----------------------------------------------------------------------------------------------- E8

def e8(data, a2data):
    rows = data["rows"]
    strata, mismatches = by_stratum(data, list(E8_ARMS), "K0c")
    ids = {r["id"] for r in rows}
    codex = [r for r in a2data["rows"] if r["id"] in ids and r["arm"] in ("K0", "KF")]
    codex_near = {r["id"] for r in a2data["rows"] if r["stratum"] == "near"}
    per_rep = {}
    for rep in sorted({r["replicate"] for r in codex}):
        found = summary([r for r in codex if r["replicate"] == rep])
        per_rep[str(rep)] = {arm: {k: v for k, v in found.get(arm, {}).items()
                                   if k in COUNTED + ("answered", "medianNewTokens", "meanWebCalls")}
                             for arm in ("K0", "KF")}
    pooled = {r["id"]: r for r in estimate.pooled(codex)}
    claude = {r["id"]: r for r in estimate.pooled(rows)}
    per_question = []
    for qid in sorted(ids):
        c, k = pooled.get(qid, {}), claude.get(qid, {})
        if all((c.get(a) or {}).get("newTokens") for a in ("K0", "KF")) and all(
                (k.get(a) or {}).get("newTokens") for a in E8_ARMS):
            per_question.append({"id": qid, "codex": r3(c["KF"]["newTokens"] / c["K0"]["newTokens"]),
                                 "claude": r3(k["KFc"]["newTokens"] / k["K0c"]["newTokens"])})
    near = strata["near"]
    return {"arms": list(E8_ARMS), "complete": completeness(data), "questions": len(ids),
            "sameQuestionsAsA2Near": ids == codex_near, "byStratum": {"near": near},
            "codex": {"arms": summary(codex), "byReplicate": per_rep,
                      "paired": dict(estimate.paired(codex, "KF", "K0"), seconds=seconds_ratio(codex, "KF", "K0"))},
            "perQuestion": {"pairs": per_question,
                            "bothBelow1": sum(p["codex"] < 1 and p["claude"] < 1 for p in per_question),
                            "codexBelow1": sum(p["codex"] < 1 for p in per_question),
                            "claudeBelow1": sum(p["claude"] < 1 for p in per_question),
                            "spearman": spearman([p["codex"] for p in per_question], [p["claude"] for p in per_question])},
            "contradictedKinds": contradicted_kinds(data["base"], data["layout"]["folders"])}, mismatches


# ----------------------------------------------------------------------------------------------- predictions

def num(x, places=2):
    """A number with a true minus sign."""
    return ("%.*f" % (places, x)).replace("-", "\u2212")


def opt(x, places=2):
    return "–" if x is None else num(x, places)


def signed(n):
    return ("%+d" % n).replace("-", "\u2212")


def ci(v, places=2):
    """A ratio or difference with its interval as the plan writes them: "0.52 (0.41–0.57)", "−5.4 (−7.2 to −3.6)"."""
    if not v or "low" not in v:
        return "–"
    centre = v.get("median", v.get("mean", v.get("estimate")))
    return "%s (%s%s%s)" % (num(centre, places), num(v["low"], places), " to " if v["low"] < 0 else "–",
                            num(v["high"], places))


def part(text, met, numbers):
    return {"part": text, "met": met, "numbers": numbers}


def judge(parts):
    flags = [p["met"] for p in parts if p["met"] is not None]
    if not flags:
        return "not judged"
    return "met" if all(flags) else "not met" if not any(flags) else "partly met"


def predictions(v):
    out = []

    def add(pid, experiment, statement, parts, note=None):
        out.append({"id": pid, "experiment": experiment, "prediction": statement, "parts": parts,
                    "verdict": judge(parts), "note": note})

    A2, A3, E8 = v["A2"], v["A3"], v["E8"]
    s2 = A2["byStratum"]
    arm = lambda s, a, k: s2[s]["arms"][a][k]  # noqa: E731
    tot = lambda a, k: s2["all"]["arms"][a][k]  # noqa: E731
    paired = lambda s, a: s2[s]["paired"][a]  # noqa: E731
    pair = lambda s, name: s2[s]["pairs"][name]  # noqa: E731

    # ---- A2-1 contradicted statements
    contra = {a: tot(a, "contradicted") for a in A2_ARMS}
    web_on = ", ".join("%s %d" % (a, contra[a]) for a in WEB_ON)
    worst = max(contra[a] for a in WEB_ON)
    add("A2-1", "A2", "Contradicted statements stay near zero: each web-on researcher arm has at most 3 in its 180 "
        "answers and none more than 2 above K0; P has at least as many as any researcher arm. MF at most 9 and MF1 at "
        "most 3.", [
            part("Each web-on researcher arm at most 3 in 180", all(contra[a] <= 3 for a in WEB_ON), web_on + " of 180"),
            part("None more than 2 above K0", all(contra[a] - contra["K0"] <= 2 for a in WEB_ON),
                 "most above K0: %s" % signed(worst - contra["K0"])),
            part("P at least as many as any web-on researcher arm (the web-off arms are A2-1's last two parts)",
                 contra["P"] >= worst,
                 "P %d, the most in a web-on researcher arm %d" % (contra["P"], worst)),
            part("MF at most 9", contra["MF"] <= 9, "MF %d (near %d, mid %d, far %d)" % (
                contra["MF"], *[arm(s, "MF", "contradicted") for s in STRATA])),
            part("MF1 at most 3", contra["MF1"] <= 3, "MF1 %d (near %d, mid %d, far %d)" % (
                contra["MF1"], *[arm(s, "MF1", "contradicted") for s in STRATA]))])

    # ---- A2-2 sourced results
    short = ["%s %s %d" % (s, a, arm(s, a, "resultGiven")) for s in STRATA for a in WEB_ON if arm(s, a, "resultGiven") < 57]
    apart = ["%s %s %s" % (s, a, signed(arm(s, a, "resultGiven") - arm(s, "K0", "resultGiven")))
             for s in STRATA for a in WEB_ON
             if abs(arm(s, a, "resultGiven") - arm(s, "K0", "resultGiven")) > 3]
    mm = pair("near", "MF/MF1")["resultGiven"]
    add("A2-2", "A2", "A sourced result in at least 57 of 60 answers per stratum for every web-on researcher arm, within "
        "3 of K0. Memory alone: MF gives one in at least 50 of 60 near, 20–40 of 60 mid and at most 6 of 60 far "
        "answers, and MF1 fewer than MF in near (the MF against MF1 sourced-result difference above 0, its interval "
        "excluding 0).", [
            part("At least 57 of 60 per stratum, every web-on researcher arm", not short,
                 "; ".join("%s: %s" % (s, ", ".join("%s %d" % (a, arm(s, a, "resultGiven")) for a in WEB_ON))
                           for s in STRATA) + (" (below 57: %s)" % ", ".join(short) if short else "")),
            part("Within 3 of K0", not apart, "more than 3 from K0: %s" % (", ".join(apart) if apart else "none")),
            part("MF near at least 50 of 60", arm("near", "MF", "resultGiven") >= 50,
                 "MF near %d" % arm("near", "MF", "resultGiven")),
            part("MF mid 20–40 of 60", 20 <= arm("mid", "MF", "resultGiven") <= 40,
                 "MF mid %d" % arm("mid", "MF", "resultGiven")),
            part("MF far at most 6 of 60", arm("far", "MF", "resultGiven") <= 6,
                 "MF far %d" % arm("far", "MF", "resultGiven")),
            part("MF1 fewer than MF in near, the paired difference above 0 with its interval excluding 0",
                 arm("near", "MF1", "resultGiven") < arm("near", "MF", "resultGiven") and mm["low"] > 0,
                 "MF1 near %d against MF %d; MF − MF1 share with a sourced result %s" % (
                     arm("near", "MF1", "resultGiven"), arm("near", "MF", "resultGiven"), ci(mm)))],
        note="Completeness counts an honest \"not found\" and carries no memory-only prediction: MF1 complete %s, MF %s "
             "(near, mid, far)." % ("/".join(str(arm(s, "MF1", "complete")) for s in STRATA),
                                    "/".join(str(arm(s, "MF", "complete")) for s in STRATA)))

    # ---- A2-3 tokens and web, near
    kf, kf2 = paired("near", "KF"), paired("near", "KF2")
    split = A2["estimates"]["split"]
    mfkf = pair("near", "MF/KF")["tokens"]
    add("A2-3", "A2", "Tokens and web, near: KF/K0 at most 0.70 with its interval below 1; KF2/K0 between KF/K0 and 1; "
        "KF200/K0 and KF1/K0 intervals include 1. KF's web difference against K0 at most −2 with its interval below 0, "
        "KF answers without web at least 15 of 60, and KF's web ratio against K0 below its token ratio. Parent split: "
        "the near questions whose parent is in KF2 have a median KF2/K0 ratio at most 0.8 of that of the questions "
        "whose parent is not. MF/KF near at most 0.8.", [
            part("KF/K0 at most 0.70, interval below 1", kf["tokens"]["median"] <= 0.70 and kf["tokens"]["high"] < 1,
                 "KF/K0 %s" % ci(kf["tokens"])),
            part("KF2/K0 between KF/K0 and 1", kf["tokens"]["median"] <= kf2["tokens"]["median"] <= 1,
                 "KF2/K0 %s" % ci(kf2["tokens"])),
            part("KF200/K0 and KF1/K0 intervals include 1",
                 all(paired("near", a)["tokens"]["low"] <= 1 <= paired("near", a)["tokens"]["high"]
                     for a in ("KF200", "KF1")),
                 "KF200/K0 %s, KF1/K0 %s" % (ci(paired("near", "KF200")["tokens"]), ci(paired("near", "KF1")["tokens"]))),
            part("KF web difference at most −2, interval below 0",
                 kf["webCalls"]["mean"] <= -2 and kf["webCalls"]["high"] < 0,
                 "KF − K0 web calls per answer %s" % ci(kf["webCalls"], 1)),
            part("KF answers without web at least 15 of 60", arm("near", "KF", "noWeb") >= 15,
                 "%d of 60" % arm("near", "KF", "noWeb")),
            part("KF web ratio below its token ratio", kf["webRatio"] < kf["tokens"]["median"],
                 "web ratio %.2f against token ratio %.2f" % (kf["webRatio"], kf["tokens"]["median"])),
            part("Parent split at most 0.8", split.get("ratio") is not None and split["ratio"] <= 0.8,
                 "%s questions with/without the parent in KF2; median KF2/K0 %.2f with, %.2f without; ratio %s" % (
                     "/".join(map(str, split["n"])), split["medianWith"], split["medianWithout"],
                     ci(dict(split, median=split["ratio"])))),
            part("MF/KF near at most 0.8", mfkf["median"] <= 0.8, "MF/KF %s" % ci(mfkf))],
        note="KF2's near ratios fall in two groups (the split above), and the median of the 20 falls between the two "
             "groups' medians; their geometric mean is %.2f. MF/KF is above 1 because KF answered %d of 60 near "
             "questions without the web (median %.0fk new tokens) and MF, with the web off, searched the store longer "
             "(median %.0fk)." % (
                 A2["nearGeometricMeanRatio"]["KF2"], arm("near", "KF", "noWeb"),
                 arm("near", "KF", "medianNewTokens") / 1e3, arm("near", "MF", "medianNewTokens") / 1e3))

    # ---- A2-4 mid and far
    includes = lambda t: t["low"] <= 1 <= t["high"]  # noqa: E731
    add("A2-4", "A2", "Mid and far: every store arm's KF/K0-style ratio has an interval including 1.", [
        part("%s/K0, mid and far" % a, all(includes(paired(s, a)["tokens"]) for s in ("mid", "far")),
             "mid %s, far %s" % (ci(paired("mid", a)["tokens"]), ci(paired("far", a)["tokens"])))
        for a in WEB_ON if a != "K0"],
        note="In mid the larger stores cost more, as the paper outline expects for a property nobody asked of a "
             "well-covered polymer, and also gave fewer sourced results, which no prediction expected (%s of 60, K0 "
             "%d). E4's far savings were read as K0's "
             "night-time answers in test 1; here K0 answered beside the other arms and far ratios are %s; P/K0 far is "
             "%s, so K0 itself was somewhat dearer on far questions." % (
                 ", ".join("%s %d" % (a, arm("mid", a, "resultGiven")) for a in WEB_ON if a != "K0"),
                 arm("mid", "K0", "resultGiven"),
                 ", ".join("%s %.2f" % (a, paired("far", a)["tokens"]["median"]) for a in WEB_ON if a != "K0"),
                 ci(paired("far", "P")["tokens"])))

    # ---- A2-5 against P
    add("A2-5", "A2", "Against the plain session: the KF/P paired ratio in near below 1; K0/P at or above 1 in near and "
        "far.", [
            part("KF/P near below 1", pair("near", "KF/P")["tokens"]["median"] < 1,
                 "KF/P near %s" % ci(pair("near", "KF/P")["tokens"])),
            part("K0/P near at or above 1", pair("near", "K0/P")["tokens"]["median"] >= 1,
                 "K0/P near %s" % ci(pair("near", "K0/P")["tokens"])),
            part("K0/P far at or above 1", pair("far", "K0/P")["tokens"]["median"] >= 1,
                 "K0/P far %s" % ci(pair("far", "K0/P")["tokens"]))])

    # ---- A2-6 Fig. 4c
    slope, passes = A2["estimates"]["slope"], (A2["estimates"].get("passes") or {}).get("logFindings")
    cite = [arm("near", a, "citingFindings") for a in WEB_ON]
    contra_on = [contra[a] for a in WEB_ON]
    sens = A2["passSensitivity"]
    add("A2-6", "A2", "Fig. 4c: the near scaling slope below 0 with its interval excluding 0; the far slope's interval "
        "includes 0; near answers citing saved findings rise with size (KF at least 45 of 60; K0 and KF200 at most 3); "
        "contradicted statements flat near zero; the pass-on-store-size coefficient's interval includes 0.", [
            part("Near slope below 0, interval excluding 0", slope["near"]["high"] < 0, "near %s" % ci(slope["near"], 3)),
            part("Far slope interval includes 0", slope["far"]["low"] <= 0 <= slope["far"]["high"],
                 "far %s (mid %s)" % (ci(slope["far"], 3), ci(slope["mid"], 3))),
            part("Near citing rises with size; KF at least 45; K0 and KF200 at most 3",
                 cite == sorted(cite) and cite[-1] >= 45 and cite[0] <= 3 and cite[1] <= 3,
                 "K0 → KF: %s of 60" % ", ".join(map(str, cite))),
            part("Contradicted statements flat near zero", max(contra_on) <= 3 and max(contra_on) - min(contra_on) <= 2,
                 "%s of 180 (K0 → KF)" % ", ".join(map(str, contra_on))),
            part("Pass on store size: interval includes 0", passes and passes["low"] <= 0 <= passes["high"],
                 "log-findings coefficient %s (variational Bayes); sensitivity, GEE %s, and %s on the %d answers "
                 "without an access-uncertain statement; passes K0 → KF %s of 180" % (
                     ci(passes, 3), ci(sens.get("all"), 3), ci(sens.get("withoutAccessUncertain"), 3),
                     (sens.get("withoutAccessUncertain") or {}).get("answers", 0),
                     ", ".join(str(tot(a, "pass")) for a in WEB_ON)))])

    # ---- A2-7 passes
    pass_rows = {s: {a: arm(s, a, "pass") for a in A2_ARMS} for s in STRATA}
    below = all(pass_rows[s]["P"] < min(pass_rows[s][a] for a in WEB_ON) for s in STRATA)
    np_p = A2["nonPasses"]["P"]["all"]
    cells = [(s, rep, c["spread"]) for s, reps in A2["passesByReplicate"].items() for rep, c in reps.items()]
    wide = ["%s r%s %d" % c for c in cells if c[2] > 2]
    add("A2-7", "A2", "Passes, second: P below the researcher arms in every stratum, mostly through access-uncertain "
        "statements; among web-on researcher arms, differences within CL-21's 2 in 20 per replicate.", [
            part("P below every web-on researcher arm in every stratum (the web-off arms in the note)", below,
                 "; ".join("%s: P %d, web-on %s" % (s, pass_rows[s]["P"], "/".join(str(pass_rows[s][a]) for a in WEB_ON))
                           for s in STRATA)),
            part("Mostly through access-uncertain statements", np_p["accessUncertainOnly"] > np_p["nonPasses"] / 2,
                 "of P's %d non-passes, %d had an access-uncertain statement and no contradicted one, %d a contradicted "
                 "statement, %d neither; P had %d access-uncertain statements in 180 answers, K0 %d" % (
                     np_p["nonPasses"], np_p["accessUncertainOnly"], np_p["contradicted"], np_p["other"],
                     tot("P", "accessUncertain"), tot("K0", "accessUncertain"))),
            part("Web-on researcher arms within 2 of 20 per replicate and stratum", not wide,
                 "%d of %d replicate-by-stratum cells spread more than 2 (%s)" % (
                     len(wide), len(cells), ", ".join(wide) or "none"))],
        note="The memory-only arms pass less than P in mid and far (MF1 %s, MF %s; near, mid, far), as answers that give "
             "no sourced result." % ("/".join(str(pass_rows[s]["MF1"]) for s in STRATA),
                                     "/".join(str(pass_rows[s]["MF"]) for s in STRATA)))

    # ---- A3-1
    stores = A3["stores"]
    contra3 = {a: stores[a]["byStratum"]["all"]["contradicted"] for a in stores}
    result3 = {a: stores[a]["byStratum"]["all"]["resultGiven"] for a in stores}
    few = ["%s %d" % (a, n) for a, n in result3.items() if n < 57]
    add("A3-1", "A3", "At most 22 contradicted statements in the 1,320 answers and at most 2 in any arm's 60; a sourced "
        "result in at least 57 of 60 answers per arm.", [
            part("At most 22 in all", sum(contra3.values()) <= 22, "{:,} in {:,} answers".format(
                sum(contra3.values()), A3["complete"]["rows"])),
            part("At most 2 in any arm's 60", max(contra3.values()) <= 2, "most in one arm %d (%s)" % (
                max(contra3.values()), ", ".join(a for a, n in contra3.items() if n == max(contra3.values())))),
            part("Sourced result in at least 57 of 60 per arm", not few, "range %d–%d of 60%s" % (
                min(result3.values()), max(result3.values()), "; below 57: " + ", ".join(few) if few else ""))])

    # ---- A3-2
    sl3, spread = A3["estimates"]["slope"], A3["estimates"]["seedSpread"]
    near_spread = {z: spread["near/R%d" % z]["maxOverMin"] for z in SIZES}
    add("A3-2", "A3", "The near scaling slope (all 22 arms) below 0 with its interval excluding 0, the mid and far "
        "slopes' intervals including 0; the seed spread at 100–400 questions wide (the five seeds' near medians "
        "differing by at least 20%).", [
            part("Near slope below 0, interval excluding 0", sl3["near"]["high"] < 0, "near %s" % ci(sl3["near"], 3)),
            part("Mid and far intervals include 0",
                 all(sl3[s]["low"] <= 0 <= sl3[s]["high"] for s in ("mid", "far")),
                 "mid %s, far %s" % (ci(sl3["mid"], 3), ci(sl3["far"], 3))),
            part("Seed spread at 100–400 wide: largest near median at least 1.2 times the smallest",
                 all(near_spread[z] >= 1.2 for z in (100, 200, 400)),
                 "near, largest over smallest of the five seeds' medians: %s" % ", ".join(
                     "%d %.2f" % (z, near_spread[z]) for z in SIZES))],
        note="The spread is no narrower where memory cannot help: far %s, mid %s (100, 200, 400, 800), so with one "
             "answer per question and store most of it is answer-to-answer variation, not store composition." % (
                 ", ".join("%.2f" % spread["far/R%d" % z]["maxOverMin"] for z in SIZES),
                 ", ".join("%.2f" % spread["mid/R%d" % z]["maxOverMin"] for z in SIZES)))

    # ---- A3-3
    cov = A3["estimates"]["coverage"]
    par = cov["parentInStore"]
    add("A3-3", "A3", "What saves cost is the question's own topic, not the store's size: in the coverage model, "
        "exp(parent coefficient) at most 0.8 with its interval below 1, and the log-findings coefficient's interval "
        "including 0 once parent-in-store is in the model.", [
            part("exp(parent) at most 0.8, interval below 1", par["multiplier"] <= 0.8 and par["multiplierHigh"] < 1,
                 "exp(parent) %.2f (%.2f–%.2f), %d near questions" % (par["multiplier"], par["multiplierLow"],
                                                                     par["multiplierHigh"], cov["questions"])),
            part("Log-findings coefficient interval includes 0",
                 cov["logFindings"]["low"] <= 0 <= cov["logFindings"]["high"],
                 "log findings %s" % ci(cov["logFindings"], 3))])

    # ---- A3-4
    by_size = A3["bySize"]
    cite_size = [sum(by_size[str(z)]["nearCiting"]) for z in SIZES]
    par_size = [sum(by_size[str(z)]["nearParents"]) for z in SIZES]
    anchor = A3["anchors"]["near"]
    add("A3-4", "A3", "Near answers citing saved findings rise with size and track the near parents present; the "
        "anchors' KF/K0 near ratio falls within the range of A2's three replicates.", [
            part("Near citing rises with size", all(a < b for a, b in zip(cite_size, cite_size[1:])),
                 "near answers citing a finding, five seeds together (of 100): %s at 100, 200, 400, 800 questions" % (
                     ", ".join(map(str, cite_size)))),
            part("Tracks the near parents present (both rise at every size step, rank correlation over the 20 stores "
                 "above 0)",
                 all(a < b for a, b in zip(par_size, par_size[1:])) and (A3["track"]["parentsVsCiting"] or 0) > 0,
                 "near parents present (of 100): %s; per store %s; Spearman %s" % (
                     ", ".join(map(str, par_size)),
                     "; ".join("%d: %s" % (z, "/".join(map(str, by_size[str(z)]["nearParents"])))
                                                         for z in SIZES), opt(A3["track"]["parentsVsCiting"]))),
            part("Anchors' KF/K0 near within A2's replicate range",
                 anchor["A2range"][0] <= anchor["A3"]["median"] <= anchor["A2range"][1],
                 "A3 KF/K0 near %s; A2 replicates %s" % (ci(anchor["A3"]), ", ".join(
                     "%.3f" % x for x in anchor["A2replicates"].values())))])

    # ---- E8
    e = E8["byStratum"]["near"]
    ea = e["arms"]
    ep = e["paired"]["KFc"]
    add("E8-1", "E8", "At most 1 contradicted statement per arm, and KFc gives a sourced result in at least 18 of 20 "
        "answers and in no fewer than K0c less 1.", [
            part("At most 1 contradicted statement per arm", all(ea[a]["contradicted"] <= 1 for a in E8_ARMS),
                 "K0c %d, KFc %d in 20 answers (%d and %d answers with one); A2's Codex K0 %d and KF %d in 60 on the "
                 "same questions" % (ea["K0c"]["contradicted"], ea["KFc"]["contradicted"],
                                    ea["K0c"]["answersContradicted"], ea["KFc"]["answersContradicted"],
                                    E8["codex"]["arms"]["K0"]["contradicted"], E8["codex"]["arms"]["KF"]["contradicted"])),
            part("KFc sourced result at least 18 of 20", ea["KFc"]["resultGiven"] >= 18,
                 "KFc %d" % ea["KFc"]["resultGiven"]),
            part("KFc no fewer than K0c less 1", ea["KFc"]["resultGiven"] >= ea["K0c"]["resultGiven"] - 1,
                 "KFc %d, K0c %d" % (ea["KFc"]["resultGiven"], ea["K0c"]["resultGiven"]))])
    add("E8-2", "E8", "KFc/K0c near tokens below 1 (the median paired ratio's interval below 1) and KFc's web calls fewer "
        "than K0c's (the mean paired difference's interval below 0); KFc cites saved findings in at least 14 of 20 "
        "answers.", [
            part("KFc/K0c interval below 1", ep["tokens"]["high"] < 1,
                 "KFc/K0c %s (Codex KF/K0 on the same questions %s)" % (ci(ep["tokens"]),
                                                                        ci(E8["codex"]["paired"]["tokens"]))),
            part("KFc web calls fewer, interval below 0", ep["webCalls"]["high"] < 0,
                 "KFc − K0c web calls per answer %s; %d of 20 KFc answers without web" % (ci(ep["webCalls"], 1),
                                                                                     ea["KFc"]["noWeb"])),
            part("KFc cites saved findings in at least 14 of 20", ea["KFc"]["citingFindings"] >= 14,
                 "KFc %d, K0c %d" % (ea["KFc"]["citingFindings"], ea["K0c"]["citingFindings"]))])
    cx = E8["codex"]["byReplicate"]
    add("E8-3", "E8", "Caution, not a prediction: access-uncertain statements and passes may differ from the Codex arms "
        "because Claude Code's fetch tool cannot open many sources; contradicted statements and sourced results carry "
        "the comparison.", [
            part("Access-uncertain statements and passes (reported)", None,
                 "access-uncertain K0c %d, KFc %d in 20; A2's Codex K0 %s and KF %s per replicate of 20; passes K0c %d, "
                 "KFc %d of 20, Codex K0 %s and KF %s" % (
                     ea["K0c"]["accessUncertain"], ea["KFc"]["accessUncertain"],
                     "/".join(str(c["K0"]["accessUncertain"]) for c in cx.values()),
                     "/".join(str(c["KF"]["accessUncertain"]) for c in cx.values()),
                     ea["K0c"]["pass"], ea["KFc"]["pass"], "/".join(str(c["K0"]["pass"]) for c in cx.values()),
                     "/".join(str(c["KF"]["pass"]) for c in cx.values())))])
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
    data = {e: load(e, root) for e in FOLDERS}
    a2v, m2 = a2(data["A2"])
    a3v, m3 = a3(data["A3"], a2v)
    e8v, m8 = e8(data["E8"], data["A2"])
    meta = dict(kf.meta("part_a/a2a3e8_results.py"), analysisRevision=revision(),
                records={e: {"folder": FOLDERS[e], "folders": data[e]["pins"],
                             "reportAt": data[e]["report"].get("at")} for e in FOLDERS})
    value = {"meta": meta, "A2": a2v, "A3": a3v, "E8": e8v,
             "crossChecks": {"mismatches": [dict(m, experiment=e) for e, ms in (("A2", m2), ("A3", m3), ("E8", m8))
                                            for m in ms]}}
    value["predictions"] = predictions(value)
    return value


def k(v):
    return "–" if v is None else "%.1fk" % (v / 1e3)


def markdown(value):
    meta, A2, A3, E8 = value["meta"], value["A2"], value["A3"], value["E8"]
    lines = ["# A2, A3 and E8 results: memory, scaling and a second engine on the frozen knowledge base", "",
             "Drawn from the records only by `studies/macromolecules/part_a/a2a3e8_results.py` (revision %s) on %s, "
             "from each experiment's pre-registered report (`part_a.py report`, `estimate.py`) and rows; no engine "
             "call. Code `study-freeze-2`, prompt `%s`, KF `%s`; research and checks on Codex, E8's researcher on "
             "Claude Code. 20 questions per stratum: only large effects are detectable, and everything here is "
             "descriptive. Quality leads with contradicted statements, complete answers and sourced results; tokens "
             "and web calls next; passes and access-uncertain statements second (CL-21: two checks of the same answers "
             "move passes by up to 2 in 20)." % (meta["analysisRevision"], meta["builtAt"], meta["prompt"],
                                                 meta["knowledgeSnapshot"]), ""]
    mism = value["crossChecks"]["mismatches"]
    lines += [("**%d mismatches between the reports and their rows** (see results.json)." % len(mism)) if mism else
              "Every count in the reports agrees with its rows.", ""]
    for name, v in (("A2", A2), ("A3", A3), ("E8", E8)):
        c = v["complete"]
        recs = meta["records"][name]["folders"].values()
        lines.append("- %s: {:,} of {:,} answers in the rows, {:,} answered, {:,} checked; ran %s to %s from harness "
                     "revisions %s; folders %s.".format(c["rows"], c["expected"], c["answered"], c["checked"]) % (
            name, min(f["ranFrom"] or "?" for f in recs)[:16], max(f["ranTo"] or "?" for f in recs)[:16],
            ", ".join(sorted({x[:7] for f in recs for x in f["runRevisions"]})), ", ".join(
                "%s %s (%d failed)" % (f, x["state"], x["failed"]) for f, x in c["folders"].items())))
    lines += ["", "## A2: memory and scaling (60 held-out questions, 3 replicates; 60 answers per arm and stratum)", "",
              "Ratios are KF/K0-style paired ratios against K0 (median over questions of each arm's replicates "
              "pooled, bootstrap 95% interval); web calls are the mean per answer.", ""]
    head = ("| Arm (findings) | Contradicted | Complete | Sourced result | Median new tokens | Tokens vs K0 | Time vs K0 "
            "| Web calls | No web | Citing findings | Passes | Access-uncertain |")
    for s in STRATA + ("all",):
        part = A2["byStratum"][s]
        lines += ["### %s" % s, "", head, "| --- |" + " ---: |" * 11]
        for arm in A2_ARMS:
            a, p = part["arms"][arm], part["paired"].get(arm) or {}
            lines.append("| %s (%s) | %d | %d | %d | %s | %s | %s | %.1f | %d | %d | %d | %d |" % (
                arm, "{:,}".format(A2["storeFindings"][arm]) if A2["storeFindings"][arm] else "plain", a["contradicted"],
                a["complete"], a["resultGiven"], k(a["medianNewTokens"]), ci(p.get("tokens")) if p else "–",
                ci(p.get("seconds")) if p else "–", a["meanWebCalls"], a["noWeb"], a["citingFindings"], a["pass"],
                a["accessUncertain"]))
        lines.append("")
    lines += ["### Further pairs", "", "| Stratum | Pair | Tokens | Time | Web-call difference | Web ratio | "
              "Sourced-result difference |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for s in STRATA + ("all",):
        for name, p in A2["byStratum"][s]["pairs"].items():
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                s, name, ci(p["tokens"]), ci(p["seconds"]), ci(p["webCalls"], 1),
                "–" if p["webRatio"] is None else "%.2f" % p["webRatio"], ci(p["resultGiven"])))
    est = A2["estimates"]
    sens = A2["passSensitivity"]
    lines += ["", "### Estimates", "",
              "- Within-question scaling slope of log new tokens on log store findings (K0, KF200, KF1, KF2, KF; 900 "
              "answers): %s." % ", ".join("%s %s" % (s, ci(est["slope"][s], 3)) for s in STRATA),
              "- KF2 parent split (near): %d questions with the parent in KF2, median KF2/K0 %.2f; %d without, %.2f; "
              "ratio %s." % (est["split"]["n"][0], est["split"]["medianWith"], est["split"]["n"][1],
                             est["split"]["medianWithout"], ci(dict(est["split"], median=est["split"]["ratio"]))),
              "- Pass on log store findings, mixed logistic regression (variational Bayes, pre-registered): %s on %d "
              "answers. Sensitivity (GEE, robust): %s on all answers; %s on the %d without an access-uncertain "
              "statement (%d passes)." % (
                  ci((est.get("passes") or {}).get("logFindings"), 3), (est.get("passes") or {}).get("answers", 0),
                  ci(sens.get("all"), 3),
                  ci(sens.get("withoutAccessUncertain"), 3), (sens.get("withoutAccessUncertain") or {}).get("answers", 0),
                  (sens.get("withoutAccessUncertain") or {}).get("passes", 0)),
              "- KF/K0 per replicate: %s." % "; ".join("%s %s" % (s, ", ".join(
                  "r%s %s" % (rep, ci(v)) for rep, v in est["byReplicate"][s].items())) for s in STRATA),
              "- Passes per replicate (of 20), P / K0 / KF200 / KF1 / KF2 / KF / MF1 / MF: %s." % "; ".join(
                  "%s %s" % (s, ", ".join("r%s %s" % (rep, "/".join(str(c[a]) for a in A2_ARMS))
                                          for rep, c in A2["passesByReplicate"][s].items())) for s in STRATA),
              "- Contradicted statements by the checker's kind/category (diagnostic, from the check items): %s." %
              "; ".join("%s %s" % (arm, ", ".join("%s %d" % kv for kv in v["contradicted"].items()))
                        for arm, v in A2["contradictedKinds"].items() if v["contradicted"]), ""]
    lines += ["## A3: resampled stores (one answer per question and store; K0 and KF same-day anchors)", "",
              "| Store | Findings | Near parents | Near citing | Near tokens vs K0 | Mid | Far | Contradicted | "
              "Sourced result | Complete | Passes |", "| --- |" + " ---: |" * 10]
    for arm, st in A3["stores"].items():
        b = st["byStratum"]
        lines.append("| %s | {:,} | %d | %d | %s | %s | %s | %d | %d | %d | %d |".format(st["findings"]) % (
            arm, st["nearParents"], b["near"]["citingFindings"], ci(b["near"]["tokensVsK0"]),
            ci(b["mid"]["tokensVsK0"]), ci(b["far"]["tokensVsK0"]), b["all"]["contradicted"], b["all"]["resultGiven"],
            b["all"]["complete"], b["all"]["pass"]))
    e3, s3 = A3["estimates"], A3["passSensitivity"]
    lines += ["", "- Within-question scaling slope (22 arms, 1,320 answers): %s." % ", ".join(
                  "%s %s" % (s, ci(e3["slope"][s], 3)) for s in STRATA),
              "- Coverage model (near, 20 resampled stores): exp(parent in store) %.2f (%.2f–%.2f); log findings %s." % (
                  e3["coverage"]["parentInStore"]["multiplier"], e3["coverage"]["parentInStore"]["multiplierLow"],
                  e3["coverage"]["parentInStore"]["multiplierHigh"], ci(e3["coverage"]["logFindings"], 3)),
              "- Seed spread, the five seeds' median new tokens (largest over smallest): %s." % "; ".join(
                  "%s %s (%.2f)" % (key, "/".join(k(m) for m in v["medians"]), v["maxOverMin"])
                  for key, v in e3["seedSpread"].items()),
              "- Pass on log store findings (variational Bayes): %s on %d answers; GEE %s; without access-uncertain "
              "statements %s." % (ci((e3.get("passes") or {}).get("logFindings"), 3),
                                  (e3.get("passes") or {}).get("answers", 0), ci(s3.get("all"), 3),
                                  ci(s3.get("withoutAccessUncertain"), 3)),
              "- Near parents present against near answers citing findings over the 20 stores: Spearman %s; "
              "against the near token ratio: %s." % (opt(A3["track"]["parentsVsCiting"]),
                                                     opt(A3["track"]["parentsVsNearTokenRatio"])),
              "- Anchors (A3's KF/K0 against A2's replicates): %s." % "; ".join(
                  "%s %s against %s" % (s, ci(v["A3"]), "/".join("%.2f" % x for x in v["A2replicates"].values()))
                  for s, v in A3["anchors"].items()), ""]
    lines += ["## E8: the researcher on Claude Code, near questions (20 answers per arm), beside A2's Codex arms", "",
              "| Arm | Engine | Answers | Contradicted | Complete | Sourced result | Median new tokens | Web calls | "
              "No web | Citing findings | Passes | Access-uncertain | Statements per check |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    kinds_e8, kinds_a2 = E8["contradictedKinds"], A2["contradictedKinds"]
    for arm, a, engine, n in [(x, E8["byStratum"]["near"]["arms"][x], "Claude Code", kinds_e8.get(x, {}))
                              for x in E8_ARMS] + [(x, E8["codex"]["arms"][x], "Codex (A2, 3 rep.)", kinds_a2.get(x, {}))
                                                   for x in ("K0", "KF")]:
        lines.append("| %s | %s | %d | %d | %d | %d | %s | %.1f | %d | %d | %d | %d | %s |" % (
            arm, engine, a["answered"], a["contradicted"], a["complete"], a["resultGiven"], k(a["medianNewTokens"]),
            a["meanWebCalls"], a["noWeb"], a["citingFindings"], a["pass"], a["accessUncertain"],
            n.get("medianStatements", "–") if engine == "Claude Code"
            else "%s (A2, all strata)" % n.get("medianStatements", "–")))
    ep, cp = E8["byStratum"]["near"]["paired"]["KFc"], E8["codex"]["paired"]
    pq = E8["perQuestion"]
    lines += ["", "- KFc/K0c tokens %s, time %s, web-call difference %s, web ratio %.2f, sourced-result difference %s." % (
                  ci(ep["tokens"]), ci(ep["seconds"]), ci(ep["webCalls"], 1), ep["webRatio"], ci(ep["resultGiven"])),
              "- Codex KF/K0 on the same 20 questions (A2, 3 replicates pooled): tokens %s, time %s, web-call difference "
              "%s, web ratio %.2f." % (ci(cp["tokens"]), ci(cp["seconds"]), ci(cp["webCalls"], 1), cp["webRatio"]),
              "- Per question: KF cheaper than K0 on Codex for %d of %d questions, on Claude Code for %d, both for %d; "
              "Spearman between the two engines' per-question ratios %s." % (
                  pq["codexBelow1"], len(pq["pairs"]), pq["claudeBelow1"], pq["bothBelow1"], pq["spearman"]),
              "- Contradicted statements by kind/category (diagnostic): %s." % "; ".join(
                  "%s %s" % (arm, ", ".join("%s %d" % kv for kv in v["contradicted"].items()))
                  for arm, v in kinds_e8.items()),
              "- The two engines' token counts are not on one scale (each engine's own accounting); only ratios within "
              "an engine are compared.", ""]
    lines += ["## The predictions", ""]
    for p in value["predictions"]:
        lines.append("- **%s, %s.** %s" % (p["id"], p["verdict"], p["prediction"]))
        for q in p["parts"]:
            word = "reported" if q["met"] is None else "met" if q["met"] else "not met"
            lines.append("  - %s: %s (%s)." % (q["part"], word, q["numbers"]))
        if p.get("note"):
            lines.append("  - Note: %s" % p["note"])
    return "\n".join(lines) + "\n"


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
    parser = argparse.ArgumentParser(description="A2, A3 and E8's results from the records only.")
    parser.add_argument("--root", type=Path, help="read the run folders here instead of .oopc/loop/harness/")
    parser.add_argument("--out", type=Path, help="write here instead of analysis/a2a3e8/")
    args = parser.parse_args()
    value = build(args.root)
    out = write(value, args.out)
    for p in value["predictions"]:
        print("%-5s %-11s %s" % (p["id"], p["verdict"], " | ".join(
            "%s: %s" % ("–" if q["met"] is None else "ok" if q["met"] else "NO", q["numbers"]) for q in p["parts"])))
    print("cross-checks: %d mismatches" % len(value["crossChecks"]["mismatches"]))
    print("wrote", out / "results.json", out / "results.md")


if __name__ == "__main__":
    main()
