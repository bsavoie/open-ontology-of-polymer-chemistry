"""Public archives admit reviewed paths and preserve an existing download on failure."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from oopc.release import build_release
from oopc.util import atomic_json, digest
from oopc.vocabulary import get_ontology

spec = importlib.util.spec_from_file_location("package_release", Path(__file__).resolve().parents[1]/"tools/package_release.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class ShippingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/"config").mkdir()
        (self.root/"oopc").mkdir()
        (self.root/"oopc/public.py").write_text("# public fixture\n")
        self.paths = ["config/public-files.json", "oopc/public.py"]
        self.allow(self.paths)
        self.release = build_release(self.root/"releases/fixture", [{"@id":"wop-000001", "@type":"PolymerConcept", "label":"Fixture", "status":"seed", "layer":"science"}], get_ontology(), {})
        atomic_json(self.root/"releases/current.json", {"release_id":"fixture"})

    def tearDown(self):
        self.temp.cleanup()

    def allow(self, paths):
        atomic_json(self.root/"config/public-files.json", {"format":"oopc-public-files-v1", "files":paths})

    def test_private_files_and_misplaced_audit_are_excluded_and_hashes_match(self):
        for name in (".oopc/audit-vault/answers.json", "benchmarks/audit.json", "examples/source.pdf", "oopc/source-download.json", "docs/private-notes.md"):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("PRIVATE-SENTINEL")
        result = packaging.build_bundle(self.root)
        with zipfile.ZipFile(result["path"]) as bundle:
            prefix = bundle.namelist()[0].split("/")[0]+"/"
            manifest = json.loads(bundle.read(prefix+"BUNDLE-MANIFEST.json"))
            self.assertFalse(manifest["privateTracesIncluded"])
            for name, checksum in manifest["files"].items():
                data = bundle.read(prefix+name)
                self.assertEqual(digest(data), checksum)
                self.assertNotIn(b"PRIVATE-SENTINEL", data)
            self.assertEqual(set(bundle.namelist()), {prefix+name for name in manifest["files"]}|{prefix+"BUNDLE-MANIFEST.json"})
        repeated = packaging.build_bundle(self.root)
        self.assertEqual(result["sha256"], repeated["sha256"])

    def test_failed_member_does_not_replace_previous_download(self):
        result = packaging.build_bundle(self.root)
        original = Path(result["path"]).read_bytes()
        self.allow(self.paths+["missing.txt"])
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            packaging.build_bundle(self.root)
        self.assertEqual(Path(result["path"]).read_bytes(), original)

    def test_symlink_file_and_directory_are_rejected(self):
        target = self.root/"private-secret.txt"
        target.write_text("PRIVATE")
        (self.root/"oopc/linked.py").symlink_to(target)
        self.allow(self.paths+["oopc/linked.py"])
        with self.assertRaisesRegex(ValueError, "symlinks"):
            packaging.collect_members(self.root)
        (self.root/"linked").symlink_to(self.root/"oopc", target_is_directory=True)
        self.allow(self.paths+["linked/public.py"])
        with self.assertRaisesRegex(ValueError, "symlinks"):
            packaging.collect_members(self.root)

    def test_unsafe_allowlist_is_rejected(self):
        for member in ("../secret", "/tmp/secret", ".oopc/run.json", "oopc\\secret", "oopc//public.py", "private/secret"):
            with self.subTest(member=member):
                self.allow(self.paths+[member])
                with self.assertRaises(ValueError):
                    packaging.collect_members(self.root)

    def test_public_manifest_covers_runtime_modules_and_actual_assets(self):
        root = Path(__file__).resolve().parents[1]
        selected = set(json.loads((root/"config/public-files.json").read_text())["files"])
        runtime = {str(path.relative_to(root)).replace("\\", "/") for path in (root/"oopc").rglob("*.py")}
        self.assertFalse(runtime-selected, "Register new runtime modules in config/public-files.json")
        for name in ("oopc/web/index.html", "oopc/web/researcher.js", "oopc/web/researcher.css", "oopc/web/operator.html",
                     "oopc/web/app.js", "oopc/web/style.css", "oopc/web/vendor/cytoscape.min.js", "oopc/web/vendor/cytoscape.LICENSE",
                     "oopc/web/vendor/openchemlib.js", "oopc/web/vendor/openchemlib.LICENSE"):
            self.assertIn(name, selected)
            self.assertGreater((root/name).stat().st_size, 0)


    def test_every_doc_is_shipped_or_internal_and_shipped_docs_link_only_to_shipped_files(self):
        import re
        root = Path(__file__).resolve().parents[1]
        selection = json.loads((root/"config/public-files.json").read_text())
        shipped, internal = set(selection["files"]), selection.get("internal", [])
        is_internal = lambda name: any(name == item or (item.endswith("/") and name.startswith(item)) for item in internal)
        for path in (root/"docs").rglob("*.md"):
            name = path.relative_to(root).as_posix()
            with self.subTest(doc=name):
                self.assertTrue((name in shipped) != is_internal(name),
                    "List each doc once: in files if the loop needs it, else under internal")
        for name in sorted(item for item in shipped if item.endswith(".md")):
            for target in re.findall(r"\]\(([^)\s]+)\)", (root/name).read_text(encoding="utf-8")):
                target = target.split("#")[0]
                if not target or re.match(r"^[a-z]+:", target):
                    continue
                resolved = (root/name).parent.joinpath(target).resolve().relative_to(root).as_posix()
                with self.subTest(doc=name, link=target):
                    self.assertTrue(resolved in shipped or any(item.startswith(resolved.rstrip("/") + "/") for item in shipped),
                                    "A shipped doc links to a file that is not shipped")
