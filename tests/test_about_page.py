"""The about page: every term has one definition, figures are theme-neutral and current, and the page ships."""
import fnmatch
import importlib.util
import json
import re
import sqlite3
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "oopc" / "web"
FIGURES = WEB / "about"
SVG = "{http://www.w3.org/2000/svg}"
PAGE_FILES = ["about.html", "about.css", "about.js"]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Page(HTMLParser):
    """The terms, glossary entries, cross-references and figure holders in about.html."""

    def __init__(self):
        super().__init__()
        self.terms, self.entries, self.see_also, self.figures = [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-term" in attrs:
            self.terms.append(attrs["data-term"])
        if tag == "div" and "entry" in (attrs.get("class") or "").split() and attrs.get("id", "").startswith("term-"):
            self.entries.append(attrs["id"][len("term-"):])
        if tag == "a" and (attrs.get("href") or "").startswith("#term-"):
            self.see_also.append(attrs["href"][len("#term-"):])
        if "data-figure" in attrs:
            self.figures.append(attrs)


def read_page():
    page = Page()
    page.feed((WEB / "about.html").read_text(encoding="utf-8"))
    return page


def svg_files():
    return sorted(FIGURES.glob("*.svg"))


class AboutPageTests(unittest.TestCase):
    def test_every_term_has_one_definition_and_every_definition_is_used(self):
        page = read_page()
        used = set(page.terms)
        for path in svg_files():
            used |= {element.get("data-term") for element in ET.parse(path).iter() if element.get("data-term")}
        entries = page.entries
        self.assertEqual(len(entries), len(set(entries)), "A glossary term is defined twice")
        self.assertFalse(used - set(entries), "Terms without a glossary entry")
        self.assertFalse(set(entries) - used, "Glossary entries that nothing on the page or in a figure uses")
        self.assertFalse(set(page.see_also) - set(entries), "Cross-references to missing glossary entries")

    def test_figures_are_labelled_groups_coloured_only_by_the_page(self):
        self.assertTrue(svg_files())
        for path in svg_files():
            with self.subTest(figure=path.name):
                text = path.read_text(encoding="utf-8")
                root = ET.fromstring(text)
                self.assertEqual(root.tag, SVG + "svg")
                # A group, not an image: an image role would hide the clickable labels from screen readers.
                self.assertEqual(root.get("role"), "group")
                self.assertRegex(root.get("viewBox") or "", r"^0 0 \d+ \d+$")
                self.assertEqual([child.tag for child in root][:2], [SVG + "title", SVG + "desc"])
                self.assertTrue(root.find(SVG + "title").text and root.find(SVG + "desc").text)
                for element in root.iter():
                    self.assertNotEqual(element.tag, SVG + "style")
                    for name in ("fill", "stroke", "style", "color", "font-family"):
                        self.assertIsNone(element.get(name), f"{name} on <{element.tag}>: colour and type come from about.css")
                for leak in ("/Users/", "/home/", ".oopc", "file:", "#"):
                    self.assertNotIn(leak, text)

    def test_page_names_every_figure_with_its_shape(self):
        referenced = set()
        for holder in read_page().figures:
            style = dict(part.split(":", 1) for part in holder["style"].split(";") if part)
            for key, name in (("--wide", holder["data-figure"]), ("--narrow", holder.get("data-narrow"))):
                if not name:
                    continue
                with self.subTest(figure=name):
                    path = FIGURES / f"{name}.svg"
                    self.assertTrue(path.is_file())
                    referenced.add(path.name)
                    width, height = ET.parse(path).getroot().get("viewBox").split()[2:]
                    self.assertEqual(style.get(key), f"{width}/{height}", "The holder's aspect ratio must match the figure")
        self.assertEqual(referenced, {path.name for path in svg_files()})

    def test_page_and_figures_ship_with_the_package_and_release(self):
        shipped = PAGE_FILES + [f"about/{path.name}" for path in svg_files()]
        package_data = json.loads(re.search(r"^oopc = (\[.*\])$", (ROOT / "pyproject.toml").read_text(), re.M).group(1))
        assets = load_tool("check_distribution").ASSETS
        public = set(json.loads((ROOT / "config/public-files.json").read_text())["files"])
        for name in shipped:
            with self.subTest(file=name):
                self.assertTrue(any(fnmatch.fnmatch(f"web/{name}", pattern) for pattern in package_data))
                self.assertIn(f"web/{name}", assets)
                self.assertIn(f"oopc/web/{name}", public)
        self.assertIn('href="/about.html"', (WEB / "index.html").read_text(encoding="utf-8"))

    def test_seed_numbers_and_figures_match_the_current_release(self):
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
        drawn = load_tool("draw_about_figures").figures(ROOT)
        for name, content in drawn.items():
            with self.subTest(figure=name):
                self.assertEqual((FIGURES / name).read_text(encoding="utf-8"), content,
                                 "Figures are stale: run python tools/draw_about_figures.py")


if __name__ == "__main__":
    unittest.main()
