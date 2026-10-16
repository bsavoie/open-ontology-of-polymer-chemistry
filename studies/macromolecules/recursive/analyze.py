"""Test 2's numbers, from its records only, as pre-registered in docs/exec-plans/active/self-improvement-test-plan.md
("Test 2 protocol": analysis and predictions). Written 2026-10-14, after the run and before reading its crossing.

    python -B analyze.py        # writes analysis.json and analysis.txt in the run folder

- System effect: the last prompt on the last store (P3S3) against the first on the first (P0S0).
- Prompt effect: P3 against P0 on each store. Store effect: S3 against S0 under each prompt.
- Contradicted statements (unsupported for a reason other than source access), complete answers, answers reporting a
  sourced result, passes; median paired token ratio and mean web-call difference with bootstrap 95% intervals, by
  stratum and overall, on the questions both arms answered and had checked.
- The trajectory: each round's dev decision and the adopted prompt on the 60 held-out questions with that round's
  store (answered on different days, so read for shape only).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recursive import recursive  # noqa: E402  (the tracked test 2 driver: paths, load, measures)
from ablation import analyze as ablation_analyze  # noqa: E402

BASE = recursive.BASE
STRATA = ("near", "mid", "far")
COMPARISONS = {"system": ("P3S3", "P0S0"), "prompt on S0": ("P3S0", "P0S0"), "prompt on S3": ("P3S3", "P0S3"),
               "store under P0": ("P0S3", "P0S0"), "store under P3": ("P3S3", "P3S0")}
LIMITS = {"old": 600, "new": 1000}  # the improver's instructions and the pre-registration


def pair(rows, a, b):
    both = [r for r in rows if r.get(a) and r.get(b)]
    ma, mb = recursive.measures(both, a), recursive.measures(both, b)
    return {"questions": len(both), a: ma, b: mb,
            "tokens": ablation_analyze.ratio_ci(both, a, b, "newTokens"),
            "webCalls": ablation_analyze.diff_ci(both, a, b, "webCalls")}


def crossing():
    folder = BASE / "eval" / "final"
    questions = json.loads((recursive.ABLATION / "heldout.json").read_text())
    arms = sorted(p.stem for p in folder.glob("*.txt"))
    rows = recursive.load(folder, questions, arms)
    out = {"arms": {a: recursive.measures(rows, a) for a in arms}, "complete": sum(all(r.get(a) for a in arms) for r in rows)}
    for name, (a, b) in COMPARISONS.items():
        if a in arms and b in arms:
            out[name] = {"all": pair(rows, a, b), **{s: pair([r for r in rows if r["stratum"] == s], a, b) for s in STRATA}}
    return out


def predictions(cross):
    """Written before the run; descriptive, nothing is gated."""
    prompt = [(cross["prompt on S0"]["all"], "P3S0", "P0S0"), (cross["prompt on S3"]["all"], "P3S3", "P0S3")]
    no_worse = all(p[last]["contradicted"] <= p[first]["contradicted"] + 1 and p[last]["complete"] >= p[first]["complete"] - 2
                   for p, last, first in prompt)
    store = cross["store under P0"]["all"]["tokens"]
    cheaper = all(p["tokens"] and p["tokens"]["median"] < 1 for p, _, _ in prompt)
    return {"1 P3 no worse than P0 on either store (contradicted +1, complete -2)": no_worse,
            "2 store effect under P0 small (token interval contains 1)": bool(store and store["low"] <= 1 <= store["high"]),
            "3 a cost edit was adopted (round 2), so P3/P0 median token ratio below 1 on both stores": cheaper}


def trajectory():
    rounds = []
    for r in recursive.ROUNDS:
        decision = json.loads((BASE / "eval" / ("round-%d" % r) / "dev" / "decision.json").read_text())
        proposal = (json.loads((BASE / "improver" / ("round-%d.json" % r)).read_text()).get("proposal") or {})
        held = json.loads((BASE / "eval" / ("round-%d" % r) / "heldout" / "done.json").read_text())
        rounds.append({"round": r, "adopted": decision.get("adopted"), "rules": decision.get("rules"),
                       "dev": decision.get("measures"), "devTokenRatio": decision.get("tokenRatio"),
                       "edit": {"oldChars": len(proposal.get("old", "")), "newChars": len(proposal.get("new", "")),
                                "withinPreregisteredLimits": len(proposal.get("old", "")) <= LIMITS["old"]
                                and len(proposal.get("new", "")) <= LIMITS["new"],
                                "expectedEffect": proposal.get("expectedEffect")},
                       "heldout": held.get("measures"), "promptVersion": decision.get("adoptedVersion")})
    return rounds


def main():
    cross = crossing()
    value = {"crossing": cross, "predictions": predictions(cross), "trajectory": trajectory(),
             "errorsLeft": recursive.errors_left()}
    (BASE / "analysis.json").write_text(json.dumps(value, indent=1, ensure_ascii=False))
    lines = ["Final crossing: questions with all arms answered and checked: %d/60; failed results left: %d"
             % (cross["complete"], value["errorsLeft"])]
    for arm, m in cross["arms"].items():
        lines.append("  %-5s %s" % (arm, m))
    for name in COMPARISONS:
        if name in cross:
            c = cross[name]["all"]
            a, b = COMPARISONS[name]
            lines.append("\n[%s] %s vs %s on %d questions: tokens %s, web %s" % (name, a, b, c["questions"], c["tokens"], c["webCalls"]))
            for arm in (a, b):
                m = c[arm]
                lines.append("   %-5s contradicted %d, complete %d, sourced %d, pass %d" % (
                    arm, m["contradicted"], m["complete"], m["sourced"], m["pass"]))
            for s in STRATA:
                t = cross[name][s]["tokens"]
                lines.append("   %-4s tokens %s" % (s, t and "%.2f (%.2f-%.2f)" % (t["median"], t["low"], t["high"])))
    lines.append("\nPredictions: " + json.dumps(value["predictions"], indent=1))
    lines.append("\nTrajectory:")
    for r in value["trajectory"]:
        lines.append("  round %d adopted %s, edit %d/%d chars (within limits: %s), dev tokens %s, held-out %s" % (
            r["round"], r["adopted"], r["edit"]["oldChars"], r["edit"]["newChars"], r["edit"]["withinPreregisteredLimits"],
            (r["devTokenRatio"] or {}).get("median"), r["heldout"]))
    (BASE / "analysis.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return value


if __name__ == "__main__":
    main()
