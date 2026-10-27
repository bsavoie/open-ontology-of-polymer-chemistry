"""Part C's proposal step offline (refinement/propose.py), with scripted curator and reviewer sessions behind the study
Guard: answers that do not follow the schema are failed as invalid-output and tried once more; edits off the closed
list, without evidence or with evidence that is only trace adjacency are refused before review; runs stop for quota and
resume without asking a finished batch again; no engine is called unless the code is the tag, nor before the question
sets are fixed and committed by hash; every edit gets one verdict; and only approved edits are assembled, once, in a
stable order, into the formats overlay.py reads."""
import json, re, sys, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
sys.path.insert(0, str(Path(__file__).resolve().parent))  # this folder, for the shared fixture
import driver  # noqa: E402
from refinement import overlay, pins, propose, questions  # noqa: E402
from oopc import calls, engines  # noqa: E402
from oopc.util import atomic_json, digest, read_json  # noqa: E402
from test_refinement_overlay import ART, SI, World  # noqa: E402

BATCHES = {
    "batch-01": {"groups": [{"name": "PA66", "misses": [{"id": "m-001", "query": "PA66 Tg", "finding": "finding:f1"}],
                             "hops": []},
                            {"pair": [SI, ART], "misses": [], "hops": [{"id": "h-001", "from": ART, "to": SI}]},
                            {"property": "Tg", "misses": ["m-002"], "hops": []}]},
    "batch-02": {"groups": [{"name": "Lexan", "misses": [{"id": "m-101"}], "hops": []},
                            {"name": "sample A", "misses": [{"id": "m-102"}], "hops": []}]},
}


def fields(**values):
    empty = {k: ([] if s.get("type") == "array" else False if s.get("type") == "boolean" else "")
             for k, s in propose._FIELDS["properties"].items()}
    return dict(empty, **values)


def proposal(kind, sources=(), misses=(), hops=(), **values):
    return {"type": kind, "fields": fields(**values), "misses": list(misses), "hops": list(hops),
            "sources": [{"url": u, "quote": q} for u, q in sources], "why": "It fixes the misses it lists."}


PA66 = proposal("name", [("https://example.org/pa66", "Polyamide 66 (PA 6,6) resin")], ["m-001"],
                polymer="wop-000003", field="abbreviations", name="PA66")
CURATED = {
    "batch-01": [
        PA66,
        proposal("name", [("https://example.org/pei", "PEI")], ["m-001"], polymer="wop-000006", field="abbreviations",
                 name="PEI"),  # refused: names unrelated polymers and is not marked ambiguous
        proposal("source-link", [("https://example.org/si", "Supporting Information for: The article")], hops=["h-001"],
                 a="url:https://example.org/si", relation="supplement-of", b="doi:10.1000/art"),
        proposal("source-link", [("https://example.org/next-page-in-the-trace", "opened right after")], hops=["h-001"],
                 a=SI, relation="supplement-of", b=ART),  # refused: evidence from neither source
        proposal("name", [], ["m-001"], polymer="wop-000003", field="alternateNames", name="Nylon 66"),  # no source
        proposal("annotation", [], ["m-001"], finding="finding:f6", subject="wop-000004"),  # a person approved f6
        proposal("family-link", [("https://example.org/pla", "PLA is an aliphatic polyester")], ["m-001"],
                 narrower="wop-000008", broader=["wop-000007"]),  # the reviewer rejects it
        proposal("polymer", [("https://example.org/copa", "Polyamide 6/66 copolymer (PA6/66)")], ["m-001"],
                 label="Polyamide 6/66 copolymer", abbreviations=["PA6/66"], broader=["wop-000001"]),
        proposal("property-term", [], ["m-002"], term="glass-transition-temperature", names=["Tg", "glass transition"]),
        proposal("name", [("https://example.org/pa66", "PA66")], ["m-999"], polymer="wop-000003", field="abbreviations",
                 name="PA66"),  # refused: cites a miss the batch does not have
        proposal("name", [("https://example.org/pa66b", "PA66 grades")], [], ["h-001"], polymer="wop-000003",
                 field="abbreviations", name="PA66"),  # the same edit again, answering a hop: merged into the first
    ],
    "batch-02": [
        proposal("name", [("https://example.org/lexan", "LEXAN™ polycarbonate resin")], ["m-101"], polymer="wop-000006",
                 field="tradeNames", name="Lexan"),
        proposal("annotation", [], ["m-102"], finding="finding:f5", subject="wop-000008"),
        dict(PA66, misses=["m-101"]),  # approved in both batches: assembled once
    ],
}


class Engine:
    """Answers by schema: the curator its batch's proposals, the reviewer a verdict for each edit it is shown,
    rejecting family links. `fail(kind, batch, n)` may return a failure reason for the n-th call of that kind and
    batch; `answer(kind, batch, value)` may change an answer."""

    def __init__(self, fail=None, answer=None):
        self.calls, self.fail, self.answer, self.prompts = [], fail, answer, []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        kind = "curator" if schema is propose.CURATOR_SCHEMA else "review"
        if kind == "curator":
            batch = re.search(r'<dossier batch="([^"]+)">', prompt).group(1)
        else:
            shown = json.loads(prompt.split("<edits>\n", 1)[1].rsplit("\n</edits>", 1)[0])
            batch = "batch-02" if any(e["edit"].get("name") == "Lexan" for e in shown) else "batch-01"
        self.calls.append((kind, batch, engine, web))
        self.prompts.append(prompt)
        reason = self.fail and self.fail(kind, batch, sum(c[:2] == (kind, batch) for c in self.calls))
        if reason:
            raise engines.EngineError(reason, "scripted " + reason, seconds=1.0)
        if kind == "curator":
            value = {"edits": json.loads(json.dumps(CURATED[batch])), "notes": ""}
        else:
            value = {"verdicts": [{"id": e["id"], "verdict": "rejected" if e["type"] == "family-link" else "approved",
                                   "reason": "Its source says so."} for e in shown], "notes": ""}
        if self.answer:
            value = self.answer(kind, batch, value)
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": value,
                "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10}, "observedTools": [],
                "agentSeconds": 1.0}


def fix_questions(test, top):
    """H, N and L written and fixed by hash, their digests committed in a commitments.json of the test's own (taken as
    committed to git), as questions.py's commands leave them before curation."""
    for patch in (mock.patch.object(questions, "COMMITMENTS", top / "commitments.json"),
                  mock.patch.object(questions, "in_head", lambda path: True)):
        patch.start()
        test.addCleanup(patch.stop)
    atomic_json(questions.COMMITMENTS, dict({k: {} for k in questions.ENTRIES}, format=questions.COMMITTED))
    for name in pins.SETS:
        atomic_json(questions.path(name + ".json"), [{"id": name.lower() + "1", "set": name, "question": "Q %s?" % name}])
    questions.hashes()
    questions.commit_questions(write=True)


class Propose(World):
    def setUp(self):
        super().setUp()
        for name, batch in BATCHES.items():
            atomic_json(pins.FOLDERS["mine"] / "dossier" / (name + ".json"), batch)
        fix_questions(self, self.tmp)

    def guard(self, engine):
        return driver.Guard(time.time() + 3600, read_quota=lambda e: {"remainingPercent": 80}, run_session=engine,
                            signed=lambda e: True, base=pins.folder("propose"))

    def item(self, part, name):
        return read_json(pins.FOLDERS["propose"] / part / (name + ".json"))

    def test_curate_screen_review_and_assemble(self):
        engine = Engine()
        self.assertEqual(propose.curate(self.guard(engine))["status"], "completed")
        self.assertEqual([(c[0], c[1], c[2], c[3]) for c in engine.calls],
                         [("curator", "batch-01", engines.CLAUDE, True), ("curator", "batch-02", engines.CLAUDE, True)])
        # What the curator reads: the closed list, the graph, A1's classes and the batch.
        prompt = engine.prompts[0]
        for text in ("supplement-of", "never evidence", "wop-000003 | Polyamide 66", "glass-transition-temperature |",
                     '"m-001"'):
            self.assertIn(text, prompt)
        first = self.item("curator", "batch-01")
        refused = {r["index"]: " ".join(r["problems"]) for r in first["refused"]}
        self.assertEqual(sorted(refused), [2, 4, 5, 6, 10])
        self.assertIn("unrelated polymer", refused[2])
        self.assertIn("no evidence comes from either source", refused[4])
        self.assertIn("no source", refused[5])
        self.assertIn("approved", refused[6])
        self.assertIn("m-999", refused[10])
        kept = {e["index"]: e for e in first["edits"]}
        self.assertEqual(sorted(kept), [1, 3, 7, 8, 9])
        self.assertEqual(kept[1]["hops"], ["h-001"])  # the duplicate's hop, merged
        self.assertEqual(kept[3]["edit"], {"a": SI, "relation": "supplement-of", "b": ART})  # keys as the store keys
        self.assertEqual(calls.records(pins.FOLDERS["propose"])[0]["phase"], "study:refinement:curator")
        # The reviewer: one Codex session per batch, shown the screened edits and what they name, not the reasons.
        self.assertEqual(propose.review(self.guard(engine))["status"], "completed")
        reviews = [c for c in engine.calls if c[0] == "review"]
        self.assertEqual([(c[1], c[2]) for c in reviews], [("batch-01", engines.CODEX), ("batch-02", engines.CODEX)])
        shown = json.loads(engine.prompts[2].split("<edits>\n", 1)[1].rsplit("\n</edits>", 1)[0])
        self.assertEqual([e["id"] for e in shown], ["p01", "p03", "p07", "p08", "p09"])
        self.assertNotIn("why", shown[0])
        self.assertEqual(shown[0]["polymers"][0]["label"], "Polyamide 66")
        self.assertEqual(shown[1]["sourcesLinked"]["b"]["title"], "Paper finding:f1")
        self.assertIn("definition", shown[4]["propertyClass"])
        # Assembly: approved only, in order, the edit approved twice kept once, new polymers in the reserved block.
        value = propose.assemble()
        edits = value["edits"]
        self.assertEqual(list(edits), ["e-%03d" % n for n in range(1, 7)])
        self.assertEqual([e["type"] for e in edits.values()],
                         ["name", "source-link", "polymer", "property-term", "name", "annotation"])
        self.assertEqual(edits["e-001"]["misses"], ["m-001", "m-101"])
        self.assertEqual(edits["e-001"]["proposer"], {"engine": engines.CLAUDE, "model": "scripted", "batch": "batch-01"})
        self.assertEqual(edits["e-001"]["reviewer"], {"engine": engines.CODEX, "model": "scripted",
                                                      "verdict": "approved", "reason": "Its source says so."})
        self.assertEqual(sorted(edits["e-001"]), ["edit", "hops", "misses", "proposer", "reviewer", "sources", "type"])
        self.assertEqual(edits["e-003"]["edit"]["id"], "wop-900001")
        folder = pins.FOLDERS["overlay"]
        graph, store = read_json(folder / "graph-overlay.json"), read_json(folder / "store-overlay.json")
        self.assertEqual(sorted(graph), ["familyLinks", "format", "names", "polymers"])
        self.assertEqual(graph["familyLinks"], [])  # rejected
        self.assertEqual(graph["polymers"], [{"edit": "e-003", "id": "wop-900001", "label": "Polyamide 6/66 copolymer",
                                              "abbreviations": ["PA6/66"], "alternateNames": [],
                                              "broader": ["wop-000001"]}])
        self.assertEqual(graph["names"][1], {"edit": "e-005", "polymer": "wop-000006", "field": "tradeNames",
                                             "name": "Lexan"})
        self.assertEqual(store["sourceLinks"], [{"edit": "e-002", "a": SI, "relation": "supplement-of", "b": ART,
                                                 "evidence": "Supporting Information for: The article",
                                                 "evidenceUrl": "https://example.org/si"}])
        self.assertEqual(store["annotations"], [{"edit": "e-006", "finding": "finding:f5", "subject": "wop-000008"}])
        self.assertEqual(propose.status()["assembled"], 6)
        self.assertEqual(propose.assemble(), value)  # the same again: nothing rewritten
        self.assertTrue(overlay.check()["ok"])  # what overlay.py reads
        edits_file = read_json(folder / "edits.json")
        edits_file["edits"]["e-001"]["misses"] = ["m-001"]
        atomic_json(folder / "edits.json", edits_file)
        with self.assertRaises(SystemExit):  # never rewritten with other content
            propose.assemble()

    def test_assembly_waits_for_every_batch(self):
        engine = Engine(fail=lambda kind, batch, n: "quota" if batch == "batch-02" else None)
        self.assertEqual(propose.curate(self.guard(engine)), {"status": "stopped", "part": "curator", "reason": "quota"})
        with self.assertRaises(SystemExit):
            propose.assemble()
        self.assertEqual(propose.review(self.guard(engine))["status"], "completed")  # batch-01 can be reviewed
        with self.assertRaises(SystemExit):
            propose.assemble()

    def test_runs_resume_and_transient_failures_are_tried_once_more(self):
        failures = {("curator", "batch-01", 1): "crashed", ("curator", "batch-02", 1): "quota"}
        engine = Engine(fail=lambda kind, batch, n: failures.get((kind, batch, n)))
        self.assertEqual(propose.curate(self.guard(engine))["reason"], "quota")
        self.assertEqual([c[:2] for c in engine.calls], [("curator", "batch-01")] * 2 + [("curator", "batch-02")])
        attempts = self.item("curator", "batch-01")["attempts"]
        self.assertEqual([a.get("reason") for a in attempts], ["crashed", None])
        self.assertEqual(self.item("curator", "batch-02")["attempts"][0]["reason"], "quota")
        self.assertNotIn("curator", self.item("curator", "batch-02"))  # a stop leaves it to do
        self.assertEqual(propose.curate(self.guard(engine))["status"], "completed")
        self.assertEqual([c[:2] for c in engine.calls[3:]], [("curator", "batch-02")])  # batch-01 is not asked again
        self.assertEqual(propose.curate(self.guard(engine)), {"status": "completed", "part": "curator", "pending": 0})
        self.assertEqual(len(engine.calls), 4)
        # An answer saved but not yet screened (a crash in between) is screened again, without another session.
        item = self.item("curator", "batch-01")
        screened = item.pop("edits"), item.pop("refused")
        atomic_json(pins.FOLDERS["propose"] / "curator/batch-01.json", item)
        self.assertEqual(propose.curate(self.guard(engine))["failed"], [])
        self.assertEqual(len(engine.calls), 4)
        self.assertEqual((self.item("curator", "batch-01")["edits"], self.item("curator", "batch-01")["refused"]),
                         screened)
        # A failure that is not transient is the batch's, after which the run goes on; a rerun tries it again.
        engine = Engine(fail=lambda kind, batch, n: "rejected" if (kind, batch, n) == ("review", "batch-01", 1) else None)
        self.assertEqual(propose.review(self.guard(engine)), {"status": "completed", "part": "review",
                                                              "failed": ["batch-01"]})
        self.assertEqual(self.item("review", "batch-01")["review"]["error"]["reason"], "rejected")
        self.assertEqual(propose.review(self.guard(engine))["failed"], [])
        self.assertEqual([c[:2] for c in engine.calls], [("review", "batch-01"), ("review", "batch-02"),
                                                         ("review", "batch-01")])

    def test_answers_must_follow_the_schema(self):
        def answer(kind, batch, value):
            if kind == "curator" and batch == "batch-01":
                value["edits"][0]["fields"].pop("ambiguous")
            if kind == "review":
                value["verdicts"] = value["verdicts"][1:]  # one edit without a verdict
            return value
        engine = Engine(answer=answer)
        self.assertEqual(propose.curate(self.guard(engine))["failed"], ["batch-01"])
        item = self.item("curator", "batch-01")
        self.assertEqual([a["reason"] for a in item["attempts"]], ["invalid-output"] * 2)  # tried once more
        self.assertEqual(item["curator"]["error"]["reason"], "invalid-output")
        self.assertEqual(calls.records(pins.FOLDERS["propose"])[0]["outcome"], "completed")  # its tokens are counted
        self.assertEqual(propose.review(self.guard(engine))["failed"], ["batch-02"])
        self.assertEqual(self.item("review", "batch-02")["review"]["error"]["reason"], "invalid-output")
        self.assertIsNone(propose.conforms({"edits": [], "notes": ""}, propose.CURATOR_SCHEMA))
        self.assertIn("unexpected", propose.conforms({"edits": [], "notes": "", "more": 1}, propose.CURATOR_SCHEMA))
        bad = dict(PA66, type="finding")
        self.assertIn("not one of", propose.conforms({"edits": [bad], "notes": ""}, propose.CURATOR_SCHEMA))

    def test_screening_holds_to_the_closed_list_and_its_evidence(self):
        ctx = propose.context()
        ids = {"misses": {"m-001"}, "hops": {"h-001"}}
        self.assertEqual(propose.screen(PA66, ids, ctx)[1], [])
        self.assertTrue(propose.screen(dict(PA66, type="finding"), ids, ctx)[1])  # off the closed list
        unquoted = dict(PA66, sources=[{"url": "https://example.org/pa66", "quote": "Polyamide 66 resin"}])
        self.assertIn("no quote contains", " ".join(propose.screen(unquoted, ids, ctx)[1]))
        cycle = proposal("family-link", [("https://example.org/x", "x")], ["m-001"], narrower="wop-000001",
                         broader=["wop-000002"])
        self.assertIn("cycle", " ".join(propose.screen(cycle, ids, ctx)[1]))
        orphan = proposal("polymer", [("https://example.org/x", "Polyamide 6/66 copolymer")], ["m-001"],
                          label="Polyamide 6/66 copolymer")
        self.assertIn("broader", " ".join(propose.screen(orphan, ids, ctx)[1]))
        absent = proposal("source-link", [("https://example.org/si", "Supporting Information")], hops=["h-001"],
                          a=SI, relation="supplement-of", b="doi:10.9/absent")
        self.assertIn("holds no source", " ".join(propose.screen(absent, ids, ctx)[1]))
        crossref = proposal("source-link", [("https://api.crossref.org/works/10.1000/art", "is-supplement-to")],
                            hops=["h-001"], a=SI, relation="supplement-of", b=ART)
        self.assertEqual(propose.screen(crossref, ids, ctx)[1], [])  # Crossref's record of one of them
        term = proposal("property-term", [], ["m-001"], term="glass-transition-temperature", names=["T"])
        self.assertTrue(propose.screen(term, ids, ctx)[1])
        self.assertIn("no miss or hop", " ".join(propose.screen(dict(PA66, misses=[]), ids, ctx)[1]))

    def test_curation_waits_for_the_question_sets_fixed_and_committed_by_hash(self):
        engine = Engine()
        hashes, commitments = questions.path("hashes.json"), questions.COMMITMENTS
        fixed, committed = hashes.read_bytes(), commitments.read_bytes()

        def refused(pattern):
            with self.assertRaisesRegex(SystemExit, pattern):
                propose.curate(self.guard(engine))
            self.assertEqual(engine.calls, [])
        hashes.unlink()
        refused("not fixed by hash")
        atomic_json(hashes, {"sets": {name: digest(questions.load(name, hashed=False)) for name in ("H", "N")}})
        refused("covers H, N, not H, N and L")
        hashes.write_bytes(fixed)
        rows = questions.load("L")
        atomic_json(questions.path("L.json"), [dict(rows[0], question="Changed?")])
        refused("L.json differs from its hash")
        atomic_json(questions.path("L.json"), rows)
        atomic_json(commitments, dict(json.loads(committed), questions={}))
        refused("commitments.json has no questions entry")
        entry = json.loads(committed)
        entry["questions"]["files"]["H.json"] = "0" * 64
        atomic_json(commitments, entry)
        refused(r"questions: the private files differ from commitments.json \(files\)")
        commitments.write_bytes(committed)
        with mock.patch.object(questions, "in_head", lambda path: False):
            refused("not committed to git")
        self.assertEqual(propose.curate(self.guard(engine))["status"], "completed")
        digest_ = questions.file_digest(hashes)
        self.assertEqual({self.item("curator", b)["questionsSha256"] for b in BATCHES}, {digest_})
        self.assertEqual(json.loads(committed)["questions"]["hashes.json"], digest_)

    def test_no_engine_unless_the_code_is_the_tag(self):
        engine = Engine()
        with mock.patch.object(pins, "frozen", mock.Mock(side_effect=SystemExit("not the tag"))):
            with self.assertRaises(SystemExit):
                propose.curate(self.guard(engine))
        self.assertEqual(engine.calls, [])
        self.assertFalse((pins.FOLDERS["propose"] / "curator").exists())

    def test_a_changed_dossier_is_refused(self):
        engine = Engine(fail=lambda kind, batch, n: "quota" if batch == "batch-02" else None)
        propose.curate(self.guard(engine))
        self.assertEqual(propose.status()["batches"][0]["curated"], "done")
        atomic_json(pins.FOLDERS["mine"] / "dossier/batch-01.json", {"groups": []})
        with self.assertRaises(SystemExit):
            propose.curate(self.guard(Engine()))
        with self.assertRaises(SystemExit):
            propose.assemble()
        self.assertEqual(len(engine.calls), 2)


if __name__ == "__main__":
    unittest.main()
