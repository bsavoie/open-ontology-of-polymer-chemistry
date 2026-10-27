"""Part C's offline lookup measure: the three measures on a hand-made example; what a search returns (every finding
of the call, same-source ones included: "the first ten" are a call at the default limit); and, in
test_refinement_run's world after a scripted screen, the canonical queries and the issued calls as recorded (query and
limit) searched as search_knowledge searches, the pool (everything returned, and the same queries at limit 25), the
judge blind (findings shuffled from a sorted pool, numbered, no ids, no arm), a grown pool judged only for its new
findings, failures retried, and the report's numbers for a trade name and a family link."""
import random, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests folder, for test_refinement_run's world
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
from test_refinement_run import SETS, Engine, World  # noqa: E402
from refinement import lookup, mine, pins, run  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.util import read_json  # noqa: E402


def search(q, limit, origins, b, o, pooled=None):
    return {"q": q, "limit": limit, "origins": origins, "returned": {"B": b, "Oplus": o},
            "pooled": pooled or {"B": b, "Oplus": o}}


class Measures(unittest.TestCase):
    def test_recall_lost_gained_and_wrong_polymer_on_a_hand_made_example(self):
        b = ["r1", "x1", "r2", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "r3"]  # an 11th, same-source result counts
        o = ["r1", "r5", "x1", "y1"]  # O+ loses r2 and r3 and gains r5
        wide = {"B": b + ["r6"], "Oplus": o}  # r6: only in the limit-25 call, so in the pool and never returned
        stored = {"queries": [search("PLA tensile strength", 10, ["canonical"], b, o, wide),
                              search("polylactide modulus", 25, ["issued"], ["r2", "r4"], ["r2"])]}
        relevant = {i: i.startswith("r") for i in lookup.pool(stored)}
        subjects = dict({i: "wop-000001" for i in relevant}, x1="wop-000002", y1="wop-000003", x2="")
        got = lookup.measures(stored, relevant, subjects, {"wop-000001", "wop-000009"})
        self.assertEqual((got["pool"], got["relevant"], got["queries"]), (15, 6, 2))
        canonical = got["canonical"]
        self.assertEqual((canonical["B"]["relevantFound"], canonical["B"]["recall"]), (3, 0.5))
        self.assertEqual((canonical["Oplus"]["relevantFound"], canonical["Oplus"]["recall"]), (2, 2 / 6))
        self.assertEqual((canonical["lost"], canonical["gained"]), (["r2", "r3"], ["r5"]))
        self.assertEqual(canonical["B"]["wrongPolymer"], ["x1"])  # x2 has no subject: unfiled, not wrong
        self.assertEqual((canonical["B"]["unfiled"], canonical["Oplus"]["wrongPolymer"]), (1, ["x1", "y1"]))
        self.assertEqual(canonical["B"]["returned"], 11)
        issued = got["issued"]
        self.assertEqual((issued["B"]["recall"], issued["Oplus"]["recall"], issued["lost"]), (2 / 6, 1 / 6, ["r4"]))
        everything = got["all"]
        self.assertEqual((everything["B"]["recall"], everything["Oplus"]["recall"]), (4 / 6, 3 / 6))
        self.assertEqual((everything["lost"], everything["gained"]), (["r2", "r3", "r4"], ["r5"]))
        unknown = lookup.measures(stored, relevant, subjects, None)  # the refined graph knows no asked polymer
        self.assertIsNone(unknown["all"]["B"]["wrongPolymer"])
        rows = [dict(got, set="L", group="name", stratum="tertile-1"), dict(unknown, set="L", group="name")]
        summed = lookup.aggregate(rows)["all"]
        self.assertEqual((summed["lost"], summed["B"]["relevantFound"], summed["lostShare"]), (6, 8, 6 / 8))
        self.assertEqual((summed["B"]["wrongPolymer"], summed["B"]["polymerKnown"]), (len(everything["B"]["wrongPolymer"]),
                                                                                       1))
        self.assertEqual(summed["B"]["pooledRecall"], 8 / 12)

    def test_a_search_returns_every_finding_of_the_call_same_source_ones_included(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        with knowledge.connect(root) as db:
            for n in range(1, 12):  # ten full matches, and an eleventh that matches less but shares p1's source
                statement = ("PCL film %d had a tensile strength of %d MPa." % (n, n) if n <= 10
                             else "PCL film 1 had an elongation at break of 300%.")
                knowledge._insert_finding(db, "finding:p%d" % n, "q", "research", knowledge.clean_finding({
                    "statement": statement, "material": "PCL film", "property": "tensile strength", "value": "1",
                    "unit": "MPa", "conditions": "", "subject": "", "sourceTitle": "Paper",
                    "sourceUrl": "https://example.org/%d" % (1 if n == 11 else n), "sourceDoi": "",
                    "locator": "Table 1", "excerpt": "1", "needsReview": False, "reviewFlag": ""}),
                    status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-10-10T00:00:00+00:00")
        query = "PCL tensile strength"
        found = lookup.returned(root, query)
        self.assertEqual((len(found), found[-1]), (11, "finding:p11"))  # the same-source finding after the ten
        result = knowledge.search(root, query, 10, compact=True)
        self.assertEqual(found, [f["id"] for g in mine.GROUPED for f in result[g]])
        self.assertIn("finding:p11", lookup.returned(root, query, 25))


class Lookup(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def screen(self):
        run.prepare_screen()
        (pins.BASE / "pilot").mkdir(parents=True, exist_ok=True)
        (pins.BASE / "pilot/CHECKED").write_text("")
        self.assertEqual(run.run_screen(1, runner=self.world.guard(Engine()))["status"], "completed")

    def judges(self, engine):
        return [c for c in engine.calls if c[0] == "judge"]

    def test_the_pool_is_judged_blind_and_the_report_measures_the_name_and_the_family_link(self):
        self.screen()
        engine = Engine()
        state = lookup.judge(runner=self.world.guard(engine))
        self.assertEqual((state["status"], state["judged"], state["waiting"]), ("completed", 6, 0))
        self.assertEqual(sorted(c[1] for c in self.judges(engine)), sorted(q["id"] for q in run.screen_order()))
        stored = read_json(pins.folder("lookup") / "searches/l-name.json")
        self.assertEqual([(s["q"], s["limit"], s["origins"]) for s in stored["queries"]],
                         [("Ingeo 4043D tensile strength", 10, ["canonical", "issued"]),
                          ("polylactide tensile strength", 10, ["issued"])])
        made = lookup.roots()
        self.assertEqual(stored["queries"][0]["returned"]["B"], lookup.returned(made["B"], "Ingeo 4043D tensile strength"))
        self.assertEqual(stored["queries"][0]["pooled"]["B"],
                         lookup.returned(made["B"], "Ingeo 4043D tensile strength", 25))
        self.assertEqual(set(stored["queries"][0]["returned"]["Oplus"]), {"finding:pla-1", "finding:ingeo-1"})
        self.assertEqual(len(stored["queries"][0]["returned"]["B"]), 5)  # the seed does not know Ingeo: no filter
        self.assertEqual(stored["queries"][1]["returned"]["B"], ["finding:pla-1"])  # unfiled under the seed
        ldpe = read_json(pins.folder("lookup") / "searches/n-ldpe.json")
        self.assertEqual([(s["q"], s["limit"]) for s in ldpe["queries"]],
                         [("LDPE tensile strength", 10), ("PCL tensile strength", 25)])  # the call as recorded
        call = read_json(pins.folder("lookup") / "judge/l-name/call-1.json")
        pooled = sorted(lookup.pool(stored))
        random.Random("%s-l-name-1" % lookup.JUDGE_SEED).shuffle(pooled)
        self.assertEqual(call["findings"], pooled)  # from the sorted pool: the order owes nothing to the arms
        prompt = next(p for p in engine.prompts if "Ingeo 4043D sheet?" in p)
        for leak in ("finding:", "Oplus", "O+", "baseline", "refined", "seed", " arm", "KF"):
            self.assertNotIn(leak, prompt)
        self.assertEqual(prompt.count("\n%d. " % len(pooled)), 1)
        self.assertIn("in the polymer ontology: Polylactide", prompt)
        report = lookup.report()
        rows = {r["id"]: r for r in read_json(pins.folder("lookup") / "rows.json")}
        name = rows["l-name"]
        self.assertEqual((name["relevant"], name["canonical"]["B"]["recall"], name["canonical"]["Oplus"]["recall"]),
                         (2, 1.0, 1.0))
        self.assertEqual(name["canonical"]["B"]["wrongPolymer"], ["finding:hdpe-1", "finding:ldpe-1", "finding:pcl-1"])
        self.assertEqual(name["canonical"]["Oplus"]["wrongPolymer"], [])
        # B's issued queries include the canonical one; its second, by the seed's name, misses the unfiled finding
        self.assertEqual((name["issued"]["queries"], name["issued"]["B"]["recall"], name["issued"]["gained"]),
                         (2, 1.0, ["finding:ingeo-1"]))
        family = rows["h-family"]
        self.assertEqual((family["canonical"]["B"]["recall"], family["canonical"]["Oplus"]["recall"]), (0.5, 1.0))
        self.assertEqual((family["all"]["gained"], family["all"]["lost"]), (["finding:hdpe-1"], []))
        self.assertEqual(report["judged"], 6)
        self.assertEqual(report["groups"]["L"]["all"]["gained"], 1)
        self.assertEqual(set(report["groups"]), {"all", "H", "H/near", "H/mid", "N", "N/asked-pair", "N/asked-polymer",
                                                 "L", "L/name", "L/value"})
        self.assertTrue((pins.folder("lookup") / "report.md").read_text().startswith("# Lookup"))

    def test_before_the_screen_questions_wait_unless_canonical_only_and_a_grown_pool_judges_only_what_is_new(self):
        engine = Engine()
        state = lookup.judge(runner=self.world.guard(engine))
        self.assertEqual((state["waiting"], self.judges(engine)), (6, []))
        state = lookup.judge(runner=self.world.guard(engine), canonical_only=True)
        self.assertEqual((state["judged"], len(self.judges(engine))), (6, 6))
        self.screen()
        again = Engine()
        state = lookup.judge(runner=self.world.guard(again))
        self.assertEqual([c[1] for c in self.judges(again)], ["n-ldpe"])  # its issued query found a new finding
        second = read_json(pins.folder("lookup") / "judge/n-ldpe/call-2.json")
        self.assertEqual(second["findings"], ["finding:pcl-1"])
        self.assertTrue(read_json(pins.folder("lookup") / "searches/h-pcl.json")["issuedRead"])
        self.assertEqual(len(lookup.rows()), 6)

    def test_a_judge_that_does_not_number_each_finding_once_is_tried_again_then_failed_and_redone_on_a_rerun(self):
        class Sloppy(Engine):
            bad = 2

            def __call__(self, engine, prompt, schema, **options):
                result = super().__call__(engine, prompt, schema, **options)
                if schema is lookup.JUDGE_SCHEMA and self.bad:
                    self.bad -= 1
                    result["answer"]["judgements"] = result["answer"]["judgements"][1:]
                return result
        engine = Sloppy()
        state = lookup.judge(runner=self.world.guard(engine), canonical_only=True)
        self.assertEqual((state["judged"], state["failed"]), (5, 1))
        first = sorted((pins.folder("lookup") / "judge").glob("*/call-1.json"))
        failed = [read_json(p) for p in first if "error" in read_json(p)["result"]]
        self.assertEqual([a["reason"] for a in failed[0]["attempts"]], ["invalid-output", "invalid-output"])
        state = lookup.judge(runner=self.world.guard(Engine()), canonical_only=True)
        self.assertEqual((state["judged"], state["failed"]), (1, 0))
        self.assertTrue(lookup.verdicts(failed[0]["question"]))

    def test_quota_stops_the_judge_and_nothing_runs_unless_the_code_is_the_tag(self):
        engine = Engine()
        state = lookup.judge(runner=self.world.guard(engine, quota=1), canonical_only=True)
        self.assertEqual((state["status"], state["stopReason"], engine.calls), ("stopped", "quota", []))
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("Tag study-freeze-3 does not exist yet")):
            with self.assertRaisesRegex(SystemExit, "study-freeze-3"):
                lookup.judge(runner=self.world.guard(engine), canonical_only=True)
        self.assertEqual(engine.calls, [])


def step(i, kind, **fields):
    return dict({"i": i, "type": kind}, **({"limit": None, "status": "ok"} if kind == "store" else {}), **fields)


def screened(question, steps, reported=()):
    """A screen B answer as mining normalizes one (`cases.screen_answers`)."""
    return {"id": "screen/s1/%s-B" % question["id"], "origin": "screen", "question": question["question"],
            "questionId": question["id"], "materials": question["materials"], "property": question["property"],
            "kind": question["kind"], "steps": steps, "cited": {"findings": [], "notes": [], "urls": []},
            "reported": list(reported), "sources": []}


class HopsRemoved(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def test_bs_held_unreached_hops_split_by_the_refined_search_and_attributed_to_edit_groups(self):
        name, pcl = SETS["L"][0], SETS["H"][1]
        ingeo = {"statement": "Ingeo 4043D sheet had a tensile strength of 55 MPa.", "material": "Ingeo 4043D",
                 "property": "tensile strength", "value": "1", "unit": "MPa", "sourceTitle": "",
                 "sourceUrl": "https://example.org/10.1/b", "sourceDoi": "10.1/b"}
        # B searched PLA by the seed's name (the unfiled Ingeo finding is not returned), opened the Ingeo paper and
        # reported its value, then searched by the trade name, which returned the Ingeo finding as new.
        answers = {"l-name": screened(name, [
            step(0, "store", q="polylactide tensile strength"), step(1, "web-search", query="ingeo 4043d tensile"),
            step(2, "open", url="https://example.org/10.1/b", outcome="opened"),
            step(3, "store", q="Ingeo tensile strength")], [ingeo]),
            "h-pcl": screened(pcl, [step(0, "store", q="PCL tensile strength")])}
        made = lookup.roots()
        build = lambda groups: made["Oplus"] if "name/family" in groups else made["B"]  # noqa: E731
        with mock.patch.object(lookup, "screen_answers", lambda: answers):
            report = lookup.report(build=build)
        rows = {r["id"]: r for r in read_json(pins.folder("lookup") / "hops.json")}
        self.assertEqual(set(rows), {"l-name", "h-pcl"})  # the questions B answered
        got = rows["l-name"]
        self.assertEqual((got["web"], got["store"]), ({"heldUnreached": 1, "reachable": 1},
                                                       {"heldUnreached": 1, "reachable": 1}))
        self.assertEqual(got["byGroup"], {"name/family": 2})  # Ingeo's trade name and its filing, not a link or term
        self.assertEqual([h["refined"] for h in got["heldUnreached"]], ["reachable", "reachable"])
        self.assertEqual((rows["h-pcl"]["web"], rows["h-pcl"]["hops"]), ({"heldUnreached": 0, "reachable": 0}, 0))
        totals = report["hopsRemoved"]
        self.assertEqual((totals["L"]["all"], totals["H"]["all"]["heldUnreached"]),
                         ({"heldUnreached": 2, "reachable": 2, "share": 1.0}, 0))
        self.assertEqual(totals["all"]["byGroup"], {"name/family": 2})
        self.assertIn("L/name", totals)
        self.assertIn("## Hops removed", (pins.folder("lookup") / "report.md").read_text())
        other = dict(ingeo, statement="Ingeo 4043D sheet had an elongation at break of 6%.")  # not what was saved
        unsaved = {r["id"]: r for r in lookup.hop_rows(made=made, build=build, answers=dict(
            answers, **{"l-name": dict(answers["l-name"], reported=[other])}))}["l-name"]
        self.assertEqual((unsaved["web"]["heldUnreached"], unsaved["byClass"]["web:unsaved-detail"]), (0, 1))
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("not the tag")), self.assertRaises(SystemExit):
            lookup.hop_rows(made=made, build=build, answers=answers)


if __name__ == "__main__":
    unittest.main()
