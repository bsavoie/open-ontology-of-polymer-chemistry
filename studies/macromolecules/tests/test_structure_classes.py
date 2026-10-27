"""Strategy 3's offline estimate (`structure/classes.py`) on hand-made records: values parsed and normalized; a
finding's class from A1's map, else its rules; the class-based first search (lineage, class, ranking, the first ten,
the same-source cap); recall against Part C's verdicts, the grown pool and the upper bound; the blind judge writing only
to this study's folder (Part C's untouched), judging only what Part C never saw, blind and once; late finds and later
searches; tables, conflicts and the prediction verdicts."""
import contextlib, io, random, re, shutil, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
import driver  # noqa: E402
from structure import classes  # noqa: E402
from refinement import lookup, mine, pins  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402

MAP = {"tensile strength": {"class": "tensile-strength", "assignedBy": "rule"},
       "glass transition temperature": {"class": "glass-transition-temperature", "assignedBy": "rule"},
       "heating rate": {"class": "heating-cooling-rate", "assignedBy": "rule"},
       "odd label": {"class": "tensile-modulus", "assignedBy": "model"}}
ASKED, FAMILY, OTHER = "wop-000001", "wop-000100", "wop-000002"
LINEAGE = {ASKED: {ASKED, FAMILY}, OTHER: {OTHER, FAMILY}}
QUESTION = {"id": "q1", "set": "H", "kind": "property", "group": "property", "stratum": "near",
            "property": "tensile strength", "materials": ["PLA"], "polymerIds": [ASKED],
            "question": "Report a published tensile strength of PLA."}


def lineage(root, ids):
    return set().union(*(LINEAGE.get(i, {i}) for i in ids)) if ids else set()


def row(identifier, prop, value, unit, subject, status=knowledge.SUPPORTED, source="a"):
    return {"id": identifier, "property": prop, "value": value, "unit": unit, "subject": subject, "status": status,
            "source": source}


ROWS = [row("finding:r1", "tensile strength", "60 ± 2", "MPa", ASKED),
        row("finding:fam", "tensile strength", "50", "MPa", FAMILY, source="d"),
        row("finding:a1", "tensile strength", "55", "MPa", ASKED, knowledge.ACCEPTED, "b"),
        row("finding:u1", "tensile strength", "58", "MPa", ASKED, knowledge.UNCERTAIN, "c"),
        row("finding:x", "tensile strength", "1", "MPa", ASKED, knowledge.UNSUPPORTED),
        row("finding:cond", "heating rate", "10", "°C/min", ASKED),
        row("finding:tg", "glass transition temperature", "60", "°C", ASKED, source="e"),
        row("finding:unfiled", "tensile strength", "40", "MPa", "", source="g"),
        row("finding:other", "tensile strength", "90", "MPa", OTHER, source="f")]


def make_store(root, rows):
    with knowledge.connect(root) as db:
        for r in rows:
            knowledge._insert_finding(db, r["id"], "q", "research", knowledge.clean_finding({
                "statement": "A %s finding." % r["property"], "material": "PLA", "property": r["property"],
                "value": r["value"], "unit": r["unit"], "conditions": "", "subject": r["subject"],
                "sourceTitle": "Paper", "sourceUrl": "https://example.org/%s" % r["source"], "sourceDoi": "",
                "locator": "Table 1", "excerpt": r["value"], "derivation": "read"}),
                status=r["status"], producer_engine="codex", created_at="2026-10-10T00:00:00+00:00")


class World:
    """A store, A1's map and vocabulary, Part C's lookup folder (one question's searches and verdicts) and this study's
    output folder, all temporary; `knowledge.lineage` reads LINEAGE."""

    def __init__(self, test, rows=ROWS):
        self.top = Path(tempfile.mkdtemp(prefix="oopc-structure-test-"))
        test.addCleanup(shutil.rmtree, self.top, True)
        self.root, self.partc, self.out = self.top / "KF", self.top / "partc", self.top / "out"
        make_store(self.root, rows)
        atomic_json(self.top / "map.json", MAP)
        for patch in (mock.patch.object(pins, "PROPERTY_MAP", self.top / "map.json"),
                      mock.patch.object(knowledge, "lineage", lineage)):
            patch.start()
            test.addCleanup(patch.stop)
        self.idx = classes.index(self.root)
        self.props = mine.Properties(self.top / "map.json")

    def part_c(self, question_id, queries, verdicts):
        atomic_json(self.partc / "searches" / (question_id + ".json"), {"question": question_id, "queries": [
            {"q": q, "limit": 10, "origins": [origin], "returned": {"B": ids, "Oplus": ids},
             "pooled": {"B": ids, "Oplus": ids}} for q, origin, ids in queries]})
        atomic_json(self.partc / "judge" / question_id / "call-1.json", {
            "question": question_id, "call": 1, "findings": sorted(verdicts), "result": {"relevant": verdicts}})


class Values(unittest.TestCase):
    def test_numbers_uncertainties_ranges_and_what_is_not_numeric(self):
        cases = {("60", "MPa"): ("point", 60, 60), ("1,200", "g/mol"): ("point", 1200, 1200),
                 ("−125", "°C"): ("point", -125, -125), ("1.2e-3", ""): ("point", 0.0012, 0.0012),
                 ("1.11 × 10⁻¹⁰", "cm³"): ("point", 1.11e-10, 1.11e-10),
                 ("about 7", "MPa"): ("approx", 7, 7), ("31.4 ± 0.95", "MPa"): ("uncertainty", 30.45, 32.35),
                 ("(1.2 ± 0.1) × 10⁻³", "Pa"): ("uncertainty", 0.0011, 0.0013),
                 ("48.3 (0.3)", "MPa"): ("uncertainty", 48.0, 48.6),
                 ("approximately 4.0 ± 0.1", "mg"): ("uncertainty", 3.9, 4.1),
                 ("10–11", "µm"): ("range", 10, 11), ("120–105", "°C"): ("range", 105, 120),
                 ("100 to −80", "°C"): ("range", -80, 100), ("between 5 and 9", "%"): ("range", 5, 9),
                 ("94.5 %", ""): ("point", 94.5, 94.5), ("210 °C", "°C"): ("point", 210, 210)}
        for (value, unit), (kind, low, high) in cases.items():
            got = classes.parse_value(value, unit)
            self.assertEqual(got["kind"], kind, value)
            self.assertAlmostEqual(got["low"], low, msg=value)
            self.assertAlmostEqual(got["high"], high, msg=value)
        self.assertEqual(classes.parse_value("94.5 %", "")["unit"], "%")  # the unit written in the value
        for value, unit, kind in (("<0.01", "%", "bound"), ("at least 5", "specimens", "bound"),
                                  ("180.9 and 171.7", "°C", "list"), ("50 × 50 × 2", "mm", "list"),
                                  ("90.9; 3.2", "kDa; dimensionless", "list"), ("nitrogen", "", "text"),
                                  ("ASTM D638", "", "text"), ("", "MPa", "empty")):
            self.assertEqual(classes.parse_value(value, unit)["kind"], kind, value)

    def test_a_unit_normalizes_only_when_oopc_units_knows_it(self):
        n = classes.normalized(classes.parse_value("60", "°C"))
        self.assertEqual(n["dimension"], "temperature")
        self.assertAlmostEqual(n["low"], 333.15)
        self.assertAlmostEqual(classes.normalized(classes.parse_value("2 ± 0.5", "GPa"))["high"], 2.5e9)
        self.assertAlmostEqual(classes.normalized(classes.parse_value("45", "%"))["low"], 0.45)
        self.assertEqual(classes.normalized(classes.parse_value("12", "μm"))["dimension"], "length")  # Greek mu, NFKC
        for value, unit in (("6", "kJ/m²"), ("77", "Shore A"), ("2.86", ""), ("<5", "MPa"), ("soft", "MPa")):
            self.assertIsNone(classes.normalized(classes.parse_value(value, unit)), (value, unit))

    def test_a_findings_class_comes_from_the_map_then_the_rules(self):
        self.assertEqual(classes.finding_class("Tensile  Strength", MAP), "tensile-strength")  # normalized key
        self.assertEqual(classes.finding_class("odd label", MAP), "tensile-modulus")  # a stored assignment
        self.assertEqual(classes.finding_class("melt flow rate", MAP), "melt-flow-rate")  # A1's rules
        self.assertEqual(classes.finding_class("", MAP), "unclassified")


class Search(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def search(self, groups, wanted, limit=classes.LIMIT, same=classes.SAME_SOURCE):
        return classes.class_search(self.world.idx, self.world.root, groups, wanted, limit, same)

    def test_lineage_and_class_ranked_by_status_then_the_asked_polymer_then_same_source(self):
        got = self.search([[ASKED]], ["tensile-strength"])
        # reviewed (the asked polymer before its family), added, needs checking; then r1's source-mate; never the
        # rejected, unfiled, other-polymer or other-class findings
        self.assertEqual(got, ["finding:r1", "finding:fam", "finding:a1", "finding:u1", "finding:cond"])
        self.assertEqual(self.search([[ASKED]], ["tensile-strength"], limit=2, same=0), ["finding:r1", "finding:fam"])
        self.assertEqual(self.search([[ASKED], [OTHER]], ["tensile-strength"], same=0)[-1], "finding:other")
        self.assertEqual(self.search([[ASKED]], ["glass-transition-temperature"], same=0), ["finding:tg"])
        self.assertEqual(self.search([], ["tensile-strength"]), [])

    def test_same_source_findings_are_capped_at_twelve_per_call_unless_uncapped(self):
        rows = [row("finding:v", "tensile strength", "60", "MPa", ASKED)] + [
            row("finding:s%02d" % n, "heating rate", str(n), "K/min", ASKED) for n in range(20)]
        world = World(self, rows)
        capped = classes.class_search(world.idx, world.root, [[ASKED]], ["tensile-strength"])
        uncapped = classes.class_search(world.idx, world.root, [[ASKED]], ["tensile-strength"], same=None)
        self.assertEqual((len(capped), len(uncapped)), (1 + knowledge.SAME_SOURCE, 21))
        self.assertEqual(capped[1:3], ["finding:s00", "finding:s01"])  # in saved order

    def test_structure_counts_classes_kinds_numeric_values_and_normalizable_units(self):
        got = classes.structure(self.world.idx)
        everything = got["all"]
        self.assertEqual(everything["findings"], 8)  # the rejected one is left out
        self.assertEqual((everything["classed"], everything["numeric"], everything["normalizable"]), (8, 8, 7))
        self.assertEqual(got["byKind"], {"material-property": 7, "test-condition": 1})
        self.assertEqual(got["materialProperty"]["normalizableShare"], 1.0)
        self.assertEqual(got["unitsToAdd"], [])  # °C/min is a condition's unit, not a property's
        self.assertEqual(got["classesWithFindings"]["materialProperty"], 2)


class Recall(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.world.part_c("q1", [("PLA tensile strength", "canonical", ["finding:r1", "finding:cond", "finding:tg"]),
                                 ("PLA strength", "issued", ["finding:a1"])],
                          {"finding:r1": True, "finding:cond": True, "finding:tg": False, "finding:a1": True})

    def test_recall_against_part_cs_verdicts_the_grown_pool_and_the_upper_bound(self):
        w = self.world
        got = classes.question_row(w.idx, w.root, QUESTION, w.props, w.out, w.partc)
        self.assertEqual(got["groups"], [[ASKED]])  # the question's polymer id (the store has no graph names)
        self.assertEqual(got["groupsWithoutOracle"], [])
        self.assertEqual(got["classes"], {"curated": ["tensile-strength"], "rules": ["tensile-strength"]})
        first = got["recall"]["curated/first10+source"]
        self.assertEqual((first["partc"], first["unjudged"]), (1.0, 2))  # fam and u1 were never judged
        self.assertEqual(got["recall"]["today/first"]["partc"], 2 / 3)
        self.assertEqual(got["recall"]["today/all"]["partc"], 1.0)
        self.assertEqual(first["grown"], 1.0)  # unjudged counted irrelevant: the lower bound
        self.assertEqual(first["upper"], (3 + 2) / (3 + 2))
        self.assertEqual(got["recall"]["today/first"]["upper"], 2 / 3)  # today's findings were all judged
        # the newly judged findings grow the pool: fam relevant, u1 not
        atomic_json(w.out / "lookup/judge/q1/call-1.json", {"question": "q1", "call": 1, "findings": [
            "finding:fam", "finding:u1"], "result": {"relevant": {"finding:fam": True, "finding:u1": False}}})
        got = classes.question_row(w.idx, w.root, QUESTION, w.props, w.out, w.partc)
        self.assertEqual((got["grownRelevant"], got["unjudged"]), (4, 0))
        self.assertEqual(got["recall"]["curated/first10+source"]["grown"], 1.0)
        self.assertEqual(got["recall"]["today/first"]["grown"], 2 / 4)
        self.assertEqual(got["recall"]["today/all"]["grown"], 3 / 4)
        self.assertEqual(got["recall"]["curated/first10"]["grown"], 3 / 4)  # without the condition's source-mate
        self.assertEqual(classes.missed([got], w.idx, w.root, "curated/first10"), {
            "condition etc.: its source has a class match (cut by a cap)": 1, "total": 1})  # cond, r1's source-mate
        self.assertEqual(got["recall"]["today/first+curated/first10"]["grown"], 1.0)  # added to today's first search
        summary = classes.recall_summary([got], ("today/first", "curated/first10+source"))
        self.assertEqual((summary["today/first"]["grown"], summary["curated/first10+source"]["partcQuestions"]),
                         (0.5, 1))


class Engine:
    """A scripted judge: every finding whose line names "tensile" is relevant; prompts kept."""

    def __init__(self):
        self.prompts = []

    def __call__(self, engine, prompt, schema, **options):
        self.prompts.append(prompt)
        listed = re.findall(r"^(\d+)\. (.*)$", prompt.split("\nFindings:\n", 1)[1], re.M)
        return {"engine": engine, "model": "scripted", "sessionId": "s", "usage": {}, "answer": {"judgements": [
            {"number": int(n), "relevant": "tensile" in line, "reason": "scripted"} for n, line in listed]}}


class Judge(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.world.part_c("q1", [("PLA tensile strength", "canonical", ["finding:r1", "finding:cond"])],
                          {"finding:r1": True, "finding:cond": True})
        quiet = contextlib.redirect_stdout(io.StringIO())  # the Guard prints every event
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def guard(self, engine):
        (self.world.top / "guard").mkdir(exist_ok=True)
        return driver.Guard(time.time() + 600, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                            signed=lambda e: True, base=self.world.top / "guard")

    def run_judge(self, engine):
        w = self.world
        with mock.patch.object(lookup, "withheld", lambda: [QUESTION]):
            return classes.judge(w.out, runner=self.guard(engine), partc=w.partc, root=w.root, labels={ASKED: "PLA"})

    def test_only_what_part_c_never_saw_is_judged_blind_once_in_this_folder(self):
        w = self.world
        before = sorted(p.read_bytes() for p in w.partc.rglob("*.json"))
        engine = Engine()
        state = self.run_judge(engine)
        self.assertEqual((state["status"], state["judged"], state["sessions"]), ("completed", 1, 1))
        call = read_json(w.out / "lookup/judge/q1/call-1.json")
        new = sorted(["finding:fam", "finding:a1", "finding:u1"])  # class-search results outside Part C's pool
        random.Random("%s-q1-1" % lookup.JUDGE_SEED).shuffle(new)
        self.assertEqual(call["findings"], new)  # Part C's seed and shuffle, from the sorted list
        self.assertTrue(all(call["result"]["relevant"].values()))
        prompt = engine.prompts[0]
        self.assertTrue(prompt.startswith(lookup.JUDGE))
        self.assertIn("in the polymer ontology: PLA", prompt)
        for leak in ("finding:", "class search", "curated", "Oplus", "KF"):
            self.assertNotIn(leak, prompt)
        self.assertEqual(prompt.count("\n3. "), 1)
        self.assertEqual(sorted(p.read_bytes() for p in w.partc.rglob("*.json")), before)  # Part C untouched
        self.assertFalse((w.partc / "state.json").exists())
        self.assertTrue(list((w.out / "lookup/.oopc/loop/calls").glob("*.json")))  # the session's ledger, here
        again = Engine()
        self.assertEqual(self.run_judge(again)["sessions"], 0)  # nothing new to judge
        self.assertEqual(again.prompts, [])
        self.assertEqual(lookup.folder.__module__, lookup.__name__)  # Part C's folder is restored afterwards

    def test_a_session_limit_leaves_the_rest_for_later(self):
        w = self.world
        with mock.patch.object(lookup, "withheld", lambda: [QUESTION]):
            state = classes.judge(w.out, runner=self.guard(Engine()), partc=w.partc, root=w.root, labels={},
                                  limit_calls=0)
        self.assertEqual((state["sessions"], state["skipped"]), (0, 1))


class Fakes:
    """What late_finds reads of mining: a question's polymer ids and property, and its on-property test."""

    def context(self, answer):
        return {"ids": frozenset(answer["polymerIds"]), "property": answer["property"]}

    def on_property(self, text, ctx):
        return "strength" in (text or "") or "rate" in (text or "")

    def classes(self, text):
        return {"tensile-strength"} if "tensile" in text else set()


class LateAndLater(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def test_late_finds_returned_by_a_class_first_search_and_why_not(self):
        w, fakes = self.world, Fakes()
        answer = {"id": "loop/a", "materials": [], "polymerIds": [ASKED], "property": "tensile strength",
                  "question": "PLA tensile strength?"}
        misses = [{"id": "m-%d" % n, "kind": "late-find", "answer": "loop/a", "finding": f, "returnedAt": 2}
                  for n, f in enumerate(["finding:a1", "finding:cond", "finding:other", "finding:tg",
                                         "finding:unfiled", "finding:x"])] + [
            {"id": "m-u", "kind": "unresolved-name", "answer": "loop/a"}]
        rows, summary = classes.late_finds(w.idx, w.root, misses, [answer], fakes, miner=fakes)
        reasons = {r["finding"]: r["reason"] for r in rows}
        self.assertEqual(reasons, {"finding:a1": "returned", "finding:cond": "returned",  # via its source
                                   "finding:other": "finding outside the asked lineage",
                                   "finding:tg": "another property class",
                                   "finding:unfiled": "finding not filed under a polymer",
                                   "finding:x": "rejected or merged"})
        self.assertEqual(summary["lateFinds"], 6)
        self.assertEqual(summary["returned"]["first10+source"], 2)
        self.assertEqual(summary["returned"]["first10"], 1)
        self.assertEqual(summary["lenient"], 2)  # a1 and cond: in the lineage and on the property by mining's test
        self.assertEqual(summary["share"]["first10+source"], 2 / 6)

    def test_later_searches_covered_by_the_class_first_search(self):
        w = self.world
        w.part_c("q1", [("PLA tensile strength", "canonical", ["finding:r1"]),
                        ("PLA strength", "issued", ["finding:a1", "finding:cond"]),
                        ("PLA Tg", "issued", ["finding:tg"]), ("PLA nothing", "issued", [])],
                 {"finding:r1": True, "finding:a1": True, "finding:cond": True, "finding:tg": False})
        first = ["finding:r1", "finding:a1", "finding:cond"]
        rows = [{"id": "q1", "returned": {"curated/%s" % v: first for v in classes.VARIANTS}}]
        issued = {"q1": [["PLA tensile strength", 10], ["PLA strength", 10], ["PLA Tg", 10], ["PLA nothing", 10],
                         ["never replayed", 10]], "q2": []}
        got = classes.later_searches(rows, issued, w.partc)
        self.assertEqual((got["answers"], got["answersWithLater"], got["later"], got["empty"], got["notReplayed"]),
                         (1, 1, 3, 1, 1))
        self.assertEqual(got["byVariant"]["first10"], {"covered": 1, "relevantCovered": 1, "withRelevant": 1})


class Tables(unittest.TestCase):
    def test_answerable_from_saved_values_and_conflicts_beyond_the_tolerance(self):
        rows = [row("finding:t1", "tensile strength", "50", "MPa", ASKED),
                row("finding:t2", "tensile strength", "80", "MPa", ASKED, source="b"),
                row("finding:t3", "tensile strength", "6", "kJ/m²", OTHER),
                row("finding:g1", "glass transition temperature", "60", "°C", ASKED),
                row("finding:g2", "glass transition temperature", "68", "°C", ASKED),
                row("finding:g3", "glass transition temperature", "75", "°C", OTHER),
                row("finding:g4", "glass transition temperature", "60", "°C", OTHER)]
        w = World(self, rows)
        answer = lambda groups, wanted: classes.table_answerable(w.idx, w.root, {}, wanted, groups)  # noqa: E731
        self.assertEqual(answer([[ASKED]], ["tensile-strength"])["strict"], True)
        both = answer([[ASKED], [OTHER]], ["tensile-strength"])
        self.assertEqual((both["strict"], both["anyUnit"]), (False, False))  # OTHER's value is not in MPa
        tg = answer([[ASKED], [OTHER]], ["glass-transition-temperature"])
        self.assertEqual((tg["strict"], tg["anyUnit"], tg["exact"]), (True, True, True))
        self.assertEqual(answer([], ["tensile-strength"])["strict"], False)
        stated = classes.conflicts(w.idx, classes.TOLERANCE["stated"])
        loose = classes.conflicts(w.idx, classes.TOLERANCE["loose"])
        # pairs: ASKED tensile (50 vs 80 MPa, two sources), ASKED Tg (60 vs 68 °C: within 5 K), OTHER Tg (75 vs 60 °C,
        # one source)
        self.assertEqual((stated["pairs"], stated["conflicting"], stated["conflictingAcrossSources"]), (3, 2, 1))
        self.assertEqual(loose["conflicting"], 0)

    def test_the_prediction_verdicts(self):
        value = {"structure": {"all": {"classShare": 0.99, "normalizableShare": 0.47},
                               "materialProperty": {"normalizableShare": 0.56}},
                 "recall": {"curated/first10+source": {"grown": 0.86, "partc": 0.9}},
                 "lateFinds": {"summary": {"share": {"first10+source": 0.2}}}}
        got = classes.predictions(value)
        self.assertEqual({k: v["met"] for k, v in got.items()}, {"classShare": True, "numericNormalizableShare": False,
                                                                 "recall": True, "lateFindsAvoided": False})


if __name__ == "__main__":
    unittest.main()
