"""The about page: its figure is described for screen readers, its seed numbers are current, and the page ships."""
import fnmatch
import importlib.util
import json
import re
import sqlite3
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "oopc" / "web"
PAGE_FILES = ["about.html", "about.css", "about.js"]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Figure(HTMLParser):
    """The loop figure's svg and the text of its title and description."""

    def __init__(self):
        super().__init__()
        self.svg, self.inside, self.text = None, None, {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "svg" and attrs.get("id") == "loop-art":
            self.svg = attrs
        if self.svg and tag in ("title", "desc"):
            self.inside = attrs.get("id")

    def handle_endtag(self, tag):
        if tag in ("title", "desc"):
            self.inside = None

    def handle_data(self, data):
        if self.inside:
            self.text[self.inside] = self.text.get(self.inside, "") + data


class AboutPageTests(unittest.TestCase):
    def test_the_animated_figure_is_named_and_described(self):
        figure = Figure()
        figure.feed((WEB / "about.html").read_text(encoding="utf-8"))
        self.assertIsNotNone(figure.svg, "about.html holds the loop figure")
        self.assertEqual(figure.svg.get("role"), "img")
        for label in figure.svg["aria-labelledby"].split():
            self.assertTrue(figure.text.get(label, "").strip(), f"#{label} names or describes the figure")

    def test_page_ships_with_the_package_and_release(self):
        package_data = json.loads(re.search(r"^oopc = (\[.*\])$", (ROOT / "pyproject.toml").read_text(), re.M).group(1))
        assets = load_tool("check_distribution").ASSETS
        public = set(json.loads((ROOT / "config/public-files.json").read_text())["files"])
        for name in PAGE_FILES:
            with self.subTest(file=name):
                self.assertTrue(any(fnmatch.fnmatch(f"web/{name}", pattern) for pattern in package_data))
                self.assertIn(f"web/{name}", assets)
                self.assertIn(f"oopc/web/{name}", public)
        self.assertIn('href="/about.html"', (WEB / "index.html").read_text(encoding="utf-8"))

    def test_seed_numbers_match_the_current_release(self):
        pointer = ROOT / "releases" / "current.json"
        if not pointer.is_file():
            self.skipTest("No seed release in this checkout")
        release = ROOT / "releases" / json.loads(pointer.read_text())["release_id"] / "graph.sqlite"
        with sqlite3.connect(f"file:{release}?mode=ro", uri=True) as db:
            families = db.execute("SELECT count(*) FROM records WHERE type = 'PolymerConcept'").fetchone()[0]
            structures = db.execute("SELECT count(*) FROM records WHERE type = 'Structure'").fetchone()[0]
            records = db.execute("SELECT count(*) FROM records").fetchone()[0]
        html = (WEB / "about.html").read_text(encoding="utf-8")
        for stated in (f"{families} polymer families", f"{structures} chemical structures", f"{records:,} records"):
            self.assertIn(stated, html)


if __name__ == "__main__":
    unittest.main()
