"""The About tab: it is a tab of the app, its figures are described for screen readers, its seed numbers are
current, and its files ship."""
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
PAGE_FILES = ["about.css", "about.js"]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def about_template():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<template id="about-view">(.*?)</template>', html, re.S)
    assert match, "index.html holds the About tab's template"
    return match.group(1)


class Figures(HTMLParser):
    """Each svg figure's attributes and the text of the elements its aria-labelledby names."""

    def __init__(self):
        super().__init__()
        self.svgs, self.inside, self.text = [], None, {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "svg":
            self.svgs.append(attrs)
        if tag in ("title", "desc"):
            self.inside = attrs.get("id")

    def handle_endtag(self, tag):
        if tag in ("title", "desc"):
            self.inside = None

    def handle_data(self, data):
        if self.inside:
            self.text[self.inside] = self.text.get(self.inside, "") + data


class AboutPageTests(unittest.TestCase):
    def test_about_is_a_tab_of_the_app(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<a href="#/about" data-tab="about">About</a>', html)
        self.assertLess(html.index('src="/about.js"'), html.index('src="/researcher.js"'), "about.js loads before the router")
        self.assertIn('"about"', re.search(r"const TABS = \[(.*?)\]", (WEB / "researcher.js").read_text(encoding="utf-8")).group(1))

    def test_every_figure_is_named_and_described(self):
        figures = Figures()
        figures.feed(about_template())
        self.assertEqual({svg["id"] for svg in figures.svgs}, {"loop-art", "seed-art", "engines-art"})
        for svg in figures.svgs:
            self.assertEqual(svg.get("role"), "img")
            for label in svg["aria-labelledby"].split():
                with self.subTest(figure=svg["id"], label=label):
                    self.assertTrue(figures.text.get(label, "").strip(), f"#{label} names or describes the figure")

    def test_page_ships_with_the_package_and_release(self):
        package_data = json.loads(re.search(r"^oopc = (\[.*\])$", (ROOT / "pyproject.toml").read_text(), re.M).group(1))
        assets = load_tool("check_distribution").ASSETS
        public = set(json.loads((ROOT / "config/public-files.json").read_text())["files"])
        for name in PAGE_FILES:
            with self.subTest(file=name):
                self.assertTrue(any(fnmatch.fnmatch(f"web/{name}", pattern) for pattern in package_data))
                self.assertIn(f"web/{name}", assets)
                self.assertIn(f"oopc/web/{name}", public)

    def test_seed_numbers_match_the_current_release(self):
        pointer = ROOT / "releases" / "current.json"
        if not pointer.is_file():
            self.skipTest("No seed release in this checkout")
        release = ROOT / "releases" / json.loads(pointer.read_text())["release_id"] / "graph.sqlite"
        with sqlite3.connect(f"file:{release}?mode=ro", uri=True) as db:
            identities = db.execute("SELECT count(*) FROM records WHERE type = 'PolymerConcept'").fetchone()[0]
            structures = db.execute("SELECT count(*) FROM records WHERE type = 'Structure'").fetchone()[0]
            records = db.execute("SELECT count(*) FROM records").fetchone()[0]
        html = about_template()
        for stated in (f"{identities} polymer identities", f"{structures} chemical structures", f"{records:,} records"):
            self.assertIn(stated, html)
        self.assertEqual(re.findall(r'data-to="(\d+)"', html), [str(identities), str(structures), str(records)])


if __name__ == "__main__":
    unittest.main()
