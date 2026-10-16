"""The scaling run's numbers, from its records and test 1's answers only; predictions were written before the run
(docs/exec-plans/active/self-improvement-test-plan.md, "E4 and E5").

    python analyze.py        # writes analysis.json and analysis.txt beside this file

Ran in `.oopc/loop/harness/2026-10-scaling/` and still reads and writes there, not beside this file; moved to the
repository on 2026-10-13 unchanged except imports and paths.
"""
import importlib.util, json, math, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, run_dir  # noqa: E402

BASE = run_dir("2026-10-scaling")
ABLATION = run_dir("2026-10-ablation")
spec = importlib.util.spec_from_file_location("ablation_analyze", STUDY / "ablation" / "analyze.py")
ablation_analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ablation_analyze)
ratio_ci, diff_ci, median = ablation_analyze.ratio_ci, ablation_analyze.diff_ci, ablation_analyze.median

WEB_ARMS = ("K0", "K200", "K1", "K2", "K3")   # the scaling curve, in order of store size
MEMORY_ARMS = ("M1", "M3")                     # web off
RECHECKED = ("K0", "K3")                       # test 1's answers, checked again here
ARMS = WEB_ARMS + MEMORY_ARMS
STRATA = ("near", "mid", "far")


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


def metrics(answer, check):
    if not answer or "error" in answer:
        return None
    m, body = answer.get("metrics") or {}, answer.get("answer") or {}
    statements = (check or {}).get("statements") or [] if check and "error" not in check else []
    cited = [c for c in body.get("citations") or [] if isinstance(c, str)]
    return {"verdict": check.get("verdict") if check and "error" not in check else None,
            "supported": (sum(s.get("verdict") == "supported" for s in statements) / len(statements)) if statements else None,
            "contradicted": sum(s.get("verdict") == "unsupported" and s.get("category") != "source-access" for s in statements),
            "complete": next((s.get("verdict") for s in statements if s.get("kind") == "completeness"), None),
            "newTokens": m.get("newTokens"), "webCalls": m.get("webCalls"), "seconds": m.get("seconds"),
            "findingCitations": sum(c.startswith("finding:") for c in cited)}


def load():
    rows = []
    for q in json.loads((ABLATION / "heldout.json").read_text()):
        row = {"id": q["id"], "stratum": q["stratum"], "kind": q["kind"]}
        for arm in ARMS:
            key = "%s-%s-" % (q["id"][:12], arm)
            source = ABLATION if arm in RECHECKED else BASE
            row[arm] = metrics(_read(source / "results" / (key + "answer.json")), _read(BASE / "results" / (key + "check.json")))
            if arm in RECHECKED:
                first = metrics(_read(ABLATION / "results" / (key + "answer.json")), _read(ABLATION / "results" / (key + "check.json")))
                row[arm + "@test1"] = first
        rows.append(row)
    return rows


def arm_summary(rows, arm):
    got = [r[arm] for r in rows if r.get(arm)]
    return {"answered": len(got), "pass": sum(a["verdict"] == "pass" for a in got),
            "uncertain": sum(a["verdict"] == "uncertain" for a in got), "fail": sum(a["verdict"] == "fail" for a in got),
            "complete": sum(a["complete"] == "supported" for a in got),
            "contradictedStatements": sum(a["contradicted"] for a in got),
            "medianSupported": median(a["supported"] for a in got), "medianNewTokens": median(a["newTokens"] for a in got),
            "medianWebCalls": median(a["webCalls"] for a in got), "noWeb": sum(a["webCalls"] == 0 for a in got),
            "medianSeconds": median(a["seconds"] for a in got), "citingFindings": sum(a["findingCitations"] > 0 for a in got)}


def versus(rows, a, b):
    both = [r for r in rows if r.get(a) and r.get(b)]
    return {"tokens": ratio_ci(both, a, b, "newTokens"), "seconds": ratio_ci(both, a, b, "seconds"),
            "webCalls": diff_ci(both, a, b, "webCalls"), "supported": diff_ci(both, a, b, "supported"),
            "passes": [sum(r[a]["verdict"] == "pass" for r in both), sum(r[b]["verdict"] == "pass" for r in both)]}


def summarize(rows):
    arms = {arm: arm_summary(rows, arm) for arm in ARMS}
    arms.update({arm + "@test1": arm_summary(rows, arm + "@test1") for arm in RECHECKED})
    pairs = {"%s/K0" % arm: versus(rows, arm, "K0") for arm in WEB_ARMS[1:]}
    pairs.update({"M1/K1": versus(rows, "M1", "K1"), "M3/K3": versus(rows, "M3", "K3")})
    return {"arms": arms, "pairs": pairs}


def predictions(by):
    """Written before the run. Descriptive: none of them gates anything."""
    near, far = by["near"], by["far"]
    k2 = near["pairs"]["K2/K0"]["tokens"]
    k1, k3 = near["pairs"]["K1/K0"]["tokens"], near["pairs"]["K3/K0"]["tokens"]
    k0_contradicted = sum(by[s]["arms"]["K0"]["contradictedStatements"] for s in STRATA)
    return {
        "1 near K2/K0 tokens interval below 1": bool(k2 and k2["high"] < 1),
        "1 near K3/K0 tokens <= K1/K0 tokens": bool(k1 and k3 and k3["median"] <= k1["median"]),
        "2 far K1/K0 and K2/K0 token intervals contain 1": all(
            (p := far["pairs"]["%s/K0" % a]["tokens"]) and p["low"] <= 1 <= p["high"] for a in ("K1", "K2")),
        "3 no snapshot has >1 more contradicted statement than K0": all(
            sum(by[s]["arms"][a]["contradictedStatements"] for s in STRATA) <= k0_contradicted + 1 for a in WEB_ARMS[1:]),
        "4 M3 near complete in >= 10 of 20": near["arms"]["M3"]["complete"] >= 10,
        "4 M3 near complete > M1 near complete": near["arms"]["M3"]["complete"] > near["arms"]["M1"]["complete"],
        "4 M3 far complete <= 3 of 20": far["arms"]["M3"]["complete"] <= 3,
        "4 memory-only arms each <= 1 contradicted statement": all(
            sum(by[s]["arms"][a]["contradictedStatements"] for s in STRATA) <= 1 for a in MEMORY_ARMS),
    }


def test1_secondary(by):
    """Test 1's decision rule recomputed with the same-day checker that is given session records (secondary)."""
    near, far = by["near"]["pairs"]["K3/K0"], by["far"]["pairs"]["K3/K0"]
    cheaper = bool(near["tokens"] and near["tokens"]["median"] <= 0.85 and near["tokens"]["high"] < 1)
    kept = near["passes"][0] >= near["passes"][1] - 1
    flat = bool(far["tokens"] and far["tokens"]["low"] <= 1 <= far["tokens"]["high"])
    return {"nearCheaper": cheaper, "nearPassesKept": kept, "farFlat": flat, "cleanMemoryEffect": cheaper and kept and flat}


def curve(by, sizes):
    return {s: [dict(arm=a, findings=sizes.get(a), **{k: by[s]["arms"][a][k] for k in (
        "medianNewTokens", "medianWebCalls", "noWeb", "citingFindings", "pass", "complete", "contradictedStatements")})
        for a in WEB_ARMS] for s in STRATA + ("all",)}


def main():
    rows = load()
    by = {s: summarize([r for r in rows if r["stratum"] == s]) for s in STRATA}
    by["all"] = summarize(rows)
    baseline = json.loads((BASE / "baseline.json").read_text())
    sizes = {a: v["findings"] for a, v in baseline["stores"].items()}
    value = {"byStratum": by, "curve": curve(by, sizes), "predictions": predictions(by),
             "test1Secondary": test1_secondary(by), "storeSizes": sizes,
             "complete": sum(all(r.get(a) and r[a]["verdict"] for a in ARMS) for r in rows), "questions": len(rows)}
    (BASE / "analysis.json").write_text(json.dumps(value, indent=1))
    lines = ["Questions with every arm answered and checked: %d/%d" % (value["complete"], value["questions"]),
             "Store sizes (findings): %s" % sizes]
    for s in STRATA + ("all",):
        lines.append("\n[%s]" % s)
        for arm, summary in by[s]["arms"].items():
            lines.append("  %-9s %s" % (arm, summary))
        for name, pair in by[s]["pairs"].items():
            lines.append("  %-9s %s" % (name, pair))
    lines.append("\nPredictions: %s" % json.dumps(value["predictions"], indent=1))
    lines.append("Test 1, secondary (same-day checker with session records): %s" % value["test1Secondary"])
    (BASE / "analysis.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return value


if __name__ == "__main__":
    main()
