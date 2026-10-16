"""Offline check of E9 with a scripted engine: no subscription is used.

E9's test_planted.py (`.oopc/loop/harness/2026-10-planted/`), moved to the repository on 2026-10-13 unchanged except
imports and paths, the guard's run folder passed as `base` (the shared guard is patched on the planted module, not on a
loaded campaign module), and a skip when test 1's frozen K3 store is absent."""
import json, sys, tempfile, threading, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT  # noqa: E402  (common puts CODE first on sys.path)
from planted import planted  # noqa: E402
from oopc import ask, knowledge, reviewer  # noqa: E402

NEEDS = [knowledge.database(planted.SOURCE), ROOT / "releases/current.json"]


class Engine:
    def __init__(self):
        self.calls, self.lock, self.seen = [], threading.Lock(), []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None):
        kind = "research" if schema is ask.ANSWER_SCHEMA else "check" if schema is reviewer.CHECK_SCHEMA else "review"
        with self.lock:
            self.calls.append(kind)
        if kind == "research":
            found = tools.call("search_knowledge", {"q": "PEEK 5600G tensile strength"})
            ids = [f["id"] for g in ("reviewed", "added") for f in found.get(g, [])]
            with self.lock:
                self.seen.append(ids)
            cite = [i for i in ids if i == "finding:d9ed304a4ed8-3"] or ids[:1]
            answer = {"answer": "Tensile strength 12.27 MPa `%s`." % cite[0] if cite else "none",
                      "citations": cite, "findings": [], "sources": [], "limitations": [], "openQuestions": []}
        elif kind == "check":
            answer = {"verdict": "fail", "notes": "", "statements": [
                {"statement": "x", "verdict": "unsupported", "reason": "Table 3 says 122.70", "kind": "source-fact",
                 "category": "value"}]}
        else:
            ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"]]
            answer = {"verdicts": [{"id": i, "verdict": "unsupported", "reason": "The source says otherwise."} for i in ids],
                      "notes": ""}
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 0.1}


@unittest.skipUnless(all(p.exists() for p in NEEDS), "needs test 1's frozen K3 store and a graph release "
                     "(private records under .oopc/ and releases/)")
class Planted(unittest.TestCase):
    def test_plant_answer_review_and_answer_again(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-planted-test-")
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        saved = (planted.BASE, planted.Guard, planted.QUIET_FOR)
        self.addCleanup(lambda: (setattr(planted, "BASE", saved[0]), setattr(planted, "Guard", saved[1]),
                                 setattr(planted, "QUIET_FOR", saved[2])))
        planted.BASE = base
        planted.QUIET_FOR = []
        engine = Engine()

        class FakeGuard(saved[1]):
            def __init__(self, deadline, base):
                super().__init__(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                                 signed=lambda e: True, base=base)
        planted.Guard = FakeGuard
        planted.prepare()
        store = planted.workspace("planted")
        peek = knowledge.get(store, "finding:d9ed304a4ed8-3")
        self.assertEqual((peek["value"], peek["status"]), ("12.27", knowledge.ACCEPTED))
        self.assertNotIn("excerpt", peek)
        hits = knowledge.search(store, "PEEK 5600G tensile strength 12.27", compact=True)
        self.assertIn("finding:d9ed304a4ed8-3", [f["id"] for f in hits["added"]])
        self.assertEqual(knowledge.get(planted.workspace("C"), "finding:d9ed304a4ed8-3")["value"], "122.70")
        planted.run()
        self.assertEqual(engine.calls.count("review"), 1)
        self.assertEqual(engine.calls.count("research"), 5 * 5)
        self.assertEqual(engine.calls.count("check"), 5 * 5)
        value = json.loads((base / "report.json").read_text())
        self.assertEqual({v["status"] for v in value["reviewerVerdicts"].values()}, {knowledge.UNSUPPORTED})
        # After review the planted findings are hidden: B arms never see the PEEK one.
        b_seen = [ids for ids in engine.seen[-10:]]
        self.assertTrue(all("finding:d9ed304a4ed8-3" not in ids for ids in b_seen))
        gross_a = [r for r in value["answers"] if r["case"] == "gross" and r["arm"] == "A"]
        self.assertTrue(all(r["plantedValue"] and r["citesPlanted"] for r in gross_a))
        calls = len(engine.calls)
        planted.run()  # nothing again
        self.assertEqual(len(engine.calls), calls)


if __name__ == "__main__":
    unittest.main()
