"""Part A's harness offline, with a scripted engine and its own release and stores in a temporary folder: the KF cuts,
the resampled stores, the similarity ladder, the sharded and replicated plans with their pins, the case-study and E9
replicates run end to end, the combined reports, and the refusal to prepare or run unless the code is the tag. A last
test reads the real private records (read-only) and skips when they are absent."""
import contextlib, hashlib, io, json, math, random, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402
import driver  # noqa: E402
from part_a import estimate, part_a  # noqa: E402
from campaign import make_questions  # noqa: E402
from case_studies import case_studies, score  # noqa: E402
from planted import planted  # noqa: E402
from scaling import scaling  # noqa: E402
from oopc import ask, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, locked, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

stores = part_a.stores
OLD = """CREATE TABLE IF NOT EXISTS source_access (id TEXT PRIMARY KEY, source_key TEXT, url TEXT, locator TEXT,
    observation TEXT, identity_evidence TEXT, question_id TEXT, engine TEXT, session_id TEXT, observed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_state (question_id TEXT, kind TEXT, state TEXT, reason TEXT, engine TEXT,
    updated_at TEXT, PRIMARY KEY(question_id, kind));"""  # tables KF keeps from an earlier schema; scaling.cut reads them


def release(root):
    path = build_release(root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                         "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
    release_id = json.loads((path / "manifest.json").read_text())["release_id"]
    path.rename(root / "releases" / release_id)
    atomic_json(root / "releases/current.json", {"release_id": release_id})


def add(db, identifier, question, created, statement, *, status=knowledge.SUPPORTED, reviewed="", detail=None,
        value="41", material="polymer 1"):
    knowledge._insert_finding(db, identifier, question, "research", knowledge.clean_finding({
        "statement": statement, "material": material, "property": "crystallinity", "value": value, "unit": "%",
        "conditions": "second heating", "subject": "", "sourceTitle": "Paper " + question, "sourceDoi": "",
        "sourceUrl": "https://example.org/" + question, "locator": "Table 1", "excerpt": value, "needsReview": False,
        "reviewFlag": ""}), status=status, producer_engine="codex", created_at=created, reviewed_at=reviewed,
        reviewer_engine="codex" if reviewed else "", detail=detail or {"reviewMode": "researcher", "needsReview": False})


def note(db, identifier, question, created):
    knowledge._insert_note(db, identifier, question, "research", {"title": "Paper " + question, "url":
                           "https://example.org/n/" + question, "doi": "", "locator": "p. 1", "excerpts": [],
                           "supports": "crystallinity of polymer 1", "conditions": "", "readUrl": ""}, created_at=created)


def deposit(db, question, at, findings=1, notes=1):
    db.execute("INSERT INTO deposits (question_id, origin, engine, deposited_at, findings, notes, dropped, review_status, "
               "duplicates, duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (question, "research", "codex", at, findings, notes, 0, "reviewed", 0, "[]"))


def review(db, identifier, question, at):
    db.execute("INSERT INTO reviews (id, question_id, engine, started_at, finished_at, status, reason) VALUES "
               "(?,?,?,?,?,?,?)", (identifier, question, "codex", at, at, "completed", ""))


PLANTED = {p["id"]: dict(statement="Source statement %d of polymer 1 crystallinity." % n, value="7%d" % n, unit="%",
                         conditions="second heating", status=knowledge.SUPPORTED, question_id="e9source%d" % n)
           for n, p in enumerate(planted.PLANTS)}


def kf(root):
    """A small KF: questions across the cut times, a merge after them, a finding re-reviewed after a cut that kept its
    earlier verdict, records without a question, the five E9 source findings, and a deposit with nothing in it."""
    release(root)
    with knowledge.connect(root) as db:
        db.executescript(OLD)
        for n in range(1, 7):  # q1..q6, one per day from 2026-10-01: before and after the K200 cut (10-05)
            q, at = "q%d" % n, "2026-10-0%dT12:00:00+00:00" % n
            add(db, "finding:%s-1" % q, q, at, "Polymer 1 reached %d1%% crystallinity in study %s." % (n, q),
                reviewed=at)
            add(db, "finding:%s-2" % q, q, at, "Polymer 1 film %s gave %d2%% crystallinity." % (q, n),
                status=knowledge.ACCEPTED)
            note(db, "note:%s-1" % q, q, at)
            deposit(db, q, at)
            review(db, "review-" + q, q, at)
        # q1's third finding was re-reviewed by the cleanup (10-14), which kept its earlier verdict; its fourth was
        # reviewed only then; its fifth, flagged, also.
        add(db, "finding:q1-3", "q1", "2026-10-01T12:00:00+00:00", "Polymer 1 rechecked crystallinity 43%.",
            reviewed="2026-10-14T09:00:00+00:00", detail={"reviewMode": "researcher", "needsReview": False,
            "previousReviews": [{"verdict": "uncertain", "reason": "403", "engine": "claude-code",
                                 "reviewedAt": "2026-10-01T13:00:00+00:00"}]})
        add(db, "finding:q1-4", "q1", "2026-10-01T12:00:00+00:00", "Polymer 1 crystallinity 44% by WAXD.",
            reviewed="2026-10-14T09:00:00+00:00")
        add(db, "finding:q1-5", "q1", "2026-10-01T12:00:00+00:00", "Polymer 1 crystallinity 45% read off a figure.",
            reviewed="2026-10-14T09:00:00+00:00", detail={"reviewMode": "researcher", "needsReview": True})
        review(db, "review-q1-cleanup", "q1", "2026-10-14T09:00:00+00:00")
        merged = {"id": "finding:q2-9", "question_id": "q2", "origin": "research", "statement":
                  "Polymer 1 restored duplicate crystallinity 29%.", "material": "polymer 1", "property": "crystallinity",
                  "value": "29", "unit": "%", "conditions": "", "subject": "", "source_title": "Paper q2",
                  "source_url": "https://example.org/q2", "source_doi": "", "locator": "Table 2", "excerpt": "29",
                  "status": knowledge.ACCEPTED, "review_reason": "", "reviewer_engine": "", "reviewed_at": "",
                  "producer_engine": "codex", "created_at": "2026-10-02T12:00:00+00:00", "detail": "{}"}
        db.execute("INSERT INTO merged VALUES (?,?,?,?)", ("finding:q2-9", "finding:q2-1", "2026-10-14T09:00:26+00:00",
                                                          json.dumps(merged)))
        db.execute("INSERT INTO source_access (id, question_id, observed_at) VALUES (?,?,?)",
                   ("access-1", "q3", "2026-10-03T12:00:00+00:00"))
        add(db, "finding:legacy-1", "legacy", "2026-09-27", "Imported polymer 1 crystallinity 50%.", reviewed="2026-09-27")
        note(db, "note:legacy-1", "legacy", "2026-09-27")
        deposit(db, "empty-q", "2026-10-02T12:00:00+00:00", 0, 0)
        for identifier, was in PLANTED.items():  # E9's five source findings (each its own question)
            add(db, identifier, was["question_id"], "2026-10-01T12:00:00+00:00", was["statement"], value=was["value"],
                reviewed="2026-10-01T13:00:00+00:00")
            deposit(db, was["question_id"], "2026-10-01T12:00:00+00:00")


def store_ids(root):
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    value = {t: {r[0] for r in db.execute("SELECT %s FROM %s" % (c, t))} for t, c in (
        ("findings", "id"), ("notes", "id"), ("deposits", "question_id"), ("reviews", "id"), ("merged", "id"),
        ("findings_fts", "id"), ("source_access", "question_id"))}
    db.close()
    return value


class Engine:
    """Answers by schema: plain, researcher (searches saved knowledge for the question's subject and cites what it
    finds), check, blind score, and review (every finding unsupported, but those in `skip`). Counts each kind. `fail`,
    when set, is asked first: `fail(kind, prompt)` returns a failure reason to raise (counted as "failed-<kind>"), or
    None; `drop`, when set, is asked whether a score result should leave out its first code."""

    def __init__(self):
        self.calls, self.seen, self.engines, self.prompts = [], [], [], []
        self.fail, self.drop, self.skip = None, None, set()

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, **options):
        if options.get("resume"):  # The researcher's second turn (2026-10-25 on): no findings, no cost, not counted.
            return {"engine": engine, "model": "scripted", "sessionId": options["resume"], "answer": {
                "answer": "", "citations": [], "findings": [], "sources": [], "limitations": [], "openQuestions": []},
                "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}, "observedTools": [],
                "agentSeconds": 0.0}
        props = schema.get("properties", {})
        kind = ("plain" if schema is parity.DIRECT_SCHEMA else "research" if schema is ask.ANSWER_SCHEMA else
                "check" if schema is reviewer.CHECK_SCHEMA else "score" if "scores" in props else "review")
        reason = self.fail and self.fail(kind, prompt)
        if reason:
            self.calls.append("failed-" + kind)
            raise engines.EngineError(reason, "scripted " + reason, seconds=1.0)
        if kind == "score":
            self.prompts.append(prompt)
        if schema is parity.DIRECT_SCHEMA:
            kind, answer = "plain", {"answer": "Not found.", "citations": [], "limitations": []}
        elif schema is ask.ANSWER_SCHEMA:
            kind = "research"
            found = tools.call("search_knowledge", {"q": "PEEK 5600G tensile strength" if "PEEK" in prompt
                                                    else "polymer 1 crystallinity"}) if tools else {}
            ids = [f["id"] for g in ("reviewed", "added") for f in found.get(g, [])]
            self.seen.append(ids)
            cite = [i for i in ids if i == "finding:d9ed304a4ed8-3"] or ids[:1]
            answer = {"answer": "Tensile strength 12.27 MPa `%s`." % (cite[0] if cite else "none"), "citations": cite,
                      "findings": [], "limitations": [], "openQuestions": [],
                      "sources": [{"title": "Handbook", "url": "https://example.org/h", "doi": "", "locator": "Table 2",
                                   "excerpts": [], "supports": "no such value", "conditions": "", "readUrl": ""}]}
        elif schema is reviewer.CHECK_SCHEMA:
            kind, answer = "check", {"verdict": "pass", "resultGiven": True, "notes": "", "statements": [
                {"statement": "s", "verdict": "supported", "reason": "r", "kind": "completeness", "category": "none",
                 "evidence": "live"}]}
        elif "scores" in props:
            kind = "score"
            codes = [e["code"] for e in json.loads(prompt[prompt.index("\n[") + 1:])]
            fields = props["scores"]["items"]["properties"]
            answer = {"notes": "", "scores": [{k: (1 if v["type"] == "integer" else True) for k, v in fields.items()
                                               if k != "code"} | {"code": c} for c in codes]}
            if self.drop and self.drop(prompt):
                answer["scores"] = answer["scores"][1:]
        else:
            kind = "review"
            ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"] if f["id"] not in self.skip]
            answer = {"notes": "", "verdicts": [{"id": i, "verdict": "unsupported", "reason": "The source says otherwise.",
                                                 "excerpt": "", "material": ""} for i in ids]}
        self.calls.append(kind)
        self.engines.append((kind, engine))
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": 1000 if kind != "research" or "none" not in answer["answer"] else 2000,
                          "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 1.0}


class PartA(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-part-a-test-")
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name).resolve()
        self.root, self.into = self.tmp / "main", self.tmp / "harness"
        kf(self.root)
        k0 = self.tmp / "k0"  # what test 1's K0 is to KF: the store as it stood on 2026-10-02
        stores.built(self.tmp / "k0-build", "K0", self.root, lambda ws: stores.cut(ws, stores.CHECK), self.root)
        (self.tmp / "k0-build/K0").rename(k0)
        heldout = [{"id": "h%d" % n, "question": "What crystallinity did polymer %d reach in study %d?" % (n % 2, n),
                    "stratum": ("near", "mid", "far")[n % 3], "kind": "property", "material": "M%d" % n,
                    "property": "P%d" % n, "depth": "standard", "parent": {0: "q1", 1: "q6"}.get(n)} for n in range(6)]
        atomic_json(self.tmp / "heldout.json", heldout)
        atomic_json(self.tmp / "dev.json", [{"material": "D", "property": "P"}])
        atomic_json(self.tmp / "campaign.json", [ask_(q, "property", "polymer %s" % q, "crystallinity") for q in
                                                 ("q1", "q2", "q3", "q4", "q5", "q6")])  # first asks of the store's
        atomic_json(self.tmp / "planted/baseline.json", {"originals": PLANTED})
        patches = [(part_a, "ROOT", self.root), (part_a, "K0", k0), (part_a, "HELDOUT", self.tmp / "heldout.json"),
                   (part_a, "DEV", self.tmp / "dev.json"), (part_a, "CAMPAIGN", self.tmp / "campaign.json"),
                   (case_studies, "ROOT", self.root), (case_studies, "BASE", self.tmp / "case-studies-r1"),
                   (planted, "ROOT", self.root), (planted, "BASE", self.tmp / "planted"),
                   (case_studies, "frozen", lambda: "1c06a7f" + "0" * 33),
                   (part_a, "dirty", lambda: {})]  # the refusal of uncommitted code has its own test
        for target, name, value in patches:
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        pins = dict(part_a.PINS, promptVersion=ask.prompt_version(), kf=driver.fingerprint(self.root),
                    models={e: engines.ENGINES[e]["model"] for e in part_a.PINS["models"]},
                    release=read_json(self.root / "releases/current.json")["release_id"])
        for patch in (mock.patch.object(part_a, "PINS", pins), mock.patch.dict(part_a.LADDER, parents=3, least=2),
                      mock.patch.object(stores, "SIZES", (2, 4)), mock.patch.object(stores, "SEEDS", (1, 2)),
                      mock.patch.object(part_a, "CASE_STUDIES", ["case-studies-r2"]),
                      mock.patch.object(part_a, "PLANTED", ["planted-kf-r1"])):
            patch.start()
            self.addCleanup(patch.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.engine = Engine()
        real = driver.Guard

        def guard(deadline, base=None, **_):
            return real(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=self.engine,
                        signed=lambda e: True, base=base)
        patch = mock.patch.object(driver, "Guard", guard)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_cut_undoes_later_merges_and_reviews_and_keeps_earlier_verdicts(self):
        changes = {}
        store = stores.built(self.tmp / "cuts", "KF200", self.root,
                             lambda ws: changes.update(stores.cut(ws, stores.CUTS["KF200"])), self.root)
        self.assertEqual(changes, {"mergesUndone": 1, "reopened": 2, "earlierReviewKept": 1})
        got = store_ids(store)
        self.assertEqual({i for i in got["findings"] if i.startswith("finding:q")},
                         {"finding:q%d-%d" % (n, k) for n in range(1, 5) for k in (1, 2)} |
                         {"finding:q1-3", "finding:q1-4", "finding:q1-5", "finding:q2-9"})
        self.assertEqual(got["findings_fts"], got["findings"])  # the restored finding is searchable again
        self.assertEqual((got["merged"], "review-q1-cleanup" in got["reviews"], "q5" in got["deposits"]), (set(), False, False))
        rows = {f: knowledge.get(store, f) for f in ("finding:q1-3", "finding:q1-4", "finding:q1-5", "finding:q2-9")}
        self.assertEqual({f: r["status"] for f, r in rows.items()},
                         {"finding:q1-3": knowledge.UNCERTAIN, "finding:q1-4": knowledge.ACCEPTED,
                          "finding:q1-5": knowledge.UNREVIEWED, "finding:q2-9": knowledge.ACCEPTED})
        db = sqlite3.connect(knowledge.database(store))
        self.assertEqual(db.execute("SELECT reviewed_at, review_reason, detail FROM findings WHERE id='finding:q1-3'")
                         .fetchone()[:2], ("2026-10-01T13:00:00+00:00", "403"))
        db.close()
        self.assertIn("finding:q2-9", [f["id"] for f in knowledge.search(store, "restored duplicate crystallinity")["added"]])
        self.assertEqual(stores.built(self.tmp / "cuts", "KF200", self.root, lambda ws: 1 / 0), store)  # never rebuilt
        same = stores.compare(store, store)
        self.assertEqual((same["onlyStore"], same["onlyReference"], same["statusChanges"]), ([], [], {}))

    def test_resampled_stores_are_nested_reproducible_and_searchable(self):
        value = stores.resample(self.tmp / "resampled", self.root, (2, 4), (1, 2), self.root)
        questions = ["q%d" % n for n in range(1, 7)] + [p["question_id"] for p in PLANTED.values()]
        self.assertEqual(value["questions"], len(questions))  # not "legacy", not the deposit without records
        for seed in (1, 2):
            small, large = (store_ids(self.tmp / "resampled" / stores.name(n, seed)) for n in (2, 4))
            self.assertTrue(all(small[t] <= large[t] for t in small))
            order = value["orderings"][str(seed)]
            self.assertEqual(order, stores.ordering(questions, seed))
            for size, got in ((2, small), (4, large)):
                kept = set(order[:size]) | {"legacy"}
                self.assertIn("finding:legacy-1", got["findings"])
                self.assertEqual(got["deposits"], kept - {"legacy"})
                self.assertEqual({f.split(":")[1].rsplit("-", 1)[0] for f in got["notes"]} - {"legacy"},
                                 {q for q in kept if q.startswith("q")})
                self.assertEqual(got["findings_fts"], got["findings"])
                self.assertEqual(got["merged"], {"finding:q2-9"} if "q2" in kept else set())
                self.assertEqual(got["source_access"], {"q3"} & kept)
        again = stores.resample(self.tmp / "again", self.root, (2, 4), (1, 2), self.root)
        self.assertEqual(again["stores"], value["stores"])  # a seed gives the same store
        self.assertTrue(knowledge.search(self.tmp / "resampled" / stores.name(4, 1), "polymer 1 crystallinity")["reviewed"])

    def test_the_ladder_draws_parents_by_rule_and_words_their_revisits_as_the_campaign_did(self):
        rows, found = campaign(), {"t1": 3, "t2": 5, "t3": 4, "t4": 2, "t5": 9, "t6": 9, "t8": 3, "t9": 3}
        # t1 and t3 ask one pair twice (and t7 revisits t1), t4 has too few findings, t5 names two polymers, t6 is a
        # held-out pair: only t2, t8 and t9 may start a ladder
        self.assertEqual([q["taskId"] for q in part_a.candidates(rows, found, {("D", "P5")}, 3)], ["t2", "t8", "t9"])
        self.assertEqual([q["taskId"] for q in part_a.candidates(rows + [dict(rows[1], taskId="t10", revisit="exact",
                                                                             parent="t2")], found, {("D", "P5")}, 3)],
                         ["t8", "t9"])
        questions = part_a.ladder(rows, found, {("D", "P5")}, parents=3, least=3, seed="s")
        self.assertEqual(questions, part_a.ladder(rows, found, {("D", "P5")}, parents=3, least=3, seed="s"))
        parents = {q["parent"] for q in questions}
        self.assertEqual((len(questions), parents), (9, {"t2", "t8", "t9"}))
        by = {(q["parent"], q["stratum"]): q for q in questions}
        asked = {r["taskId"]: r for r in rows}
        texts = {r["question"] for r in rows}
        for parent in parents:
            self.assertEqual(by[parent, "exact"]["question"], asked[parent]["question"])
            self.assertNotIn(by[parent, "paraphrase"]["question"], texts)
            self.assertNotIn(by[parent, "sibling"]["question"], texts)
            self.assertEqual(by[parent, "paraphrase"]["kind"], asked[parent]["kind"])
        self.assertEqual(by["t2", "sibling"]["kind"], "property")  # a method question's sibling asks for the value
        with self.assertRaises(ValueError):
            part_a.ladder(rows, found, {("D", "P5")}, parents=4, least=3, seed="s")
        real = make_questions.sibling  # a parent whose sibling is word for word a campaign question is passed over
        with mock.patch.object(make_questions, "sibling", lambda q, rng: (rows[0]["question"], "property")
                               if q["taskId"] == "t8" else real(q, rng)):
            self.assertEqual({q["parent"] for q in part_a.ladder(rows, found, {("D", "P5")}, parents=2, least=3,
                                                                  seed="s")}, {"t2", "t9"})

    def test_prepare_writes_sharded_replicate_plans_with_their_pins_and_reports_them(self):
        layout = part_a.prepare("A2", shards=2, into=self.into)
        self.assertEqual((layout["folders"], layout["answers"]), (["r1-s1", "r1-s2", "r2-s1", "r2-s2", "r3-s1", "r3-s2"],
                                                                  6 * 8 * 3))
        self.assertEqual(layout["cuts"]["checkAgainstK0"]["statusChanges"], {})
        order = read_json(self.tmp / "heldout.json")
        random.Random(scaling.SEED).shuffle(order)
        base = self.into / "2026-10-kf-scaling"
        for name in layout["folders"]:
            plan, pins = read_json(base / name / "plan.json"), read_json(base / name / "pins.json")
            shard = int(name[-1])
            self.assertEqual([q["id"] for q in plan["questions"]], [q["id"] for q in order[shard - 1::2]])
            self.assertEqual([(a["name"], a["kind"], a["web"]) for a in plan["arms"]], [
                ("P", "plain", True), ("K0", "researcher", True), ("KF200", "researcher", True),
                ("KF1", "researcher", True), ("KF2", "researcher", True), ("KF", "researcher", True),
                ("MF1", "researcher", False), ("MF", "researcher", False)])
            self.assertEqual(plan["stores"]["KF"], part_a.PINS["kf"])
            self.assertEqual(plan["stores"]["MF1"], plan["stores"]["KF1"])
            self.assertEqual((pins["kind"], pins["tag"], pins["promptVersion"], set(pins["harness"])),
                             ("driver", "study-freeze-2", ask.prompt_version(), {"revision", "clean", "path"}))
        self.assertEqual(part_a.prepare("A2", shards=2, into=self.into)["at"], layout["at"])
        with self.assertRaises(SystemExit):
            part_a.prepare("A2", shards=3, into=self.into)  # a layout is fixed once written
        state = part_a.run(base / "r1-s1", hours=1)
        self.assertEqual(state["status"], "completed")
        self.assertEqual((self.engine.calls.count("plain"), self.engine.calls.count("research"),
                          self.engine.calls.count("check")), (3, 3 * 7, 3 * 8))
        self.assertEqual(read_json(base / "r1-s1/plan.json")["stores"]["KF"], driver.fingerprint(self.root))
        self.assertEqual(len((base / "r1-s1/runs.jsonl").read_text().splitlines()), 1)
        value = part_a.report("A2", into=self.into)
        arms = value["byStratum"]["all"]["arms"]
        self.assertEqual((arms["KF"]["answered"], arms["KF"]["complete"], arms["P"]["answered"]), (3, 3, 3))
        self.assertEqual(value["byStratum"]["all"]["paired"]["KF"]["tokens"]["median"], 1.0)
        self.assertEqual(set(value["byStratum"]["all"]["pairs"]), {"KF/P", "K0/P", "MF/KF", "MF/MF1"})
        self.assertEqual(value["byStratum"]["all"]["pairs"]["MF/MF1"]["resultGiven"]["mean"], 0)
        self.assertEqual((set(value["estimates"]), value["estimates"]["split"]["arms"]),
                         ({"slope", "passes", "split", "byReplicate"}, ["KF2", "K0"]))
        replicates = {r["replicate"] for r in read_json(base / "rows.json")}
        self.assertTrue(all(set(by) == replicates for by in value["estimates"]["byReplicate"].values()))
        self.assertEqual(json.loads((base / "r1-s1/runs.jsonl").read_text().splitlines()[-1])["codexFloor"],
                         common.FLOOR)
        rows = read_json(base / "rows.json")
        self.assertEqual(len(rows), 6 * 8 * 3)
        parent = {(r["id"], r["arm"]): r["parentInStore"] for r in rows}  # q1 is in every store, q6 only in KF
        self.assertEqual([parent["h0", a] for a in ("P", "K0", "KF200", "KF")], [None, True, True, True])
        self.assertEqual([parent["h1", a] for a in ("K0", "KF200", "KF2", "KF", "MF")], [False, False, True, True, True])
        a3 = part_a.prepare("A3", shards=1, into=self.into)
        self.assertEqual(a3["arms"], ["K0", "KF", "R2-s1", "R4-s1", "R2-s2", "R4-s2"])  # with same-day anchors
        a4 = part_a.prepare("A4", shards=1, into=self.into)
        self.assertEqual((a4["questions"], a4["arms"], len(a4["folders"])), (9, ["K0", "KF"], 2))

    def test_e8_answers_on_claude_code_and_is_checked_by_the_codex_checker(self):
        layout = part_a.prepare("E8", into=self.into)
        self.assertEqual((layout["folders"], layout["arms"], layout["answers"]), (["r1-s1"], ["K0c", "KFc"], 2 * 2))
        run = self.into / "2026-10-kf-e8/r1-s1"
        plan, pins = read_json(run / "plan.json"), read_json(run / "pins.json")
        self.assertEqual([q["id"] for q in plan["questions"]],  # the near stratum, in test 1's order
                         [q["id"] for q in part_a.heldout() if q["stratum"] == "near"])
        self.assertEqual([(a["name"], a["engine"], a["web"]) for a in plan["arms"]],
                         [("K0c", engines.CLAUDE, True), ("KFc", engines.CLAUDE, True)])
        self.assertEqual((plan["checker"], sorted(plan["models"])), (engines.CODEX, [engines.CLAUDE, engines.CODEX]))
        self.assertEqual((pins["engines"], pins["checker"], plan["stores"]["KFc"]),
                         ({"K0c": engines.CLAUDE, "KFc": engines.CLAUDE}, engines.CODEX, part_a.PINS["kf"]))
        with mock.patch.dict(part_a.PINS, models=dict(part_a.PINS["models"], **{engines.CLAUDE: "another-model"})):
            with self.assertRaisesRegex(SystemExit, "models"):
                part_a.run(run, hours=1)
        self.assertEqual(part_a.run(run, hours=1)["status"], "completed")
        self.assertEqual(sorted(set(self.engine.engines)), [("check", engines.CODEX), ("research", engines.CLAUDE)])
        self.assertEqual(len(self.engine.engines), 2 * 2 * 2)
        value = part_a.report("E8", into=self.into)
        self.assertEqual((value["reference"], value["byStratum"]["near"]["arms"]["KFc"]["answered"]), ("K0c", 2))
        self.assertIn("KFc", value["byStratum"]["near"]["paired"])

    def test_a5_replicates_run_end_to_end_and_report_with_the_first_run(self):
        layout = part_a.prepare("A5", into=self.into)
        self.assertEqual((layout["caseStudies"], layout["planted"]), (["case-studies-r2"], ["planted-kf-r1"]))
        cases, e9 = self.into / "case-studies-r2", self.into / "planted-kf-r1"
        self.assertEqual(read_json(cases / "pins.json")["stores"]["cs4-first"]["W"], part_a.PINS["kf"])
        self.assertEqual(planted.verdicts(e9 / "workspaces/planted")["gross"]["status"], knowledge.ACCEPTED)
        self.assertEqual(knowledge.get(e9 / "before/workspaces/C", "finding:d9ed304a4ed8-3")["value"], "70")
        self.assertEqual(part_a.run(cases, hours=1)["status"], "completed")
        calls = list(self.engine.calls)
        self.assertEqual((calls.count("plain"), calls.count("check"), calls.count("score")), (11, 27, 4))
        self.assertEqual(part_a.run(e9, hours=1)["status"], "completed")
        e9calls = self.engine.calls[len(calls):]
        self.assertEqual((e9calls.count("research"), e9calls.count("check"), e9calls.count("review"),
                          e9calls.count("score")), (25, 25, 1, 1))  # then one blind scoring session
        prompt = self.engine.prompts[-1]
        self.assertTrue("sourceValue" in prompt and "finding:" not in prompt and '"arm"' not in prompt)
        self.assertEqual(len(read_json(e9 / "scoring/e9-key.json")["key"]), 25)
        self.assertTrue(all("finding:d9ed304a4ed8-3" not in ids for ids in self.engine.seen[-10:]))  # hidden after review
        value = part_a.report("A5", into=self.into)
        self.assertEqual(value["plantedTotal"]["gross/A"]["citesPlanted"], 2)
        self.assertEqual((value["plantedTotal"]["gross/A"]["blindScored"], value["plantedTotal"]["gross/B"]["presentsPlanted"]),
                         (2, 2))  # the scripted scorer says yes to everything
        self.assertEqual(value["plantedTotal"]["gross/review"], {knowledge.UNSUPPORTED: 1})
        self.assertEqual(value["caseStudiesTotal"]["cs1-conditions/R"]["answered"], 3)
        self.assertEqual(value["caseStudiesTotal"]["blind cs4/first"]["answers"], 3)
        before = len(self.engine.calls)
        part_a.run(cases, hours=1), part_a.run(e9, hours=1)  # resuming asks nothing again
        self.assertEqual(len(self.engine.calls), before)

    def test_cs4_first_askings_retry_transient_failures_and_record_others_as_final(self):
        part_a.prepare("A5", into=self.into)
        cases, made, real = self.into / "case-studies-r2", [], ask.Questions
        left = {"rate-limited": 1}

        def fail(kind, prompt):
            if kind == "research" and "reported for novoloid (Kynol) fibers" in prompt and left["rate-limited"]:
                left["rate-limited"] -= 1
                return "rate-limited"
            if kind == "research" and "creep compliance has been reported" in prompt:
                return "crashed"  # every time: failed for good after the app's own retry
        self.engine.fail = fail
        with mock.patch.object(case_studies.ask, "Questions", lambda *a, **k: made.append(k) or real(*a, **k)):
            first = part_a.run(cases, hours=1)
            second = part_a.run(cases, hours=1)
        self.assertEqual((first["status"], first["stopReason"]), ("stopped", "cs4 first askings incomplete"))
        self.assertEqual(second["status"], "completed")  # the replicate goes on without the failed one
        self.assertEqual({k.get("review_engine") for k in made}, {engines.CODEX})
        ws = cases / "cs4-first/workspaces/W"
        novoloid = read_json(ask.folder(ws) / hashlib.md5(b"oopc-cs4-novoloid").hexdigest() / "question.json")
        self.assertEqual((novoloid["status"], len(novoloid["failedRuns"])), ("completed", 1))
        self.assertNotEqual(novoloid["runId"], novoloid["failedRuns"][0])  # asked again on a fresh trace run
        creep = read_json(cases / "cs4-first/items/fepm-creep.json")
        self.assertEqual((creep["state"], creep["error"]["reason"], case_studies.final(creep)), ("failed", "crashed", True))
        self.assertEqual(self.engine.calls.count("failed-research"), 3)  # novoloid once, the creep question twice

    def test_e9_review_failures_are_retried_and_a_skipped_plant_does_not_hold_the_replicate(self):
        part_a.prepare("A5", into=self.into)
        e9, left = self.into / "planted-kf-r1", {"n": 2}

        def fail(kind, prompt):
            if kind == "review" and left["n"]:
                left["n"] -= 1
                return "rate-limited"
        self.engine.fail, self.engine.skip = fail, {"finding:3cc0b647b329-12"}  # the subtle plant left unassessed
        states = [part_a.run(e9, hours=1) for _ in range(3)]
        self.assertEqual([s.get("stopReason") for s in states[:2]], ["review: rate-limited"] * 2)
        self.assertEqual(states[2]["status"], "completed")
        self.assertEqual(planted.review_state(e9 / "workspaces/planted")["status"], "reviewed")
        record = read_json(e9 / "review.json")
        self.assertEqual(([f["transient"] for f in record["failures"]], record["skipped"]), ([True, True], ["subtle"]))
        self.assertEqual(part_a.report("A5", into=self.into)["plantedTotal"]["subtle/review"], {"skipped": 1})

    def test_an_e9_review_that_fails_twice_for_another_reason_is_final(self):
        part_a.prepare("A5", into=self.into)
        e9 = self.into / "planted-kf-r1"
        self.engine.fail = lambda kind, prompt: "invalid-output" if kind == "review" else None
        state = part_a.run(e9, hours=1)
        self.assertEqual((state["status"], state["stopReason"].startswith("review failed")), ("failed", True))
        part_a.run(e9, hours=1)  # recorded: no session is spent on it again
        self.assertEqual(self.engine.calls.count("failed-review"), 2)
        self.assertFalse((e9 / "after/plan.json").exists())

    def test_blind_scoring_that_leaves_out_a_code_is_redone_once(self):
        part_a.prepare("A5", into=self.into)
        cases, left = self.into / "case-studies-r2", {"n": 1}

        def drop(prompt):
            if "glass transition temperature (Tg)" in prompt and left["n"]:  # cs1's rubric
                left["n"] -= 1
                return True
        self.engine.drop = drop
        self.assertEqual(part_a.run(cases, hours=1)["status"], "completed")
        self.assertEqual(self.engine.calls.count("score"), 5)  # cs1 twice, then cs2, cs3 and cs4
        self.assertEqual(read_json(cases / "scoring/cs1-conditions.json")["attempts"], 2)

    def test_a_scoring_failure_that_repeats_is_final_and_costs_no_session_on_a_relaunch(self):
        part_a.prepare("A5", into=self.into)
        cases = self.into / "case-studies-r2"
        self.engine.drop = lambda prompt: "glass transition temperature (Tg)" in prompt
        state = part_a.run(cases, hours=1)
        self.assertEqual((state["status"], state["scoringFailed"]), ("completed", ["cs1-conditions"]))
        sessions = self.engine.calls.count("score")
        part_a.run(cases, hours=1)
        self.assertEqual((sessions, self.engine.calls.count("score")), (5, 5))
        entries = [{"question": "q", "arm": a, "text": "Tg 50 °C", "questionText": "Q?"} for a in ("R", "P")]
        self.engine.drop = None
        self.engine.fail = lambda kind, prompt: "quota" if kind == "score" else None  # transient: not counted
        score.groups(self.tmp / "scored", {"cs1-conditions": entries}, runner=self.engine)
        self.assertEqual(read_json(self.tmp / "scored/scoring/cs1-conditions.json")["attempts"], 0)
        self.assertEqual(score.pending(self.tmp / "scored", ["cs1-conditions"])["pending"], ["cs1-conditions"])
        self.engine.fail = None
        score.groups(self.tmp / "scored", {"cs1-conditions": entries}, runner=self.engine)
        self.assertEqual(score.pending(self.tmp / "scored", ["cs1-conditions"]), {"pending": [], "failed": []})

    def test_scoring_waits_until_every_item_is_settled(self):
        part_a.prepare("A5", into=self.into)
        cases = self.into / "case-studies-r2"
        self.assertFalse(case_studies.settled(cases))
        state = part_a.scored({"status": "completed"}, cases, case_studies.settled(cases), lambda guard: 1 / 0, [], 1)
        self.assertEqual(state["stopReason"], "items not settled")
        part_a.run(cases, hours=1)
        self.assertTrue(case_studies.settled(cases))
        item = cases / "cs1-conditions/items/0000-R.json"
        value = read_json(item)
        value.pop("check")
        atomic_json(item, value)
        self.assertFalse(case_studies.settled(cases))
        value["check"] = {"error": {"reason": "timeout"}}  # a check that failed after its retry is final
        atomic_json(item, value)
        self.assertTrue(case_studies.settled(cases))

    def test_a_stop_file_in_a_replicate_folder_stops_its_parts(self):
        part_a.prepare("A5", into=self.into)
        for base in (self.into / "case-studies-r2", self.into / "planted-kf-r1"):
            (base / "STOP").write_text("")
            state = part_a.run(base, hours=1)
            self.assertEqual((state["status"], state["stopReason"]), ("stopped", "owner-stop"))
        self.assertEqual(self.engine.calls, [])

    def test_the_2026_10_13_e9_answers_are_scored_blind_with_the_same_rubric_read_only(self):
        for item in planted.PLANTS:
            for arm, reps in planted.ARMS.items():
                for rep in range(reps):
                    atomic_json(planted.result_path(item, arm, rep, "answer"), {"answer": {
                        "answer": "It reached %s `finding:x-1`." % planted.VALUES[item["case"]][0], "limitations": []}})
        old = sorted((str(p), p.stat().st_mtime_ns) for p in (self.tmp / "planted").rglob("*"))
        value = part_a.score_record(into=self.into)
        self.assertEqual((value["pending"], value["failed"], value["report"]["e9/A"]["answers"]), ([], [], 10))
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in (self.tmp / "planted").rglob("*")), old)
        self.assertEqual(len(read_json(self.into / "2026-10-kf-a5/e9-2026-10-13/scoring/e9-key.json")["key"]), 25)
        prompt = self.engine.prompts[-1]
        self.assertTrue("plantedValue" in prompt and "finding:" not in prompt and '"arm"' not in prompt)
        self.assertEqual(self.engine.calls, ["score"])

    def test_uncommitted_code_or_harness_is_refused_and_the_revision_is_the_harness_repository(self):
        repo = self.tmp / "repo"
        for path in ("oopc/a.py", "config/b.json", "studies/macromolecules/part_a/c.py"):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text("x\n")
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *a], cwd=repo,
                                        check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        git("add", ".")
        git("commit", "-q", "-m", "harness")
        with mock.patch.object(common, "CODE", repo), mock.patch.object(part_a, "HARNESS",
                                                                         repo / "studies/macromolecules/part_a"):
            self.assertEqual((DIRTY(), part_a.revision()["revision"]), ({}, git("rev-parse", "HEAD")))
            (repo / "oopc/a.py").write_text("y\n")
            self.assertEqual(list(DIRTY()), ["code"])
            with mock.patch.object(part_a, "dirty", DIRTY), self.assertRaisesRegex(SystemExit, "Uncommitted"):
                part_a.pinned()
            git("checkout", "oopc/a.py")
            (repo / "studies/macromolecules/part_a/c.py").write_text("y\n")
            self.assertEqual((list(DIRTY()), part_a.revision()["clean"]), (["harness"], False))

    def test_nothing_prepares_or_runs_unless_the_code_is_the_tag_and_the_pins_hold(self):
        repo = self.tmp / "other-code"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *a], cwd=repo,
                                        check=True, capture_output=True)
        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "not the tag")
        with mock.patch.object(case_studies, "frozen", FROZEN), mock.patch.object(case_studies, "ROOT", common.ROOT), \
                mock.patch.object(common, "CODE", repo):  # the real check, on code at another commit
            with self.assertRaises(SystemExit):
                part_a.prepare("A2", into=self.into)
            with self.assertRaises(SystemExit):
                part_a.prepare("A5", into=self.into)
        self.assertFalse(self.into.exists())
        part_a.prepare("A4", into=self.into)
        with mock.patch.dict(part_a.PINS, promptVersion="000000000000"):
            with self.assertRaisesRegex(SystemExit, "promptVersion"):
                part_a.run(self.into / "2026-10-kf-ladder/r1-s1", hours=1)
        with locked(self.into / "2026-10-kf-ladder/r1-s1/run.lock"):  # another process runs this folder
            with self.assertRaisesRegex(SystemExit, "Another process"):
                part_a.run(self.into / "2026-10-kf-ladder/r1-s1", hours=1)
        self.assertEqual(self.engine.calls, [])


FROZEN = case_studies.frozen  # the real check, before setUp replaces it
DIRTY = part_a.dirty  # likewise


class Estimators(unittest.TestCase):
    """The estimators recover what synthetic answers were made with."""

    def rows(self, slope=-0.1, parent=-0.5):
        rows = []
        for q in range(8):
            for findings, present in ((150, False), (1000, False), (1000, True), (8000, True)):
                tokens = math.exp(10 + 0.1 * q + slope * math.log(findings) + parent * present)
                rows.append({"id": "q%d" % q, "stratum": "near", "arm": "R%d%s" % (findings, "p" * present),
                             "replicate": 1, "answered": True, "checked": True, "newTokens": tokens,
                             "webCalls": 4 - 2 * present, "storeFindings": findings, "parentInStore": present,
                             "resultGiven": not present, "pass": (q + findings) % 3 > 0})
        return rows

    def test_slope_coverage_split_pairs_and_passes(self):
        self.assertAlmostEqual(estimate.slope(self.rows(parent=0))["near"]["estimate"], -0.1, places=4)
        found = estimate.coverage(self.rows())
        self.assertAlmostEqual(found["logFindings"]["estimate"], -0.1, places=4)
        self.assertAlmostEqual(found["parentInStore"]["multiplier"], round(math.exp(-0.5), 3), places=3)
        rows = self.rows()
        pair = estimate.paired(rows, "R1000p", "R1000")
        self.assertEqual((pair["tokens"]["median"], pair["webCalls"]["mean"], pair["webRatio"], pair["resultGiven"]["mean"]),
                         (round(math.exp(-0.5), 3), -2, 0.5, -1))
        mixed = [dict(r, arm="KF2", parentInStore=r["id"] in ("q0", "q1", "q2", "q3")) for r in rows if r["arm"] == "R1000"]
        mixed = [dict(r, newTokens=r["newTokens"] * (0.5 if r["parentInStore"] else 1)) for r in mixed]
        base = [dict(r, arm="K0") for r in rows if r["arm"] == "R1000"]
        split = estimate.split(mixed + base, "KF2", "K0")
        self.assertEqual((split["n"], split["ratio"]), ([4, 4], 0.5))
        self.assertTrue({"logFindings"} <= set(estimate.passes(rows)) or {"unavailable"} & set(estimate.passes(rows))
                        or "error" in estimate.passes(rows))


def ask_(task, kind, material, prop, variant=0, **extra):
    """A campaign first ask, worded by the campaign's own phrasings."""
    form = extra.get("form", kind)
    text = make_questions.PHRASES[form][variant].format(p=prop, m=material, f=extra.get("factor", ""), ms=material)
    return dict(taskId=task, kind=kind, materials=[material], property=prop, variant=variant, question=text,
                revisit=None, number=int(task[1:]), wave=1, **extra)


def campaign():
    """Campaign rows: first asks of each kind (two with the same pair), a comparison and a revisit."""
    return [ask_("t1", "property", "A", "P1"), ask_("t2", "method", "B", "P2", 1), ask_("t3", "property", "A", "P1", 2),
            ask_("t4", "property", "C", "P3"), dict(ask_("t5", "comparison", "A and B", "P4"), materials=["A", "B"]),
            ask_("t6", "property", "D", "P5"), dict(ask_("t7", "property", "A", "P1"), revisit="exact", parent="t1"),
            ask_("t8", "effect", "E", "P6", factor="annealing"),
            ask_("t9", "assessment", "F", "P7", form="assessment-grades")]


@unittest.skipUnless(all(p.exists() for p in (part_a.HELDOUT, part_a.CAMPAIGN, part_a.DEV, knowledge.database(part_a.ROOT),
                                              planted.BASE / "baseline.json")),
                     "needs the private records (held-out, campaign and dev questions, KF, E9's record); set "
                     "OOPC_STUDY_ROOT to the main checkout")
class RealInputs(unittest.TestCase):
    """The real inputs, read-only: KF is the pinned store, the five E9 source findings are unchanged since 2026-10-13,
    and the ladder finds 30 parents with at least 3 findings each, outside the held-out and dev pairs. KF is read from
    its frozen copy (`analysis/kf.py`): the live store, KF while Part A ran, has taken new questions since 2026-10-25."""

    def test_kf_the_plants_and_the_ladder(self):
        frozen = common.analysis_dir("kf") / "workspaces/KF"
        if not knowledge.database(frozen).exists():
            self.skipTest("needs KF's frozen copy (analysis/kf.py store())")
        self.assertEqual(driver.fingerprint(frozen), part_a.PINS["kf"])
        self.assertEqual(planted.unchanged(frozen, read_json(planted.BASE / "baseline.json")["originals"]), {})
        questions = part_a.ladder_questions()
        parents = {q["parent"]: q for q in questions}
        avoid = {(q["material"], q["property"]) for q in read_json(part_a.HELDOUT) + read_json(part_a.DEV)}
        self.assertEqual((len(questions), len(parents)), (90, 30))
        self.assertTrue(all(q["parentFindings"] >= 3 and (q["material"], q["property"]) not in avoid
                            for q in parents.values()))
        campaign = read_json(part_a.CAMPAIGN)
        revisited = {q.get("parent") for q in campaign if q.get("revisit")}
        asked = [(m, q["property"]) for q in campaign if q.get("revisit") is None for m in q["materials"]]
        texts = {q["question"] for q in campaign}
        self.assertFalse(set(parents) & revisited)
        self.assertTrue(all(asked.count((q["material"], q["property"])) == 1 for q in parents.values()))
        self.assertFalse({q["question"] for q in questions if q["stratum"] != "exact"} & texts)
        self.assertEqual(len(part_a.heldout()), 60)


if __name__ == "__main__":
    unittest.main()
