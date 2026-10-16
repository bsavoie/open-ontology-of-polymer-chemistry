"""Draw the about page's figures as theme-neutral SVG.

The figures carry classes, not colours: ``oopc/web/about.css`` colours them from
the app's tokens, so they follow the light and dark themes. Labels that name a
glossary term carry ``data-term`` and open its definition on the page.

Figures 1 and 2 read the public seed release (``releases/current.json``); the
rest are schematic. Nothing is read from ``.oopc/``. Output is deterministic, so
``--check`` can confirm that the committed files are current.

    python tools/draw_about_figures.py            # write oopc/web/about/*.svg
    python tools/draw_about_figures.py --check    # compare with the committed files
"""

import argparse
import json
import math
import random
import re
import sqlite3
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "oopc" / "web" / "about"
PLA = "wop-000217"


def hypot(dx, dy):
    """A distance that is the same on every Python: math.hypot became correctly rounded in 3.10, and the force layout
    amplifies its last-bit differences (CL-16)."""
    return math.sqrt(dx * dx + dy * dy)


# ---------------------------------------------------------------------------
# SVG helpers: classes only, numbers rounded to 0.1 so output is stable
# ---------------------------------------------------------------------------

def num(value):
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def attrs(**values):
    parts = []
    for key, value in values.items():
        if value is None:
            continue
        name = key.rstrip("_").replace("_", "-")
        shown = num(value) if isinstance(value, (int, float)) else escape(str(value), {'"': "&quot;"})
        parts.append(f'{name}="{shown}"')
    return " ".join(parts)


def text(x, y, content, cls="lbl", anchor=None, term=None):
    """One line of text; ``term`` makes it open that glossary definition."""
    classes = cls + (" term" if term else "")
    return f"<text {attrs(x=x, y=y, class_=classes, text_anchor=anchor, data_term=term)}>{escape(content)}</text>"


def lines(x, y, rows, step, cls="lbl", anchor=None, term=None):
    return "".join(text(x, y + i * step, row, cls, anchor, term) for i, row in enumerate(rows))


def line(x1, y1, x2, y2, cls="edge"):
    return f"<line {attrs(x1=x1, y1=y1, x2=x2, y2=y2, class_=cls)}/>"


def path(d, cls="edge"):
    return f"<path {attrs(d=d, class_=cls)}/>"


def circle(x, y, r, cls):
    return f"<circle {attrs(cx=x, cy=y, r=r, class_=cls)}/>"


def rect(x, y, w, h, cls, rx=8):
    return f"<rect {attrs(x=x, y=y, width=w, height=h, rx=rx, class_=cls)}/>"


def chevron(x, y, angle, cls="edge", size=6.0):
    """An open arrowhead with its tip at (x, y), pointing along ``angle``."""
    a, b = angle + math.radians(150), angle - math.radians(150)
    return path(f"M{num(x + size * math.cos(a))} {num(y + size * math.sin(a))}L{num(x)} {num(y)}"
                f"L{num(x + size * math.cos(b))} {num(y + size * math.sin(b))}", cls)


def arrow(x1, y1, x2, y2, cls="edge"):
    return line(x1, y1, x2, y2, cls) + chevron(x2, y2, math.atan2(y2 - y1, x2 - x1), cls.replace(" dash", ""))


def elbow(d, x, y, angle, cls="edge"):
    """A path ending in an arrowhead at (x, y)."""
    return path(d, cls) + chevron(x, y, angle, cls.replace(" dash", ""))


def text_width(content, size=13.0, factor=0.56):
    """A generous estimate of rendered width, for sizing boxes and avoiding overlaps."""
    return len(content) * size * factor


def svg(width, height, title, description, body, extra=""):
    classes = f"fig {extra}".strip()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="group" class="{classes}">'
            f"<title>{escape(title)}</title><desc>{escape(description)}</desc>{body}</svg>\n")


# ---------------------------------------------------------------------------
# Seed access (public release only)
# ---------------------------------------------------------------------------

def release_database(root=ROOT):
    pointer = root / "releases" / "current.json"
    if not pointer.is_file():
        raise SystemExit("No seed release here: run `python -m oopc import-seed` first.")
    database = root / "releases" / json.loads(pointer.read_text())["release_id"] / "graph.sqlite"
    return sqlite3.connect(f"file:{database}?mode=ro", uri=True)


def family_graph(db):
    nodes = sorted(row[0] for row in db.execute("SELECT id FROM records WHERE type = 'PolymerConcept'"))
    known = set(nodes)
    edges = set()
    for subject, obj in db.execute("SELECT subject, object FROM edges WHERE predicate IN ('broader', 'narrower', 'related')"):
        if subject in known and obj in known and subject != obj:
            edges.add(tuple(sorted((subject, obj))))
    return nodes, sorted(edges)


def molfile(db, structure_id):
    return json.loads(db.execute("SELECT json FROM records WHERE id = ?", (structure_id,)).fetchone()[0])["molfileV3000"]


# ---------------------------------------------------------------------------
# The seed graph
# ---------------------------------------------------------------------------

def components(nodes, edges):
    neighbours = {node: set() for node in nodes}
    for a, b in edges:
        neighbours[a].add(b)
        neighbours[b].add(a)
    seen, groups = set(), []
    for node in nodes:
        if node in seen:
            continue
        stack, group = [node], []
        seen.add(node)
        while stack:
            current = stack.pop()
            group.append(current)
            for other in sorted(neighbours[current] - seen):
                seen.add(other)
                stack.append(other)
        groups.append(sorted(group))
    return sorted(groups, key=lambda g: (-len(g), g[0])), neighbours


def force_layout(group, neighbours, rng, iterations=400):
    """Fruchterman-Reingold on one cluster: unit-scale positions about its centroid."""
    if len(group) == 1:
        return {group[0]: (0.0, 0.0)}
    pos = {node: [rng.uniform(-1, 1), rng.uniform(-1, 1)] for node in group}
    temperature = 0.4
    for _ in range(iterations):
        move = {node: [0.0, 0.0] for node in group}
        for i, u in enumerate(group):
            for v in group[i + 1:]:
                dx, dy = pos[u][0] - pos[v][0], pos[u][1] - pos[v][1]
                d = max(hypot(dx, dy), 0.01)
                push = 1.0 / d
                move[u][0] += dx / d * push
                move[u][1] += dy / d * push
                move[v][0] -= dx / d * push
                move[v][1] -= dy / d * push
            for v in sorted(neighbours[u]):
                if u < v:
                    dx, dy = pos[u][0] - pos[v][0], pos[u][1] - pos[v][1]
                    d = max(hypot(dx, dy), 0.01)
                    pull = d * d
                    move[u][0] -= dx / d * pull
                    move[u][1] -= dy / d * pull
                    move[v][0] += dx / d * pull
                    move[v][1] += dy / d * pull
        for node in group:
            dx, dy = move[node]
            d = max(hypot(dx, dy), 1e-9)
            step = min(d, temperature)
            pos[node][0] += dx / d * step
            pos[node][1] += dy / d * step
        temperature = max(temperature * 0.985, 0.002)
    cx = sum(p[0] for p in pos.values()) / len(pos)
    cy = sum(p[1] for p in pos.values()) / len(pos)
    return {node: (p[0] - cx, p[1] - cy) for node, p in pos.items()}


def level(local, tilt):
    """Rotate a cluster so its long axis lies near horizontal, which packs better into a wide band."""
    sxx = sum(x * x for x, _ in local.values())
    syy = sum(y * y for _, y in local.values())
    sxy = sum(x * y for x, y in local.values())
    angle = -0.5 * math.atan2(2 * sxy, sxx - syy) + tilt
    c, s = math.cos(angle), math.sin(angle)
    return {node: (x * c - y * s, x * s + y * c) for node, (x, y) in local.items()}


def pack(groups, layouts, aspect, spacing, rng):
    """Clusters along an elliptical spiral, largest first; then single families fill the gaps evenly."""
    boxes, positions = [], {}
    for group in (g for g in groups if len(g) > 1):
        tilt = rng.uniform(-0.4, 0.4)
        local = {node: (x * spacing, y * spacing) for node, (x, y) in level(layouts[group[0]], tilt).items()}
        x0, x1 = min(p[0] for p in local.values()), max(p[0] for p in local.values())
        y0, y1 = min(p[1] for p in local.values()), max(p[1] for p in local.values())
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = (x1 - x0) / 2 + 10, (y1 - y0) / 2 + 10
        theta = 0.0
        while True:
            r = 0.5 * theta
            cx, cy = r * math.cos(theta) * aspect, r * math.sin(theta)
            if all(abs(cx - bx) >= hw + bw or abs(cy - by) >= hh + bh for bx, by, bw, bh in boxes):
                break
            theta += max(0.01, 1.5 / max(r, 1.0))
        boxes.append((cx, cy, hw, hh))
        for node, (x, y) in local.items():
            positions[node] = (cx + x - mx, cy + y - my)

    # Single families: a jittered grid around the clusters, nearest the centre first.
    taken = list(positions.values())
    xs, ys = [p[0] for p in taken], [p[1] for p in taken]
    singles = [g[0] for g in groups if len(g) == 1]
    step = spacing * 0.95
    candidates = []
    row = 0
    y = min(ys) - 6 * step
    while y <= max(ys) + 6 * step:
        x = min(xs) - 6 * step * aspect + (step / 2 if row % 2 else 0)
        while x <= max(xs) + 6 * step * aspect:
            candidates.append((x + rng.uniform(-5.5, 5.5), y + rng.uniform(-5.5, 5.5)))
            x += step
        y += step * 0.87
        row += 1
    candidates.sort(key=lambda p: (p[0] / aspect) ** 2 + p[1] ** 2)
    chosen = []
    for x, y in candidates:
        if len(chosen) == len(singles):
            break
        if all(hypot(x - px, y - py) >= spacing * 0.8 for px, py in taken):
            chosen.append((x, y))
            taken.append((x, y))
    for node, point in zip(singles, chosen):
        positions[node] = point
    return positions


def seed_graph_figure(db, width, height):
    nodes, edges = family_graph(db)
    groups, neighbours = components(nodes, edges)
    rng = random.Random(20261010)
    layouts = {group[0]: force_layout(group, neighbours, rng) for group in groups}
    positions = pack(groups, layouts, aspect=width / height * 0.9, spacing=16.0, rng=rng)
    margin = 18.0
    xs, ys = [p[0] for p in positions.values()], [p[1] for p in positions.values()]
    scale = min((width - 2 * margin) / (max(xs) - min(xs)), (height - 2 * margin) / (max(ys) - min(ys)))
    ox = (width - (max(xs) - min(xs)) * scale) / 2 - min(xs) * scale
    oy = (height - (max(ys) - min(ys)) * scale) / 2 - min(ys) * scale
    at = {node: (ox + x * scale, oy + y * scale) for node, (x, y) in positions.items()}
    cluster = next(group for group in groups if PLA in group)
    highlight = set(cluster)

    body = ['<g class="links">']
    for a, b in edges:
        body.append(line(*at[a], *at[b], "link link-hi" if a in highlight and b in highlight else "link"))
    body.append('</g><g class="dots">')
    for node in nodes:
        r = 2.1 + 0.55 * math.sqrt(len(neighbours[node]))
        body.append(circle(*at[node], r + 0.6, "dot dot-hi") if node in highlight else circle(*at[node], r, "dot"))
    body.append("</g>")

    # Label the polylactide cluster where the label and its leader cross the fewest dots and links.
    cx = sum(at[n][0] for n in cluster) / len(cluster)
    cy = sum(at[n][1] for n in cluster) / len(cluster)
    obstacles = [at[n] for n in nodes if n not in highlight]
    for a, b in edges:
        if a not in highlight:
            (x1, y1), (x2, y2) = at[a], at[b]
            steps = max(1, int(hypot(x2 - x1, y2 - y1) / 5))
            obstacles += [(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps) for k in range(1, steps)]
    label = "Polylactide family"
    label_width = text_width(label, 12.5)
    best = None
    for degrees in range(0, 360, 10):
        angle = math.radians(degrees)
        ux, uy = math.cos(angle), math.sin(angle)
        ax, ay = at[max(cluster, key=lambda n: (at[n][0] - cx) * ux + (at[n][1] - cy) * uy)]
        lx, ly = ax + 36 * ux, ay + 36 * uy
        left = lx + 4 if ux >= 0 else lx - label_width - 4
        box = (left - 6, ly - 10, left + label_width + 6, ly + 10)
        if box[0] < 4 or box[2] > width - 4 or box[1] < 4 or box[3] > height - 4:
            continue
        crowd = sum(1 for x, y in obstacles if box[0] <= x <= box[2] and box[1] <= y <= box[3])
        for k in range(1, 8):
            px, py = ax + (lx - ax) * k / 8, ay + (ly - ay) * k / 8
            crowd += sum(1 for x, y in obstacles if hypot(x - px, y - py) < 5)
        score = (crowd, abs(uy), degrees)
        if best is None or score < best[0]:
            best = (score, ax, ay, lx, ly, angle, left)
    _, ax, ay, lx, ly, angle, left = best
    body.append(line(ax + 7 * math.cos(angle), ay + 7 * math.sin(angle), lx, ly, "leader"))
    body.append(text(left, ly + 4.5, label, "lbl hero-label", term="polymer-family"))

    singletons = sum(1 for group in groups if len(group) == 1)
    description = (f"{len(nodes)} polymer families from the seed, drawn as dots and joined by {len(edges)} family "
                   f"and related-family links into {len(groups)} clusters; {singletons} families have no link yet. "
                   "The polylactide cluster is highlighted.")
    return svg(width, height, "The seed graph", description, "".join(body), "fig-hero")


# ---------------------------------------------------------------------------
# Repeat-unit drawing from a V3000 molfile (mirrors the app's bracket logic)
# ---------------------------------------------------------------------------

def parse_v3000(block):
    atoms, bonds, sru, section = [], [], None, None
    for raw in block.splitlines():
        if not raw.startswith("M  V30 "):
            continue
        body = raw[7:].strip()
        if body.startswith("BEGIN "):
            section = body.split()[1]
            continue
        if body.startswith("END "):
            section = None
            continue
        parts = body.split()
        if section == "ATOM":
            atoms.append((parts[1], float(parts[2]), float(parts[3])))
        elif section == "BOND":
            config = next((int(p.split("=")[1]) for p in parts[4:] if p.startswith("CFG=")), 0)
            bonds.append((int(parts[1]), int(parts[2]) - 1, int(parts[3]) - 1, config))
        elif section == "SGROUP" and parts[1] == "SRU":
            members = [int(v) - 1 for v in re.search(r"ATOMS=\(\d+ ([^)]*)\)", body).group(1).split()]
            brackets = [[float(v) for v in found.split()[1:]] for found in re.findall(r"BRKXYZ=\(([^)]*)\)", body)]
            label = re.search(r"LABEL=(\S+)", body)
            sru = {"atoms": members, "brackets": brackets, "label": label.group(1) if label else "n"}
    return atoms, bonds, sru


def repeat_unit(block, cx, cy, scale):
    """A skeletal drawing centred on (cx, cy); returns (svg, half-width, half-height)."""
    atoms, bonds, sru = parse_v3000(block)
    xs, ys = [a[1] for a in atoms], [a[2] for a in atoms]
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    def at(x, y):
        return cx + (x - mx) * scale, cy - (y - my) * scale

    points = [at(x, y) for _, x, y in atoms]
    labelled = {i for i, (element, _, _) in enumerate(atoms) if element not in {"C", "*"}}
    out = []
    for order, a, b, config in bonds:
        (x1, y1), (x2, y2) = points[a], points[b]
        length = hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        if a in labelled:
            x1, y1 = x1 + ux * 8, y1 + uy * 8
        if b in labelled:
            x2, y2 = x2 - ux * 8, y2 - uy * 8
        if config == 3:  # hashed wedge, narrow at the stereocentre
            for k in range(1, 7):
                f = k / 6.5
                px, py = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
                half = 0.6 + 3.4 * f
                out.append(line(px - uy * half, py + ux * half, px + uy * half, py - ux * half, "bond"))
        elif config == 1:  # solid wedge
            out.append(path(f"M{num(x1)} {num(y1)}L{num(x2 - uy * 3.6)} {num(y2 + ux * 3.6)}"
                            f"L{num(x2 + uy * 3.6)} {num(y2 - ux * 3.6)}Z", "bond wedge"))
        elif order == 2:
            for side in (-2.3, 2.3):
                out.append(line(x1 - uy * side, y1 + ux * side, x2 - uy * side, y2 + ux * side, "bond"))
        else:
            out.append(line(x1, y1, x2, y2, "bond"))
    for i in sorted(labelled):
        out.append(text(points[i][0], points[i][1] + 5, atoms[i][0], "atom", "middle"))
    extent = list(points)
    if sru:
        sx = sum(points[i][0] for i in sru["atoms"]) / len(sru["atoms"])
        right = None
        for values in sru["brackets"]:
            (bx1, by1), (bx2, by2) = at(values[0], values[1]), at(values[3], values[4])
            tick = 5 if sx > bx1 else -5
            out.append(path(f"M{num(bx1 + tick)} {num(by1)}L{num(bx1)} {num(by1)}L{num(bx2)} {num(by2)}"
                            f"L{num(bx2 + tick)} {num(by2)}", "bracket"))
            extent += [(bx1, by1), (bx2, by2)]
            if right is None or bx1 > right[0]:
                right = (bx1, max(by1, by2))
        out.append(text(right[0] + 3, right[1] + 9, sru["label"], "bracket-label"))
    half_w = max(abs(x - cx) for x, _ in extent) + 6
    half_h = max(abs(y - cy) for _, y in extent) + 6
    return "".join(out), half_w, half_h


# ---------------------------------------------------------------------------
# Polylactide in the graph
# ---------------------------------------------------------------------------

def clip(node, toward, gap=5.0):
    """Where a line from a node's centre towards a point leaves the node's outline."""
    x, y = node["at"]
    dx, dy = toward[0] - x, toward[1] - y
    if node["shape"] == "circle":
        d = hypot(dx, dy) or 1.0
        return x + dx / d * (node["r"] + gap), y + dy / d * (node["r"] + gap)
    hw, hh = node["w"] / 2 + gap, node["h"] / 2 + gap
    t = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return x + dx * t, y + dy * t


def link(a, b, cls="edge"):
    """An arrow from node a to node b; returns (svg, start, end)."""
    start, end = clip(a, b["at"]), clip(b, a["at"])
    return arrow(*start, *end, cls), start, end


def predicate(x, y, label, anchor="middle"):
    return text(x, y, label, "pred", anchor, term="predicate")


def concept_node(at, r, name, identifier, side, main=False):
    """A polymer family: a circle, its name and its identifier beside it."""
    x, y = at
    out = [circle(x, y, r, "n-concept n-main" if main else "n-concept")]
    if side == "above":
        tx, ty, anchor = x, y - r - 24, "middle"
    elif side == "below":
        tx, ty, anchor = x, y + r + 18, "middle"
    else:
        tx, ty, anchor = x + r + 10, y - 2, "start"
    out.append(text(tx, ty, name, "lbl lbl-strong", anchor))
    out.append(text(tx, ty + 16, identifier, "mono", anchor, term="identifier"))
    if main:
        out.append(text(x, y + 4.5, "PLA", "lbl lbl-node", "middle"))
    return {"shape": "circle", "at": at, "r": r}, "".join(out)


def facet_pill(left, cy, label):
    w = text_width(label, 12.5) + 22
    node = {"shape": "rect", "at": (left + w / 2, cy), "w": w, "h": 26}
    return node, rect(left, cy - 13, w, 26, "n-facet", rx=13) + text(left + w / 2, cy + 4.5, label, "lbl lbl-sm", "middle", "facet")


def process_box(cx, cy, w, rows):
    h = 14 + 16 * len(rows)
    start = cy - (len(rows) - 1) * 8 + 4.5
    node = {"shape": "rect", "at": (cx, cy), "w": w, "h": h}
    drawn = (rect(cx - w / 2, cy - h / 2, w, h, "n-process") + lines(cx, start, rows, 16, "lbl lbl-sm", "middle")
             + text(cx - w / 2 + 2, cy - h / 2 - 8, "Process", "cap"))
    return node, drawn


def page_icon(x, y):
    """A folded-corner page, 22 by 28, centred on (x, y)."""
    l, t = x - 11, y - 14
    return path(f"M{num(l)} {num(t)}H{num(l + 15)}L{num(l + 22)} {num(t + 7)}V{num(t + 28)}H{num(l)}Z"
                f"M{num(l + 15)} {num(t)}V{num(t + 7)}H{num(l + 22)}", "n-evidence")


def diamond(x, y, size=7):
    return path(f"M{num(x)} {num(y - size)}L{num(x + size)} {num(y)}L{num(x)} {num(y + size)}L{num(x - size)} {num(y)}Z", "claim")


EVIDENCE_LINES = ["ChEBI entry 53408,", "poly[(S)-lactic acid]"]
PROCESS_ROWS = ["Catalyst/initiator-controlled", "bulk or solution route"]
FACETS = ["bio based", "biodegradable", "thermoplastic"]


def polylactide_wide(unit_svg, half_w, half_h):
    body = []
    unit_at = (690, 84)
    unit = {"shape": "rect", "at": unit_at, "w": half_w * 2, "h": half_h * 2}
    body.append(f'<g class="structure">{unit_svg}</g>')
    body.append(text(unit_at[0], unit_at[1] + half_h + 14, "poly-L-lactide unit", "lbl lbl-sm", "middle", "repeat-unit"))
    body.append(text(unit_at[0], unit_at[1] + half_h + 29, "+1 structure (the D unit)", "lbl lbl-xs muted", "middle"))

    family_at = (400, 222)
    family = {"shape": "circle", "at": family_at, "r": 28}
    plla = {"shape": "circle", "at": (120, 100), "r": 13}
    plga = {"shape": "circle", "at": (120, 326), "r": 13}

    for member, dy in ((plla, -8), (plga, 18)):
        drawn, start, end = link(family, member)
        body.append(drawn)
        body.append(predicate((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + dy, "narrower"))

    drawn, start, end = link(family, unit)
    body.append(drawn)
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    body.append(diamond(mx, my))
    body.append(predicate(mx - 14, my - 14, "hasStructure", "end"))
    body.append(text(mx, my + 24, "claim", "lbl lbl-xs", "middle", "claim"))

    evidence_at = (690, 250)
    evidence = {"shape": "rect", "at": evidence_at, "w": 22, "h": 28}
    ex, ey = clip(evidence, (mx, my), 4)
    sx, sy = mx + (ex - mx) * 0.07, my + (ey - my) * 0.07
    body.append(arrow(sx, sy, ex, ey, "edge dash"))
    body.append(predicate((mx + ex) / 2 - 4, (my + ey) / 2 + 17, "evidence", "end"))
    body.append(page_icon(*evidence_at))
    body.append(text(evidence_at[0] + 20, evidence_at[1] - 6, "Evidence", "cap", "start", "source"))
    body.append(lines(evidence_at[0] + 20, evidence_at[1] + 10, EVIDENCE_LINES, 15, "lbl lbl-xs", "start"))

    process, drawn = process_box(392, 404, 230, PROCESS_ROWS)
    body.append(drawn)
    drawn, start, end = link(family, process)
    body.append(drawn)
    body.append(predicate((start[0] + end[0]) / 2 - 10, (start[1] + end[1]) / 2 + 4, "hasProcess", "end"))

    tops = [336, 372, 408]
    for label, cy in zip(FACETS, tops):
        node, drawn = facet_pill(684, cy, label)
        body.append(drawn)
        end = (678, cy)
        body.append(arrow(*clip(family, end), *end, "edge edge-fan"))
    body.append(text(684 + 2, 440, "+6 more facets", "lbl lbl-xs muted"))
    body.append(predicate(548, 296, "hasFacet"))

    _, drawn = concept_node((120, 100), 13, "Poly(L-lactide)", "wop-000218", "below")
    body.append(drawn)
    _, drawn = concept_node((120, 326), 13, "Poly(lactide-co-glycolide)", "wop-000220", "below")
    body.append(drawn)
    _, drawn = concept_node(family_at, 28, "Polylactide family", "wop-000217", "above", main=True)
    body.append(drawn)
    return 880, 452, "".join(body)


def polylactide_narrow(unit_svg_at):
    """A tree: the family at the top, one row per relationship, each predicate on its branch."""
    body = []
    spine_x, child_x = 30, 150
    _, drawn = concept_node((spine_x, 40), 20, "Polylactide family", "wop-000217", "right", main=True)
    body.append(drawn)
    rows = []

    def branch(y, label, end_x=child_x - 8):
        rows.append(y)
        body.append(arrow(spine_x, y, end_x, y))
        body.append(predicate(spine_x + 12, y - 7, label, "start"))

    for y, name, identifier in ((112, "Poly(L-lactide)", "wop-000218"), (168, "Poly(lactide-co-glycolide)", "wop-000220")):
        branch(y, "narrower", child_x - 16)
        _, drawn = concept_node((child_x, y), 9, name, identifier, "right")
        body.append(drawn)

    unit_svg, half_w, half_h = unit_svg_at(child_x + 76, 262)
    branch(262, "hasStructure", child_x + 76 - half_w - 2)
    body.append(diamond(122, 262))
    body.append(f'<g class="structure">{unit_svg}</g>')
    body.append(text(child_x + 76, 262 + half_h + 14, "poly-L-lactide unit", "lbl lbl-sm", "middle", "repeat-unit"))
    body.append(text(child_x + 76, 262 + half_h + 29, "+1 structure (the D unit)", "lbl lbl-xs muted", "middle"))
    body.append(text(114, 286, "claim", "lbl lbl-xs", "end", "claim"))
    body.append(arrow(122, 271, 122, 384, "edge dash"))
    body.append(predicate(114, 340, "evidence", "end"))
    body.append(page_icon(122, 404))
    body.append(text(142, 398, "Evidence", "cap", "start", "source"))
    body.append(lines(142, 414, EVIDENCE_LINES, 15, "lbl lbl-xs", "start"))

    branch(500, "hasProcess", child_x - 10)
    _, drawn = process_box(child_x + 100, 500, 200, ["Catalyst/initiator-", "controlled bulk or", "solution route"])
    body.append(drawn)

    branch(584, "hasFacet", child_x - 10)
    left = child_x
    for i, label in enumerate(FACETS):
        if i == 2:
            left = child_x
        node, drawn = facet_pill(left, 584 if i < 2 else 620, label)
        body.append(drawn)
        left += node["w"] + 8
    body.append(text(left + 2, 624, "+6 more", "lbl lbl-xs muted"))
    body.insert(0, line(spine_x, 62, spine_x, rows[-1]))
    return 360, 648, "".join(body)


def polylactide_figure(db, narrow=False):
    structure = molfile(db, "structure:poly-l-lactide-unit")
    if narrow:
        width, height, body = polylactide_narrow(lambda x, y: repeat_unit(structure, x, y, 24.0))
    else:
        width, height, body = polylactide_wide(*repeat_unit(structure, 690, 84, 26.0))
    description = ("The polylactide family, wop-000217, in the seed graph. It has two narrower members, "
                   "poly(L-lactide) and poly(lactide-co-glycolide). It has a structure, the poly-L-lactide repeat "
                   "unit, through a claim whose evidence is ChEBI entry 53408. It has a process, a catalyst- or "
                   "initiator-controlled bulk or solution route, and facets including bio based, biodegradable "
                   "and thermoplastic.")
    return svg(width, height, "Polylactide in the graph", description, body)


# ---------------------------------------------------------------------------
# The loop: the page's opening figure
# ---------------------------------------------------------------------------

# Each step: its name, the lines beneath it as (text, glossary term), and where the label sits.
LOOP_STEPS = [
    ("Ask", [("you", None)], ("middle", 0, -44)),
    ("Answer", [("the research agent", "research-agent")], ("start", 18, -4)),
    ("Save", [("findings and", "finding"), ("source notes", "source-note")], ("start", 14, 28)),
    ("Review", [("a separate reviewer", "reviewer")], ("end", -14, 28)),
    ("Reuse", [("the next question", "cumulative")], ("end", -18, -4)),
]
NARROW_PLACEMENTS = [("middle", 0, -24), ("start", 14, 5), ("start", 10, 26), ("end", -10, 26), ("end", -14, 5)]


def at_angle(cx, cy, r, degrees):
    a = math.radians(degrees)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def loop_figure(narrow=False):
    if narrow:
        width, height, cx, cy, radius, store = 360, 430, 180, 210, 104, 40
    else:
        width, height, cx, cy, radius, store = 600, 580, 300, 290, 150, 58
    angles = [-90 + 72 * i for i in range(5)]
    points = [at_angle(cx, cy, radius, a) for a in angles]
    body = []

    # The ring of steps.
    for i in range(5):
        a1, a2 = angles[i] + 8, angles[(i + 1) % 5] - 8
        if a2 < a1:
            a2 += 360
        (x1, y1), (x2, y2) = at_angle(cx, cy, radius, a1), at_angle(cx, cy, radius, a2)
        body.append(elbow(f"M{num(x1)} {num(y1)}A{radius} {radius} 0 0 1 {num(x2)} {num(y2)}",
                          x2, y2, math.radians(a2) + math.pi / 2, "edge ring"))

    # Open questions: a second, outer loop from Answer back to Ask.
    outer = radius + (36 if narrow else 54)
    start_angle, end_angle = (-30, -68) if narrow else (-28, -70)
    (sx, sy), (ex, ey) = at_angle(cx, cy, outer, start_angle), at_angle(cx, cy, outer, end_angle)
    ask_x, ask_y = points[0]
    leaving = math.radians(end_angle - 90)  # the arc's direction at its end, carried smoothly into Ask
    qx, qy = ex + 24 * math.cos(leaving), ey + 24 * math.sin(leaving)
    tip = (ask_x + 13, ask_y - 4)
    ax, ay = points[1]
    tangent = math.radians(start_angle - 90)  # the arc's direction as it leaves its start
    jx, jy = sx - 28 * math.cos(tangent), sy - 28 * math.sin(tangent)
    body.append(elbow(f"M{num(ax + 7)} {num(ay - 11)}Q{num(jx)} {num(jy)} {num(sx)} {num(sy)}A{outer} {outer} 0 0 0 {num(ex)} {num(ey)}Q{num(qx)} {num(qy)} {num(tip[0])} {num(tip[1])}",
                      *tip, math.atan2(tip[1] - qy, tip[0] - qx), "edge dash outer-arc"))
    if narrow:
        body.append(text(350, 68, "open questions", "pred", "end", "research-queue"))
    else:
        lx, ly = at_angle(cx, cy, outer + 22, -62)
        body.append(text(lx, ly, "open questions", "pred", "start", "research-queue"))
        body.append(text(lx, ly + 16, "the loop can ask itself", "lbl lbl-xs muted", "start"))

    # Saved knowledge at the centre: a disc of findings.
    rng = random.Random(5)
    body.append(circle(cx, cy, store, "store"))
    statuses = (["s-reviewed"] * 7 + ["s-added"] * 5 + ["s-checking"] * 2) if narrow else \
               (["s-reviewed"] * 12 + ["s-added"] * 8 + ["s-checking"] * 2)
    rng.shuffle(statuses)
    spread, dot = (store - 11, 3.4) if narrow else (store - 13, 4.2)
    for i, status in enumerate(statuses):
        r = 6 + spread * math.sqrt((i + 0.5) / len(statuses))
        a = i * 2.39996
        body.append(circle(cx + r * math.cos(a), cy + r * math.sin(a) * 0.9, dot, f"fdot {status}"))
    body.append(text(cx, cy - store - 12, "Saved knowledge", "lbl lbl-strong", "middle"))

    def spoke(i, inward, cls, label=None, offset=(0, 0), anchor="middle", term=None):
        px, py = points[i]
        ux, uy = (px - cx) / radius, (py - cy) / radius
        far, near = (px - ux * 15, py - uy * 15), (cx + ux * (store + 9), cy + uy * (store + 9))
        out = arrow(*(far if inward else near), *(near if inward else far), cls)
        if label and not narrow:
            out += text((far[0] + near[0]) / 2 + offset[0], (far[1] + near[1]) / 2 + offset[1], label, "pred", anchor, term)
        return out

    body.append(spoke(2, True, "edge spoke-accent", "saves", (10, 2), "start"))
    body.append(spoke(3, True, "edge", "labels", (-10, 2), "end"))
    body.append(spoke(1, False, "edge spoke-accent", "read first", (4, 22), "middle", "knowledge-search"))

    # Step nodes and names; the wide figure also says who acts.
    for i, ((name, rows, placement), (x, y)) in enumerate(zip(LOOP_STEPS, points)):
        anchor, dx, dy = NARROW_PLACEMENTS[i] if narrow else placement
        body.append(circle(x, y, 7 if narrow else 8, "step"))
        body.append(text(x + dx, y + dy, name, "lbl step-name", anchor))
        if not narrow:
            for k, (row, term) in enumerate(rows):
                body.append(text(x + dx, y + dy + 17 + 15 * k, row, "lbl lbl-sm muted", anchor, term))

    # Measure sits outside, on demand.
    mx, my = (325, 372) if narrow else (556, 516)
    ax, ay = points[1]
    end = (ax + 6, ay + 15)
    control = (mx + 6, (my + ay) / 2 + 20)
    body.append(elbow(f"M{mx - 5} {my - 11}Q{num(control[0])} {num(control[1])} {num(end[0])} {num(end[1])}", *end,
                      math.atan2(end[1] - control[1], end[0] - control[0]), "edge dash"))
    body.append(circle(mx, my, 6, "step step-satellite"))
    body.append(text(mx, my + 26, "Measure", "lbl step-name step-minor", "middle"))
    body.append(text(mx, my + 42, "on demand", "lbl lbl-sm muted", "middle", "parity-set"))

    description = ("The loop. Ask (you), Answer (the research agent), Save (findings and source notes), Review (a "
                   "separate reviewer) and Reuse (the next question) form a ring around saved knowledge: Save writes "
                   "into it, the reviewer labels it, and Answer reads it first. An outer loop carries each answer's "
                   "open questions back to Ask, so the loop can ask them itself. Measure sits outside and runs on demand.")
    return svg(width, height, "The loop", description, "".join(body), "fig-loop")


# ---------------------------------------------------------------------------
# Who vouches for a fact
# ---------------------------------------------------------------------------

BADGES = {
    "added": ("Added", "s-added", "added"),
    "checking": ("Needs checking", "s-checking", "needs-checking"),
    "reviewed": ("Reviewed", "s-reviewed", "reviewed"),
    "rejected": ("Rejected", "s-rejected", "rejected"),
}


def badge_width(kind):
    return text_width(BADGES[kind][0], 12, 0.6) + 32


def status_card(x, y, kind, caption):
    """A status pill like the app's badge with a caption beneath; (x, y) is its top-left."""
    label, cls, term = BADGES[kind]
    w = badge_width(kind)
    return (rect(x, y, w, 24, f"badge-shape {cls}", rx=12) + circle(x + 13, y + 12, 3.5, f"badge-dot {cls}")
            + text(x + 22, y + 16.3, label, f"lbl badge-text {cls}", term=term)
            + lines(x + 2, y + 42, caption, 14, "lbl lbl-xs muted"))


def reviewer_box(x, y, w):
    return (rect(x, y, w, 52, "card", rx=10) + text(x + w / 2, y + 23, "Reviewer", "lbl lbl-strong", "middle", "reviewer")
            + text(x + w / 2, y + 40, "opens the source", "lbl lbl-xs muted", "middle"))


def new_finding(x, y, w):
    return rect(x, y, w, 36, "card", rx=18) + text(x + w / 2, y + 23, "New finding", "lbl lbl-strong", "middle", "finding")


OUTCOMES = [("reviewed", ["the source supports it"]), ("checking", ["could not confirm: a lead"]),
            ("rejected", ["hidden from search,", "reason kept"])]


def vouch_figure(narrow=False):
    body = []
    if narrow:
        width, height = 360, 612
        added_x, check_x = 16, 196
        added_mid, check_mid = added_x + badge_width("added") / 2, check_x + badge_width("checking") / 2
        body.append(new_finding(110, 10, 140))
        body.append(elbow(f"M180 46V64H{num(added_mid)}V90", added_mid, 90, math.pi / 2))
        body.append(elbow(f"M180 64H{num(check_mid)}V90", check_mid, 90, math.pi / 2))
        body.append(status_card(added_x, 96, "added", ["read directly in", "the source"]))
        body.append(status_card(check_x, 96, "checking", ["unsure, or the excerpt", "lacks the number"]))
        body.append(reviewer_box(196, 206, 148))
        body.append(arrow(check_mid, 166, check_mid, 200))
        body.append(elbow("M106 108H150V232H190", 190, 232, 0.0, "edge dash"))
        body.append(text(156, 196, "1 in 5", "pred", "start", "spot-check"))
        for i, (kind, caption) in enumerate(OUTCOMES):
            top = 298 + i * 74
            body.append(elbow(f"M270 258V276H182V{top + 12}H200", 200, top + 12, 0.0))
            body.append(status_card(206, top, kind, caption))
        body.append(arrow(added_mid, 166, added_mid, 292))
        body.append(status_card(added_x, 298, "added", ["not sampled:", "stays Added"]))
        body.append(line(16, 540, 344, 540, "edge dash faint"))
        body.append(text(16, 564, "Imported draft (seed)", "lbl lbl-sm", term="imported-draft"))
        body.append(text(16, 582, "source-backed, never shown as reviewed", "lbl lbl-xs muted"))
    else:
        width, height = 880, 322
        body.append(new_finding(0, 120, 132))
        body.append(elbow("M132 138H162V74H214", 214, 74, 0.0))
        body.append(elbow("M162 138V204H214", 214, 204, 0.0))
        body.append(status_card(222, 62, "added", ["read directly in the source"]))
        body.append(status_card(222, 192, "checking", ["unsure, or the excerpt", "lacks the number"]))
        body.append(reviewer_box(470, 112, 132))
        check_end = 222 + badge_width("checking") + 8
        body.append(elbow(f"M{num(check_end)} 204H430V150H464", 464, 150, 0.0))
        added_end = 222 + badge_width("added") + 8
        body.append(path(f"M{num(added_end)} 74H404"))
        body.append(elbow("M404 74V30H690", 690, 30, 0.0))
        body.append(elbow("M404 74H430V126H464", 464, 126, 0.0, "edge dash"))
        body.append(text(438, 102, "1 in 5", "pred", "start", "spot-check"))
        body.append(status_card(700, 18, "added", ["not sampled: stays Added"]))
        for i, (kind, caption) in enumerate(OUTCOMES):
            y = 108 + i * 68
            body.append(elbow(f"M602 138H650V{y}H690", 690, y, 0.0))
            body.append(status_card(700, y - 12, kind, [" ".join(caption)]))
        body.append(line(0, 290, 880, 290, "edge dash faint"))
        body.append(text(0, 312, "Imported draft (seed)", "lbl lbl-sm", term="imported-draft"))
        body.append(text(154, 312, "source-backed, never shown as reviewed", "lbl lbl-xs muted"))
    description = ("A new finding is either added, when the research agent read it directly in the source, or marked "
                   "needs checking, when it was unsure or the excerpt lacks the number. A reviewer opens the source "
                   "for every finding that needs checking and for a one-in-five sample of added ones, and labels "
                   "each reviewed, needs checking (could not confirm) or rejected (hidden from search, with the "
                   "reason kept). Added findings that are not sampled stay added. Imported seed content is a separate "
                   "lane: source-backed, never shown as reviewed.")
    return svg(width, height, "Who vouches for a fact", description, "".join(body))


# ---------------------------------------------------------------------------
# How it accumulates (an illustration, not measured data)
# ---------------------------------------------------------------------------

PANELS = [
    ("First question about PLA", 6, {2: "s-checking"}, set(), 0.0),
    ("A few questions later", 15, {11: "s-checking"}, {0, 1, 2, 4, 6}, 0.4),
    ("Later", 26, {19: "s-checking", 23: "s-checking"}, {0, 1, 2, 3, 4, 5, 6, 8, 9, 11, 12, 14, 15, 17}, 0.72),
]


def accumulation_panel(x, y, w, title, count, checking, reviewed, saved_share, compact=False, centre=98, bar=176):
    out = [text(x + w / 2, y + 14, title, "lbl lbl-strong", "middle")]
    cx, cy = x + w / 2, y + centre
    for i in range(count):
        r = 25 + 5.4 * math.sqrt(i) if compact else 34 + 8.5 * math.sqrt(i)
        a = i * 2.39996 - 1.2
        px, py = cx + r * math.cos(a), cy + r * math.sin(a) * 0.72
        out.append(line(cx, cy, px, py, "spoke"))
        status = checking.get(i) or ("s-reviewed" if i in reviewed else "s-added")
        out.append(circle(px, py, 3.8 if compact else 4.6, f"fdot {status}"))
    out.append(circle(cx, cy, 13 if compact else 16, "n-concept n-main"))
    out.append(text(cx, cy + 4, "PLA", "lbl lbl-node", "middle"))
    bar_w = w - 40
    out.append(rect(x + 20, y + bar, bar_w, 10, "bar-new", rx=5))
    if saved_share:
        out.append(rect(x + 20, y + bar, bar_w * saved_share, 10, "bar-saved", rx=5))
    return "".join(out)


LEGEND = [("dot", "s-reviewed", "Reviewed", "reviewed"), ("dot", "s-added", "Added", "added"),
          ("dot", "s-checking", "Needs checking", "needs-checking"),
          ("bar", "bar-saved", "facts from saved knowledge", None), ("bar", "bar-new", "facts from new reading", None)]


def legend(x, y, rows):
    out = []
    for row, items in enumerate(rows):
        cursor, base = x, y + row * 22
        for kind, cls, label, term in (LEGEND[i] for i in items):
            if kind == "dot":
                out.append(circle(cursor + 5, base - 4, 4.6, f"fdot {cls}"))
                out.append(text(cursor + 15, base, label, "lbl lbl-xs", term=term))
                cursor += 15 + text_width(label, 12) + 18
            else:
                out.append(rect(cursor, base - 9, 26, 10, cls, rx=5))
                out.append(text(cursor + 34, base, label, "lbl lbl-xs"))
                cursor += 34 + text_width(label, 12) + 18
    return "".join(out)


def accumulation_figure(narrow=False):
    body = []
    if narrow:
        width, height = 360, 240
        for x, title, panel in ((5, "First question", PANELS[0]), (185, "Later", PANELS[2])):
            body.append(accumulation_panel(x, 0, 170, title, *panel[1:], compact=True, centre=82, bar=142))
        body.append(legend(20, 186, [[0, 1, 2], [3], [4]]))
    else:
        width, height = 880, 238
        for i, panel in enumerate(PANELS):
            body.append(accumulation_panel(i * 300, 0, 280, *panel))
        body.append(legend(20, 230, [[0, 1, 2, 3, 4]]))
    description = ("An illustration, not measured data. Snapshots of the findings attached to PLA. After the first "
                   "question there are a few added findings and one that needs checking, and every fact in the answer "
                   "comes from new reading. Later there are many more findings, most of them reviewed, and most of "
                   "each answer's facts come from saved knowledge.")
    return svg(width, height, "How knowledge accumulates", description, "".join(body))


# ---------------------------------------------------------------------------

def figures(root=ROOT):
    db = release_database(root)
    try:
        return {
            "fig-loop.svg": loop_figure(),
            "fig-loop-narrow.svg": loop_figure(narrow=True),
            "fig-accumulation.svg": accumulation_figure(),
            "fig-accumulation-narrow.svg": accumulation_figure(narrow=True),
            "fig-who-vouches.svg": vouch_figure(),
            "fig-who-vouches-narrow.svg": vouch_figure(narrow=True),
            "fig-seed-graph.svg": seed_graph_figure(db, 1240, 340),
            "fig-seed-graph-narrow.svg": seed_graph_figure(db, 360, 320),
            "fig-polylactide.svg": polylactide_figure(db),
            "fig-polylactide-narrow.svg": polylactide_figure(db, narrow=True),
        }
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed figures instead of writing")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root holding releases/")
    options = parser.parse_args(argv)
    drawn = figures(options.root)
    if options.check:
        stale = [name for name, content in drawn.items()
                 if not (OUTPUT / name).is_file() or (OUTPUT / name).read_text(encoding="utf-8") != content]
        extra = sorted(p.name for p in OUTPUT.glob("*.svg") if p.name not in drawn)
        for name in stale:
            print(f"stale: {name}")
        for name in extra:
            print(f"not generated: {name}")
        return 1 if stale or extra else 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, content in drawn.items():
        (OUTPUT / name).write_text(content, encoding="utf-8")
    print(f"wrote {len(drawn)} figures to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
