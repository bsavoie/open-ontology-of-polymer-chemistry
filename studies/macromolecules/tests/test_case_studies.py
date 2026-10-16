"""The case studies offline, with a scripted engine: every study's arms answer and are checked, cs4's first askings go
through the loop (saved and reviewed) and its repeats read what they saved; nothing runs without the tag."""
import contextlib, io, json, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driver  # noqa: E402
from case_studies import case_studies  # noqa: E402
from oopc import ask, knowledge, parity, reviewer  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402


class Engine:
    def __init__(self):
        self.calls = []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        if schema is parity.DIRECT_SCHEMA:
            kind = "plain"
            answer = {"answer": "Not found in open sources.", "citations": [], "limitations": []}
        elif schema is ask.ANSWER_SCHEMA:
            found = tools.call("search_knowledge", {"q": prompt[-80:]}) if tools else {}
            notes = [n["id"] for n in found.get("notes", [])]
            kind = "research-with-notes" if notes else "research"
            answer = {"answer": "Not found in open sources; the sources read report no such value.", "citations": [],
                      "findings": [], "limitations": [], "openQuestions": [],
                      "sources": [{"title": "Fiber handbook", "url": "https://example.org/fiber", "doi": "",
                                   "locator": "Table 2", "excerpts": [], "supports": "lacks oxygen permeability",
                                   "conditions": "", "readUrl": ""}]}
        elif schema is reviewer.CHECK_SCHEMA:
            kind = "check"
            answer = {"verdict": "pass", "resultGiven": False, "notes": "", "statements": [
                {"statement": "Not found", "verdict": "supported", "reason": "Stated", "kind": "completeness",
                 "category": "none", "evidence": "live"}]}
        else:
            kind = "review"
            ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"]]
            answer = {"verdicts": [{"id": i, "verdict": "supported", "reason": "ok"} for i in ids], "notes": ""}
        self.calls.append(kind)
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 1.0}


class CaseStudies(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-cases-test-")
        self.addCleanup(folder.cleanup)
        root, base = Path(folder.name).resolve() / "source", Path(folder.name).resolve() / "run"
        path = build_release(root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                             "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
        release_id = json.loads((path / "manifest.json").read_text())["release_id"]
        path.rename(root / "releases" / release_id)
        atomic_json(root / "releases/current.json", {"release_id": release_id})
        with knowledge.connect(root):  # an empty store
            pass
        for name, value in (("ROOT", root), ("BASE", base)):
            patch = mock.patch.object(case_studies, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(case_studies, "frozen", return_value="tag")
        patch.start()
        self.addCleanup(patch.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.base = base

    def test_every_study_runs_and_cs4_repeats_read_what_the_first_askings_saved(self):
        engine = Engine()
        real_guard = driver.Guard

        def guard(deadline, base=None, **_):
            return real_guard(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                              signed=lambda e: True, base=base)
        with mock.patch.object(driver, "Guard", guard):
            case_studies.prepare()
            state = case_studies.run(hours=1)
        self.assertEqual(state["status"], "completed", state)
        # cs1 and cs2: 3 questions x 2 arms; cs3: 2 x 3; cs4 first askings: 3 through the loop; cs4 repeats: 3 x 2.
        self.assertEqual(engine.calls.count("plain"), 3 + 3 + 2 + 3)
        self.assertEqual(engine.calls.count("check"), 6 + 6 + 6 + 3 + 6)
        firsts = [read_json(p) for p in sorted((self.base / "cs4-first/items").glob("*.json"))]
        self.assertEqual(len(firsts), 3)
        self.assertTrue(all(f["deposit"]["counts"] is not None for f in firsts))
        # The repeats' searches found the notes the first askings left; the other studies' stores had none.
        self.assertEqual(engine.calls.count("research-with-notes"), 3)
        value = case_studies.report()
        self.assertEqual(sorted(value), ["cs1-conditions", "cs2-conflicts", "cs3-screening", "cs4-first", "cs4-repeat"])
        calls = len(engine.calls)
        with mock.patch.object(driver, "Guard", guard):
            case_studies.run(hours=1)  # resuming repeats nothing
        self.assertEqual(len(engine.calls), calls)

    def test_nothing_runs_without_the_tag(self):
        with mock.patch.object(case_studies, "frozen", side_effect=SystemExit("no tag")):
            with self.assertRaises(SystemExit):
                case_studies.prepare()


if __name__ == "__main__":
    unittest.main()
