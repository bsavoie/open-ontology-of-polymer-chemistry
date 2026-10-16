"""One fingerprint may share ancestor expansion, never filesystem authority."""
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oopc import release as releases
from oopc import release_verification as cache
from oopc.vocabulary import get_ontology


def original_fingerprint(path, manifest):
    """Literal pre-optimization algorithm; independent of the changed helper."""
    names = set(manifest["files"]) | {"manifest.json"}
    files, parents, resolved_parents = set(), set(), {}
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe release fingerprint path: " + name)
        file = path / relative
        if stat.S_ISLNK(file.lstat().st_mode):
            resolved = file.resolve(strict=True)
        else:
            parent = file.parent
            if parent not in resolved_parents:
                resolved_parents[parent] = parent.resolve(strict=True)
            resolved = resolved_parents[parent] / file.name
        files.update((file, resolved))
        parents.update(file.parents)
        parents.update(resolved.parents)
    return (tuple((str(file), cache._identity(file, content=True)) for file in sorted(files)),
            tuple((str(parent), cache._identity(parent, content=False)) for parent in sorted(parents)))


class FingerprintParentReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="oopc-fingerprint-parent-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.release = self.root / "work" / "release"
        self.manifest = self.make_files(self.release, ["records.jsonl", "ontology.json",
            "nested/alpha.json", "nested/beta.json", "nested/deeper/gamma.json"])

    @staticmethod
    def make_files(root, names):
        for name in [*names, "manifest.json"]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Synthetic fingerprint fixture: " + name, encoding="utf-8")
        return {"files": {name: {} for name in names}}

    def equal_original(self, path=None, manifest=None):
        path = self.release if path is None else path
        manifest = self.manifest if manifest is None else manifest
        expected = original_fingerprint(path, manifest)
        self.assertEqual(cache._fingerprint(path, manifest), expected)
        return expected

    def test_shared_and_nested_parents_keep_exact_ordered_output(self):
        value = self.equal_original()
        self.assertEqual([row[0] for row in value[0]], sorted(row[0] for row in value[0]))
        self.assertEqual([row[0] for row in value[1]], sorted(row[0] for row in value[1]))
        self.assertEqual(len(value[0]), 6)
        parent_names = {row[0] for row in value[1]}
        self.assertIn(str(self.release / "nested" / "deeper"), parent_names)
        self.assertIn(str(self.release), parent_names)

    def test_relative_lexical_and_resolved_paths_remain_distinct(self):
        relative = Path(os.path.relpath(self.release, Path.cwd()))
        expected = self.equal_original(relative)
        file_names = {row[0] for row in expected[0]}
        self.assertIn(str(relative / "records.jsonl"), file_names)
        self.assertIn(str(self.release / "records.jsonl"), file_names)
        self.assertNotEqual(expected, self.equal_original(self.release))

    def test_file_and_ancestor_symlinks_retain_both_identities(self):
        target = self.root / "outside" / "target.json"
        target.parent.mkdir()
        target.write_text("Synthetic target", encoding="utf-8")
        (self.release / "linked.json").symlink_to(target)
        manifest = {"files": dict(self.manifest["files"], **{"linked.json": {}})}
        link = self.root / "release-link"
        link.symlink_to(self.release, target_is_directory=True)
        value = self.equal_original(link, manifest)
        file_names = {row[0] for row in value[0]}
        self.assertIn(str(link / "linked.json"), file_names)
        self.assertIn(str(target), file_names)
        self.assertIn(str(link), {row[0] for row in value[1]})
        self.assertIn(str(target.parent), {row[0] for row in value[1]})

    def test_dotdot_after_symlink_keeps_filesystem_not_lexical_resolution(self):
        lexical = self.root / "lexical"
        actual = self.root / "actual"
        lexical.mkdir()
        (actual / "child").mkdir(parents=True)
        self.make_files(lexical / "release", list(self.manifest["files"]))
        self.make_files(actual / "release", list(self.manifest["files"]))
        (lexical / "link").symlink_to(actual / "child", target_is_directory=True)
        path = lexical / "link" / ".." / "release"
        value = self.equal_original(path)
        self.assertIn(str(actual / "release" / "records.jsonl"), {row[0] for row in value[0]})
        self.assertNotIn(str(lexical / "release" / "records.jsonl"), {row[0] for row in value[0]})
        self.assertIn(str(lexical / "link" / ".."), {row[0] for row in value[1]})

    def test_unsafe_and_missing_paths_preserve_original_rejections(self):
        cases = [({"files": {"../escape": {}}}, ValueError),
                 ({"files": {str(self.root / "absolute"): {}}}, ValueError),
                 ({"files": {"missing.json": {}}}, FileNotFoundError)]
        for manifest, error in cases:
            with self.subTest(manifest=manifest):
                with self.assertRaises(error) as before:
                    original_fingerprint(self.release, manifest)
                with self.assertRaises(error) as after:
                    cache._fingerprint(self.release, manifest)
                self.assertEqual(str(before.exception), str(after.exception))
        dangling = self.release / "dangling.json"
        dangling.symlink_to(self.root / "not-present")
        for operation in (original_fingerprint, cache._fingerprint):
            with self.assertRaises(FileNotFoundError):
                operation(self.release, {"files": {"dangling.json": {}}})

    def test_file_content_mode_inode_and_link_identity_are_fresh(self):
        path = self.release / "records.jsonl"
        previous = self.equal_original()
        path.write_bytes(path.read_bytes() + b"changed")
        current = self.equal_original()
        self.assertNotEqual(current, previous)
        previous = current
        path.chmod(path.stat().st_mode ^ 0o020)
        current = self.equal_original()
        self.assertNotEqual(current, previous)
        previous = current
        replacement = path.with_name("replacement")
        shutil.copy2(path, replacement)
        replacement.replace(path)
        current = self.equal_original()
        self.assertNotEqual(current, previous)
        previous = current
        os.link(path, self.root / "hardlink")
        self.assertNotEqual(self.equal_original(), previous)

    def test_ancestor_mode_and_replacement_change_without_file_identity_change(self):
        before = self.equal_original()
        work = self.release.parent
        work.chmod(work.stat().st_mode ^ 0o020)
        changed_mode = self.equal_original()
        self.assertEqual(changed_mode[0], before[0])
        self.assertNotEqual(changed_mode[1], before[1])
        saved = self.root / "saved-work"
        work.rename(saved)
        work.mkdir()
        (saved / self.release.name).rename(self.release)
        replaced = self.equal_original()
        self.assertEqual(replaced[0], changed_mode[0])
        self.assertNotEqual(replaced[1], changed_mode[1])

    def test_ancestor_symlink_retarget_is_not_hidden_between_calls(self):
        alternate = self.root / "alternate"
        shutil.copytree(self.release, alternate)
        link = self.root / "release-link"
        link.symlink_to(self.release, target_is_directory=True)
        before = self.equal_original(link)
        link.unlink()
        link.symlink_to(alternate, target_is_directory=True)
        after = self.equal_original(link)
        self.assertNotEqual(after, before)
        self.assertIn(str(alternate / "records.jsonl"), {row[0] for row in after[0]})

    def test_unrelated_sibling_changes_still_do_not_invalidate(self):
        before = self.equal_original()
        (self.release / "unlisted-dir").mkdir()
        (self.release / "unlisted-file").write_text("Not a release input", encoding="utf-8")
        self.assertEqual(self.equal_original(), before)

    def test_every_call_repeats_resolve_and_all_file_and_ancestor_identities(self):
        expected = self.equal_original()
        identities = cache._identity
        resolve = Path.resolve
        with patch.object(cache, "_identity", wraps=identities) as checked, \
             patch.object(Path, "resolve", autospec=True, side_effect=resolve) as resolved:
            with cache.release_verification_scope():
                self.assertEqual(cache._fingerprint(self.release, self.manifest), expected)
                first_checks, first_resolves = list(checked.call_args_list), list(resolved.call_args_list)
                checked.reset_mock(); resolved.reset_mock()
                self.assertEqual(cache._fingerprint(self.release, self.manifest), expected)
                self.assertEqual(checked.call_args_list, first_checks)
                self.assertEqual(resolved.call_args_list, first_resolves)
        self.assertEqual(len(first_checks), sum(map(len, expected)))
        self.assertEqual(len(first_resolves), 3)

    def test_parent_expansions_scale_with_distinct_parents_not_file_count(self):
        manifest = self.make_files(self.root / "many", [f"bucket/item-{i:03d}.json" for i in range(60)] +
                                   [f"bucket/deeper/item-{i:03d}.json" for i in range(60)])
        folder = self.root / "many"
        original_property = Path.parents
        counts = []
        results = []
        for operation in (original_fingerprint, cache._fingerprint):
            expanded = []
            def parents(path):
                expanded.append(path)
                return original_property.fget(path)
            with patch.object(Path, "parents", property(parents)):
                results.append(operation(folder, manifest))
            counts.append(len(expanded))
        self.assertEqual(results[0], results[1])
        self.assertEqual(counts, [242, 3])

    def test_windows_case_aliases_keep_original_first_spelling_and_root_semantics(self):
        # PureWindowsPath supplies Windows equality/casing semantics without
        # touching a Windows filesystem. Actual stat mutation cases are above.
        manifests = [{"files": {"nested/a.json": {}, "NESTED/b.json": {}, "Other/c.json": {}}},
                     {"files": {"Nested/Deep/a.json": {}, "nested/deep/b.json": {}, "linked.json": {}}},
                     {"files": {"": {}}}]
        def lstat(path):
            return SimpleNamespace(st_mode=stat.S_IFLNK if path.name == "linked.json" else stat.S_IFREG)
        def resolve(path, *, strict):
            self.assertTrue(strict)
            if path.name == "linked.json":
                return PureWindowsPath("D:/External/TARGET.json")
            return PureWindowsPath(str(path).lower())
        def identity(path, *, content):
            return (str(path).lower(), content)
        for root in (PureWindowsPath("C:/Release"), PureWindowsPath("C:/"), PureWindowsPath(".")):
            for manifest in manifests:
                with self.subTest(root=root, manifest=manifest), \
                     patch(__name__ + ".Path", PureWindowsPath), patch.object(cache, "Path", PureWindowsPath), \
                     patch.object(PureWindowsPath, "lstat", lstat, create=True), \
                     patch.object(PureWindowsPath, "resolve", resolve, create=True), \
                     patch.object(cache, "_identity", side_effect=identity):
                    self.assertEqual(cache._fingerprint(root, manifest), original_fingerprint(root, manifest))

    def test_public_snapshot_still_rejects_identical_bytes_behind_file_symlink(self):
        path = releases.build_release(self.root / "public", [{"@id": "wop-000001", "@type": "PolymerConcept",
            "label": "Synthetic", "status": "seed", "layer": "science"}], get_ontology(), {})
        source = path / "records.jsonl"
        target = self.root / "original-records.jsonl"
        with cache.release_verification_scope():
            releases.verify_release(path)
            shutil.copy2(source, target)
            source.unlink()
            source.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                releases.verify_release(path)


if __name__ == "__main__":
    unittest.main()
