"""One-off store upkeep before a freeze: each action reports first, and changes the store only with apply."""
import json
from pathlib import Path
import tempfile
import unittest

from oopc import knowledge, reviewer, sources, upkeep
from oopc.release import build_release
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology

POLYMERS = [("wop-000001", "Polyethylene family", ["PE"]), ("wop-000002", "High-density polyethylene", ["HDPE"]),
            ("wop-000003", "Polyetherimide", ["PEI"]), ("wop-000004", "Polyethyleneimine", ["PEI"]),
            ("wop-000005", "Thermoplastic vulcanizate", ["TPV"]), ("wop-000006", "Polyamide family", ["PA"])]
FAMILIES = [("wop-000002", "wop-000001")]


def finding(n, **extra):
    value = {"statement": "HDPE grade %d had a tensile strength of %d MPa." % (n, 20 + n), "material": "HDPE grade %d" % n,
             "property": "tensile strength", "value": str(20 + n), "unit": "MPa", "conditions": "", "subject": "",
             "sourceTitle": "Paper %d" % n, "sourceUrl": "https://example.org/p%d" % n, "sourceDoi": "",
             "locator": "Table 1", "excerpt": "tensile strength of %d MPa" % (20 + n), "derivation": "read"}
    value.update(extra)
    return value


class UpkeepTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-upkeep-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        records = [{"@id": i, "@type": "PolymerConcept", "label": label, "abbreviations": abbreviations,
                    "status": "seed", "layer": "science"} for i, label, abbreviations in POLYMERS]
        records += [{"@id": "claim:%s-%s-%s" % (s, p, o), "@type": "Claim", "label": "%s %s %s" % (s, p, o), "subject": s,
                     "predicate": p, "object": o, "context": {}, "evidence": [], "status": "seed", "layer": "science"}
                    for member, family in FAMILIES for s, p, o in ((member, "broader", family), (family, "narrower", member))]
        build_release(self.root / "releases/fixture", records, get_ontology(), {})
        release_id = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / release_id)
        atomic_json(self.root / "releases/current.json", {"release_id": release_id})

    def save(self, question, items, question_text=""):
        knowledge.deposit(self.root, question * 32, {"findings": items, "sources": []}, engine="codex", spot_check_rate=0,
                          question=question_text)
        if question_text:
            atomic_json(knowledge.folder(self.root) / "questions" / (question * 32) / "question.json",
                        {"id": question * 32, "question": question_text})
        return [f["id"] for f in knowledge.for_question(self.root, question * 32)]

    def set(self, identifier, **columns):
        with knowledge.connect(self.root) as db:
            for key, value in columns.items():
                db.execute("UPDATE findings SET %s=? WHERE id=?" % key, (value, identifier))

    def test_access_uncertain_findings_go_back_to_review_and_the_store_is_backed_up(self):
        flagged, sampled, ambiguous = self.save("a", [finding(1), finding(2), finding(3)])
        self.set(flagged, status="uncertain", review_reason="The Wiley article returned 403 Forbidden, so Table 1 could not be read.")
        self.set(sampled, status="uncertain", review_reason="The PDF text could not be extracted (compressed stream).",
                 detail=json.dumps({"spotCheck": "uncertain"}))
        self.set(ambiguous, status="uncertain", review_reason="The table gives two values and the row label is ambiguous.")
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE deposits SET review_attempts=2, review_status='reviewed'")
        report = upkeep.requeue(self.root)
        self.assertEqual((report["candidates"], report["sampled"], report["applied"]), (2, 1, False))
        self.assertEqual(knowledge.get(self.root, flagged)["status"], "uncertain")  # A report changes nothing.
        done = upkeep.requeue(self.root, apply=True)
        self.assertTrue((Path(done["backup"]) / "knowledge.sqlite").exists())
        self.assertEqual([knowledge.get(self.root, i)["status"] for i in (flagged, sampled, ambiguous)],
                         ["unreviewed", "accepted", "uncertain"])
        self.assertEqual(knowledge.review_queue(self.root), ["a" * 32])
        self.assertEqual(upkeep.audit(self.root)["accessUncertain"]["count"], 0)

    def test_bare_excerpts_go_to_their_reviewer_and_picked_ones_are_withdrawn(self):
        picked, missing, reviewed = self.save("b", [
            finding(7, statement="HDPE-1 had a tensile strength of 27.4 MPa.", value="27.4", excerpt="27.4"),
            finding(8, excerpt=""), finding(9, excerpt="29 MPa")])
        self.set(reviewed, status="supported")
        self.assertTrue(knowledge.bare_excerpt("27.4") and knowledge.bare_excerpt("29 MPa", "MPa"))
        self.assertFalse(knowledge.bare_excerpt("Tg 58.5 °C", "°C"))
        # An excerpt an earlier pass picked from captured text by itself (here, another measurement's row).
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET excerpt='HDPE-1 | flexural strength | 27.4' WHERE id=?", (picked,))
            knowledge._set_detail(db, picked, excerptFrom={"captured": "https://open.example.org/hdpe", "was": "27.4"})
        report = upkeep.excerpts(self.root, apply=True)
        self.assertEqual((report["withdrawn"], report["sentToSpotCheck"], report["sentToRecheck"]), (1, 2, 1))
        withdrawn = knowledge.get(self.root, picked)
        self.assertEqual(withdrawn["excerpt"], "27.4")  # Its former excerpt, until its reviewer quotes one.
        with knowledge.connect(self.root) as db:
            detail = lambda i: json.loads(db.execute("SELECT detail FROM findings WHERE id=?", (i,)).fetchone()[0])
            self.assertEqual((detail(missing)["spotCheck"], detail(missing)["needsExcerpt"]), ("pending", True))
            self.assertEqual(detail(picked)["excerptWithdrawn"]["excerpt"], "HDPE-1 | flexural strength | 27.4")
            self.assertNotIn("excerptFrom", detail(picked))
            self.assertEqual(detail(reviewed)["recheck"], "pending")
        # Its reviewer returns the span that shows the value.
        knowledge.record_review(self.root, "b" * 32, engine="codex", started_at="", seconds=1, usage={}, verdicts={
            missing: {"verdict": "supported", "reason": "Table 1.", "excerpt": "tensile strength of 28 MPa for grade 8"}})
        self.assertEqual(knowledge.get(self.root, missing)["excerpt"], "tensile strength of 28 MPa for grade 8")

    def test_polymer_ids_from_the_question_and_family_members(self):
        question = "What tensile strength has been reported for polyetherimide?"
        pei, family, unrelated, blend = self.save("c", [
            finding(1, statement="PEI (Ultem 1010) had a tensile strength of 21 MPa.", material="PEI, Ultem 1010"),
            finding(2), finding(3), finding(4, statement="A PA/TPV blend had a tensile strength of 24 MPa.",
                                            material="PA/TPV blend")], question_text=question)
        # Deposit settles an ambiguous name by the question and writes it out; it never files a blend under the
        # question's polymer.
        saved = knowledge.get(self.root, pei)
        self.assertEqual((saved["subject"], saved["material"]), ("wop-000003", "Polyetherimide (PEI), Ultem 1010"))
        self.assertNotIn("subject", knowledge.get(self.root, blend))
        self.set(pei, subject="")  # As deposits before 2026-10-14 left it.
        self.set(family, subject="wop-000001")
        self.set(unrelated, subject="wop-000005")
        report = upkeep.polymers(self.root, apply=True)
        self.assertEqual(knowledge.get(self.root, pei)["subject"], "wop-000003")  # Its written-out name files it.
        self.assertEqual(knowledge.get(self.root, family)["subject"], "wop-000002")  # Family narrowed to its member.
        self.assertEqual(report["byRule"], {"filed by own text": 1, "narrowed by own text": 1})
        self.assertEqual(knowledge.get(self.root, unrelated)["subject"], "wop-000005")  # Left for a person to judge.
        self.assertEqual([c["id"] for c in report["toCheck"]], [unrelated])
        # A person's approved correction is applied as given; an unknown polymer id is refused.
        approved = self.root / "approved.json"
        atomic_json(approved, {unrelated: "wop-000002"})
        self.assertEqual(upkeep.corrections(self.root, approved, apply=True)["changes"], 1)
        self.assertEqual(knowledge.get(self.root, unrelated)["subject"], "wop-000002")
        atomic_json(approved, {unrelated: "wop-999999"})
        with self.assertRaises(ValueError):
            upkeep.corrections(self.root, approved)
        atomic_json(approved, {unrelated: {"polymer": "wop-000002", "material": "High-density polyethylene grade 3",
                                           "by": "independent reviewer"}})
        upkeep.corrections(self.root, approved, apply=True)
        corrected = knowledge.get(self.root, unrelated)
        self.assertEqual((corrected["material"], corrected["subject"]), ("High-density polyethylene grade 3", "wop-000002"))
        # An approved blank stays blank: a later automatic pass never files it again (six were, 2026-10-14).
        atomic_json(approved, {pei: {"polymer": "", "by": "independent reviewer"}})
        upkeep.corrections(self.root, approved, apply=True)
        self.assertNotIn("subject", knowledge.get(self.root, pei))
        self.assertEqual(upkeep.polymers(self.root, apply=True)["changes"], 0)
        self.assertNotIn("subject", knowledge.get(self.root, pei))

    def old_deposit(self, identifier, question, item, status="accepted"):
        """A finding as a deposit made before the duplicate rules improved saved it."""
        with knowledge.connect(self.root) as db:
            knowledge._insert_finding(db, identifier, question * 32, "research", knowledge.clean_finding(item),
                                      status=status, producer_engine="codex", created_at="2026-10-11T00:00:00")
        return identifier

    def test_duplicates_merge_into_the_reviewed_one_and_old_ids_still_resolve(self):
        first = self.old_deposit("finding:d-1", "d", finding(1, excerpt=""))
        again = self.old_deposit("finding:e-1", "e", finding(1, statement="The HDPE grade 1 tensile strength was 21 MPa.",
                                                             excerpt="21 MPa"), status="supported")
        grade = self.old_deposit("finding:f-1", "f", finding(4, statement="The UHMWPE was the GUR-2122 grade.",
                                                             material="UHMWPE GUR-2122", value="GUR-2122", unit="",
                                                             sourceUrl="https://example.org/g"))
        method = self.old_deposit("finding:g-1", "g", finding(5, statement="GUR-2122 wear was measured block-on-ring.",
                                                              material="UHMWPE GUR-2122 specimens", value="block-on-ring",
                                                              unit="", sourceUrl="https://example.org/g"))
        self.assertEqual(upkeep.duplicates(self.root)["pairs"], 1)  # A grade number in one statement is not a value.
        upkeep.duplicates(self.root, apply=True)
        self.assertIsNone(knowledge.for_question(self.root, "d" * 32) or None)
        resolved = knowledge.get(self.root, first)
        self.assertEqual((resolved["id"], resolved["mergedFrom"], resolved["status"]), (again, first, "supported"))
        self.assertEqual(upkeep.audit(self.root)["duplicates"]["pairs"], 0)
        self.assertEqual({knowledge.get(self.root, i)["id"] for i in (grade, method)}, {grade, method})

    def test_an_ambiguous_polymer_name_is_settled_at_deposit_or_sent_to_review(self):
        # Owner, 2026-10-14: an ambiguous label is updated when the source is ingested, never stored ambiguous.
        settled, unsettled = self.save("i", [
            finding(1, statement="PEI had a tensile strength of 21 MPa.", material="PEI film", sourceUrl="https://e.org/a"),
            finding(2, statement="PEI had a tensile strength of 22 MPa.", material="PEI gel", sourceUrl="https://e.org/b")])
        # Not settled by the question; the first source's note says which PEI it is.
        knowledge.deposit(self.root, "j" * 32, {"findings": [
            finding(1, statement="PEI had a tensile strength of 21 MPa.", material="PEI film", sourceUrl="https://e.org/c")],
            "sources": [{"title": "Polyethyleneimine films", "url": "https://e.org/c", "doi": "", "locator": "",
                         "excerpts": [], "supports": "tensile strength", "conditions": ""}]}, engine="codex",
            spot_check_rate=0)
        [noted] = knowledge.for_question(self.root, "j" * 32)
        self.assertEqual((noted["material"], noted["subject"], noted["status"]),
                         ("Polyethyleneimine (PEI) film", "wop-000004", "accepted"))
        unsure = knowledge.get(self.root, settled)
        self.assertEqual((unsure["status"], unsure["reviewFlag"], unsure["asks"]),
                         ("unreviewed", "Ambiguous polymer name: PEI could be Polyetherimide or Polyethyleneimine",
                          ["material"]))
        self.assertIn("reviewFlag", json.loads(reviewer.review_prompt([unsure])[len(reviewer.INSTRUCTION):]
                                               .split("\n\n", 1)[1])["findings"][0])
        knowledge.record_review(self.root, "i" * 32, engine="codex", started_at="", seconds=1, usage={}, verdicts={
            settled: {"verdict": "supported", "reason": "Table 2.", "excerpt": "", "material":
                      "Polyetherimide (PEI) film, Ultem 1000"},
            unsettled: {"verdict": "supported", "reason": "Table 2.", "excerpt": "", "material": ""}})
        relabelled, still = knowledge.get(self.root, settled), knowledge.get(self.root, unsettled)
        self.assertEqual((relabelled["material"], relabelled["subject"], relabelled["status"]),
                         ("Polyetherimide (PEI) film, Ultem 1000", "wop-000003", "supported"))
        self.assertEqual((still["status"], still["review"]["reason"]), ("uncertain", "Its polymer name (PEI) is still ambiguous."))

    def test_stored_ambiguous_names_are_settled_from_captured_text_or_reviewed(self):
        page = ("<html><body>" + "<p>Films of polyetherimide were cast from solution and dried.</p>" * 40 +
                "</body></html>").encode()
        sources.capture(self.root, {"url": "https://e.org/pei"}, fetch=lambda url, accept="*/*", timeout=20:
                        (200, "text/html", page, url))
        captured = self.old_deposit("finding:l-1", "l", finding(1, statement="PEI had a tensile strength of 21 MPa.",
                                                                material="PEI film", sourceUrl="https://e.org/pei"))
        added = self.old_deposit("finding:m-1", "m", finding(2, statement="PEI had a tensile strength of 22 MPa.",
                                                             material="PEI gel", sourceUrl="https://e.org/x"))
        reviewed = self.old_deposit("finding:n-1", "n", finding(3, statement="PEI had a tensile strength of 23 MPa.",
                                                                material="PEI", sourceUrl="https://e.org/y"),
                                    status="supported")
        report = upkeep.disambiguate(self.root, apply=True)
        self.assertEqual((report["ambiguous"], report["settled"], report["toReview"]), (3, 1, 2))
        first = knowledge.get(self.root, captured)
        self.assertEqual((first["material"], first["subject"]), ("Polyetherimide (PEI) film", "wop-000003"))
        self.assertEqual(knowledge.get(self.root, added)["status"], "unreviewed")  # No longer used as Added.
        self.assertEqual(knowledge.get(self.root, reviewed)["status"], "supported")  # Checked again, review kept.
        self.assertEqual(sorted(knowledge.review_queue(self.root)), ["m" * 32, "n" * 32])

    def test_a_common_word_abbreviation_is_written_out_only_when_the_context_names_its_polymer(self):
        build_release(self.root / "releases/mc", [{"@id": "wop-000007", "@type": "PolymerConcept",
                      "label": "Methyl cellulose", "abbreviations": ["MC"], "status": "seed", "layer": "science"}],
                      get_ontology(), {})
        release = json.loads((self.root / "releases/mc/manifest.json").read_text())["release_id"]
        (self.root / "releases/mc").rename(self.root / "releases" / release)
        atomic_json(self.root / "releases/current.json", {"release_id": release})
        knowledge._ALIASES.clear(), knowledge._FAMILIES.clear()
        text = {"material": "MC films", "statement": "MC films had a tensile strength of 21 MPa."}
        settled, _ = knowledge.settle_names(self.root, text, "Edible films of methyl cellulose")
        self.assertEqual(settled["material"], "Methyl cellulose (MC) films")
        unsettled, names = knowledge.settle_names(self.root, text, "Moisture content of paper")
        self.assertEqual((unsettled["material"], names), ("MC films", []))
        again, _ = knowledge.settle_names(self.root, settled, "Edible films of methyl cellulose")
        self.assertEqual(again["material"], "Methyl cellulose (MC) films")  # Written out once.

    def test_a_reviewed_finding_checked_again_keeps_its_review_unless_rejected(self):
        kept, doubted = self.save("k", [finding(1, excerpt="21"), finding(2, excerpt="22")])
        self.set(kept, status="supported")
        self.set(doubted, status="supported")
        upkeep.excerpts(self.root, apply=True)  # No captured text: both are checked again for an excerpt.
        self.assertEqual(knowledge.review_queue(self.root), ["k" * 32])
        knowledge.record_review(self.root, "k" * 32, engine="codex", started_at="", seconds=1, usage={}, verdicts={
            kept: {"verdict": "supported", "reason": "Table 1.", "excerpt": "tensile strength of 21 MPa", "material": ""},
            doubted: {"verdict": "unsupported", "reason": "Table 1 gives 12 MPa.", "excerpt": "", "material": ""}})
        first, second = knowledge.get(self.root, kept), knowledge.get(self.root, doubted)
        self.assertEqual((first["status"], first["excerpt"]), ("supported", "tensile strength of 21 MPa"))
        self.assertEqual((second["status"], second["review"]["reason"]),
                         ("uncertain", "A second review found it unsupported: Table 1 gives 12 MPa."))
        self.assertEqual(knowledge.review_queue(self.root), [])

    def test_reviews_return_an_excerpt_only_when_one_is_missing(self):
        self.assertIn("excerpt", reviewer.REVIEW_SCHEMA["properties"]["verdicts"]["items"]["required"])
        [kept] = self.save("h", [finding(1, derivation="figure")])
        knowledge.record_review(self.root, "h" * 32, engine="codex", started_at="", seconds=1, usage={}, verdicts={
            kept: {"verdict": "supported", "reason": "Fig. 2.", "excerpt": "a strength of 21 MPa"}})
        self.assertEqual(knowledge.get(self.root, kept)["excerpt"], "tensile strength of 21 MPa")


if __name__ == "__main__":
    unittest.main()
