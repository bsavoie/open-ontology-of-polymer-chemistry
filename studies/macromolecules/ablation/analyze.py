"""The memory ablation's numbers, from its records only; the comparisons and decision rule were fixed before the run
(docs/exec-plans/active/self-improvement-test-plan.md).

    python analyze.py        # writes analysis.json and analysis.txt beside this file

Ran in `.oopc/loop/harness/2026-10-ablation/` and still reads and writes there, not beside this file; moved to the
repository on 2026-10-13 unchanged except imports and paths.
"""
import json, math, random, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402

BASE = run_dir("2026-10-ablation")
ARMS = ("P", "K0", "K3")
STRATA = ("near", "mid", "far")
PAIRS = (("K3", "K0"), ("K3", "P"), ("K0", "P"))
DRAWS = 2000


def load(part="check"):
    questions = json.loads((BASE / "heldout.json").read_text())
    rows = []
    for q in questions:
        row = {"id": q["id"], "stratum": q["stratum"], "kind": q["kind"]}
        for arm in ARMS:
            base = BASE / "results" / ("%s-%s-" % (q["id"][:12], arm))
            answer = json.loads(Path(str(base) + "answer.json").read_text()) if Path(str(base) + "answer.json").exists() else None
            check = json.loads(Path(str(base) + part + ".json").read_text()) if Path(str(base) + part + ".json").exists() else None
            if not answer or "error" in answer:
                row[arm] = None
                continue
            metrics, body = answer.get("metrics") or {}, answer.get("answer") or {}
            statements = (check or {}).get("statements") or []
            cited = [c for c in body.get("citations") or [] if isinstance(c, str)]
            row[arm] = {
                "verdict": (check or {}).get("verdict") if check and "error" not in check else None,
                "supported": (sum(s.get("verdict") == "supported" for s in statements) / len(statements)) if statements else None,
                "contradicted": sum(s.get("verdict") == "unsupported" and s.get("category") != "source-access" for s in statements),
                "complete": next((s.get("verdict") for s in statements if s.get("kind") == "completeness"), None),
                "newTokens": metrics.get("newTokens"), "webCalls": metrics.get("webCalls"), "seconds": metrics.get("seconds"),
                "findingCitations": sum(c.startswith("finding:") for c in cited)}
        rows.append(row)
    return rows


def median(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(values), 3) if values else None


def ratio_ci(rows, a, b, key):
    """Median paired ratio a/b with a bootstrap 95% interval over questions."""
    logs = [math.log(r[a][key] / r[b][key]) for r in rows if r.get(a) and r.get(b) and r[a][key] and r[b][key]]
    if len(logs) < 3:
        return None
    rng = random.Random(7)
    draws = sorted(statistics.median(rng.choices(logs, k=len(logs))) for _ in range(DRAWS))
    return {"n": len(logs), "median": round(math.exp(statistics.median(logs)), 3),
            "low": round(math.exp(draws[int(0.025 * DRAWS)]), 3), "high": round(math.exp(draws[int(0.975 * DRAWS)]), 3)}


def diff_ci(rows, a, b, key):
    """Mean paired difference a-b with a bootstrap 95% interval."""
    diffs = [r[a][key] - r[b][key] for r in rows if r.get(a) and r.get(b) and r[a][key] is not None and r[b][key] is not None]
    if len(diffs) < 3:
        return None
    rng = random.Random(7)
    draws = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(DRAWS))
    return {"n": len(diffs), "mean": round(statistics.mean(diffs), 3), "low": round(draws[int(0.025 * DRAWS)], 3),
            "high": round(draws[int(0.975 * DRAWS)], 3)}


def summarize(rows):
    arms = {}
    for arm in ARMS:
        answered = [r[arm] for r in rows if r.get(arm)]
        arms[arm] = {"answered": len(answered),
                     "pass": sum(a["verdict"] == "pass" for a in answered),
                     "uncertain": sum(a["verdict"] == "uncertain" for a in answered),
                     "fail": sum(a["verdict"] == "fail" for a in answered),
                     "contradictedStatements": sum(a["contradicted"] for a in answered),
                     "medianSupported": median(a["supported"] for a in answered),
                     "medianNewTokens": median(a["newTokens"] for a in answered),
                     "medianWebCalls": median(a["webCalls"] for a in answered),
                     "noWeb": sum(a["webCalls"] == 0 for a in answered),
                     "medianSeconds": median(a["seconds"] for a in answered),
                     "citingFindings": sum(a["findingCitations"] > 0 for a in answered)}
    pairs = {}
    for a, b in PAIRS:
        both = [r for r in rows if r.get(a) and r.get(b)]
        pairs["%s/%s" % (a, b)] = {
            "tokens": ratio_ci(both, a, b, "newTokens"), "seconds": ratio_ci(both, a, b, "seconds"),
            "webCalls": diff_ci(both, a, b, "webCalls"), "supported": diff_ci(both, a, b, "supported"),
            "passes": [sum(r[a]["verdict"] == "pass" for r in both), sum(r[b]["verdict"] == "pass" for r in both)]}
    return {"arms": arms, "pairs": pairs}


def decision(by_stratum):
    """Pre-registered: a clean memory effect means near questions cost clearly less with the grown store at no loss of
    passes, and far questions (nothing to remember) show no such effect."""
    near, far = by_stratum["near"]["pairs"]["K3/K0"], by_stratum["far"]["pairs"]["K3/K0"]
    cheaper = bool(near["tokens"] and near["tokens"]["median"] <= 0.85 and near["tokens"]["high"] < 1)
    passes_kept = near["passes"][0] >= near["passes"][1] - 1
    control_flat = bool(far["tokens"] and far["tokens"]["low"] <= 1 <= far["tokens"]["high"])
    return {"nearCheaper": cheaper, "nearPassesKept": passes_kept, "farFlat": control_flat,
            "cleanMemoryEffect": cheaper and passes_kept and control_flat}


def main(part="check"):
    rows = load(part)
    by_stratum = {s: summarize([r for r in rows if r["stratum"] == s]) for s in STRATA}
    value = {"all": summarize(rows), "byStratum": by_stratum, "decision": decision(by_stratum),
             "complete": sum(all(r.get(a) for a in ARMS) for r in rows), "questions": len(rows)}
    label = "" if part == "check" else "-" + part
    (BASE / ("analysis%s.json" % label)).write_text(json.dumps(value, indent=1))
    lines = ["Questions with all three arms answered: %d/%d" % (value["complete"], value["questions"])]
    for s in STRATA + ("all",):
        part = value["all"] if s == "all" else by_stratum[s]
        lines.append("\n[%s]" % s)
        for arm in ARMS:
            lines.append("  %s %s" % (arm, part["arms"][arm]))
        for name, pair in part["pairs"].items():
            lines.append("  %s %s" % (name, pair))
    lines.append("\nDecision: %s" % value["decision"])
    (BASE / ("analysis%s.txt" % label)).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--checks", default="check", help="check (primary) or check2 (the secondary recheck)")
    main(parser.parse_args().checks)
