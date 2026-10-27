"""Part C's analysis (refinement/analysis.py) on synthetic run folders: the build's counts by type and the in-sample
effects; the screen's per-arm counts, Part A's paired estimators, the attribution (web calls + 1 and tokens, ties
apart) and Figure panel b from `lookup.py report`'s hop rows; the lookup measures read from its report; the case
studies with their replicate spread, C7 as C1's questions on K0 and C2 and C3 without a qualifying edit; each
prediction's verdict, pending while its records are missing; the refusals to write a local path or into the run
folder; and, in test_refinement_run's world (a real seed, release O and the stores), wrong-polymer citations read from
each arm's own store copy and graph, with nothing in the workspace changed."""
import hashlib, json, math, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests folder, for test_refinement_run's world
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
from refinement import analysis, lookup, pins  # noqa: E402

ARMS = ("B0", "B", "Oplus")


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def item(tokens, web, cites=(), contradicted=0, complete=True, result=True, passed=True, lookups=2, seconds=10.0):
    text = "A value. " + " ".join("`%s`" % c for c in cites)
    return {"answer": {"answer": {"answer": text, "citations": list(cites[:1])}, "runId": "run-1",
                       "metrics": {"newTokens": tokens, "webCalls": web, "knowledgeLookups": lookups,
                                   "seconds": seconds}},
            "check": {"verdict": "pass" if passed else "fail", "measures": {
                "contradicted": contradicted, "complete": complete, "resultGiven": result, "pass": passed,
                "accessUncertain": 0, "statements": 4}}}


def q(identifier, name, stratum, group="property", **extra):
    return dict({"id": identifier, "set": name, "stratum": stratum, "group": group, "kind": group,
                 "question": "What is the tensile strength of %s?" % identifier, "materials": ["PLA"],
                 "polymerIds": ["wop-000001"], "property": "tensile strength"}, **extra)


# question: (B0, B, O+) as (tokens, web calls)
COSTS = {"h1": ((100e3, 6), (50e3, 2), (50e3, 2)), "h2": ((100e3, 6), (50e3, 2), (50e3, 2)),
         "h3": ((100e3, 4), (100e3, 4), (80e3, 1)),  # the ontology effect is the larger
         "n1": ((100e3, 6), (50e3, 2), (50e3, 2)), "n2": ((100e3, 6), (50e3, 2), (50e3, 2)),
         "n3": ((40e3, 0), (40e3, 0), (40e3, 0)),  # no effect either way: a tie
         "l1": ((100e3, 6), (50e3, 2), (50e3, 2)), "l2": ((100e3, 6), (50e3, 2), (50e3, 2)),
         "l3": ((100e3, 6), (50e3, 2), (50e3, 2))}
QUESTIONS = [q("h1", "H", "near"), q("h2", "H", "near"), q("h3", "H", "far"), q("n1", "N", "asked-pair"),
             q("n2", "N", "asked-pair"), q("n3", "N", "asked-pair"), q("l1", "L", "tertile-1", "name"),
             q("l2", "L", "tertile-1", "family", familyInSeed=False), q("l3", "L", "tertile-2", "value")]
SUBJECTS = {"finding:kf-1": "wop-000001", "finding:kf-2": "wop-000002", "finding:kf-0": "",
            "finding:kf-3": "wop-000003"}
HOP_ROWS = [  # B's hops as lookup.hop_rows writes them: 20 web hops, 10 limited by accumulation, 2 held-unreached
    {"id": "h1", "set": "H", "stratum": "near", "group": "property", "byClass": {
        "web:new-knowledge": 2, "web:failed": 2, "web:held-unreached": 1, "store:held-unreached": 1},
     "byGroup": {"name/family": 1}, "web": {"heldUnreached": 1, "reachable": 1},
     "store": {"heldUnreached": 1, "reachable": 0}},
    {"id": "h3", "set": "H", "stratum": "far", "group": "property", "byClass": {
        "web:new-knowledge": 2, "web:unsaved-detail": 2, "web:failed": 2, "web:repeat": 1},
     "byGroup": {}, "web": {"heldUnreached": 0, "reachable": 0}, "store": {"heldUnreached": 0, "reachable": 0}},
    {"id": "n1", "set": "N", "stratum": "asked-pair", "group": "property", "byClass": {
        "web:new-knowledge": 2, "web:unsaved-detail": 2, "web:failed": 2, "web:held-unreached": 1,
        "web:search-only": 1}, "byGroup": {}, "web": {"heldUnreached": 1, "reachable": 0},
     "store": {"heldUnreached": 0, "reachable": 0}}] + [
    {"id": i, "set": i[0].upper(), "stratum": s, "group": g, "byClass": {}, "byGroup": {},
     "web": {"heldUnreached": 0, "reachable": 0}, "store": {"heldUnreached": 0, "reachable": 0}}
    for i, s, g in (("h2", "near", "property"), ("n2", "asked-pair", "property"), ("n3", "asked-pair", "property"),
                    ("l1", "tertile-1", "name"), ("l2", "tertile-1", "family"), ("l3", "tertile-2", "value"))]


class Stub(analysis.Polymers):
    """Each arm's store holds SUBJECTS (K0 only kf-1); every asked lineage is PLA's."""

    def subject(self, root, ids):
        held = SUBJECTS if Path(root).name != "B0" else {"finding:kf-1": "wop-000001"}
        return {i: held[i] for i in ids if i in held}

    def lineage(self, question, root):
        return {"wop-000001"}


def screen_folder(base):
    """A screen of one shard: COSTS, B and O+ citing saved findings, a few contradicted and incomplete answers."""
    folder = base / "screen/s1"
    write(base / "screen/experiment.json", {"folders": ["s1"], "questions": len(QUESTIONS), "arms": list(ARMS)})
    write(folder / "plan.json", {"arms": [{"name": a, "root": "/elsewhere/%s" % a} for a in ARMS],
                                 "questions": QUESTIONS})
    write(folder / "state.json", {"status": "completed", "failedItems": 0})
    write(folder / "pins.json", {"harness": {"revision": "a" * 40, "clean": True}, "tag": "study-freeze-3"})
    for index, question in enumerate(QUESTIONS):
        for arm, (tokens, web) in zip(ARMS, COSTS[question["id"]]):
            cites = () if arm == "B0" else ("finding:kf-1",)
            if arm == "B" and question["id"] == "h2":
                cites = ("finding:kf-1", "finding:kf-2", "finding:kf-0", "finding:gone")
            if question["id"] == "l2" and arm != "B0":
                cites = ("finding:kf-3",)  # a family member: wrong under the rule, in a family the graph lacks
            row = item(tokens, web, cites, contradicted=int((arm, question["id"]) in (("Oplus", "h1"), ("B", "n1"))),
                       complete=(arm, question["id"]) != ("Oplus", "n2"))
            write(folder / "items" / ("%04d-%s.json" % (index, arm)), row)


def build_folder(base):
    write(base / "propose/curator/batch-01.json", {
        "curator": {"answer": {"edits": [{"type": "name"}, {"type": "name"}, {"type": "annotation"},
                                         {"type": "property-term"}]}},
        "edits": [{"index": 1, "type": "name"}, {"index": 3, "type": "annotation"}, {"index": 4, "type": "property-term"}],
        "refused": [{"index": 2, "type": "name", "problems": ["already names it"]}]})
    write(base / "propose/review/batch-01.json", {"review": {"answer": {"verdicts": [
        {"id": "p01", "verdict": "approved"}, {"id": "p03", "verdict": "approved"},
        {"id": "p04", "verdict": "rejected"}]}}})
    write(base / "propose/curator/batch-02.json", {"curator": {"answer": {"edits": []}}, "edits": [], "refused": []})
    write(base / "overlay/edits.json", {"edits": {
        "e-001": {"type": "name", "edit": {"field": "tradeNames", "name": "Ingeo", "polymer": "wop-000001"}},
        "e-002": {"type": "annotation", "edit": {"finding": "finding:kf-0", "subject": "wop-000001"}}}})
    write(base / "mine/effects.json", {"complete": True, "dropped": ["e-002"], "edits": {
        "e-001": {"type": "name", "missesFixed": 3, "hopsReachable": 1, "resultsLost": 0,
                  "byKind": {"unresolved-name": 3}, "byHop": {"web": 1}},
        "e-002": {"type": "annotation", "missesFixed": 0, "hopsReachable": 0, "resultsLost": 2}},
        "groups": {"all": {"missesFixed": 3, "byKind": {"unresolved-name": 3}, "hopsReachable": 1,
                           "byHop": {"web": 1}, "resultsLost": 0, "root": "/Users/somebody/root"}}})
    write(base / "mine/summary.json", {"pool": {"answers": 7}, "misses": {"byKind": {"late-find": 2}},
                                       "hops": {"web": {"byClass": {"failed": 3}}}, "propertyMap": "/Users/x/map"})


def lookup_folder(base, done=True):
    """`lookup.py report`'s files from hand-made searches: equal recall on H and N, a gain on L, nothing lost."""
    def stored(b, o):
        return {"queries": [{"q": "PLA tensile strength", "limit": 10, "origins": ["canonical"],
                             "returned": {"B": b, "Oplus": o}, "pooled": {"B": b, "Oplus": o}}]}
    rows = []
    for question in QUESTIONS:
        b, o = (["r1", "x1"], ["r1", "r2", "x1"]) if question["set"] == "L" else (["r1", "r2"], ["r1", "r2"])
        found = stored(b, o)
        relevant = {i: i.startswith("r") for i in lookup.pool(found)}
        rows.append(dict({k: question.get(k) for k in ("id", "set", "kind", "group", "stratum")}, issuedRead=True,
                         **lookup.measures(found, relevant, {i: "wop-000001" for i in relevant}, {"wop-000001"})))
    report = {"at": "2026-10-22T18:00:00+00:00", "questions": len(QUESTIONS), "judged": len(rows), "limit": 10,
              "poolLimit": 25, "groups": {n: lookup.aggregate(c) for n, c in lookup.subsets(rows).items()},
              "hopsRemoved": {"all": {"questions": 9}}}
    write(base / "lookup/report.json", report)
    write(base / "lookup/rows.json", rows)
    write(base / "lookup/hops.json", HOP_ROWS)
    if done:
        (base / "lookup/judge.done").write_text("2026-10-22T17:59:00Z exit 0\n")


CASE_QUESTIONS = [dict(q("c1a", "C", "written", "C1"), cases=["C1", "C7"], case="C1"),
                  dict(q("c1b", "C", "written", "C1"), cases=["C1"], case="C1"),
                  dict(q("c5a", "H", "near"), cases=["C5"]), dict(q("c6a", "H", "far"), cases=["C6"])]


def cases_folder(base, replicates=(1, 2), missing=False):
    """Two replicates on B0, O0, B and O+: C1 halves the tokens on O+ in r1 and saves a fifth in r2; on K0 nothing
    changes; C5 and C6 change nothing."""
    write(base / "cases/experiment.json", {"folders": ["r%d" % r for r in replicates], "questions": 4,
                                           "arms": list(pins.CASE_ARMS), "replicates": len(replicates),
                                           "byCase": {"C1": ["c1a", "c1b"], "C5": ["c5a"], "C6": ["c6a"],
                                                      "C7": ["c1a"]}})
    write(base / "cases/selection.json", {"qualifying": {"C1": 0, "C2": 0, "C3": 0, "C5": 9, "C6": 4},
                                          "shortfalls": {"C1": 3, "C2": 3, "C3": 3}})
    for r in replicates:
        folder = base / "cases" / ("r%d" % r)
        write(folder / "plan.json", {"arms": [{"name": a} for a in pins.CASE_ARMS], "questions": CASE_QUESTIONS})
        write(folder / "state.json", {"status": "completed" if not missing else "running"})
        for index, question in enumerate(CASE_QUESTIONS):
            for arm in pins.CASE_ARMS:
                if missing and r == replicates[-1] and arm == "Oplus":
                    continue
                c1 = question["case"] if "case" in question else None
                tokens, web, cites = {"B0": (60e3, 6, ()), "O0": (60e3, 6, ()), "B": (100e3, 4, ()),
                                      "Oplus": ((50e3 if r == 1 else 80e3), 2, ("finding:kf-1",))}[arm] if c1 else \
                    (70e3, 3, ("finding:kf-1",) if arm in ("B", "Oplus") else ())
                write(folder / "items" / ("%04d-%s.json" % (index, arm)), item(tokens, web, cites))


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.top = Path(tempfile.mkdtemp(prefix="oopc-refinement-analysis-"))
        self.addCleanup(shutil.rmtree, self.top, True)
        self.base = self.top / "2026-10-refinement"

    def test_the_build_counts_by_type_and_labels_the_effects_in_sample(self):
        build_folder(self.base)
        got = analysis.build_part(self.base)
        e = got["edits"]
        self.assertEqual((e["proposed"], e["proposedTotal"]), ({"name": 2, "annotation": 1, "property-term": 1}, 4))
        self.assertEqual((e["refusedByScreening"], e["approvedByReviewer"], e["rejectedByReviewer"]),
                         ({"name": 1}, {"name": 1, "annotation": 1}, {"property-term": 1}))
        self.assertEqual((e["assembled"], e["dropped"], e["inForce"], e["inForceTotal"]),
                         ({"name": 1, "annotation": 1}, {"annotation": 1}, {"name": 1}, 1))
        self.assertEqual((e["namesByField"], e["sourceLinksByRelation"]), ({"tradeNames": 1}, {}))
        self.assertEqual(got["droppedEdits"], [{"edit": "e-002", "type": "annotation", "missesFixed": 0,
                                                "hopsReachable": 0, "resultsLost": 2}])
        self.assertEqual(got["effects"]["inForce"]["missesFixed"], 3)
        self.assertEqual(got["effects"]["byType"]["name"]["byHop"], {"web": 1})
        self.assertNotIn("root", got["effects"]["groups"]["all"])  # a local path is never copied
        self.assertIn("in-sample", got["inSample"])
        self.assertEqual([b["reviewed"] for b in got["batches"]], [True, False])

    def test_the_screen_counts_pairs_and_attributes_per_question(self):
        screen_folder(self.base)
        got = analysis.screen_part(self.base, Stub())
        self.assertEqual(got["complete"]["answered"], 27)
        arms = got["groups"]["all"]["arms"]
        b, o, b0 = arms["B"], arms["Oplus"], arms["B0"]
        self.assertEqual((b["contradicted"], o["contradicted"], o["complete"], b["complete"]), (1, 1, 8, 9))
        self.assertEqual((b["citingFindings"], b0["citingFindings"], b["findingCitations"]), (9, 0, 12))
        self.assertEqual(b["wrongPolymer"], {"citations": 2, "answers": 2, "judged": 9, "citationsFamilyNotInGraph": 1,
                                             "unfiledCitations": 1, "citationsNotInStore": 1})
        self.assertEqual((b["meanWebCalls"], b["noWeb"], b["medianNewTokens"]), (round(18 / 9, 3), 1, 50e3))
        accumulation = got["groups"]["all"]["paired"]["accumulation"]  # B against B0
        self.assertEqual((accumulation["tokens"]["median"], accumulation["tokens"]["n"]), (0.5, 9))
        self.assertAlmostEqual(accumulation["webCalls"]["mean"], round(-28 / 9, 3))
        self.assertEqual(accumulation["webRatio"], round(18 / 46, 3))
        self.assertEqual(accumulation["citing"]["totals"], {"B": 9, "B0": 0})
        ontology = got["groups"]["all"]["paired"]["ontology"]  # O+ against B
        self.assertEqual((ontology["tokens"]["median"], ontology["complete"]["totals"]), (1.0, {"Oplus": 8, "B": 9}))
        self.assertEqual(ontology["wrongPolymer"]["totals"], {"Oplus": 1, "B": 2})
        points = {p["id"]: p for p in got["points"]}
        self.assertEqual(points["h1"]["accumulation"]["web"], round(math.log(3 / 7), 3))  # web calls + 1
        self.assertEqual(points["h3"]["ontology"]["tokens"], round(math.log(0.8), 3))
        self.assertEqual(points["n3"]["ontology"]["web"], 0.0)
        web = got["groups"]["all"]["attribution"]["web"]
        self.assertEqual((web["accumulationLarger"], web["ontologyLarger"], web["ties"]), (7, 1, 1))
        self.assertEqual(web["shareAccumulationLarger"]["share"], round(7 / 9, 3))
        self.assertEqual(set(got["groups"]), {"all", "H", "H/near", "H/far", "N", "N/asked-pair", "L", "L/name",
                                              "L/family", "L/value"})  # L by its group, as lookup.subsets
        self.assertEqual(got["hops"]["status"], "pending")

    def test_panel_b_and_the_lookup_part_come_from_lookup_reports_own_files(self):
        screen_folder(self.base)
        lookup_folder(self.base)
        hops = analysis.screen_part(self.base, Stub())["hops"]
        self.assertEqual(hops["status"], "complete")
        h = hops["groups"]["all"]
        self.assertEqual((h["webHops"], h["grouped"]["accumulation"], h["heldUnreached"]["web"]), (20, 10, 2))
        self.assertEqual((h["answersWithHeldUnreached"]["web"], h["heldUnreached"]["webReachableOnO+"]), (2, 1))
        self.assertEqual(hops["groups"]["H"]["webHops"], 12)
        got = analysis.lookup_part(self.base)
        self.assertEqual((got["status"], got["judged"], got["issuedRead"]), ("complete", 9, 9))
        self.assertEqual(got["groups"]["L"]["all"]["recallGain"], round(1 - 0.5, 3))
        self.assertEqual(got["groups"]["H"]["all"]["recallGain"], 0.0)
        self.assertEqual(got["groups"]["all"]["canonical"]["lost"], 0)
        (self.base / "lookup/judge.done").unlink()
        self.assertEqual(analysis.lookup_part(self.base)["status"], "partial")
        shutil.rmtree(self.base / "lookup")
        self.assertEqual(analysis.lookup_part(self.base)["status"], "pending")

    def test_the_cases_spread_over_replicates_c7_on_k0_and_c2_c3_without_an_edit(self):
        cases_folder(self.base)
        got = analysis.cases_part(self.base, {"name": 3, "annotation": 5})
        self.assertEqual(got["status"], "complete")
        c1 = got["cases"]["C1"]
        one = c1["perQuestion"]["c1a"]
        self.assertEqual(one["paired"]["O+/B"]["replicates"], {"1": {"tokens": 0.5, "web": 0.6},
                                                               "2": {"tokens": 0.8, "web": 0.6}})
        self.assertEqual(one["paired"]["O+/B"]["pooled"]["tokens"], round(math.sqrt(50 * 80) / 100, 3))
        self.assertEqual(one["arms"]["O+"]["newTokens"]["min"], 50e3)
        self.assertEqual(c1["arms"]["O+"]["webCallsByReplicate"]["means"], [2, 2])
        self.assertEqual(c1["origins"], {"c1a": "written", "c1b": "written"})
        c7 = got["cases"]["C7"]
        self.assertEqual((c7["questions"], c7["designated"], list(c7["arms"])), (["c1a", "c1b"], ["c1a"], ["B0", "O0"]))
        self.assertEqual(c7["paired"]["O0/B0"]["medianPooled"], {"tokens": 1.0, "web": 1.0})
        self.assertEqual(got["cases"]["C2"]["status"], "no qualifying edit")
        self.assertIn("source-link 0", got["cases"]["C2"]["why"])
        self.assertIn("family-link 0", got["cases"]["C3"]["why"])
        self.assertEqual(got["cases"]["C8"]["status"], "no question")

    def test_cases_still_running_are_partial_and_their_predictions_pending(self):
        cases_folder(self.base, missing=True)
        got = analysis.cases_part(self.base, {})
        self.assertEqual((got["status"], got["cases"]["C1"]["status"]), ("partial", "partial"))
        found = {p["id"]: p for p in analysis.predictions({"cases": got})}
        self.assertTrue(found["P5"]["verdict"].startswith("pending"))

    def test_every_prediction_is_judged_from_the_parts_with_its_numbers(self):
        screen_folder(self.base)
        lookup_folder(self.base)
        cases_folder(self.base)
        build_folder(self.base)
        out = self.top / "out"
        value = analysis.run("all", self.base, out, polymers=Stub())
        found = {p["id"]: p for p in value["predictions"]}
        self.assertEqual(list(found), ["P1", "P2", "P3", "P4", "P5"])
        # P1: 10 of 20 web hops limited by accumulation is not most; 2 of 20 avoidable; in 2 of 9 answers
        self.assertEqual([p["met"] for p in found["P1"]["parts"]], [False, True, True])
        self.assertEqual(found["P1"]["verdict"], "partly met")
        self.assertEqual(found["P2"]["verdict"], "met")
        # P3 on H and N: contradicted 1 and 1; wrong polymer B 1, O+ 0; complete O+ one fewer; results equal
        self.assertEqual([p["met"] for p in found["P3"]["parts"]], [True, True, False, True])
        p4 = {p["part"]: p["met"] for p in found["P4"]["parts"]}
        self.assertEqual((p4["C1: O+ fewer web steps than B"], p4["C1: O+ cites saved findings more often than B"]),
                         (True, True))
        self.assertEqual(p4["C2: O+ at least a third fewer hops"], analysis.UNTESTABLE)
        self.assertEqual(p4["C3: fewer web steps and more citing"], analysis.UNTESTABLE)
        self.assertEqual(p4["L: O+ fewer web steps than B"], False)  # equal web calls are not fewer
        self.assertEqual(p4["H and N overall: paired token ratio O+/B within 0.9–1.1"], True)
        self.assertEqual(found["P4"]["verdict"], "partly met")
        self.assertEqual(found["P5"]["verdict"], "met")
        written = json.loads((out / "results.json").read_text())
        self.assertEqual(written["meta"]["pins"]["tag"], "study-freeze-3")
        self.assertEqual(len(written["meta"]["commitments"]["sha256"]), 64)
        text = (out / "results.md").read_text()
        for heading in ("## The build", "## The screen", "## Lookup", "## Case studies", "## The predictions"):
            self.assertIn(heading, text)
        self.assertNotIn("/Users/", json.dumps(written))

    def test_the_predictions_wait_for_records_not_yet_written(self):
        screen_folder(self.base)
        value = analysis.run("all", self.base, self.top / "out", polymers=Stub())
        found = {p["id"]: p for p in value["predictions"]}
        self.assertEqual((found["P1"]["verdict"], found["P2"]["verdict"]), ("pending (so far not judged)",) * 2)
        self.assertNotEqual(found["P3"]["verdict"][:7], "pending")

    def test_nothing_is_written_into_the_run_folder_nor_a_local_path_anywhere(self):
        build_folder(self.base)
        with self.assertRaisesRegex(SystemExit, "run folder"):
            analysis.run("build", self.base, self.base / "analysis")
        with self.assertRaisesRegex(SystemExit, "local path"):
            analysis.write("x", {"meta": {}, "where": "/Users/somebody"}, self.top / "out")


class Workspaces(unittest.TestCase):
    """Wrong-polymer citations on real store copies and graphs (test_refinement_run's world): under the seed HDPE is
    outside polyethylene's lineage, under release O (its family link) it is inside; a finding without a subject is
    unfiled; nothing in a workspace changes while it is read."""

    def setUp(self):
        from test_refinement_run import SETS, World
        import driver
        from refinement import run
        self.world, self.question = World(self), SETS["H"][0]  # polyethylene, wop-000009
        self.folder = pins.BASE / "screen/s1"
        self.roots = {arm: driver.workspace(self.folder, arm, releases=run.release_root(arm), store=run.store_root(arm))
                      for arm in ARMS}

    def state(self, arm):
        return {str(p.relative_to(self.roots[arm])): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.roots[arm].rglob("*")) if p.is_file()}

    def test_wrong_polymer_citations_follow_each_arms_store_and_graph(self):
        cites = ("finding:hdpe-1", "finding:ldpe-1", "finding:pcl-1", "finding:ingeo-1", "finding:gone")
        before = {arm: self.state(arm) for arm in ARMS}
        rows = {arm: analysis.answer_row(self.question, arm, item(1000, 1, cites), self.roots[arm], analysis.Polymers())
                for arm in ARMS}
        self.assertEqual(rows["B"]["wrongPolymerIds"], ["finding:hdpe-1", "finding:pcl-1"])  # LDPE is a member
        self.assertEqual((rows["B"]["unfiledCitations"], rows["B"]["citationsNotInStore"]), (1, 1))
        self.assertNotIn("finding:hdpe-1", rows["Oplus"]["wrongPolymerIds"])  # release O links HDPE to the family
        self.assertIn("finding:pcl-1", rows["Oplus"]["wrongPolymerIds"])
        self.assertEqual(rows["B0"]["citationsNotInStore"], 5)  # K0 holds PLA's finding only
        self.assertEqual({arm: self.state(arm) for arm in ARMS}, before)


if __name__ == "__main__":
    unittest.main()
