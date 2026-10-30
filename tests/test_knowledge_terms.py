"""Search reads property terms only from tables a store may hold (`oopc reflect` writes them); without them, or with
them empty, it returns what it returned before."""
import json
import unittest

import test_knowledge_search as base
from oopc import knowledge

finding = base.finding

# The tables as the refinement study pins them (studies/macromolecules/refinement/pins.py, TABLES).
TABLES = """
CREATE TABLE IF NOT EXISTS property_terms (term TEXT PRIMARY KEY, names TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finding_terms (finding_id TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY (finding_id, term));
"""
GLASS = ("glass-transition", ["glass transition temperature", "glass transition", "Tg", "T_g"])
DENSITY = ("density", ["density", "specific gravity", "ρ"])


class KnowledgeTerms(unittest.TestCase):
    setUp = base.KnowledgeSearch.setUp  # A small graph release: PLA, PCL, the polyethylene family and others.
    save = base.KnowledgeSearch.save

    def ids(self, query, **options):
        return [f["id"] for f in knowledge.search(self.root, query, **options)["added"]]

    def tables(self, terms=(), annotations=()):
        with knowledge.connect(self.root) as db:
            db.executescript(TABLES)
            db.executemany("INSERT INTO property_terms VALUES (?, ?)", [(t, json.dumps(names)) for t, names in terms])
            db.executemany("INSERT INTO finding_terms VALUES (?, ?)", annotations)

    def present(self):
        with knowledge.connect(self.root) as db:
            return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} & set(knowledge.TERMS)

    def test_without_the_tables_or_with_them_empty_a_search_is_unchanged(self):
        self.save("a", [finding("PLA 4032D had a Tg of 60 °C by DSC.", "PLA 4032D", "accepted", doi="10.1/s"),
                        finding("DSC scans used a heating rate of 10 K/min under nitrogen.", "DSC specimens", "accepted",
                                doi="10.1/s"),
                        finding("PLA crystallinity rose to 45% after annealing at 100 °C.", "PLA", "accepted", doi="10.1/a"),
                        finding("PLA films lost mass in buffer at body temperature.", "PLA films", "accepted", doi="10.1/m")])
        self.save("b", [finding("Polycaprolactone had a glass transition temperature of −60 °C.", "PCL", "accepted",
                                doi="10.1/c"),
                        finding("Marlex HDPE film absorbed 0.01% water.", "Marlex film", "accepted", subject="wop-000010",
                                doi="10.1/hd"),
                        finding("Polyethylene films absorb little water.", "polyethylene", "accepted", subject="wop-000009",
                                doi="10.1/pe"),
                        finding("LDPE specific gravity was 0.92.", "LDPE", "accepted", subject="wop-000011", doi="10.1/ld")],
                  review=True)
        knowledge.deposit(self.root, "n" * 32, {"findings": [], "sources": [
            {"title": "Thermal analysis of PLA films", "url": "https://doi.org/10.1/s", "doi": "10.1/s", "locator": "",
             "excerpts": ["PLA 4032D Tg 60 °C"], "supports": "PLA Tg by DSC", "conditions": ""}]}, engine="codex")
        queries = ["PLA glass transition temperature", "PCL Tg", "HDPE density", "polyethylene water absorption",
                   "high-density polyethylene water absorption", "Phenol–formaldehyde resin family", "glass transition",
                   "specific gravity", "annealing crystallinity", "heating rate under nitrogen", "Tg"]
        search = lambda: [knowledge.search(self.root, q, compact=compact) for q in queries for compact in (False, True)]
        before = search()
        self.assertGreater(sum(bool(found["reviewed"] or found["added"]) for found in before), len(queries))
        self.assertEqual(self.present(), set())  # A search never creates them.
        self.tables()
        self.assertEqual(self.present(), set(knowledge.TERMS))
        self.assertEqual(search(), before)
        # Terms are read only beside their annotations' table.
        with knowledge.connect(self.root) as db:
            db.execute("DROP TABLE finding_terms")
            db.execute("INSERT INTO property_terms VALUES (?, ?)", (GLASS[0], json.dumps(GLASS[1])))
        self.assertEqual(search(), before)

    def test_a_property_term_finds_findings_written_with_its_other_names(self):
        [symbol] = self.save("a", [finding("PLA 4032D had a Tg of 60 °C by DSC.", "PLA 4032D", "accepted", doi="10.1/a")])
        [words] = self.save("b", [finding("Polycaprolactone had a glass transition temperature of −60 °C.", "PCL",
                                          "accepted", doi="10.1/b")])
        [warm] = self.save("c", [finding("PLA films lost mass in buffer at body temperature.", "PLA films", "accepted",
                                         doi="10.1/c")])
        self.assertEqual(self.ids("glass transition temperature"), [words, warm])
        self.assertEqual(self.ids("Tg"), [symbol])
        self.tables(terms=[GLASS, DENSITY])
        found = self.ids("glass transition temperature")
        self.assertEqual((set(found[:2]), found[2:]), ({words, symbol}, [warm]))
        self.assertEqual(set(self.ids("Tg")), {symbol, words})  # "temperature" alone does not name the term.
        # The polymer a query names still decides which findings are about it.
        self.assertEqual(self.ids("PCL Tg"), [words])

    def test_an_annotation_covers_the_terms_words_within_the_polymer_asked_about(self):
        [tan] = self.save("a", [finding("PLA 2003D showed a tan δ peak at 62 °C.", "PLA 2003D", "accepted", doi="10.1/t")])
        [warm] = self.save("b", [finding("PLA films lost mass in buffer at body temperature.", "PLA films", "accepted",
                                         doi="10.1/w")])
        [other] = self.save("c", [finding("Capa 6800 showed a tan δ peak at −55 °C.", "Capa 6800", "accepted",
                                          subject="wop-000002", doi="10.1/o")])
        [family] = self.save("d", [finding("The film's β relaxation was at −20 °C.", "film", "accepted",
                                           subject="wop-000009", doi="10.1/f")])
        [sibling] = self.save("e", [finding("The film's γ relaxation was at −120 °C.", "film", "accepted",
                                            subject="wop-000011", doi="10.1/g")])
        self.assertEqual(self.ids("PLA glass transition temperature"), [warm, tan])  # tan matches only the polymer.
        self.assertEqual(self.ids("HDPE glass transition"), [])
        self.tables(terms=[GLASS], annotations=[(i, GLASS[0]) for i in (tan, other, family, sibling)])
        self.assertEqual(self.ids("PLA glass transition temperature"), [tan, warm])
        # Annotated findings filed under the polymer's family come in; a sibling's or another polymer's do not.
        self.assertEqual(self.ids("HDPE glass transition"), [family])
        self.assertEqual(self.ids("PCL glass transition"), [other])

    def test_a_term_name_inside_a_polymer_name_does_not_take_over_the_polymer(self):
        [water] = self.save("a", [finding("Marlex HDPE film absorbed 0.01% water.", "Marlex film", "accepted",
                                          subject="wop-000010", doi="10.1/hd")])
        [gravity] = self.save("b", [finding("The resin's specific gravity was 0.95.", "resin", "accepted",
                                            subject="wop-000009", doi="10.1/pe")])
        self.save("c", [finding("PLA bars absorbed 0.5% water.", "PLA bars", "accepted", doi="10.1/pla")])
        query = "high-density polyethylene water absorption"
        before = self.ids(query)
        self.assertEqual((before, self.ids("HDPE density")), ([water], [water]))
        self.tables(terms=[DENSITY, GLASS])
        self.assertEqual(self.ids(query), before)  # "density" is part of the polymer's name, not the property.
        self.assertEqual(set(self.ids("HDPE density")), {water, gravity})  # Here it is the property.


if __name__ == "__main__":
    unittest.main()
