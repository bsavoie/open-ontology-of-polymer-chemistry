"""A retained lexical layout never retains filesystem or release authority."""
import asyncio
from contextvars import copy_context
import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oopc import release as releases
from oopc import release_verification as cache
from oopc.vocabulary import get_ontology
from tests import test_fingerprint_parent_reuse as legacy


class FingerprintLayoutReuseTests(unittest.TestCase):
    def setUp(self):
        if os.name != "posix":
            self.skipTest("The optimized layout is explicitly POSIX-only")
        temporary = tempfile.TemporaryDirectory(prefix="oopc-layout-regression-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.release = self.root / "work" / "release"
        records = [{"@id": "wop-%06d" % index, "@type": "PolymerConcept", "label": "Synthetic %d" % index,
                    "status": "seed", "layer": "science"} for index in (1, 2)]
        releases.build_release(self.release, records, get_ontology(), {})
        self.manifest = releases.verify_release(self.release)
        # Additional checksum-bound files exercise shared and nested parents.
        # Their bytes and their manifest entries pass the real public verifier.
        for name in ("nested/alpha.json", "nested/beta.json", "nested/deeper/gamma.json"):
            path = self.release / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps({"fixture": name}).encode()
            path.write_bytes(raw)
            self.manifest["files"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self.write_manifest(self.manifest)
        self.assertEqual(releases.verify_release(self.release), self.manifest)

    def write_manifest(self, manifest):
        (self.release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def layout(self):
        value = cache._fingerprint_layout(self.release, self.manifest)
        self.assertIsNotNone(value)
        return value

    def equal_original(self, layout, path=None, manifest=None):
        path = self.release if path is None else path
        manifest = self.manifest if manifest is None else manifest
        expected = legacy.original_fingerprint(path, manifest)
        self.assertEqual(cache._fingerprint_with_layout(path, manifest, layout), expected)
        return expected

    def test_reused_layout_preserves_tuple_and_every_dynamic_check(self):
        layout = self.layout()
        expected = self.equal_original(layout)
        identity, lstat, resolve = cache._identity, Path.lstat, Path.resolve
        with patch.object(cache, "_fingerprint", wraps=cache._fingerprint) as fallback:
            with patch.object(cache, "_identity", wraps=identity) as identities, \
                 patch.object(Path, "lstat", autospec=True, side_effect=lstat) as stated, \
                 patch.object(Path, "resolve", autospec=True, side_effect=resolve) as resolved:
                for index in range(2):
                    self.assertEqual(cache._fingerprint_with_layout(self.release, self.manifest, layout), expected)
                    calls = (list(identities.call_args_list), list(stated.call_args_list), list(resolved.call_args_list))
                    if index == 0:
                        first = calls
                    else:
                        self.assertEqual(calls, first)
                    identities.reset_mock(); stated.reset_mock(); resolved.reset_mock()
            self.assertEqual(fallback.call_count, 0)
        self.assertEqual(len(first[0]), sum(map(len, expected)))
        files = [Path(name) for name, _ in expected[0]]
        for file in files:
            self.assertGreaterEqual(sum(call.args[0] == file for call in first[1]), 2)
        self.assertEqual(len(first[2]), len({file.parent for file in files}))

    def test_warm_snapshot_builds_layout_once_and_keeps_it_frozen(self):
        builder = cache._fingerprint_layout
        with patch.object(cache, "_fingerprint_layout", wraps=builder) as built:
            with cache.release_verification_scope():
                releases.verify_release(self.release)
                snapshot = cache._state().snapshots[self.release]
                layout = snapshot.layout
                self.assertIsNotNone(layout)
                before = built.call_count
                with patch.object(cache, "_fingerprint_with_layout", wraps=cache._fingerprint_with_layout) as used:
                    self.assertEqual(releases.verify_release(self.release), self.manifest)
                    self.assertEqual(releases.verify_release(self.release), self.manifest)
                    self.assertEqual(used.call_count, 2)
                self.assertEqual(built.call_count, before)
                self.assertIs(cache._state().snapshots[self.release].layout, layout)
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(layout, dataclasses.fields(layout)[0].name, None)
            with cache.release_verification_scope():
                releases.verify_release(self.release)
                self.assertIsNot(cache._state().snapshots[self.release].layout, layout)
                self.assertGreater(built.call_count, before)

    def test_262_concept_long_root_uses_layout_with_all_fresh_checks(self):
        # The retained standard fixture has an ordinary 116-character release
        # root. Match its path depth as well as length: both affect the bounded
        # metadata allowance, independently of source-record byte size.
        parent = self.root / "fixture" / "workspace"
        padding = 116 - len(str(parent / "release")) - 1
        if padding <= 0:
            self.skipTest("Fixture needs a temporary root short enough for a 116-character canonical release path")
        release = parent / ("r" * padding) / "release"
        self.assertEqual(len(str(release)), 116)
        records = [{"@id": "wop-%06d" % index, "@type": "PolymerConcept",
                    "label": "Synthetic family %d" % index, "status": "seed", "layer": "science"}
                   for index in range(1, 263)]
        releases.build_release(release, records, get_ontology(), {})
        manifest = releases.verify_release(release)
        expected = legacy.original_fingerprint(release, manifest)
        with patch.object(cache, "MAX_FINGERPRINT_LAYOUT_BYTES", 1024 * 1024):
            with cache.release_verification_scope():
                self.assertEqual(releases.verify_release(release), manifest)
                self.assertIsNone(cache._state().snapshots[release].layout)
                self.assertEqual(releases.verify_release(release), manifest)
        with cache.release_verification_scope():
            self.assertEqual(releases.verify_release(release), manifest)
            layout = cache._state().snapshots[release].layout
            self.assertIsNotNone(layout)
            self.assertGreater(layout.metadata_bytes, 1024 * 1024)
            self.assertLessEqual(layout.metadata_bytes, 2 * 1024 * 1024)
            identity, lstat, resolve = cache._identity, Path.lstat, Path.resolve
            with patch.object(cache, "_fingerprint", wraps=cache._fingerprint) as fallback, \
                 patch.object(cache, "_fingerprint_layout", wraps=cache._fingerprint_layout) as rebuilt, \
                 patch.object(cache, "_identity", wraps=identity) as identities, \
                 patch.object(Path, "lstat", autospec=True, side_effect=lstat) as stated, \
                 patch.object(Path, "resolve", autospec=True, side_effect=resolve) as resolved:
                for index in range(2):
                    self.assertEqual(releases.verify_release(release), manifest)
                    checks = (list(identities.call_args_list), list(stated.call_args_list), list(resolved.call_args_list))
                    if index == 0:
                        first = checks
                    else:
                        self.assertEqual(checks, first)
                    identities.reset_mock(); stated.reset_mock(); resolved.reset_mock()
                self.assertEqual(fallback.call_count, 0)
                self.assertEqual(rebuilt.call_count, 0)
            self.assertEqual(len(first[0]), sum(map(len, expected)))
            for name, _ in expected[0]:
                self.assertGreaterEqual(sum(call.args[0] == Path(name) for call in first[1]), 2)
            self.assertEqual(len(first[2]), len({Path(name).parent for name, _ in expected[0]}))
            self.assertEqual(cache._fingerprint_with_layout(release, manifest, layout), expected)

    def test_content_mode_inode_and_hardlink_changes_remain_visible(self):
        path = self.release / "records.jsonl"
        layout = self.layout()
        before = self.equal_original(layout)
        original = path.read_bytes()
        info = path.stat()
        path.write_bytes(original.replace(b"Synthetic 1", b"Synthetic X"))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        after = self.equal_original(layout)
        self.assertNotEqual(before, after)
        path.write_bytes(original)
        for change in ("mode", "inode", "hardlink"):
            with self.subTest(change=change), cache.release_verification_scope():
                releases.verify_release(self.release)
                layout = cache._state().snapshots[self.release].layout
                before = self.equal_original(layout)
                if change == "mode":
                    path.chmod(path.stat().st_mode ^ 0o020)
                elif change == "inode":
                    replacement = path.with_name("replacement")
                    shutil.copy2(path, replacement)
                    replacement.replace(path)
                else:
                    os.link(path, self.root / "hardlink")
                self.assertNotEqual(self.equal_original(layout), before)
                with patch.object(releases, "_verify_release_data", wraps=releases._verify_release_data) as full:
                    self.assertEqual(releases.verify_release(self.release), self.manifest)
                    self.assertEqual(full.call_count, 1)

    def test_cached_public_release_cannot_hide_tampered_bytes_or_file_symlink(self):
        path = self.release / "records.jsonl"
        raw = path.read_bytes()
        with cache.release_verification_scope():
            releases.verify_release(self.release)
            self.assertIsNotNone(cache._state().snapshots[self.release].layout)
            info = path.stat()
            path.write_bytes(raw.replace(b"Synthetic 1", b"Synthetic X"))
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, "checksum"):
                releases.verify_release(self.release)
            self.assertFalse(cache._state().snapshots)
            path.write_bytes(raw)
            releases.verify_release(self.release)
            target = self.root / "source-original.jsonl"
            path.rename(target); path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                releases.verify_release(self.release)
            self.assertFalse(cache._state().snapshots)

    def test_ancestor_identity_and_new_symlink_retarget_use_fresh_filesystem_state(self):
        layout = self.layout()
        before = self.equal_original(layout)
        self.release.parent.chmod(self.release.parent.stat().st_mode ^ 0o020)
        after = self.equal_original(layout)
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        saved = self.root / "saved-work"
        self.release.parent.rename(saved)
        self.release.parent.mkdir()
        (saved / "release").rename(self.release)
        replaced = self.equal_original(layout)
        self.assertEqual(after[0], replaced[0])
        self.assertNotEqual(after[1], replaced[1])
        first, second = self.root / "first-target", self.root / "second-target"
        shutil.copytree(self.release / "nested", first)
        shutil.copytree(self.release / "nested", second)
        (second / "alpha.json").write_text('{"changed":"target"}', encoding="utf-8")
        shutil.rmtree(self.release / "nested")
        (self.release / "nested").symlink_to(first, target_is_directory=True)
        with patch.object(cache, "_fingerprint", wraps=cache._fingerprint) as fallback:
            with self.assertRaises(cache.ReleaseVerificationError):
                cache._fingerprint_with_layout(self.release, self.manifest, layout)
            first_value = self.equal_original(None)
            (self.release / "nested").unlink()
            (self.release / "nested").symlink_to(second, target_is_directory=True)
            with self.assertRaises(cache.ReleaseVerificationError):
                cache._fingerprint_with_layout(self.release, self.manifest, layout)
            second_value = self.equal_original(None)
            self.assertEqual(fallback.call_count, 2)
        self.assertNotEqual(first_value, second_value)
        self.assertIn(str(second / "alpha.json"), {name for name, _ in second_value[0]})

    def test_file_symlink_switch_falls_back_with_exact_target_and_rejection_errors(self):
        layout = self.layout()
        path = self.release / "nested/alpha.json"
        target = self.root / "outside.json"
        path.rename(target); path.symlink_to(target)
        with patch.object(cache, "_fingerprint", wraps=cache._fingerprint) as fallback:
            with self.assertRaises(cache.ReleaseVerificationError):
                cache._fingerprint_with_layout(self.release, self.manifest, layout)
            value = self.equal_original(None)
            self.assertEqual(fallback.call_count, 1)
        self.assertIn(str(target), {name for name, _ in value[0]})
        target.unlink()
        errors = []
        for method in (legacy.original_fingerprint,
                       lambda p, m: cache._fingerprint_with_layout(p, m, None)):
            with self.assertRaises(FileNotFoundError) as error:
                method(self.release, self.manifest)
            errors.append(str(error.exception))
        self.assertEqual(*errors)

    def test_observed_transient_symlink_forces_full_reverification_after_restoration(self):
        path = self.release / "records.jsonl"
        target = self.root / "temporarily-moved-records.jsonl"
        lstat = Path.lstat
        with cache.release_verification_scope():
            releases.verify_release(self.release)
            previous = cache._state().snapshots[self.release]
            self.assertIsNotNone(previous.layout)
            path.rename(target); path.symlink_to(target)
            observed = []
            def restore_after_observation(file, *args, **kwargs):
                info = lstat(file, *args, **kwargs)
                if file == path and stat.S_ISLNK(info.st_mode):
                    observed.append(True)
                    path.unlink(); target.rename(path)
                return info
            with patch.object(Path, "lstat", autospec=True, side_effect=restore_after_observation), \
                 patch.object(releases, "_verify_release_data", wraps=releases._verify_release_data) as full:
                self.assertEqual(releases.verify_release(self.release), self.manifest)
                self.assertEqual(observed, [True])
                self.assertEqual(full.call_count, 1)
            self.assertIsNot(cache._state().snapshots[self.release], previous)

    def test_manifest_spelling_order_names_and_metadata_never_reuse_wrong_layout(self):
        layout = self.layout()
        reordered = copy.deepcopy(self.manifest)
        reordered["files"] = dict(reversed(list(reordered["files"].items())))
        changed_names = copy.deepcopy(self.manifest)
        changed_names["files"]["extra.json"] = {}
        (self.release / "extra.json").write_text("fixture", encoding="utf-8")
        aliased = copy.deepcopy(self.manifest)
        aliased["files"]["nested//alpha.json"] = aliased["files"].pop("nested/alpha.json")
        for manifest in (reordered, changed_names, aliased):
            with self.subTest(names=list(manifest["files"])), \
                 patch.object(cache, "_fingerprint", wraps=cache._fingerprint) as fallback:
                self.equal_original(layout, manifest=manifest)
                self.assertEqual(fallback.call_count, 1)
        self.assertIsNone(cache._fingerprint_layout(self.release, aliased))
        with cache.release_verification_scope():
            releases.verify_release(self.release)
            path = self.release / "manifest.json"
            path.write_bytes(path.read_bytes() + b"\n")
            with patch.object(releases, "_verify_release_data", wraps=releases._verify_release_data) as full:
                self.assertEqual(releases.verify_release(self.release), self.manifest)
                self.assertEqual(full.call_count, 1)
            changed = copy.deepcopy(self.manifest)
            changed["record_count"] += 1
            self.write_manifest(changed)
            with self.assertRaisesRegex(ValueError, "record count"):
                releases.verify_release(self.release)
            self.assertFalse(cache._state().snapshots)

    def test_unsupported_lexical_paths_preserve_original_outputs_and_errors(self):
        relative = Path(os.path.relpath(self.release, Path.cwd()))
        for path in (relative, self.release.parent / ".." / "work" / "release"):
            with self.subTest(path=path):
                self.assertIsNone(cache._fingerprint_layout(path, self.manifest))
                self.equal_original(self.layout(), path=path)
        for name in ("../escape", str(self.root / "absolute"), "missing.json"):
            manifest = {"files": {name: {}}}
            errors = []
            for method in (legacy.original_fingerprint,
                           lambda p, m: cache._fingerprint_with_layout(p, m, self.layout())):
                try:
                    method(self.release, manifest)
                except (ValueError, OSError) as error:
                    errors.append((type(error), str(error)))
                else:
                    self.fail("Expected original fingerprint rejection")
            self.assertEqual(errors[0], errors[1])

    def test_each_layout_cap_falls_back_without_rejecting_a_valid_release(self):
        expected = legacy.original_fingerprint(self.release, self.manifest)
        for setting in ("MAX_FINGERPRINT_LAYOUT_FILES", "MAX_FINGERPRINT_LAYOUT_PATHS",
                        "MAX_FINGERPRINT_LAYOUT_BYTES"):
            with self.subTest(setting=setting), patch.object(cache, setting, 1):
                self.assertIsNone(cache._fingerprint_layout(self.release, self.manifest))
                with cache.release_verification_scope():
                    self.assertEqual(releases.verify_release(self.release), self.manifest)
                    self.assertIsNone(cache._state().snapshots[self.release].layout)
                    self.assertEqual(releases.verify_release(self.release), self.manifest)
                    self.assertEqual(cache._fingerprint_with_layout(self.release, self.manifest, None), expected)

    def test_exact_file_path_and_declared_metadata_limits_are_inclusive(self):
        layout = self.layout()
        original = legacy.original_fingerprint(self.release, self.manifest)
        required = {
            "MAX_FINGERPRINT_LAYOUT_FILES": len(set(self.manifest["files"]) | {"manifest.json"}),
            "MAX_FINGERPRINT_LAYOUT_PATHS": sum(map(len, original)),
            "MAX_FINGERPRINT_LAYOUT_BYTES": layout.metadata_bytes,
        }
        for setting, boundary in required.items():
            for limit, retained in ((boundary, True), (boundary - 1, False)):
                with self.subTest(setting=setting, limit=limit), patch.object(cache, setting, limit):
                    actual = cache._fingerprint_layout(self.release, self.manifest)
                    self.assertEqual(actual is not None, retained)
                    if retained:
                        self.assertEqual(actual, layout)
                    self.assertEqual(cache._fingerprint_with_layout(self.release, self.manifest, actual), original)
                    with cache.release_verification_scope():
                        self.assertEqual(releases.verify_release(self.release), self.manifest)
                        self.assertEqual(cache._state().snapshots[self.release].layout is not None, retained)
                        self.assertEqual(releases.verify_release(self.release), self.manifest)

    def test_snapshot_eviction_explicit_clear_and_scope_exit_remove_layout_owners(self):
        paths = [self.release, self.root / "second-release", self.root / "third-release"]
        for path in paths[1:]:
            shutil.copytree(self.release, path)
        with cache.release_verification_scope():
            state = cache._state()
            for path in paths[:2]:
                releases.verify_release(path)
            self.assertEqual(len(state.snapshots), 2)
            self.assertTrue(all(snapshot.layout is not None for snapshot in state.snapshots.values()))
            self.assertTrue(all(snapshot.layout.metadata_bytes <= cache.MAX_FINGERPRINT_LAYOUT_BYTES
                                for snapshot in state.snapshots.values()))
            self.assertLessEqual(sum(snapshot.layout.metadata_bytes for snapshot in state.snapshots.values()),
                                 2 * cache.MAX_FINGERPRINT_LAYOUT_BYTES)
            first = state.snapshots[paths[0]].layout
            releases.verify_release(paths[2])
            self.assertEqual(set(state.snapshots), set(paths[1:]))
            releases.verify_release(paths[0])
            self.assertIsNot(state.snapshots[paths[0]].layout, first)
            self.assertLessEqual(len(state.snapshots), 2)
            cache.clear_release_verification_cache()
            self.assertFalse(state.snapshots)
            self.assertEqual(state.snapshot_bytes, 0)
            releases.verify_release(paths[0])
            inherited = copy_context()
        self.assertFalse(state.snapshots)
        self.assertFalse(state.active)
        self.assertIsNone(inherited.run(cache._state))
        with cache.release_verification_scope(), patch.object(cache, "MAX_SOURCE_BYTES", 1):
            self.assertEqual(releases.verify_release(self.release), self.manifest)
            self.assertFalse(cache._state().snapshots)

    def test_copied_thread_context_cannot_reuse_parent_layout(self):
        observations, failures = [], []
        with cache.release_verification_scope():
            releases.verify_release(self.release)
            parent_state = cache._state()
            parent_layout = parent_state.snapshots[self.release].layout
            inherited = copy_context()
            def child():
                try:
                    self.assertIsNone(cache._state())
                    with cache.release_verification_scope():
                        releases.verify_release(self.release)
                        observations.append(cache._state().snapshots[self.release].layout)
                        self.assertIsNot(cache._state(), parent_state)
                except BaseException as error:
                    failures.append(error)
            thread = threading.Thread(target=lambda: inherited.run(child))
            thread.start(); thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertFalse(failures)
            self.assertEqual(len(observations), 1)
            self.assertIsNot(observations[0], parent_layout)
            self.assertIs(parent_state.snapshots[self.release].layout, parent_layout)

    def test_child_async_task_cannot_reuse_parent_layout(self):
        async def run():
            with cache.release_verification_scope():
                releases.verify_release(self.release)
                parent = cache._state().snapshots[self.release].layout
                async def child():
                    self.assertIsNone(cache._state())
                    with cache.release_verification_scope():
                        releases.verify_release(self.release)
                        child_layout = cache._state().snapshots[self.release].layout
                        self.assertIsNot(child_layout, parent)
                        self.assertEqual(releases.verify_release(self.release), self.manifest)
                await asyncio.create_task(child())
                self.assertIs(cache._state().snapshots[self.release].layout, parent)
        asyncio.run(run())


class FingerprintLayoutWindowsFallbackTests(unittest.TestCase):
    def test_case_aliases_reordered_keys_and_root_keep_literal_windows_oracle(self):
        names = {"nested/a.json": {}, "NESTED/b.json": {}, "Nested/./c.json": {}}
        manifests = [{"files": names}, {"files": dict(reversed(list(names.items())))}, {"files": {"": {}}}]
        def resolve(path, *, strict):
            self.assertTrue(strict)
            return PureWindowsPath(str(path).lower())
        for root in (PureWindowsPath("C:/Release"), PureWindowsPath("C:/"), PureWindowsPath(".")):
            for manifest in manifests:
                with self.subTest(root=root, manifest=manifest), \
                     patch.object(cache, "Path", PureWindowsPath), patch.object(legacy, "Path", PureWindowsPath), \
                     patch.object(PureWindowsPath, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG), create=True), \
                     patch.object(PureWindowsPath, "resolve", resolve, create=True), \
                     patch.object(cache, "_identity", side_effect=lambda path, *, content: (str(path).lower(), content)):
                    self.assertIsNone(cache._fingerprint_layout(root, manifest))
                    self.assertEqual(cache._fingerprint_with_layout(root, manifest, None),
                                     legacy.original_fingerprint(root, manifest))


if __name__ == "__main__":
    unittest.main()
