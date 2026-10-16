"""Synthetic evidence cases; no host engines or private overnight text."""
import unittest
import test_core_loop as core
from oopc import knowledge, parity, reviewer


class EvidenceChecks(unittest.TestCase):
    setUp = core.CoreLoopTests.setUp

    def test_a_cited_finding_reaches_the_checker_with_its_source_and_status(self):
        knowledge.deposit(self.root, "a" * 32, core.answer("", [], [dict(core.FINDING, needsReview=False)]),
                          engine="codex", spot_check_rate=0)
        finding = knowledge.for_question(self.root, "a" * 32)[0]
        [source, url] = parity.resolve_sources(self.root, [finding["id"], "https://example.org/other"])
        self.assertEqual((source["url"], source["locator"], source["status"]), (core.FINDING["sourceUrl"], "Table 2", "accepted"))
        self.assertEqual(url, {"url": "https://example.org/other"})

    def test_legacy_verdict_is_preserved_with_unspecified_diagnostics(self):
        checked = reviewer.normalize_check({"verdict": "fail", "statements": [
            {"statement": "The title is incorrect", "verdict": "unsupported", "reason": "Different title"}]})
        self.assertEqual(checked["verdict"], "fail")
        self.assertEqual(checked["statements"][0]["category"], "unspecified")

    def test_answer_checks_classify_causes_without_admitting_findings(self):
        cases = [("Internal Added status", "provenance", "none", "supported"),
                 ("Conditional calculation", "inference", "inference", "uncertain"),
                 ("Promised equation absent", "completeness", "completeness", "unsupported"),
                 ("Incorrect title", "source-fact", "bibliography", "unsupported")]
        result = reviewer.check_answer("Give method and equation", "Synthetic answer", [], engine="codex",
            runner=core.ScriptedEngine({"verdict": "fail", "notes": "", "statements": [
                {"statement": text, "kind": kind, "category": category, "verdict": verdict, "reason": "Synthetic reason"}
                for text, kind, category, verdict in cases]}))
        self.assertEqual([s["category"] for s in result["statements"]], [c[2] for c in cases])
        self.assertIsNone(result["resultGiven"])  # an older-format answer has no judgement, never a guessed one
        given = reviewer.check_answer("Give the Tg", "Not found in open sources.", [], engine="codex",
            runner=core.ScriptedEngine({"verdict": "uncertain", "resultGiven": False, "notes": "", "statements": [
                {"statement": "Not found", "kind": "completeness", "category": "none", "verdict": "supported",
                 "reason": "Stated unavailable"}]}))
        self.assertIs(given["resultGiven"], False)
        self.assertIn("resultGiven", reviewer.CHECK_SCHEMA["required"])
        self.assertEqual(knowledge.summary(self.root)["findings"], {})
        prompt = reviewer.check_prompt("", "", [])
        for rule in ('labelled "Interpretation:"', 'labelled "Background:"', "a reported result with no citation at all",
                     "do not require it to repeat either source's error", "uncertain when a secondary detail is omitted",
                     'An honest "not\nfound" can be complete without giving the result'):
            self.assertIn(rule, prompt)
        self.assertIn("Judge only what the source itself says", reviewer.review_prompt([]))
        self.assertNotIn("kind", reviewer.REVIEW_SCHEMA["properties"]["verdicts"]["items"]["properties"])

    def test_a_source_note_keeps_the_url_actually_read_and_the_reviewer_gets_it(self):
        q = "b" * 32
        note = {"title": "Synthetic film", "url": core.FINDING["sourceUrl"], "doi": core.FINDING["sourceDoi"],
                "supports": "Annealing method", "readUrl": "https://example.org/open-copy.pdf"}
        knowledge.deposit(self.root, q, core.answer("", [], [core.FINDING], [note, dict(note, readUrl="file:///secret")]),
                          engine="codex", review_mode="all")
        self.assertEqual([knowledge.get(self.root, "note:%s-%d" % (q[:12], n)).get("readUrl") for n in (1, 2)],
                         ["https://example.org/open-copy.pdf", None])
        found = knowledge.for_question(self.root, q)[0]

        def run(engine, prompt, schema, **options):
            self.assertIn("https://example.org/open-copy.pdf", prompt)
            return {"engine": engine, "answer": {"verdicts": [
                {"id": found["id"], "verdict": "uncertain", "reason": "Access unavailable"}]}}
        reviewer.review(self.root, q, engine="claude-code", runner=run)
        self.assertEqual(knowledge.get(self.root, found["id"])["status"], "uncertain")

    def test_requested_methods_are_deposited_and_reused_without_web(self):
        method = dict(core.FINDING, statement="CO2 was measured by alkali trapping and titration.",
                      property="CO2 method", value="titration", needsReview=False)
        first = core.ScriptedEngine(core.answer("Method supplied", [], [method]))
        service = core.Questions(self.root, runner=first)
        core.CoreLoopTests.ask(self, service, "How was the polymer mineralization measured?")
        def repeat(tools):
            matches = tools.call("search_knowledge", {"q": "CO2 method"})["added"]
            return core.answer("Alkali trapping", [matches[0]["id"]])
        done = core.CoreLoopTests.ask(self, core.Questions(self.root, runner=core.ScriptedEngine(repeat)),
                                     "How was the polymer mineralization measured?")
        self.assertEqual(done["reusedFindings"]["added"], 1)

    def test_an_empty_or_inconsistent_model_pass_is_not_a_pass(self):
        for statements, expected in (([], "uncertain"), ([{"statement": "Method absent", "verdict": "unsupported"}], "fail")):
            result = reviewer.check_answer("Supply method", "", [], engine="codex", runner=core.ScriptedEngine(
                {"verdict": "pass", "statements": statements, "notes": ""}))
            self.assertEqual(result["verdict"], expected)
