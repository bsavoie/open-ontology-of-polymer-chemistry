"""The polymer-filter measurement (P1-9) on a small workspace: what a search naming a question's polymer keeps."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
from analysis import polymer_filter  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

POLYMERS = [("wop-000001", "Polyethylene family", ["PE"]), ("wop-000002", "High-density polyethylene", ["HDPE"]),
            ("wop-000003", "Polylactide", ["PLA"])]


def finding(statement, material, subject=""):
    return {"statement": statement, "material": material, "property": "", "value": "", "unit": "", "conditions": "",
            "subject": subject, "sourceTitle": "", "sourceUrl": "https://example.org/a", "sourceDoi": "",
            "locator": "Table 1", "excerpt": statement, "derivation": "read"}


class PolymerFilterTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-filter-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        records = [{"@id": i, "@type": "PolymerConcept", "label": label, "abbreviations": names, "status": "seed",
                    "layer": "science"} for i, label, names in POLYMERS]
        records += [{"@id": "claim:%s-%s-%s" % (s, p, o), "@type": "Claim", "label": "%s %s %s" % (s, p, o),
                     "subject": s, "predicate": p, "object": o, "context": {}, "evidence": [], "status": "seed",
                     "layer": "science"} for s, p, o in (("wop-000002", "broader", "wop-000001"),
                                                         ("wop-000001", "narrower", "wop-000002"))]
        build_release(self.root / "releases/fixture", records, get_ontology(), {})
        release = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / release)
        atomic_json(self.root / "releases/current.json", {"release_id": release})
        question = "q" * 32
        knowledge.deposit(self.root, question, {"sources": [], "findings": [
            finding("HDPE pipe grade had a density of 0.95 g/cm3.", "HDPE pipe grade"),
            finding("The resin had a melt flow index of 0.3 g/10 min.", "Marlex 9006", subject="wop-000001"),
            finding("The PLA control had a Tg of 60 °C.", "PLA control")]}, engine="codex", spot_check_rate=0,
            question="What density does HDPE reach?")
        with knowledge.connect(self.root) as db:  # As a deposit before 2026-10-12 filed it: under the family.
            db.execute("UPDATE findings SET subject='wop-000001' WHERE material='Marlex 9006'")
        atomic_json(knowledge.folder(self.root) / "questions" / question / "question.json",
                    {"id": question, "question": "What density does HDPE reach?"})
        self.question = question

    def test_lineage_keeps_a_family_filed_finding_that_exact_ids_drop(self):
        value = polymer_filter.measure(self.root, knowledge.database(self.root), [(self.question, "HDPE")])
        self.assertEqual((value["findings"], value["keptExact"], value["keptLineage"]), (3, 1, 2))  # The PLA control drops.
        self.assertEqual(polymer_filter.question_tasks(self.root), [(self.question, "What density does HDPE reach?")])

    def test_a_material_naming_no_known_polymer_is_left_out(self):
        value = polymer_filter.measure(self.root, knowledge.database(self.root), [(self.question, "Surlyn 8940")])
        self.assertEqual((value["findings"], value["leftOut"], value["shareLineage"]), (0, 3, None))


if __name__ == "__main__":
    unittest.main()
