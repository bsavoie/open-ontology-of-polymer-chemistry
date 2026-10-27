"""The parity run with a scripted engine: frozen direct answers, no saved findings, canaries on demand."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oopc import engines, improve, knowledge, parity, reviewer
from oopc.ask import ANSWER_SCHEMA, prompt_version
from oopc.release import build_release
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology


def finding(n, **extra):
    value = {"statement": "Polymer %d reached %d%% crystallinity by DSC." % (n, 40 + n), "material": "polymer %d" % n,
             "property": "crystallinity", "value": str(40 + n), "unit": "%", "conditions": "second heating",
             "subject": "", "sourceTitle": "Paper %d" % n, "sourceUrl": "https://example.org/p%d" % n,
             "sourceDoi": "", "locator": "Table %d" % n, "excerpt": "%d%%" % (40 + n), "needsReview": False, "reviewFlag": ""}
    value.update(extra)
    return value


class Engine:
    """Answers by schema, like a real engine would, and counts calls by kind."""

    def __init__(self, *, ontology_passes=True, catch=True):
        self.calls = {"direct": 0, "ontology": 0, "deposit": 0, "check": 0, "review": 0}
        self.ontology_passes, self.catch = ontology_passes, catch
        self.turns = []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None,
                 persist=False, resume=None, previous_usage=None, folder=None):
        usage = {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 100}
        if schema is ANSWER_SCHEMA:
            self.turns.append({"persist": persist, "resume": resume, "folder": str(folder), "tools": tools is not None,
                               "web": web})
        if resume:  # The researcher's second turn: the findings it read, from the cached prefix.
            self.calls["deposit"] += 1
            answer = {"answer": "", "citations": [], "findings": [finding(8)], "sources": [], "limitations": [],
                      "openQuestions": []}
            return {"engine": engine, "model": "scripted", "sessionId": resume, "answer": answer,
                    "usage": {"input_tokens": 1000, "cached_input_tokens": 950, "output_tokens": 50},
                    "observedTools": [], "agentSeconds": 0.5}
        if schema is parity.DIRECT_SCHEMA:
            self.calls["direct"] += 1
            answer = {"answer": "A plain answer with a cited claim [s](https://example.org/x) about the polymer here.",
                      "citations": ["https://example.org/x"], "limitations": []}
            usage = dict(usage, input_tokens=2000)
        elif schema is ANSWER_SCHEMA:
            self.calls["ontology"] += 1
            if tools is not None:
                tools.call("search_knowledge", {"q": "crystallinity"})
            answer = {"answer": "It reached 49% `https://example.org/p9` according to the cited polymer source here.",
                      "citations": ["https://example.org/p9"], "findings": [], "sources": [], "limitations": [],
                      "openQuestions": []}
        elif schema is reviewer.CHECK_SCHEMA:
            self.calls["check"] += 1
            self.check_prompts = getattr(self, "check_prompts", []) + [prompt]
            wrong = "It reached" in prompt and not self.ontology_passes
            answer = {"verdict": "fail" if wrong else "pass", "resultGiven": True, "notes": "", "statements": [
                {"statement": "x", "verdict": "unsupported" if wrong else "supported", "reason": "ok", "kind": "source-fact",
                 "category": "contradiction" if wrong else "none", "evidence": "live"},
                {"statement": "complete", "verdict": "supported", "reason": "ok", "kind": "completeness",
                 "category": "none", "evidence": "none"}]}
        else:
            self.calls["review"] += 1
            ids = json.loads(prompt[prompt.index("{"):])["findings"]
            answer = {"verdicts": [{"id": f["id"], "verdict": ("unsupported" if self.catch else "supported")
                                    if f["id"].startswith("canary") else "supported", "reason": "r"} for f in ids],
                      "notes": ""}
        return {"engine": engine, "model": "scripted", "sessionId": "s%d" % len(self.turns) if persist else "s",
                "answer": answer, "usage": usage, "observedTools": [], "agentSeconds": 1.0}


class ParityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-parity-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        (self.root / "tmp").mkdir()  # The researcher's session folders.
        patch = mock.patch.object(tempfile, "tempdir", str(self.root / "tmp"))
        patch.start()
        self.addCleanup(patch.stop)
        path = build_release(self.root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                             "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
        release_id = json.loads((path / "manifest.json").read_text())["release_id"]
        path.rename(self.root / "releases" / release_id)
        atomic_json(self.root / "releases/current.json", {"release_id": release_id})
        with knowledge.connect(self.root) as db:
            for n in (1, 2, 3):
                knowledge._insert_finding(db, "finding:known-%d" % n, "q", "ask", knowledge.clean_finding(finding(n)),
                                          status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-09-29T00:00:0%d" % n)

    def test_a_run_freezes_direct_answers_and_never_saves_findings(self):
        engine = Engine()
        first = parity.run(self.root, engine="codex", checker="claude-code", runner=engine, canaries=True)
        questions = len(parity.load_set()["questions"])
        self.assertEqual(engine.calls, {"direct": questions, "ontology": questions, "deposit": questions,
                                        "check": 2 * questions, "review": 1})
        self.assertEqual(first["meta"]["prompt"], prompt_version())  # Which instructions the run measured.
        self.assertEqual(first["canaries"]["caught"], 3)
        self.assertEqual(first["summary"]["all"]["checked"], questions)
        self.assertEqual(first["summary"]["all"]["passes"], {"direct": questions, "ontology": questions})
        # The researcher's tokens are both turns' own: 300 new for the answer and 100 for its findings.
        self.assertEqual(first["summary"]["all"]["medianTokenRatio"], 0.308)
        self.assertEqual(first["summary"]["all"]["medianTokens"]["ontology"], 400)
        self.assertEqual(first["summary"]["all"]["medianTotalTokens"]["ontology"], 2150)
        self.assertEqual(first["summary"]["all"]["medianSeconds"], {"direct": 1.0, "ontology": 1.0})
        self.assertEqual(first["summary"]["all"]["medianTotalSeconds"], {"direct": 1.0, "ontology": 1.5})
        self.assertEqual((first["summary"]["covered"]["questions"], first["summary"]["uncovered"]["questions"]), (4, 4))
        self.assertTrue(first["guardrail"]["holds"])
        self.assertEqual(knowledge.summary(self.root)["findings"], {"supported": 3})  # Nothing saved by the run.
        again = Engine(ontology_passes=False)
        second = parity.run(self.root, engine="codex", checker="claude-code", runner=again)
        self.assertEqual((again.calls["direct"], again.calls["review"]), (0, 0))  # Direct answers frozen; no canaries.
        self.assertEqual(again.calls["check"], 2 * questions)  # The frozen plain answers are checked again beside.
        self.assertEqual((second["guardrail"]["extraContradicted"], second["guardrail"]["passDeficit"]),
                         (questions, questions))
        self.assertEqual(second["summary"]["all"]["contradicted"], {"direct": 0, "ontology": questions})
        self.assertEqual(second["summary"]["all"]["complete"], {"direct": questions, "ontology": questions})
        self.assertFalse(second["guardrail"]["holds"])
        self.assertEqual(parity.runs(self.root)[0], second["run"])
        # Two runs side by side, like for like: the second contradicts its sources, so it is not recommended.
        compared = improve.compare(first, second)
        self.assertEqual((compared["contradicted"], compared["passes"], compared["compared"], compared["recommended"]),
                         ((0, questions), (questions, 0), questions, False))
        self.assertTrue(improve.compare(second, first)["recommended"])

    def test_the_researcher_arm_answers_then_writes_its_findings_by_resuming_its_session(self):
        engine = Engine()
        baseline = parity.run(self.root, engine="codex", checker="claude-code", runner=engine, only="covered")
        arm = json.loads((parity.folder(self.root) / "runs" / parity.runs(self.root)[0] / "c1-ontology.json").read_text())
        first, second = engine.turns[:2]
        self.assertEqual((first["persist"], first["resume"], second["resume"], second["folder"]),
                         (True, None, "s1", first["folder"]))
        self.assertEqual((second["tools"], second["web"]), (first["tools"], first["web"]))
        metrics = arm["metrics"]
        self.assertEqual((metrics["seconds"], metrics["depositSeconds"], metrics["totalSeconds"], metrics["newTokens"]),
                         (1.0, 0.5, 1.5, 400))
        self.assertEqual(len(arm["answer"]["findings"]), 1)  # Kept with the answer, never saved.
        self.assertEqual(knowledge.summary(self.root)["findings"], {"supported": 3})
        self.assertEqual(list((self.root / "tmp").iterdir()), [])  # Each session's folder is deleted after its turns.

        # A second turn that fails is recorded beside the answer, which is still checked.
        class NoFindings(Engine):
            def __call__(self, engine, prompt, schema, **options):
                if options.get("resume"):
                    raise engines.EngineError("timeout", "slow", seconds=7.0, usage={
                        "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5})
                return super().__call__(engine, prompt, schema, **options)
        row = parity.run(self.root, engine="codex", checker="claude-code", runner=NoFindings(),
                         only="covered")["rows"][0]["arms"]["ontology"]
        self.assertEqual((row["depositError"]["reason"], row["verdict"]), ("timeout", "pass"))
        self.assertEqual((row["metrics"]["totalSeconds"], row["metrics"]["newTokens"], row["metrics"]["depositFailed"]),
                         (8.0, 315, True))
        self.assertEqual(list((self.root / "tmp").iterdir()), [])

        # One that reported no usage keeps the answer's tokens, with the deposit's unmeasured: not compared on tokens.
        class Unmeasured(Engine):
            def __call__(self, engine, prompt, schema, **options):
                if options.get("resume"):
                    raise engines.EngineError("crashed", "exit 1")
                return super().__call__(engine, prompt, schema, **options)
        value = parity.run(self.root, engine="codex", checker="claude-code", runner=Unmeasured(), only="covered")
        metrics = value["rows"][0]["arms"]["ontology"]["metrics"]
        self.assertEqual((metrics["newTokens"], metrics["answerNewTokens"], metrics["depositNewTokens"],
                          metrics["depositFailed"]), (300, 300, None, True))
        self.assertIsNone(value["rows"][0]["tokenRatio"])
        compared = improve.compare(baseline, value)
        self.assertEqual((compared["failedDeposits"], compared["tokensCompared"], compared["recommended"]),
                         ((0, 4), 0, False))
        self.assertIn("failed deposit", compared["notice"])

    def test_direct_answers_are_frozen_per_engine_and_model(self):
        # 2026-10-11: Codex moved from gpt-6-astra to gpt-6.1-sol; the plain baseline moves with it.
        questions = len(parity.load_set()["questions"])
        first = parity.run(self.root, engine="codex", checker="claude-code", runner=Engine())
        model = engines.ENGINES["codex"]["model"]
        self.assertEqual(first["meta"]["model"], model)
        self.assertTrue((parity.direct_folder(self.root, "codex", model) / "c1.json").exists())
        with mock.patch.dict(engines.ENGINES, {"codex": dict(engines.ENGINES["codex"], model="next-model")}):
            newer = Engine()
            parity.run(self.root, engine="codex", checker="claude-code", runner=newer)
        self.assertEqual(newer.calls["direct"], questions)

    def test_canaries(self):
        items = parity.make_canaries(self.root)
        self.assertEqual([i["id"] for i in items], ["canary:value", "canary:condition", "canary:source", "control:true"])
        # The value is changed where the statement gives it, not the number in the polymer's name; the wrong source
        # is another paper's.
        base = knowledge.get(self.root, "finding:known-3")
        self.assertEqual((items[0]["statement"], items[0]["value"]), ("Polymer 3 reached 72% crystallinity by DSC.", "72"))
        self.assertEqual(items[2]["statement"], base["statement"])
        self.assertNotEqual(items[2]["source"]["url"], base["source"]["url"])
        caught = parity.run_canaries(self.root, "codex", runner=Engine())
        self.assertEqual((caught["caught"], caught["accepted"], caught["canaries"], caught["controlSupported"]), (3, 0, 3, True))
        missed = parity.run_canaries(self.root, "codex", runner=Engine(catch=False))
        self.assertEqual((missed["caught"], missed["accepted"]), (0, 3))

    def test_canaries_for_a_mistyped_title_and_a_method_given_only_in_the_methods(self):
        # 2026-10 campaign: a title typo ("vinimidazole") reached an answer, and a reviewer that read only Table 9
        # rejected a method stated in the paper's Test Methods.
        with knowledge.connect(self.root) as db:
            knowledge._insert_finding(db, "finding:known-4", "q", "ask", knowledge.clean_finding(finding(
                4, sourceTitle="Poly(1-vinylimidazole) brushes on silica", conditions="DSC, 10 °C/min, second heating")),
                status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-09-28T00:00:00")
        items = {i["id"]: i for i in parity.make_canaries(self.root)}
        self.assertEqual(items["canary:title"]["source"]["title"], "Poly(1-vinlimidazole) brushes on silica")
        self.assertEqual((items["canary:title"]["expected"], items["control:methods"]["expected"]),
                         ("unsupported", "supported"))
        self.assertEqual(items["control:methods"]["locator"], "Table 4")
        caught = parity.run_canaries(self.root, "codex", runner=Engine())
        self.assertEqual((caught["caught"], caught["canaries"], caught["controlSupported"]), (4, 4, True))

    def test_a_recheck_checks_both_arms_of_a_question_again(self):
        class FailOnce(Engine):
            def __call__(self, engine, prompt, schema, **options):
                if schema is reviewer.CHECK_SCHEMA and "It reached" in prompt and not getattr(self, "failed", False):
                    self.failed = True
                    raise engines.EngineError("quota", "limit")
                return super().__call__(engine, prompt, schema, **options)
        first = parity.run(self.root, engine="codex", checker="claude-code", runner=FailOnce(), only="covered")
        self.assertEqual(first["summary"]["all"]["checked"], 3)
        engine = Engine()
        filled = parity.recheck(self.root, checker="claude-code", runner=engine)
        self.assertEqual(engine.calls["check"], 2)  # The failed arm and the plain arm beside it, not the others.
        self.assertEqual(filled["summary"]["all"]["checked"], 4)

    def test_the_checker_sees_the_sessions_web_actions(self):
        class Reading(Engine):
            def __call__(self, engine, prompt, schema, **options):
                value = super().__call__(engine, prompt, schema, **options)
                if schema is ANSWER_SCHEMA and not options.get("resume"):
                    value["observedTools"] = [
                        {"type": "web_search", "action": "open", "url": "https://publisher.example/p", "outcome": "refused"},
                        {"type": "mcp_tool_call", "tool": "search_knowledge"}]
                return value
        engine = Reading()
        parity.run(self.root, engine="codex", checker="claude-code", runner=engine, only="covered")
        given = [json.loads(p[p.index("{"):]) for p in engine.check_prompts if "It reached" in p]
        self.assertEqual(given[0]["session"]["webActions"],
                         [{"action": "open", "url": "https://publisher.example/p", "outcome": "refused"}])

    def test_failed_arms_are_reported_not_raised(self):
        class Failing(Engine):
            def __call__(self, engine, prompt, schema, **options):
                if schema is ANSWER_SCHEMA:
                    raise engines.EngineError("timeout", "slow")
                return super().__call__(engine, prompt, schema, **options)
        value = parity.run(self.root, engine="codex", runner=Failing(), only="covered")
        self.assertEqual(value["summary"]["covered"]["failures"]["ontology"], 4)
        self.assertEqual(value["summary"]["all"]["checked"], 0)

    def test_failed_checks_are_filled_in_later_without_answering_again(self):
        class QuotaChecker(Engine):
            def __call__(self, engine, prompt, schema, **options):
                if schema is not parity.DIRECT_SCHEMA and schema is not ANSWER_SCHEMA:
                    raise engines.EngineError("quota", "limit")
                return super().__call__(engine, prompt, schema, **options)
        first = parity.run(self.root, engine="codex", checker="claude-code", runner=QuotaChecker(), canaries=True)
        self.assertEqual(first["summary"]["all"]["checked"], 0)
        self.assertIsNone(first["guardrail"]["holds"])  # Too few checked pairs to judge.
        self.assertIn("error", first["canaries"])
        engine = Engine()
        filled = parity.recheck(self.root, checker="claude-code", runner=engine)
        questions = len(parity.load_set()["questions"])
        self.assertEqual(engine.calls, {"direct": 0, "ontology": 0, "deposit": 0, "check": 2 * questions, "review": 1})
        self.assertEqual(filled["summary"]["all"]["checked"], questions)
        self.assertTrue(filled["guardrail"]["holds"])
        self.assertEqual(filled["canaries"]["caught"], 3)
        # The plain answers stay frozen; every run checks them again beside the researcher's.
        again = Engine()
        parity.run(self.root, engine="codex", checker="claude-code", runner=again)
        self.assertEqual((again.calls["direct"], again.calls["check"]), (0, 2 * questions))

    def test_a_checker_gets_what_a_cited_finding_says_and_where_its_source_was_read(self):
        # 200-task Q25 failed on a paywalled DOI the researcher had read in an open copy.
        knowledge.deposit(self.root, "n" * 32, {"findings": [], "sources": [
            {"title": "Paper 1", "url": "https://doi.org/10.1/one", "doi": "10.1/one", "locator": "", "excerpts": ["41%"],
             "supports": "crystallinity", "conditions": "", "readUrl": "https://open.example.org/one.pdf"}]}, engine="codex")
        with knowledge.connect(self.root) as db:
            knowledge._insert_finding(db, "finding:doi-1", "q", "ask", knowledge.clean_finding(
                finding(4, sourceUrl="", sourceDoi="10.1/one")), status=knowledge.ACCEPTED, producer_engine="codex",
                created_at="2026-09-29T00:00:04")
        by_url, by_finding = parity.resolve_sources(self.root, ["https://doi.org/10.1/one", "finding:doi-1"])
        self.assertEqual(by_url, {"url": "https://doi.org/10.1/one", "readUrl": "https://open.example.org/one.pdf"})
        self.assertEqual(by_finding["readUrl"], "https://open.example.org/one.pdf")
        self.assertEqual((by_finding["statement"], by_finding["value"], by_finding["conditions"], by_finding["status"]),
                         ("Polymer 4 reached 44% crystallinity by DSC.", "44", "second heating", "accepted"))

    def test_the_checker_sees_what_the_researchers_knowledge_searches_returned(self):
        # Memory ablation 2026-10-13: "the saved knowledge did not contain a value" could not be checked without it.
        engine = Engine()
        parity.run(self.root, engine="codex", checker="claude-code", runner=engine, only="covered")
        given = [json.loads(p[p.index("{"):]) for p in engine.check_prompts]
        ontology = [g for g in given if "It reached" in g["answer"]]
        direct = [g for g in given if "It reached" not in g["answer"]]
        self.assertTrue(ontology and all(g["session"]["knowledgeSearches"][0]["query"] == "crystallinity" for g in ontology))
        self.assertTrue(direct and not any("session" in g for g in direct))  # A plain session searched no saved knowledge.

    def test_cited_fraction_counts_substantive_parts(self):
        text = ("A long paragraph about polymer crystallinity measured carefully by calorimetry [1](https://x.org).\n\n"
                "Another long paragraph without any citation about some polymer property values here.\n\n"
                "Short line.")
        self.assertEqual(parity.cited_fraction({"answer": text}), 0.5)
        self.assertIsNone(parity.cited_fraction({"answer": "Too short."}))
        # A lead-in and a table go with the caption that cites them; a note about the search is not a claim.
        table = ("I verified one open-access study reporting all four requested quantities in this session.\n\n"
                 "For neat polycarbonate the patent reports the following heat deflection values:\n\n"
                 "| Material | HDT |\n|---|---|\n| Linear PC | 139.4 °C |\n\n"
                 "Both are neat-material controls reported in Table 3 of the patent. `https://p.org/x`\n\n"
                 "These are grade-specific results and should not be read as a general polycarbonate value.")
        self.assertEqual(parity.cited_fraction({"answer": table}), 0.5)
        # Labelled reasoning and background are judged by the checker, not counted as uncited claims.
        labelled = table.replace("These are grade-specific", "**Interpretation:** these are grade-specific") + (
            "\n\nBackground: heat deflection temperature measures deflection under a fixed load while heating a bar.")
        self.assertEqual(parity.cited_fraction({"answer": labelled}), 1.0)


if __name__ == "__main__":
    unittest.main()
