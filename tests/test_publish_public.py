"""The public repository receives one commit per version and nothing from the development history."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("publish_public", Path(__file__).resolve().parents[1]/"tools/publish_public.py")
publish_public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_public)

IDENTITY = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


class PublishPublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dev, self.public = Path(self.temp.name)/"dev", Path(self.temp.name)/"public.git"
        patcher = mock.patch.dict(os.environ, IDENTITY)
        patcher.start()
        self.addCleanup(patcher.stop)
        git(self.temp.name, "init", "-q", "--bare", str(self.public))
        git(self.temp.name, "init", "-q", "-b", "main", str(self.dev))
        self.write({"config/public-files.json": json.dumps({"internal": ["docs/exec-plans/"]}),
                    "oopc/__init__.py": '__version__ = "1.0.0"\n', "README.md": "first\n",
                    "docs/exec-plans/plan.md": "PRIVATE-PLAN\n", ".claude/launch.json": "{}\n"})
        self.write({"README.md": "second\n"})

    def tearDown(self):
        self.temp.cleanup()

    def write(self, files):
        for name, text in files.items():
            (self.dev/name).parent.mkdir(parents=True, exist_ok=True)
            (self.dev/name).write_text(text)
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", "development commit")
        return git(self.dev, "rev-parse", "HEAD")

    def publish(self, **options):
        return publish_public.publish(self.dev, to=str(self.public), **options)

    def test_dry_run_pushes_nothing(self):
        plan = self.publish()
        self.assertFalse(plan["published"])
        self.assertEqual(plan["excluded"], ["docs/exec-plans/", ".claude/"])
        self.assertEqual(git(self.public, "for-each-ref"), "")

    def test_versions_arrive_as_single_commits_without_history_or_internal_files(self):
        first = self.publish(push=True, tag="v1.0.0", tag_message="First version")
        self.assertTrue(first["published"])
        self.assertEqual(git(self.public, "ls-tree", "-r", "--name-only", "main").split(),
                         ["README.md", "config/public-files.json", "oopc/__init__.py"])
        self.assertEqual(git(self.public, "rev-list", "--count", "main"), "1")
        self.assertIn("Development-revision: " + first["revision"], git(self.public, "log", "-1", "--format=%B", "main"))
        self.assertEqual(git(self.public, "tag", "-l", "--format=%(contents)", "v1.0.0"), "First version")
        plan = git(self.dev, "rev-parse", "main:docs/exec-plans/plan.md")
        for name in git(self.dev, "rev-list", "main").split() + [plan]:  # No development commit or plan reached it.
            self.assertNotEqual(subprocess.run(["git", "cat-file", "-e", name], cwd=self.public).returncode, 0)

        self.assertFalse(self.publish(push=True)["published"])  # Nothing new: refused.
        self.write({"docs/exec-plans/plan.md": "PRIVATE-PLAN, revised\n"})
        self.assertFalse(self.publish(push=True)["published"])  # Only internal files changed.
        self.write({"README.md": "third\n"})
        second = self.publish(push=True, message="oopc 1.0.1\n\nCo-Authored-By: Fixture <fixture@example.invalid>")
        self.assertEqual(git(self.public, "rev-list", "main").split(), [second["commit"], first["commit"]])
        self.assertTrue(git(self.public, "log", "-1", "--format=%B", "main").rstrip().endswith(
            "Co-Authored-By: Fixture <fixture@example.invalid>\nDevelopment-revision: " + second["revision"]))
        with self.assertRaisesRegex(ValueError, "already has tag"):
            self.write({"README.md": "fourth\n"})
            self.publish(push=True, tag="v1.0.0")

    def test_home_directory_is_refused(self):
        self.write({"notes.txt": "see " + str(Path.home()) + "/data\n"})
        with self.assertRaisesRegex(ValueError, "home directory"):
            self.publish(push=True)
        self.assertEqual(git(self.public, "for-each-ref"), "")


if __name__ == "__main__":
    unittest.main()
