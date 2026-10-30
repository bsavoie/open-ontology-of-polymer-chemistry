"""Ontology reflection end to end with scripted sessions: mine the recorded searches, propose, screen, review, drop
what loses more than it fixes, apply to the overlay and the store, and revert."""
import datetime as dt
import json
import re
import unittest

import test_knowledge_search as base
from oopc import engines, knowledge, loop, reflect
from oopc.util import atomic_json

finding = base.finding
PVC = "wop-000016"
GLASS = "glass-transition-temperature"


def stamp(seconds):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).isoformat()


class Sessions:
    """A curator and a reviewer: `curate(dossier)` gives the edits (with the groups' miss ids by what they are about),
    `judge(edits)` the verdicts. Any other step is an exception to raise."""

    def __init__(self, curate=None, judge=None, fail=None):
        self.curate, self.judge, self.fail, self.calls = curate, judge, fail, []

    def __call__(self, engine, prompt, schema, **options):
        self.calls.append({"engine": engine, "schema": schema, "web": options.get("web"), "tools": options.get("tools")})
        if self.fail:
            raise self.fail
        if schema is reflect.CURATOR_SCHEMA:
            groups = json.loads(re.search(r"<dossier[^>]*>\n(.*)\n</dossier>", prompt, re.S).group(1))
            answer = {"edits": self.curate({g["about"]: g["misses"] for g in groups}), "notes": ""}
        else:
            answer = {"verdicts": self.judge(json.loads(re.search(r"<edits>\n(.*)\n</edits>", prompt, re.S).group(1))),
                      "notes": ""}
        usage = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100}
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer, "usage": usage,
                "observedTools": [], "agentSeconds": 1.0}


def edit(kind, misses, sources=(), **fields):
    value = {"polymer": "", "field": "", "name": "", "ambiguous": False, "finding": "", "subject": "", "term": "",
             "names": []}
    value.update(fields)
    return {"type": kind, "fields": value, "misses": misses, "sources": [{"url": u, "quote": q} for u, q in sources],
            "why": "A test edit."}


class Reflection(unittest.TestCase):
    save = base.KnowledgeSearch.save

    def setUp(self):
        base.KnowledgeSearch.setUp(self)  # A small graph release: PLA, PCL, the polyethylene family and others.
        records = [{"@id": i, "@type": "PolymerConcept", "label": label, "abbreviations": abbreviations,
                    "status": "seed", "layer": "science"}
                   for i, label, abbreviations in base.POLYMERS + [(PVC, "Poly(vinyl chloride)", ["PVC"])]]
        records += [{"@id": "claim:%s-%s-%s" % (s, p, o), "@type": "Claim", "label": "%s %s %s" % (s, p, o), "subject": s,
                     "predicate": p, "object": o, "context": {}, "evidence": [], "status": "seed", "layer": "science"}
                    for member, family in base.FAMILIES for s, p, o in ((member, "broader", family),
                                                                         (family, "narrower", member))]
        from oopc.release import build_release
        from oopc.vocabulary import get_ontology
        build_release(self.root / "releases/with-pvc", records, get_ontology(), {})
        release_id = json.loads((self.root / "releases/with-pvc/manifest.json").read_text())["release_id"]
        (self.root / "releases/with-pvc").rename(self.root / "releases" / release_id)
        atomic_json(self.root / "releases/current.json", {"release_id": release_id})
        self.clock = 0

    def answer(self, identifier, question, steps, cited=()):
        """A completed answer with its trace: `steps` are knowledge queries, or ("web", query) for a web search."""
        run = self.root / ".oopc/runs" / ("run-" + identifier)
        run.mkdir(parents=True)
        queries = [s for s in steps if isinstance(s, str)]
        run.joinpath("events.jsonl").write_text("".join(json.dumps(
            {"operation": "knowledge.search_knowledge", "status": "ok", "sequence": i,
             "request": {"tool": "search_knowledge", "arguments": {"q": q, "limit": 10}}}) + "\n"
            for i, q in enumerate(queries, 1)))
        tools = [{"type": "mcp_tool_call", "tool": "search_knowledge"} if isinstance(s, str) else
                 {"type": "web_search", "query": s[1]} for s in steps]
        folder = knowledge.folder(self.root) / "questions" / identifier
        self.clock += 10
        atomic_json(folder / "question.json", {"id": identifier, "question": question, "status": "completed",
                                               "runId": "run-" + identifier, "startedAt": stamp(self.clock),
                                               "finishedAt": stamp(self.clock + 5)})
        atomic_json(folder / "result.json", {"answer": {"answer": " ".join("`%s`" % c for c in cited),
                                                        "citations": list(cited)}, "observedTools": tools})

    def store(self):
        """Findings and answers with one miss of each kind, and a finding two answers cite through its polymer id."""
        tg = self.save("a", [finding("PLA 4032D had a Tg of 61 °C by DSC.", "PLA 4032D", "accepted", doi="10.1/tg")])[0]
        self.save("b", [finding("PLA film was annealed at a temperature of %d °C." % (70 + i), "PLA film", "accepted",
                                doi="10.1/an%d" % i) for i in range(10)])
        [ingeo] = self.save("c", [finding("Ingeo 4032D film crystallinity was 45%.", "Ingeo 4032D film", "accepted",
                                          subject="wop-000001", doi="10.1/in")])
        [geon] = self.save("d", [finding("Geon 103 resin had a tensile strength of 52 MPa.", "Geon 103 resin", "accepted",
                                         doi="10.1/ge")])
        [pcl] = self.save("e", [finding("Capa 6800 melted at 60 °C.", "Capa 6800", "accepted", subject="wop-000002",
                                        doi="10.1/pc")])
        [film] = self.save("f", [finding("Polyvinyl chloride film absorbed 0.4% water.", "polyvinyl chloride film",
                                         "accepted", doi="10.1/w")])
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET property='Tg' WHERE id=?", (tg,))
        self.answer("q1", "What is the Tg of PLA?", ["PLA glass transition temperature", "PLA Tg"], cited=[tg])
        self.answer("q2", "What is the tensile strength of polyvinyl chloride?", ["polyvinyl chloride tensile strength"])
        self.answer("q3", "How crystalline is PLA film?", ["PLA crystallinity"], cited=[ingeo])
        self.answer("q4", "How crystalline is annealed PLA?", ["PLA crystallinity annealing"], cited=[ingeo])
        self.answer("q5", "What is the dielectric constant of Halar ECTFE?",
                    ["Halar ECTFE dielectric constant", ("web", "ECTFE dielectric constant datasheet")])
        # q6 saved again what the store held: its search, by a name the graph lacks, never returned it.
        knowledge.deposit(self.root, "q6", {"findings": [finding("Capa 6800 melted at 60 °C.", "Capa 6800", "accepted",
                                                                 subject="wop-000002", doi="10.1/pc")], "sources": []},
                          engine="codex")
        self.answer("q6", "Is this caprolactone grade crystalline?", ["biodegradable grade crystallinity"])
        return {"tg": tg, "ingeo": ingeo, "geon": geon, "pcl": pcl, "film": film}

    def curate(self, ids):
        def edits(groups):
            name = groups["name: polyvinyl chloride"]
            unfiled = groups["name: geon 103 resin"]
            late = groups["polymer: Polylactide; property: tg"]
            return [edit("name", name, [("https://example.org/pvc", "Polyvinyl chloride (PVC) is a thermoplastic.")],
                         polymer=PVC, field="alternateNames", name="polyvinyl chloride"),
                    edit("annotation", unfiled, finding=ids["geon"], subject=PVC),
                    edit("annotation", name, finding=ids["film"], subject=PVC),
                    edit("property-term", late, term=GLASS, names=["glass transition temperature", "Tg"]),
                    edit("annotation", late, finding=ids["ingeo"], subject="wop-000002"),
                    edit("name", name, polymer=PVC, field="tradeNames", name="Vinylite"),
                    edit("name", name, [("https://example.org/geon", "Geon vinyl compounds")], polymer=PVC,
                         field="tradeNames", name="Geon"),
                    edit("name", late, [("https://example.org/pla", "PLA")], polymer="wop-000002",
                         field="abbreviations", name="PLA"),
                    edit("name", ["m-000000000000"], [("https://example.org/pvc", "PVC-U is rigid PVC")], polymer=PVC,
                         field="abbreviations", name="PVC-U")]
        return edits

    @staticmethod
    def judge(items):
        return [{"id": e["id"], "verdict": "rejected" if e["fields"].get("name") == "Geon" else "approved",
                 "reason": "The source says so."} for e in items]

    def ids(self, query):
        found = knowledge.search(self.root, query, compact=True)
        return [f["id"] for group in ("reviewed", "added", "unreviewed") for f in found[group]]

    def test_mining_finds_each_kind_of_miss_without_an_engine_or_a_write(self):
        ids = self.store()
        record = reflect.run(self.root, runner=Sessions(fail=AssertionError("no engine")), dry_run=True)
        self.assertEqual((record["status"], record["answers"], record["searches"]), ("dry-run", 6, 7))
        # Unresolved names: q2's and q5's questions and searches, and the Geon and PVC film findings.
        self.assertEqual(record["missCounts"], {"late-find": 1, "unresolved-name": 6, "saved-again": 1,
                                                "empty-then-web": 1})
        about = {g["about"]: g for g in record["dossier"]}
        self.assertEqual(about["polymer: Polylactide; property: tg"]["examples"][0]["q"], "PLA glass transition temperature")
        self.assertEqual(about["name: geon 103 resin"]["findings"][0]["id"], ids["geon"])
        self.assertEqual(about["name: ectfe"]["kinds"], {"unresolved-name": 2})
        self.assertEqual(about["polymer: none named; words: halar ectfe dielectric constant"]["examples"][0]["webQuery"],
                         "ECTFE dielectric constant datasheet")
        self.assertEqual(about["polymer: Polycaprolactone; property: "]["kinds"], {"saved-again": 1})
        self.assertFalse((knowledge.folder(self.root) / "reflect").exists())
        self.assertFalse((knowledge.folder(self.root) / knowledge.ONTOLOGY).exists())

    def test_a_run_applies_what_the_reviewer_approved_and_the_replay_kept_and_records_who_vouched(self):
        ids = self.store()
        before = {q: self.ids(q) for q in ("PLA crystallinity", "polyvinyl chloride tensile strength",
                                           "PLA glass transition temperature", "PVC strength")}
        self.assertNotIn(ids["tg"], before["PLA glass transition temperature"])
        sessions = Sessions(self.curate(ids), self.judge)
        record = reflect.run(self.root, runner=sessions, engine="codex")
        self.assertEqual(record["status"], "done")
        self.assertEqual([c["schema"] is reflect.CURATOR_SCHEMA for c in sessions.calls], [True, False])
        self.assertTrue(all(c["web"] and c["tools"] is None for c in sessions.calls))
        why = {p["key"]: p["refused"] for p in record["proposed"]}
        self.assertEqual([k for k, v in why.items() if not v], ["p01", "p02", "p03", "p04", "p05", "p07"])
        self.assertIn("it carries no source with an address and a quote", why["p06"])
        self.assertIn("'PLA' also names wop-000001", why["p08"][0])
        self.assertIn("it cites misses that are not in the dossier: m-000000000000", why["p09"])
        verdicts = {p["key"]: (p["review"]["verdict"], p.get("dropped")) for p in record["proposed"] if p.get("review")}
        self.assertEqual(verdicts["p07"][0], "rejected")
        self.assertEqual(verdicts["p05"], ("approved", "it loses more cited results than it fixes misses"))
        effects = {p["key"]: p["effect"] for p in record["proposed"] if p.get("effect")}
        self.assertEqual((len(effects["p05"]["fixed"]), effects["p05"]["lostCount"]), (0, 2))
        # The name filed the film finding before its own annotation came to be applied, which is left out.
        p03 = next(p for p in record["proposed"] if p["key"] == "p03")
        self.assertEqual(p03["notApplied"], ["the finding is filed under %s already" % PVC])
        self.assertEqual(knowledge.get(self.root, ids["film"])["subject"], PVC)
        self.assertEqual(len(effects["p01"]["fixed"]), 3)  # q2's question and search, and the film it files.
        self.assertEqual(len(record["applied"]), 3)
        # In force: the name filters a search to PVC, the annotation files the Geon finding, the term finds "Tg".
        applied = {e["type"]: e for e in knowledge.ontology_edits(self.root)}
        self.assertEqual({e["status"] for e in applied.values()}, {"applied"})
        self.assertEqual(applied["name"]["review"]["verdict"], "approved")
        self.assertEqual(applied["name"]["proposedBy"]["engine"], "codex")
        self.assertEqual(applied["name"]["effect"]["fixed"], 3)
        self.assertEqual(knowledge.get(self.root, ids["geon"])["subject"], PVC)
        self.assertIn(ids["geon"], self.ids("polyvinyl chloride tensile strength"))
        self.assertIn(ids["geon"], self.ids("PVC strength"))
        self.assertIn(ids["tg"], self.ids("PLA glass transition temperature"))
        self.assertEqual(self.ids("PLA crystallinity"), before["PLA crystallinity"])  # The dropped edit did nothing.
        self.assertEqual(knowledge.get(self.root, ids["ingeo"])["subject"], "wop-000001")
        self.assertEqual(knowledge.polymer_ids(self.root, "Polyvinyl Chloride"), {PVC})
        # The run's record is private and kept beside its misses; the loop shows a summary.
        status = loop.status(self.root)["reflection"]
        self.assertEqual((status["everyDays"], len(status["inForce"]), status["runs"][0]["applied"]),
                         (0, 3, record["applied"]))
        self.assertEqual(status["runs"][0]["dropped"], 1)
        self.assertTrue((knowledge.folder(self.root) / "reflect" / ("mined-%s.json" % record["id"])).exists())
        self.assertFalse(list((knowledge.folder(self.root) / "reflect").glob("work-*")))  # The store copies are gone,
        self.assertFalse([k for k in knowledge._ALIASES if "/work-" in str(k)])  # and so is what search cached of them.

        # Revert undoes each; a search reads the store as it did before; the same edit is never proposed again.
        for identifier in record["applied"]:
            reflect.revert(self.root, identifier)
        self.assertEqual({q: self.ids(q) for q in before}, before)
        self.assertFalse(knowledge.get(self.root, ids["geon"]).get("subject"))
        with knowledge.connect(self.root) as db:
            self.assertFalse({r[0] for r in db.execute("SELECT name FROM sqlite_master")} & set(knowledge.TERMS))
        with self.assertRaises(ValueError):
            reflect.revert(self.root, record["applied"][0])
        fields, why = reflect.screen(self.root, edit("name", [], [("https://example.org/pvc", "polyvinyl chloride")],
                                                     polymer=PVC, field="alternateNames", name="Polyvinyl chloride"),
                                     set(), reflect.Store(self.root))
        self.assertIn("the same edit was reverted before", why)

    def test_a_new_name_files_the_unfiled_findings_that_use_it_and_revert_unfiles_them(self):
        [film] = self.save("a", [finding("Polyvinyl chloride film absorbed 0.4% water.", "polyvinyl chloride film",
                                         "accepted", doi="10.1/w")])
        self.assertFalse(knowledge.get(self.root, film).get("subject"))
        entry = {"id": "e-test", "type": "name", "fields": {"polymer": PVC, "field": "alternateNames",
                                                            "name": "Polyvinyl chloride", "ambiguous": False}}
        changes = reflect.apply(self.root, entry)
        self.assertEqual(changes, [{"finding": film, "was": "", "to": PVC, "before": None}])
        self.assertEqual(knowledge.get(self.root, film)["subject"], PVC)
        reflect.revert(self.root, "e-test")
        self.assertFalse(knowledge.get(self.root, film).get("subject"))
        self.assertEqual(knowledge.ontology_edits(self.root)[0]["status"], "reverted")

    def test_a_failed_session_is_tried_once_more_then_the_run_fails_with_its_reason_and_changes_nothing(self):
        self.store()
        sessions = Sessions(fail=engines.EngineError("crashed", "The session crashed"))
        record = reflect.run(self.root, runner=sessions, engine="claude-code")
        self.assertEqual((record["status"], record["reason"], len(sessions.calls)), ("failed", "crashed", 2))
        self.assertEqual(knowledge.ontology_edits(self.root), [])
        sessions = Sessions(fail=engines.EngineError("quota", "Usage limit reached"))
        self.assertEqual(reflect.run(self.root, runner=sessions, engine="codex")["reason"], "quota")
        self.assertEqual(len(sessions.calls), 1)
        # Any other error is recorded too, so the loop waits its days rather than start a session every hour.
        loop.update_settings(self.root, {"reflectEveryDays": 7})
        with self.assertRaises(RuntimeError):
            reflect.run(self.root, runner=Sessions(fail=RuntimeError("a bug")), engine="codex")
        self.assertEqual((reflect.runs(self.root)[0]["status"], reflect.runs(self.root)[0]["reason"]), ("failed", "crashed"))
        self.assertEqual(reflect.stage(self.root, runner=sessions, engine="codex"), {"status": "not-due"})

    def test_the_loop_runs_it_only_when_switched_on_and_due(self):
        self.store()
        self.assertEqual(loop.settings(self.root)["reflectEveryDays"], 0)  # Off by default.
        sessions = Sessions(lambda groups: [], self.judge)
        self.assertEqual(reflect.stage(self.root, runner=sessions, engine="codex"), {"status": "off"})
        for bad in (-1, 366, 1.5, True):
            with self.subTest(days=bad), self.assertRaises(ValueError):
                loop.update_settings(self.root, {"reflectEveryDays": bad})
        loop.update_settings(self.root, {"reflectEveryDays": 7})
        self.assertEqual(reflect.stage(self.root, runner=sessions, engine="codex")["status"], "done")
        self.assertEqual(reflect.stage(self.root, runner=sessions, engine="codex"), {"status": "not-due"})
        later = dt.datetime.now(dt.timezone.utc).timestamp() + 7 * 86400 + 60
        self.assertEqual(reflect.stage(self.root, runner=sessions, engine="codex", moment=later)["status"],
                         "nothing-to-fix")  # Mining resumes after the answers the last run mined.
        self.assertEqual(len(sessions.calls), 1)
        entry = loop.tick(self.root, runner=sessions, engine="codex")
        self.assertEqual(entry["reflection"], {"status": "not-due"})

    def test_search_reads_names_from_the_overlay_only_while_they_are_applied(self):
        self.assertEqual(knowledge.polymer_ids(self.root, "Vinylite"), set())
        value = {"format": reflect.FORMAT, "edits": [{"id": "e-1", "type": "name", "status": "applied",
                                                      "fields": {"polymer": PVC, "name": "Vinylite"}}]}
        atomic_json(knowledge.folder(self.root) / knowledge.ONTOLOGY, value)
        self.assertEqual(knowledge.polymer_ids(self.root, "vinylite"), {PVC})
        self.assertIn("pvc", {n.lower() for n in knowledge.polymer_aliases(self.root)["vinylite"]})
        value["edits"][0]["status"] = "reverted"
        atomic_json(knowledge.folder(self.root) / knowledge.ONTOLOGY, value)
        self.assertEqual(knowledge.polymer_ids(self.root, "Vinylite"), set())
        self.assertNotIn("vinylite", knowledge.polymer_aliases(self.root))


if __name__ == "__main__":
    unittest.main()
