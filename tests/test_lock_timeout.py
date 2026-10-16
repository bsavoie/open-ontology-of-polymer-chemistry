"""Bounded waits on local lock files report the lock instead of hanging (TD-5)."""
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from oopc import trace
from oopc.util import locked


class BoundedLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oopc-lock-")
        self.path = Path(self.temp.name) / "run" / ".lock"

    def tearDown(self):
        self.temp.cleanup()

    def test_reentrant_wait_times_out_and_names_the_holding_thread(self):
        started = time.monotonic()
        with locked(self.path, timeout=5):
            with self.assertRaisesRegex(TimeoutError, r"\.lock \(held in this process by thread 'MainThread'"):
                with locked(self.path, timeout=0.2):
                    self.fail("A second holder must not acquire the lock")
        self.assertLess(time.monotonic() - started, 3)
        with locked(self.path, timeout=0.2):
            pass  # released after the timed-out waiter gave up

    def test_bounded_wait_acquires_once_the_holder_releases(self):
        held, release = threading.Event(), threading.Event()

        def holder():
            with locked(self.path):
                held.set()
                release.wait(5)

        worker = threading.Thread(target=holder, name="holder")
        worker.start()
        held.wait(5)
        threading.Timer(0.2, release.set).start()
        with locked(self.path, timeout=5):
            pass
        worker.join(5)

    def test_non_blocking_and_unbounded_modes_are_unchanged(self):
        with locked(self.path):
            with self.assertRaises(BlockingIOError):
                with locked(self.path, blocking=False):
                    pass

    def test_run_trace_writers_use_a_bounded_wait(self):
        source = Path(trace.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count('locked(self.path / ".lock", timeout=RUN_LOCK_TIMEOUT)'), 3)
        self.assertNotIn('locked(self.path / ".lock")', source)


class PrivateStorageModeTests(unittest.TestCase):
    """TD-22: trace indexes and lock files must not be readable by other local users."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oopc-private-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_new_and_existing_sqlite_files_are_owner_only(self):
        import sqlite3
        from oopc.util import private_sqlite
        fresh = self.root / "fresh.sqlite"
        with sqlite3.connect(private_sqlite(fresh)) as db:
            db.execute("PRAGMA journal_mode=WAL"); db.execute("CREATE TABLE t (x)"); db.execute("INSERT INTO t VALUES (1)")
            wal = fresh.with_name(fresh.name + "-wal")
            self.assertTrue(wal.exists())
            for path in (fresh, wal, fresh.with_name(fresh.name + "-shm")):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, path.name)
        old = self.root / "old.sqlite"
        sqlite3.connect(str(old)).close()
        os.chmod(old, 0o644)
        private_sqlite(old)
        self.assertEqual(stat.S_IMODE(old.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_lock_files_are_owner_only(self):
        with locked(self.root / "run" / ".lock", timeout=1):
            pass
        self.assertEqual(stat.S_IMODE((self.root / "run" / ".lock").stat().st_mode) & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
