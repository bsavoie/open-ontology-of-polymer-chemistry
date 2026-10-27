"""Blind scoring of the case studies' answers with a scripted scorer: the scorer sees neither arms nor citations, and
the report joins its counts back to the arms."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_studies import score  # noqa: E402
from oopc.util import atomic_json  # noqa: E402

R_TEXT = ("PVA's Tg is 85 °C by DSC at 10 °C/min (second heating) `finding:abc123-4`, and 105 °C as the tan delta "
          "peak by DMA at 1 Hz [Lee 2020](https://doi.org/10.1/x). The saved findings give no other value.")
P_TEXT = "PVA's Tg is about 80 °C https://example.org/pva.pdf, perhaps 75 °C."


class Scorer:
    def __init__(self):
        self.prompts = []

    def __call__(self, engine, prompt, schema, **options):
        self.prompts.append(prompt)
        codes = [e["code"] for e in json.loads(prompt[prompt.index("\n[") + 1:])]
        fields = schema["properties"]["scores"]["items"]["properties"]
        scores = [{k: (0 if v["type"] == "integer" else False) for k, v in fields.items() if k != "code"} | {
            "code": c, "uncitedValues": 1} for c in codes]
        return {"engine": engine, "model": "scripted", "sessionId": "s", "usage": {}, "observedTools": [],
                "agentSeconds": 0.1, "answer": {"scores": scores, "notes": ""}}


class CaseStudyScoringTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-scoring-test-")
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        atomic_json(self.base / "cs1-conditions/plan.json", {"questions": [{"id": "pva", "question": "PVA Tg?"}]})
        for arm, text in (("R", R_TEXT), ("P", P_TEXT)):
            item = {"question": "pva", "arm": arm, "answer": {"answer": {
                "answer": text, "citations": [], "limitations": ["Only open sources were read."]}}}
            atomic_json(self.base / ("cs1-conditions/items/0000-%s.json" % arm), item)
        atomic_json(self.base / "cs4-first/items/novoloid.json", {"question": {"id": "novoloid", "question": "Q"},
                    "answer": {"answer": {"answer": "Not found in open sources.", "limitations": []}}})

    def test_the_scorer_is_blind_and_the_report_joins_its_counts_to_the_arms(self):
        blinded = score.blind(R_TEXT)
        self.assertNotIn("finding:", blinded)
        self.assertNotIn("https://", blinded)
        self.assertIn("[S1]", blinded)
        self.assertIn("Lee 2020 [S2]", blinded)
        self.assertIn("sources give no other value", blinded)
        self.assertEqual(score.blind("Saved-knowledge searches found none; the saved 23 °C result stands."),
                         "sources searches found none; the 23 °C result stands.")
        scorer = Scorer()
        value = score.run(self.base, runner=scorer)
        self.assertEqual(len(scorer.prompts), 2)  # one session per study
        for prompt in scorer.prompts:
            self.assertNotIn("finding:", prompt)
            self.assertNotIn('"arm"', prompt)
        self.assertEqual(value["byArm"]["cs1-conditions/R"]["answers"], 1)
        self.assertEqual(value["byArm"]["cs1-conditions/P"]["uncitedValues"], 1)
        self.assertEqual(value["byArm"]["cs4/first"]["answers"], 1)
        score.run(self.base, runner=scorer)
        self.assertEqual(len(scorer.prompts), 2)  # scored groups are not scored again


if __name__ == "__main__":
    unittest.main()
