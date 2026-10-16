"""Reject cross-platform archive escapes before the offline source build."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools.check_distribution import ASSETS, check_archives


class DistributionArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.wheel = self.root / "fixture.whl"
        self.source = self.root / "fixture.tar.gz"
        self.make_wheel()
        self.make_source()

    def make_wheel(self, extra=None):
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name in ASSETS:
                archive.writestr("oopc/" + name, "fixture")
            for name in ("LICENSE", "LICENSE-DATA", "LICENSE-CONTENT", "NOTICE"):
                archive.writestr("fixture.dist-info/licenses/" + name, "fixture")
            if extra:
                archive.writestr(extra, "untrusted")

    def make_source(self, extra=None, kind=tarfile.REGTYPE):
        with tarfile.open(self.source, "w:gz") as archive:
            content = b"fixture"
            member = tarfile.TarInfo("fixture/PKG-INFO")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
            if extra:
                member = tarfile.TarInfo(extra)
                member.type = kind
                if kind == tarfile.SYMTYPE:
                    member.linkname = "../../outside"
                archive.addfile(member)

    def test_valid_archives_identify_both_offline_build_inputs(self):
        self.assertEqual(check_archives(self.root), (self.wheel, self.source))

    def test_source_paths_cannot_escape_on_posix_or_windows(self):
        for name in ("../outside", "/outside", "C:/fixture/PKG-INFO",
                     "fixture/../../outside", "fixture\\..\\outside"):
            with self.subTest(name=name):
                self.make_source(name)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    check_archives(self.root)

    def test_unsafe_directory_or_link_cannot_enter_source_build(self):
        for name, kind in (("../outside", tarfile.DIRTYPE),
                           ("fixture/oopc/link", tarfile.SYMTYPE)):
            with self.subTest(name=name):
                self.make_source(name, kind)
                with self.assertRaises(ValueError):
                    check_archives(self.root)

    def test_wheel_rejects_windows_drive_and_backslash_paths(self):
        for name in ("C:/oopc/escape.py", "oopc\\..\\escape.py"):
            with self.subTest(name=name):
                self.make_wheel(name)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    check_archives(self.root)

    def test_windows_aliases_and_reserved_devices_are_rejected_on_every_host(self):
        for name in (".. /pyproject.toml", "fixture/oopc/schema/.. /.. /.. /escape.json",
                     "fixture/oopc/module.py.", "fixture/oopc/module.py ",
                     "fixture/oopc/ con.py", "fixture/oopc/CON.py",
                     "fixture/oopc/NUL.tar.py", "fixture/oopc/COM¹.py",
                     "fixture/oopc/bad?.py"):
            with self.subTest(name=name):
                self.make_source(name)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    check_archives(self.root)


if __name__ == "__main__":
    unittest.main()
