"""Knowledge search ranks by relevance: the polymer a query names, then how many of its words a finding matches."""
import json
from pathlib import Path
import tempfile
import unittest

from oopc import knowledge
from oopc.release import build_release
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology

POLYMERS = [("wop-000001", "Polylactide", ["PLA"]), ("wop-000002", "Polycaprolactone", ["PCL"]),
            ("wop-000003", "Poly(3-hydroxybutyrate-co-3-hydroxyvalerate)", ["PHBV"]),
            ("wop-000004", "Poly(3-hydroxybutyrate)", ["PHB"]), ("wop-000005", "Polyisoprene", ["IR"]),
            ("wop-000006", "Poly(ethylene naphthalate)", ["PEN"]), ("wop-000007", "Phenol–formaldehyde resin family", ["PF"]),
            ("wop-000008", "Silicone resin", []), ("wop-000009", "Polyethylene family", ["PE"]),
            ("wop-000010", "High-density polyethylene", ["HDPE"]), ("wop-000011", "Low-density polyethylene", ["LDPE"]),
            ("wop-000012", "Polyetherimide", ["PEI"]), ("wop-000013", "Polyethyleneimine", ["PEI"]),
            ("wop-000014", "FKM fluoroelastomer family", ["FKM"]),
            ("wop-000015", "Chlorinated polyethylene elastomer", ["CM", "CPE"])]
# The graph's family links: HDPE and LDPE are members of the polyethylene family.
FAMILIES = [("wop-000010", "wop-000009"), ("wop-000011", "wop-000009")]


def finding(statement, material, status, *, subject="", doi="10.1/x"):
    return {"statement": statement, "material": material, "property": "", "value": "", "unit": "", "conditions": "",
            "subject": subject, "sourceTitle": "", "sourceUrl": "https://example.org/" + doi, "sourceDoi": doi,
            "locator": "Table 1", "excerpt": statement[:40], "needsReview": status == "unreviewed", "reviewFlag": ""}


class KnowledgeSearch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-search-test-")
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

    def save(self, question, items, *, review=None):
        knowledge.deposit(self.root, question * 32, {"findings": items, "sources": []}, engine="codex", spot_check_rate=0)
        rows = knowledge.for_question(self.root, question * 32)
        if review:
            with knowledge.connect(self.root) as db:
                for row in rows:
                    db.execute("UPDATE findings SET status='supported', review_reason='Table 1.' WHERE id=?", (row["id"],))
        return [row["id"] for row in rows]

    def test_reviewed_findings_on_other_polymers_do_not_crowd_out_the_one_asked_about(self):
        # Overnight Q37: reviewed PCL and PLA DSC findings were listed before the PHBV ones it needed.
        self.save("a", [finding("PCL45 has a first-heating DSC crystallinity of 58%.", "PCL45", "accepted", doi="10.1/a%d" % i)
                        for i in range(8)] +
                  [finding("Neat PLA showed DSC crystallinity of 23.9%.", "PLA 3100HP", "accepted", doi="10.1/p")], review=True)
        [phbv] = self.save("b", [finding("PHBV28 pellets melted at 94 °C by DSC.", "PHBV28; 28 mol% 3HV", "accepted",
                                         doi="10.1/h")])
        found = knowledge.search(self.root, "PHBV DSC crystallinity", compact=True)
        self.assertEqual(found["reviewed"], [])
        self.assertEqual([f["id"] for f in found["added"]], [phbv])

    def test_a_grade_number_counts_but_a_longer_name_does_not(self):
        [phb] = self.save("a", [finding("PHB film modulus was 1456 MPa.", "PHB Y3000P", "accepted", doi="10.1/b")])
        [phbv] = self.save("b", [finding("PHBV3 pellets melted at 174 °C.", "PHBV3", "accepted", doi="10.1/c")])
        self.assertEqual([f["id"] for f in knowledge.search(self.root, "PHB modulus")["added"]], [phb])
        self.assertEqual([f["id"] for f in knowledge.search(self.root, "PHBV melting")["added"]], [phbv])

    def test_the_polymer_is_found_by_its_other_names_and_graph_id(self):
        [long_name] = self.save("a", [finding("Polycaprolactone films lost 11% Mn by hydrolysis in buffer.", "film", "accepted", doi="10.1/d")])
        [by_id] = self.save("b", [finding("Capa 6800 melted at 57 °C.", "Capa 6800", "accepted",
                                          subject="wop-000002", doi="10.1/e")])
        found = {f["id"] for f in knowledge.search(self.root, "PCL melting hydrolysis")["added"]}
        self.assertEqual(found, {long_name, by_id})

    def test_more_matched_words_rank_first_and_the_limit_is_the_total(self):
        ids = self.save("a", [finding("PLA lost mass in buffer.", "PLA", "accepted", doi="10.1/f"),
                              finding("PLA crystallinity rose after annealing at 100 °C.", "PLA", "accepted", doi="10.1/g")])
        self.save("b", [finding("PLA annealing raised crystallinity.", "PLA", "accepted", doi="10.1/h%d" % i)
                        for i in range(3)], review=True)
        ranked = knowledge.search(self.root, "PLA crystallinity annealing", limit=25)
        self.assertEqual([f["id"] for f in ranked["added"]], [ids[1], ids[0]])  # Matching only the polymer ranks last.
        self.save("c", [finding("PLA annealing raised crystallinity again.", "PLA", "accepted", doi="10.1/k%d" % i)
                        for i in range(8)])
        ranked = knowledge.search(self.root, "PLA crystallinity annealing", limit=25)
        self.assertNotIn(ids[0], [f["id"] for f in ranked["added"]])  # ...and only fills a short result.
        # Researchers asked for 8 or fewer in most searches and lost what they needed: a limit is at least 10.
        found = knowledge.search(self.root, "PLA crystallinity annealing", limit=2)
        self.assertEqual(sum(len(found[k]) for k in ("reviewed", "added", "unreviewed")), 10)

    def test_a_search_also_returns_what_the_same_sources_gave(self):
        # 200-task run: repeats re-read a paper for method details already saved from it.
        tg, method = self.save("a", [
            dict(finding("PLA 4032D had a Tg of 60 °C by DSC.", "PLA 4032D", "accepted", doi="10.1/s"),
                 sourceTitle="Thermal analysis of PLA films"),
            finding("DSC scans used a heating rate of 10 K/min under nitrogen.", "DSC specimens", "accepted", doi="10.1/s")])
        [elsewhere] = self.save("b", [finding("Specimens were dried at 40 °C for 24 h.", "PCL bars", "accepted", doi="10.1/t")])
        knowledge.deposit(self.root, "c" * 32, {"findings": [], "sources": [
            {"title": "Thermal analysis of PLA films", "url": "https://doi.org/10.1/s", "doi": "10.1/s", "locator": "",
             "excerpts": ["PLA 4032D Tg 60 °C"], "supports": "PLA Tg by DSC", "conditions": "",
             "readUrl": "https://repository.example.org/pla.pdf"}]}, engine="codex")
        found = knowledge.search(self.root, "PLA glass transition Tg", compact=True)
        self.assertEqual([f["id"] for f in found["added"]], [tg, method])
        self.assertNotIn(elsewhere, [f["id"] for f in found["added"]])
        self.assertEqual(found["added"][0]["source"]["title"], "Thermal analysis of PLA films")
        self.assertEqual(found["notes"][0]["readUrl"], "https://repository.example.org/pla.pdf")

    def test_a_grade_number_after_a_name_still_names_the_polymer(self):
        # 14% of the 200-task run's findings had no polymer id, many for names like EVOH44 or PHBV28.
        subject = lambda material: knowledge.infer_subject(self.root, {"material": material, "statement": ""})
        self.assertEqual(subject("PHBV28; 28 mol% 3HV"), "wop-000003")
        self.assertEqual(subject("PLA1 film"), "wop-000001")
        self.assertEqual(subject("PCL films"), "wop-000002")
        self.assertEqual(subject("IR spectra"), "")  # A short abbreviation that is also a common word.
        self.assertEqual(subject("pla1 film"), "")  # ...and a short one is a name only in capitals.
        # Wave 1 of the campaign: 30% of findings had no polymer id, many for names like these.
        self.assertEqual(subject("PEN film, Teonex"), "wop-000006")  # Three letters in capitals, in a material.
        self.assertEqual(knowledge.infer_subject(self.root, {"material": "", "statement": "A pen was used."}), "")
        self.assertEqual(subject("Dynea phenol–formaldehyde novolac, cured"), "wop-000007")  # "resin family" left off.
        self.assertEqual(subject("silicone sealant"), "")  # A lone "silicone" is not "Silicone resin".

    def test_the_same_number_for_a_more_specific_material_is_the_same_fact(self):
        fact = lambda statement, material, value, unit="°C", doi="10.1/m": {
            "statement": statement, "material": material, "property": "", "value": value, "unit": unit,
            "sourceDoi": doi, "sourceUrl": ""}
        first = fact("The Mp=3,040 g/mol PMMA sample had onset Tg 89.034 °C.", "Agilent PMMA", "89.034")
        again = fact("Agilent PMMA with Mp = 3,040 g/mol had an onset glass-transition temperature of 89.034 °C.",
                     "Agilent PMMA, molecular-weight series", "89.034")
        self.assertTrue(knowledge.same_fact(first, again))
        self.assertTrue(knowledge.same_fact(first, dict(again, sourceDoi="", sourceUrl="https://doi.org/10.1/M")))
        other_grade = (fact("Selvol 540 film dissolved completely.", "PVA Selvol 540", "100", "%"),
                       fact("Selvol 203 film dissolved completely.", "PVA Selvol 203", "100", "%"))
        self.assertFalse(knowledge.same_fact(*other_grade))
        self.assertFalse(knowledge.same_fact(first, dict(again, unit="K")))
        # A paper's table gives −134.3 J/g and its text +134.3 J/g: two readings to keep apart (independent review,
        # 2026-10-14), though their numbers differ only in sign.
        table = fact("Neat POM had a tabulated second-heating melting enthalpy of −134.3 J/g.", "Neat POM", "−134.3", "J/g")
        prose = fact("Neat POM had a second-heating melting enthalpy of 134.3 J/g in the text.", "Neat POM", "134.3", "J/g")
        self.assertFalse(knowledge.same_fact(table, prose))
        self.assertTrue(knowledge.same_fact(table, dict(table, value="-134.3")))  # A hyphen for the minus sign.
        # A unit's exponent is not a number of the fact, and 1.0 mm is not said to be the 1 mm of another sentence.
        modulus = fact("Ard 100 film had a tensile modulus of 100 kg/mm² at 100 °C.", "Ard 100 film", "100", "kg/mm²")
        yielded = fact("Ard 100 film had a tensile yield strength of 2.0 kg/mm² at 100 °C.", "Ard 100 film", "2.0", "kg/mm²")
        self.assertFalse(knowledge.same_fact(modulus, yielded))

    def test_short_abbreviations_that_are_common_words_do_not_restrict_the_search(self):
        [pla] = self.save("a", [finding("PLA IR spectra showed a carbonyl band at 1750 cm-1.", "PLA", "accepted")])
        self.assertEqual([f["id"] for f in knowledge.search(self.root, "carbonyl band IR")["added"]], [pla])
        self.assertEqual([f["id"] for f in knowledge.search(self.root, "pla carbonyl")["added"]], [pla])

    def test_without_a_named_polymer_findings_must_match_a_query_word(self):
        [hit] = self.save("a", [finding("PLA annealed 60 min reached 45% crystallinity.", "PLA", "accepted", doi="10.1/i"),
                                finding("PLA melted at 176 °C.", "PLA", "accepted", doi="10.1/j")])[:1]
        self.assertEqual([f["id"] for f in knowledge.search(self.root, "annealed 60 min")["added"]], [hit])

    def test_a_search_result_stays_short(self):
        long_reason = "The source reports it in Table 1 with full conditions." * 10
        self.save("a", [finding("PLA crystallinity was 45%. " + "x" * 600, "PLA " + "y" * 300, "accepted")], review=True)
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET review_reason=?", (long_reason,))
        [item] = knowledge.search(self.root, "PLA crystallinity", compact=True)["reviewed"]
        self.assertLessEqual(len(item["statement"]), 300)
        self.assertNotIn("reason", item["review"])  # Supported needs no reason in a search.
        self.assertNotIn("producerEngine", item)
        self.assertEqual(knowledge.get(self.root, item["id"])["review"]["reason"], long_reason)


    def test_a_polymer_search_also_finds_its_family_and_members_but_not_its_siblings(self):
        # Campaign: 2.4% of findings were filed under the family or a member of the polymer asked about.
        [family] = self.save("a", [finding("Polyethylene films absorb little water.", "polyethylene", "accepted",
                                           subject="wop-000009", doi="10.1/pe")])
        [hdpe] = self.save("b", [finding("Marlex HDPE film absorbed 0.01% water.", "Marlex film", "accepted",
                                         subject="wop-000010", doi="10.1/hd")])
        [ldpe] = self.save("c", [finding("LDPE film absorbed 0.02% water.", "film", "accepted",
                                         subject="wop-000011", doi="10.1/ld")])
        ids = lambda q: {f["id"] for f in knowledge.search(self.root, q)["added"]}
        self.assertEqual(ids("HDPE water absorption"), {hdpe, family})
        self.assertEqual(ids("polyethylene water absorption"), {family, hdpe, ldpe})

    def test_a_finding_is_filed_under_the_polymer_its_question_is_about(self):
        # Campaign: 8.7% of findings named their material only by a trade or grade name ("Viton A-200").
        question = "How does the cure system change compression set of FKM fluoroelastomer?"
        knowledge.deposit(self.root, "q" * 32, {"findings": [
            finding("Viton A-200 had 18% compression set after 70 h at 200 °C.", "Viton A-200", "accepted", doi="10.1/v"),
            finding("PLA 4032D had a Tg of 60 °C.", "PLA 4032D", "accepted", doi="10.1/w")], "sources": []},
            engine="codex", spot_check_rate=0, question=question)
        self.assertEqual([f["subject"] for f in knowledge.for_question(self.root, "q" * 32)], ["wop-000014", "wop-000001"])
        self.assertEqual(knowledge.question_subject(self.root, "Compare PLA and PCL films."), "")  # Two polymers: no context.

    def test_a_name_two_unrelated_polymers_share_needs_the_asker_to_choose(self):
        [ambiguous] = knowledge.ambiguous_polymers(self.root, "What is the Tg of PEI by DMA?")
        self.assertEqual((ambiguous["name"], [o["label"] for o in ambiguous["options"]]),
                         ("PEI", ["Polyetherimide", "Polyethyleneimine"]))
        self.assertEqual(knowledge.ambiguous_polymers(self.root, "What is the Tg of PEI (polyetherimide) by DMA?"), [])
        self.assertEqual(knowledge.ambiguous_polymers(self.root, "What is the Tg of HDPE?"), [])
        self.assertEqual(knowledge.question_subject(self.root, "What is the Tg of PEI by DMA?"), "")

    def test_an_abbreviation_that_is_also_a_unit_does_not_name_the_polymer_in_a_finding(self):
        # Before 2026-10-12 a search for chlorinated polyethylene (CM) returned findings measured in cm.
        self.save("a", [finding("PLA bars 10 cm long had a modulus of 3.5 GPa.", "PLA bars", "accepted", doi="10.1/cm")])
        [cpe] = self.save("b", [finding("Tyrin CPE had a Shore A hardness of 65.", "Tyrin CPE", "accepted", doi="10.1/cpe")])
        found = knowledge.search(self.root, "chlorinated polyethylene elastomer (CM) Shore A hardness")
        self.assertEqual([f["id"] for f in found["added"]], [cpe])

    def test_your_own_question_asks_which_polymer_an_ambiguous_name_means(self):
        from oopc.ask import NeedsClarification, Questions
        service = Questions(self.root, reviews=False)
        ask = lambda question, origin="ask": service.submit({"question": question, "depth": "quick", "runtime": "codex",
                                                             "origin": origin, "authorizeSubscription": True})
        with self.assertRaises(NeedsClarification) as raised:
            ask("What is the Tg of PEI by DMA?")
        self.assertEqual([o["label"] for o in raised.exception.choices[0]["options"]], ["Polyetherimide", "Polyethyleneimine"])
        self.assertEqual(service.list()["tasks"], [])  # Nothing was queued.
        # The research queue has no one to ask: the research agent states its reading instead.
        self.assertEqual(ask("What is the Tg of PEI by DMA?", origin="research")["status"], "queued")
        service.wait(10)


if __name__ == "__main__":
    unittest.main()
