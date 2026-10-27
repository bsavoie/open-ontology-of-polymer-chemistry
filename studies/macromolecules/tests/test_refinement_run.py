"""Part C's driver plans offline, in a temporary world built as overlay.py builds the real one (its own pinned seed
snapshot, an overlay of approved edits, `overlay.build`: the seed and release O, the four stores under
`stores/workspaces/` and `overlay/fingerprint.json`), with H, N and L fixed by hash and everything committed in a
commitments.json of its own: the pilot's, screen's and case studies' arms, stores, releases and question order; the
stores read where the build made them; the case questions written for the purpose (questions.py write-C, scripted)
read into the cases' plan; every refusal (the code is not the tag, a store or its tables not the recorded ones, the
three tables where they should not be or missing where they should, release O being the seed, the question sets not
their hashes, a commitment missing or not what the private files hold, the pilot unchecked); and the pilot and the
screen run end to end with a scripted engine behind the study Guard. `World` and `Engine` are shared with
test_refinement_lookup.py."""
import contextlib, hashlib, io, json, random, re, sqlite3, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests folder, for the overlay test's snapshot helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import lookup, mine, overlay, pins, propose, questions, run  # noqa: E402
from part_a import part_a  # noqa: E402
from oopc import ask, engines, knowledge, reviewer  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from test_refinement_overlay import edit, polymer  # noqa: E402

SNAPSHOT = {"schema": "wop-publication-snapshot-v2", "methodology": {}, "chemicalStructures": [], "aliases": [],
            "searchTerms": [], "polymers": [
                polymer(1, "Polylactide", ["PLA"]), polymer(2, "Polycaprolactone", ["PCL"]),
                polymer(9, "Polyethylene family", ["PE"], narrower=(11,), kind="family"),
                polymer(10, "High-density polyethylene", ["HDPE"]),
                polymer(11, "Low-density polyethylene", ["LDPE"], broader=(9,))]}  # the seed lacks HDPE's family link
EDITS = [edit("name", {"polymer": "wop-000001", "field": "tradeNames", "name": "Ingeo", "ambiguous": False}),
         edit("family-link", {"narrower": "wop-000010", "broader": "wop-000009"})]  # release O's two edits
LINK = edit("source-link", {"a": "doi:10.1/b", "relation": "supplement-of", "b": "doi:10.1/a"},
            sources=(("https://doi.org/10.1/b", "Supporting information for the article"),), misses=(), hops=("h-001",))
FINDINGS = [  # id, statement, material, subject (KF), doi
    ("finding:pla-1", "PLA film had a tensile strength of 60 MPa.", "PLA film", "wop-000001", "10.1/a"),
    ("finding:ingeo-1", "Ingeo 4043D sheet had a tensile strength of 55 MPa.", "Ingeo 4043D", "", "10.1/b"),
    ("finding:hdpe-1", "HDPE bars had a tensile strength of 25 MPa.", "HDPE", "wop-000010", "10.1/c"),
    ("finding:pcl-1", "PCL film had a tensile strength of 20 MPa.", "PCL", "wop-000002", "10.1/d"),
    ("finding:ldpe-1", "LDPE film had a tensile strength of 10 MPa.", "LDPE", "wop-000011", "10.1/e")]


def question(identifier, name, text, materials, ids, kind, stratum, **extra):
    return dict({"id": identifier, "set": name, "question": text, "materials": materials, "polymerIds": ids,
                 "property": "tensile strength", "kind": kind, "group": kind, "stratum": stratum, "depth": "standard"},
                **extra)


SETS = {
    "H": [question("h-family", "H", "Report a published value of tensile strength for polyethylene, with the specimen.",
                   ["polyethylene"], ["wop-000009"], "property", "near", material="polyethylene"),
          question("h-pcl", "H", "Report a published value of tensile strength for PCL, with the specimen.", ["PCL"],
                   ["wop-000002"], "method", "mid", material="PCL")],
    "N": [question("n-pla", "N", "What tensile strength has been reported for PLA? Give the value with units.", ["PLA"],
                   ["wop-000001"], "property", "asked-pair"),
          question("n-ldpe", "N", "Find a published measurement of tensile strength for LDPE.", ["LDPE"], ["wop-000011"],
                   "property", "asked-polymer")],
    "L": [question("l-name", "L", "What tensile strength has been reported for Ingeo 4043D sheet?", ["Ingeo 4043D"],
                   ["wop-000001"], "name", "tertile-1", askedName="Ingeo 4043D"),
          question("l-value", "L", "Report a tensile strength of HDPE with its test method and specimen.", ["HDPE"],
                   ["wop-000010"], "value", "tertile-2")]}
# What the scripted researcher searches besides the canonical query: (query, limit), None for the tool's default.
ISSUED = {"l-name": [("polylactide tensile strength", None)], "n-ldpe": [("PCL tensile strength", 25)]}
RELEVANT = {"h-family": ("HDPE", "LDPE"), "h-pcl": ("PCL",), "n-pla": ("PLA", "Ingeo"), "n-ldpe": ("LDPE",),
            "l-name": ("PLA", "Ingeo"), "l-value": ("HDPE",)}  # what the scripted judge calls relevant


def store(root, rows):
    with knowledge.connect(root) as db:
        for identifier, statement, material, subject, doi in rows:
            knowledge._insert_finding(db, identifier, "q-" + identifier, "research", knowledge.clean_finding({
                "statement": statement, "material": material, "property": "tensile strength", "value": "1",
                "unit": "MPa", "conditions": "23 °C", "subject": subject, "sourceTitle": "Paper " + doi,
                "sourceUrl": "https://example.org/" + doi, "sourceDoi": doi, "locator": "Table 1",
                "excerpt": statement[:40], "needsReview": False, "reviewFlag": ""}),
                status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-10-10T00:00:00+00:00")


def execute(root, *statements):
    db = sqlite3.connect(knowledge.database(root))
    for statement in statements:
        db.execute(statement)
    db.commit()
    db.close()


class World:
    """A temporary Part C world, built by overlay.py from a tiny pinned seed and the overlay `edits`: the seed root and
    release O, the stores K0, K0-refined, KF and KF-refined under `stores/workspaces/` with `overlay/fingerprint.json`;
    H, N and L fixed by hash, a derivation pool, and every entry committed (`questions.py commit`, `run.py commit`) in
    a commitments.json of the world's own; the pins point at it, `pins.frozen` passes and the code counts as
    committed."""

    def __init__(self, test, sets=SETS, edits=EDITS):
        folder = tempfile.TemporaryDirectory(prefix="oopc-refinement-test-")
        test.addCleanup(folder.cleanup)
        self.top = Path(folder.name).resolve()
        self.base = self.top / "run"
        quiet = contextlib.redirect_stdout(io.StringIO())  # the Guard and emit print every event
        quiet.__enter__()
        test.addCleanup(quiet.__exit__, None, None, None)
        seed_file = self.top / "seed.json"
        seed_file.write_bytes(json.dumps(SNAPSHOT).encode())
        atomic_json(self.top / "seed-lock.json", {"file": str(seed_file),
                                                  "sha256": hashlib.sha256(seed_file.read_bytes()).hexdigest()})
        store(self.top / "KF", FINDINGS)
        store(self.top / "test-1-K0", FINDINGS[:1])  # test 1's K0, which the K0 stores copy
        commitments = self.top / "commitments.json"
        atomic_json(commitments, dict({k: {} for k in questions.ENTRIES}, format=questions.COMMITTED))
        for patch in (mock.patch.object(pins, "BASE", self.base),
                      mock.patch.dict(pins.FOLDERS, {k: self.base / k for k in pins.FOLDERS}),
                      mock.patch.object(pins, "KF", self.top / "KF"),
                      mock.patch.object(pins, "K0", self.top / "test-1-K0"),
                      mock.patch.object(pins, "frozen", lambda: "3" * 40),
                      mock.patch.object(overlay, "SEED_LOCK", self.top / "seed-lock.json"),
                      mock.patch.object(overlay, "QUESTIONS_ROOT", self.top / "data"),
                      mock.patch.object(questions, "COMMITMENTS", commitments),
                      mock.patch.object(part_a, "dirty", lambda: {}), mock.patch.object(driver, "PASS_WAIT", 0)):
            patch.start()
            test.addCleanup(patch.stop)
        self.seed = overlay.release(self.top / "reference")  # what the pinned snapshot builds: the pinned release
        patch = mock.patch.dict(pins.PINS, release=self.seed, kf=driver.fingerprint(pins.KF),
                                promptVersion=ask.prompt_version(),
                                models={k: engines.ENGINES[run.ENGINE_OF[k]]["model"] for k in pins.PINS["models"]})
        patch.start()
        test.addCleanup(patch.stop)
        for name, value in propose.overlay_files(edits).items():
            atomic_json(pins.folder("overlay") / name, value, private=True)
        atomic_json(pins.folder("mine") / "effects.json", {  # the drop step's record, which the build needs
            "format": mine.FORMATS["effects"], "complete": True, "inputs": mine.effect_inputs(pins.frozen()),
            "edits": {e: {} for e in read_json(pins.folder("overlay") / "edits.json")["edits"]}, "dropped": []})
        self.built = overlay.build()
        self.refined = self.built["releases"]["refined"]
        for name, rows in sets.items():
            atomic_json(questions.path(name + ".json"), rows)
        questions.hashes()
        atomic_json(pins.folder("mine") / "pool.json", {"answers": ["a-1", "a-2"]})
        questions.commit_questions(write=True)
        run.commit(write=True)

    def store(self, name):
        """A store root as the build made it and recorded it."""
        return Path(self.built["roots"][name])

    def guard(self, engine, quota=80):
        (self.top / "guard").mkdir(exist_ok=True)
        engine.guard = driver.Guard(time.time() + 3600, read_quota=lambda e: {"remainingPercent": quota},
                                    run_session=engine, signed=lambda e: True, base=self.top / "guard")
        return engine.guard


class Engine:
    """Answers by schema, like a real engine. The researcher searches its question's material and property (and, for the
    questions in ISSUED, those calls too) and cites what it found; the checker passes; the judge calls a finding relevant
    when it names one of RELEVANT's words for the question; the case-question writer writes each item's material and
    property into a question. Every prompt is kept."""

    def __init__(self, sets=SETS):
        self.calls, self.prompts = [], []
        self.questions = [q for rows in sets.values() for q in rows]

    def asked(self, prompt):
        return next(q for q in self.questions if q["question"] in prompt)

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None,
                 **session):
        if session.get("resume"):  # The researcher's second turn (2026-10-25 on): no findings, no cost, not counted.
            return {"engine": engine, "model": "scripted", "sessionId": session["resume"], "answer": {
                "answer": "", "citations": [], "findings": [], "sources": [], "limitations": [], "openQuestions": []},
                "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}, "observedTools": [],
                "agentSeconds": 0.0}
        self.prompts.append(prompt)
        if schema is ask.ANSWER_SCHEMA:
            q = self.asked(prompt)
            self.calls.append(("research", q["id"], engine))
            cited = []
            for query, limit in [("%s %s" % (q["materials"][0], q["property"]), None)] + ISSUED.get(q["id"], []):
                found = tools.call("search_knowledge", dict({"q": query}, **({"limit": limit} if limit else {})))
                cited += [f["id"] for group in ("reviewed", "added") for f in found.get(group, [])]
            answer = {"answer": "It reached 60 MPa `%s`." % (cited[0] if cited else "none"), "citations": cited[:1],
                      "findings": [], "sources": [], "limitations": [], "openQuestions": []}
        elif schema is lookup.JUDGE_SCHEMA:
            q = self.asked(prompt)
            self.calls.append(("judge", q["id"], engine))
            listed = re.findall(r"^(\d+)\. (.*)$", prompt.split("\nFindings:\n", 1)[1], re.M)
            answer = {"judgements": [{"number": int(n), "relevant": any(w in line for w in RELEVANT[q["id"]]),
                                      "reason": "scripted"} for n, line in listed]}
        elif schema is reviewer.CHECK_SCHEMA:
            self.calls.append(("check", None, engine))
            answer = {"verdict": "pass", "resultGiven": True, "notes": "", "statements": [
                {"statement": "s", "verdict": "supported", "reason": "r", "kind": "source-fact", "category": "none",
                 "evidence": "live"}]}
        elif schema is questions.C_SCHEMA:
            items = json.loads(prompt.split("\nItems:\n", 1)[1])
            self.calls.append(("case-questions", re.search(r"The case: (.*)", prompt).group(1), engine))
            answer = {"questions": [{"item": i["item"], "question": "What %s has been reported for %s?" % (
                i["property"], i["material"]), "declined": False, "reason": ""} for i in items]}
        else:
            raise AssertionError("an unexpected session")
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer,
                "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 1.0}


def plain(fingerprint):
    return {k: fingerprint[k] for k in run.FINGERPRINT}


class RunPlans(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def test_the_stores_are_read_where_the_build_made_them(self):
        recorded = read_json(pins.folder("overlay") / "fingerprint.json")
        for arm, (name, _) in pins.ARMS.items():
            self.assertEqual(run.store_root(arm), Path(recorded["roots"][name]))
            self.assertEqual(run.store_root(arm).parent, (pins.folder("stores") / "workspaces").resolve())
        self.assertEqual(run.recorded()["KF-refined"], overlay.describe(self.world.store("KF-refined")))
        self.assertIsNone(run.recorded()["KF"]["tables"])
        self.assertEqual(knowledge.polymer_ids(self.world.store("KF-refined"), "Ingeo"), {"wop-000001"})
        self.assertEqual(self.world.refined, run.release_id(self.world.store("KF-refined")))
        atomic_json(pins.folder("overlay") / "fingerprint.json", dict(recorded, roots={}))
        with self.assertRaisesRegex(SystemExit, "does not record the fingerprint, table hash and root of K0"):
            run.store_root("B")

    def test_the_screen_has_the_three_arms_on_their_stores_and_releases_in_one_seeded_order(self):
        layout = run.prepare_screen(shards=2)
        order = [q for name in ("H", "N", "L") for q in SETS[name]]
        random.Random(run.SCREEN_SEED).shuffle(order)
        self.assertEqual(layout["order"], [q["id"] for q in order])
        self.assertEqual((layout["shards"], layout["folders"], layout["arms"]), (2, ["s1", "s2"], ["B0", "B", "Oplus"]))
        stores = run.recorded()
        for s in (1, 2):
            plan = read_json(pins.folder("screen") / ("s%d" % s) / "plan.json")
            self.assertEqual([q["id"] for q in plan["questions"]], [q["id"] for q in order[s - 1::2]])
            self.assertEqual([a["name"] for a in plan["arms"]], ["B0", "B", "Oplus"])
            self.assertTrue(all(a["engine"] == "codex" and a["web"] and a["depth"] == "standard" and "prompt" not in a
                                for a in plan["arms"]))
            self.assertEqual((plan["checker"], plan["promptVersion"]), ("codex", ask.prompt_version()))
            self.assertEqual(plan["stores"], {"B0": plain(stores["K0"]), "B": plain(stores["KF"]),
                                              "Oplus": plain(stores["KF-refined"])})
            roots = run.plan_arms(pins.folder("screen") / ("s%d" % s))
            self.assertEqual({a: run.release_id(r) for a, r in roots.items()},
                             {"B0": self.world.seed, "B": self.world.seed, "Oplus": self.world.refined})
            self.assertEqual({a: run.tables(r) for a, r in roots.items()},
                             {"B0": set(), "B": set(), "Oplus": set(pins.TABLE_NAMES)})
            self.assertTrue(all(Path(r).parent == pins.folder("screen") / ("s%d" % s) / "workspaces"
                                for r in roots.values()))  # every arm on its own copy
            recorded = read_json(pins.folder("screen") / ("s%d" % s) / "pins.json")
            self.assertEqual((recorded["kind"], recorded["shard"], recorded["arms"]["Oplus"]),
                             ("screen", s, ["KF-refined", "release-root"]))
            self.assertEqual(recorded["commitments"]["overlay"], questions.commitments()["overlay"])
        self.assertEqual(run.prepare_screen(shards=2)["order"], layout["order"])  # fixed once written
        with self.assertRaisesRegex(SystemExit, "fixed once written"):
            run.prepare_screen(shards=3)

    def test_the_pilot_takes_the_first_question_of_each_set_in_the_screens_order(self):
        order = run.screen_order()
        plan = run.prepare_pilot()
        self.assertEqual([q["set"] for q in plan["questions"]], ["H", "N", "L"])
        self.assertEqual([q["id"] for q in plan["questions"]],
                         [next(q["id"] for q in order if q["set"] == s) for s in ("H", "N", "L")])
        self.assertEqual([a["name"] for a in plan["arms"]], list(pins.SCREEN_ARMS))

    def test_the_cases_answer_each_picked_question_once_on_four_arms_in_five_replicates(self):
        atomic_json(pins.folder("cases") / "selection.json", {"cases": {"C6": [
            {"set": "written", "question": "What is the tensile strength of polybar?", "reason": "nothing saved"}]}})
        with self.assertRaisesRegex(SystemExit, "comes from questions/C.json"):  # written questions are fixed first
            run.selection()
        rules = {c: "the rule of %s" % c for c in ("C1", "C2", "C3", "C6", "C7")}
        atomic_json(pins.folder("cases") / "selection.json", {"rules": rules, "cases": {
            "C1": [{"id": "l-name", "set": "L", "reason": "Ingeo is unknown to the seed"}],
            "C3": [{"id": "h-family", "set": "H", "reason": "HDPE's family link"}],
            "C7": [{"id": "l-name", "set": "L", "reason": "C1's question on K0", "reuses": "C1"},
                   {"question": "h-family", "set": "H", "reason": "C3's question on K0", "reuses": "C3"}],
            "C2": [], "C6": []}, "shortfalls": {"C1": 2, "C2": 3, "C3": 2, "C6": 3, "C7": 1}})
        with self.assertRaisesRegex(SystemExit, "short of three questions: write them first"):
            run.prepare_cases()
        replay = {"refined": ["finding:pla-1"]}
        atomic_json(pins.folder("cases") / "pairs.json", {"cases": {
            "C2": [{"material": "PLA film", "property": "tensile strength", "polymerIds": ["wop-000001"],
                    "replay": replay, "ask": "a value with its test method and specimen"}],
            "C6": [{"material": "polyfoo", "property": "tensile strength", "replay": {"relevant": []}}]}})
        engine = Engine()
        state = questions.write_c(runner=self.world.guard(engine))
        self.assertEqual((state["status"], state["short"]), ("completed", {"C1": 2, "C2": 2, "C3": 2, "C6": 2}))
        self.assertEqual([c[1] for c in engine.calls], ["the rule of C2", "the rule of C6"])  # one session a case
        with self.assertRaisesRegex(SystemExit, "caseQuestions"):  # written, not committed yet
            run.prepare_cases()
        questions.commit_questions(write=True)
        layout = run.prepare_cases()
        self.assertEqual((layout["replicates"], layout["questions"], layout["arms"]), (5, 4, ["B0", "O0", "B", "Oplus"]))
        self.assertEqual(sorted(layout["byCase"]), ["C1", "C2", "C3", "C6", "C7"])
        plans = [read_json(pins.folder("cases") / ("r%d" % r) / "plan.json") for r in range(1, 6)]
        self.assertTrue(all(p["questions"] == plans[0]["questions"] for p in plans))
        by_id = {q["id"]: q for q in plans[0]["questions"]}
        self.assertEqual(by_id["l-name"]["cases"], ["C1", "C7"])
        self.assertEqual(by_id["h-family"]["caseReasons"], {"C3": "HDPE's family link", "C7": "C3's question on K0"})
        written = {q["case"]: q for q in plans[0]["questions"] if q["set"] == "C"}
        self.assertEqual((written["C2"]["question"], written["C2"]["materials"], written["C2"]["cases"]),
                         ("What tensile strength has been reported for PLA film?", ["PLA film"], ["C2", "C7"]))
        self.assertEqual((written["C2"]["pair"]["replay"], written["C6"]["cases"]), (replay, ["C6"]))
        stores = run.recorded()
        self.assertEqual(plans[0]["stores"], {"B0": plain(stores["K0"]), "O0": plain(stores["K0-refined"]),
                                              "B": plain(stores["KF"]), "Oplus": plain(stores["KF-refined"])})
        roots = [run.plan_arms(pins.folder("cases") / ("r%d" % r))["B"] for r in (1, 2)]
        self.assertNotEqual(roots[0], roots[1])  # fresh copies per replicate
        self.assertEqual(run.release_id(run.plan_arms(pins.folder("cases") / "r1")["O0"]), self.world.refined)
        selection = read_json(pins.folder("cases") / "selection.json")
        selection["cases"]["C2"] = [{"id": "n-pla", "set": "N", "reason": "a late pick"}]
        atomic_json(pins.folder("cases") / "selection.json", selection)
        with self.assertRaisesRegex(SystemExit, "C.json was written for another cases/selection.json"):
            run.selection()

    def test_nothing_prepares_unless_the_code_is_the_tag_and_the_pins_hold(self):
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("Tag study-freeze-3 does not exist yet")):
            with self.assertRaisesRegex(SystemExit, "study-freeze-3"):
                run.prepare_screen()
        with mock.patch.dict(pins.PINS, promptVersion="000000000000"), self.assertRaisesRegex(SystemExit, "pinned"):
            run.prepare_screen()
        with mock.patch.object(part_a, "dirty", lambda: {"harness": [" M studies/x.py"]}), \
                self.assertRaisesRegex(SystemExit, "Uncommitted"):
            run.prepare_screen()
        self.assertFalse((pins.folder("screen") / "s1").exists())

    def test_every_commitment_must_be_there_and_hold_what_the_private_files_hold(self):
        committed = questions.COMMITMENTS.read_bytes()
        self.assertEqual(run.committed(), {k: questions.commitments()[k] for k in ("questions", "overlay", "pool")})
        entry = questions.commitments()["overlay"]
        self.assertEqual(entry["releases"], {"seed": self.world.seed, "refined": self.world.refined})
        self.assertEqual(entry["stores"]["KF-refined"], self.world.built["stores"]["KF-refined"])
        self.assertIsNone(entry["files"]["excluded.json"])
        for key in ("overlay", "pool"):
            atomic_json(questions.COMMITMENTS, dict(json.loads(committed), **{key: {}}))
            with self.assertRaisesRegex(SystemExit, "commitments.json has no %s entry" % key):
                run.prepare_screen()
        questions.COMMITMENTS.write_bytes(committed)
        atomic_json(pins.folder("overlay") / "excluded.json", {"format": overlay.FORMATS["excluded"], "edits": {}})
        with self.assertRaisesRegex(SystemExit, r"overlay: the private files differ from commitments.json \(files\)"):
            run.prepare_screen()
        with self.assertRaisesRegex(SystemExit, "holds another overlay entry"):  # a committed entry is not replaced
            run.commit(write=True)
        (pins.folder("overlay") / "excluded.json").unlink()
        atomic_json(pins.folder("mine") / "pool.json", {"answers": ["a-1"]})
        with self.assertRaisesRegex(SystemExit, r"pool: the private files differ"):
            run.prepare_screen()
        atomic_json(pins.folder("mine") / "pool.json", {"answers": ["a-1", "a-2"]})
        rows = [dict(SETS["H"][0], id="c-1", set="C", case="C6", rule="r")]
        atomic_json(questions.path("C.json"), rows)
        atomic_json(questions.path("case-hashes.json"), {"sets": {"C": questions.digest(rows)}})
        with self.assertRaisesRegex(SystemExit, "commitments.json has no caseQuestions entry"):
            run.prepare_screen()
        self.assertEqual(questions.commit_questions()["caseQuestions"]["files"]["C.json"],
                         questions.file_digest(questions.path("C.json")))  # printed to paste, not written
        self.assertFalse(questions.commitments()["caseQuestions"])
        questions.commit_questions(write=True)
        run.prepare_screen()
        self.assertEqual(read_json(pins.folder("screen") / "s1/pins.json")["commitments"]["caseQuestions"],
                         questions.commitments()["caseQuestions"])

    def test_a_store_that_is_not_the_recorded_one_is_refused(self):
        with mock.patch.object(pins, "K0", self.world.store("KF")), \
                self.assertRaisesRegex(SystemExit, "the recorded K0 is not test 1's K0"):
            run.prepare_screen()
        store(self.world.store("KF"), [("finding:late-1", "A late PLA finding.", "PLA", "", "10.1/z")])
        with self.assertRaisesRegex(SystemExit, r"overlay: the private files differ .*\(stores\)"):  # committed first
            run.prepare_screen()
        with self.assertRaisesRegex(SystemExit, "arm B: the store .* is not the recorded KF"):
            run.check_arms({"B": run.store_root("B")}, graph=False)
        with self.assertRaisesRegex(SystemExit, "not what overlay/fingerprint.json records; nothing is committed"):
            run.commit()

    def test_the_tables_must_hold_what_the_build_recorded(self):
        execute(self.world.store("KF-refined"),
                "INSERT INTO source_links VALUES ('doi:10.1/a', 'supplement-of', 'doi:10.1/c', '{}')")
        with self.assertRaisesRegex(SystemExit, r"overlay: the private files differ .*\(stores\)"):
            run.prepare_screen()
        with self.assertRaisesRegex(SystemExit, "arm Oplus: the tables of the store at .* are not the recorded "
                                                "KF-refined's"):
            run.check_arms({"Oplus": run.store_root("Oplus")}, graph=False)
        execute(self.world.store("KF-refined"), "DELETE FROM source_links")
        run.prepare_pilot()
        root = run.plan_arms(pins.BASE / "pilot")["Oplus"]
        execute(root, "INSERT INTO property_terms VALUES ('tensile-strength', '[\"UTS\"]')")  # a copy changed after
        with self.assertRaisesRegex(SystemExit, "arm Oplus: the tables of the store at .* are not the recorded"):
            run.run_folder(pins.BASE / "pilot", runner=self.world.guard(Engine()))

    def test_the_three_tables_must_be_absent_from_the_seed_stores_and_present_in_the_refined_ones(self):
        execute(self.world.store("K0"), *[s for s in pins.TABLES.split(";") if s.strip()])
        with self.assertRaisesRegex(SystemExit, r"arm B0: store K0 has \['finding_terms'"):
            run.check_arms({"B0": run.store_root("B0")}, graph=False)
        execute(self.world.store("K0"), "DROP TABLE source_links", "DROP TABLE property_terms",
                "DROP TABLE finding_terms")
        execute(self.world.store("KF-refined"), "DROP TABLE source_links")
        with self.assertRaisesRegex(SystemExit, r"arm Oplus: store KF-refined lacks \['source_links'\]"):
            run.check_arms({"Oplus": run.store_root("Oplus")}, graph=False)

    def test_the_refined_ontology_must_change_something_and_the_seed_be_the_pinned_one(self):
        with mock.patch.dict(pins.PINS, release="oopc-000000000000000000000000"), \
                self.assertRaisesRegex(SystemExit, "not the pinned"):
            run.prepare_screen()
        World(self, edits=[])  # no edit: release O is the seed release, KF-refined is KF, its tables are empty
        with self.assertRaisesRegex(SystemExit, "the refined ontology changes nothing"):
            run.prepare_screen()
        world = World(self, edits=[LINK])  # approved edits may all be store edits: the tables carry them
        self.assertEqual(world.refined, world.seed)
        self.assertEqual(overlay.table_hash(world.store("KF-refined"))["source_links"], 1)
        run.prepare_screen()

    def test_question_sets_that_are_not_their_hashes_are_refused(self):
        rows = read_json(questions.path("N.json"))
        rows[0]["question"] += " Cite tables."
        atomic_json(questions.path("N.json"), rows)
        with self.assertRaisesRegex(SystemExit, "N.json differs from its hash"):
            run.prepare_screen()

    def test_the_pilot_runs_end_to_end_and_the_screen_waits_for_its_check_by_hand(self):
        engine = Engine()
        state = run.pilot(runner=self.world.guard(engine))
        self.assertEqual((state["status"], state["failedItems"]), ("completed", 0))
        self.assertEqual(sum(c[0] == "research" for c in engine.calls), 9)
        self.assertEqual(sum(c[0] == "check" for c in engine.calls), 9)
        self.assertTrue(all(c[2] == "codex" for c in engine.calls))
        folder = pins.BASE / "pilot"
        self.assertEqual([json.loads(l)["status"] for l in (folder / "runs.jsonl").read_text().splitlines()],
                         ["completed"])
        run.prepare_screen()
        with self.assertRaisesRegex(SystemExit, "pilot has not been checked by hand"):
            run.run_screen(1, runner=self.world.guard(Engine()))
        (folder / "CHECKED").write_text("checked by hand\n")
        state = run.run_screen(1, runner=self.world.guard(Engine()))
        self.assertEqual(state["status"], "completed")
        report = read_json(pins.folder("screen") / "s1/report.json")
        self.assertEqual({a: v["answered"] for a, v in report["arms"].items()}, {"B0": 6, "B": 6, "Oplus": 6})
        self.assertEqual([r["state"] for r in run.status()], ["completed", "completed"])

    def test_a_store_copy_changed_after_prepare_is_refused_at_run(self):
        run.prepare_pilot()
        root = run.plan_arms(pins.BASE / "pilot")["Oplus"]
        execute(root, "UPDATE findings SET subject='' WHERE id='finding:ingeo-1'")
        with self.assertRaisesRegex(SystemExit, "arm Oplus: the store .* is not the recorded KF-refined"):
            run.run_folder(pins.BASE / "pilot", runner=self.world.guard(Engine()))

    def test_a_stop_file_stops_a_run_at_a_boundary_and_a_rerun_resumes(self):
        engine = Engine()
        guard = self.world.guard(engine)
        (self.world.top / "guard" / "STOP").write_text("")
        self.assertEqual(run.pilot(runner=guard)["stopReason"], "owner-stop")
        self.assertEqual(engine.calls, [])
        (self.world.top / "guard" / "STOP").unlink()
        self.assertEqual(run.run_folder(pins.BASE / "pilot", runner=guard)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
