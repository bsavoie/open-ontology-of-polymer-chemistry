"""A small SVG kit for the schematic figures (Fig. 1, its TOC version, Fig. 2): shapes, measured and wrapped text,
icons, and the exports.

The SVG is the editable master: one user unit is one point (72 per inch), every label is a <text> element in Arial,
every panel is a <g id="panel-x">, and arrowheads are drawn as polygons rather than SVG markers, so the file opens
cleanly in Illustrator and Inkscape. Colours, sizes and line widths are read from `../style.py` (by parsing it, not
importing it, so no `oopc` or study code is loaded). `export()` prints the SVG to a PDF of the exact page size with
headless Chrome (fonts embedded as TrueType) and rasterises that PDF to a 600 dpi PNG with `pdftoppm`.
"""
import ast, html, math, shutil, subprocess, tempfile
from pathlib import Path

from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextToPath

HERE = Path(__file__).resolve().parent


def _style():
    """The literal constants of style.py (colours, sizes, line widths), without importing it."""
    values = {}
    for node in ast.parse((HERE.parent / "style.py").read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                values[target.id] = value
            elif isinstance(target, ast.Tuple):
                values.update((t.id, v) for t, v in zip(target.elts, value))
    return values


ST = _style()
STATUS = ST["STATUS"]  # Reviewed, Added, Needs checking, Rejected
INK, INK2, MUTED, LIGHT = ST["INK"], ST["INK2"], ST["MUTED"], ST["LIGHT"]
GRID, AXIS, BAND, SURFACE = ST["GRID"], ST["AXIS"], ST["BAND"], ST["SURFACE"]
BLUE = ST["_BLUE"]  # the researcher's arms (K0 ... KF), light to dark
P = INK2  # ARM["P"], the plain session
RESEARCHER = BLUE[3]  # the researcher and its knowledge store
SIZE, SMALL, TINY, LETTER = ST["SIZE"], ST["SMALL"], ST["TINY"], ST["LETTER"]
LINE, HAIR = ST["LINE"], ST["HAIR"]
FAMILY = ", ".join(ST["FONT"][:2]) + ", sans-serif"
PT = 72.0
DPI = 600  # ACS: line art and combination figures at 600 dpi or more

_T2P = TextToPath()
_FONTS = {}


def width(text, size=SIZE, bold=False, italic=False):
    """Advance width of `text` in points, in Arial at `size` points."""
    key = (size, bold, italic)
    if key not in _FONTS:
        _FONTS[key] = FontProperties(family=ST["FONT"][0], size=size, weight="bold" if bold else "normal",
                                     style="italic" if italic else "normal")
    return _T2P.get_text_width_height_descent(text, _FONTS[key], ismath=False)[0] if text else 0.0


def wrap(text, limit, size=SIZE, bold=False):
    """Greedy word wrap of `text` to lines no wider than `limit` points."""
    lines, line = [], ""
    for word in text.split(" "):  # not on no-break spaces
        if not word:
            continue
        trial = (line + " " + word).strip()
        if line and width(trial, size, bold) > limit:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _num(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _attrs(**kw):
    out = []
    for key, value in kw.items():
        if value is None:
            continue
        out.append('%s="%s"' % (key.rstrip("_").replace("_", "-"), html.escape(_num(value), quote=True)))
    return " ".join(out)


class Canvas:
    """An SVG page of `w` x `h` inches; items are appended in drawing order, inside the open group."""

    def __init__(self, w, h, title, desc=""):
        self.w, self.h = w * PT, h * PT
        self.title, self.desc = title, desc
        self.parts = []
        self.depth = 0

    # ------------------------------------------------------------------ structure
    def group(self, id_, transform=None):
        canvas = self

        class _G:
            def __enter__(self_):
                canvas.parts.append("  " * (canvas.depth + 1) + "<g %s>" % _attrs(id=id_, transform=transform))
                canvas.depth += 1

            def __exit__(self_, *exc):
                canvas.depth -= 1
                canvas.parts.append("  " * (canvas.depth + 1) + "</g>")
        return _G()

    def raw(self, element):
        self.parts.append("  " * (self.depth + 1) + element)

    # ------------------------------------------------------------------ shapes
    def rect(self, x, y, w, h, rx=0, fill="none", stroke=None, sw=HAIR, dash=None, opacity=None, id_=None):
        self.raw("<rect %s/>" % _attrs(id=id_, x=x, y=y, width=w, height=h, rx=rx or None, fill=fill, stroke=stroke,
                                      stroke_width=sw if stroke else None, stroke_dasharray=dash,
                                      fill_opacity=opacity))

    def circle(self, cx, cy, r, fill="none", stroke=None, sw=HAIR, dash=None, opacity=None):
        self.raw("<circle %s/>" % _attrs(cx=cx, cy=cy, r=r, fill=fill, stroke=stroke,
                                        stroke_width=sw if stroke else None, stroke_dasharray=dash,
                                        fill_opacity=opacity))

    def ellipse(self, cx, cy, rx, ry, fill="none", stroke=None, sw=HAIR):
        self.raw("<ellipse %s/>" % _attrs(cx=cx, cy=cy, rx=rx, ry=ry, fill=fill, stroke=stroke,
                                         stroke_width=sw if stroke else None))

    def line(self, x1, y1, x2, y2, stroke=INK2, sw=HAIR, dash=None, cap=None):
        self.raw("<line %s/>" % _attrs(x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, stroke_width=sw,
                                      stroke_dasharray=dash, stroke_linecap=cap))

    def path(self, d, fill="none", stroke=INK2, sw=HAIR, dash=None, join="round", cap="round", opacity=None):
        self.raw("<path %s/>" % _attrs(d=d, fill=fill, stroke=stroke, stroke_width=sw if stroke else None,
                                      stroke_dasharray=dash, stroke_linejoin=join if stroke else None,
                                      stroke_linecap=cap if stroke else None, fill_opacity=opacity))

    def polygon(self, points, fill=INK2, stroke=None, sw=HAIR):
        self.raw("<polygon %s/>" % _attrs(points=" ".join("%s,%s" % (_num(float(x)), _num(float(y)))
                                                          for x, y in points),
                                          fill=fill, stroke=stroke, stroke_width=sw if stroke else None))

    def head(self, x, y, angle, color=INK2, sw=LINE):
        """An arrowhead with its tip at (x, y), pointing along `angle` (radians)."""
        length, half = 2.2 + 2.2 * sw, 1.1 + 1.0 * sw
        c, s = math.cos(angle), math.sin(angle)
        bx, by = x - length * c, y - length * s
        self.polygon([(x, y), (bx - half * s, by + half * c), (bx + half * s, by - half * c)], fill=color)
        return bx, by

    def arrow(self, points, color=INK2, sw=LINE, dash=None, both=False, gap=0.0):
        """A polyline arrow through `points`, head at the end (and the start with `both`); `gap` shortens the ends."""
        pts = [tuple(map(float, p)) for p in points]
        pts = _shorten(pts, gap)
        x, y = pts[-1]
        px, py = pts[-2]
        bx, by = self.head(x, y, math.atan2(y - py, x - px), color, sw)
        pts[-1] = (bx * 0.4 + x * 0.6, by * 0.4 + y * 0.6)  # the line ends inside the head
        if both:
            x0, y0 = pts[0]
            nx, ny = pts[1]
            cx, cy = self.head(x0, y0, math.atan2(y0 - ny, x0 - nx), color, sw)
            pts[0] = (cx * 0.4 + x0 * 0.6, cy * 0.4 + y0 * 0.6)
        self.path("M " + " L ".join("%s %s" % (_num(px_), _num(py_)) for px_, py_ in pts), stroke=color, sw=sw,
                  dash=dash)

    def curve(self, p0, c1, c2, p1, color=INK2, sw=LINE, dash=None, head=True):
        """A cubic Bezier arrow from p0 to p1 with control points c1, c2."""
        if head:
            bx, by = self.head(p1[0], p1[1], math.atan2(p1[1] - c2[1], p1[0] - c2[0]), color, sw)
            end = (bx * 0.4 + p1[0] * 0.6, by * 0.4 + p1[1] * 0.6)
        else:
            end = p1
        self.path("M %s %s C %s %s %s %s %s %s" % tuple(_num(float(v)) for v in (*p0, *c1, *c2, *end)),
                  stroke=color, sw=sw, dash=dash)

    def arc(self, cx, cy, r, a0, a1, color=INK2, sw=LINE, head=True, dash=None):
        """A clockwise circular arc arrow (angles in degrees, 0 = east, increasing clockwise on the page)."""
        t0, t1 = math.radians(a0), math.radians(a1)
        x0, y0 = cx + r * math.cos(t0), cy + r * math.sin(t0)
        x1, y1 = cx + r * math.cos(t1), cy + r * math.sin(t1)
        if head:
            tangent = t1 + math.pi / 2
            bx, by = self.head(x1, y1, tangent, color, sw)
            # end the stroke a little before the tip, on the circle
            back = (2.2 + 2.2 * sw) * 0.6 / r
            x1, y1 = cx + r * math.cos(t1 - back), cy + r * math.sin(t1 - back)
        large = 1 if (a1 - a0) % 360 > 180 else 0
        self.path("M %s %s A %s %s 0 %d 1 %s %s" % (_num(x0), _num(y0), _num(r), _num(r), large, _num(x1), _num(y1)),
                  stroke=color, sw=sw, dash=dash)

    # ------------------------------------------------------------------ text
    def text(self, x, y, content, size=SIZE, bold=False, italic=False, color=INK, anchor="start", id_=None):
        """One line at baseline y. `content` is a string or a list of runs: (text, {bold, italic, color, sub, sup,
        size})."""
        runs = [(content, {})] if isinstance(content, str) else content
        spans, shift = [], 0.0
        for text_, style in runs:
            sz = style.get("size", size)
            dy = 0.0
            if style.get("sub") or style.get("sup"):
                sz = max(TINY, round(sz * 0.75, 2))
                dy = sz * 0.35 if style.get("sub") else -sz * 0.55
            attrs = _attrs(font_weight="bold" if style.get("bold") is True and not bold else
                           "normal" if style.get("bold") is False and bold else None,
                           font_style="italic" if style.get("italic") else None,
                           fill=style.get("color"), font_size=sz if sz != size else None,
                           dy=(dy - shift) if (dy - shift) else None)
            shift = dy
            spans.append("<tspan %s>%s</tspan>" % (attrs, html.escape(text_, quote=False)) if attrs else
                         html.escape(text_, quote=False))
        if shift:
            spans.append('<tspan dy="%s"></tspan>' % _num(-shift))
        self.raw("<text %s>%s</text>" % (_attrs(id=id_, x=x, y=y, font_size=size,
                                               font_weight="bold" if bold else None,
                                               font_style="italic" if italic else None, fill=color,
                                               text_anchor=None if anchor == "start" else anchor), "".join(spans)))

    def lines(self, x, y, lines, size=SIZE, lead=None, **kw):
        """Several lines from baseline y, `lead` points apart; returns the baseline after the last."""
        lead = lead or size * 1.22
        for i, line in enumerate(lines):
            self.text(x, y + i * lead, line, size=size, **kw)
        return y + len(lines) * lead

    def para(self, x, y, text, limit, size=SIZE, lead=None, **kw):
        """`text` wrapped to `limit` points from baseline y; returns the baseline after the last line."""
        return self.lines(x, y, wrap(text, limit, size, kw.get("bold", False)), size=size, lead=lead, **kw)

    def _gapped(self, x, y, w, h, r, g0, g1, color, sw, dash=None):
        """A rounded rectangle's outline, its top edge open from g0 to g1."""
        self.path("M %s %s L %s %s A %s %s 0 0 1 %s %s L %s %s A %s %s 0 0 1 %s %s L %s %s A %s %s 0 0 1 %s %s "
                  "L %s %s A %s %s 0 0 1 %s %s L %s %s" % tuple(_num(float(v)) for v in (
                      g1, y, x + w - r, y, r, r, x + w, y + r, x + w, y + h - r, r, r, x + w - r, y + h,
                      x + r, y + h, r, r, x, y + h - r, x, y + r, r, r, x + r, y, g0, y)),
                  stroke=color, sw=sw, dash=dash, cap="butt")

    def frame(self, x, y, w, h, letter, title=None, r=4, color=LIGHT, sw=HAIR, inset=7, pad=3):
        """A thin rounded rectangle at (x, y, w, h) whose top edge breaks for the panel letter (bold, LETTER points)
        and title (bold, SIZE points), set on the edge."""
        label = width(letter, LETTER, True) + (4 + width(title, SIZE, True) if title else 0)
        g0 = x + inset
        self._gapped(x, y, w, h, r, g0, g0 + label + 2 * pad, color, sw)
        base = y + LETTER * 0.34
        self.text(g0 + pad, base, letter, size=LETTER, bold=True)
        if title:
            self.text(g0 + pad + width(letter, LETTER, True) + 4, base, title, size=SIZE, bold=True)

    def region(self, x, y, w, h, name, r=5, fill=BAND, color=MUTED, sw=HAIR, dash="1 1.5", inset=6, pad=2.5,
               size=SMALL):
        """A shaded background with a dotted outline whose top edge breaks for its name (italic, `size` points)."""
        self.rect(x, y, w, h, rx=r, fill=fill)
        g0 = x + inset
        self._gapped(x, y, w, h, r, g0, g0 + width(name, size, italic=True) + 2 * pad, color, sw, dash)
        self.text(g0 + pad, y + size * 0.34, name, size=size, italic=True, color=INK2)

    # ------------------------------------------------------------------ output
    def svg(self):
        head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%sin" height="%sin" viewBox="0 0 %s %s" '
                'font-family="%s">\n  <title>%s</title>\n  <desc>%s</desc>\n'
                '  <rect id="background" x="0" y="0" width="%s" height="%s" fill="%s"/>\n'
                % (_num(self.w / PT), _num(self.h / PT), _num(self.w), _num(self.h), FAMILY,
                   html.escape(self.title), html.escape(self.desc), _num(self.w), _num(self.h), SURFACE))
        return head + "\n".join(self.parts) + "\n</svg>\n"


def _shorten(pts, gap):
    if not gap:
        return pts
    out = list(pts)
    for i, j in ((0, 1), (-1, -2)):
        (x0, y0), (x1, y1) = out[i], out[j]
        d = math.hypot(x1 - x0, y1 - y0) or 1
        out[i] = (x0 + (x1 - x0) * gap / d, y0 + (y1 - y0) * gap / d)
    return out


# ---------------------------------------------------------------------------------------------- icons

def person(c, x, y, s=10, color=INK2, label=None):
    """An agent: head and shoulders, `s` points tall, centred on x with its top at y."""
    r = s * 0.2
    c.circle(x, y + r, r, fill=color)
    w = s * 0.42
    top = y + 2 * r + s * 0.06
    c.path("M %s %s Q %s %s %s %s L %s %s Q %s %s %s %s Z" % tuple(_num(float(v)) for v in (
        x - w, y + s, x - w, top, x, top, x, top, x + w, top, x + w, y + s)), fill=color, stroke=None)
    if label:
        c.text(x, y + s + SMALL + 1, label, size=SMALL, anchor="middle", color=color)


def document(c, x, y, w=11, h=14, color=INK2, fill=SURFACE, lines=3):
    """A page with a folded corner, top left at (x, y)."""
    f = w * 0.3
    c.path("M %s %s L %s %s L %s %s L %s %s L %s %s Z" % tuple(_num(float(v)) for v in (
        x, y, x + w - f, y, x + w, y + f, x + w, y + h, x, y + h)), fill=fill, stroke=color, sw=HAIR)
    c.path("M %s %s L %s %s L %s %s" % tuple(_num(float(v)) for v in (x + w - f, y, x + w - f, y + f, x + w, y + f)),
           stroke=color, sw=HAIR)
    for i in range(lines):
        yy = y + f + 2.2 + i * 2.4
        if yy < y + h - 1.5:
            c.line(x + 2, yy, x + w - 2 - (2 if i == lines - 1 else 0), yy, stroke=color, sw=HAIR * 0.8)


def store(c, x, y, w=22, h=18, color=RESEARCHER, fill=SURFACE, sw=LINE):
    """A database cylinder, top left at (x, y)."""
    ry = h * 0.14
    c.path("M %s %s L %s %s A %s %s 0 0 0 %s %s L %s %s" % tuple(_num(float(v)) for v in (
        x, y + ry, x, y + h - ry, w / 2, ry, x + w, y + h - ry, x + w, y + ry)), fill=fill, stroke=color, sw=sw)
    c.ellipse(x + w / 2, y + ry, w / 2, ry, fill=fill, stroke=color, sw=sw)
    for k in (1, 2):
        yy = y + ry + (h - 2 * ry) * k / 3
        c.path("M %s %s A %s %s 0 0 0 %s %s" % tuple(_num(float(v)) for v in (x, yy, w / 2, ry, x + w, yy)),
               stroke=color, sw=HAIR)


def globe(c, cx, cy, r=6, color=INK2):
    """The web: a globe of radius r."""
    c.circle(cx, cy, r, fill=SURFACE, stroke=color, sw=HAIR * 1.4)
    c.ellipse(cx, cy, r * 0.45, r, stroke=color, sw=HAIR)
    c.line(cx - r, cy, cx + r, cy, stroke=color, sw=HAIR)
    for f in (-0.5, 0.5):
        half = r * math.sqrt(1 - f * f)
        c.line(cx - half, cy + f * r, cx + half, cy + f * r, stroke=color, sw=HAIR * 0.8)


def check(c, x, y, s=4, color=INK2, sw=LINE):
    c.path("M %s %s L %s %s L %s %s" % tuple(_num(float(v)) for v in (x, y + s * 0.5, x + s * 0.38, y + s * 0.88,
                                                                         x + s, y)), stroke=color, sw=sw)


def cross(c, x, y, s=4, color=INK2, sw=LINE):
    c.line(x, y, x + s, y + s, stroke=color, sw=sw, cap="round")
    c.line(x + s, y, x, y + s, stroke=color, sw=sw, cap="round")


def badge(c, x, y, status, size=SMALL, solid=True, anchor="start"):
    """A status badge (rounded box in the status colour, white bold label); returns its width."""
    label = status
    w = width(label, size, True) + 5
    h = size + 3
    if anchor == "middle":
        x -= w / 2
    color = STATUS[status]
    c.rect(x, y, w, h, rx=h / 2, fill=color if solid else SURFACE, stroke=None if solid else color, sw=HAIR)
    c.text(x + w / 2, y + h - 2.6 + (size - SMALL) * 0.1, label, size=size, bold=True,
           color=SURFACE if solid else color, anchor="middle")
    return w


def tinted(color, alpha):
    """`color` mixed with white (a flat tint, so exports and editors agree)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda v: round(255 - (255 - v) * alpha)
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


# ---------------------------------------------------------------------------------------------- export

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def export(canvas, name, out=HERE):
    """Writes `name`.svg (the master), `name`.pdf (headless Chrome, exact page size) and `name`.png (600 dpi)."""
    out = Path(out)
    svg = canvas.svg()
    (out / (name + ".svg")).write_text(svg, encoding="utf-8")
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or CHROME
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text('<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>@page{size:%sin %sin;'
                        'margin:0}html,body{margin:0;padding:0}svg{display:block}</style></head><body>%s</body></html>'
                        % (html.escape(canvas.title), _num(canvas.w / PT), _num(canvas.h / PT),
                           svg.split("?>", 1)[1]), encoding="utf-8")
        pdf = out / (name + ".pdf")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=%s" % pdf, page.as_uri()], check=True, capture_output=True)
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-singlefile", "-aa", "yes", "-aaVector", "yes",
                    str(pdf), str(out / name)], check=True)
    return [name + ext for ext in (".svg", ".pdf", ".png")]
