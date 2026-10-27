"""Part C's trace mining (`refinement/mine.py`), offline, on a tiny world built in a temporary folder: a seed graph
release and a refined one, a KF store, live-loop answers with traces and a raw stream, and a Part A experiment whose KF
arm answered on a copy of KF. The replay check, the pool and its exclusions, the four kinds of miss, the hop classes,
the refined split with edit-group attribution, edit effects and the written outputs. Run with today's code:

    OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_refinement_*.py"
"""
import contextlib, hashlib, json, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402
import driver  # noqa: E402
from refinement import mine, pins, propose  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.trace import TraceStore  # noqa: E402
from oopc.util import atomic_json, digest as digest_of, read_json, resolve_release  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

POLYMERS = [
    {"@id": "wop-000001", "label": "Polyamide family"},
    {"@id": "wop-000002", "label": "Polyamide 66", "abbreviations": ["PA66"], "alternateNames": ["nylon 6,6"]},
    {"@id": "wop-000003", "label": "Polystyrene", "abbreviations": ["PS"]},
    {"@id": "wop-000004", "label": "Polycarbonate", "abbreviations": ["PC"]},
    {"@id": "wop-000005", "label": "Polyamide 6", "abbreviations": ["PA6"]},
    {"@id": "wop-000006", "label": "Polyethylene terephthalate", "abbreviations": ["PET"]},
    {"@id": "wop-000007", "label": "Polypyrrole", "abbreviations": ["PPy"]},
]
SEED_LINKS = [("wop-000002", "wop-000001")]  # (member, family)
OLD, NEW = "2026-10-01T00:00:00+00:00", "2026-10-20T00:00:00+00:00"  # KF's findings, and an answer's start


def release(folder, polymers, links):
    """A graph release of `polymers` with broader/narrower claims for (member, family) `links`, in `folder`."""
    records = [dict(p, **{"@type": "PolymerConcept", "status": "seed", "layer": "science"}) for p in polymers]
    for member, family in links:
        for subject, predicate, obj in ((member, "broader", family), (family, "narrower", member)):
            records.append({"@id": "claim:%s-%s-%s" % (subject, predicate, obj), "@type": "Claim",
                            "label": "%s → %s → %s" % (subject, predicate, obj), "subject": subject,
                            "predicate": predicate, "object": obj, "status": "seed", "layer": "science",
                            "evidence": [], "verified": False, "context": {"basis": "fixture"}})
    path = build_release(Path(folder) / "staging", records, get_ontology(), {})
    target = Path(folder) / read_json(path / "manifest.json")["release_id"]
    path.rename(target)
    return target


def finding(fid, statement, material, prop, subject, doi, *, qid=None, created=OLD, status=knowledge.SUPPORTED):
    return {"id": fid, "qid": qid or "q-" + fid, "created": created, "status": status, "statement": statement,
            "material": material, "property": prop, "value": "", "unit": "", "conditions": "", "subject": subject,
            "sourceTitle": "A study numbered %s on polymers" % doi, "sourceUrl": "", "sourceDoi": doi,
            "locator": "Table 1", "excerpt": "x"}


def workspace(path, release_path, findings=(), notes=()):
    """A workspace: a link to the release, and a store holding `findings` and `notes`."""
    path = Path(path)
    (path / "releases").mkdir(parents=True)
    (path / "releases" / release_path.name).symlink_to(release_path, True)
    atomic_json(path / "releases/current.json", {"release_id": release_path.name})
    with knowledge.connect(path) as db:
        for f in findings:
            knowledge._insert_finding(db, f["id"], f["qid"], "research", knowledge.clean_finding(f), status=f["status"],
                                      producer_engine="codex", created_at=f["created"])
        for n in notes:
            knowledge._insert_note(db, n["id"], n["qid"], "research", knowledge.clean_note(n), created_at=OLD)
    return path


def traced(root, searches):
    """A trace on the workspace `root` with these (q, limit) searches made through the researcher's own tool."""
    release_path = resolve_release(root)
    run = TraceStore(root).create(release_path, "fixture")
    tools = knowledge.research_tools(root, release_path, run.path.name, "researcher")
    for q, limit in searches:
        tools.call("search_knowledge", {"q": q, "limit": limit} if limit is not None else {"q": q})
    run.finish("completed")
    return run.path.name


def stream(path, steps, answer):
    """A raw Codex stream: each step ("store", q, limit), ("search", query) or ("open", url, opened); then the
    answer."""
    lines = [{"type": "thread.started", "thread_id": "t"}]
    for n, step in enumerate(steps):
        if step[0] == "store":
            item = {"id": "item_%d" % n, "type": "mcp_tool_call", "server": "oopc", "tool": "search_knowledge",
                    "arguments": {"q": step[1], "limit": step[2]}, "result": {}, "status": "completed"}
        elif step[0] == "search":
            item = {"id": "ws-%d" % n, "type": "web_search", "query": step[1],
                    "action": {"type": "search", "query": step[1]}, "results": [{"title": "t", "snippet": "s"}]}
        else:
            item = {"id": "ws-%d" % n, "type": "web_search", "query": step[1],
                    "action": {"type": "open_page", "url": step[1]},
                    "results": [{"title": "Page" if step[2] else "Access denied",
                                 "snippet": "Total lines: %d" % (300 if step[2] else 1)}]}
        lines.append({"type": "item.completed", "item": item})
    lines += [{"type": "item.completed", "item": {"id": "m", "type": "agent_message", "text": json.dumps(answer)}},
              {"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}}]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(line) + "\n" for line in lines))


def answer_of(text, cited=(), findings=(), sources=()):
    return {"answer": text + " " + " ".join("`%s`" % c for c in cited), "citations": list(cited),
            "findings": list(findings), "sources": list(sources), "limitations": [], "openQuestions": []}


def reported(statement, material, prop, doi):
    return {"statement": statement, "material": material, "property": prop, "value": "", "unit": "",
            "sourceDoi": doi, "sourceTitle": "", "locator": "Table 1", "excerpt": "x", "derivation": "read"}


PS_HAZE = [finding("finding:pshaze%06d-1" % n, "Polystyrene sheet %d showed a haze of %d%%." % (n, n + 1), "PS sheet",
                   "haze", "wop-000003", "10.1000/psh%02d" % n) for n in range(12)]
KF_FINDINGS = PS_HAZE + [
    finding("finding:creep0000001-1", "Polyamide 66 bars showed a creep compliance of 1.2 per GPa after 100 h.",
            "Polyamide 66 bars", "creep compliance", "wop-000002", "10.1000/creep"),
    finding("finding:creepsi00001-1", "Specimens were conditioned at 50% relative humidity before testing.",
            "specimens", "conditioning", "wop-000002", "10.1000/creep.s001"),
    finding("finding:yellow000001-1", "Polystyrene sheet showed a yellowness index of 4.", "PS sheet",
            "yellowness index", "wop-000003", "10.1000/yellow"),
    finding("finding:pstensile001-1", "Polystyrene bars had a tensile strength of 45 MPa.", "PS bars",
            "tensile strength", "wop-000003", "10.1000/pst"),
    finding("finding:pethaze00001-1", "The film had a haze of 2%.", "biaxially oriented film", "haze", "wop-000006",
            "10.1000/pet"),
    finding("finding:pa6water0001-1", "Nylon 6 plaques absorbed 2.7% water at saturation.", "nylon 6 plaques",
            "water absorption", "wop-000005", "10.1000/pa6"),
    finding("finding:relax0000001-1", "Conditioned bars showed a stress relaxation of 15% in 10 h.", "conditioned bars",
            "stress relaxation", "", "10.1000/relax"),
]
KF_NOTES = [{"id": "note:kfnote00001-1", "qid": "q-note", "title": "Unsaved paper", "doi": "10.1000/held",
             "url": "https://doi.org/10.1000/held", "supports": "A lead with nothing saved.", "excerpts": []}]


class World:
    """The fixture world; `harness` stands in for `ROOT/.oopc/loop/harness`."""

    def __init__(self, folder):
        self.folder = folder = Path(folder)
        self.seed = release(folder / "rel", POLYMERS, SEED_LINKS)
        refined = [dict(p, tradeNames=[{"name": "Zytel"}]) if p["@id"] == "wop-000002" else p for p in POLYMERS]
        self.refined_release = release(folder / "rel", refined, SEED_LINKS + [("wop-000005", "wop-000001")])
        self.kf = workspace(folder / "kf", self.seed, KF_FINDINGS, KF_NOTES)
        self.fingerprint = driver.fingerprint(self.kf)
        self.harness = folder / "harness"
        self.heldout = folder / "heldout.json"
        atomic_json(self.heldout, [{"id": "h1", "question": "What is the haze of polycarbonate (PC)?"}])
        self.questions = folder / "questions"
        self.questions.mkdir()
        atomic_json(self.questions / "H.json", [{"id": "h1", "set": "H",
                                                 "question": "What is the haze of polycarbonate (PC)?"}])
        atomic_json(self.questions / "N.json", {"questions": [{"id": "n1", "set": "N",
                                                              "question": "What withheld thing is asked here?"}]})
        atomic_json(self.questions / "L.json", [{"id": "l1", "set": "L", "question": "What haze has Lexan shown?"}])
        self.fix_sets()
        self.live = workspace(folder / "live", self.seed, KF_FINDINGS[:3] + KF_FINDINGS[13:14])  # as it was then
        self.streams = folder / "live-streams"
        self.metadata = {}
        self._live()
        self._part_a()

    def fix_sets(self):
        """questions/hashes.json for H, N and L as they are now, as `questions.py hashes` writes it."""
        atomic_json(self.questions / "hashes.json", {"sets": {name: digest_of(read_json(self.questions / (
            name + ".json"))) for name in ("H", "N", "L")}})

    def ask(self, qid, question, steps, answer, *, materials=None, prop=None, with_stream=True, started=NEW):
        """A completed live-loop question: its trace on the live store, its result, and (optionally) its stream."""
        folder = self.live / ".oopc/loop/questions" / qid
        folder.mkdir(parents=True)
        run = traced(self.live, [(s[1], s[2]) for s in steps if s[0] == "store"])
        atomic_json(folder / "question.json", {"id": qid, "question": question, "status": "completed",
                                               "origin": "research", "engine": "codex", "runId": run,
                                               "startedAt": started})
        tools = []
        for n, s in enumerate(steps):
            if s[0] == "store":
                tools.append({"id": "item_%d" % n, "type": "mcp_tool_call", "server": "oopc",
                              "tool": "search_knowledge"})
            elif s[0] == "search":
                tools.append({"id": "ws-%d" % n, "type": "web_search", "query": s[1]})
            else:
                tools.append({"id": "ws-%d" % n, "type": "web_search", "query": s[1], "url": s[1]})
        atomic_json(folder / "result.json", {"answer": answer, "observedTools": tools})
        if with_stream:
            stream(self.streams / ("%s-codex.jsonl" % qid), steps, answer)
        if materials:
            self.metadata[qid] = {"materials": materials, "property": prop, "kind": "property"}

    def _live(self):
        # L1: hops of every class, in stream order with outcomes.
        self.ask("l1", "For polyamide 66 (PA66), what creep was reported?", [
            ("store", "Zytel deformation", 10), ("store", "specimen conditioning humidity", 10),
            ("search", "zytel creep data"), ("open", "https://doi.org/10.1000/creep", True),
            ("open", "https://doi.org/10.1000/creep", True), ("open", "https://doi.org/10.1000/creep.s001", True),
            ("open", "https://example.org/new-paper", True), ("open", "https://example.org/blocked", False),
            ("open", "https://doi.org/10.1000/held", True),
            ("open", "https://pmc.example.org/articles/PMC1/", True), ("search", "zytel creep afterwards")],
            answer_of("PA66 creep.", sources=[{"title": "Unsaved", "doi": "10.1000/pa6",
                                               "url": "https://doi.org/10.1000/pa6",
                                               "readUrl": "https://pmc.example.org/articles/PMC1/",
                                               "supports": "read there"}],
                      findings=[reported("Polyamide 66 bars showed a creep compliance of 1.2 per GPa after 100 h.",
                                         "Polyamide 66 bars", "creep compliance", "10.1000/creep")]),
            materials=["polyamide 66 (PA66)"], prop="creep")
        # L2: saved again, an empty search then the web, an unknown name in a query; no stream (fields only).
        self.ask("l2", "What tensile strength has been reported for polycarbonate (PC)?", [
            ("store", "polycarbonate tensile strength", 10), ("search", "polycarbonate tensile strength ASTM D638"),
            ("store", "PA612 modulus", 10), ("store", "PPy modulus", 10), ("store", "PET haze", 10)],
            answer_of("PC strength.", findings=[reported("Polystyrene bars had a tensile strength of 45 MPa.",
                                                          "PS bars", "tensile strength", "10.1000/pst")]),
            materials=["polycarbonate (PC)"], prop="tensile strength", with_stream=False)
        # L3: a late find (crowded out of the first search for its polymer, found by the second), and a withheld text.
        self.ask("l3", "For polystyrene (PS), what optical data were reported?", [
            ("store", "PS haze", 10), ("store", "PS yellowness", 10)],
            answer_of("PS optics.", cited=["finding:yellow000001-1"]), materials=["polystyrene (PS)"],
            prop="yellowness index")
        # L8: an unfiltered search that returns an unfiled finding the answer cites (a result a name edit can lose).
        self.ask("l8", "For polyamide 66 (PA66), what stress relaxation was reported?", [
            ("store", "Zytel stress relaxation", 10)], answer_of("Relaxation.", cited=["finding:relax0000001-1"]))
        self.ask("l4", "what  withheld thing is ASKED here?", [("store", "anything", 10)], answer_of("x"))
        self.ask("l7", "What tensile modulus has PS shown?", [("store", "PS modulus", 10)], answer_of("x"),
                 started="2026-10-21T05:00:00+00:00")  # after the pool's cutoff
        (self.live / ".oopc/loop/questions/l5").mkdir(parents=True)  # unreadable
        atomic_json(self.live / ".oopc/loop/questions/l6/question.json",
                    {"id": "l6", "question": "q", "status": "failed"})

    def _part_a(self):
        folder = self.harness / "2026-10-x/r1-s1"
        arms = [{"name": "KF", "kind": "researcher", "web": True}, {"name": "MF", "kind": "researcher", "web": False},
                {"name": "K0", "kind": "researcher", "web": True}]
        for arm in arms:
            arm["root"] = str(driver.workspace(folder, arm["name"], releases=self.kf, store=self.kf))
        self.cited = mine.returned(arms[0]["root"], "PS haze", 12)[0]  # surely returned by that search
        questions = [{"id": "a0", "question": "Report a published value of haze for polystyrene (PS).",
                      "material": "polystyrene (PS)", "property": "haze"},
                     {"id": "a1", "question": "What is the haze of  Polycarbonate (PC)?", "material": "PC",
                      "property": "haze"}]
        plan = {"name": "x", "questions": questions, "arms": arms, "checker": "codex",
                "stores": {"KF": self.fingerprint, "MF": self.fingerprint, "K0": {"findings": 0}}}
        atomic_json(folder / "plan.json", plan)
        atomic_json(self.harness / "2026-10-x/experiment.json", {"folders": ["r1-s1"]})
        for number, question in enumerate(questions):
            for arm in arms:
                searches = [("PS haze", 12), ("polystyrene haze sheet", None)] if number == 0 else [("PC haze", 10)]
                run = traced(arm["root"], searches)
                text = "Answer %d of arm %s." % (number, arm["name"])
                answer = answer_of(text, cited=[self.cited])
                steps = [("store",) + searches[0], ("search", "polystyrene haze astm"),
                         ("open", "https://doi.org/10.1000/psh01", True), ("store",) + searches[1:][0]] \
                    if number == 0 else [("store",) + searches[0]]
                if number == 0 and arm["name"] == "KF":
                    stream(folder / "streams/00001-codex.jsonl", steps, answer)
                atomic_json(folder / "items" / ("%04d-%s.json" % (number, arm["name"])), {
                    "question": question["id"], "arm": arm["name"],
                    "answer": {"answer": answer, "runId": run, "webActions": [
                        {"action": "open", "outcome": "opened", "url": "https://doi.org/10.1000/psh01"}]}})

    def patches(self):
        return mock.patch.object(common, "run_dir", lambda name: self.harness / name)

    def mine(self, out, **options):
        values = dict(kf=self.kf, expected=self.fingerprint, release=self.seed.name, live_root=self.live,
                      part_a={"AX": "2026-10-x"}, heldout=self.heldout, questions=self.questions,
                      streams=[self.streams], metadata=self.metadata, property_map=self.folder / "no-map.json",
                      crossref=self.folder / "crossref")
        values.update(options)
        with self.patches():
            return mine.mine(out, **values)

    def refined(self, name, *, subjects=None, unsupported=(), links=(), release=None, terms=None):
        """A refined workspace: the refined release (or `release`), and a copy of KF with some findings refiled or
        hidden, source links, and property terms {term: (names, finding ids)}."""
        root = workspace(self.folder / name, release or self.refined_release)
        source = sqlite3.connect(knowledge.database(self.kf).as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(knowledge.database(root))
        source.backup(target)
        source.close()
        for fid, subject in (subjects or {}).items():
            target.execute("UPDATE findings SET subject=? WHERE id=?", (subject, fid))
        for fid in unsupported:
            target.execute("UPDATE findings SET status='unsupported' WHERE id=?", (fid,))
        target.executescript(pins.TABLES)
        target.executemany("INSERT INTO source_links VALUES (?,?,?,?)", [(a, r, b, "") for a, r, b in links])
        for term, (names, findings) in (terms or {}).items():
            target.execute("INSERT INTO property_terms VALUES (?,?)", (term, json.dumps(names)))
            target.executemany("INSERT INTO finding_terms VALUES (?,?)", [(f, term) for f in findings])
        target.commit()
        target.close()
        return root


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="oopc-refinement-mine-")
        cls.world = World(cls.tmp.name)
        cls.out = Path(cls.tmp.name) / "mine"
        cls.kf_before = digest(knowledge.database(cls.world.kf))
        cls.summary = cls.world.mine(cls.out)
        with cls.world.patches():
            cls.answers, cls.misses, cls.hops = mine.load(cls.out)
        cls.by_id = {a["id"]: a for a in cls.answers}
        cls.miner = mine.Miner(cls.out / "workspaces/KF", property_map=Path(cls.tmp.name) / "no-map.json")
        cls.frozen = mock.patch.object(pins, "frozen", lambda: "test-commit")  # a refined root is searched
        cls.frozen.start()

    @classmethod
    def tearDownClass(cls):
        cls.frozen.stop()
        cls.tmp.cleanup()

    def test_replay_is_the_tools_search(self):
        root = self.out / "workspaces/KF"
        release_path = resolve_release(root)
        run = TraceStore(root).create(release_path, "t")
        tools = knowledge.research_tools(root, release_path, run.path.name, "researcher")
        for q, limit in (("PS haze", 12), ("polystyrene", None), ("nothing matches this", 10)):
            expected = mine.result_ids(tools.call("search_knowledge", {"q": q, "limit": limit} if limit else {"q": q}))
            self.assertEqual(mine.replay(root, q, limit), expected)
        found = mine.returned(root, "PS haze", 12)  # what the call returns: the findings among its ids, in order
        self.assertEqual(found, [i for i in mine.replay(root, "PS haze", 12) if i.startswith("finding:")])
        self.assertEqual(set(found), {f["id"] for f in PS_HAZE})  # the twelve haze sheets fill the limit

    def test_property_rule_and_question_topics(self):
        props = mine.Properties(Path(self.tmp.name) / "no-map.json")  # A1's ordered rules only
        self.assertTrue(props.same("creep", "stress relaxation"))  # one class, no shared word
        self.assertFalse(props.same("tensile strength", "drying temperature"))
        self.assertTrue(props.same("water uptake and dimensional swelling", "swelling ratio"))  # part by part
        self.assertFalse(props.same("water uptake and dimensional swelling", "specimen dimensions"))
        topic = mine.topic("For PS, find one open primary study of tensile strength of films cast and dried at "
                           "room temperature. Report one bounded quantitative result.")
        self.assertEqual(topic, "tensile strength of films cast and dried at room temperature")
        self.assertTrue(props.same(topic, "tensile strength", loose=True))  # a side word's class does not decide
        self.assertEqual(mine.topic("Explain oxygen permeability measurement using one open primary study."),
                         "oxygen permeability measurement")
        self.assertEqual(mine.candidate_names("polyether ether ketone (PEEK) and PA612 by DSC"),
                         ["polyether ether ketone", "PEEK", "PA612"])

    def test_check_reproduces_every_recorded_search_and_mining_refuses_otherwise(self):
        check = read_json(self.out / "replay-check.json")
        self.assertTrue(check["ok"])
        # Every KF arm, web off and held-out questions included (a check derives nothing); not the K0 arm.
        self.assertEqual(check["answers"], 4)
        self.assertEqual(check["searches"], 6)
        self.assertEqual(check["byExperiment"]["AX"]["matched"], 6)
        changed = Path(self.tmp.name) / "changed"
        with self.world.patches(), self.assertRaises(SystemExit) as stop:
            base = mine.base_root(changed, self.world.kf, expected=self.world.fingerprint, release=self.world.seed.name)
            with knowledge.connect(base) as db:  # the base is no longer the store the searches ran on
                knowledge._insert_finding(db, "finding:extra0000001-1", "q-x", "research", knowledge.clean_finding(
                    finding("finding:extra0000001-1", "Polycarbonate plaques had a haze of 1%.", "PC plaques", "haze",
                            "wop-000004", "10.1000/extra")), status=knowledge.SUPPORTED, producer_engine="codex",
                    created_at=OLD)
            value = mine.check(changed, base, part_a={"AX": "2026-10-x"}, fingerprint=self.world.fingerprint)
            self.assertFalse(value["ok"])
            self.assertIn("finding:extra0000001-1", value["differences"][0]["onlyReplayed"])
            raise SystemExit("refused")
        self.assertIn("refused", str(stop.exception))
        failing = {"ok": False, "differences": [{"q": "PS haze"}], "differing": 1, "searches": 6}
        with mock.patch.object(mine, "check", return_value=failing), self.assertRaises(SystemExit) as stop:
            self.world.mine(Path(self.tmp.name) / "refused")
        self.assertIn("nothing mined", str(stop.exception))
        self.assertFalse((Path(self.tmp.name) / "refused/summary.json").exists())
        with self.world.patches(), self.assertRaises(SystemExit):  # a base that is not KF is refused outright
            mine.base_root(Path(self.tmp.name) / "other", self.world.live, expected=self.world.fingerprint,
                           release=self.world.seed.name)

    def test_pool_and_what_it_leaves_out(self):
        origins = sorted(a["id"] for a in self.answers)
        self.assertEqual(origins, ["2026-10-x/r1-s1/0000-KF", "loop/l1", "loop/l2", "loop/l3", "loop/l8"])
        reasons = {e["id"]: e["reason"] for e in read_json(self.out / "excluded.json")}
        self.assertEqual(reasons["loop/l4"], "withheld question (N)")  # case and spacing ignored
        self.assertEqual(reasons["2026-10-x/r1-s1/0001-KF"], "withheld question (H)")
        self.assertEqual(reasons["2026-10-x/r1-s1/0000-MF"], "web search off")
        self.assertEqual(reasons["loop/l5"], "unreadable question record")
        self.assertEqual(reasons["loop/l6"], "not completed")
        self.assertEqual(reasons["loop/l7"], "started after the pool's cutoff, %s" % mine.CUTOFF)
        self.assertNotIn("2026-10-x/r1-s1/0000-K0", reasons)  # not a KF arm: outside the pool, not excluded from it
        self.assertEqual(self.summary["pool"]["byOrigin"], {"loop": 4, "AX": 1})
        self.assertEqual(self.summary["excluded"]["total"], len(reasons))

    def test_the_first_mining_pins_the_pool_and_later_ones_mine_exactly_it(self):
        pinned = read_json(self.out / "pool.json")
        self.assertEqual(pinned["answers"], sorted(a["id"] for a in self.answers))
        self.assertEqual((pinned["digest"], pinned["cutoff"]), (digest_of(pinned["answers"]), mine.CUTOFF))
        self.assertEqual(self.summary["pinnedPool"]["digest"], pinned["digest"])
        again = Path(self.tmp.name) / "pinned"
        again.mkdir()
        shutil.copy(self.out / "pool.json", again / "pool.json")
        self.world.ask("l9", "What haze has PS shown?", [("store", "PS haze", 10)], answer_of("x"))  # a later answer
        try:
            self.world.mine(again)
            reasons = {e["id"]: e["reason"] for e in read_json(again / "excluded.json")}
            self.assertEqual(reasons["loop/l9"], "not in the pinned pool (pool.json)")
            with self.world.patches():
                answers, misses, hops = mine.load(again)
            self.assertEqual(sorted(a["id"] for a in answers), pinned["answers"])
            # The same pool mined again gives the same ids.
            self.assertEqual([m["id"] for m in misses], [m["id"] for m in self.misses])
            self.assertEqual([h["id"] for h in hops], [h["id"] for h in self.hops])
            gone = self.world.live / ".oopc/loop/questions/l3"
            gone.rename(gone.with_name("l3-away"))
            try:
                with self.assertRaisesRegex(SystemExit, "pinned pool .* gone"):
                    self.world.mine(again)
            finally:
                gone.with_name("l3-away").rename(gone)
            pool = read_json(again / "pool.json")
            atomic_json(again / "pool.json", dict(pool, answers=pool["answers"][:-1]))
            with self.assertRaisesRegex(SystemExit, "digest"):
                self.world.mine(again)
        finally:
            shutil.rmtree(self.world.live / ".oopc/loop/questions/l9")

    def test_mining_needs_the_withheld_sets_fixed_by_hash(self):
        questions = Path(self.tmp.name) / "unfixed"
        shutil.copytree(self.world.questions, questions)
        atomic_json(questions / "L.json", [{"id": "l1", "set": "L", "question": "Another L question?"}])
        with self.assertRaisesRegex(SystemExit, "L.json is not the set"):
            self.world.mine(Path(self.tmp.name) / "unfixed-out", questions=questions)
        (questions / "hashes.json").unlink()
        with self.assertRaisesRegex(SystemExit, "not fixed by hash"):
            self.world.mine(Path(self.tmp.name) / "unfixed-out", questions=questions)
        self.assertFalse((Path(self.tmp.name) / "unfixed-out").exists())
        self.assertEqual(self.summary["questionSets"], mine.fixed_sets(self.world.questions))

    def test_records_keep_the_sessions_order_and_join_the_trace(self):
        l1 = self.by_id["loop/l1"]
        self.assertEqual(l1["orderFrom"], "stream")
        self.assertEqual([s["type"] for s in l1["steps"]][:5], ["store", "store", "web-search", "open", "open"])
        self.assertEqual(l1["steps"][7]["outcome"], "refused")
        first = l1["steps"][0]
        self.assertEqual((first["q"], first["limit"], first["status"]), ("Zytel deformation", 10, "ok"))
        self.assertEqual(first["recorded"], [])  # the live store held nothing for it then
        self.assertEqual(l1["materials"], ["polyamide 66 (PA66)"])
        l2 = self.by_id["loop/l2"]  # no stream: the record's fields, store steps joined in order
        self.assertEqual(l2["orderFrom"], "record")
        self.assertEqual([s["type"] for s in l2["steps"]], ["store", "web-search", "store", "store", "store"])
        self.assertEqual(l2["steps"][1]["actionFrom"], "fields")
        self.assertEqual(l2["steps"][2]["q"], "PA612 modulus")
        part_a = self.by_id["2026-10-x/r1-s1/0000-KF"]
        self.assertEqual(part_a["orderFrom"], "stream")
        self.assertEqual([s["type"] for s in part_a["steps"]], ["store", "web-search", "open", "store"])
        self.assertEqual(part_a["steps"][2]["outcome"], "opened")
        self.assertEqual(part_a["steps"][3]["limit"], None)
        self.assertEqual(part_a["cited"]["findings"], [self.world.cited])
        self.assertEqual(part_a["steps"][0]["recorded"], part_a["steps"][0]["replayed"])
        self.assertEqual(self.by_id["loop/l1"]["deposited"], [])

    def miss(self, kind, answer, **match):
        return [m for m in self.misses if m["kind"] == kind and m["answer"] == answer
                and all(m.get(k) == v for k, v in match.items())]

    def test_misses_of_each_kind(self):
        saved = self.miss("saved-again", "loop/l2")
        self.assertEqual([m["held"] for m in saved], [["finding:pstensile001-1"]])
        self.assertEqual(len(self.miss("empty-then-web", "loop/l2", step=0, web=1)), 1)
        names = self.miss("unresolved-name", "loop/l2", scope="query")
        self.assertEqual([(m["step"], m["names"]) for m in names], [(2, ["PA612"])])  # PPy: known, not read as written
        self.assertGreaterEqual(self.summary["other"]["unfilteredKnownName"], 1)
        late = self.miss("late-find", "loop/l3")
        self.assertEqual([(m["finding"], m["step"], m["returnedAt"]) for m in late],
                         [("finding:yellow000001-1", 0, 1)])
        store = [m for m in self.misses if m.get("scope") == "finding"]
        self.assertEqual([m["finding"] for m in store], ["finding:relax0000001-1"])  # no polymer id
        self.assertFalse(self.miss("late-find", "2026-10-x/r1-s1/0000-KF"))  # cited and returned by its first search

    def hop(self, answer, open_step):
        return next(h for h in self.hops if h["answer"] == answer and h.get("open") == open_step)

    def test_hop_classes_on_the_base(self):
        l1 = "loop/l1"
        creep = self.hop(l1, 3)
        self.assertEqual((creep["class"], creep["steps"], creep["searches"]), ("held-unreached", [2, 3],
                                                                               ["zytel creep data"]))
        # What the answer took from the page (its reported finding) matches the saved finding from it.
        self.assertEqual(creep["target"]["matched"], ["finding:creep0000001-1"])
        self.assertEqual(creep["target"]["used"]["findings"], 1)
        self.assertEqual(creep["target"]["heldSince"], "before")
        self.assertEqual(self.hop(l1, 4)["class"], "repeat")  # a page the answer had already read
        # Held, and returned by step 1 as recorded, but not read before: not a repeat. The answer took nothing from it.
        self.assertEqual(self.hop(l1, 5)["class"], "unused")
        self.assertEqual(self.hop(l1, 6)["class"], "new-knowledge")
        self.assertEqual(self.hop(l1, 7)["class"], "failed")
        self.assertEqual(self.hop(l1, 8)["class"], "unused")  # only a note holds it, and the answer used nothing
        pmc = self.hop(l1, 9)  # identified with its DOI by the answer's own source note
        self.assertIn("doi:10.1000/pa6", pmc["target"]["keys"])
        self.assertIn("the answer's source note", pmc["target"]["resolvedBy"])
        # Held and used (the answer's source note), but nothing it took matches a saved finding.
        self.assertEqual((pmc["class"], pmc["target"]["used"]["notes"]), ("unsaved-detail", 1))
        self.assertEqual(len({h["id"] for h in self.hops}), len(self.hops))
        tail = [h for h in self.hops if h["answer"] == l1 and h["class"] == "search-only"]
        self.assertEqual([h["steps"] for h in tail], [[10]])
        store = [h for h in self.hops if h["answer"] == "2026-10-x/r1-s1/0000-KF" and h["kind"] == "store"]
        self.assertEqual([h["class"] for h in store], ["repeat"])  # the second search added nothing new
        l2 = [h for h in self.hops if h["answer"] == "loop/l2" and h["kind"] == "store"]
        self.assertEqual([h["class"] for h in l2], ["repeat", "repeat", "new-polymer"])
        l3 = [h for h in self.hops if h["answer"] == "loop/l3" and h["kind"] == "store"]
        self.assertEqual([(h["class"], h["newRelevant"]) for h in l3],
                         [("held-unreached", ["finding:yellow000001-1"])])

    def test_refined_workspace_splits_held_unreached_and_attributes_groups(self):
        refined = self.world.refined("refined-a")
        base = self.out / "workspaces/KF"
        hops = self.miner.classify(self.by_id["loop/l1"], refined)
        creep = next(h for h in hops if h.get("open") == 3)
        self.assertEqual(creep["refined"], "reachable")  # Zytel is now PA66's: "Zytel deformation" finds the creep
        groups = {frozenset(["name/family"]): refined}
        hops = self.miner.classify(self.by_id["loop/l1"], refined, lambda g: groups.get(g, base))
        self.assertEqual(next(h for h in hops if h.get("open") == 3)["groups"], ["name/family"])
        hops = self.miner.classify(self.by_id["loop/l1"], base)
        self.assertEqual(next(h for h in hops if h.get("open") == 3)["refined"], "still-unreached")

    def test_relevance_needs_a_known_polymer(self):
        unknown = {"ids": frozenset(), "lineage": frozenset(), "names": set(), "property": "haze",
                   "propertyFrom": "recorded"}
        self.assertFalse(self.miner.relevant(PS_HAZE[0]["id"], unknown))  # on the property, but whose polymer?
        known = dict(unknown, lineage=frozenset(["wop-000003"]))
        self.assertTrue(self.miner.relevant(PS_HAZE[0]["id"], known))

    def roots(self):
        """Edit roots: Zytel named as PA66 (with PA6's family link), nothing changed, and Zytel wrongly named as PS."""
        wrong = release(self.world.folder / "rel-wrong", [dict(p, tradeNames=[{"name": "Zytel"}])
                                                          if p["@id"] == "wop-000003" else p for p in POLYMERS],
                        SEED_LINKS)
        return {"zytel": self.world.refined("effect-zytel"),
                "noop": self.world.refined("effect-noop", release=self.world.seed),
                "wrong": self.world.refined("effect-wrong", release=wrong)}

    def assert_rule(self, roots):
        """Every pool search the replay rule leaves out returns on the root exactly what it returns on the base."""
        for name, root in roots.items():
            diff = mine.difference(self.miner, root)
            for q, limit in mine.pool_searches(self.answers):
                if not mine.affected(self.miner, diff, q, limit):
                    fresh = mine.result_ids(knowledge.search(root, q, limit or 10, compact=True))
                    self.assertEqual(fresh, mine.replay(self.miner.base, q, limit), (name, q))

    def test_effects_of_edits_alone_by_the_replay_rule(self):
        roots = self.roots()
        self.assert_rule(roots)
        built = []

        @contextlib.contextmanager
        def build(edit):
            built.append(edit)
            yield roots[edit]
        saved = []
        creep = self.hop("loop/l1", 3)
        again = self.miss("saved-again", "loop/l1")[0]  # l1 reported the creep finding another question had saved
        value = mine.effects(self.miner, ["noop", "wrong", "zytel"], build, self.answers, self.misses, self.hops,
                             cites={"zytel": ([again["id"]], [creep["id"]])}, save=lambda v: saved.append(dict(v)))
        self.assertEqual((built, [sorted(v) for v in saved]), (["noop", "wrong", "zytel"],
                                                               [["noop"], ["noop", "wrong"],
                                                                ["noop", "wrong", "zytel"]]))
        zytel = value["zytel"]
        self.assertEqual(zytel["reachable"], [creep["id"]])  # "Zytel deformation" now returns the creep finding
        self.assertIn(again["id"], zytel["fixed"])
        self.assertEqual(zytel["cited"], {"misses": 1, "fixed": 1, "hops": 1, "reachable": 1})
        # Lost: l8 cited the unfiled relaxation finding its unfiltered search returned; Zytel now filters to PA66.
        self.assertEqual([(x["answer"], x["finding"]) for x in zytel["lost"]], [("loop/l8", "finding:relax0000001-1")])
        self.assertFalse(mine.dropped(zytel))
        self.assertGreater(zytel["searches"]["replayed"], 0)
        self.assertLess(zytel["searches"]["replayed"], zytel["searches"]["pool"])
        noop = value["noop"]
        self.assertEqual((noop["missesFixed"], noop["hopsReachable"], noop["resultsLost"],
                          noop["searches"]["replayed"]), (0, 0, 0, 0))
        wrong = value["wrong"]  # Zytel as polystyrene: the relaxation finding is lost and nothing is fixed
        self.assertEqual((wrong["missesFixed"], wrong["hopsReachable"], wrong["resultsLost"]), (0, 0, 1))
        self.assertTrue(mine.dropped(wrong))
        again_value = mine.effects(self.miner, ["noop", "wrong", "zytel"], build, self.answers, self.misses,
                                   self.hops, done=value)
        self.assertEqual((again_value, built[3:]), (value, []))  # what was measured is kept, not built again
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("not the tag")), self.assertRaises(SystemExit):
            mine.effects(self.miner, ["noop"], build, self.answers, self.misses, self.hops)

    def test_the_rule_sees_what_freeze_3_reads(self):
        if not hasattr(knowledge, "_property_terms"):
            self.skipTest("needs study-freeze-3's search (OOPC_STUDY_CODE at .oopc/study/freeze-3)")
        roots = {"link": self.world.refined("rule-link", release=self.world.seed,
                                            links=[("doi:10.1000/creep.s001", "supplement-of", "doi:10.1000/creep")]),
                 "term": self.world.refined("rule-term", release=self.world.seed, terms={
                     "creep-stress-relaxation": (["creep", "stress relaxation", "deformation"],
                                                 ["finding:creep0000001-1"])})}
        self.assert_rule(roots)
        value = mine.effects(self.miner, sorted(roots), lambda e: contextlib.nullcontext(roots[e]), self.answers,
                             self.misses, self.hops)
        # The conditioning search returned the supplement; the link brings the article's creep finding with it.
        self.assertEqual(value["link"]["reachable"], [self.hop("loop/l1", 3)["id"]])
        self.assertEqual(value["term"]["searches"]["replayed"], len([q for q, _ in mine.pool_searches(self.answers)
                                                                     if "deformation" in q or "relaxation" in q
                                                                     or "creep" in q]))

    def test_outputs_dossier_and_kf_untouched(self):
        self.assertEqual(digest(knowledge.database(self.world.kf)), self.kf_before)
        for name in ("replay-check.json", "answers.jsonl", "excluded.json", "misses.json", "hops.json", "summary.json"):
            self.assertTrue((self.out / name).exists(), name)
            self.assertEqual(os.stat(self.out / name).st_mode & 0o077, 0, name)
        summary = self.summary
        self.assertEqual(summary["misses"]["byKind"], dict(collections_counter(m["kind"] for m in self.misses)))
        self.assertEqual(summary["hops"]["web"]["byClass"]["held-unreached"], 1)
        self.assertEqual(summary["replayCheck"]["ok"], True)
        batches = sorted((self.out / "dossier").glob("batch-*.json"))
        self.assertEqual(len(batches), summary["dossier"]["batches"])
        groups = [g for b in batches for g in read_json(b)["groups"]]
        self.assertEqual(len(groups), summary["dossier"]["groups"])
        pair = next(g for g in groups if g["by"] == "source-pair")
        self.assertEqual(pair["key"], ["doi:10.1000/creep", "doi:10.1000/creep.s001"])
        self.assertEqual(pair["candidates"]["source-link"][0]["evidence"], [{"kind": "doi-stem"}])
        self.assertEqual(pair["examples"][0]["answer"], "loop/l1")
        self.assertIn("Zytel deformation", pair["queries"])
        late = next(g for g in groups if "late-find" in g["kinds"])
        self.assertEqual(late["candidates"]["property-term"][0]["finding"], "finding:yellow000001-1")
        name = next(g for g in groups if g["by"] == "name" and g["key"] == ["pa612"])
        self.assertEqual(name["count"], 1)
        self.assertEqual(read_json(self.out / "pool.json")["questionSets"], summary["questionSets"])
        with mock.patch.object(mine, "BATCH", 2):  # batches of BATCH groups, numbered from 1
            mine.write(Path(self.tmp.name) / "rebatched", self.answers, [], self.misses, self.hops, groups, summary)
        written = sorted((Path(self.tmp.name) / "rebatched/dossier").glob("batch-*.json"))
        self.assertEqual(len(written), -(-len(groups) // 2))
        self.assertEqual(read_json(written[0])["batch"], 1)
        self.assertEqual(len(read_json(written[0])["groups"]), 2)

    def test_the_curator_can_cite_every_miss_and_held_unreached_hop_by_its_id(self):
        ids = [m["id"] for m in self.misses] + [h["id"] for h in self.hops]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith(("m-", "h-")) for i in ids))
        offered = {"misses": set(), "hops": set()}
        for path in sorted((self.out / "dossier").glob("batch-*.json")):
            found = propose.cited(read_json(path))  # what the curator's edits are screened against
            offered = {k: offered[k] | found[k] for k in offered}
        self.assertEqual(offered["misses"], {m["id"] for m in self.misses})
        self.assertEqual(offered["hops"], {h["id"] for h in self.hops if h["class"] == "held-unreached"})
        creep = self.hop("loop/l1", 3)
        batch = next(read_json(p) for p in (self.out / "dossier").glob("batch-*.json")
                     if creep["id"] in propose.cited(read_json(p))["hops"])
        edit = {"type": "source-link", "fields": {}, "misses": [], "hops": [creep["id"]], "sources": [], "why": ""}
        self.assertNotIn("it cites ids that are not in the batch", " ".join(
            propose.screen(edit, propose.cited(batch), {"graph": mock.Mock(labels={}), "held": {}, "classes": {}})[1]))


def collections_counter(items):
    import collections
    return collections.Counter(items)


if __name__ == "__main__":
    unittest.main()
