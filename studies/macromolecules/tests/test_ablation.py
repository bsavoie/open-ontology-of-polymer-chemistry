"""Offline check of the ablation runner and analysis with a scripted engine: no subscription is used.

Test 1's test_ablation.py (`.oopc/loop/harness/2026-10-ablation/`), moved to the repository on 2026-10-13 unchanged
except imports and paths, the guard's run folder passed as `base` (the shared guard is patched on the ablation module,
not on a loaded campaign module), and a skip when the private records it reads are absent."""
import json, sys, tempfile, threading, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, run_dir  # noqa: E402  (common puts CODE first on sys.path)
from ablation import ablation, analyze  # noqa: E402
from oopc import ask, knowledge, parity, reviewer  # noqa: E402

BASE = run_dir("2026-10-ablation")
NEEDS = [BASE / "heldout.json", ablation.K0_STORE, knowledge.database(ROOT), ROOT / "releases/current.json"]


class Engine:
    def __init__(self):
        self.calls, self.lock = [], threading.Lock()

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None):
        with self.lock:
            self.calls.append((engine, "direct" if schema is parity.DIRECT_SCHEMA else "research"
                               if schema is ask.ANSWER_SCHEMA else "check"))
        if schema is parity.DIRECT_SCHEMA:
            answer, usage = {"answer": "A value [s](https://example.org/x).", "citations": ["https://example.org/x"],
                             "limitations": []}, 3000
        elif schema is ask.ANSWER_SCHEMA:
            found = tools.call("search_knowledge", {"q": "polystyrene tensile modulus"}) if tools else {}
            ids = [f["id"] for g in ("reviewed", "added") for f in found.get(g, [])][:1]
            answer = {"answer": "From memory `%s`." % (ids[0] if ids else "https://example.org/y"),
                      "citations": ids or ["https://example.org/y"], "findings": [], "sources": [], "limitations": [],
                      "openQuestions": []}
            usage = 1000 if ids else 2500
        else:
            answer, usage = {"verdict": "pass", "notes": "", "statements": [
                {"statement": "x", "verdict": "supported", "reason": "ok", "kind": "source-fact", "category": "none"}]}, 500
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": usage, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [{"type": "web_search"}] if usage > 1000 else [], "agentSeconds": 1.0}


@unittest.skipUnless(all(p.exists() for p in NEEDS), "needs test 1's held-out questions, the K0 backup, the live store "
                     "and a graph release (private records under .oopc/ and releases/)")
class Ablation(unittest.TestCase):
    def test_three_arms_answer_and_are_checked_then_analysed(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-ablation-test-")
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        saved = (ablation.BASE, analyze.BASE, ablation.Guard)
        self.addCleanup(lambda: (setattr(ablation, "BASE", saved[0]), setattr(analyze, "BASE", saved[1]),
                                 setattr(ablation, "Guard", saved[2])))
        ablation.BASE = analyze.BASE = base
        questions = json.loads((BASE / "heldout.json").read_text())
        picked = [next(q for q in questions if q["stratum"] == s) for s in ("near", "mid", "far")]
        (base / "heldout.json").write_text(json.dumps(picked))
        engine = Engine()

        class FakeGuard(saved[2]):
            def __init__(self, deadline, base):
                super().__init__(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                                 signed=lambda e: True, base=base)
        ablation.Guard = FakeGuard
        ablation.prepare()
        ablation.run()
        kinds = [k for _, k in engine.calls]
        self.assertEqual((kinds.count("direct"), kinds.count("research"), kinds.count("check")), (3, 6, 9))
        self.assertEqual(json.loads((base / "state.json").read_text())["status"], "completed")
        ablation.run()  # Resuming answers nothing again.
        self.assertEqual(len(engine.calls), 18)
        value = analyze.main() or json.loads((base / "analysis.json").read_text())
        self.assertEqual(value["complete"], 3)
        self.assertEqual(value["all"]["arms"]["P"]["pass"], 3)
        self.assertIn("cleanMemoryEffect", value["decision"])


if __name__ == "__main__":
    unittest.main()
