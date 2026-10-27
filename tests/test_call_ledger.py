"""Every engine attempt is recorded with its usage, and one answer is never reviewed by two sessions at once."""
import threading
import unittest
from unittest.mock import patch

import test_core_loop as core
from oopc import calls, engines, knowledge, reviewer
from oopc.util import atomic_json, now


class CallLedger(unittest.TestCase):
    setUp = core.CoreLoopTests.setUp

    def deposit(self):
        q = "c" * 32
        knowledge.deposit(self.root, q, core.answer("", [], [core.FINDING]), engine="codex", review_mode="all")
        return q, knowledge.for_question(self.root, q)[0]["id"]

    def test_failed_and_missing_usage_are_counted_once(self):
        usage = {"input_tokens": 120, "cached_input_tokens": 100, "output_tokens": 8}
        runner = core.ScriptedEngine(engines.EngineError("quota", "limited", usage=usage), core.answer("", []))
        with self.assertRaises(engines.EngineError):
            calls.invoke(self.root, "research", "q", runner, "codex", "", {})
        calls.invoke(self.root, "research", "q", runner, "codex", "", {})
        calls.invoke(self.root, "review", "q", lambda *a, **k: {"answer": {}}, "codex", "", {})
        value = calls.summary(self.root)
        self.assertEqual((value["calls"], value["measuredNewTokens"], value["missingUsage"]), (3, 1128, 1))
        self.assertEqual(value["failed"], {"quota": 1})
        self.assertEqual(calls.summary(self.root), value)

    def test_the_next_answer_waits_for_the_last_ones_findings_so_it_reads_them(self):
        started, release = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            self.assertTrue(release.wait(3))
            return {"engine": "codex", "answer": {}}
        background = threading.Thread(target=lambda: calls.invoke(self.root, "deposit", "q1", slow, "codex", "", {}))
        background.start()
        self.assertTrue(started.wait(3))
        answered = threading.Event()
        foreground = threading.Thread(target=lambda: (calls.invoke(self.root, "research", "q2", lambda *a, **k:
                                                                   {"engine": "codex", "answer": {}}, "codex", "", {}),
                                                      answered.set()))
        foreground.start()
        self.assertFalse(answered.wait(0.5))  # Still writing q1's findings.
        release.set()
        self.assertTrue(answered.wait(3))
        for thread in (background, foreground):
            thread.join(3)

    def test_a_second_reviewer_waits_and_finds_nothing_left_to_review(self):
        q, identifier = self.deposit()
        started, release = threading.Event(), threading.Event()

        def review(*a, **k):
            started.set()
            self.assertTrue(release.wait(3))
            return {"engine": "codex", "answer": {"verdicts": [{"id": identifier, "verdict": "supported", "reason": "Table"}]}}
        first = threading.Thread(target=lambda: reviewer.review(self.root, q, engine="codex", runner=review))
        first.start()
        self.assertTrue(started.wait(3))
        second = threading.Thread(target=lambda: reviewer.review(
            self.root, q, engine="codex", runner=lambda *a, **k: self.fail("duplicate review session")))
        second.start()
        release.set()
        first.join(3)
        second.join(3)
        self.assertEqual(len(calls.records(self.root)), 1)
        self.assertEqual(knowledge.get(self.root, identifier)["status"], "supported")

    def test_a_call_left_running_by_a_stopped_process_counts_as_interrupted(self):
        atomic_json(self.root / ".oopc/loop/calls/dead.json", {"callId": "dead", "phase": "review", "owner": "q",
                    "engine": "codex", "pid": 999999, "startedAt": now(), "outcome": "running", "newTokens": None})
        with patch("oopc.calls.os.kill", side_effect=ProcessLookupError):
            [record] = calls.records(self.root)
        self.assertEqual((record["outcome"], record["reason"]), ("failed", "interrupted"))


if __name__ == "__main__":
    unittest.main()
