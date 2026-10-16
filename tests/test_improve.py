"""Measure: the weekly summary, and comparing two parity runs like for like."""
import json
from pathlib import Path
import tempfile
import unittest

from oopc import improve, parity
from oopc.ask import ANSWER_SCHEMA, RESEARCHER, Questions, prompt_version, researcher_prompt
from oopc.release import build_release
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology


class Engine:
    """Answers questions and parity checks the way a real engine would, with fixed usage."""

    def __init__(self):
        self.prompts = []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        self.prompts.append(prompt)
        usage = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100}
        if schema is ANSWER_SCHEMA:
            answer = {"answer": "x", "citations": [], "findings": [], "sources": [], "limitations": [], "openQuestions": []}
        elif schema is parity.DIRECT_SCHEMA:
            answer = {"answer": "x", "citations": [], "limitations": []}
        else:
            answer = {"verdict": "pass", "statements": [{"statement": "x", "verdict": "supported", "reason": "ok"}], "notes": ""}
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer, "usage": usage,
                "observedTools": [], "agentSeconds": 1.0}


class ImproveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-improve-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        path = build_release(self.root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                             "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
        release_id = json.loads((path / "manifest.json").read_text())["release_id"]
        path.rename(self.root / "releases" / release_id)
        atomic_json(self.root / "releases/current.json", {"release_id": release_id})

    def test_the_researcher_prompt_is_the_one_in_code(self):
        prompt = researcher_prompt("What crystallinity does PLA reach?", "quick")
        self.assertIn("about 6 web searches and 4 sources", prompt)
        self.assertTrue(prompt.rstrip().endswith("What crystallinity does PLA reach?"))
        self.assertEqual(prompt.count("Question:"), 1)
        self.assertIn('"Interpretation:"', RESEARCHER)
        engine = Engine()
        service = Questions(self.root, runner=engine)
        view = service.submit({"question": "What crystallinity does PLA reach?", "authorizeSubscription": True,
                               "runtime": "codex", "depth": "quick"})
        service.wait(10)
        self.assertEqual(engine.prompts[0], prompt)
        result = json.loads((self.root / ".oopc/loop/questions" / view["id"] / "result.json").read_text())
        self.assertEqual(result["promptVersion"], prompt_version())

    def test_the_summary_reads_answers(self):
        service = Questions(self.root, runner=Engine())
        service.submit({"question": "What crystallinity does PLA reach?", "authorizeSubscription": True, "runtime": "codex"})
        service.wait(10)
        value = improve.summary(self.root)
        self.assertEqual((value["answered"], value["answeredWithoutWeb"], value["medianNewTokens"]), (1, 1, 1100))
        self.assertEqual(value["reviews"]["waiting"], 0)
        self.assertEqual(value["loopCosts"]["byPhase"]["research"]["calls"], 1)

    def test_runs_are_compared_like_for_like(self):
        def report(passes, failed=()):
            rows = [{"id": "q%d" % n, "arms": {"ontology": {"checkError": {"reason": "quota"}} if n in failed else
                     {"verdict": "pass" if n < passes else "fail", "citedFraction": 1.0,
                      "metrics": {"newTokens": 100 * (n + 1)}}}} for n in range(8)]
            return {"rows": rows}
        value = improve.compare(report(4), report(6, failed=(6, 7)))
        self.assertEqual((value["compared"], value["checked"], value["passes"]), (6, (8, 6), (4, 6)))
        self.assertEqual(value["medianNewTokens"], (350, 350))  # The same six questions on both sides.
        self.assertTrue(value["recommended"])
        self.assertFalse(improve.compare(report(4), report(8, failed=(2, 3, 4)))["recommended"])  # Five compared.
        # A lower median does not hide one slow outlier: the total may rise at most 10%.
        outlier = report(6)
        outlier["rows"][7]["arms"]["ontology"]["metrics"]["newTokens"] = 2000
        value = improve.compare(report(4), outlier)
        self.assertEqual((value["medianNewTokens"], value["totalNewTokens"]), ((450, 450), (3600, 4800)))
        self.assertFalse(value["recommended"])


if __name__ == "__main__":
    unittest.main()
