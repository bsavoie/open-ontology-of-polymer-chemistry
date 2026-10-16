import hashlib
import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from oopc.seed import import_seed
from oopc.release import build_release, load_release, verify_release
from oopc.validation import validate_records


def snapshot_fixture():
    source = {"sourceId": "shared-local-id", "lineageId": "independent-lab", "sourceType": "open_journal",
              "citation": "Fixture source", "doi": "10.1234/FIXTURE", "url": "https://example.org/paper",
              "locator": "Section 2", "accessedDate": "2026-09-10", "accessStatus": "anonymous_full_content",
              "reuseStatus": "publicly_accessible_citation_only", "permissionBasis": "Fixture citation only", "supports": ["overview", "structuralDepictions"]}
    mol = "fixture\n  authored\n\n  0  0  0  0  0  0            999 V3000\nM  V30 BEGIN CTAB\nM  V30 COUNTS 0 0 0 0 0\nM  V30 END CTAB\nM  END\n"
    polymers = []
    for i in (1, 2):
        polymers.append({"type": "polymer_entry", "wopId": "wop-%06d" % i, "canonicalName": "Fixture %d" % i,
                         "canonicalSlug": "fixture-%d" % i, "alternateNames": [], "abbreviations": [], "entryKind": "family",
                         "taxonomy": {"primaryClass": "fixture", "materialBehaviors": ["first", "second"]},
                         "relationships": [{"kind": "related", "wopId": "wop-%06d" % (3-i)}],
                         "sections": {"overview": "Attributed text with original Ω and spacing.\n\nSecond paragraph.", "history": ""},
                         "sources": [deepcopy(source)], "maturity": {"contentMaturity": "source_backed_draft"},
                         "structuralDepictions": {"reviewStatus": "reviewed", "scopeNote": "Representative fixture only.",
                                                  "representationType": "family_representative_set", "sourceIds": ["shared-local-id"],
                                                  "items": [{"structureId": "fixture", "label": "Fixture", "fidelity": "representative", "caption": "Fixture only", "altText": "Fixture"}]},
                         "contextualStructures": {}, "synthesisRoutes": []})
    return {"schema": "wop-publication-snapshot-v2", "methodology": {"sources": []}, "chemicalStructures": [{"structureId": "fixture", "molfileV3000": mol}],
            "polymers": polymers, "aliases": [{"slug": "old-name", "wopId": "wop-000001"}], "searchTerms": [{"term": "fixture search", "wopIds": ["wop-000002"], "kind": "umbrella"}]}


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.snapshot = snapshot_fixture()
        self.source = self.root / "snapshot.json"
        self.source.write_text(json.dumps(self.snapshot, ensure_ascii=False), encoding="utf-8")
        self.original = self.source.read_bytes()
        self.records, self.ontology, self.metadata = import_seed(self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scope_dedup_and_lossless_seed(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.metadata["seed_snapshot_sha256"], hashlib.sha256(self.original).hexdigest())
        indexed = {r["@id"]: r for r in self.records}
        for p in self.snapshot["polymers"]:
            self.assertEqual(indexed[p["wopId"]]["taxonomy"], p["taxonomy"])
            self.assertEqual(indexed[p["wopId"]]["maturity"], p["maturity"])
            for key, text in p["sections"].items():
                self.assertEqual(indexed["section:" + p["wopId"] + ":" + key]["text"], text)
        evidence = [r for r in self.records if r["@type"] == "Evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertNotEqual(evidence[0]["@id"], evidence[1]["@id"])
        self.assertEqual(evidence[0]["document"], evidence[1]["document"])
        self.assertEqual(len([r for r in self.records if r["@type"] == "Document"]), 1)
        self.assertEqual(indexed["structure:fixture"]["molfileV3000"], self.snapshot["chemicalStructures"][0]["molfileV3000"])
        self.assertEqual(self.metadata["aliases"], self.snapshot["aliases"])
        self.assertEqual(self.metadata["searchTerms"], self.snapshot["searchTerms"])
        self.assertTrue(all(r["status"] == "seed" for r in self.records))
        self.assertEqual(validate_records(self.records, self.ontology), [])

    def test_explicit_source_checksum_pin_rejects_changed_input(self):
        expected = hashlib.sha256(self.original).hexdigest()
        records, _, metadata = import_seed(self.source, expected_sha256=expected)
        self.assertEqual(records, self.records)
        self.assertEqual(metadata["seed_snapshot_sha256"], expected)
        self.source.write_bytes(self.original + b"\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            import_seed(self.source, expected_sha256=expected)
        self.assertEqual(self.source.read_bytes(), self.original + b"\n")

    def test_build_is_reproducible_and_contains_real_sqlite_and_rdf(self):
        first = build_release(self.root / "first", self.records, self.ontology, self.metadata)
        second = build_release(self.root / "second", self.records, self.ontology, self.metadata)
        self.assertEqual(verify_release(first), verify_release(second))
        records, ontology, manifest = load_release(first)
        self.assertEqual(records, self.records)
        self.assertEqual(ontology, self.ontology)
        self.assertTrue(manifest["release_id"].startswith("oopc-"))
        with sqlite3.connect(first / "graph.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], len(records))
            self.assertEqual(db.execute("SELECT count(*) FROM edges").fetchone()[0], sum(r["@type"] == "Claim" for r in records))
            self.assertTrue(db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'Attributed'").fetchall())
        rdf = (first / "graph.nt").read_text()
        self.assertIn("<https://bsavoie.github.io/open-ontology-of-polymer-chemistry/vocab/Claim>", rdf)
        self.assertNotIn("<https://bsavoie.github.io/open-ontology-of-polymer-chemistry/record/wop-000001> <https://bsavoie.github.io/open-ontology-of-polymer-chemistry/vocab/related>", rdf)
        self.assertEqual(build_release(first, self.records, self.ontology, self.metadata), first)

    def test_bad_candidate_leaves_valid_release_intact(self):
        dest = build_release(self.root / "valid", self.records, self.ontology, self.metadata)
        previous = (dest / "manifest.json").read_bytes()
        candidate = deepcopy(self.records)
        claim = next(r for r in candidate if r["@type"] == "Claim")
        claim["object"] = "missing:entity"
        with self.assertRaises(ValueError):
            build_release(dest, candidate, self.ontology, self.metadata)
        self.assertEqual((dest / "manifest.json").read_bytes(), previous)
        verify_release(dest)
        self.assertEqual(list(self.root.glob(".oopc-release-*")), [])

    def test_immutable_and_checksum_verified(self):
        dest = build_release(self.root / "valid", self.records, self.ontology, self.metadata)
        with self.assertRaises(FileExistsError):
            build_release(dest, self.records, self.ontology, {**self.metadata, "description": "changed"})
        (dest / "records.jsonl").write_text("corruption")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_release(dest)

    def test_never_overwrite_unowned_destination(self):
        dest = self.root / "user-folder"
        dest.mkdir()
        (dest / "important.txt").write_text("preserve me")
        with self.assertRaises(ValueError):
            build_release(dest, self.records, self.ontology, self.metadata)
        self.assertEqual((dest / "important.txt").read_text(), "preserve me")


if __name__ == "__main__":
    unittest.main()
