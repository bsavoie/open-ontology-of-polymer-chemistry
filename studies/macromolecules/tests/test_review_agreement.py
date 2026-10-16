"""Second reviews of a sample (P0-5) with a scripted reviewer: agreement on content verdicts, statuses untouched."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
from analysis import review_agreement  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402


def finding(n):
    return {"statement": "PLA grade %d had a Tg of %d °C." % (n, 50 + n), "material": "PLA grade %d" % n,
            "property": "glass transition temperature (Tg)", "value": str(50 + n), "unit": "°C", "conditions": "DSC",
            "subject": "", "sourceTitle": "Paper", "sourceUrl": "https://example.org/p%d" % n, "sourceDoi": "",
            "locator": "Table 1", "excerpt": "Tg %d °C" % (50 + n), "derivation": "figure"}


class Reviewer:
    """Agrees except on finding 2, cannot read finding 3's source, and finds 4 and 5 unsupported."""

    def __init__(self):
        self.calls = 0

    def __call__(self, engine, prompt, schema, **options):
        self.calls += 1
        ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"]]
        verdict = lambda i: (("unsupported", "Table 1 gives another value.") if i.endswith(("-2", "-4", "-5")) else
                             ("uncertain", "The publisher page returned 403.") if i.endswith("-3") else
                             ("supported", "Table 1."))
        return {"engine": engine, "model": "scripted", "sessionId": "s", "usage": {}, "observedTools": [],
                "agentSeconds": 0.1, "answer": {"notes": "", "verdicts": [
                    {"id": i, "verdict": verdict(i)[0], "reason": verdict(i)[1], "excerpt": ""} for i in ids]}}


class ReviewAgreementTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-agreement-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        build_release(self.root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                      "label": "Polylactide", "abbreviations": ["PLA"], "status": "seed", "layer": "science"}],
                      get_ontology(), {})
        release = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / release)
        atomic_json(self.root / "releases/current.json", {"release_id": release})
        knowledge.deposit(self.root, "a" * 32, {"findings": [finding(n) for n in range(1, 6)], "sources": []},
                          engine="codex", spot_check_rate=0)
        knowledge.record_review(self.root, "a" * 32, engine="codex", started_at="", seconds=1, usage={}, verdicts={
            i: {"verdict": "supported", "reason": "Table 1.", "excerpt": ""}
            for i in [f["id"] for f in knowledge.for_question(self.root, "a" * 32)]})
        # Finding 4's polymer name was left unsettled (no content verdict); a second review of Reviewed finding 5
        # found it unsupported.
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET status='uncertain', detail=json_set(detail, '$.ambiguous', json('[\"PEI\"]')) "
                       "WHERE id LIKE '%-4'")
            db.execute("UPDATE findings SET status='uncertain', detail=json_set(detail, '$.recheck', 'unsupported') "
                       "WHERE id LIKE '%-5'")
        self.out = self.root / "agreement"

    def test_agreement_counts_content_verdicts_and_never_changes_the_store(self):
        sample = review_agreement.prepare(self.root, size=5, out=self.out)
        self.assertEqual(len(sample["ids"]), 5)
        with self.assertRaises(ValueError):
            review_agreement.prepare(self.root, size=5, out=self.out)  # A sample is drawn once.
        before = {f["id"]: f["status"] for f in knowledge.for_question(self.root, "a" * 32)}
        engine = Reviewer()
        value = review_agreement.run(runner=engine, out=self.out)
        self.assertEqual((value["content"], value["agree"], value["access"], value["unsettledName"], value["agreement"]),
                         (3, 2, 1, 1, 0.667))
        self.assertEqual((value["supported→unsupported"], value["unsupported→unsupported"]), (1, 1))
        self.assertEqual((value["currentContent"], value["currentAgreement"], value["earlierAgreement"]), (3, 0.667, None))
        self.assertEqual((value["allPairs"], value["allAgree"], value["allAgreement"]), (4, 1, 0.25))
        self.assertEqual({f["id"]: f["status"] for f in knowledge.for_question(self.root, "a" * 32)}, before)
        review_agreement.run(runner=engine, out=self.out)
        self.assertEqual(engine.calls, 1)  # Done groups are not reviewed again.
        # The first reviews are pinned with the sample: applying the second review's verdict changes nothing measured.
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET status='unsupported' WHERE id LIKE '%-2'")
        self.assertEqual(review_agreement.report(out=self.out)["agreement"], 0.667)
        with self.assertRaises(ValueError):
            review_agreement.pin(knowledge.database(self.root), out=self.out)  # Never re-pinned.


if __name__ == "__main__":
    unittest.main()
