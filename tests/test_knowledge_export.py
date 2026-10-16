"""A public knowledge snapshot keeps findings with their provenance and review verdicts, and nothing private."""
import json
import tempfile
import unittest
from pathlib import Path

from oopc import knowledge
from oopc.cli import main
from oopc.release import build_release
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology


def finding(n, *, flagged=False, url=None):
    return {"statement": "PLA film %d reached %d%% crystallinity by DSC." % (n, 30 + n), "material": "PLA film",
            "property": "degree of crystallinity", "value": str(30 + n), "unit": "%", "conditions": "second heating, 10 K/min",
            "sourceTitle": "Paper %d" % n, "sourceUrl": url or "https://example.org/p%d" % n, "sourceDoi": "10.1/p%d" % n,
            "locator": "Table %d" % n, "excerpt": "secret verbatim span %d" % n, "needsReview": flagged,
            "reviewFlag": "read from a figure" if flagged else ""}


class KnowledgeExport(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-export-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        records = [{"@id": "wop-000001", "@type": "PolymerConcept", "label": "Polylactide", "abbreviations": ["PLA"],
                    "status": "seed", "layer": "science"}]
        build_release(self.root / "releases/fixture", records, get_ontology(), {})
        release_id = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / release_id)
        atomic_json(self.root / "releases/current.json", {"release_id": release_id})
        self.release_id = release_id
        self.question = "a" * 32
        knowledge.deposit(self.root, self.question, {
            "findings": [finding(1), finding(2, flagged=True), finding(3)],
            "sources": [{"title": "Paper 1", "url": "https://example.org/p1", "doi": "10.1/p1", "locator": "Table 1",
                         "excerpts": ["secret note excerpt"], "supports": "crystallinity of PLA films",
                         "conditions": "DSC", "readUrl": "https://mirror.example.org/p1"}]},
            engine="codex", spot_check_rate=0, question="What crystallinity do PLA films reach?")
        ids = [row["id"] for row in knowledge.for_question(self.root, self.question)]
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET status='supported', review_reason='Table 2 shows 32%.', reviewer_engine='codex', "
                       "reviewed_at='2026-10-13T00:00:00+00:00' WHERE id=?", (ids[1],))
            db.execute("UPDATE findings SET status='unsupported', review_reason='Table 3 gives another specimen.', "
                       "reviewer_engine='codex', reviewed_at='2026-10-13T00:00:00+00:00' WHERE id=?", (ids[2],))

    def test_the_snapshot_keeps_provenance_and_verdicts_and_withholds_what_is_private(self):
        manifest = knowledge.export(self.root, self.root / "snapshot")
        folder = self.root / "snapshot"
        findings = [json.loads(line) for line in (folder / "findings.jsonl").read_text().splitlines()]
        notes = [json.loads(line) for line in (folder / "notes.jsonl").read_text().splitlines()]
        self.assertEqual([f["statusLabel"] for f in findings], ["Added", "Reviewed", "Rejected"])
        self.assertEqual(findings[0]["polymer"], "wop-000001")
        self.assertEqual(findings[0]["polymerLabel"], "Polylactide")
        self.assertEqual(findings[0]["source"], {"title": "Paper 1", "url": "https://example.org/p1", "doi": "10.1/p1"})
        self.assertEqual(findings[2]["review"]["reason"], "Table 3 gives another specimen.")
        self.assertNotIn("review", findings[0])
        self.assertEqual(notes[0]["readUrl"], "https://mirror.example.org/p1")
        text = "".join(p.read_text() for p in folder.iterdir())
        for private in ("secret", self.question, "read from a figure", "What crystallinity", str(self.root)):
            self.assertNotIn(private, text)
        self.assertEqual(manifest["counts"], {"findings": 3, "byStatus": {"Added": 1, "Reviewed": 1, "Rejected": 1},
                                              "notes": 1, "polymers": 1, "sources": 3})
        self.assertEqual(manifest["graphRelease"], self.release_id)
        self.assertEqual(json.loads((folder / "manifest.json").read_text()), manifest)
        # The id names the content: the same knowledge gives the same id, and a snapshot is never overwritten.
        again = knowledge.export(self.root, self.root / "again")
        self.assertEqual(again["snapshotId"], manifest["snapshotId"])
        self.assertEqual((self.root / "again/findings.jsonl").read_bytes(), (folder / "findings.jsonl").read_bytes())
        with self.assertRaises(ValueError):
            knowledge.export(self.root, folder)

    def test_a_snapshot_starts_an_empty_workspace_with_the_same_knowledge(self):
        manifest = knowledge.export(self.root, self.root / "snapshot")
        other = self.root / "other"
        (other / "releases").mkdir(parents=True)
        (other / "releases" / self.release_id).symlink_to(self.root / "releases" / self.release_id, target_is_directory=True)
        atomic_json(other / "releases/current.json", {"release_id": self.release_id})
        main(["--root", str(other), "knowledge", "--import", str(self.root / "snapshot")])
        self.assertEqual(knowledge.summary(other)["findings"], {"accepted": 1, "supported": 1, "unsupported": 1})
        self.assertEqual(knowledge.review_queue(other), [])
        added = [f["id"] for f in knowledge.search(other, "PLA crystallinity", compact=True)["added"]]
        self.assertEqual(added, ["finding:" + "a" * 12 + "-1"])  # rejected findings stay hidden
        self.assertEqual(knowledge.export(other, self.root / "again")["snapshotId"], manifest["snapshotId"])
        with self.assertRaises(ValueError):  # never merged into a store that holds knowledge
            knowledge.import_snapshot(other, self.root / "snapshot")
        (self.root / "snapshot/notes.jsonl").write_text("{}\n")
        with self.assertRaises(ValueError):
            knowledge.import_snapshot(self.root / "third", self.root / "snapshot")

    def test_a_local_path_stops_the_export_before_anything_is_written(self):
        knowledge.deposit(self.root, "b" * 32, {"findings": [finding(4, url="file:///Users/someone/paper.pdf")],
                                               "sources": []}, engine="codex", spot_check_rate=0)
        with self.assertRaises(ValueError):
            knowledge.export(self.root, self.root / "snapshot")
        self.assertFalse((self.root / "snapshot").exists())
        self.assertFalse((self.root / ".snapshot.partial").exists())

    def test_the_command_line_writes_a_snapshot(self):
        main(["--root", str(self.root), "knowledge", "--export", str(self.root / "cli-snapshot")])
        self.assertTrue((self.root / "cli-snapshot/manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
