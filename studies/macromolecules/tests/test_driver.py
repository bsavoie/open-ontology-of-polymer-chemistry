"""The shared study driver with a scripted engine behind its Guard, offline: arms in turn and checked together, resume,
sleep, retries, quota, and a report that leads with the measures independent of source access, with ledger tokens."""
import contextlib, io, json, re, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common and driver
import driver  # noqa: E402  (driver imports common, which puts CODE first on sys.path)
from oopc import ask, calls, engines, knowledge, parity  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

NAMES = ["P", "K", "M"]
NEW = {"P": 3000, "K": 1000, "M": 500, "check": 200}  # new input tokens per call; every call adds 10 output tokens


def statement(verdict, kind="source-fact", category="none"):
    return {"statement": "s", "verdict": verdict, "reason": "r", "kind": kind, "category": category, "evidence": "live"}


class Engine:
    """Answers by schema, like a real engine. Records each call as (kind, arm, engine): the plain arm, the researcher
    with web search (K) or without (M), or the check of an answer, whose text names its arm. `hook(self, kind, arm)`
    runs first and may raise an EngineError or change the world."""

    def __init__(self, hook=None):
        self.calls, self.hook, self.guard = [], hook, None

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        if schema is parity.DIRECT_SCHEMA:
            kind, arm = "answer", "P"
        elif schema is ask.ANSWER_SCHEMA:
            kind, arm = "answer", "K" if web else "M"
        else:
            kind, arm = "check", re.search(r"\[arm (\w)\]", prompt).group(1)
        self.calls.append((kind, arm, engine))
        if self.hook:
            self.hook(self, kind, arm)
        if kind == "check" and arm == "M":  # web search off: wrong, incomplete and a source that would not open
            answer = {"verdict": "fail", "resultGiven": False, "notes": "", "statements": [
                statement("unsupported", category="contradiction"), statement("uncertain", category="source-access"),
                statement("uncertain", "completeness", "completeness")]}
        elif kind == "check":
            answer = {"verdict": "pass", "resultGiven": True, "notes": "",
                      "statements": [statement("supported"), statement("supported", "completeness")]}
        elif arm == "P":
            answer = {"answer": "[arm P] Polymer 1 reached 41% crystallinity [s](https://example.org/p1).",
                      "citations": ["https://example.org/p1"], "limitations": []}
        else:
            found = tools.call("search_knowledge", {"q": "polymer crystallinity"})
            cited = [f["id"] for group in ("reviewed", "added") for f in found.get(group, [])][:1]
            answer = {"answer": "[arm %s] It reached 41%% `%s`." % (arm, cited[0] if cited else "none"),
                      "citations": cited, "findings": [], "sources": [], "limitations": [], "openQuestions": []}
        usage = {"input_tokens": NEW["check" if kind == "check" else arm], "cached_input_tokens": 0,
                 "output_tokens": 10}
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": answer, "usage": usage,
                "observedTools": [], "agentSeconds": 1.0}


def failing(when, reason, usage=None, times=99):
    """A hook that raises `reason` on calls matching `when(kind, arm, number)`, at most `times` times."""
    raised = []

    def hook(engine, kind, arm):
        if when(kind, arm, len(engine.calls)) and len(raised) < times:
            raised.append(reason)
            raise engines.EngineError(reason, "scripted " + reason, seconds=1.0, usage=usage)
    return hook


class DriverTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-driver-test-")
        self.addCleanup(folder.cleanup)
        self.source, self.base = Path(folder.name).resolve() / "source", Path(folder.name).resolve() / "run"
        path = build_release(self.source / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                             "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
        release_id = json.loads((path / "manifest.json").read_text())["release_id"]
        path.rename(self.source / "releases" / release_id)
        atomic_json(self.source / "releases/current.json", {"release_id": release_id})
        with knowledge.connect(self.source) as db:
            knowledge._insert_finding(db, "finding:known-1", "q", "ask", knowledge.clean_finding({
                "statement": "Polymer 1 reached 41% crystallinity by DSC.", "material": "polymer 1",
                "property": "crystallinity", "value": "41", "unit": "%", "conditions": "second heating", "subject": "",
                "sourceTitle": "Paper 1", "sourceUrl": "https://example.org/p1", "sourceDoi": "", "locator": "Table 1",
                "excerpt": "41%", "needsReview": False, "reviewFlag": ""}),
                status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-09-29T00:00:01")
        self.arms = [{"name": "P", "kind": "plain"}] + [
            {"name": name, "kind": "researcher", "web": name == "K",
             "root": driver.workspace(self.base, name, releases=self.source, store=self.source)} for name in ("K", "M")]
        self.questions = [{"id": "q%d" % n, "question": "What crystallinity did polymer %d reach?" % n}
                          for n in (1, 2, 3)]
        self.plan = driver.prepare(self.base, "test", self.questions, self.arms, engine="codex", checker="claude-code")
        quiet = contextlib.redirect_stdout(io.StringIO())  # the Guard and emit print every event
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def run_with(self, engine, quota=80, signed=lambda e: True):
        engine.guard = driver.Guard(time.time() + 3600, read_quota=lambda e: {"remainingPercent": quota},
                                    run_session=engine, signed=signed, base=self.base)
        return driver.run(self.base, runner=engine.guard)

    def item(self, question, arm):
        return read_json(self.base / "items" / ("%04d-%s.json" % (question, arm)))

    def test_arms_answer_in_turn_and_are_checked_together_by_one_checker(self):
        engine = Engine()
        self.assertEqual(self.run_with(engine)["status"], "completed")
        expected = []
        for index in range(3):  # question i starts at arm i mod n; its checks follow its answers, on one checker
            order = NAMES[index:] + NAMES[:index]
            expected += [("answer", a, "codex") for a in order] + [("check", a, "claude-code") for a in order]
        self.assertEqual(engine.calls, expected)
        for index in range(3):
            items = [self.item(index, a) for a in NAMES]
            self.assertLess(max(i["answer"]["at"] for i in items), min(i["check"]["at"] for i in items))
            self.assertTrue(all(isinstance(i[part]["localHour"], int) for i in items for part in ("answer", "check")))
        self.assertTrue(self.item(0, "K")["answer"]["runId"].startswith("run-"))  # traced, and nothing saved:
        self.assertEqual(driver.fingerprint(self.arms[1]["root"]), self.plan["stores"]["K"])
        again = Engine()
        self.run_with(again)  # a finished run asks nothing again
        self.assertEqual(again.calls, [])

    def test_a_stopped_run_resumes_without_repeating_what_is_done(self):
        def stop_after_second_answer_of_question_two(engine, kind, arm):
            if len(engine.calls) == 8:
                (self.base / "STOP").write_text("")
        first = Engine(stop_after_second_answer_of_question_two)
        state = self.run_with(first)
        self.assertEqual((state["status"], state["stopReason"], len(first.calls)), ("stopped", "owner-stop", 8))
        self.assertEqual([a["reason"] for a in self.item(1, "P")["attempts"]], ["interrupted"])  # refused at the stop
        (self.base / "STOP").unlink()
        second = Engine()
        self.assertEqual(self.run_with(second)["status"], "completed")
        self.assertEqual([c[:2] for c in second.calls], [  # the second question's last answer, then its checks
            ("answer", "P"), ("check", "K"), ("check", "M"), ("check", "P"),
            ("answer", "M"), ("answer", "P"), ("answer", "K"), ("check", "M"), ("check", "P"), ("check", "K")])
        self.assertEqual([a["outcome"] for a in self.item(1, "P")["attempts"] if a["part"] == "answer"],
                         ["failed", "completed"])

    def test_an_attempt_the_machine_slept_through_is_tried_once_more(self):
        clock, seen = [0.0], []

        def lid_closed_during_first_answer_then_a_timeout(engine, kind, arm):
            if len(engine.calls) == 1:
                clock[0] += 47 * 60  # wall-clock time ran ahead of monotonic time: the machine slept
                seen.append(engine.guard.boundary())  # what the Guard's watch loop sees on waking
            if len(engine.calls) <= 2:
                raise engines.EngineError("timeout", "Stopped at the 600-second limit", seconds=600.0)
        with mock.patch.object(driver, "drift", lambda: clock[0]):
            engine = Engine(lid_closed_during_first_answer_then_a_timeout)
            self.assertEqual(self.run_with(engine)["status"], "completed")
            self.assertIsNone(engine.guard.boundary())
        self.assertEqual(seen, ["slept"])
        attempts = self.item(0, "P")["attempts"]  # the sleep's retry comes on top of the timeout's
        self.assertEqual([(a["outcome"], a.get("reason"), a.get("slept")) for a in attempts if a["part"] == "answer"],
                         [("failed", "timeout", 2820), ("failed", "timeout", None), ("completed", None, None)])
        self.assertEqual(len(engine.calls), 18 + 2)
        self.assertEqual(driver.report(self.base)["arms"]["P"]["slept"], 1)

    def test_a_research_timeout_is_retried_once_and_a_second_is_the_items_failure(self):
        spent = {"input_tokens": 400, "cached_input_tokens": 0, "output_tokens": 0}  # a failed session still costs
        hooks = [failing(lambda kind, arm, n: n <= 7 and (kind, arm) == ("answer", "P"), "timeout", spent),
                 failing(lambda kind, arm, n: (kind, arm) == ("check", "K"), "crashed", times=1),
                 failing(lambda kind, arm, n: n <= 7 and (kind, arm) == ("check", "M"), "timeout")]
        engine = Engine(lambda *args: [hook(*args) for hook in hooks])
        self.assertEqual(self.run_with(engine)["status"], "completed")
        p, k, m = self.item(0, "P"), self.item(0, "K"), self.item(0, "M")
        self.assertEqual((p["answer"]["error"]["reason"], len(p["attempts"]), "check" in p), ("timeout", 2, False))
        self.assertEqual([a["outcome"] for a in k["attempts"] if a["part"] == "check"], ["failed", "completed"])
        self.assertEqual((m["check"]["error"]["reason"], len([a for a in m["attempts"] if a["part"] == "check"])),
                         ("timeout", 1))  # a check timeout is not tried again
        report = driver.report(self.base)
        self.assertEqual((report["compared"], report["arms"]["P"]["failed"], report["arms"]["M"]["failed"]),
                         (2, {"answer:timeout": 1}, {"check:timeout": 1}))
        self.assertEqual(report["arms"]["P"]["tokens"]["research"],  # from the ledger, failed attempts included
                         {"calls": 4, "total": 2 * 400 + 2 * 3010, "median": 3010, "missingUsage": 0})
        again = Engine()
        self.run_with(again)  # a rerun tries the failed items, and checks the first question's arms together again
        self.assertEqual([c[:2] for c in again.calls],
                         [("answer", "P"), ("check", "P"), ("check", "K"), ("check", "M")])
        self.assertEqual(len(self.item(0, "K")["previousChecks"]), 1)

    def test_quota_and_sign_out_stop_the_run_with_their_reason(self):
        engine = Engine(failing(lambda kind, arm, n: n == 2, "quota"))
        state = self.run_with(engine)
        self.assertEqual((state["status"], state["stopReason"], len(engine.calls)), ("stopped", "quota", 2))
        self.assertEqual(self.item(0, "K")["attempts"][0]["reason"], "quota")
        self.assertNotIn("answer", self.item(0, "K"))
        low = Engine()
        self.assertEqual(self.run_with(low, quota=5)["stopReason"], "quota")  # below the Codex floor: nothing starts
        out = Engine()
        self.assertEqual(self.run_with(out, signed=lambda e: e != engines.CLAUDE)["stopReason"], "not-signed-in")
        self.assertEqual(low.calls + out.calls, [])

    def test_the_report_leads_with_measures_independent_of_source_access_and_reads_tokens_from_the_ledger(self):
        self.run_with(Engine())
        report = json.loads((self.base / "report.json").read_text())
        self.assertEqual(report["columns"][:4], ["answered", "contradicted", "complete", "resultGiven"])
        measures = {name: [report["arms"][name][c] for c in report["columns"][:-1]] for name in NAMES}
        self.assertEqual(measures, {"P": [3, 0, 3, 3, 3, 0], "K": [3, 0, 3, 3, 3, 0], "M": [3, 3, 0, 0, 0, 3]})
        self.assertEqual(report["arms"]["K"]["tokens"], {
            "research": {"calls": 3, "total": 3030, "median": 1010, "missingUsage": 0},
            "check": {"calls": 3, "total": 630, "median": 210, "missingUsage": 0}})
        self.assertEqual({r["phase"] for r in calls.records(self.arms[2]["root"])},
                         {"study:test:M:research", "study:test:M:check"})
        header = (self.base / "report.md").read_text().splitlines()[5]
        self.assertTrue(header.startswith("| Arm | Answered | Contradicted | Complete | Sourced result | Passes |"))

    def test_the_plan_is_fixed_and_a_store_must_not_change(self):
        self.assertEqual(driver.prepare(self.base, "test", self.questions, self.arms, engine="codex",
                                        checker="claude-code")["createdAt"], self.plan["createdAt"])
        with self.assertRaises(ValueError):
            driver.prepare(self.base, "test", self.questions[:2], self.arms, engine="codex", checker="claude-code")
        with knowledge.connect(self.arms[1]["root"]) as db:  # an edit to a finding's value, its status unchanged
            db.execute("UPDATE findings SET value = value || '0'")
        with self.assertRaises(ValueError):
            driver.run(self.base, runner=Engine())


if __name__ == "__main__":
    unittest.main()
