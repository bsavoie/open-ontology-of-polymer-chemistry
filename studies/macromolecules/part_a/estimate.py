"""The estimators Part A's predictions use (macromolecules-study-plan.md, "Part A harness and predictions",
"Statistics"), computed by `part_a.py report` from its answer rows. Each row is one answer: question `id`, `stratum`,
`arm`, `replicate`, `newTokens`, `webCalls`, the check's measures, `storeFindings` and `parentInStore`. Intervals are
bootstrap 95% intervals over questions (2,000 draws, seed 7, as `ablation/analyze.py`); all of it is descriptive.

- `paired`: per question, an arm's replicates pooled (geometric mean of new tokens; mean web calls; share of answers
  with a sourced result), then against a reference arm the median paired token ratio, the mean paired web-call
  difference, the ratio of mean web calls and the mean paired difference in the share with a sourced result.
- `split`: an arm's paired token ratio against a reference, compared between the questions whose parent is in the arm's
  store and those whose parent is not (unpaired): the ratio of the two groups' medians, resampling within each group.
- `slope`: log new tokens on log findings within questions (a fixed effect per question, which also absorbs the
  stratum), one slope per stratum: Fig. 4c's scaling with store size.
- `coverage`: log new tokens on log findings and parent-in-store together within questions (near): the cost of the
  question's own topic being in the store at a given store size, as exp(coefficient).
- `passes`: pass on log findings by mixed logistic regression (stratum fixed, question random intercept; statsmodels'
  variational Bayes fit when installed), the plan's "pass on snapshot".
"""
import collections, math, random, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
from ablation import analyze  # noqa: E402  (test 1's paired ratios and differences with their intervals)

DRAWS, SEED = analyze.DRAWS, 7


def pooled(rows):
    """Per question, each arm's replicates pooled."""
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        if r["answered"]:
            by[r["id"]][r["arm"]].append(r)
    out = []
    for qid, arms in by.items():
        row = {"id": qid}
        for arm, reps in arms.items():
            tokens = [r["newTokens"] for r in reps if r["newTokens"]]
            web = [r["webCalls"] for r in reps if r["webCalls"] is not None]
            checked = [r for r in reps if r["checked"]]
            row[arm] = {"newTokens": math.exp(statistics.mean(map(math.log, tokens))) if tokens else None,
                        "webCalls": statistics.mean(web) if web else None,
                        "resultGiven": statistics.mean(r["resultGiven"] is True for r in checked) if checked else None,
                        "parentInStore": reps[0].get("parentInStore")}
        out.append(row)
    return out


def paired(rows, arm, reference):
    """`arm` against `reference`, paired per question over pooled replicates (`analyze.ratio_ci`, `diff_ci`)."""
    both = [r for r in pooled(rows) if r.get(arm) and r.get(reference)]
    web = [(r[arm]["webCalls"], r[reference]["webCalls"]) for r in both
           if r[arm]["webCalls"] is not None and r[reference]["webCalls"] is not None]
    mean_b = statistics.mean(b for _, b in web) if web else 0
    return {"tokens": analyze.ratio_ci(both, arm, reference, "newTokens"),
            "webCalls": analyze.diff_ci(both, arm, reference, "webCalls"),
            "webRatio": round(statistics.mean(a for a, _ in web) / mean_b, 3) if web and mean_b else None,
            "resultGiven": analyze.diff_ci(both, arm, reference, "resultGiven")}


def split(rows, arm, reference):
    """`arm`/`reference` token ratios of the questions whose parent is in `arm`'s store against those whose is not."""
    groups = {True: [], False: []}
    for r in pooled(rows):
        if r.get(arm) and r.get(reference) and r[arm]["newTokens"] and r[reference]["newTokens"] \
                and r[arm]["parentInStore"] is not None:
            groups[bool(r[arm]["parentInStore"])].append(math.log(r[arm]["newTokens"] / r[reference]["newTokens"]))
    if len(groups[True]) < 3 or len(groups[False]) < 3:
        return {"n": [len(groups[True]), len(groups[False])]}
    rng, draws = random.Random(SEED), []
    for _ in range(DRAWS):
        draws.append(statistics.median(rng.choices(groups[True], k=len(groups[True])))
                     - statistics.median(rng.choices(groups[False], k=len(groups[False]))))
    draws.sort()
    med = {k: statistics.median(v) for k, v in groups.items()}
    return {"n": [len(groups[True]), len(groups[False])], "medianWith": round(math.exp(med[True]), 3),
            "medianWithout": round(math.exp(med[False]), 3), "ratio": round(math.exp(med[True] - med[False]), 3),
            "low": round(math.exp(draws[int(0.025 * DRAWS)]), 3), "high": round(math.exp(draws[int(0.975 * DRAWS)]), 3)}


def _blocks(rows, columns):
    """Per question, the within-question sums of products of the demeaned columns (the last one the outcome)."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["id"]].append(columns(r))
    blocks = []
    for values in by.values():
        if len(values) < 2:
            continue
        means = [statistics.mean(c) for c in zip(*values)]
        centred = [[v - m for v, m in zip(row, means)] for row in values]
        k = len(means)
        blocks.append([[sum(row[i] * row[j] for row in centred) for j in range(k)] for i in range(k)])
    return blocks


def _solve(blocks, predictors):
    """Least squares from summed blocks: the coefficients of the first `predictors` columns on the last."""
    total = [[sum(b[i][j] for b in blocks) for j in range(predictors + 1)] for i in range(predictors + 1)]
    a = [row[:predictors] for row in total[:predictors]]
    y = [total[i][predictors] for i in range(predictors)]
    if predictors == 1:
        return [y[0] / a[0][0]] if a[0][0] else None
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    if not det:
        return None
    return [(y[0] * a[1][1] - a[0][1] * y[1]) / det, (a[0][0] * y[1] - a[1][0] * y[0]) / det]


def _fit(rows, columns, predictors):
    blocks = _blocks(rows, columns)
    if len(blocks) < 3:
        return None
    estimate = _solve(blocks, predictors)
    if estimate is None:
        return None
    rng, draws = random.Random(SEED), []
    for _ in range(DRAWS):
        found = _solve(rng.choices(blocks, k=len(blocks)), predictors)
        if found is not None:
            draws.append(found)
    value = []
    for i in range(predictors):
        column = sorted(d[i] for d in draws)
        value.append({"estimate": round(estimate[i], 4), "low": round(column[int(0.025 * len(column))], 4),
                      "high": round(column[int(0.975 * len(column))], 4)})
    return {"questions": len(blocks), "coefficients": value}


def _usable(rows):
    return [r for r in rows if r["answered"] and r["newTokens"] and r.get("storeFindings")]


def slope(rows):
    """Per stratum, the within-question slope of log new tokens on log findings."""
    value = {}
    for stratum in sorted({r["stratum"] for r in rows}):
        fit = _fit([r for r in _usable(rows) if r["stratum"] == stratum],
                   lambda r: (math.log(r["storeFindings"]), math.log(r["newTokens"])), 1)
        value[stratum] = fit and dict(fit["coefficients"][0], questions=fit["questions"])
    return value


def coverage(rows, stratum="near"):
    """Within-question log new tokens on log findings and parent-in-store: exp of the parent coefficient is the cost
    multiplier of the question's own topic being in the store, at a given store size."""
    mine = [r for r in _usable(rows) if r["stratum"] == stratum and r.get("parentInStore") is not None]
    fit = _fit(mine, lambda r: (math.log(r["storeFindings"]), float(bool(r["parentInStore"])),
                                math.log(r["newTokens"])), 2)
    if not fit:
        return None
    size, parent = fit["coefficients"]
    return {"questions": fit["questions"], "logFindings": size,
            "parentInStore": dict(parent, multiplier=round(math.exp(parent["estimate"]), 3),
                                  multiplierLow=round(math.exp(parent["low"]), 3),
                                  multiplierHigh=round(math.exp(parent["high"]), 3))}


def passes(rows):
    """Pass on log findings, mixed logistic regression: stratum fixed, a random intercept per question."""
    data = [r for r in rows if r["checked"] and r.get("storeFindings")]
    if len({r["id"] for r in data}) < 3:
        return None
    try:
        import pandas
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    except ImportError as error:
        return {"unavailable": str(error)}
    frame = pandas.DataFrame({"passed": [int(r["pass"] is True) for r in data],
                              "logf": [math.log(r["storeFindings"]) for r in data],
                              "stratum": [r["stratum"] for r in data], "question": [r["id"] for r in data]})
    try:
        formula = "passed ~ logf + C(stratum)" if frame["stratum"].nunique() > 1 else "passed ~ logf"
        fit = BinomialBayesMixedGLM.from_formula(formula, {"question": "0 + C(question)"}, frame).fit_vb()
        names = list(fit.model.exog_names)
        i = names.index("logf")
        mean, sd = float(fit.fe_mean[i]), float(fit.fe_sd[i])
    except Exception as error:  # a fit that does not converge is reported, not raised
        return {"error": str(error)[:300]}
    return {"answers": len(data), "logFindings": {"estimate": round(mean, 4), "low": round(mean - 1.96 * sd, 4),
                                                  "high": round(mean + 1.96 * sd, 4)}, "method": "BinomialBayesMixedGLM.fit_vb"}
