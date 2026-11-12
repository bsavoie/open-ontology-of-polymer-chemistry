"""The consistency check: which saved findings a new finding is compared with, when a review runs for it, and what
the conflicts a reviewer or a person finds do to the findings."""
import json
import math
import unittest

import test_knowledge_search as base
from oopc import consistency, knowledge, loop, reflect, reviewer

PLA, PCL, PE, HDPE, LDPE = "wop-000001", "wop-000002", "wop-000009", "wop-000010", "wop-000011"


def fact(statement, material, prop, value, unit, *, subject=PLA, doi="10.1/x", conditions="", status="accepted"):
    return {"statement": statement, "material": material, "property": prop, "value": value, "unit": unit,
            "conditions": conditions, "subject": subject, "sourceTitle": "", "sourceUrl": "https://example.org/" + doi,
            "sourceDoi": doi, "locator": "Table 1", "excerpt": statement[:60], "needsReview": status == "unreviewed",
            "reviewFlag": ""}


class Reviewer:
    """A scripted reviewer: `conflicts(compare)` gives the conflicts for the prompt's consistency section."""

    def __init__(self, conflicts=lambda section: [], verdicts=lambda findings: []):
        self.conflicts, self.verdicts, self.calls = conflicts, verdicts, []

    def __call__(self, engine, prompt, schema, **options):
        given = json.loads(prompt[prompt.index("\n{") + 1:])
        self.calls.append({"schema": schema, "prompt": prompt, "given": given})
        answer = {"verdicts": self.verdicts(given["findings"]), "notes": ""}
        if schema is reviewer.CONSISTENCY_SCHEMA:
            answer["conflicts"] = self.conflicts(given["consistency"])
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10}, "agentSeconds": 1.0}


class Consistency(unittest.TestCase):
    def setUp(self):
        base.KnowledgeSearch.setUp(self)
        loop.update_settings(self.root, {"spotCheckRate": 0})

    def save(self, question, items, reviewed=()):
        qid = question * 32
        knowledge.deposit(self.root, qid, {"findings": items, "sources": []}, engine="codex", spot_check_rate=0)
        ids = [f["id"] for f in knowledge.for_question(self.root, qid)]
        with knowledge.connect(self.root) as db:
            for index in reviewed:
                db.execute("UPDATE findings SET status='supported', review_reason='Table 1.' WHERE id=?", (ids[index],))
        return ids

    def answer(self, question, items, depth=8):
        """A new answer's deposit, screened as `ask` screens it."""
        ids = self.save(question, items)
        return question * 32, ids, consistency.screen(self.root, question * 32, depth)

    def tranche(self, question, depth=8):
        with knowledge.connect(self.root) as db:
            return consistency.build(self.root, db, question * 32, depth)

    def status(self, identifier):
        return knowledge.get(self.root, identifier)["status"]

    def test_the_tranche_is_the_saved_findings_on_the_same_polymer_and_property_most_telling_first(self):
        tg60, tg58, melt, cold = self.save("s", [
            fact("PLA 4032D had a glass transition temperature of 60 °C.", "PLA 4032D", "glass transition temperature",
                 "60", "°C", doi="10.1/a"),
            fact("PLA film showed a glass transition at 58 °C.", "PLA film", "glass transition temperature", "58", "°C",
                 doi="10.1/b"),
            fact("PLA melted at 170 °C.", "PLA", "melting temperature", "170", "°C", doi="10.1/c"),
            fact("PLA cold crystallized at 105 °C.", "PLA", "cold crystallization temperature", "105", "°C",
                 doi="10.1/d")], reviewed=[0])
        [pcl] = self.save("p", [fact("PCL had a glass transition temperature of -60 °C.", "PCL", "glass transition "
                                     "temperature", "-60", "°C", subject=PCL, doi="10.1/e")])
        [tensile] = self.save("t", [fact("PLA tensile strength was 50 MPa.", "PLA", "tensile strength", "50", "MPa",
                                         doi="10.1/f")])
        _, [new], state = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "Glass transition temperature (Tg)",
                                                 "160", "°C", doi="10.1/g")])
        self.assertEqual(state, "tension")
        found = self.tranche("n")
        # The reviewed reading first; another polymer, another property and an unrelated one never.
        self.assertEqual(found["new"], {new: [tg60, tg58]})
        self.assertEqual(sorted(found["tension"]), sorted([(new, tg60), (new, tg58)]))
        self.assertNotIn(melt, found["saved"])
        self.assertNotIn(pcl, found["saved"])
        self.assertNotIn(tensile, found["saved"])
        self.assertNotIn(cold, found["saved"])
        # A member is compared with its family's findings, never with a sibling's.
        [family] = self.save("e", [fact("Polyethylene had a density of 0.95 g/cm3.", "polyethylene", "density", "0.95",
                                        "g/cm3", subject=PE, doi="10.1/h")])
        [sibling] = self.save("l", [fact("LDPE had a density of 0.92 g/cm3.", "LDPE", "density", "0.92", "g/cm3",
                                         subject=LDPE, doi="10.1/i")])
        self.answer("h", [fact("HDPE had a density of 0.96 g/cm3.", "HDPE", "density", "0.96", "g/cm3", subject=HDPE,
                               doi="10.1/j")])
        self.assertEqual(list(self.tranche("h")["saved"]), [family])
        self.assertNotIn(sibling, self.tranche("h")["saved"])

    def test_values_in_tension(self):
        def tension(a, b, unit_a="MPa", unit_b="MPa", same_source=False, conditions=("", "")):
            rows = [{"id": str(i), "question_id": "q", "status": "accepted", "statement": "x", "material": "PLA",
                     "property": "tensile modulus", "value": v, "unit": u, "conditions": c, "subject": PLA,
                     "source_title": "", "source_url": "", "source_doi": "10.1/same" if same_source else "10.1/%d" % i,
                     "locator": "", "detail": None}
                    for i, (v, u, c) in enumerate(((a, unit_a, conditions[0]), (b, unit_b, conditions[1])))]
            cache = {}
            return consistency.score(rows[0], rows[1], consistency._features(rows[0], cache),
                                     consistency._features(rows[1], cache), {PLA})[1]
        self.assertFalse(tension("3.5", "3500", "GPa", "MPa"))  # One value in two units.
        self.assertTrue(tension("3.5", "350", "GPa", "MPa"))  # An order of magnitude apart.
        self.assertFalse(tension("55–60", "58"))  # Overlapping ranges.
        self.assertFalse(tension("61", "80", "°C", "°C"))  # Within 20 degrees.
        self.assertTrue(tension("61", "160", "°C", "°C"))
        self.assertTrue(tension("334.15", "160", "K", "°C"))  # The same comparison in kelvin, either way round.
        self.assertTrue(tension("160", "334.15", "°C", "K"))
        self.assertFalse(tension("341.15", "80", "K", "°C"))
        self.assertTrue(tension("110-120", "60"))  # A plain range, not an exponent.
        self.assertTrue(tension("50 ± 2", "30"))  # An uncertainty is read as its range 48–52 (not 2–50).
        self.assertFalse(tension("50 ± 2", "45"))
        self.assertTrue(tension("≥80", "20"))  # Below the bound by far more than the gap.
        self.assertFalse(tension("≥80", "70"))
        self.assertFalse(tension("45", "41"))  # Two sources a tenth apart are not in tension...
        self.assertTrue(tension("45", "41", same_source=True))  # ...but one source read twice is.
        self.assertFalse(tension("45", "41", same_source=True, conditions=("23 °C", "80 °C")))  # Other conditions.
        self.assertFalse(tension("45.3 ± 0.2", "45.3", same_source=True))  # One cell read with and without its ±.
        self.assertTrue(tension("45", "4.1e2"))  # Scientific notation is read...
        self.assertFalse(tension("410", "4.1e2"))
        self.assertFalse(tension("45", "352; 41"))  # ...a cell with several values is not.
        self.assertFalse(tension("45", "41", "MPa", "%"))  # Other dimensions.

    def test_the_owners_table_of_what_is_in_tension(self):
        """Qualitative inconsistency, not measurement uncertainty (owner, 2026-11-05): two sources, one material, one
        property."""
        def tension(first, second, prop="tensile modulus", unit="GPa"):
            rows = [{"id": str(i), "question_id": "q", "status": "accepted", "statement": "x",
                     "material": "Ingeo 4032D PLA", "property": prop, "value": value, "unit": unit,
                     "conditions": conditions, "subject": PLA, "source_title": "", "source_url": "",
                     "source_doi": "10.1/%d" % i, "locator": "", "detail": None}
                    for i, (value, conditions) in enumerate((first, second))]
            cache = {}
            return consistency.in_tension(consistency._features(rows[0], cache), consistency._features(rows[1], cache),
                                          True)
        test = "ISO 527; 23 °C; 1 mm/min"
        self.assertTrue(tension(("3.2", test), ("1.1", test)))  # The same test, very different values.
        self.assertTrue(tension(("3.2 ± 0.1", test), ("1.1 ± 0.1", test)))
        self.assertTrue(tension(("3.2", "ISO 527; 23 °C"), ("1.1", "ISO 527; 40 °C")))  # Near temperatures.
        self.assertFalse(tension(("3.2", "ISO 527; 23 °C"), ("1.1", "ISO 527; 180 °C")))  # Temperature may explain it.
        solubility = ("qualitative solubility", "")
        self.assertTrue(tension(("soluble", "chloroform, 25 °C"), ("insoluble", "chloroform, 40 °C"), *solubility))
        self.assertTrue(tension(("ductile", "tensile test at 23 °C"), ("brittle", "tensile test at 30 °C"),
                                "fracture behaviour", ""))
        # Controls: one outcome worded two ways, values within their uncertainty, and a rate is no temperature.
        self.assertFalse(tension(("insoluble", "chloroform, 25 °C"), ("not soluble", "chloroform, 25 °C"),
                                 *solubility))
        self.assertFalse(tension(("55.3 ± 0.2", test), ("55.9 ± 0.3", test), unit="MPa"))
        self.assertTrue(tension(("3.2", "DSC at 10 °C/min"), ("1.1", "DSC at 40 °C/min")))
        self.assertFalse(tension(("soluble", "chloroform, 25 °C"), ("insoluble", "chloroform, 80 °C"), *solubility))
        self.assertFalse(tension(("ductile", "23 °C"), ("partially ductile", "23 °C"), "fracture behaviour", ""))
        # A specimen's dimension or a test's setting differs by design (eight film thicknesses were the only new pairs
        # the wider value reading flagged in the store); a property qualified by a setting is still a property.
        self.assertFalse(tension(("71 ± 3", ""), ("200", ""), "film thickness", "µm"))
        self.assertFalse(tension(("10", ""), ("40", ""), "DSC heating rate", "K/min"))
        self.assertTrue(tension(("0.4", ""), ("2.5", ""), "water absorption at 50% relative humidity", "%"))

    def test_values_read(self):
        read = consistency._range
        for value, expected in (("45", (45, 45)), ("-5", (-5, -5)), (".5", (.5, .5)), ("55–60", (55, 60)),
                                ("110-120", (110, 120)), ("≈1.2", (1.2, 1.2)), ("around 12", (12, 12)),
                                ("1,200", (1200, 1200)), ("1,5", (1.5, 1.5)), ("2 to 4", (2, 4)),
                                ("−60 to 60", (-60, 60)),
                                ("55.3 ± 0.2", (55.1, 55.5)), ("55.3 +/- 0.2", (55.1, 55.5)), ("27±5", (22, 32)),
                                ("40%", (40, 40)), ("40 %", (40, 40)),
                                ("6.88 × 10⁻¹⁰", (6.88e-10, 6.88e-10)), ("6.88×10^-10", (6.88e-10, 6.88e-10)),
                                ("6.88 x 10^-10", (6.88e-10, 6.88e-10)), ("1.9·10^5", (1.9e5, 1.9e5)),
                                ("4.1e2", (410, 410)), ("4.1E-3", (4.1e-3, 4.1e-3)), ("10⁵", (1e5, 1e5)),
                                ("(4.41 ± 0.01) × 10⁻¹⁶", (4.40e-16, 4.42e-16)), ("2–4 × 10³", (2000, 4000)),
                                ("<5", (-math.inf, 5)), ("≤4.8", (-math.inf, 4.8)), ("< 0.01", (-math.inf, .01)),
                                ("below 1", (-math.inf, 1)), ("up to 5", (-math.inf, 5)), (">80", (80, math.inf)),
                                ("≥2", (2, math.inf)), ("above 3", (3, math.inf)), ("at least 2", (2, math.inf))):
            with self.subTest(value=value):
                self.assertTrue(all(math.isclose(got, want, rel_tol=1e-9) for got, want in zip(read(value), expected)),
                                read(value))
        self.assertEqual(read("55 MPa", "MPa"), (55, 55))  # The finding's own unit after the number.
        self.assertIsNone(read("55 MPa"))
        for unread in ("352; 2.3", "93.84; SD 2.19", "80 × 10 × 4", "15 × 15", "1.2 × 105", "ASTM D638", "1:100",
                       "could not be melt-spun", "at least five", "", None):
            with self.subTest(unread=unread):
                self.assertIsNone(read(unread))

    def test_test_temperatures_read(self):
        read = consistency._temperature
        for conditions, expected in (("23 °C", 23), ("23°C", 23), ("tested at 25 ± 2 °C", 25), ("296 K", 22.85),
                                     ("−40 °C", -40), ("-18 °C; ISO 179", -18), ("room temperature", 23), ("RT", 23),
                                     ("ambient temperature; 50% RH", 23), ("23 °C (296 K)", 22.925),
                                     ("heated at 20 °C/min; tested at 23 °C", 23), ("50 °C/93% RH", 50)):
            with self.subTest(conditions=conditions):
                self.assertAlmostEqual(read(conditions), expected, places=3)
        for conditions in ("10 °C/min", "5 K/min", "10 °C min⁻¹", "1–2 K/day", "annealed at 100 °C; tested at 23 °C",
                           "195–430 °C", "at 25 and 40 °C", "RT→400 °C", "ISO 527-1/-2; printed 2026-07-14",
                           "2.16 kg; Cu Kα; 40 kV", "", None):
            with self.subTest(conditions=conditions):
                self.assertIsNone(read(conditions))

    def test_outcomes_in_words_that_are_opposite(self):
        def opposite(first, second):
            one, other = consistency._outcome(first), consistency._outcome(second)
            self.assertEqual(consistency.opposite(one, other), consistency.opposite(other, one))
            return consistency.opposite(one, other)
        for first, second in (("soluble", "insoluble"), ("miscible", "immiscible"), ("stable", "unstable"),
                              ("flammable", "nonflammable"), ("flammable", "non-flammable"),
                              ("could not be melt-spun", "melt-spun"), ("didn't melt", "melted"),
                              ("soluble in chloroform", "insoluble in chloroform"), ("completely soluble", "insoluble"),
                              ("ductile", "brittle"), ("amorphous", "crystalline"), ("amorphous", "semi-crystalline"),
                              ("transparent", "opaque"), ("passed", "failed"), ("pass", "fails"), ("present", "absent"),
                              ("hydrophobic", "hydrophilic"), ("increased", "decreased"), ("increases", "decrease"),
                              ("yes", "no"), ("no break", "complete break")):
            with self.subTest(first=first, second=second):
                self.assertTrue(opposite(first, second))
        for first, second in (("insoluble", "not soluble"), ("not brittle", "ductile"), ("soluble", "soluble"),
                              ("partially soluble", "insoluble"), ("no", "none"),
                              ("injection molding", "injection molding; no annealing"),  # Its negation is another word.
                              ("room temperature, no particular temperature control", "room temperature"),
                              ("injection molding", "injection moulding"), ("ASTM D638", "ASTM D882"),
                              ("soluble", "readily soluble in warm water and in hot toluene")):
            with self.subTest(first=first, second=second):
                self.assertFalse(opposite(first, second))
        self.assertIsNone(consistency._outcome("352; 2.3"))

    def test_outcomes_in_words_in_tension_need_the_same_material_and_from_one_source_the_same_conditions(self):
        def tension(first, second, same_source=False, prop="solubility"):
            rows = [{"id": str(i), "question_id": "q", "status": "accepted", "statement": "x", "material": material,
                     "property": prop, "value": value, "unit": "", "conditions": conditions, "subject": PLA,
                     "source_title": "", "source_url": "", "source_doi": "10.1/same" if same_source else "10.1/%d" % i,
                     "locator": "", "detail": None}
                    for i, (value, material, conditions) in enumerate((first, second))]
            cache = {}
            return consistency.score(rows[0], rows[1], consistency._features(rows[0], cache),
                                     consistency._features(rows[1], cache), {PLA})[1]
        self.assertTrue(tension(("soluble", "CTA, DS 2.86", "chloroform"), ("insoluble", "CTA, DS 2.86", "chloroform")))
        self.assertFalse(tension(("soluble", "CTA, DS 2.86", "chloroform"), ("insoluble", "PLA 4032D", "chloroform")))
        # One source testing one material in two solvents: different conditions, no tension; the same, tension.
        self.assertFalse(tension(("soluble", "CTA, DS 2.86", "chloroform"), ("insoluble", "CTA, DS 2.86", "acetone"),
                                 same_source=True))
        self.assertTrue(tension(("soluble", "CTA, DS 2.86", "acetone"), ("insoluble", "CTA, DS 2.86", "acetone"),
                                same_source=True))
        self.assertFalse(tension(("soluble", "CTA", ""), ("3.2", "CTA", "")))  # A word and a number: not compared.

    def test_an_opposite_outcome_in_words_sends_an_answer_to_review(self):
        [saved] = self.save("s", [fact("PLA 4032D could not be melt-spun at 23 °C.", "PLA 4032D", "melt-spinning "
                                       "feasibility", "could not be melt-spun", "", conditions="23 °C", doi="10.1/a")])
        _, [new], state = self.answer("n", [fact("PLA 4032D was melt-spun into fibres.", "PLA 4032D",
                                                 "melt-spinning feasibility", "melt-spun", "", doi="10.1/b")])
        self.assertEqual((state, self.tranche("n")["tension"]), ("tension", [(new, saved)]))
        self.assertIn("opposite outcomes (soluble and insoluble, brittle and ductile)", consistency.INSTRUCTION)

    def test_the_tranche_takes_at_most_three_findings_from_a_source_and_caps_the_saved_findings_given(self):
        ids = self.save("s", [fact("PLA tensile strength was %d MPa in run %d." % (50 + i, i), "PLA",
                                   "tensile strength", str(50 + i), "MPa", doi="10.1/one") for i in range(6)])
        others = self.save("o", [fact("PLA tensile strength was %d MPa." % (60 + i), "PLA", "tensile strength",
                                      str(60 + i), "MPa", doi="10.1/o%d" % i) for i in range(20)])
        self.answer("n", [fact("PLA tensile strength was 55 MPa.", "PLA", "tensile strength", "55", "MPa",
                               doi="10.1/n%d" % i) for i in range(12)])
        found = self.tranche("n", depth=8)
        for compared in found["new"].values():
            self.assertEqual(len(compared), 8)
            self.assertLessEqual(len(set(compared) & set(ids)), 3)
        self.assertLessEqual(len(found["saved"]), 40)
        found = self.tranche("n", depth=1)
        self.assertEqual(len(found["saved"]), 1)  # Every new finding compared with the same most telling one.
        self.assertIn(next(iter(found["saved"])), ids + others)

    def test_on_one_polymer_the_same_grade_is_compared_first(self):
        other, same = self.save("s", [
            fact("PLA 2003D had a tensile strength of 53 MPa.", "PLA 2003D", "tensile strength", "53", "MPa", doi="10.1/a"),
            fact("PLA 4032D had a tensile strength of 54 MPa.", "PLA 4032D", "tensile strength", "54", "MPa",
                 doi="10.1/b")])
        _, [new], _ = self.answer("n", [fact("PLA 4032D had a tensile strength of 55 MPa.", "PLA 4032D",
                                             "tensile strength", "55", "MPa", doi="10.1/c")])
        self.assertEqual(self.tranche("n")["new"], {new: [same, other]})
        # A comparison alone asks for no source verdicts.
        found = self.tranche("n")
        prompt = reviewer.review_prompt([], None, found)
        self.assertIn("Review every finding in findings below", prompt)
        self.assertIn("a finding listed only under consistency gets no verdict", prompt)
        self.assertNotIn("Review every finding below and return", prompt)
        self.assertEqual(json.loads(prompt[prompt.index("\n{") + 1:])["findings"], [])

    def test_every_new_finding_gets_a_share_of_the_budget(self):
        # Eight new findings on eight polymers, each with eight equally telling saved findings of its own: the cap of
        # 40 saved findings is shared out, never spent on the first five.
        polymers = ["wop-%06d" % i for i in range(1, 9)]
        for i, polymer in enumerate(polymers):
            self.save("s%d" % i, [fact("Polymer %d had a tensile strength of %d MPa (run %d)." % (i, 50 + j, j),
                                       "polymer %d" % i, "tensile strength", str(50 + j), "MPa", subject=polymer,
                                       doi="10.1/s%d-%d" % (i, j)) for j in range(8)])
        self.answer("n", [fact("Polymer %d had a tensile strength of 52 MPa." % i, "polymer %d" % i, "tensile strength",
                               "52", "MPa", subject=polymer, doi="10.1/n%d" % i) for i, polymer in enumerate(polymers)])
        found = self.tranche("n")
        self.assertEqual(len(found["new"]), 8)
        self.assertLessEqual(len(found["saved"]), 40)
        self.assertEqual({len(ids) for ids in found["new"].values()}, {5})

    def test_a_unit_slip_in_saved_knowledge_reaches_the_comparison(self):
        # Planted-conflict check, 2026-11-05: a correct "6.00 GPa" was taken for a repeat of a saved "6.00 MPa".
        [slip] = self.save("s", [fact("Udel GF-120 had a tensile modulus of 6.00 MPa (ASTM D638).", "Udel GF-120",
                                      "tensile modulus", "6.00", "MPa", doi="10.1/udel")])
        _, [new], state = self.answer("n", [fact("Udel GF-120 had a tensile modulus of 6.00 GPa (ASTM D638).",
                                                 "Udel GF-120", "tensile modulus", "6.00", "GPa", doi="10.1/udel")])
        self.assertEqual((state, self.tranche("n")["tension"]), ("tension", [(new, slip)]))

    def test_a_filed_finding_is_compared_with_unfiled_ones_naming_its_material(self):
        [old] = self.save("s", [fact("Ingeo 4032D had a glass transition temperature of 60 °C.", "Ingeo 4032D",
                                     "glass transition temperature", "60", "°C", subject="", doi="10.1/a")])
        self.assertFalse(knowledge.get(self.root, old).get("subject"))
        _, [new], state = self.answer("n", [fact("Ingeo 4032D had a Tg of 160 °C.", "Ingeo 4032D",
                                                 "glass transition temperature", "160", "°C", doi="10.1/b")])
        self.assertEqual((state, self.tranche("n")["new"]), ("tension", {new: [old]}))

    def test_a_new_finding_joins_the_property_terms_in_force_and_is_compared_through_them(self):
        [tg60] = self.save("s", [fact("PLA had a glass transition temperature of 60 °C.", "PLA",
                                      "glass transition temperature", "60", "°C", doi="10.1/a")])
        reflect.apply(self.root, {"id": "e-tg", "type": "property-term", "fields": {
            "term": "glass-transition-temperature", "names": ["glass transition temperature", "Tg"]}})
        _, [new], state = self.answer("n", [fact("PLA 2003D softened at 160 °C.", "PLA", "Tg", "160", "°C",
                                                 doi="10.1/b")])
        with knowledge.connect(self.root) as db:
            terms = {f for (f,) in db.execute("SELECT finding_id FROM finding_terms")}
        self.assertEqual(terms, {tg60, new})  # Annotated when saved, not at the next reflection.
        self.assertEqual((state, self.tranche("n")["new"]), ("tension", {new: [tg60]}))

    def test_the_reviewer_settles_conflicts_by_default(self):
        tg60, tg62, tm = self.save("s", [
            fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition temperature", "60", "°C",
                 doi="10.1/a"),
            fact("PLA had a glass transition temperature of 62 °C.", "PLA", "glass transition temperature", "62", "°C",
                 doi="10.1/b"),
            fact("PLA melted at 150 °C.", "PLA", "melting temperature", "150", "°C", doi="10.1/c")], reviewed=[0])
        question, (wrong, other, melt), state = self.answer("n", [
            fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature", "160", "°C", doi="10.1/d"),
            fact("PLA had a Tg of 61 °C after annealing.", "PLA", "glass transition temperature", "61", "°C",
                 doi="10.1/e"),
            fact("PLA melted at 175 °C.", "PLA", "melting temperature", "175", "°C", doi="10.1/f")])
        self.assertEqual((state, knowledge.review_queue(self.root)), ("tension", [question]))

        def conflicts(section):
            self.assertEqual({n["id"] for n in section["new"]}, {wrong, other, melt})
            # Each saved one once, by a short id; its source by one address; its status in words.
            self.assertEqual([s["id"] for s in section["saved"]], ["s%d" % n for n in range(1, len(section["saved"]) + 1)])
            ref = {s["statement"]: s for s in section["saved"]}["PLA had a glass transition temperature of 60 °C."]
            self.assertEqual(ref["status"], "Reviewed")
            self.assertEqual(ref["source"]["doi"], "10.1/a")  # In tension: its source in full, as it may be opened.
            return [{"finding": wrong, "with": ref["id"], "reading": "new-misread",
                     "reason": "Its Table 2 gives 60 °C, as %s says." % ref["id"]},
                    {"finding": wrong, "with": tg60, "reading": "unresolved", "reason": "A second conflict, ignored."},
                    {"finding": other, "with": tg62, "reading": "sources-disagree", "reason": "Both read right."},
                    {"finding": melt, "with": tm, "reading": "saved-misread", "reason": "Its Table 3 gives 175 °C."},
                    {"finding": melt, "with": tg60, "reading": "new-misread", "reason": "Never offered."}]
        engine = Reviewer(conflicts)
        summary = reviewer.review(self.root, question, runner=engine, engine="codex")
        self.assertIs(engine.calls[0]["schema"], reviewer.CONSISTENCY_SCHEMA)
        self.assertIn(consistency.INSTRUCTION, engine.calls[0]["prompt"])
        self.assertEqual(self.status(wrong), "unsupported")
        self.assertIn("conflicts with " + tg60, knowledge.get(self.root, wrong)["review"]["reason"])
        self.assertIn("as %s says" % tg60, knowledge.get(self.root, wrong)["review"]["reason"])  # Its short id, mapped back.
        self.assertEqual(self.status(tm), "unsupported")  # The saved finding misread its source.
        self.assertEqual((self.status(other), self.status(tg62), self.status(tg60)), ("accepted", "accepted", "supported"))
        self.assertEqual(knowledge.get(self.root, other)["conflictsWith"], [tg62])
        self.assertEqual(knowledge.get(self.root, tg62)["conflictsWith"], [other])
        self.assertEqual(summary["consistency"], {"state": "checked", "compared": 3, "conflicts": 3, "open": 0,
                                                  "waiting": False})
        self.assertEqual([(c["reading"], c["resolution"], c["settledBy"]) for c in
                          sorted(consistency.conflicts(self.root), key=lambda c: c["reading"])],
                         [("new-misread", "new-misread", "reviewer"), ("saved-misread", "saved-misread", "reviewer"),
                          ("sources-disagree", "sources-disagree", "reviewer")])
        self.assertEqual(knowledge.review_queue(self.root), [])
        # A search shows a finding's conflicts with findings still in force, so an answer reports both.
        found = knowledge.search(self.root, "PLA glass transition temperature", compact=True)
        shown = {f["id"]: f.get("conflictsWith") for group in ("reviewed", "added") for f in found[group]}
        self.assertEqual((shown[other], shown[tg62], shown[tg60]), ([tg62], [other], None))
        self.assertNotIn(wrong, shown)

    def test_a_reviewed_finding_judged_misread_needs_checking_and_a_supported_new_one_is_not_rejected(self):
        [tg60] = self.save("s", [fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition "
                                      "temperature", "60", "°C", doi="10.1/a")], reviewed=[0])
        question, [new], _ = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature",
                                                    "160", "°C", doi="10.1/b", status="unreviewed")])
        engine = Reviewer(lambda section: [{"finding": new, "with": tg60, "reading": "new-misread", "reason": "?"}],
                          verdicts=lambda findings: [{"id": new, "verdict": "supported", "reason": "Table 2.",
                                                      "excerpt": "Tg 160 °C", "material": ""}])
        reviewer.review(self.root, question, runner=engine, engine="codex")
        # The same review found it supported: the conflict stays open for a person, both linked.
        self.assertEqual(self.status(new), "supported")
        [open_] = consistency.conflicts(self.root, "open")
        self.assertEqual((open_["reading"], open_["finding"]["id"], open_["other"]["id"]), ("new-misread", new, tg60))
        self.assertEqual(knowledge.get(self.root, tg60)["conflictsWith"], [new])

        [tg62] = self.save("t", [fact("PLA had a glass transition temperature of 62 °C.", "PLA", "glass transition "
                                      "temperature", "62", "°C", doi="10.1/c")], reviewed=[0])
        question, (later, again) = self.answer("u", [
            fact("PLA had a Tg of 20 °C.", "PLA", "glass transition temperature", "20", "°C", doi="10.1/d"),
            fact("PLA film had a Tg of 21 °C.", "PLA", "glass transition temperature", "21", "°C", doi="10.1/e")])[:2]
        reviewer.review(self.root, question, runner=Reviewer(lambda section: [
            {"finding": later, "with": tg62, "reading": "saved-misread", "reason": "Its table gives 26 °C."},
            {"finding": again, "with": tg62, "reading": "saved-misread", "reason": "Its table gives 26 °C."}]),
            engine="codex")
        # A second reviewer's word makes a Reviewed one Needs checking, once, however many conflicts name it.
        self.assertEqual(self.status(tg62), "uncertain")
        self.assertEqual(len([c for c in consistency.conflicts(self.root) if c["reading"] == "saved-misread"]), 2)

    def test_with_person_resolution_conflicts_wait_for_a_person(self):
        loop.update_settings(self.root, {"conflictResolution": "person"})
        tg60, tg62 = self.save("s", [
            fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition temperature", "60", "°C",
                 doi="10.1/a"),
            fact("PLA had a glass transition temperature of 62 °C.", "PLA", "glass transition temperature", "62", "°C",
                 doi="10.1/b")])
        question, [wrong], _ = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature",
                                                      "160", "°C", doi="10.1/d")])
        reviewer.review(self.root, question, runner=Reviewer(lambda section: [
            {"finding": wrong, "with": tg60, "reading": "new-misread", "reason": "Its Table 2 gives 60 °C."},
            {"finding": wrong, "with": tg62, "reading": "sources-disagree", "reason": "Both read right."}]),
            engine="codex")
        self.assertEqual({self.status(i) for i in (wrong, tg60, tg62)}, {"accepted"})  # Nothing changed status.
        waiting = {c["other"]["id"]: c for c in consistency.conflicts(self.root, "open")}
        self.assertEqual({k: v["reading"] for k, v in waiting.items()},
                         {tg60: "new-misread", tg62: "sources-disagree"})
        self.assertEqual(sorted(knowledge.get(self.root, wrong)["conflictsWith"]), sorted([tg60, tg62]))
        self.assertEqual(consistency.stats(self.root)["open"], 2)
        with self.assertRaises(ValueError):
            consistency.settle(self.root, waiting[tg60]["id"], "approve")

        settled = consistency.settle(self.root, waiting[tg60]["id"], "new-misread", "Table 2 says 60 °C.")
        self.assertEqual((settled["status"], settled["resolution"], settled["settledBy"]),
                         ("settled", "new-misread", "person"))
        found = knowledge.get(self.root, wrong)
        self.assertEqual((found["status"], found["review"]["engine"]), ("unsupported", "person"))
        self.assertIn("A person judged", found["review"]["reason"])
        self.assertEqual(knowledge.get(self.root, tg60).get("conflictsWith"), None)
        consistency.settle(self.root, waiting[tg62]["id"], "no-conflict")
        self.assertEqual((self.status(tg62), knowledge.get(self.root, tg62).get("conflictsWith")), ("accepted", None))
        with self.assertRaises(ValueError):
            consistency.settle(self.root, waiting[tg62]["id"], "no-conflict")  # Settled already.

    def test_a_person_confirming_the_sources_disagree_keeps_both_linked(self):
        loop.update_settings(self.root, {"conflictResolution": "person"})
        [tg60] = self.save("s", [fact("PLA had a glass transition temperature of 60 °C.", "PLA",
                                      "glass transition temperature", "60", "°C", doi="10.1/a")])
        question, [new], _ = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature",
                                                    "160", "°C", doi="10.1/b")])
        reviewer.review(self.root, question, runner=Reviewer(lambda section: [
            {"finding": new, "with": tg60, "reading": "sources-disagree", "reason": "Both read right."}]), engine="codex")
        [waiting] = consistency.conflicts(self.root, "open")
        consistency.settle(self.root, waiting["id"], "sources-disagree")
        self.assertEqual((knowledge.get(self.root, new)["conflictsWith"], knowledge.get(self.root, tg60)["conflictsWith"]),
                         ([tg60], [new]))
        found = knowledge.search(self.root, "PLA glass transition temperature", compact=True)
        self.assertEqual({f["id"]: f.get("conflictsWith") for f in found["added"]}, {new: [tg60], tg60: [new]})

    def test_a_rejection_calls_off_a_pending_recheck_and_a_merged_finding_is_followed(self):
        loop.update_settings(self.root, {"conflictResolution": "person"})
        tg60, tg62 = self.save("s", [
            fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition temperature", "60", "°C",
                 doi="10.1/a"),
            fact("PLA had a glass transition temperature of 62 °C.", "PLA", "glass transition temperature", "62", "°C",
                 doi="10.1/b")], reviewed=[0, 1])
        question, [new], _ = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature",
                                                    "160", "°C", doi="10.1/c")])
        reviewer.review(self.root, question, runner=Reviewer(lambda section: [
            {"finding": new, "with": tg60, "reading": "saved-misread", "reason": "?"},
            {"finding": new, "with": tg62, "reading": "saved-misread", "reason": "?"}]), engine="codex")
        waiting = {c["other"]["id"]: c["id"] for c in consistency.conflicts(self.root, "open")}
        # tg60 waits for a recheck of its excerpt; a person rejects it; the recheck cannot bring it back.
        with knowledge.connect(self.root) as db:
            knowledge._set_detail(db, tg60, recheck="pending")
            db.execute("UPDATE deposits SET review_attempts=0 WHERE question_id=?", ("s" * 32,))
        self.assertIn("s" * 32, knowledge.review_queue(self.root))
        consistency.settle(self.root, waiting[tg60], "saved-misread")
        self.assertEqual((self.status(tg60), knowledge.get(self.root, tg60).get("recheck")), ("unsupported", None))
        self.assertNotIn("s" * 32, knowledge.review_queue(self.root))
        # tg62 is merged into a kept duplicate before anyone settles its conflict: the conflict follows it.
        [kept] = self.save("k", [fact("PLA Tg was 62 °C.", "PLA", "glass transition temperature", "62", "°C",
                                      doi="10.1/k")])
        with knowledge.connect(self.root) as db:
            db.execute("INSERT INTO merged VALUES (?,?,?,?)", (tg62, kept, "now", "{}"))
            consistency.merged(db, tg62, kept)
            db.execute("DELETE FROM findings WHERE id=?", (tg62,))
        self.assertEqual(knowledge.get(self.root, new)["conflictsWith"], [kept])
        self.assertEqual(consistency.conflict(self.root, waiting[tg62])["other"]["id"], kept)
        consistency.settle(self.root, waiting[tg62], "saved-misread")
        self.assertEqual(self.status(kept), "unsupported")
        # A finding gone without a trace cannot be rejected: that conflict is settled another way.
        question, [gone], state = self.answer("m", [fact("PLA had a Tg of 60 °C.", "PLA", "glass transition temperature",
                                                         "60", "°C", doi="10.1/m")])
        self.assertEqual(state, "tension")  # With the 160 °C finding, the one left in force.
        reviewer.review(self.root, question, runner=Reviewer(lambda section: [
            {"finding": gone, "with": new, "reading": "new-misread", "reason": "?"}]), engine="codex")
        [last] = consistency.conflicts(self.root, "open")
        with knowledge.connect(self.root) as db:
            db.execute("DELETE FROM findings WHERE id=?", (gone,))
        with self.assertRaises(ValueError):
            consistency.settle(self.root, last["id"], "new-misread")
        self.assertEqual(consistency.settle(self.root, last["id"], "no-conflict")["status"], "settled")

    def test_an_answer_with_nothing_in_tension_is_compared_only_when_a_review_runs_anyway(self):
        [tg60] = self.save("s", [fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition "
                                      "temperature", "60", "°C", doi="10.1/a")])
        question, [close], state = self.answer("n", [fact("PLA had a Tg of 61 °C.", "PLA", "glass transition "
                                                          "temperature", "61", "°C", doi="10.1/b")])
        self.assertEqual((state, knowledge.review_queue(self.root)), ("pending", []))
        engine = Reviewer()
        reviewer.review(self.root, question, runner=engine, engine="codex")
        self.assertEqual(engine.calls, [])
        # A finding flagged for review brings the comparison into its session.
        question, (flagged, quiet), state = self.answer("f", [
            fact("PLA had a Tg of 59 °C read from Figure 2.", "PLA", "glass transition temperature", "59", "°C",
                 doi="10.1/c", status="unreviewed"),
            fact("PLA had a Tg of 60.5 °C.", "PLA", "glass transition temperature", "60.5", "°C", doi="10.1/d")])
        self.assertEqual(state, "pending")
        summary = reviewer.review(self.root, question, runner=engine, engine="codex")
        given = engine.calls[0]["given"]
        self.assertEqual([f["id"] for f in given["findings"]], [flagged])
        new = {n["id"]: n for n in given["consistency"]["new"]}
        self.assertEqual(set(new[flagged]), {"id", "compareWith"})  # Listed for its source check: by id alone.
        self.assertIn("statement", new[quiet])
        saved = {s["id"]: s for s in given["consistency"]["saved"]}
        [ref] = [r for r in new[quiet]["compareWith"] if saved[r]["statement"].endswith("of 60 °C.")]
        # Not in tension: its source by one address, and no material the statement already gives.
        self.assertEqual((saved[ref]["source"], "material" in saved[ref]), ("10.1/a", False))
        self.assertEqual(summary["consistency"]["state"], "checked")

    def test_off_compares_nothing_and_a_tension_gone_by_review_time_needs_no_session(self):
        [tg60] = self.save("s", [fact("PLA had a glass transition temperature of 60 °C.", "PLA", "glass transition "
                                      "temperature", "60", "°C", doi="10.1/a")])
        question, _, state = self.answer("n", [fact("PLA had a Tg of 160 °C.", "PLA", "glass transition temperature",
                                                    "160", "°C", doi="10.1/b")], depth=0)
        self.assertIsNone(state)
        self.assertIsNone(knowledge.deposit_summary(self.root, question)["consistency"])
        self.assertEqual(knowledge.review_queue(self.root), [])
        question, _, state = self.answer("m", [fact("PLA had a Tg of 150 °C.", "PLA", "glass transition temperature",
                                                    "150", "°C", doi="10.1/c")])
        self.assertEqual(state, "tension")
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET status='unsupported' WHERE id=?", (tg60,))
        engine = Reviewer()
        summary = reviewer.review(self.root, question, runner=engine, engine="codex")
        self.assertEqual((engine.calls, knowledge.review_queue(self.root)), ([], []))
        # Nothing saved is related any more but the first answer's 160 °C, which is not in tension with 150 °C.
        self.assertEqual(summary["consistency"]["state"], "pending")
        loop.update_settings(self.root, {"consistencyDepth": 0})
        self.assertIsNone(consistency.tranche(self.root, question, 0))

    def test_settings_are_validated(self):
        self.assertEqual({k: loop.settings(self.root)[k] for k in ("consistencyDepth", "conflictResolution")},
                         {"consistencyDepth": 8, "conflictResolution": "reviewer"})
        for bad in ({"consistencyDepth": -1}, {"consistencyDepth": 26}, {"consistencyDepth": "8"},
                    {"consistencyDepth": 2.5}, {"conflictResolution": "robot"}):
            with self.subTest(change=bad), self.assertRaises(ValueError):
                loop.update_settings(self.root, bad)
        self.assertEqual(loop.update_settings(self.root, {"consistencyDepth": 20, "conflictResolution": "person"})
                         ["consistencyDepth"], 20)


if __name__ == "__main__":
    unittest.main()
