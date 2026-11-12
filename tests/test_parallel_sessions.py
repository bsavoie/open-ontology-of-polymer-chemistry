"""Several sessions on one store (owner, 2026-11-05: parallel sessions on one machine): the app, `oopc ask`, the loop's
tick and parallel questions write it at once without losing or doubling anything."""
import json
import sqlite3
import threading
import time
import unittest
from unittest import mock

import test_core_loop as core
from oopc import calls, knowledge, loop, reviewer, sources
from oopc.ask import Questions
from oopc.util import atomic_json, locked


class ParallelSessions(unittest.TestCase):
    setUp = core.CoreLoopTests.setUp

    def deposit(self, question, finding=core.FINDING):
        knowledge.deposit(self.root, question, core.answer("", [], [finding]), engine="codex", review_mode="all")
        return knowledge.for_question(self.root, question)[0]["id"]

    def test_the_store_runs_in_wal_mode_so_readers_never_wait_for_a_writer(self):
        self.deposit("a" * 32)
        with sqlite3.connect(str(knowledge.database(self.root))) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        with knowledge.connect(self.root, write=True) as writer:  # A writer holds the store ...
            writer.execute("UPDATE deposits SET findings=findings")
            self.assertEqual(len(knowledge.for_question(self.root, "a" * 32)), 1)  # ... and a reader still reads.

    def test_two_answers_saving_one_fact_at_once_save_it_once(self):
        real, entered = knowledge.settle_names, []

        def slow(root, finding, context=""):  # The first deposit lingers after its duplicate check.
            entered.append(threading.current_thread().name)
            if len(entered) == 1:
                time.sleep(0.4)
            return real(root, finding, context)
        with mock.patch.object(knowledge, "settle_names", slow):
            first = threading.Thread(target=self.deposit, args=("a" * 32,), name="first")
            first.start()
            time.sleep(0.1)
            second = threading.Thread(target=self.deposit, args=("b" * 32,), name="second")
            second.start()
            first.join(5)
            second.join(5)
        with knowledge.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT duplicates FROM deposits WHERE question_id=?", ("b" * 32,)).fetchone()[0], 1)

    def test_reviews_of_two_answers_run_side_by_side_and_hold_no_store_lock_through_the_session(self):
        loop.update_settings(self.root, {"parallelQuestions": 2})
        other = dict(core.FINDING, statement="PLA film annealed at 120 °C reached 50% crystallinity by DSC.", value="50",
                     sourceUrl="https://example.org/pla-other", sourceDoi="10.1234/example.2")
        ids = {"a" * 32: self.deposit("a" * 32), "b" * 32: self.deposit("b" * 32, other)}
        together, free = threading.Barrier(2, timeout=5), []

        def review(engine, prompt, schema, **options):
            together.wait()  # Both sessions are running at once.
            try:
                with locked(knowledge.folder(self.root) / "review.lock", blocking=False):
                    free.append(True)  # Maintenance could run now: no review holds the store's lock.
            except BlockingIOError:
                free.append(False)
            identifier = next(i for i in ids.values() if i in prompt)
            return {"engine": engine, "answer": {"verdicts": [{"id": identifier, "verdict": "supported",
                                                               "reason": "Table 2."}]}}
        threads = [threading.Thread(target=reviewer.review, args=(self.root, q), kwargs={"engine": "codex", "runner": review})
                   for q in ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(free, [True, True])
        self.assertEqual({knowledge.get(self.root, i)["status"] for i in ids.values()}, {"supported"})
        with knowledge.connect(self.root) as db:
            self.assertEqual({r[0] for r in db.execute("SELECT review_claim FROM deposits")}, {None})

    def test_a_claim_left_by_a_stopped_process_does_not_block_the_review(self):
        q = "a" * 32
        identifier = self.deposit(q)
        with knowledge.connect(self.root, write=True) as db:
            db.execute("UPDATE deposits SET review_claim=? WHERE question_id=?",
                       (json.dumps({"pid": core.dead_pid(), "at": "2026-11-05T00:00:00+00:00"}), q))
        reviewer.review(self.root, q, engine="codex", runner=lambda engine, prompt, schema, **o: {
            "engine": engine, "answer": {"verdicts": [{"id": identifier, "verdict": "supported", "reason": "Table 2."}]}})
        self.assertEqual(knowledge.get(self.root, identifier)["status"], "supported")

    def test_engine_slots_follow_the_parallel_setting(self):
        def overlap(count):
            loop.update_settings(self.root, {"parallelQuestions": count})
            inside, most, guard = [0], [0], threading.Lock()

            def session(*a, **k):
                with guard:
                    inside[0] += 1
                    most[0] = max(most[0], inside[0])
                time.sleep(0.3)
                with guard:
                    inside[0] -= 1
                return {"engine": "codex", "answer": {}}
            threads = [threading.Thread(target=calls.invoke, args=(self.root, "research", "q%d" % n, session, "codex",
                                                                    "", {})) for n in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            return most[0]
        self.assertEqual(overlap(1), 1)
        self.assertEqual(overlap(3), 3)

    def test_questions_run_in_parallel_slots(self):
        loop.update_settings(self.root, {"parallelQuestions": 2})
        together = threading.Barrier(2, timeout=5)

        def research(tools):
            together.wait()  # Both questions are being researched at once.
            return core.answer("Answered.", [])
        service = Questions(self.root, runner=core.ScriptedEngine(research, research))
        views = [service.submit({"question": "Question number %d about PLA crystallinity?" % n, "budgetSeconds": 300,
                                 "authorizeSubscription": True, "runtime": "codex"}) for n in range(2)]
        service.wait(10, reviews=True)
        self.assertEqual([service.get(v["id"])["status"] for v in views], ["completed", "completed"])

    def test_a_question_a_stopped_drainer_left_running_is_retried_when_the_next_drainer_starts(self):
        service = Questions(self.root, runner=core.ScriptedEngine(core.answer("Answered.", [])))
        with mock.patch.object(service, "start"):  # Queued, as if its drainer then stopped mid-question.
            view = service.submit({"question": "What crystallinity does annealed PLA reach?", "budgetSeconds": 300,
                                   "authorizeSubscription": True, "runtime": "codex"})
        item = service._read(view["id"])
        item.update(status="running", startedAt=item["submittedAt"])
        service._write(item)
        service.start()
        service.wait(10, reviews=True)
        done = service.get(view["id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(service._read(view["id"])["attempts"][0]["reason"], "interrupted")

    def test_one_questions_file_is_written_by_one_process_at_a_time(self):
        first = Questions(self.root, runner=core.ScriptedEngine())
        second = Questions(self.root, runner=core.ScriptedEngine())  # Another process: its own thread lock.
        with mock.patch.object(first, "start"):
            view = first.submit({"question": "What crystallinity does annealed PLA reach?", "budgetSeconds": 300,
                                 "authorizeSubscription": True, "runtime": "codex"})
        order = []
        with first._holding(view["id"]):
            waiter = threading.Thread(target=lambda: second._holding(view["id"]).__enter__() or order.append("second"))
            waiter.start()
            time.sleep(0.3)
            order.append("first done")
        waiter.join(5)
        self.assertEqual(order, ["first done", "second"])

    def test_settings_changed_by_two_processes_at_once_keep_both_changes(self):
        real = loop.settings

        def slow(root):
            value = real(root)
            time.sleep(0.2)  # Both read before either writes, without the lock.
            return value
        with mock.patch.object(loop, "settings", slow):
            threads = [threading.Thread(target=loop.update_settings, args=(self.root, change))
                       for change in ({"spotCheckRate": 0.5}, {"researchPerWeek": 3})]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
        value = loop.settings(self.root)
        self.assertEqual((value["spotCheckRate"], value["researchPerWeek"]), (0.5, 3))
        with self.assertRaises(ValueError):
            loop.update_settings(self.root, {"parallelQuestions": 0})

    def test_a_failed_capture_never_overwrites_one_another_process_saved(self):
        source = {"url": "https://example.org/paper", "title": "A paper"}
        path = sources._path(self.root, sources.key(source))

        def fetch(url):  # Another process captures it while this one tries and fails.
            atomic_json(path, {"key": sources.key(source), "text": "The paper's text. " * 100, "attempts": []})
            return 404, "text/html", b"", url
        value = sources.capture(self.root, source, fetch=fetch)
        self.assertTrue(value.get("text"))
        self.assertTrue(sources.captured(self.root, source))


if __name__ == "__main__":
    unittest.main()
