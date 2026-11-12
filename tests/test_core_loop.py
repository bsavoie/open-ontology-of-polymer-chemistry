"""The core loop end to end with a scripted engine: ask, deposit, review, reuse."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

from oopc import calls, engines, knowledge, loop, reviewer, sources
from oopc.ask import (ANSWER_SCHEMA, CHAT_SITES, DEFAULT_SCOPE, DEPOSIT, FOLLOW_UP, QuestionUnavailable, Questions,
                      prompt_version, redirect_url, researcher_prompt, reuse_stats, workspace_scope)
from oopc.release import build_release
from oopc.trace import TraceStore
from oopc.util import atomic_json, locked
from oopc.vocabulary import get_ontology

FINDING = {"statement": "PLA film annealed at 100 °C for 1 h reached 45% crystallinity by DSC.",
           "material": "PLA film, 4032D", "property": "crystallinity", "value": "45", "unit": "%",
           "conditions": "annealed 100 °C, 1 h; DSC first heating", "subject": "wop-000001",
           "sourceTitle": "Annealing of PLA films", "sourceUrl": "https://example.org/pla-annealing",
           "sourceDoi": "10.1234/example.1", "locator": "Table 2", "excerpt": "crystallinity of 45% after 1 h at 100 °C"}


def answer(text, citations, findings=(), sources=()):
    return {"answer": text, "citations": list(citations), "findings": list(findings), "sources": list(sources),
            "limitations": [], "openQuestions": ["How does annealing time change crystallinity?"]}


def save_session(engine, folder):
    """What an engine saves for a session it can resume: a Codex rollout under $CODEX_HOME (a Claude Code transcript
    under $CLAUDE_CONFIG_DIR), with its id recorded in the session's working folder as `engines.run_session` does."""
    identifier = str(uuid.uuid4())
    home = engines.engine_home(engine)  # A person's own folder when the session runs as one (`engines.as_person`).
    if engine == "codex":
        path = home / "sessions/2026/10/25" / ("rollout-2026-10-25T00-00-00-%s.jsonl" % identifier)
    else:
        path = home / "projects/-scripted" / (identifier + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    engines._record_session(folder, engine, identifier)
    return identifier


class ScriptedEngine:
    """Returns scripted answers in order; calls tools the way a researcher would.

    Like a real engine, a research session saved for a second turn (`persist`) can be resumed: the second turn returns
    the findings and sources its scripted answer held (the first turn returns them empty), or the next of `deposits`
    (an answer, an exception, or a callable whose answer, if any, replaces the held one). Resuming a session that is no
    longer saved fails. Each call's own usage is 1000 input and 100 output tokens."""

    def __init__(self, *steps, deposits=()):
        self.steps, self.deposits, self.calls, self.held = list(steps), list(deposits), [], {}

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None,
                 persist=False, resume=None, previous_usage=None, folder=None):
        self.calls.append({"engine": engine, "schema": schema, "tools": tools is not None, "prompt": prompt, "web": web,
                           "persist": persist, "resume": resume, "folder": folder, "previousUsage": previous_usage,
                           "toolNames": [t["name"] for t in tools.tools()["tools"]] if tools is not None else []})
        if resume:
            if not engines.saved_session_exists(engine, resume):
                raise engines.EngineError("crashed", "No saved session " + resume)
            step = self.deposits.pop(0) if self.deposits else None
            if isinstance(step, Exception):
                raise step
            value = (step(tools) if callable(step) else step) or self.held[resume]
            value = dict(answer("", []), openQuestions=[], findings=value.get("findings", []),
                         sources=value.get("sources", []))
            return self.result(engine, resume, value)
        step = self.steps.pop(0)
        session = save_session(engine, folder) if persist else None
        if isinstance(step, Exception):
            step.session_id = session
            raise step
        value = step(tools) if callable(step) else step
        if persist and schema is ANSWER_SCHEMA:
            self.held[session] = value
            value = dict(value, findings=[], sources=[])
        return self.result(engine, session or "s%d" % len(self.calls), value)

    @staticmethod
    def result(engine, session, value):
        usage = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100}
        return {"engine": engine, "model": "scripted", "sessionId": session, "answer": value, "usage": usage,
                "sessionUsage": usage, "observedTools": [], "agentSeconds": 1.0}


def dead_pid():
    """The id of a process that has ended."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def saved_sessions(root):
    """Every session an engine still has saved, and every session working folder left."""
    return ([str(p) for p in Path(os.environ["CODEX_HOME"]).rglob("*.jsonl")]
            + [str(p) for p in Path(os.environ["CLAUDE_CONFIG_DIR"]).rglob("*.jsonl")]
            + [str(p) for p in (Path(root) / "tmp").glob("oopc-session-*")])


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
        # Spot checks and the consistency check send findings to review; tests that need them turn them on.
        loop.update_settings(self.root, {"spotCheckRate": 0, "consistencyDepth": 0})
        # Saved sessions and their working folders stay inside the test's folder.
        (self.root / "tmp").mkdir()
        for patch in (mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home"),
                                                   "CLAUDE_CONFIG_DIR": str(self.root / "claude-home"),
                                                   "OOPC_TEST_ENGINE_HOMES": "1"}),
                      mock.patch.object(tempfile, "tempdir", str(self.root / "tmp"))):
            patch.start()
            self.addCleanup(patch.stop)

    def ask(self, service, question):
        view = service.submit({"question": question, "budgetSeconds": 300, "authorizeSubscription": True,
                               "runtime": "codex"})
        service.wait(10, reviews=True)  # A background deposit or review must not outlive the test's folder.
        self.assertEqual(saved_sessions(self.root), [])  # Whatever happened, no saved session is left behind.
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
        # Its page also lists the sources it read and the facts it found already saved (none yet).
        self.assertEqual([(n["title"], n["supports"]) for n in done["notes"]], [("Annealing of PLA films", "crystallinity")])
        self.assertEqual(done["alreadyKnown"], [])

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
        service.wait(10, reviews=True)

    def test_manual_retry_and_interrupted_recovery(self):
        service = Questions(self.root, runner=ScriptedEngine(engines.EngineError("timeout", "limit"), answer("ok", [])))
        failed = self.ask(service, "A question that times out first")
        service.retry(failed["id"])
        service.wait(10, reviews=True)
        self.assertEqual(service.get(failed["id"])["status"], "completed")
        with self.assertRaises(ValueError):
            service.retry(failed["id"])
        # A question left running by a stopped app is interrupted and retried once; what its session saved is deleted.
        path = self.root / ".oopc/loop/questions" / failed["id"]
        stuck = Questions(self.root, runner=ScriptedEngine(answer("recovered", [])))
        item = json.loads((path / "question.json").read_text())
        work = engines.session_folder(failed["id"])
        save_session("codex", work)
        item.update(status="running", session={"engine": "codex", "folder": str(work)})  # Stopped before its id came back.
        atomic_json(path / "question.json", item)
        self.assertEqual(len(saved_sessions(self.root)), 2)
        stuck.recover()
        stuck.wait(10, reviews=True)
        view = stuck.get(failed["id"])
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["result"]["answer"], "recovered")
        self.assertEqual(saved_sessions(self.root), [])

    def test_failed_review_is_retried_once_then_left_failed(self):
        service = Questions(self.root, runner=ScriptedEngine(answer("x", [], [FINDING])))
        done = self.ask(service, "What crystallinity does annealed PLA reach?")
        for expected in ("failed", "failed"):
            result = loop.tick(self.root, runner=ScriptedEngine(engines.EngineError("invalid-output", "bad")),
                               engine="codex")
            self.assertEqual(result["reviews"][0]["status"], expected)
        self.assertEqual(loop.tick(self.root, runner=ScriptedEngine(), engine="codex")["reviews"], [])
        self.assertEqual(knowledge.deposit_summary(self.root, done["id"])["reviewStatus"], "failed")

    def test_the_answer_is_shown_first_and_its_findings_are_saved_by_resuming_its_session(self):
        # 2026-10-25: writing the findings was about two-thirds of the researcher's output; the answer no longer waits.
        note = {"title": "Annealing of PLA films", "url": "https://example.org/pla-annealing", "doi": "",
                "locator": "Table 2", "excerpts": ["45%"], "supports": "crystallinity", "conditions": "100 °C",
                "readUrl": ""}
        text = "Crystallinity reached 45% `https://example.org/pla-annealing`."
        seen = {}

        def during(tools):  # Turn 2 runs after the answer was delivered.
            [path] = (self.root / ".oopc/loop/questions").glob("*/question.json")
            view = service.get(path.parent.name)
            seen.update(status=view["status"], depositState=view["depositState"], answer=view["result"]["answer"],
                        deposit=view.get("deposit"))
        engine = ScriptedEngine(answer(text, ["https://example.org/pla-annealing"], [dict(FINDING, derivation="read")],
                                       [note]), deposits=[during])
        service = Questions(self.root, runner=engine)
        done = self.ask(service, "How does annealing change PLA crystallinity?")
        self.assertEqual(seen, {"status": "completed", "depositState": {"status": "saving"}, "answer": text,
                                "deposit": None})
        # Both turns of one saved session, with the same schema, tools and web settings (the engine's cached prefix).
        first, second = engine.calls
        [session] = engine.held
        self.assertEqual((first["persist"], first["resume"], second["persist"], second["resume"]),
                         (True, None, False, session))
        self.assertTrue(first["schema"] is second["schema"] is ANSWER_SCHEMA)
        self.assertEqual((first["toolNames"], first["web"]), (["search_knowledge"], True))
        self.assertEqual((second["toolNames"], second["web"], str(second["folder"])),
                         (first["toolNames"], first["web"], str(first["folder"])))
        self.assertEqual(second["previousUsage"], {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100})
        # The deposit rules moved to the second turn's instructions.
        self.assertIn("leave both empty", first["prompt"])
        self.assertNotIn("One value per finding", first["prompt"])
        self.assertEqual(second["prompt"], DEPOSIT)
        self.assertIn("One value per finding", DEPOSIT)
        # The deposit lands as it did when one turn wrote everything.
        self.assertEqual(done["depositState"], {"status": "saved"})
        self.assertEqual((done["deposit"]["findings"], done["deposit"]["notes"]), (1, 1))
        self.assertEqual([f["status"] for f in done["findings"]], ["accepted"])
        self.assertEqual(done["result"]["answer"], text)
        folder = self.root / ".oopc/loop/questions" / done["id"]
        stored = json.loads((folder / "result.json").read_text())
        self.assertEqual((len(stored["answer"]["findings"]), stored["depositTurn"]["usage"]["output_tokens"]), (1, 100))
        self.assertNotIn("session", json.loads((folder / "question.json").read_text()))
        # Each turn's own usage is in the ledger once.
        self.assertEqual([(r["phase"], r["newTokens"]) for r in calls.records(self.root)],
                         [("research", 1100), ("deposit", 1100)])
        self.assertEqual(TraceStore(self.root).run(done["runId"]).meta()["status"], "completed")

    def test_a_failed_second_turn_is_retried_once_then_the_answer_stands_without_its_findings(self):
        crash = engines.EngineError("crashed", "exit 1")
        engine = ScriptedEngine(answer("It reached 45%.", [], [FINDING]), deposits=[crash, crash])
        done = self.ask(Questions(self.root, runner=engine), "What crystallinity does annealed PLA reach?")
        self.assertEqual([c["resume"] is not None for c in engine.calls], [False, True, True])
        self.assertEqual((done["status"], done["result"]["answer"]), ("completed", "It reached 45%."))
        self.assertEqual(done["depositState"], {"status": "failed", "reason": "crashed", "message": "exit 1"})
        self.assertNotIn("deposit", done)
        self.assertEqual((done["findings"], knowledge.review_queue(self.root)), ([], []))
        # One transient failure is tried again; a timeout is not.
        again = ScriptedEngine(answer("x", [], [dict(FINDING, derivation="read")]), deposits=[crash])
        self.assertEqual(self.ask(Questions(self.root, runner=again), "Another PLA annealing question")["depositState"],
                         {"status": "saved"})
        slow = ScriptedEngine(answer("x", [], [FINDING]), deposits=[engines.EngineError("timeout", "limit")])
        stopped = self.ask(Questions(self.root, runner=slow), "A third PLA annealing question")
        self.assertEqual((stopped["status"], stopped["depositState"]["reason"], len(slow.calls)),
                         ("completed", "timeout", 2))

    def stopped_after_the_answer(self, engine, question):
        """A question whose process stopped as its answer was delivered: completed, its deposit saving, its session
        saved, its owner gone."""
        service = Questions(self.root, runner=engine)
        with mock.patch.object(Questions, "_deposit_in_background"):
            view = service.submit({"question": question, "depth": "quick", "authorizeSubscription": True,
                                   "runtime": "codex"})
            service.wait(10)
        item = service._read(view["id"])
        self.assertEqual((item["status"], item["depositState"]["status"], item["depositState"]["pid"]),
                         ("completed", "saving", os.getpid()))
        item["depositState"]["pid"] = dead_pid()
        service._write(item)
        return item

    def restart(self, engine):
        service = Questions(self.root, runner=engine, reviews=False)
        service.recover()
        service.wait(10, reviews=True)
        return service

    def test_a_deposit_left_saving_by_a_stopped_app_is_settled_at_the_next_start(self):
        engine = ScriptedEngine(*[answer("x", [], [dict(FINDING, derivation="read", value=str(n),
                                                        statement="PLA reached %d%% crystallinity." % n)])
                                  for n in (41, 42, 43)])
        # The engine still has the session: its second turn is tried once more.
        item = self.stopped_after_the_answer(engine, "What crystallinity does annealed PLA reach?")
        self.assertEqual(len(saved_sessions(self.root)), 2)  # The saved session and its working folder.
        view = self.restart(engine).get(item["id"])
        self.assertEqual((view["depositState"], view["deposit"]["findings"]), ({"status": "saved"}, 1))
        self.assertEqual(saved_sessions(self.root), [])
        # The session is gone: the findings are not saved, as interrupted, and its folder is deleted.
        item = self.stopped_after_the_answer(engine, "What crystallinity does PLA reach after annealing?")
        for path in Path(os.environ["CODEX_HOME"]).rglob("*.jsonl"):
            path.unlink()
        view = self.restart(engine).get(item["id"])
        self.assertEqual(view["depositState"], {"status": "failed", "reason": "interrupted",
                                                "message": "The app stopped while the findings were being saved"})
        self.assertEqual(saved_sessions(self.root), [])
        self.assertFalse([c for c in engine.calls if c["resume"] == item["session"]["id"]])
        # A settlement is the one more try: a transient failure then is final.
        item = self.stopped_after_the_answer(engine, "Does annealing raise PLA crystallinity?")
        engine.deposits = [engines.EngineError("crashed", "exit 1")]
        view = self.restart(engine).get(item["id"])
        self.assertEqual((view["depositState"]["reason"], [c["resume"] for c in engine.calls].count(item["session"]["id"])),
                         ("crashed", 1))
        self.assertEqual(saved_sessions(self.root), [])

    def test_a_stale_deposit_is_settled_without_a_restart_and_a_live_one_is_left_alone(self):
        # An interrupted `oopc ask` or a killed tick left it saving; the running app lists it, or the next tick runs.
        engine = ScriptedEngine(*[answer("x", [], [dict(FINDING, derivation="read", value=str(n),
                                                        statement="PLA reached %d%% crystallinity." % n)])
                                  for n in (51, 52)])
        item = self.stopped_after_the_answer(engine, "What crystallinity does annealed PLA reach?")
        path = self.root / ".oopc/loop/questions" / item["id"] / "question.json"
        live = json.loads(path.read_text())
        live["depositState"]["pid"] = os.getppid()  # A process that is still running: not this one's to settle.
        atomic_json(path, live)
        service = Questions(self.root, runner=engine, reviews=False)
        self.assertEqual((service.settle_stale(), service.get(item["id"])["depositState"]), ([], {"status": "saving"}))
        atomic_json(path, item)  # Its owner gone: the task list settles it.
        service.list()
        service.wait(10, reviews=True)
        self.assertEqual(service.get(item["id"])["depositState"], {"status": "saved"})
        self.assertEqual(json.loads(path.read_text()).get("session"), None)
        # The loop's tick settles one too, before it ends.
        other = self.stopped_after_the_answer(engine, "Does annealing raise PLA crystallinity?")
        tick = loop.tick(self.root, runner=engine, engine="codex")
        self.assertEqual((tick["deposits"], service.get(other["id"])["depositState"]), ([other["id"]], {"status": "saved"}))
        self.assertEqual(saved_sessions(self.root), [])

    def test_a_settlement_never_races_a_live_deposit(self):
        engine = ScriptedEngine(answer("x", [], [dict(FINDING, derivation="read")]))
        item = self.stopped_after_the_answer(engine, "What crystallinity does annealed PLA reach?")
        lock = self.root / ".oopc/loop/questions" / item["id"] / "deposit.lock"
        with locked(lock):  # Another process is saving them (its pid is gone from this one's view, its lock is not).
            service = self.restart(engine)
            self.assertEqual(service.get(item["id"])["depositState"], {"status": "saving"})
        self.assertFalse([c for c in engine.calls if c["resume"]])
        service.list()
        service.wait(10, reviews=True)
        self.assertEqual(service.get(item["id"])["depositState"], {"status": "saved"})

    def test_a_deposit_whose_second_turn_had_finished_is_saved_from_its_result(self):
        # The process stopped after turn 2 wrote its findings into the result but before they were deposited.
        engine = ScriptedEngine(answer("x", [], [dict(FINDING, derivation="read")]))
        item = self.stopped_after_the_answer(engine, "What crystallinity does annealed PLA reach?")
        result_path = self.root / ".oopc/loop/questions" / item["id"] / "result.json"
        stored = json.loads(result_path.read_text())
        stored["answer"]["findings"] = [dict(FINDING, derivation="read")]
        stored["depositTurn"] = {"callId": "c", "usage": {}, "agentSeconds": 1.0, "observedTools": []}
        atomic_json(result_path, stored)
        view = self.restart(engine).get(item["id"])
        self.assertEqual((view["depositState"], view["deposit"]["findings"]), ({"status": "saved"}, 1))
        self.assertFalse([c for c in engine.calls if c["resume"]])  # Not asked again.
        self.assertEqual(saved_sessions(self.root), [])

    def test_a_deposit_that_cannot_start_leaves_the_answer_and_no_saved_session(self):
        class NoThreads(threading.Thread):
            def start(self):
                if self.name == "oopc-deposit":
                    raise RuntimeError("can't start new thread")
                super().start()
        with mock.patch("oopc.ask.threading.Thread", NoThreads):
            done = self.ask(Questions(self.root, runner=ScriptedEngine(answer("It reached 45%.", [], [FINDING]))),
                            "What crystallinity does annealed PLA reach?")
        self.assertEqual((done["status"], done["result"]["answer"]), ("completed", "It reached 45%."))
        self.assertEqual((done["depositState"]["status"], done["depositState"]["reason"]), ("failed", "crashed"))

    def test_a_failed_deposit_still_captures_the_answers_cited_sources(self):
        captured = []
        engine = ScriptedEngine(answer("It reached 45% `https://example.org/pla-annealing`.",
                                       ["https://example.org/pla-annealing"], [FINDING]),
                                deposits=[engines.EngineError("timeout", "limit")])
        with mock.patch.object(sources, "network_allowed", return_value=True), \
                mock.patch("oopc.ask.after_answer", lambda root, qid, answer: captured.append(answer["citations"])):
            done = self.ask(Questions(self.root, runner=engine), "What crystallinity does annealed PLA reach?")
        self.assertEqual((done["depositState"]["reason"], captured), ("timeout", [["https://example.org/pla-annealing"]]))

    def test_a_retried_second_turn_starts_from_the_usage_the_failed_attempt_reported(self):
        # Codex reports a resumed session's usage from its start: a failed attempt's turn is in the next report too.
        reported = {"input_tokens": 2600, "cached_input_tokens": 900, "output_tokens": 180}
        engine = ScriptedEngine(answer("x", [], [dict(FINDING, derivation="read")]), deposits=[
            engines.EngineError("invalid-output", "no answer", usage={"input_tokens": 1600}, session_usage=reported)])
        done = self.ask(Questions(self.root, runner=engine), "What crystallinity does annealed PLA reach?")
        first, second = [c["previousUsage"] for c in engine.calls if c["resume"]]
        self.assertEqual((first, second), (ScriptedEngine.result("codex", "s", {})["usage"], reported))
        self.assertEqual(done["depositState"], {"status": "saved"})

    def test_oopc_ask_says_what_happened_to_the_findings(self):
        from oopc.cli import deposit_outcome
        self.assertEqual(deposit_outcome({"depositState": {"status": "saved"},
                                          "deposit": {"findings": 3, "notes": 2, "duplicates": 1}}),
                         "Findings saved: 3 findings and 2 source notes (1 already known).")
        self.assertEqual(deposit_outcome({"depositState": {"status": "failed", "reason": "timeout",
                                                           "message": "Stopped at the 300-second limit"}}),
                         "Findings not saved (timeout): Stopped at the 300-second limit. The answer stands.")
        self.assertEqual(deposit_outcome({"depositState": {"status": "saving"}}), "Findings are still being saved.")

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
        service.wait(10, reviews=True)
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

    def test_a_question_retried_by_hand_gets_a_new_trace_its_searches_are_recorded_in(self):
        # Before 2026-10-26 a retried question kept its failed trace, which refused the researcher's searches.
        def researcher(tools):
            tools.call("search_knowledge", {"q": "PLA crystallinity"})
            return answer("ok", [])
        service = Questions(self.root, runner=ScriptedEngine(engines.EngineError("timeout", "limit"), researcher))
        failed = self.ask(service, "What crystallinity does annealed PLA reach?")
        service.retry(failed["id"])
        service.wait(10, reviews=True)
        done = service.get(failed["id"])
        self.assertEqual(done["status"], "completed")
        self.assertNotEqual(done["runId"], failed["runId"])
        self.assertEqual(TraceStore(self.root).run(failed["runId"]).meta()["status"], "failed")
        events = TraceStore(self.root).run(done["runId"]).events()["events"]
        self.assertEqual([(e["agent_id"], e["status"]) for e in events if e["kind"] == "access"], [("researcher", "ok")])

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
        # The answer's page shows the saved finding it matched, and which question saved it.
        self.assertEqual([(f["id"], f["questionId"]) for f in second["alreadyKnown"]],
                         [(first["findings"][0]["id"], first["id"])])
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
        # The answer, its findings, then one review call for the flagged and the sampled findings.
        self.assertEqual([c["resume"] is not None for c in engine.calls], [False, True, False])
        for statement in (confident["statement"], skipped["statement"], unsure["statement"]):
            self.assertIn(statement, engine.calls[2]["prompt"])
        findings = service.get(view["id"])["findings"]
        # A sampled finding the reviewer skipped stays added on the researcher's judgement.
        self.assertEqual([f["status"] for f in findings], ["unsupported", "accepted", "supported"])
        self.assertEqual([f.get("spotCheck") for f in findings], ["unsupported", "not-assessed", None])
        self.assertEqual(findings[0]["review"]["engine"], "claude-code")
        self.assertEqual(knowledge.spot_check_stats(self.root),
                         {"checked": 1, "supported": 0, "unsupported": 1, "uncertain": 0, "pending": 0, "failed": 0,
                          "unsupportedRate": 1.0})
        self.assertEqual(knowledge.review_queue(self.root), [])

    def test_a_new_value_in_tension_with_saved_knowledge_is_reviewed_with_its_comparison(self):
        loop.update_settings(self.root, {"consistencyDepth": 8})
        confident = dict(FINDING, needsReview=False, reviewFlag="")
        first = self.ask(Questions(self.root, runner=ScriptedEngine(answer("x", [], [confident]))),
                         "What crystallinity does annealed PLA reach?")
        self.assertEqual(first["deposit"]["consistency"]["state"], "none")  # Nothing saved to compare with yet.
        other = dict(confident, statement="PLA film annealed at 100 °C for 1 h reached 85% crystallinity by DSC.",
                     value="85", sourceUrl="https://example.org/other", sourceDoi="10.1234/example.2",
                     excerpt="85% crystallinity")
        seen = {}

        def review(tools):
            seen["prompt"] = engine.calls[-1]["prompt"]
            new = "finding:%s-1" % seen["id"][:12]
            return {"verdicts": [], "conflicts": [{"finding": new, "with": first["findings"][0]["id"],
                                                   "reading": "sources-disagree", "reason": "Table 2s differ."}],
                    "notes": ""}
        engine = ScriptedEngine(answer("y", [], [other]), review)
        service = Questions(self.root, runner=engine, review_engine="claude-code")
        view = service.submit({"question": "How crystalline does PLA get on annealing?", "depth": "quick",
                               "authorizeSubscription": True, "runtime": "codex"})
        seen["id"] = view["id"]
        service.wait(10, reviews=True)
        # Nothing waited for a source check, but 85% beside a saved 45% sent the answer to review.
        self.assertIs(engine.calls[-1]["schema"], reviewer.CONSISTENCY_SCHEMA)
        self.assertIn(first["findings"][0]["statement"], seen["prompt"])
        done = service.get(view["id"])
        self.assertEqual(done["deposit"]["consistency"], {"state": "checked", "compared": 1, "conflicts": 1, "open": 0,
                                                          "waiting": False})
        self.assertEqual(done["findings"][0]["conflictsWith"], [first["findings"][0]["id"]])

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
        self.assertEqual(len(engine.calls), 3)  # The answer, its findings and their review, all before the tick ends.
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
        self.assertEqual(loop.settings(self.root), {"reviewMode": "researcher", "spotCheckRate": 0.3, "researchPerWeek": 0,
                                                    "reflectEveryDays": 0, "consistencyDepth": 8,
                                                    "conflictResolution": "reviewer", "parallelQuestions": 1, "scope": "",
                                                    "redirectUrl": "", "saveOutsideScope": False})
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

    def follow(self, service, parent, question, runtime="codex"):
        return service.submit({"question": question, "depth": "quick", "authorizeSubscription": True, "runtime": runtime,
                               "parentId": parent})

    def test_a_follow_up_is_told_the_conversation_with_its_findings_status_now(self):
        unnamed = dict(FINDING, subject="", material="4032D film", statement="The annealed 4032D film melted at 170 °C.",
                       property="melting temperature", value="170", unit="°C", excerpt="Tm of 170 °C",
                       derivation="read")
        engine = ScriptedEngine(
            answer("Crystallinity reached 45% `https://example.org/pla-annealing`.", ["https://example.org/pla-annealing"],
                   [FINDING]),
            {"verdicts": [], "notes": ""},  # The review right after the first answer, left inconclusive.
            answer("It melted at 170 °C `https://example.org/pla-annealing`.", ["https://example.org/pla-annealing"],
                   [unnamed]))
        service = Questions(self.root, runner=engine, review_engine="codex")
        first = self.ask(service, "How does annealing change PLA crystallinity?")
        [saved] = first["findings"]
        with knowledge.connect(self.root) as db:  # A later review rejected it.
            db.execute("UPDATE findings SET status='unsupported', review_reason='Table 2 reports 41%.' WHERE id=?",
                       (saved["id"],))
        second = self.follow(service, first["id"], "What about its melting point?")
        service.wait(10, reviews=True)
        done = service.get(second["id"])

        # A question asked on its own keeps its prompt exactly; the follow-up's adds the conversation before its question.
        self.assertEqual(engine.calls[0]["prompt"], researcher_prompt("How does annealing change PLA crystallinity?", "quick"))
        self.assertNotIn(FOLLOW_UP, engine.calls[0]["prompt"])
        prompt = [c for c in engine.calls if c["schema"] is ANSWER_SCHEMA and not c["resume"]][1]["prompt"]
        self.assertIn(FOLLOW_UP, prompt)
        self.assertIn("Earlier question 1: How does annealing change PLA crystallinity?\nAnswer 1:\nCrystallinity reached 45%",
                      prompt)
        self.assertIn("- `%s` Rejected: %s (reviewer: Table 2 reports 41%%.)" % (saved["id"], FINDING["statement"]), prompt)
        self.assertTrue(prompt.endswith("Follow-up question:\nWhat about its melting point?"))
        told = self.root / ".oopc/loop/questions" / done["id"] / "conversation.txt"
        self.assertIn("Earlier question 1:", told.read_text())
        self.assertEqual(told.stat().st_mode & 0o777, 0o600)
        stored = json.loads((told.parent / "result.json").read_text())
        self.assertEqual(stored["promptVersion"], prompt_version(follow_up=True))
        self.assertNotEqual(prompt_version(follow_up=True), prompt_version())
        self.assertEqual(TraceStore(self.root).run(done["runId"]).meta()["task"]["followsQuestion"], first["id"])

        # Both questions show the conversation; the follow-up's finding is filed by the question before it.
        self.assertEqual((done["parentId"], done["threadId"]), (first["id"], first["id"]))
        turns = [(t["taskId"], t["status"]) for t in done["thread"]]
        self.assertEqual(turns, [(first["id"], "completed"), (done["id"], "completed")])
        self.assertEqual([t["taskId"] for t in service.get(first["id"])["thread"]], [first["id"], done["id"]])
        self.assertEqual([f["subject"] for f in done["findings"]], ["wop-000001"])

        # A conversation is continued from its latest answer, and only from an answered question.
        with self.assertRaises(QuestionUnavailable):
            self.follow(service, first["id"], "And its glass transition?")
        with self.assertRaises(FileNotFoundError):
            self.follow(service, "0" * 32, "And its glass transition?")
        with self.assertRaises(ValueError):
            self.follow(service, "../elsewhere", "And its glass transition?")
        failed = dict(json.loads((told.parent / "question.json").read_text()), status="failed")
        atomic_json(told.parent / "question.json", failed, private=True)
        with self.assertRaises(QuestionUnavailable):
            self.follow(service, done["id"], "And its glass transition?")

    def test_a_long_conversation_leaves_out_its_oldest_answers_first(self):
        folder, service = self.root / ".oopc/loop/questions", Questions(self.root, runner=ScriptedEngine())
        # The second question's clock is ahead of the third's: the conversation follows its links, not its clocks.
        chain = [("a" * 32, None, "First question about PLA?", "01"), ("b" * 32, "a" * 32, "Second question?", "09"),
                 ("c" * 32, "b" * 32, "Third question?", "05")]
        for identifier, parent, question, hour in chain:
            atomic_json(folder / identifier / "question.json", {"id": identifier, "question": question, "origin": "ask",
                        "status": "completed", "submittedAt": "2026-10-30T%s:00:00+00:00" % hour,
                        "attempts": [], **({"parentId": parent, "threadId": "a" * 32} if parent else {})})
            atomic_json(folder / identifier / "result.json", {"answer": {"answer": question[:5] + " answer. " * 40,
                                                                          "citations": []}})
        third = service._read("c" * 32)
        self.assertEqual([t["id"] for t in service.earlier(third)], ["a" * 32, "b" * 32])
        self.assertEqual([t["id"] for t in service.thread(third)], ["a" * 32, "b" * 32, "c" * 32])
        whole = service.conversation(third)
        self.assertIn("Answer 1:\nFirst answer.", whole)
        with mock.patch("oopc.ask.CONVERSATION_CHARACTERS", 600):
            short = service.conversation(third)
        self.assertIn("Earlier question 1: First question about PLA?\n(Its answer and findings are left out", short)
        self.assertIn("Earlier question 2: Second question?\nAnswer 2:\nSecon answer.", short)
        with mock.patch("oopc.ask.CONVERSATION_CHARACTERS", 50):  # The last answer is shortened, never left out.
            self.assertIn("Answer 2:\nSecon answer.", service.conversation(third))

    def test_a_follow_up_waits_for_the_answer_before_it_to_be_saved_and_reviewed(self):
        saving, reviewing, seen = threading.Event(), threading.Event(), {}

        def review(tools):
            reviewing.wait(10)
            return {"verdicts": [{"id": seen["finding"], "verdict": "supported", "reason": "Table 2 reports 45%."}],
                    "notes": ""}

        def follow_up(tools):  # What the follow-up finds when it starts.
            parent = json.loads((self.root / ".oopc/loop/questions" / seen["first"] / "question.json").read_text())
            seen.update(parent=parent["depositState"], status=knowledge.get(self.root, seen["finding"])["status"])
            return answer("Its melting point was not in the saved findings.", [])
        engine = ScriptedEngine(answer("It reached 45%.", ["https://example.org/pla-annealing"], [FINDING]), review,
                                follow_up, deposits=[lambda tools: saving.wait(10) and None])
        service = Questions(self.root, runner=engine, review_engine="codex")
        researched = lambda: [c for c in engine.calls if c["schema"] is ANSWER_SCHEMA and not c["resume"]]  # noqa: E731

        def until(check):
            deadline = time.monotonic() + 10
            while not check() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(check())
        with mock.patch("oopc.ask.PARENT_POLL_SECONDS", 0.02):
            first = service.submit({"question": "What crystallinity does annealed PLA reach?", "depth": "quick",
                                    "authorizeSubscription": True, "runtime": "codex"})
            seen.update(first=first["id"], finding="finding:%s-1" % first["id"][:12])
            until(lambda: service.get(first["id"])["status"] == "completed")
            # On the other engine, nothing else makes it wait: it waits for the findings to be saved, then reviewed.
            second = self.follow(service, first["id"], "What about its melting point?", runtime="claude-code")
            until(lambda: (service.get(second["id"]).get("progress") or {}).get("lastAction") == calls.WAITING["deposit"])
            saving.set()
            until(lambda: (service.get(second["id"]).get("progress") or {}).get("lastAction") == calls.WAITING["review"])
            self.assertEqual(len(researched()), 1)
            reviewing.set()
            service.wait(10, reviews=True)
        self.assertEqual(len(researched()), 2)
        self.assertEqual((seen["parent"]["status"], "reviewing" in seen["parent"], seen["status"]),
                         ("saved", False, "supported"))
        self.assertEqual(service.get(second["id"])["status"], "completed")

    def test_a_question_outside_the_scope_is_not_researched_and_points_elsewhere(self):
        loop.update_settings(self.root, {"researchPerWeek": 5})  # Its open questions would join the queue if it ran.
        engine = ScriptedEngine(dict(answer("", []), openQuestions=[], outOfScope="It asks for a bread recipe."))
        service = Questions(self.root, runner=engine)
        done = self.ask(service, "What is a good recipe for banana bread?")
        self.assertEqual((done["status"], done["outOfScope"]), ("completed", "It asks for a bread recipe."))
        self.assertEqual(done["redirectUrl"], "https://chatgpt.com/")  # The chat of the engine that ran it.
        self.assertIn("Your field is " + DEFAULT_SCOPE + ".", engine.calls[0]["prompt"])
        # One turn: no second turn, deposit, review, source capture or research queue; its session is gone.
        self.assertEqual(len(engine.calls), 1)
        self.assertNotIn("depositState", done)
        self.assertEqual((done["findings"], done["notes"], loop.research_queue(self.root)), ([], [], []))
        self.assertEqual(knowledge.review_queue(self.root), [])
        self.assertEqual(TraceStore(self.root).run(done["runId"]).meta()["status"], "completed")
        self.assertEqual(json.loads((self.root / ".oopc/loop/questions" / done["id"] / "result.json").read_text())
                         ["promptVersion"], prompt_version())
        self.assertEqual(Questions(self.root).list()["tasks"][0]["outOfScope"], "It asks for a bread recipe.")
        # Not an answer in the counts: neither reuse nor the week's summary counts it as one.
        self.assertEqual(reuse_stats(self.root), {"answered": 0, "citingReviewed": 0})
        from oopc import improve
        self.assertEqual({k: improve.summary(self.root)[k] for k in ("answered", "outOfScope", "notSavedOutsideScope")},
                         {"answered": 0, "outOfScope": 1, "notSavedOutsideScope": 0})

        loop.update_settings(self.root, {"redirectUrl": "https://example.org/other-harness"})
        self.assertEqual(service.get(done["id"])["redirectUrl"], "https://example.org/other-harness")
        # A follow-up can still continue the conversation, and is told the question before it was not answered.
        engine.steps.append(answer("PLA films crystallize on annealing.", []))
        self.follow(service, done["id"], "What about annealed PLA films instead?")
        service.wait(10, reviews=True)
        self.assertIn("(Not answered: outside this assistant's scope.)", engine.calls[1]["prompt"])

    def test_an_answer_outside_the_scope_stands_but_saves_nothing_by_default(self):
        loop.update_settings(self.root, {"researchPerWeek": 5})  # Its open questions would join the queue in scope.
        outside = "It asks about graphite anodes in lithium-ion cells"
        engine = ScriptedEngine(dict(answer("Graphite anodes reach about 372 mAh/g.", []),
                                     openQuestions=["Which binders suit silicon anodes?"], outOfScope=outside))
        service = Questions(self.root, runner=engine)
        done = self.ask(service, "What capacity do graphite anodes reach?")
        # A sentence beside an answer never declines it: the answer stands, with nothing pointing elsewhere.
        self.assertNotIn("outOfScope", done)
        self.assertEqual((done["status"], done["result"]["answer"]), ("completed", "Graphite anodes reach about 372 mAh/g."))
        self.assertEqual(done["depositState"], {"status": "skipped", "reason": "outside-scope", "message": outside})
        # One turn: no second turn, findings, review or research queue, and its session and trace are finished.
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual((done["findings"], done["notes"], done["queuedResearch"], loop.research_queue(self.root)),
                         ([], [], [], []))
        self.assertEqual(knowledge.review_queue(self.root), [])
        self.assertNotIn("session", json.loads((self.root / ".oopc/loop/questions" / done["id"] / "question.json")
                                               .read_text()))
        self.assertEqual(TraceStore(self.root).run(done["runId"]).meta()["status"], "completed")
        self.assertEqual(reuse_stats(self.root), {"answered": 1, "citingReviewed": 0})  # It is an answer.
        from oopc import improve  # ... counted apart as one whose findings were not saved.
        self.assertEqual({k: improve.summary(self.root)[k] for k in ("answered", "outOfScope", "notSavedOutsideScope")},
                         {"answered": 1, "outOfScope": 0, "notSavedOutsideScope": 1})
        from oopc.cli import deposit_outcome
        self.assertIn("outside this workspace's scope", deposit_outcome(done))
        # A follow-up is told that it was outside the scope and saved nothing.
        engine.steps.append(answer("PVDF is the usual binder.", []))
        self.follow(service, done["id"], "Which polymer binders do graphite anodes use?")
        service.wait(10, reviews=True)
        self.assertIn("It was outside this assistant's scope, so its findings were not saved.", engine.calls[1]["prompt"])

        # The owner can save such answers as in scope ones are.
        self.assertTrue(loop.update_settings(self.root, {"saveOutsideScope": True})["saveOutsideScope"])
        engine = ScriptedEngine(dict(answer("Graphite anodes reach about 372 mAh/g.", []), outOfScope=outside))
        saved = self.ask(Questions(self.root, runner=engine), "What capacity do graphite anodes reach at C/10?")
        self.assertEqual((saved["depositState"]["status"], len(engine.calls)), ("saved", 2))  # The answer, then findings.
        for change in ({"saveOutsideScope": "yes"}, {"saveOutsideScope": 1}, {"saveOutsideScope": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                loop.update_settings(self.root, change)

    def test_the_scope_is_a_setting_filled_into_the_researchers_prompt(self):
        battery = "lithium-ion battery electrochemistry: electrodes, electrolytes and cell performance"
        self.assertEqual(loop.update_settings(self.root, {"scope": "  " + battery + "\n"})["scope"], battery)
        engine = ScriptedEngine(answer("Graphite anodes reach about 372 mAh/g.", []))
        done = self.ask(Questions(self.root, runner=engine), "What capacity do graphite anodes reach?")
        self.assertIn("Your field is " + battery + ".", engine.calls[0]["prompt"])
        self.assertNotIn(DEFAULT_SCOPE, engine.calls[0]["prompt"])
        version = json.loads((self.root / ".oopc/loop/questions" / done["id"] / "result.json").read_text())["promptVersion"]
        self.assertEqual(version, prompt_version(scope=battery))
        self.assertNotEqual(version, prompt_version())  # A changed scope is a changed prompt.
        self.assertEqual(researcher_prompt("Q?", "quick"), researcher_prompt("Q?", "quick", scope=DEFAULT_SCOPE))
        self.assertNotIn("{scope}", researcher_prompt("Q?", "quick"))
        self.assertIn('"outOfScope"', json.dumps(ANSWER_SCHEMA["required"]))
        self.assertIn("outOfScope as empty strings", DEPOSIT)

        self.assertEqual(loop.update_settings(self.root, {"scope": ""})["scope"], "")  # Empty restores the default.
        self.assertEqual(workspace_scope(self.root), DEFAULT_SCOPE)
        for change in ({"scope": "polymers"}, {"scope": 42}, {"scope": "x" * 2001}, {"redirectUrl": "ftp://example.org"},
                       {"redirectUrl": "claude.ai"}, {"redirectUrl": "https://exa mple.org"}, {"redirectUrl": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                loop.update_settings(self.root, change)
        self.assertEqual(loop.update_settings(self.root, {"redirectUrl": " https://claude.ai/new "})["redirectUrl"],
                         "https://claude.ai/new")
        self.assertEqual(redirect_url(self.root, "claude-code"), "https://claude.ai/new")
        loop.update_settings(self.root, {"redirectUrl": ""})
        self.assertEqual(redirect_url(self.root, "claude-code"), CHAT_SITES["claude-code"])

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
