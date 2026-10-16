"""The core loop end to end with a scripted engine: ask, deposit, review, reuse."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from oopc import engines, knowledge, loop, reviewer, sources
from oopc.ask import ANSWER_SCHEMA, Questions, reuse_stats
from oopc.release import build_release
from oopc.trace import TraceStore
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology

FINDING = {"statement": "PLA film annealed at 100 °C for 1 h reached 45% crystallinity by DSC.",
           "material": "PLA film, 4032D", "property": "crystallinity", "value": "45", "unit": "%",
           "conditions": "annealed 100 °C, 1 h; DSC first heating", "subject": "wop-000001",
           "sourceTitle": "Annealing of PLA films", "sourceUrl": "https://example.org/pla-annealing",
           "sourceDoi": "10.1234/example.1", "locator": "Table 2", "excerpt": "crystallinity of 45% after 1 h at 100 °C"}


def answer(text, citations, findings=(), sources=()):
    return {"answer": text, "citations": list(citations), "findings": list(findings), "sources": list(sources),
            "limitations": [], "openQuestions": ["How does annealing time change crystallinity?"]}


class ScriptedEngine:
    """Returns scripted answers in order; calls tools the way a researcher would."""

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        self.calls.append({"engine": engine, "schema": schema, "tools": tools is not None, "prompt": prompt})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        value = step(tools) if callable(step) else step
        return {"engine": engine, "model": "scripted", "sessionId": "s%d" % len(self.calls), "answer": value,
                "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100},
                "observedTools": [], "agentSeconds": 1.0}


class CoreLoopTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-loop-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        build_release(self.root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                      "label": "Polylactide", "abbreviations": ["PLA"], "status": "seed", "layer": "science"}], get_ontology(), {})
        atomic_json(self.root / "releases/current.json", {"release_id": json.loads(
            (self.root / "releases/fixture/manifest.json").read_text())["release_id"]})
        # The release folder is named by its identity when resolved by id.
        release_id = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / release_id)
        loop.update_settings(self.root, {"spotCheckRate": 0})

    def ask(self, service, question):
        view = service.submit({"question": question, "budgetSeconds": 300, "authorizeSubscription": True,
                               "runtime": "codex"})
        service.wait(10, reviews=True)  # A background review must not outlive the test's folder.
        return service.get(view["id"])

    def test_answer_deposit_review_and_reuse(self):
        first = ScriptedEngine(answer("Crystallinity reached 45% `https://example.org/pla-annealing`.",
                                      ["https://example.org/pla-annealing"], [FINDING, {"statement": "no source"}],
                                      [{"title": "Annealing of PLA films", "url": "https://example.org/pla-annealing",
                                        "doi": "", "locator": "Table 2", "excerpts": ["45%"], "supports": "crystallinity",
                                        "conditions": "100 °C"}]))
        service = Questions(self.root, runner=first)
        done = self.ask(service, "How does annealing change PLA crystallinity?")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["deposit"]["findings"], 1)
        self.assertEqual(done["deposit"]["dropped"], 1)  # No source: never stored or reviewed.
        self.assertEqual(done["deposit"]["reviewStatus"], "pending")
        self.assertIs(first.calls[0]["schema"], ANSWER_SCHEMA)
        self.assertTrue(first.calls[0]["tools"])
        [finding] = done["findings"]
        self.assertEqual(finding["status"], "unreviewed")

        review = ScriptedEngine({"verdicts": [{"id": finding["id"], "verdict": "supported",
                                               "reason": "Table 2 reports 45% after 1 h at 100 °C."}], "notes": ""})
        result = loop.tick(self.root, runner=review, engine="claude-code")
        self.assertEqual(result["reviews"][0]["status"], "reviewed")
        self.assertFalse(review.calls[0]["tools"])  # The reviewer gets web only, never the graph or knowledge.
        self.assertIn(finding["statement"], review.calls[0]["prompt"])
        self.assertEqual(knowledge.get(self.root, finding["id"])["review"]["reason"],
                         "Table 2 reports 45% after 1 h at 100 °C.")

        def researcher(tools):
            found = tools.call("search_knowledge", {"q": "PLA crystallinity annealing"})
            self.assertEqual([f["id"] for f in found["reviewed"]], [finding["id"]])
            return answer(f"It reached 45% `{finding['id']}`.", [finding["id"]])
        second = self.ask(Questions(self.root, runner=ScriptedEngine(researcher)), "What crystallinity does annealed PLA reach?")
        self.assertEqual(second["reusedFindings"], {"cited": 1, "supported": 1, "added": 0})
        self.assertEqual(second["deposit"]["reviewStatus"], "nothing-to-review")
        events = TraceStore(self.root).run(second["runId"]).events()["events"]
        self.assertEqual([(e["operation"], e["status"]) for e in events if e["kind"] == "access"],
                         [("knowledge.search_knowledge", "ok")])
        self.assertEqual(reuse_stats(self.root), {"answered": 2, "citingReviewed": 1})
        self.assertEqual(knowledge.about(self.root, "wop-000001")[0]["id"], finding["id"])

    def test_unsupported_findings_are_hidden_and_unassessed_ones_become_uncertain(self):
        second = dict(FINDING, statement="PLA reached 60% crystallinity after 10 min.", locator="Figure 3")
        service = Questions(self.root, runner=ScriptedEngine(answer("x", [], [FINDING, second])))
        done = self.ask(service, "What crystallinity does annealed PLA reach?")
        ids = [f["id"] for f in done["findings"]]
        reviewer.review(self.root, done["id"], engine="codex", runner=ScriptedEngine(
            {"verdicts": [{"id": ids[1], "verdict": "unsupported", "reason": "Figure 3 shows 35%."},
                          {"id": "finding:someone-else", "verdict": "supported", "reason": "ignored"}], "notes": ""}))
        statuses = {f["id"]: f["status"] for f in knowledge.for_question(self.root, done["id"])}
        self.assertEqual(statuses, {ids[0]: "uncertain", ids[1]: "unsupported"})
        found = knowledge.search(self.root, "PLA crystallinity")
        self.assertEqual([f["id"] for f in found["unreviewed"]], [ids[0]])
        self.assertEqual(found["reviewed"], [])

    def test_transient_failure_retries_once_then_fails_with_its_reason(self):
        crash = engines.EngineError("crashed", "exit 1")
        service = Questions(self.root, runner=ScriptedEngine(crash, answer("ok", [])))
        self.assertEqual(self.ask(service, "A question that recovers after one crash")["status"], "completed")
        service = Questions(self.root, runner=ScriptedEngine(crash, crash))
        failed = self.ask(service, "A question that crashes twice in a row")
        self.assertEqual((failed["status"], failed["error"]["reason"], failed["attempts"]), ("failed", "crashed", 2))
        self.assertTrue(failed["canRetry"])
        self.assertEqual(TraceStore(self.root).run(failed["runId"]).meta()["status"], "failed")

    def test_timeouts_and_quota_are_not_retried_automatically(self):
        for reason in ("timeout", "quota", "not-signed-in", "rejected"):
            with self.subTest(reason=reason):
                engine = ScriptedEngine(engines.EngineError(reason, "stopped"))
                failed = self.ask(Questions(self.root, runner=engine), "Question failing with " + reason)
                self.assertEqual((failed["status"], failed["error"]["reason"], len(engine.calls)), ("failed", reason, 1))

    def test_a_question_submitted_while_the_drainer_finishes_is_still_answered(self):
        # CL-5: the submit saw the drainer alive and started none; the drainer had already found the queue empty.
        service = Questions(self.root, runner=ScriptedEngine(answer("first", []), answer("second", [])))
        finish = service._drain_locked
        late = []

        def drain_then_submit():
            finish()
            if not late:
                late.append(service.submit({"question": "A question that arrives as the drainer exits",
                                            "budgetSeconds": 300, "authorizeSubscription": True, "runtime": "codex"}))
        service._drain_locked = drain_then_submit
        first = service.submit({"question": "What crystallinity does annealed PLA reach?", "budgetSeconds": 300,
                                "authorizeSubscription": True, "runtime": "codex"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (late and service._read(late[0]["id"])["status"] == "completed"):
            time.sleep(0.05)
        self.assertEqual(service._read(first["id"])["status"], "completed")
        self.assertEqual(service._read(late[0]["id"])["status"], "completed")
        service.wait(10)

    def test_manual_retry_and_interrupted_recovery(self):
        service = Questions(self.root, runner=ScriptedEngine(engines.EngineError("timeout", "limit"), answer("ok", [])))
        failed = self.ask(service, "A question that times out first")
        service.retry(failed["id"])
        service.wait(10)
        self.assertEqual(service.get(failed["id"])["status"], "completed")
        with self.assertRaises(ValueError):
            service.retry(failed["id"])
        # A question left running by a stopped app is interrupted and retried once.
        path = self.root / ".oopc/loop/questions" / failed["id"]
        stuck = Questions(self.root, runner=ScriptedEngine(answer("recovered", [])))
        item = json.loads((path / "question.json").read_text())
        item["status"] = "running"
        atomic_json(path / "question.json", item)
        stuck.recover()
        stuck.wait(10)
        view = stuck.get(failed["id"])
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["result"]["answer"], "recovered")

    def test_failed_review_is_retried_once_then_left_failed(self):
        service = Questions(self.root, runner=ScriptedEngine(answer("x", [], [FINDING])))
        done = self.ask(service, "What crystallinity does annealed PLA reach?")
        for expected in ("failed", "failed"):
            result = loop.tick(self.root, runner=ScriptedEngine(engines.EngineError("invalid-output", "bad")),
                               engine="codex")
            self.assertEqual(result["reviews"][0]["status"], expected)
        self.assertEqual(loop.tick(self.root, runner=ScriptedEngine(), engine="codex")["reviews"], [])
        self.assertEqual(knowledge.deposit_summary(self.root, done["id"])["reviewStatus"], "failed")

    def test_a_failed_review_is_retried_on_another_engine(self):
        # The 200-task run: two reviews stalled twice on the same engine.
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [FINDING])), reviews=False),
                        "What crystallinity does annealed PLA reach?")
        with self.assertRaises(engines.EngineError):
            reviewer.review(self.root, done["id"], runner=ScriptedEngine(engines.EngineError("timeout", "stalled")),
                            engine="claude-code")
        chosen = []
        with mock.patch.object(engines, "choose_engine",
                               lambda preferred=None, avoid=None, **k: chosen.append((preferred, avoid)) or "codex"):
            reviewer.review(self.root, done["id"], runner=ScriptedEngine({"verdicts": [], "notes": ""}))
        self.assertEqual(chosen, [("codex", "claude-code")])  # The producer's engine, avoiding the one that failed.

    def test_a_review_runs_in_a_fresh_session_of_the_engine_that_wrote_the_answer(self):
        # Campaign wave 2 (2026-10-11): Claude could not open 41% of the sources Codex had read.
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [FINDING])), reviews=False),
                        "What crystallinity does annealed PLA reach?")
        chosen = []
        with mock.patch.object(engines, "choose_engine",
                               lambda preferred=None, avoid=None, **k: chosen.append((preferred, avoid)) or "codex"):
            reviewer.review(self.root, done["id"], runner=ScriptedEngine({"verdicts": [], "notes": ""}))
        self.assertEqual(chosen, [("codex", None)])

    def test_research_queue_is_explicit_off_by_default_and_weekly_limited(self):
        with self.assertRaises(ValueError):
            loop.add_research(self.root, "short")
        limit = 3
        for index in range(limit + 1):
            loop.add_research(self.root, "Research gap number %d about PLA annealing" % index)
        self.assertEqual(len(loop.research_queue(self.root)), limit + 1)
        self.assertEqual(loop.research_stage(self.root, runner=ScriptedEngine())["status"], "off")
        self.assertEqual(loop.settings(self.root)["researchPerWeek"], 0)  # Off by default.
        for bad in (-1, 101, 2.5, "10", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                loop.update_settings(self.root, {"researchPerWeek": bad})
        loop.update_settings(self.root, {"researchPerWeek": limit})
        for _ in range(limit):
            outcome = loop.research_stage(self.root, runner=ScriptedEngine(answer("ok", [])))
            self.assertEqual((outcome["status"], outcome["outcome"]), ("asked", "completed"))
        self.assertEqual(loop.research_stage(self.root, runner=ScriptedEngine())["status"], "weekly-limit-reached")
        research = [t for t in Questions(self.root).list()["tasks"] if t["origin"] == "research"]
        self.assertEqual(len(research), limit)

    def test_only_figure_readings_conversions_and_combined_values_wait_for_review(self):
        # Owner, 2026-10-14: the researcher's own doubt flags caught 1 error in 1,868; review what is derived.
        confident = dict(FINDING, derivation="read")
        unsure = dict(FINDING, statement="PLA reached about 50% crystallinity after 2 h, read from Figure 4.",
                      value="50", locator="Figure 4", derivation="figure")
        converted = dict(FINDING, statement="PLA crystallinity of 45% corresponds to 42 J/g of melting enthalpy.",
                         property="melting enthalpy", value="42", unit="J/g", derivation="converted")
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident, unsure, converted]))),
                        "What crystallinity does annealed PLA reach?")
        statuses = [f["status"] for f in done["findings"]]
        self.assertEqual(statuses, ["accepted", "unreviewed", "unreviewed"])
        self.assertEqual([f.get("reviewFlag") for f in done["findings"]],
                         [None, "Read from a figure", "Converted or calculated"])
        self.assertIn("derivation", ANSWER_SCHEMA["properties"]["findings"]["items"]["required"])
        self.assertNotIn("reviewFlag", ANSWER_SCHEMA["properties"]["findings"]["items"]["properties"])

    def test_after_the_answer_titles_come_from_crossref_and_sources_are_captured(self):
        # Campaign 2026-10: a typed title ("vinimidazole") reached a checked answer; checks hung on pages that
        # opened one day and not the next.
        page = ("<html><body>" + "<p>Annealed films were measured by DSC.</p>" * 60 +
                "<p>The crystallinity of 45% after 1 h at 100 °C was the highest.</p></body></html>").encode()
        message = {"title": ["Annealing of poly(lactide) <i>films</i>"], "issued": {"date-parts": [[2020]]}}
        pages = {sources.CROSSREF + "10.1234/example.1": (200, "application/json", json.dumps({"message": message}).encode()),
                 "https://example.org/pla-annealing": (200, "text/html", page)}
        network = lambda url, accept="*/*", timeout=20: next(
            ((s, k, b, url) for prefix, (s, k, b) in pages.items() if url.startswith(prefix)), (404, "", b"", url))
        typed = dict(FINDING, derivation="read", sourceTitle="Anealing of PLA film")
        with mock.patch.object(sources, "get", network), mock.patch.object(sources, "network_allowed", return_value=True):
            done = self.ask(Questions(self.root, runner=ScriptedEngine(answer(
                "Crystallinity reached 45% `https://example.org/pla-annealing`.", ["https://example.org/pla-annealing"],
                [typed]))), "What crystallinity does annealed PLA reach?")
        saved = knowledge.get(self.root, done["findings"][0]["id"])
        self.assertEqual((saved["source"]["title"], saved["titleAsWritten"]),
                         ("Annealing of poly(lactide) films", "Anealing of PLA film"))
        self.assertEqual(knowledge.search(self.root, "poly(lactide) crystallinity")["added"][0]["id"], saved["id"])
        kept = sources.captured(self.root, {"url": "https://example.org/pla-annealing", "doi": "10.1234/example.1"})
        self.assertIn("crystallinity of 45%", kept["text"])

    def test_answers_stored_before_the_narrow_review_keep_their_flags(self):
        old = [dict(FINDING, needsReview=False, reviewFlag=""),
               dict(FINDING, statement="PLA reached 50% crystallinity.", value="50", needsReview=True,
                    reviewFlag="Doubtful")]
        self.assertEqual([(f["needsReview"], f["reviewFlag"]) for f in map(knowledge.clean_finding, old)],
                         [(False, ""), (True, "Doubtful")])

    def test_the_researcher_decides_which_findings_need_review(self):
        confident = dict(FINDING, derivation="read")
        unsure = dict(FINDING, statement="PLA reached about 50% crystallinity after 2 h, read from Figure 4.",
                      value="50", locator="Figure 4", derivation="figure")
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident, unsure]))),
                        "What crystallinity does annealed PLA reach?")
        statuses = [f["status"] for f in done["findings"]]
        self.assertEqual(statuses, ["accepted", "unreviewed"])
        self.assertEqual(done["findings"][1]["reviewFlag"], "Read from a figure")
        self.assertEqual(done["deposit"]["reviewStatus"], "pending")
        found = knowledge.search(self.root, "PLA crystallinity", compact=True)
        self.assertEqual([f["id"] for f in found["added"]], [done["findings"][0]["id"]])
        review = ScriptedEngine({"verdicts": [{"id": done["findings"][1]["id"], "verdict": "supported", "reason": "Fig. 4"}], "notes": ""})
        reviewer.review(self.root, done["id"], engine="codex", runner=review)
        self.assertNotIn(done["findings"][0]["statement"], review.calls[0]["prompt"])  # Added findings are not re-reviewed.
        self.assertEqual([f["status"] for f in knowledge.for_question(self.root, done["id"])], ["accepted", "supported"])
        # A researcher that sends everything confidently still gets reviewed in the "all" mode.
        loop.update_settings(self.root, {"reviewMode": "all"})
        fresh = dict(confident, statement="PLA quenched from the melt was amorphous by DSC.", value="0", locator="Table 3")
        strict = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [fresh]))), "Another PLA crystallinity question")
        self.assertEqual([f["status"] for f in strict["findings"]], ["unreviewed"])
        with self.assertRaises(ValueError):
            loop.update_settings(self.root, {"reviewMode": "never"})

    def test_the_researchers_own_call_decides_without_an_excerpt_rule(self):
        # The campaign's automatic excerpt flag sent 226 findings to review and none was rejected: removed 2026-10-12.
        confident = dict(FINDING, derivation="read", excerpt="crystallinity increased with annealing time")
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident]))),
                        "What crystallinity does annealed PLA reach?")
        self.assertEqual([f["status"] for f in done["findings"]], ["accepted"])

    def test_open_questions_join_the_research_queue_only_when_background_research_is_on(self):
        quiet = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", []))), "How does annealing change PLA films?")
        self.assertEqual(quiet["queuedResearch"], [])
        self.assertEqual(loop.research_queue(self.root), [])
        loop.update_settings(self.root, {"researchPerWeek": 5})
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", []))), "How does annealing change PLA?")
        self.assertEqual(done["queuedResearch"], ["How does annealing time change crystallinity?"])
        [item] = loop.research_queue(self.root)
        self.assertEqual((item["fromQuestion"], item["status"]), (done["id"], "waiting"))
        outcome = loop.research_stage(self.root, runner=ScriptedEngine(answer("y", [])))
        self.assertEqual(outcome["outcome"], "completed")
        self.assertEqual(len(loop.research_queue(self.root)), 1)  # Research answers never queue more research.

    def test_depth_sets_the_time_limit_and_the_web_budget(self):
        engine = ScriptedEngine(answer("x", []))
        done = self.ask_with(Questions(self.root, runner=engine), {"depth": "quick"})
        self.assertEqual((done["depth"], done["budgetSeconds"]), ("quick", 300))
        self.assertIn("about 6 web searches and 4 sources", engine.calls[0]["prompt"])
        self.assertIn("up to two reads beyond", engine.calls[0]["prompt"])
        legacy = self.ask_with(Questions(self.root, runner=ScriptedEngine(answer("x", []))), {"budgetSeconds": 1200})
        self.assertEqual(legacy["depth"], "thorough")
        service = Questions(self.root, runner=ScriptedEngine())
        for extra in ({"depth": "deep"}, {"depth": "quick", "budgetSeconds": 600}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                service.submit(dict({"question": "A long enough question", "authorizeSubscription": True}, **extra))

    def ask_with(self, service, extra):
        view = service.submit(dict({"question": "A question about PLA depth " + str(extra), "authorizeSubscription": True,
                                    "runtime": "codex"}, **extra))
        service.wait(10)
        return service.get(view["id"])

    def test_the_researcher_has_only_the_knowledge_tools(self):
        def researcher(tools):
            self.assertEqual([t["name"] for t in tools.tools()["tools"]], ["search_knowledge"])
            for name in ("search", "get_record", "traverse"):
                with self.subTest(tool=name), self.assertRaises(ValueError):
                    tools.call(name, {"q": "Polylactide"})
            with self.assertRaises(ValueError):
                tools.call("search_knowledge", {"q": "x", "extra": 1})
            return answer("x", [])
        done = self.ask(Questions(self.root, runner=ScriptedEngine(researcher)), "Which polylactide findings exist?")
        events = TraceStore(self.root).run(done["runId"]).events()["events"]
        self.assertEqual([(e["operation"], e["status"]) for e in events if e["kind"] == "access" or e["status"] == "error"],
                         [("knowledge.search_knowledge", "error")])

    def test_repeated_facts_are_not_saved_twice(self):
        confident = dict(FINDING, needsReview=False, reviewFlag="")
        first = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident, dict(confident)]))),
                         "What crystallinity does annealed PLA reach?")
        self.assertEqual((first["deposit"]["findings"], first["deposit"]["duplicates"]), (1, 1))  # Within one answer.
        reworded = dict(confident, statement="Annealed PLA film (100 °C, 1 h) reached 45 % crystallinity by DSC.",
                        sourceUrl="https://www.example.org/pla-annealing/", sourceDoi="10.1234/EXAMPLE.1")
        other_value = dict(confident, statement="PLA film annealed at 120 °C for 1 h reached 52% crystallinity.", value="52")
        second = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [reworded, other_value]))),
                          "Does annealing raise PLA crystallinity?")
        self.assertEqual((second["deposit"]["findings"], second["deposit"]["duplicates"]), (1, 1))
        self.assertEqual(second["deposit"]["duplicateOf"], [first["findings"][0]["id"]])
        self.assertEqual([f["value"] for f in second["findings"]], ["52"])
        # Rows of one table read alike but are different facts.
        row30 = dict(confident, statement="Neat PLA 3100HP (30 s cycle) showed DSC Tg 58.6 °C and Tm 176.4 °C on first heating.",
                     value="58.6; 176.4", locator="Table 3, 30 s row")
        row60 = dict(row30, statement="Neat PLA 3100HP (60 s cycle) showed DSC Tg 58.5 °C and Tm 176.9 °C on first heating.",
                     value="58.5; 176.9", locator="Table 3, 60 s row")
        rows = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [row30, row60]))), "PLA Tg and Tm by cycle time?")
        self.assertEqual((rows["deposit"]["findings"], rows["deposit"]["duplicates"]), (2, 0))
        # A fact judged unsupported before is saved again only for review.
        reviewer.review(self.root, first["id"], engine="codex", runner=ScriptedEngine(
            {"verdicts": [], "notes": ""}))  # Nothing awaits review for the first question: no call is made.
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE findings SET status='unsupported' WHERE id=?", (first["findings"][0]["id"],))
        third = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident]))),
                         "What crystallinity does annealed PLA reach after 1 h?")
        self.assertEqual([(f["status"], f["reviewFlag"]) for f in third["findings"]],
                         [("unreviewed", "A matching finding was judged unsupported before")])

    def test_flagged_and_sampled_findings_are_reviewed_together_after_the_answer(self):
        loop.update_settings(self.root, {"spotCheckRate": 1})
        confident = dict(FINDING, needsReview=False, reviewFlag="")
        skipped = dict(confident, statement="PLA film annealed at 120 °C for 1 h reached 52% crystallinity.", value="52",
                       excerpt="crystallinity of 52% after 1 h at 120 °C")
        unsure = dict(FINDING, statement="PLA reached about 50% crystallinity after 2 h, read from Figure 4.",
                      value="50", locator="Figure 4", needsReview=True, reviewFlag="Value read from a figure")
        seen = {}

        def review(tools):
            item = json.loads((self.root / ".oopc/loop/questions" / seen["id"] / "question.json").read_text())
            seen["statusDuringReview"] = item["status"]
            return {"verdicts": [{"id": "finding:%s-1" % seen["id"][:12], "verdict": "unsupported",
                                  "reason": "Table 2 reports 41%, not 45%."},
                                 {"id": "finding:%s-3" % seen["id"][:12], "verdict": "supported", "reason": "Fig. 4."}],
                    "notes": ""}
        engine = ScriptedEngine(answer("x", [], [confident, skipped, unsure]), review)
        service = Questions(self.root, runner=engine, review_engine="claude-code")
        view = service.submit({"question": "What crystallinity does annealed PLA reach?", "depth": "quick",
                               "authorizeSubscription": True, "runtime": "codex"})
        seen["id"] = view["id"]
        service.wait(10, reviews=True)
        self.assertEqual(seen["statusDuringReview"], "completed")  # The answer was delivered first.
        self.assertEqual(len(engine.calls), 2)  # One review call for the flagged and the sampled findings.
        for statement in (confident["statement"], skipped["statement"], unsure["statement"]):
            self.assertIn(statement, engine.calls[1]["prompt"])
        findings = service.get(view["id"])["findings"]
        # A sampled finding the reviewer skipped stays added on the researcher's judgement.
        self.assertEqual([f["status"] for f in findings], ["unsupported", "accepted", "supported"])
        self.assertEqual(findings[0]["review"]["engine"], "claude-code")
        self.assertEqual(knowledge.spot_check_stats(self.root),
                         {"checked": 1, "supported": 0, "unsupported": 1, "uncertain": 0, "pending": 0, "failed": 0,
                          "unsupportedRate": 1.0})
        self.assertEqual(knowledge.review_queue(self.root), [])

    def test_a_research_answer_finishes_its_review_before_the_tick_ends(self):
        loop.update_settings(self.root, {"spotCheckRate": 1, "researchPerWeek": 1})
        loop.add_research(self.root, "What crystallinity does annealed PLA reach after an hour?")
        confident = dict(FINDING, needsReview=False, reviewFlag="")
        def review(tools):
            time.sleep(0.5)  # A real review takes minutes; the tick must not end before it.
            asked = loop.research_queue(self.root)[0]["questionId"]
            return {"verdicts": [{"id": "finding:%s-1" % asked[:12], "verdict": "supported", "reason": "Table 2."}], "notes": ""}
        engine = ScriptedEngine(answer("x", [], [confident]), review)
        self.assertEqual(loop.research_stage(self.root, runner=engine, engine="claude-code")["outcome"], "completed")
        self.assertEqual(len(engine.calls), 2)
        self.assertEqual(knowledge.review_queue(self.root), [])

    def test_missed_reviews_run_in_the_loop_and_the_rate_is_a_setting(self):
        loop.update_settings(self.root, {"spotCheckRate": 1})
        confident = dict(FINDING, needsReview=False, reviewFlag="")
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident])), reviews=False),
                        "What crystallinity does annealed PLA reach?")
        self.assertEqual((done["deposit"]["waitingReview"], knowledge.review_queue(self.root)), (1, [done["id"]]))
        tick = loop.tick(self.root, engine="codex", runner=ScriptedEngine(
            {"verdicts": [{"id": done["findings"][0]["id"], "verdict": "supported", "reason": "Table 2"}], "notes": ""}))
        self.assertEqual([(r["questionId"], r["status"]) for r in tick["reviews"]], [(done["id"], "reviewed")])
        self.assertEqual(knowledge.for_question(self.root, done["id"])[0]["status"], "supported")
        self.assertEqual(knowledge.spot_check_stats(self.root)["unsupportedRate"], 0.0)
        for bad in (1.5, -0.1, "0.2"):
            with self.subTest(rate=bad), self.assertRaises(ValueError):
                loop.update_settings(self.root, {"spotCheckRate": bad})
        self.assertTrue(knowledge.sampled("finding:x-1", 1) and not knowledge.sampled("finding:x-1", 0))

    def test_settings_saved_before_the_simplification_still_read(self):
        atomic_json(self.root / ".oopc/loop/settings.json", {"autoQueue": True, "backgroundResearch": False,
                                                             "researchPerWeek": 10, "weeklyParity": True, "spotCheckRate": 0.3})
        self.assertEqual(loop.settings(self.root), {"reviewMode": "researcher", "spotCheckRate": 0.3, "researchPerWeek": 0})
        with self.assertRaises(ValueError):
            loop.update_settings(self.root, {"autoQueue": True})

    def test_searches_find_findings_under_another_name_of_the_polymer(self):
        confident = dict(FINDING, statement="Annealed polylactide film reached 45% crystallinity by DSC.",
                         needsReview=False, reviewFlag="")
        self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident]))), "Crystallinity of annealed films?")
        self.assertEqual(knowledge.expand(self.root, "PLA crystallinity"), ["Polylactide"])
        self.assertEqual(len(knowledge.search(self.root, "PLA")["added"]), 1)
        self.assertEqual(knowledge.expand(self.root, "nylon"), [])
        # A finding's polymer id comes from its material, by any name the graph knows.
        unnamed = dict(confident, subject="", statement="Polylactide film reached 30% crystallinity.", value="30",
                       material="PLA film")
        done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [unnamed]))), "Another crystallinity question?")
        self.assertEqual(done["findings"][0]["subject"], "wop-000001")

    def test_submission_validation(self):
        service = Questions(self.root, runner=ScriptedEngine())
        for request in ({}, {"question": "short", "authorizeSubscription": True},
                        {"question": "A long enough question", "authorizeSubscription": False},
                        {"question": "A long enough question", "authorizeSubscription": True, "budgetSeconds": 42},
                        {"question": "A long enough question", "authorizeSubscription": True, "runtime": "other"},
                        {"question": "A long enough question", "authorizeSubscription": True, "mode": "task"}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                service.submit(request)


if __name__ == "__main__":
    unittest.main()
