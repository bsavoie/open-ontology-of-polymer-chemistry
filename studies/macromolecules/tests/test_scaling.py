"""Offline check of the scaling runner and analysis with a scripted engine: no subscription is used.

The scaling run's test_scaling.py (`.oopc/loop/harness/2026-10-scaling/`), moved to the repository on 2026-10-13
unchanged except imports and paths, the guard's run folder passed as `base`, a skip when the private records it reads
are absent, and one isolation step: after prepare(), the rechecked arms' links to test 1's private traces are replaced
by copies of the three questions' traces, because reading a trace opens its trace.sqlite for writing (WAL), which would
touch test 1's private folder."""
import json, shutil, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, run_dir  # noqa: E402  (common puts CODE first on sys.path)
from scaling import scaling, analyze  # noqa: E402
from oopc import ask, knowledge, parity  # noqa: E402

ABLATION = run_dir("2026-10-ablation")
NEEDS = [ABLATION / "heldout.json", ABLATION / "results"] + [
    knowledge.database(ABLATION / "workspaces" / arm) for arm in ("K0", "K3")] + [ROOT / "releases/current.json"]


class Engine:
    def __init__(self):
        self.calls, self.lock = [], threading.Lock()

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None):
        kind = "research" if schema is ask.ANSWER_SCHEMA else "check"
        with self.lock:
            self.calls.append((kind, web, "session" in prompt and '"knowledgeSearches"' in prompt))
        if kind == "research":
            found = tools.call("search_knowledge", {"q": "polystyrene tensile modulus"}) if tools else {}
            ids = [f["id"] for g in ("reviewed", "added") for f in found.get(g, [])][:1]
            answer = {"answer": "From memory `%s`." % (ids[0] if ids else "https://example.org/y"),
                      "citations": ids or ["https://example.org/y"], "findings": [], "sources": [], "limitations": [],
                      "openQuestions": []}
            usage = 1000 if ids else 2500
        else:
            answer, usage = {"verdict": "pass", "notes": "", "statements": [
                {"statement": "x", "verdict": "supported", "reason": "ok", "kind": "completeness", "category": "none"}]}, 500
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": usage, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [{"type": "web_search"}] if web and usage > 1000 else [], "agentSeconds": 1.0}


@unittest.skipUnless(all(p.exists() for p in NEEDS), "needs test 1's held-out questions, answers and frozen K0 and K3 "
                     "stores, and a graph release (private records under .oopc/ and releases/)")
class Scaling(unittest.TestCase):
    def test_snapshots_answer_and_recheck_then_analyse(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-scaling-test-")
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        saved = (scaling.BASE, analyze.BASE, scaling.Guard, scaling.ABLATION)
        self.addCleanup(lambda: (setattr(scaling, "BASE", saved[0]), setattr(analyze, "BASE", saved[1]),
                                 setattr(scaling, "Guard", saved[2])))
        scaling.BASE = analyze.BASE = base
        engine = Engine()

        class FakeGuard(saved[2]):
            def __init__(self, deadline, base):
                super().__init__(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                                 signed=lambda e: True, base=base)
        scaling.Guard = FakeGuard
        scaling.prepare()
        baseline = json.loads((base / "baseline.json").read_text())
        sizes = {a: v["findings"] for a, v in baseline["stores"].items()}
        self.assertEqual((sizes["K0"], sizes["K200"], sizes["K1"], sizes["K2"], sizes["K3"]), (150, 532, 2170, 5021, 8905))
        self.assertEqual((sizes["M1"], sizes["M3"]), (2170, 8905))
        self.assertTrue(baseline["cutReproducesK0"])
        # A cut store has no review after its cut and full-text rows only for what it kept.
        db = sqlite3.connect(knowledge.database(scaling.workspace("K1")))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM findings WHERE COALESCE(reviewed_at,'') > ?",
                                    (scaling.CUTS["K1"],)).fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM findings_fts").fetchone()[0], 2170)
        db.close()
        # Three questions, one per stratum, in place of the sixty.
        questions = json.loads((scaling.ABLATION / "heldout.json").read_text())
        picked = [next(q for q in questions if q["stratum"] == s) for s in ("near", "mid", "far")]
        heldout = base / "ablation-heldout.json"
        heldout.write_text(json.dumps(picked))
        original = scaling.ABLATION
        for arm in scaling.RECHECK_ARMS:  # copies of the three questions' traces, not links into test 1's folder
            runs = scaling.workspace(arm) / ".oopc/runs"
            runs.unlink()
            runs.mkdir()
            for q in picked:
                run_id = json.loads((original / "results" / ("%s-%s-answer.json" % (q["id"][:12], arm))).read_text()).get("runId")
                if run_id and (original / "workspaces" / arm / ".oopc/runs" / run_id).is_dir():
                    shutil.copytree(original / "workspaces" / arm / ".oopc/runs" / run_id, runs / run_id)
        fake = base / "ablation"
        fake.mkdir()
        (fake / "heldout.json").write_text(heldout.read_text())
        (fake / "results").symlink_to(original / "results", target_is_directory=True)
        (fake / "workspaces").symlink_to(original / "workspaces", target_is_directory=True)
        scaling.ABLATION = analyze.ABLATION = fake
        self.addCleanup(lambda: (setattr(scaling, "ABLATION", original), setattr(analyze, "ABLATION", original)))
        scaling.run()
        research = [c for c in engine.calls if c[0] == "research"]
        checks = [c for c in engine.calls if c[0] == "check"]
        self.assertEqual(len(research), 3 * len(scaling.ANSWER_ARMS))  # no new answers for the rechecked arms
        self.assertEqual(sum(not web for _, web, _ in research), 3 * len(scaling.NO_WEB))
        self.assertEqual(len(checks), 3 * (len(scaling.ANSWER_ARMS) + len(scaling.RECHECK_ARMS)))
        self.assertTrue(all(given for _, _, given in checks))  # every check is given the session's searches
        self.assertEqual(json.loads((base / "state.json").read_text())["status"], "completed")
        scaling.run()  # Resuming answers and checks nothing again.
        self.assertEqual(len(engine.calls), len(research) + len(checks))
        value = analyze.main()
        self.assertEqual(value["complete"], 3)
        self.assertEqual(value["storeSizes"]["K2"], 5021)
        self.assertIn("cleanMemoryEffect", value["test1Secondary"])
        self.assertEqual(value["byStratum"]["all"]["arms"]["M3"]["noWeb"], 3)


if __name__ == "__main__":
    unittest.main()
