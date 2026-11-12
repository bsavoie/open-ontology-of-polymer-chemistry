"""Ontology reflection end to end with scripted sessions: mine the recorded searches, propose, screen, review, drop
what loses more than it fixes, apply to the overlay and the store, and revert."""
import datetime as dt
import json
import re
import unittest
from unittest import mock

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

    def co_use(self):
        """Two answers that each cited a PLA tensile strength and an elongation at break from other sources, the
        second found only by a second search (ten other tensile strengths fill the first search)."""
        def saved(question, statement, material, prop, doi):
            [identifier] = self.save(question, [finding(statement, material, "accepted", subject="wop-000001", doi=doi)])
            with knowledge.connect(self.root) as db:
                db.execute("UPDATE findings SET property=? WHERE id=?", (prop, identifier))
            return identifier
        ids = {"ts1": saved("a", "PLA 4032D tensile strength was 55 MPa.", "PLA 4032D", "tensile strength", "10.1/ts1"),
               "eb1": saved("b", "PLA 4032D elongation at break was 6%.", "PLA 4032D", "elongation at break", "10.1/eb1"),
               "ts2": saved("c", "PLA film tensile strength was 60 MPa.", "PLA film", "Tensile strength", "10.1/ts2"),
               "eb2": saved("d", "PLA film elongation at break was 4%.", "PLA film", "elongation at break (εb)",
                            "10.1/eb2")}
        for i in range(10):
            saved("p%d" % i, "PLA grade %d tensile strength was %d MPa." % (i, 50 + i), "PLA", "tensile strength",
                  "10.1/pad%d" % i)
        self.answer("q1", "What are the tensile strength and elongation at break of PLA 4032D?",
                    ["PLA 4032D tensile strength", "PLA 4032D elongation at break"], cited=[ids["ts1"], ids["eb1"]])
        self.answer("q2", "How strong and ductile is PLA film?",
                    ["PLA film tensile strength", "PLA film elongation at break"], cited=[ids["ts2"], ids["eb2"]])
        return ids

    def test_findings_used_together_are_mined_and_a_link_between_their_terms_returns_them_together(self):
        ids = self.co_use()
        self.assertNotIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))
        record = reflect.run(self.root, runner=Sessions(fail=AssertionError("no engine")), dry_run=True)
        self.assertEqual(record["missCounts"]["co-use"], 2)
        [group] = [g for g in record["dossier"] if g["about"].startswith("co-use")]
        self.assertEqual((group["about"], group["answers"], group["citedTogether"]),
                         ("co-use: elongation at break + tensile strength", 2, 2))
        self.assertEqual(group["sides"], {"elongation at break": ["elongation at break", "elongation at break (εb)"],
                                          "tensile strength": ["tensile strength", "Tensile strength"]})
        self.assertEqual(group["examples"][0]["found"]["id"], ids["ts1"])
        self.assertEqual(group["examples"][0]["foundLater"]["id"], ids["eb1"])

        def curate(groups):
            used = groups["co-use: elongation at break + tensile strength"]
            return [edit("property-term", used, term="tensile-strength", names=["tensile strength"]),
                    edit("link", used, term="tensile-strength", linked="elongation-at-break"),
                    edit("property-term", used, term="elongation-at-break", names=["elongation at break"]),
                    edit("link", used, term="tensile-strength", linked="tensile-strength"),
                    edit("link", used, term="tensile-strength", linked="yield-strength")]
        briefs = []

        def judge(items):
            briefs.extend(items)
            return [{"id": e["id"], "verdict": "approved", "reason": "Reported together from one tensile test."}
                    for e in items]
        record = reflect.run(self.root, runner=Sessions(curate, judge), engine="codex")
        why = {p["key"]: p["refused"] for p in record["proposed"]}
        self.assertEqual([k for k, v in why.items() if not v], ["p01", "p02", "p03"])
        self.assertIn("a link joins two different property terms", why["p04"])
        self.assertIn("yield-strength is neither", why["p05"][0])
        # The reviewer sees both terms' names, proposed in the same run, and the answers that used them together.
        link = next(b for b in briefs if b["type"] == "link")
        self.assertEqual(link["terms"], {"tensile-strength": ["tensile strength"],
                                         "elongation-at-break": ["elongation at break"]})
        self.assertEqual({e["foundLater"]["property"] for e in link["evidence"]},
                         {"elongation at break", "elongation at break (εb)"})
        # Measured once its terms were in force: it fixes both answers' co-use misses and loses nothing.
        p02 = next(p for p in record["proposed"] if p["key"] == "p02")
        co_use = {m["id"] for m in reflect.json.loads((knowledge.folder(self.root) / "reflect" / (
            "mined-%s.json" % record["id"])).read_text())["misses"] if m["kind"] == "co-use"}
        self.assertLessEqual(co_use, set(p02["effect"]["fixed"]))
        self.assertEqual(p02["effect"]["lostCount"], 0)
        self.assertGreater(p02["effect"]["added"], 0)
        self.assertEqual(len(record["applied"]), 3)
        self.assertEqual(reflect.links(self.root), [("elongation-at-break", "tensile-strength")])
        # A search naming a polymer and one term now returns the other's findings for it, from either side.
        found = self.ids("PLA 4032D tensile strength")
        self.assertIn(ids["eb1"], found)
        self.assertIn(ids["eb2"], found)
        self.assertIn(ids["ts1"], self.ids("PLA elongation at break"))
        self.assertNotIn(ids["eb1"], self.ids("tensile strength"))  # Not without a polymer.
        # Reverted, the link no longer adds anything; the terms stay.
        reflect.revert(self.root, p02["applied"])
        self.assertNotIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))
        self.assertEqual(reflect.links(self.root), [])
        fields, why = reflect.screen(self.root, edit("link", [], term="tensile-strength", linked="elongation-at-break"),
                                     set(), reflect.Store(self.root))
        self.assertIn("the same edit was reverted before", why)

    def test_a_link_gets_no_credit_for_a_miss_the_store_no_longer_has_nor_for_misses_of_other_kinds(self):
        ids = self.co_use()

        def curate(groups):
            used = groups["co-use: elongation at break + tensile strength"]
            return [edit("property-term", used, term="tensile-strength", names=["tensile strength"]),
                    edit("property-term", used, term="elongation-at-break", names=["elongation at break"]),
                    edit("link", used, term="tensile-strength", linked="elongation-at-break")]
        approve = lambda items: [{"id": e["id"], "verdict": "approved", "reason": "Yes."} for e in items]  # noqa: E731
        real = reflect.effect

        def late_finds_only(root, copy, edit_, changes, pool, found, cache):
            value = real(root, copy, edit_, changes, pool, found, cache)
            kinds = {m["id"]: m["kind"] for m in found}
            if edit_["type"] == "link":
                value["fixed"] = [m for m in value["fixed"] if kinds[m] != "co-use"]
            return value
        with mock.patch.object(reflect, "effect", late_finds_only):
            record = reflect.run(self.root, runner=Sessions(curate, approve), engine="codex")
        link = next(p for p in record["proposed"] if p["type"] == "link")
        self.assertTrue(link["effect"]["fixed"])  # It fixes the late finds of the same findings, but no co-use miss.
        self.assertEqual(link["dropped"], "it fixes no co-use miss")
        # With the same link already in force, replaying it again fixes nothing: the store no longer misses them.
        reflect.apply(self.root, {"id": "e-link", "type": "link", "fields": {"term": "tensile-strength",
                                                                           "linked": "elongation-at-break"}})
        self.assertIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))
        found = json.loads((knowledge.folder(self.root) / "reflect" / ("mined-%s.json" % record["id"])).read_text())["misses"]
        pool = reflect.answers(self.root)
        for answer in pool:
            answer["citedResolved"] = set(answer["cited"])
        copy = reflect.workspace(self.root, self.root / "copy")
        effect = reflect.effect(self.root, copy, {"type": "link", "fields": {"term": "tensile-strength",
                                                                           "linked": "elongation-at-break"}},
                                [], pool, found, {})
        self.assertEqual((effect["fixed"], effect["lostCount"], effect["added"]), ([], 0, 0))

    def test_a_link_whose_term_was_not_approved_is_not_applied_and_one_that_fixes_nothing_is_dropped(self):
        ids = self.co_use()

        def curate(groups):
            used = groups["co-use: elongation at break + tensile strength"]
            return [edit("property-term", used, term="tensile-strength", names=["tensile strength"]),
                    edit("property-term", used, term="elongation-at-break", names=["elongation at break"]),
                    edit("property-term", used, term="density", names=["density"]),
                    edit("link", used, term="tensile-strength", linked="elongation-at-break"),
                    edit("link", used, term="tensile-strength", linked="density")]
        judge = lambda items: [{"id": e["id"], "verdict": "rejected" if e["fields"].get("term") == "elongation-at-break"
                                else "approved", "reason": "?"} for e in items]  # noqa: E731
        record = reflect.run(self.root, runner=Sessions(curate, judge), engine="codex")
        proposed = {p["key"]: p for p in record["proposed"]}
        self.assertEqual(proposed["p04"]["notApplied"], ["a term it joins is not in force"])
        # No saved density finding for PLA: the link would add nothing an answer used, so it is dropped.
        self.assertEqual((proposed["p05"]["dropped"], proposed["p05"]["effect"]["fixed"]), ("it fixes no co-use miss", []))
        self.assertEqual(len(record["applied"]), 2)
        self.assertNotIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))

    def _bundle_run(self, link_loses=0):
        """A run proposing two terms and the link between them, where the elongation term alone loses a cited result
        (as the Tg term did in the 2026-11-05 trial) and the link, measured with it, loses `link_loses`."""
        def curate(groups):
            used = groups["co-use: elongation at break + tensile strength"]
            return [edit("property-term", used, term="tensile-strength", names=["tensile strength"]),
                    edit("property-term", used, term="elongation-at-break", names=["elongation at break"]),
                    edit("link", used, term="tensile-strength", linked="elongation-at-break")]
        approve = lambda items: [{"id": e["id"], "verdict": "approved", "reason": "Yes."} for e in items]  # noqa: E731
        real = reflect.effect

        def effect(root, copy, edit_, changes, pool, found, cache):
            value = real(root, copy, edit_, changes, pool, found, cache)
            if edit_["fields"].get("term") == "elongation-at-break" and edit_["type"] == "property-term":
                value.update(lostCount=1, lost=[["q1", "lost"]])
            if edit_["type"] == "link":
                value["lostCount"] = link_loses
            return value
        with mock.patch.object(reflect, "effect", effect):
            record = reflect.run(self.root, runner=Sessions(curate, approve), engine="codex")
        return record, {p["key"]: p for p in record["proposed"]}

    def test_a_term_dropped_alone_is_kept_with_the_link_that_needs_it_and_reverting_it_reverts_the_link(self):
        ids = self.co_use()
        record, proposed = self._bundle_run()
        term, link = proposed["p02"], proposed["p03"]
        self.assertNotIn("dropped", term)  # Lost one result alone; kept with the link, which fixes the co-use misses.
        self.assertEqual(term["effect"]["lostCount"], 1)
        self.assertTrue(link["effect"]["fixed"])
        edits = {e["id"]: e for e in knowledge.ontology_edits(self.root)}
        self.assertEqual(len(record["applied"]), 3)
        self.assertEqual(edits[term["applied"]]["with"], [link["applied"]])
        self.assertEqual(edits[link["applied"]]["with"], [term["applied"]])
        self.assertLess(record["applied"].index(term["applied"]), record["applied"].index(link["applied"]))
        self.assertIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))
        # The term out of force takes its link with it; the other term stays.
        entry = reflect.revert(self.root, term["applied"])
        self.assertEqual(entry["alsoReverted"], [link["applied"]])
        self.assertEqual(reflect.links(self.root), [])
        self.assertEqual(list(reflect.terms(self.root)), ["tensile-strength"])
        self.assertNotIn(ids["eb1"], self.ids("PLA 4032D tensile strength"))

    def test_a_link_and_the_term_it_needs_are_dropped_together(self):
        self.co_use()
        record, proposed = self._bundle_run(link_loses=5)
        self.assertEqual(proposed["p03"]["dropped"],
                         "it loses more cited results than it fixes misses, with the terms it needs")
        self.assertEqual(proposed["p02"]["dropped"], "it loses more cited results than it fixes misses")
        self.assertEqual(len(record["applied"]), 1)  # The tensile-strength term, kept on its own.
        self.assertEqual((list(reflect.terms(self.root)), reflect.links(self.root)), (["tensile-strength"], []))

    def test_a_test_condition_saved_as_a_finding_is_never_counted_as_used_together(self):
        ids = self.co_use()
        mined = lambda: reflect.run(self.root, runner=Sessions(fail=AssertionError("no engine")),  # noqa: E731
                                    dry_run=True)["missCounts"].get("co-use", 0)
        self.assertEqual(mined(), 2)
        with knowledge.connect(self.root) as db:  # q2's second finding is the test's temperature: no property.
            db.execute("UPDATE findings SET property='tensile test temperature' WHERE id=?", (ids["eb2"],))
        self.assertEqual(mined(), 1)
        self.assertTrue(reflect.CONDITION.search("DSC heating rate"))
        self.assertFalse(reflect.CONDITION.search("heat deflection temperature"))

    def test_an_unfiled_finding_is_offered_by_names_a_name_edit_could_add(self):
        long = "Alternating copolymer derived from 1,4-butanediol diacrylate and cyclooctene, extruded film"
        saved = {material: self.save("u%d" % i, [finding("The %s had a modulus of %d MPa." % (material, 100 + i),
                                                         material, "accepted", doi="10.1/u%d" % i)])[0]
                 for i, material in enumerate([long, "Derakane Momentum 470-300", "Polyethersulfone, BASF"])}
        names = {m["finding"]: m["names"] for m in reflect.unfiled(self.root, reflect.Store(self.root), "", {})}
        self.assertNotIn(saved[long], names)  # Longer than any name search reads: no name edit could fix it.
        self.assertEqual(names[saved["Derakane Momentum 470-300"]], ["Derakane Momentum 470-300"])
        self.assertEqual(names[saved["Polyethersulfone, BASF"]], ["Polyethersulfone"])  # A company is no name.

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
