#!/usr/bin/env python3
"""The OOPC wordmark as the app's top bar prints it, as vector files for the preprint and anywhere else.

OOPC in Inter Bold (the app's bundled `InterVariable.woff2` at wght 700, opsz 21, letter-spacing 0.03 em), printed in
three inks like a copy-machine proof: a purple plate and a yellow plate out of register, screen-blended so they mix
where they overlap, under a white key at 84%. The offsets are the app's (`researcher.css`, `.word::before/::after`) in
em at its 21 px: purple +1.5 px right and 1 px up, yellow 2 px left and 1.5 px down. The letters are outlines, so the
files need no font.

- `oopc-wordmark` the icon: the wordmark on the top bar's dark ground (#17141f), a rounded tile.
- `oopc-wordmark-paper` for a white page: the same plates in the light theme's purple, multiplied like ink, under the
  light theme's ink.

Writes each as SVG and PDF (the PDF draws the plates in an isolated transparency group with /Screen or /Multiply)
to `studies/macromolecules/manuscript/figures/` (or `--out`).

    python -B wordmark.py [--out DIR]
"""
import argparse
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FONT = REPO / "oopc" / "web" / "vendor" / "InterVariable.woff2"
OUT = HERE.parent / "manuscript" / "figures"

EM = 100.0                       # PDF points per em; the files scale freely
APP_PX = 21.0                    # the top bar's font size, which the offsets are measured at
PURPLE_OFFSET = (1.5, -1.0)      # px at 21 px, y down
YELLOW_OFFSET = (-2.0, 1.5)
TRACKING = 0.03                  # em

STYLES = {
    "oopc-wordmark": {"ground": "#17141f", "purple": "#ab95ff", "yellow": "#f6c43f", "key": "#ffffff",
                      "key_alpha": 0.84, "blend": "screen"},
    "oopc-wordmark-paper": {"ground": None, "purple": "#5a35d0", "yellow": "#f6c43f", "key": "#1d1b26",
                            "key_alpha": 1.0, "blend": "multiply"},
}
PAD = (0.42, 0.28)              # the tile's padding around the inked letters, em (x, y)
RADIUS = 0.2                     # the tile's corner radius, em


class PathPen(BasePen):
    """Records a glyph run as PDF path operators and an SVG path, in points with y up (PDF) and y down (SVG)."""

    def __init__(self, glyphset, height):
        super().__init__(glyphset)
        self.pdf, self.svg, self.height = [], [], height

    def _xy(self, pt):
        return f"{pt[0]:.2f} {pt[1]:.2f}", f"{pt[0]:.2f} {self.height - pt[1]:.2f}"

    def _moveTo(self, pt):
        a, b = self._xy(pt); self.pdf.append(f"{a} m"); self.svg.append(f"M{b}")

    def _lineTo(self, pt):
        a, b = self._xy(pt); self.pdf.append(f"{a} l"); self.svg.append(f"L{b}")

    def _curveToOne(self, p1, p2, p3):
        pts = [self._xy(p) for p in (p1, p2, p3)]
        self.pdf.append(" ".join(a for a, _ in pts) + " c"); self.svg.append("C" + " ".join(b for _, b in pts))

    def _closePath(self):
        self.pdf.append("h"); self.svg.append("Z")


def letters():
    """OOPC laid out on a baseline at 0, in points: (glyph set, [(glyph name, x)], ink bounds)."""
    font = TTFont(FONT)
    units = font["head"].unitsPerEm
    glyphs = font.getGlyphSet(location={"wght": 700, "opsz": APP_PX})
    cmap = font.getBestCmap()
    scale, run, x = EM / units, [], 0.0
    for ch in "OOPC":
        name = cmap[ord(ch)]
        run.append((name, x))
        x += glyphs[name].width * scale + TRACKING * EM
    bounds = BoundsPen(glyphs)
    for name, gx in run:
        glyphs[name].draw(TransformPen(bounds, (scale, 0, 0, scale, gx, 0)))
    return glyphs, run, scale, bounds.bounds


def draw(glyphs, run, scale, dx, dy, height):
    pen = PathPen(glyphs, height)
    for name, gx in run:
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, scale, gx + dx, dy)))
    return " ".join(pen.pdf), "".join(pen.svg)


def rgb(hex_colour):
    return " ".join(f"{int(hex_colour[i:i + 2], 16) / 255:.4f}" for i in (1, 3, 5))


def rounded(w, h, r):
    k = 0.5523 * r
    return (f"{r} 0 m {w - r} 0 l {w - r + k} 0 {w} {r - k} {w} {r} c {w} {h - r} l {w} {h - r + k} {w - r + k} {h} "
            f"{w - r} {h} c {r} {h} l {r - k} {h} 0 {h - r + k} 0 {h - r} c 0 {r} l 0 {r - k} {r - k} 0 {r} 0 c h")


def pdf_file(objects):
    """A minimal PDF from object bodies (1-based, in order); object 1 is the catalog."""
    out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def stream(dictionary, data):
    data = data.encode()
    return f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def write(name, style, out):
    glyphs, run, scale, (x0, y0, x1, y1) = letters()
    px = EM / APP_PX
    (pdx, pdy), (ydx, ydy) = [(ox * px, -oy * px) for ox, oy in (PURPLE_OFFSET, YELLOW_OFFSET)]  # to y up
    # The ink's extent, plates included; the tile pads it, the paper mark crops to it.
    left, right = x0 + min(0, pdx, ydx), x1 + max(0, pdx, ydx)
    bottom, top = y0 + min(0, pdy, ydy), y1 + max(0, pdy, ydy)
    padx, pady = (PAD[0] * EM, PAD[1] * EM) if style["ground"] else (0, 0)
    w, h = right - left + 2 * padx, top - bottom + 2 * pady
    shift_x, shift_y = padx - left, pady - bottom
    purple_pdf, purple_svg = draw(glyphs, run, scale, shift_x + pdx, shift_y + pdy, h)
    yellow_pdf, yellow_svg = draw(glyphs, run, scale, shift_x + ydx, shift_y + ydy, h)
    key_pdf, key_svg = draw(glyphs, run, scale, shift_x, shift_y, h)
    blend = style["blend"].capitalize()

    page = []
    if style["ground"]:
        page.append(f"{rgb(style['ground'])} rg {rounded(round(w, 2), round(h, 2), RADIUS * EM)} f")
    page.append("/Plates Do")
    page.append(f"/Key gs {rgb(style['key'])} rg {key_pdf} f")
    plates = f"/Blend gs {rgb(style['purple'])} rg {purple_pdf} f {rgb(style['yellow'])} rg {yellow_pdf} f"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.2f} {h:.2f}] /Contents 7 0 R "
         f"/Group << /S /Transparency /CS /DeviceRGB >> "
         f"/Resources << /ExtGState << /Key 4 0 R >> /XObject << /Plates 6 0 R >> >> >>").encode(),
        f"<< /Type /ExtGState /ca {style['key_alpha']} >>".encode(),
        f"<< /Type /ExtGState /BM /{blend} >>".encode(),
        stream(f"/Type /XObject /Subtype /Form /BBox [0 0 {w:.2f} {h:.2f}] "
               f"/Group << /S /Transparency /I true /CS /DeviceRGB >> /Resources << /ExtGState << /Blend 5 0 R >> >>",
               plates),
        stream("", "\n".join(page)),
    ]
    (out / f"{name}.pdf").write_bytes(pdf_file(objects))

    ground = (f'<rect width="{w:.2f}" height="{h:.2f}" rx="{RADIUS * EM:.2f}" fill="{style["ground"]}"/>'
              if style["ground"] else "")
    key_alpha = f' fill-opacity="{style["key_alpha"]}"' if style["key_alpha"] < 1 else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" width="{w:.2f}" height="{h:.2f}">'
           f'<title>OOPC</title>{ground}<g style="isolation:isolate">'
           f'<path fill="{style["purple"]}" style="mix-blend-mode:{style["blend"]}" d="{purple_svg}"/>'
           f'<path fill="{style["yellow"]}" style="mix-blend-mode:{style["blend"]}" d="{yellow_svg}"/></g>'
           f'<path fill="{style["key"]}"{key_alpha} d="{key_svg}"/></svg>\n')
    (out / f"{name}.svg").write_text(svg)
    return w, h


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, style in STYLES.items():
        w, h = write(name, style, args.out)
        print(f"{name}: {w:.1f} x {h:.1f} pt (aspect {w / h:.2f})")


if __name__ == "__main__":
    main()
