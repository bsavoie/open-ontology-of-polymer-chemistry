"""The schematic figures (figures/schematics/draw.py with kit.py): text wraps within its width, and a canvas is a
well-formed SVG of the right size. When the frozen code, the released knowledge snapshot and A1's outputs are present
(OOPC_STUDY_ROOT naming the main checkout), Figures 1 and 2 and the TOC graphic are also drawn from them, without
exporting: each is 7 in wide (the TOC 3.25 x 1.75 in), uses no text below 5.5 pt and carries no local path. Nothing is
written to disk."""
import re, sys, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY / "figures" / "schematics"))
try:
    import kit  # noqa: E402
    import draw  # noqa: E402
except ImportError as error:  # matplotlib missing
    raise unittest.SkipTest("the schematics need matplotlib: %s" % error)

SVG = "{http://www.w3.org/2000/svg}"


def sizes(svg):
    return [float(v) for v in re.findall(r'font-size="([0-9.]+)"', svg)]


class Kit(unittest.TestCase):
    def test_wrap_keeps_each_line_within_its_width(self):
        text = "Pellets; TA Instruments DSC 250 in modulated mode; nitrogen; second heating; 5 °C/min."
        lines = kit.wrap(text, 80, kit.SMALL)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(kit.width(line, kit.SMALL) <= 80 for line in lines if " " in line))
        self.assertEqual(" ".join(lines), text)
        self.assertTrue(any("5 °C/min." in line for line in lines))  # a no-break space holds

    def test_canvas_is_well_formed_svg_in_points(self):
        c = kit.Canvas(7.0, 1.0, "test")
        with c.group("panel-a"):
            c.frame(1, 5, 200, 60, "a", "Title")
            c.text(10, 30, [("T", {}), ("g", {"sub": True}), (" & <PVC>", {})], size=kit.SMALL)
            c.arrow([(10, 40), (100, 40)])
        root = ET.fromstring(c.svg())
        self.assertEqual((root.get("width"), root.get("viewBox")), ("7in", "0 0 504 72"))
        self.assertEqual(root.find(SVG + "g").get("id"), "panel-a")
        self.assertGreaterEqual(min(sizes(c.svg())), kit.TINY)


class Figures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.F = draw.facts()
        except (OSError, KeyError, StopIteration) as error:
            raise unittest.SkipTest("the frozen code, snapshot or A1 outputs are not here: %s" % error)

    def test_each_figure_draws_at_its_size_with_no_small_text_or_local_path(self):
        for build, size in ((draw.figure1, "7in"), (draw.figure2, "7in"), (draw.figure_toc, "3.25in")):
            svg = build(self.F).svg()
            root = ET.fromstring(svg)
            self.assertEqual(root.get("width"), size)
            self.assertGreaterEqual(min(sizes(svg)), kit.TINY)
            self.assertNotRegex(svg, r"/Users/|/home/|/private/")
        self.assertEqual(draw.figure_toc(self.F).h, 1.75 * 72)

    def test_no_text_below_6_5_pt(self):
        """The figures name things and leave explanations to the caption: every text element is at least 6.5 pt (a
        subscript, a tspan, may be smaller)."""
        for build in (draw.figure1, draw.figure2, draw.figure_toc):
            svg = build(self.F).svg()
            self.assertGreaterEqual(min(float(v) for v in re.findall(r'<text[^>]*font-size="([0-9.]+)"', svg)), 6.5)

    def test_the_drawn_numbers_are_the_manuscripts(self):
        svg = draw.figure1(self.F).svg()
        for number in ("1,092", "8,899", "1,679", "157", "155.1 ± 0.5 °C"):
            self.assertIn(number, svg)
        svg = draw.figure2(self.F).svg()
        for number in ("16,925", "274", self.F["prompt"], "1.10", "27 pairs", "10–25", "1 in 5"):
            self.assertIn(number, svg)


if __name__ == "__main__":
    unittest.main()
