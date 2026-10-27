"""Structure strategy 2, the coverage-summary estimate (`structure/coverage.py`), offline on a tiny world in a temporary
folder: a graph release (PEEK, the polyethylene family with HDPE, PVAc), a KF store, a property map, a screen shard
with B, B0 and O+ items and the B arm's traces and payloads, the blind judge's records, and pool answers from the live
loop and Part A. Coverage classes (lineage, rejected findings, the same-category rule, the store at an answer's start),
payload measures and later-search classes, the avoidable tokens and shares, the CL-18 rule, and the report. Run with
today's code:

    OOPC_STUDY_CODE=$PWD python3 -B -m unittest discover -s studies/macromolecules/tests -p "test_structure_*.py"
"""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
from structure import coverage  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

POLYMERS = [("wop-000001", "Polyether ether ketone", ["PEEK"]), ("wop-000002", "Polyethylene family", ["PE"]),
            ("wop-000003", "High-density polyethylene", ["HDPE"]), ("wop-000004", "Polyvinyl acetate", ["PVAc"])]
LINKS = [("wop-000003", "wop-000002")]  # (member, family)
MAP = {"glass transition temperature": "glass-transition-temperature", "tensile modulus": "tensile-modulus",
       "creep compliance": "creep-stress-relaxation", "notched izod impact strength": "notched-izod-impact"}
OLD = "2026-09-30T00:00:00+00:00"


def finding(fid, prop, subject, *, material="PEEK film", qid="q-old", created=OLD, status=knowledge.SUPPORTED):
    return {"id": fid, "qid": qid, "created": created, "status": status,
            "statement": "The %s had a %s of 1." % (material, prop), "material": material, "property": prop,
            "value": "1", "unit": "", "conditions": "", "subject": subject, "sourceTitle": "A study of %s" % fid,
            "sourceUrl": "https://example.org/%s" % fid, "sourceDoi": "", "locator": "Table 1", "excerpt": "1"}


FINDINGS = [
    finding("finding:tg-1", "glass transition temperature", "wop-000001", qid="p1",
            created="2026-10-01T00:00:00+00:00"),
    finding("finding:tg-2", "glass transition temperature", "wop-000001", created="2026-10-05T00:00:00+00:00"),
    finding("finding:mod", "tensile modulus", "wop-000001"),
    finding("finding:creep", "creep compliance", "wop-000001", status=knowledge.UNSUPPORTED),  # rejected: hidden
    finding("finding:izod", "notched Izod impact strength", "wop-000001"),
    finding("finding:pe", "tensile modulus", "wop-000002", material="polyethylene resin"),  # the family's
]


def entry(fid):
    """A payload entry as the tool returns it (compact)."""
    f = next(x for x in FINDINGS if x["id"] == fid)
    return {"id": fid, "statement": f["statement"], "material": f["material"], "property": f["property"],
            "value": f["value"], "unit": "", "subject": f["subject"], "status": f["status"],
            "source": {"title": f["sourceTitle"], "url": f["sourceUrl"]}}


NOTE = {"id": "note:n1", "title": "A study", "url": "https://example.org/n1"}


def payload(*ids, notes=()):
    return {"reviewed": [entry(i) for i in ids], "added": [], "unreviewed": [], "notes": list(notes)}


def size(value):
    return len(json.dumps(value, ensure_ascii=False))


def trace(root, run_id, calls):
    """A run's trace: a `search_knowledge` event per (query, payload) and each payload file."""
    folder = Path(root) / ".oopc/runs" / run_id
    (folder / "payloads").mkdir(parents=True)
    lines = []
    for number, (query, result) in enumerate(calls, 1):
        digest = "%s-%d" % (run_id, number)
        atomic_json(folder / "payloads" / (digest + ".json"), {"result": result})
        lines.append(json.dumps({"operation": "knowledge.search_knowledge", "status": "ok", "sequence": number,
                                 "payload_hash": digest, "request": {"arguments": {"q": query}}}))
    (folder / "events.jsonl").write_text("\n".join(lines) + "\n")


def question(qid, material, ids, prop, set_, stratum):
    return {"id": qid, "question": "What is the %s of %s?" % (prop, material), "materials": [material],
            "polymerIds": ids, "property": prop, "set": set_, "stratum": stratum, "kind": "property"}


def item(text, tokens, web=0, run=None, actions=()):
    return {"answer": {"answer": {"answer": text}, "runId": run, "webActions": list(actions),
                       "metrics": {"newTokens": tokens, "webCalls": web, "knowledgeLookups": 1}}}


class World:
    def __init__(self, test):
        folder = tempfile.TemporaryDirectory(prefix="oopc-coverage-test-")
        test.addCleanup(folder.cleanup)
        self.top = Path(folder.name).resolve()
        records = [{"@id": i, "@type": "PolymerConcept", "label": label, "abbreviations": names, "status": "seed",
                    "layer": "science"} for i, label, names in POLYMERS]
        for member, family in LINKS:
            for s, p, o in ((member, "broader", family), (family, "narrower", member)):
                records.append({"@id": "claim:%s-%s-%s" % (s, p, o), "@type": "Claim", "label": "%s %s %s" % (s, p, o),
                                "subject": s, "predicate": p, "object": o, "context": {}, "evidence": [],
                                "status": "seed", "layer": "science"})
        self.kf = self.top / "KF"
        build_release(self.kf / "releases/fixture", records, get_ontology(), {})
        release = read_json(self.kf / "releases/fixture/manifest.json")["release_id"]
        (self.kf / "releases/fixture").rename(self.kf / "releases" / release)
        atomic_json(self.kf / "releases/current.json", {"release_id": release})
        with knowledge.connect(self.kf) as db:
            for f in FINDINGS:
                knowledge._insert_finding(db, f["id"], f["qid"], "research", knowledge.clean_finding(f),
                                          status=f["status"], producer_engine="codex", created_at=f["created"])
        self.map = self.top / "map.json"
        atomic_json(self.map, {k: {"class": v} for k, v in MAP.items()})
        self.screen()
        self.pool()

    def screen(self):
        base, shard = self.top / "screen", self.top / "screen/s1"
        roots = {arm: shard / "workspaces" / arm for arm in ("B0", "B", "Oplus")}
        self.questions = [question("q-tg", "PEEK", ["wop-000001"], "glass transition temperature", "H", "near"),
                          question("q-creep", "PEEK", ["wop-000001"], "creep compliance", "H", "mid"),
                          question("q-pvac", "PVAc", ["wop-000004"], "glass transition temperature", "H", "far"),
                          question("q-impact", "PEEK", ["wop-000001"], "notched impact strength", "N", "asked-polymer")]
        atomic_json(base / "experiment.json", {"folders": ["s1"]})
        atomic_json(shard / "plan.json", {"arms": [{"name": a, "root": str(r)} for a, r in roots.items()],
                                          "questions": self.questions})
        self.calls = {
            "q-tg": [("PEEK glass transition temperature", payload("finding:tg-1", "finding:tg-2", "finding:mod",
                                                                   notes=[NOTE])),
                     ("polyether ether ketone glass transition", payload("finding:tg-1", "finding:tg-2"))],
            "q-creep": [("PEEK creep compliance", payload("finding:tg-1", "finding:mod", notes=[NOTE])),
                        ("polyether ether ketone creep", payload("finding:tg-2")),
                        ("HDPE creep", payload("finding:pe"))],
            "q-pvac": [("PVAc glass transition temperature", payload())],
            "q-impact": [("PEEK notched impact strength", payload("finding:izod"))]}
        texts = {"q-tg": "PEEK's Tg is 1 `finding:tg-1`. The heating rate is not in the saved findings.",
                 "q-creep": "The paper does not report creep compliance at 23 °C.",
                 "q-pvac": "No glass transition temperature value was found.",
                 "q-impact": "The notched Izod impact strength is 1 `finding:izod`."}
        tokens = {"q-tg": (20000, 25000), "q-creep": (40000, 20000), "q-pvac": (30000, 30000),
                  "q-impact": (25000, 25000)}
        opened = [{"action": "search", "outcome": "searched"}, {"action": "open", "outcome": "opened", "url": "u"}]
        for index, q in enumerate(self.questions):
            trace(roots["B"], "run-" + q["id"], self.calls[q["id"]])
            web = 3 if q["id"] == "q-creep" else 0
            atomic_json(shard / "items" / ("%04d-B.json" % index),
                        item(texts[q["id"]], tokens[q["id"]][0], web, "run-" + q["id"], opened if web else ()))
            atomic_json(shard / "items" / ("%04d-B0.json" % index), item("B0's answer.", tokens[q["id"]][1], 5))
            atomic_json(shard / "items" / ("%04d-Oplus.json" % index),
                        item("The study does not report a creep value." if q["id"] == "q-creep" else "O+.", 30000))
        for qid, relevant in (("q-creep", {"finding:tg-1": False}), ("q-impact", {"finding:izod": True})):
            atomic_json(self.top / "lookup/judge" / qid / "call-1.json", {"result": {"relevant": relevant}})

    def pool(self):
        root = self.top / "pool-root"
        trace(root, "run-p1", [("PEEK glass transition temperature", payload("finding:mod")),
                               ("PEEK Tg", payload())])
        atomic_json(self.top / "live/p1/result.json", {
            "usage": {"input_tokens": 50000, "cached_input_tokens": 20000, "output_tokens": 2000},
            "answer": {"answer": "No Tg value was found in the saved findings."}})
        atomic_json(self.top / "harness/ladder/r1-s1/items/0000-KF.json",
                    item("HDPE's tensile modulus is 1 `finding:pe`.", 10000))
        atomic_json(self.top / "harness/cases/items/0000-KF.json", item("The paper does not report haze.", 8000))
        self.answers = [
            {"id": "loop/p1", "questionId": "p1", "origin": "loop", "kind": "property", "root": str(root),
             "runId": "run-p1", "startedAt": "2026-10-03T00:00:00+00:00", "materials": ["PEEK"],
             "property": "glass transition temperature", "question": "What is the Tg of PEEK?",
             "steps": [{"type": "store"}, {"type": "store"}, {"type": "web-search"},
                       {"type": "open", "outcome": "opened"}]},
            {"id": "ladder/r1-s1/0000-KF", "questionId": "a4", "origin": "A4", "kind": "property", "root": str(root),
             "runId": "run-none", "startedAt": None, "materials": ["HDPE"], "property": "tensile modulus",
             "question": "What is the tensile modulus of HDPE?",
             "detail": {"folder": "ladder/r1-s1", "item": "0000-KF"},
             "steps": [{"type": "store"}]},
            {"id": "cases/0000-KF", "questionId": "a5", "origin": "A5", "kind": None, "root": str(root),
             "runId": "run-none", "startedAt": None, "materials": [], "property": None,
             "question": "Report the haze of a PEEK film.", "detail": {"folder": "cases", "item": "0000-KF"},
             "steps": []}]

    def coverage(self):
        return coverage.Coverage(self.kf, property_map=self.map)

    def report(self, kf=None):
        kf = kf or self.coverage()
        return coverage.report(kf, screen=self.top / "screen",
                               pool={"answers": self.answers, "live": self.top / "live",
                                     "harness": self.top / "harness"},
                               judged=lambda qid: coverage.judge_relevant(qid, self.top / "lookup"))


class Classes(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.kf = self.world.coverage()

    def classify(self, material, ids, prop, **kwargs):
        return self.kf.classify(self.kf.context({"question": "?", "materials": [material], "polymerIds": ids,
                                                 "property": prop}), **kwargs)

    def test_covered_polymer_only_and_nothing_with_the_line(self):
        got = self.classify("PEEK", ["wop-000001"], "glass transition temperature")
        self.assertEqual((got["coverage"], got["onProperty"]), ("covered", 2))
        self.assertEqual(got["onPropertyIds"], ["finding:tg-1", "finding:tg-2"])
        self.assertEqual(dict(got["line"]), {"glass-transition-temperature": 2, "tensile-modulus": 1,
                                             "notched-izod-impact": 1})  # the rejected creep finding is not there
        creep = self.classify("PEEK", ["wop-000001"], "creep compliance")
        self.assertEqual((creep["coverage"], creep["polymerFindings"]), ("polymer-only", 4))
        self.assertEqual(self.classify("PVAc", ["wop-000004"], "glass transition temperature")["coverage"], "nothing")

    def test_a_member_sees_its_family_and_the_store_is_taken_at_the_answer_start(self):
        self.assertEqual(self.classify("HDPE", [], "tensile modulus")["onPropertyIds"], ["finding:pe"])
        then = self.classify("PEEK", [], "glass transition temperature", before="2026-10-03T00:00:00+00:00",
                             exclude="p1")  # tg-1 is the answer's own, tg-2 came later
        self.assertEqual(then["coverage"], "polymer-only")
        self.assertEqual(self.classify("PEEK", [], "glass transition temperature",
                                       before="2026-10-03T00:00:00+00:00")["onPropertyIds"], ["finding:tg-1"])

    def test_the_same_category_rule_and_the_class_only_result(self):
        got = self.classify("PEEK", ["wop-000001"], "notched impact strength")
        self.assertEqual((got["coverage"], got["strict"], got["onPropertyIds"]),
                         ("covered", "polymer-only", ["finding:izod"]))
        ctx = self.kf.context({"question": "?", "materials": ["PEEK"], "property": "notched impact strength"})
        self.assertFalse(self.kf.on_property("tensile modulus", ctx))  # another category: no
        self.assertTrue(self.kf.asks("polyether ether ketone notched impact", ctx))
        self.assertFalse(self.kf.asks("PEEK heating rate", ctx))


class Payloads(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.kf = self.world.coverage()
        self.root = self.world.top / "screen/s1/workspaces/B"

    def measured(self, qid):
        q = next(q for q in self.world.questions if q["id"] == qid)
        ctx = self.kf.context(q)
        cover = self.kf.classify(ctx)
        found = coverage.searches(self.root, "run-" + qid)
        return found, coverage.measure(found, ctx, cover, self.kf), cover

    def test_payloads_are_measured_as_recorded(self):
        found = coverage.searches(self.root, "run-q-tg")
        calls = self.world.calls["q-tg"]
        self.assertEqual([(s["q"], s["chars"]) for s in found], [(q, size(p)) for q, p in calls])
        self.assertEqual([e["chars"] for e in found[0]["entries"]],
                         [size(entry(i)) + 2 for i in ("finding:tg-1", "finding:tg-2", "finding:mod")]
                         + [size(NOTE) + 2])
        self.assertIsNone(coverage.searches(self.root, "run-missing"))

    def test_a_polymer_only_answer_avoids_its_reformulation_and_the_first_payload_off_target(self):
        found, got, cover = self.measured("q-creep")
        self.assertEqual(got["later"], {"new-polymer": 1, "productive": 0, "after-exhaustion": 1, "unproductive": 0})
        first = self.world.calls["q-creep"][0][1]
        self.assertEqual(got["firstOffChars"], size(entry("finding:tg-1")) + 2 + size(entry("finding:mod")) + 2)
        self.assertEqual(got["firstNoteChars"], size(NOTE) + 2)
        self.assertEqual(got["firstChars"], size(first))
        later, estimate = coverage.saving(cover["coverage"], got)
        second = size(self.world.calls["q-creep"][1][1])
        self.assertEqual((later, estimate), (second, second + got["firstOffChars"]))  # HDPE's search is not cut
        self.assertTrue(got["feasible"])

    def test_a_covered_answer_avoids_only_a_reask_after_exhaustion(self):
        _, got, cover = self.measured("q-tg")
        self.assertEqual((got["firstOnTarget"], got["later"]["after-exhaustion"], got["reask"]["after-exhaustion"]),
                         (2, 1, 1))
        self.assertEqual(coverage.saving("covered", got), (got["laterChars"]["after-exhaustion"],) * 2)
        _, impact, _ = self.measured("q-impact")
        self.assertEqual(coverage.saving("covered", impact), (0, 0))
        _, pvac, _ = self.measured("q-pvac")
        self.assertEqual(coverage.saving("nothing", pvac), (0, 0))  # an empty payload has nothing off target
        self.assertEqual(coverage.saving(None, pvac), (None, None))


class Absences(unittest.TestCase):
    def test_statements_and_what_they_blame(self):
        text = ("PEEK's Tg is 143 °C. The heating rate is not in the saved findings.\n"
                "| Tm | not reported in the datasheet |\nThe evidence used here does not provide a value. "
                "A creep value was not found.")
        found = coverage.absences(text)
        self.assertEqual(len(found), 4)
        self.assertEqual([coverage.blame(s) for s in found], ["store", "source", "own", "unattributed"])

    def test_the_rule_counts_store_only_answers_and_classes_the_line_held(self):
        world = World(self)
        kf = world.coverage()
        cover = kf.classify(kf.context({"question": "?", "materials": ["PEEK"], "property": "creep compliance"}))
        got = coverage.cl18("The paper does not report a glass transition temperature.", "store-only", cover, [], kf,
                            cover["askedClasses"])
        self.assertEqual((got["a"], got["aNotReturned"], got["aAsked"], got["bSource"], got["strict"]), (1, 1, 0, 1, 1))
        returned = coverage.cl18("No glass transition temperature value was found.", "opened", cover,
                                 ["glass-transition-temperature"], kf)
        self.assertEqual((returned["a"], returned["aNotReturned"], returned["b"], returned["loose"]), (1, 0, 0, 0))
        self.assertEqual(coverage.reading_web({"webCalls": 0}, []), "store-only")
        self.assertEqual(coverage.reading_web({"webCalls": 2}, [{"action": "open", "outcome": "refused"}]), "no-page")
        self.assertEqual(coverage.reading_steps([{"type": "find", "outcome": "opened"}]), "opened")


class Report(unittest.TestCase):
    def test_the_report_from_the_records(self):
        world = World(self)
        value, rows, absent = world.report()
        screen = {r["id"]: r for r in rows if r["origin"] == "screen"}
        self.assertEqual({k: r["coverage"] for k, r in screen.items()},
                         {"q-tg": "covered", "q-creep": "polymer-only", "q-pvac": "nothing", "q-impact": "covered"})
        creep = screen["q-creep"]
        calls = world.calls["q-creep"]
        later = size(calls[1][1])
        off = size(entry("finding:tg-1")) + 2 + size(entry("finding:mod")) + 2
        self.assertAlmostEqual(creep["share"]["later"], later / 4 / 40000)
        self.assertAlmostEqual(creep["share"]["estimate"], (later + off) / 4 / 40000)
        self.assertEqual((creep["b0NewTokens"], creep["judgeRelevant"], screen["q-pvac"]["judgeRelevant"]),
                         (20000, 0, None))
        self.assertAlmostEqual(screen["q-tg"]["share"]["estimate"],
                               size(world.calls["q-tg"][1][1]) / 4 / 20000)
        summary = value["screen"]["all"]
        self.assertEqual(summary["sparse"]["answers"], 2)
        shares = [screen[k]["share"]["estimate"] for k in ("q-creep", "q-pvac")]
        self.assertAlmostEqual(summary["sparse"]["share"]["estimate"]["mean"], round(sum(shares) / 2, 4))
        self.assertEqual(value["classification"]["strict"]["movedByRelaxation"]["screen"], 1)
        self.assertEqual(value["judge"]["sparseWithRelevant"], [])
        self.assertEqual(value["judge"]["byCoverage"]["covered"], {"relevant": 1, "not judged": 1})
        self.assertEqual(value["midPenalty"]["H/mid"]["meanB"], 40000)
        pool = {r["id"]: r for r in rows if r["origin"] != "screen"}
        self.assertEqual(sorted(pool), ["ladder/r1-s1/0000-KF", "loop/p1"])  # A5 recorded no material or property
        p1 = pool["loop/p1"]
        self.assertEqual((p1["coverage"], p1["newTokens"]), ("polymer-only", 32000))
        self.assertAlmostEqual(p1["share"]["estimate"],
                               (size(payload()) + size(entry("finding:mod")) + 2) / 4 / 32000)
        self.assertEqual((pool["ladder/r1-s1/0000-KF"]["coverage"], pool["ladder/r1-s1/0000-KF"]["traced"]),
                         ("covered", False))
        cl18 = value["cl18"]
        # q-tg's "not in the saved findings" and q-pvac's unattributed "No ... value was found", both store-only
        self.assertEqual((cl18["screenB"]["b"]["statements"], cl18["screenB"]["bStore"]["statements"],
                          cl18["screenB"]["strict"]["answers"], cl18["screenB"]["loose"]["answers"]), (2, 1, 0, 1))
        self.assertEqual(cl18["screenOplus"]["bSource"]["answers"], 1)
        self.assertEqual(cl18["pool/A5"]["strict"]["answers"], 1)  # store-only, blaming a paper
        self.assertEqual(cl18["pool"]["answers"], 3)
        self.assertIn("## Prediction 2", coverage.markdown(value))

    def test_the_verdict(self):
        def shares(sparse, covered, overall):
            return {k: {"share": {"estimate": {"mean": v}}} for k, v in
                    (("sparse", sparse), ("covered", covered), ("all", overall))}
        self.assertEqual(coverage.verdict(shares(0.15, 0.01, 0.05))["verdict"], "met")
        self.assertEqual(coverage.verdict(shares(0.096, 0.039, 0.053))["verdict"], "partly met")
        self.assertEqual(coverage.verdict(shares(0.3, 0.05, 0.1))["verdict"], "not met")

    def test_the_interval_resamples_a_question_s_answers_together(self):
        rows = [{"questionId": "a", "x": 1.0}, {"questionId": "a", "x": 3.0}, {"questionId": "b", "x": 2.0},
                {"questionId": "c", "x": 0.0}]
        got = coverage.mean_ci(rows, lambda r: r["x"])
        self.assertEqual((got["n"], got["questions"], got["mean"]), (4, 3, 1.5))
        self.assertEqual(got, coverage.mean_ci(rows, lambda r: r["x"]))  # seeded
        self.assertLessEqual(got["low"], got["mean"])
        self.assertEqual(coverage.pooled_ci(rows, lambda r: r["x"], lambda r: 2.0)["share"], 0.75)


if __name__ == "__main__":
    unittest.main()
