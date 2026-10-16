"""Windows storage branches are exercised with mocks on any host and in CI."""
import errno
import os
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import Mock, patch

from oopc.util import _windows_locked, atomic_bytes, locked


class StoragePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_private_write_without_fchmod_uses_path_permission_fallback(self):
        original_chmod = os.chmod
        with patch("oopc.util.os.fchmod", None, create=True), patch("oopc.util.os.chmod", wraps=original_chmod) as chmod:
            path = self.root/"private.json"
            atomic_bytes(path, b'{"private":true}', private=True)
        self.assertEqual(path.read_bytes(), b'{"private":true}')
        self.assertEqual(chmod.call_count, 1)
        self.assertEqual(chmod.call_args.args[1], 0o600)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_failed_permissions_close_descriptor_and_preserve_previous_file(self):
        path = self.root/"private.json"
        path.write_bytes(b"prior")
        descriptors = []
        def fail(fd, mode):
            descriptors.append(fd)
            raise PermissionError("permission fixture")
        with patch("oopc.util.os.fchmod", side_effect=fail, create=True):
            with self.assertRaises(PermissionError):
                atomic_bytes(path, b"replacement", private=True)
        self.assertEqual(path.read_bytes(), b"prior")
        self.assertEqual(list(self.root.iterdir()), [path])
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_windows_lock_keeps_waiting_beyond_ten_contention_attempts(self):
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        backend.locking.side_effect = [OSError(errno.EACCES, "busy") for _ in range(12)]+[None, None]
        with open(self.root/"lock", "a+b") as handle, patch("oopc.util.time.sleep") as sleep:
            with _windows_locked(handle, backend=backend):
                self.assertEqual(backend.locking.call_count, 13)
            self.assertEqual(sleep.call_count, 12)
            self.assertEqual(backend.locking.call_args.args, (handle.fileno(), backend.LK_UNLCK, 1))
            self.assertEqual(handle.tell(), 0)

    def test_windows_nonblocking_lock_never_enters_body_or_unlocks_on_contention(self):
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        backend.locking.side_effect = OSError(errno.EACCES, "busy")
        with open(self.root/"lock", "a+b") as handle, patch("oopc.util.time.sleep") as sleep:
            with self.assertRaises(BlockingIOError):
                with _windows_locked(handle, blocking=False, backend=backend):
                    self.fail("Locked body must not execute")
            self.assertEqual(backend.locking.call_count, 1)
            sleep.assert_not_called()

    def test_windows_unexpected_failure_and_interruption_are_not_hidden(self):
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        backend.locking.side_effect = OSError(errno.EBADF, "bad descriptor")
        with open(self.root/"lock", "a+b") as handle, patch("oopc.util.time.sleep") as sleep:
            with self.assertRaises(OSError) as caught:
                with _windows_locked(handle, backend=backend):
                    self.fail("Locked body must not execute")
            self.assertEqual(caught.exception.errno, errno.EBADF)
            sleep.assert_not_called()
            backend.locking.side_effect = OSError(errno.EACCES, "busy")
            sleep.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                with _windows_locked(handle, backend=backend):
                    self.fail("Locked body must not execute")

    def test_windows_lock_releases_after_body_error(self):
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        with open(self.root/"lock", "a+b") as handle:
            with self.assertRaisesRegex(RuntimeError, "body"):
                with _windows_locked(handle, backend=backend):
                    handle.seek(10)
                    raise RuntimeError("body")
            self.assertEqual(backend.locking.call_count, 2)
            self.assertEqual(backend.locking.call_args.args, (handle.fileno(), backend.LK_UNLCK, 1))
            self.assertEqual(handle.tell(), 0)

    def test_actual_platform_nonblocking_lock_contention(self):
        path = self.root/"real-lock"
        with locked(path):
            with self.assertRaises(BlockingIOError):
                with locked(path, blocking=False):
                    self.fail("A second handle cannot enter the locked region")
        with locked(path, blocking=False):
            pass


class ProjectionPortabilityTests(unittest.TestCase):
    def test_staging_flush_uses_writable_handles_without_changing_release_bytes(self):
        from oopc.release import build_release, verify_release
        from oopc.vocabulary import get_ontology
        records = [{"@id": "wop-000001", "@type": "PolymerConcept",
                    "label": "Synthetic polymer", "status": "seed", "layer": "science"}]
        original_open, original_fsync = Path.open, os.fsync
        handles, flushed = {}, []

        def tracked_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            handles[handle.fileno()] = handle
            return handle

        def windows_fsync(descriptor):
            # Windows rejects fsync on a read-only file descriptor. Enforce
            # that constraint on every host while still performing real sync.
            handle = handles[descriptor]
            if not handle.writable():
                raise OSError(errno.EBADF, "Windows requires a writable flush handle")
            flushed.append(Path(handle.name).name)
            return original_fsync(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normal = build_release(root / "normal", records, get_ontology(), {})
            with patch.object(Path, "open", tracked_open), \
                    patch("oopc.release.os.fsync", side_effect=windows_fsync):
                windows = build_release(root / "windows", records, get_ontology(), {})
            expected = verify_release(normal)
            self.assertEqual(verify_release(windows), expected)
            self.assertEqual(len(flushed), len(expected["files"]) + 1)  # Includes manifest.
            self.assertIn("graph.sqlite", flushed)
            self.assertIn("manifest.json", flushed)
            for relative in expected["files"]:
                self.assertEqual((normal / relative).read_bytes(),
                                 (windows / relative).read_bytes(), relative)

    def test_staging_flush_failure_cleans_candidate_and_preserves_prior_release(self):
        from oopc.release import build_release, verify_release
        from oopc.vocabulary import get_ontology
        records = [{"@id": "wop-000001", "@type": "PolymerConcept",
                    "label": "Synthetic prior", "status": "seed", "layer": "science"}]
        original_fsync, calls = os.fsync, []

        def fail_second_sync(descriptor):
            calls.append(descriptor)
            if len(calls) == 2:
                raise OSError(errno.EIO, "synthetic flush failure")
            return original_fsync(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = build_release(root / "prior", records, get_ontology(), {})
            expected = verify_release(prior)
            changed = [dict(records[0], label="Synthetic candidate")]
            with patch("oopc.release.os.fsync", side_effect=fail_second_sync):
                with self.assertRaisesRegex(OSError, "synthetic flush failure"):
                    build_release(root / "candidate", changed, get_ontology(), {})
            self.assertEqual(len(calls), 2)
            self.assertEqual(verify_release(prior), expected)
            self.assertEqual(list(root.iterdir()), [prior])

    def test_projection_bytes_match_with_windows_text_translation(self):
        from oopc.release import build_release, verify_release
        from oopc.vocabulary import get_ontology
        records = [{"@id":"wop-000001", "@type":"PolymerConcept", "label":"Polymer µ / α", "status":"seed", "layer":"science"}]
        original_open = Path.open
        def windows_open(path, mode="r", *args, **kwargs):
            if "b" not in mode and any(char in mode for char in "wax"):
                if kwargs.get("newline") is None:
                    kwargs["newline"] = "\r\n"
            return original_open(path, mode, *args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normal = build_release(root/"normal", records, get_ontology(), {})
            with patch.object(Path, "open", windows_open):
                windows = build_release(root/"windows", records, get_ontology(), {})
            self.assertEqual(verify_release(normal), verify_release(windows))
            for relative in verify_release(normal)["files"]:
                self.assertEqual((normal/relative).read_bytes(), (windows/relative).read_bytes(), relative)

    def test_sqlite_uses_canonical_windows_drive_uri(self):
        from oopc.graph import Graph
        graph = Graph.__new__(Graph)
        graph.path = PureWindowsPath("C:/Polymer data #1/µ")
        with patch("oopc.graph.sqlite3.connect") as connect:
            with graph.db():
                pass
        self.assertEqual(connect.call_args.args, ("file:///C:/Polymer%20data%20%231/%C2%B5/graph.sqlite?mode=ro",))
        self.assertTrue(connect.call_args.kwargs["uri"])

    def test_read_only_graph_with_non_ascii_and_reserved_url_characters(self):
        import sqlite3
        from oopc.graph import Graph
        from oopc.release import build_release
        from oopc.vocabulary import get_ontology
        with tempfile.TemporaryDirectory() as temporary:
            # '?' is not a valid Windows file-name character; URI escaping of
            # spaces, '#' and Unicode must work on all supported platforms.
            release = build_release(Path(temporary)/"polymer data #µ", [{"@id":"wop-000001", "@type":"PolymerConcept", "label":"µ polymer", "status":"seed", "layer":"science"}], get_ontology(), {})
            graph = Graph(release)
            self.assertEqual(graph.get("wop-000001")["label"], "µ polymer")
            with graph.db() as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM records")
