"""Part C's case selection (`refinement/cases.py`), offline, on the fixture world of `test_refinement_mine.py` with a
refined workspace (a trade name, a family link, a refiled finding, a source link, a property term) and one screen
shard: each case's rule on a question built for it, exclusive and seeded picks, C7 reusing C1-C3, shortfalls, the
selection file's format, and that the refined arm's items are never read. Run with today's code:

    OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_refinement_*.py"
"""
import random, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver  # noqa: E402
from refinement import cases, mine, overlay, pins, questions  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from test_refinement_mine import World, answer_of, reported, traced  # noqa: E402

QUESTIONS = {
    "H": [{"id": "h-c1", "question": "What stress relaxation is reported for Zytel?", "material": "Zytel",
           "property": "stress relaxation"},
          {"id": "h-c5", "question": "Report the haze of polystyrene (PS).", "material": "polystyrene (PS)",
           "property": "haze"}],
    "N": [{"id": "n-c3", "question": "How much water does polyamide absorb?", "material": "polyamide",
           "property": "water absorption"},
          {"id": "n-c6", "question": "What haze has been measured for polycarbonate (PC)?",
           "material": "polycarbonate (PC)", "property": "haze"}],
    "L": [{"id": "l-c8", "question": "What haze has PET film shown?", "material": "polyethylene terephthalate (PET)",
           "property": "haze"},
          {"id": "l-c2", "question": "What creep compliance has PA66 shown?", "material": "polyamide 66 (PA66)",
           "property": "creep"}],
}
EXPECTED = {"h-c1": {"C1", "C4"}, "h-c5": {"C5"}, "n-c3": {"C3"}, "n-c6": {"C6"}, "l-c8": {"C8"}, "l-c2": {"C2"}}


class CasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="oopc-refinement-cases-")
        folder = Path(cls.tmp.name)
        cls.world = world = World(folder)
        cls.base = driver.workspace(folder / "screen-ws", "B", releases=world.kf, store=world.kf)
        cls.refined = world.refined("refined", subjects={"finding:relax0000001-1": "wop-000004",
                                                         "finding:pethaze00001-1": "wop-000007"},
                                    links=[("doi:10.1000/creep", "supplement-of", "doi:10.1000/creep.s001")])
        db = sqlite3.connect(knowledge.database(cls.refined))
        db.execute("INSERT INTO property_terms VALUES (?, ?)",
                   ("creep-stress-relaxation", '["creep", "stress relaxation"]'))
        db.commit()
        db.close()
        cls.questions = {name: [dict(q, set=name) for q in items] for name, items in QUESTIONS.items()}
        for name, items in QUESTIONS.items():
            atomic_json(folder / "questions" / (name + ".json"), {"questions": [dict(q, set=name) for q in items]})
        # The screen's shard: B answered l-c2 with a store search that misses, then the web, reporting the saved creep
        # finding from the page it opened; Oplus's item is garbage.
        cls.shard = folder / "screen/s1"
        plan = {"name": "screen-s1", "questions": cls.questions["L"][1:], "checker": "codex", "arms": [
            {"name": "B", "kind": "researcher", "web": True, "root": str(cls.base)},
            {"name": "Oplus", "kind": "researcher", "web": True, "root": str(cls.refined)}]}
        atomic_json(cls.shard / "plan.json", plan)
        run = traced(cls.base, [("Zytel deformation", 10)])
        creep = reported("Polyamide 66 bars showed a creep compliance of 1.2 per GPa after 100 h.", "Polyamide 66 bars",
                         "creep compliance", "10.1000/creep")
        atomic_json(cls.shard / "items/0000-B.json", {"question": "l-c2", "arm": "B", "answer": {
            "answer": answer_of("PA66 creep.", findings=[creep]), "runId": run, "webActions": [
                {"action": "search", "outcome": "searched", "query": "zytel creep"},
                {"action": "open", "outcome": "opened", "url": "https://doi.org/10.1000/creep"}]}})
        (cls.shard / "items/0000-Oplus.json").write_text("the refined arm's outcome is never read")
        cls.miner = mine.Miner(cls.base, property_map=folder / "no-map.json")
        cls.frozen = mock.patch.object(pins, "frozen", lambda: "test-commit")  # the refined root is searched
        cls.frozen.start()

    @classmethod
    def tearDownClass(cls):
        cls.frozen.stop()
        cls.tmp.cleanup()

    def answers(self):
        real = mine.read_json

        def guarded(path):
            if "Oplus" in str(path):
                raise AssertionError("read the refined arm's item %s" % path)
            return real(path)
        with self.world.patches(), mock.patch.object(mine, "read_json", guarded):
            return cases.screen_answers([self.shard])

    def select(self, out, **options):
        with self.world.patches():
            return cases.select(self.questions, self.base, self.refined, answers=self.answers(), out=out,
                                miner=self.miner, **options)

    def test_reads_only_the_baseline_arm(self):
        answers = self.answers()
        self.assertEqual(list(answers), ["l-c2"])
        self.assertEqual([s["type"] for s in answers["l-c2"]["steps"]], ["store", "web-search", "open"])
        self.assertEqual(cases.withheld_questions(Path(self.tmp.name) / "questions")["N"][0]["set"], "N")

    def test_each_rule_on_the_question_built_for_it(self):
        answers = self.answers()
        for name, items in self.questions.items():
            for question in items:
                row = cases.evidence(self.miner, question, self.base, self.refined, answers.get(question["id"]))
                found = {c for c in cases.DRAWN if row[c]}
                self.assertEqual(found, EXPECTED[question["id"]], question["id"])
        c1 = cases.evidence(self.miner, self.questions["H"][0], self.base, self.refined)
        self.assertEqual(c1["newRelevant"], ["finding:creep0000001-1"])
        c3 = cases.evidence(self.miner, self.questions["N"][0], self.base, self.refined)
        self.assertEqual(c3["familyFindings"], ["finding:pa6water0001-1"])
        c8 = cases.evidence(self.miner, self.questions["L"][0], self.base, self.refined)
        self.assertEqual(c8["risks"], [{"query": "polyethylene terephthalate (PET) haze",
                                        "left": "finding:pethaze00001-1"}])
        c2 = cases.evidence(self.miner, self.questions["L"][1], self.base, self.refined, answers["l-c2"])
        self.assertEqual(c2["linkedHops"][0]["target"], ["doi:10.1000/creep"])

    def test_with_a_group_builder_attribution_decides(self):
        answers = self.answers()
        source_link = lambda groups: self.refined if "source-link" in groups else self.base  # noqa: E731
        row = cases.evidence(self.miner, self.questions["L"][1], self.base, self.refined, answers["l-c2"], source_link)
        self.assertTrue(row["C2"])
        name = lambda groups: self.refined if "name/family" in groups else self.base  # noqa: E731
        row = cases.evidence(self.miner, self.questions["L"][1], self.base, self.refined, answers["l-c2"], name)
        self.assertFalse(row["C2"])  # reachable, but by the name, not a link
        row = cases.evidence(self.miner, self.questions["H"][0], self.base, self.refined, None, name)
        self.assertFalse(row["C4"])  # the property-term group alone (the baseline here) does not reach it
        self.assertTrue(row["C1"])

    def test_selection_is_exclusive_seeded_and_written_in_the_runs_format(self):
        out = Path(self.tmp.name) / "cases"
        value = self.select(out)
        written = read_json(out / "selection.json")
        self.assertEqual(written["cases"], value["cases"])
        ids = {c: [p["id"] for p in picks] for c, picks in written["cases"].items()}
        self.assertEqual(ids, {"C1": ["h-c1"], "C2": ["l-c2"], "C3": ["n-c3"], "C4": [], "C5": ["h-c5"],
                               "C6": ["n-c6"], "C7": ["h-c1", "l-c2", "n-c3"], "C8": ["l-c8"]})
        self.assertEqual(written["qualifying"]["C4"], 1)  # h-c1 qualified, but C1 took it first
        self.assertEqual(written["shortfalls"], {"C1": 2, "C2": 2, "C3": 2, "C4": 3, "C5": 2, "C6": 2, "C8": 2})
        pick = written["cases"]["C1"][0]
        self.assertEqual((pick["set"], pick["question"]), ("H", "What stress relaxation is reported for Zytel?"))
        self.assertEqual(pick["reason"]["newRelevant"], ["finding:creep0000001-1"])
        self.assertEqual(written["cases"]["C7"][1]["reuses"], "C2")
        self.assertEqual(written["seed"], pins.SELECTION_SEED)
        again = self.select(Path(self.tmp.name) / "again")
        self.assertEqual(again["cases"], value["cases"])

    def test_pairs_for_the_cases_short_of_three_are_what_write_c_reads(self):
        out = Path(self.tmp.name) / "pairs"
        value = self.select(out)
        offered = read_json(out / "pairs.json")
        self.assertEqual(set(offered["cases"]), set(value["shortfalls"]) - {"C7"})
        self.assertEqual(value["pairs"], {c: len(p) for c, p in offered["cases"].items()})
        for case, entries in offered["cases"].items():
            self.assertLessEqual(len(entries), value["shortfalls"][case] + questions.SPARE)
            for entry in entries:
                self.assertLessEqual({"material", "property", "polymerIds", "replay"}, set(entry))
                question = {"id": "pair", "set": "C", "question": "%s %s" % (entry["material"], entry["property"]),
                            "materials": [entry["material"]], "property": entry["property"],
                            "polymerIds": entry["polymerIds"]}
                with self.world.patches():  # the pair qualifies by its case's own rule
                    self.assertTrue(cases.evidence(self.miner, question, self.base, self.refined)[case], entry)
        c5 = {(p["material"], p["property"]) for p in offered["cases"]["C5"]}
        self.assertEqual(c5, {("Polystyrene", "yellowness index"), ("Polystyrene", "tensile strength")})  # not haze:
        # h-c5 asks polystyrene's haze already
        self.assertEqual(offered["cases"]["C2"], [])  # the link reaches nothing the canonical calls do not already
        plan = questions.case_plan(read_json(out / "selection.json"), offered)  # write-C takes them as they are
        self.assertEqual(plan["C5"]["needed"], 2)
        self.assertEqual([p["material"] for p in plan["C5"]["pairs"]], [p["material"] for p in offered["cases"]["C5"]])

    def test_the_command_runs_on_the_code_under_test_with_the_group_builder(self):
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("not the tag")), self.assertRaises(SystemExit):
            self.select(Path(self.tmp.name) / "refused")
        self.assertFalse((Path(self.tmp.name) / "refused/selection.json").exists())
        seen = {}

        def select(questions, base, refined, **options):
            seen.update(options, refined=refined)
            return {"qualifying": {}, "shortfalls": {}, "cases": {}}
        with mock.patch.object(cases, "select", select), mock.patch.object(mine, "base_root", lambda out: self.base), \
                mock.patch.object(cases, "withheld_questions", lambda: self.questions), \
                mock.patch("builtins.print"):
            cases.main(["select"])
        self.assertIs(seen["build"].__wrapped__, overlay.root_for)  # C2 and C4 are decided edit group by edit group
        self.assertEqual(seen["refined"], pins.store("KF-refined"))

    def test_seeded_shuffle_picks_three_of_many(self):
        more = {name: list(items) for name, items in self.questions.items()}
        extra = [{"id": "h-c5-%d" % n, "set": "H", "question": "Report haze number %d of polystyrene (PS)." % n,
                  "material": "polystyrene (PS)", "property": "haze"} for n in range(4)]
        more["H"] = more["H"] + extra
        with self.world.patches():
            value = cases.select(more, self.base, self.refined, answers=self.answers(),
                                 out=Path(self.tmp.name) / "many", miner=self.miner)
        order = sorted([("H", q["id"]) for q in [self.questions["H"][1]] + extra])
        random.Random("%s:C5" % pins.SELECTION_SEED).shuffle(order)
        self.assertEqual([p["id"] for p in value["cases"]["C5"]], [key[1] for key in order[:3]])
        self.assertNotIn("C5", value["shortfalls"])


if __name__ == "__main__":
    unittest.main()
