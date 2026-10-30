#!/usr/bin/env python3
"""Figures 1 and 2 of the Macromolecules manuscript, and the TOC graphic: schematics drawn as editable SVG masters
with PDF and 600 dpi PNG exports (`kit.py`), 7 in wide (ACS double column; the TOC graphic 3.25 x 1.75 in).

Every number and every example drawn is read here from a file, never typed in, and the script stops if a file does not
say what the manuscript says (`facts()`):

- the frozen code at tag study-freeze-2 (worktree `.oopc/study/freeze-2`, read only, parsed with `ast`, never imported):
  the researcher prompt and its hash, the depth budgets, the search limits, the spot-check rate, the review time limit;
- the released code at tag study-freeze-4 (0.13.0, worktree `.oopc/study/freeze-4`, parsed the same way), which the
  branches are drawn as: the answer is shown at once and the session resumes in the background to save what it read.
  Its prompt (`RESEARCHER` and `DEPOSIT`) gives the hash drawn, checked against the confirmation run's pins, and the
  budgets, limits and rates drawn must be the same in both;
- the improvement steps of the recursive test and the restarts (`studies/macromolecules/recursive/`): edit limits,
  the token-ratio limit and the minimum number of pairs, and the recursive test's three decisions;
- the released knowledge snapshot `oopc-knowledge-db1fc22ca88a0c0b45b9218b` (`findings.jsonl`, `manifest.json`): the
  finding card of Fig. 1c, the PVC values of Fig. 1a and the PAEK lineage counts;
- the seed release `oopc-6ad56d8b354d053bcc3cf3a1` (`graph.sqlite`, opened read only): record counts, family links,
  abbreviations and trade names;
- A1's outputs on KF (`table1/table1.json`, `dataset-kf/growth.json`): the question count and the growth curve.

What each element of the figures rests on is listed in SOURCES.md beside this file.

    OOPC_STUDY_ROOT=<main checkout> python -B draw.py [--out DIR]
"""
import argparse, ast, collections, hashlib, json, os, re, sqlite3, subprocess, sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit  # noqa: E402
from kit import (BAND, GRID, HAIR, INK, INK2, LETTER, LIGHT, LINE, MUTED, P, RESEARCHER, SIZE, SMALL, STATUS,  # noqa
                 SURFACE, TINY, Canvas, badge, check, cross, document, store, tinted, width, wrap)

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]


def _main_checkout():
    """The main checkout, where the private records live, also when this file is in a git worktree."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=HERE,
                                capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        return STUDY.parents[1]


ROOT = Path(os.environ.get("OOPC_STUDY_ROOT") or _main_checkout())
FREEZE = ROOT / ".oopc/study/freeze-2"
RELEASED = ROOT / ".oopc/study/freeze-4"
AFTER = "after each answer, in the background"  # the lower branch of Fig. 1b and Fig. 2d, as the released code runs it


def _constants(path, names=None):
    """Literal module-level constants of a Python file, parsed, not imported."""
    values = {}
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = value
                elif isinstance(target, ast.Tuple) and isinstance(value, tuple):
                    values.update((t.id, v) for t, v in zip(target.elts, value))
    return {k: v for k, v in values.items() if names is None or k in names}


def _default(path, function, argument):
    """The default value of `argument` in `function` of a Python file."""
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            args = node.args
            pairs = list(zip(args.kwonlyargs, args.kw_defaults)) + list(zip(args.args[::-1], args.defaults[::-1]))
            for arg, default in pairs:
                if arg.arg == argument:
                    return ast.literal_eval(default)
    raise SystemExit("no default %s in %s" % (argument, function))


def _need(condition, what):
    if not condition:
        raise SystemExit("refusing to draw: " + what)


def facts():
    """Everything the figures draw, read from the frozen code, the released snapshot and A1's outputs."""
    kf = _constants(STUDY / "analysis/kf.py")
    snapshot_dir = ROOT / ".oopc/study/release/knowledge-study-freeze-2"
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    _need(manifest["snapshotId"] == kf["SNAPSHOT_ID"] and manifest["graphRelease"] == kf["RELEASE_ID"],
          "the released snapshot is not KF's")
    findings = {}
    with open(snapshot_dir / "findings.jsonl", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            findings[row["id"]] = row
    _need(len(findings) == manifest["counts"]["findings"], "snapshot finding count")

    # The frozen code.
    ask = _constants(FREEZE / "oopc/ask.py", {"DEPTHS", "RESEARCHER"})
    frozen_prompt = hashlib.sha256(ask["RESEARCHER"].encode()).hexdigest()[:12]
    _need(frozen_prompt == kf["PROMPT"], "the frozen prompt hash is %s, not %s" % (frozen_prompt, kf["PROMPT"]))
    knowledge_py = FREEZE / "oopc/knowledge.py"
    knowledge = _constants(knowledge_py, {"FILL", "SAME_SOURCE", "MAX_FINDINGS"})
    source = knowledge_py.read_text(encoding="utf-8")
    limits = re.search(r"limit = min\(max\(int\(limit\), (\d+)\), (\d+)\)", source)
    notes = re.search(r"words, (\d+) if compact else limit\)", source)
    _need(limits and notes and "search(self.root, args[\"q\"], args.get(\"limit\", 10), compact=True)" in source,
          "search limits in the frozen knowledge.py")
    spot = _default(knowledge_py, "deposit", "spot_check_rate")
    review_seconds = _constants(FREEZE / "oopc/reviewer.py", {"REVIEW_SECONDS"})["REVIEW_SECONDS"]

    # The released code: its prompt is drawn, and what else is drawn must not have changed since the frozen code.
    released = _constants(RELEASED / "oopc/ask.py", {"DEPTHS", "RESEARCHER", "DEPOSIT"})
    prompt = hashlib.sha256((released["RESEARCHER"] + "\n" + released["DEPOSIT"]).encode()).hexdigest()[:12]
    pins = json.loads((ROOT / ".oopc/study/analysis/confirm/results.json").read_text(encoding="utf-8"))["meta"]["pins"]
    _need(prompt == pins["promptVersion"], "the released prompt hash is %s, not the confirmation run's %s"
          % (prompt, pins["promptVersion"]))
    released_py = RELEASED / "oopc/knowledge.py"
    _need(released["DEPTHS"] == ask["DEPTHS"]
          and _constants(released_py, {"FILL", "SAME_SOURCE", "MAX_FINDINGS"}) == knowledge
          and all(re.search(p, released_py.read_text(encoding="utf-8")) for p in (re.escape(limits.group(0)),
                                                                                 re.escape(notes.group(0))))
          and _default(released_py, "deposit", "spot_check_rate") == spot
          and _constants(RELEASED / "oopc/reviewer.py", {"REVIEW_SECONDS"})["REVIEW_SECONDS"] == review_seconds,
          "a budget, limit or rate drawn differs between the frozen and the released code")
    parity = json.loads((FREEZE / "benchmarks/parity.json").read_text(encoding="utf-8"))["questions"]
    recursive = _constants(STUDY / "recursive/recursive.py", {"TOKEN_LIMIT", "MIN_PAIRS"})
    restart = _constants(STUDY / "recursive/restart.py", {"EDIT_LIMITS"})
    rounds = json.loads((ROOT / ".oopc/loop/harness/2026-10-recursive/rounds.json").read_text(encoding="utf-8"))
    per_round = collections.Counter(task["round"] for task in rounds)
    _need(set(per_round.values()) == {100}, "recursive-test rounds of 100 tasks")
    dev = json.loads((ROOT / ".oopc/loop/harness/2026-10-recursive/dev.json").read_text(encoding="utf-8"))
    dev = len(dev["questions"] if isinstance(dev, dict) else dev)
    _need(dev == 30 and "30 questions" in (STUDY / "recursive/recursive.py").read_text(encoding="utf-8"),
          "30 development questions")
    decisions = []
    for r in (1, 2, 3):
        path = ROOT / (".oopc/loop/harness/2026-10-recursive/eval/round-%d/dev/decision.json" % r)
        decisions.append(json.loads(path.read_text(encoding="utf-8"))["adopted"])

    # The seed release.
    graph = sqlite3.connect((ROOT / "releases" / kf["RELEASE_ID"] / "graph.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        by_type = dict(graph.execute("SELECT type, count(*) FROM records GROUP BY type"))
        labels = dict(graph.execute("SELECT id, label FROM records WHERE type='PolymerConcept'"))
        broader = collections.defaultdict(set)
        for s, o in graph.execute("SELECT subject, object FROM edges WHERE predicate='broader'"):
            broader[s].add(o)
        abbreviations, trade = collections.defaultdict(list), {}
        for id_, text in graph.execute("SELECT id, json FROM records WHERE type='PolymerConcept'"):
            record = json.loads(text)
            for a in record.get("abbreviations") or []:
                abbreviations[a].append(record["label"])
            for t in record.get("tradeNames") or []:
                trade[t["name"]] = record["label"]
    finally:
        graph.close()

    table1 = json.loads((ROOT / ".oopc/study/analysis/table1/table1.json").read_text(encoding="utf-8"))
    growth = json.loads((ROOT / ".oopc/study/analysis/dataset-kf/growth.json").read_text(encoding="utf-8"))
    for data in (table1, growth):
        _need(data["meta"]["knowledgeSnapshot"] == kf["SNAPSHOT_ID"], "A1 output not built on KF")
    _need(table1["seed"]["byType"] == by_type, "seed record counts differ from Table 1")

    # PAEK lineage: the family, its members and their findings by status.
    family = next(i for i, l in labels.items() if l == "Poly(aryl ether ketone) family")
    members = sorted((i for i, up in broader.items() if family in up), key=lambda i: labels[i])
    by_polymer = collections.defaultdict(collections.Counter)
    for row in findings.values():
        by_polymer[row.get("polymer")][row["statusLabel"]] += 1

    return {
        "kf": kf, "manifest": manifest, "counts": manifest["counts"],
        "questions": table1["questions"]["completedAnswers"],
        "findings": findings, "prompt": prompt, "depths": ask["DEPTHS"], "fill": knowledge["FILL"],
        "sameSource": knowledge["SAME_SOURCE"], "limits": (int(limits.group(1)), int(limits.group(2))),
        "notes": int(notes.group(1)), "spot": spot, "reviewSeconds": review_seconds, "parity": len(parity),
        "tokenLimit": recursive["TOKEN_LIMIT"], "minPairs": recursive["MIN_PAIRS"], "edit": restart["EDIT_LIMITS"],
        "decisions": decisions, "dev": dev, "perRound": 100, "byType": by_type, "labels": labels, "broader": broader,
        "abbreviations": abbreviations, "trade": trade, "family": family, "members": members,
        "byPolymer": by_polymer, "growth": growth,
    }


def n(v):
    return "{:,}".format(v)


def finding(F, identifier):
    row = F["findings"].get(identifier)
    _need(row is not None, "no %s in the snapshot" % identifier)
    return row


# ------------------------------------------------------------------------------------------------ shared pieces

def node(c, x, y, w, h, title, sub=None, color=INK2, fill=SURFACE, sw=HAIR, size=SMALL, bold=True, dash=None,
         title_color=None, rx=2.5, sub_size=TINY):
    """A rounded box with a centred title and an optional wrapped subtitle."""
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=color, sw=sw, dash=dash)
    lines = wrap(sub, w - 5, sub_size) if sub else []
    total = size + len(lines) * sub_size * 1.2
    base = y + (h - total) / 2 + size * 0.78
    c.text(x + w / 2, base, title, size=size, bold=bold, anchor="middle", color=title_color or INK)
    c.lines(x + w / 2, base + sub_size * 1.25, lines, size=sub_size, lead=sub_size * 1.2, anchor="middle",
            color=INK2)


def status_box(c, x, y, w, h, status, sub=None, size=SMALL):
    color = STATUS[status]
    node(c, x, y, w, h, status, sub, color=color, fill=tinted(color, 0.14), sw=LINE, size=size, title_color=INK)


def legend(c, x, y, statuses=None, size=SMALL, gap=8):
    """The four status colours in a row, as dots with labels; returns the end x."""
    for s in statuses or list(STATUS):
        c.circle(x + 2.5, y - size * 0.32, 2.5, fill=STATUS[s])
        c.text(x + 7, y, s, size=size)
        x += 7 + width(s, size) + gap
    return x


TITLES = {"fig1a": "One question, many sources", "fig1b": "Answering and accumulating",
          "fig1c": "Findings filed on polymer identities", "fig1d": "Improvement on two time scales",
          "fig2a": "Data model in two layers", "fig2b": "Polymer resolution and search",
          "fig2c": "The researcher session", "fig2d": "Deposit and review",
          "fig2e": "Scaffold improvement between rounds of questions"}
# A panel function lays out from its origin (x0, y0) over (w, h); its content starts about 13 pt below y0. In a frame,
# the origin sits TOP above the frame's top edge (where the letter and title are), the content PAD inside its sides
# and bottom; frames side by side are GAP apart, and a row's frame starts LIFT below the row, room for its label.
PAD, TOP, GAP, LIFT = 4.5, 7, 6, 4.5


def page(title, desc, F, rows):
    """A 7 in page of framed panels. `rows`: (panel height, [panel functions]) from top to bottom; the panel letter
    is the function name's last character."""
    W = kit.ST["DOUBLE"] * 72
    frames, y = [], LIFT
    for height, panels in rows:
        fw = (W - 1 - GAP * (len(panels) - 1)) / len(panels)
        fh = height - TOP + PAD
        for k, panel in enumerate(panels):
            frames.append((panel, 0.5 + k * (fw + GAP), y, fw, fh))
        y += fh + LIFT + 4.5
    c = Canvas(W / 72, (y - LIFT - 4.5 + 1) / 72, title, desc)
    for panel, x, y, fw, fh in frames:
        letter = panel.__name__[-1]
        with c.group("panel-" + letter):
            c.frame(x, y, fw, fh, letter, TITLES[panel.__name__])
            panel(c, F, x + PAD, y - TOP, fw - 2 * PAD, fh + TOP - PAD)
    return c


# ------------------------------------------------------------------------------------------------ Figure 1

PVC = [  # (source, [(qualifier, finding id)]): Tg values of PVC in KF, read from the snapshot
    ("PVC film, PRESTIGE 200 µm", [("DMA, 1 Hz", "finding:7944458e3bee-19"),
                                   ("DMA, 10 Hz", "finding:7944458e3bee-20")]),
    ("DSC application note", [("neat PVC", "finding:7944458e3bee-2"), ("20 wt% DOP", "finding:7944458e3bee-12")]),
    ("SG-5 PVC plasticizer study", [("pure PVC, DSC", "finding:b9585bbac0ca-2"),
                                    ("50 phr DEHP, DSC", "finding:b9585bbac0ca-1")]),
]
CARD = "finding:7ec2dd2b46e7-1"  # Fig. 1c: Kepstan 6002 PEKK, Tg by modulated DSC, Reviewed
GRADES = {"Poly(ether ketone ketone)": ["Kepstan 6002", "Kimya PEKK-A"]}  # as KF's PEKK findings name them


def value_of(row):
    return ("%s %s" % (row["value"], row.get("unit", ""))).strip()


def pill(c, cx, cy, label, size=SIZE, color=INK, dash=None, extra="", pw=None):
    """A stage pill centred at (cx, cy): `label` bold, then `extra` in regular weight, `pw` wide (else as wide as
    its text needs); returns its width."""
    pw = pw or width(label, size, True) + width(extra, size) + 9
    ph = size + 6
    c.rect(cx - pw / 2, cy - ph / 2, pw, ph, rx=ph / 2, fill=SURFACE, stroke=color, sw=LINE, dash=dash)
    c.text(cx, cy + size * 0.36, [(label, {}), (extra, {"bold": False})] if extra else label, size=size, bold=True,
           anchor="middle", color=color)
    return pw


def fig1a(c, F, x0, y0, w, h):
    # The question.
    qx, qy, qw, qh = x0 + 2, y0 + 58, 50, 30
    c.rect(qx, qy, qw, qh, rx=6, fill=SURFACE, stroke=INK2, sw=LINE)
    c.path("M %s %s L %s %s L %s %s" % (qx + 14, qy + qh, qx + 10, qy + qh + 6, qx + 21, qy + qh), fill=SURFACE,
           stroke=INK2, sw=LINE)
    c.rect(qx + 10.6, qy + qh - 1.2, 9.8, 2.2, fill=SURFACE)
    c.lines(qx + qw / 2, qy + 12.5, [[("What is the T", {}), ("g", {"sub": True})], "of PVC?"], size=SIZE,
            anchor="middle", lead=9)
    # Sources: each reports its own value, for its own grade, specimen, method and conditions.
    cx, cw = x0 + 64, 108
    cy, card_h, gap = y0 + 17, 31, 8
    ends = []
    for k, (label, rows) in enumerate(PVC):
        y = cy + k * (card_h + gap)
        c.line(qx + qw, qy + qh / 2, cx, y + card_h / 2, stroke=LIGHT, sw=HAIR)
        c.rect(cx, y, cw, card_h, rx=2.5, fill=SURFACE, stroke=INK2, sw=HAIR)
        document(c, cx + 4, y + 4, w=8, h=10, color=MUTED, lines=2)
        c.text(cx + 15, y + 9.5, label, size=SMALL, bold=True)
        for j, (qual, fid) in enumerate(rows):
            yy = y + 18.5 + j * 7.6
            c.text(cx + 15, yy, qual, size=SMALL, color=INK2)
            c.text(cx + cw - 5, yy, value_of(finding(F, fid)), size=SMALL, bold=True, anchor="end")
        ends.append(y + card_h / 2)
    # A plain session reads them, answers, and keeps nothing.
    px = x0 + w - 32
    pw = pill(c, px, y0 + 29, "Plain session", color=P)
    for yy in ends:
        c.arrow([(cx + cw + 1, yy), (px - pw / 2 + 2, y0 + 34)], color=LIGHT, sw=HAIR, gap=1)
    c.arrow([(px, y0 + 35.5), (px, y0 + 51)], color=P, sw=LINE)
    document(c, px - 6, y0 + 53, w=12, h=15, color=P, lines=3)
    c.text(px, y0 + 76, "answer", size=SMALL, anchor="middle", color=P)
    c.arrow([(px, y0 + 80), (px, y0 + 89)], color=P, sw=LINE)
    store(c, px - 11, y0 + 91, w=22, h=17, color=LIGHT, sw=HAIR)
    cross(c, px - 5, y0 + 95, s=10, color=P, sw=LINE)
    # The next question starts again from the sources.
    base = cy + 3 * card_h + 2 * gap
    c.curve((px, y0 + 112), (px, y0 + h - 8), (cx + cw * 0.85, y0 + h - 8), (cx + cw * 0.72, base + 1.5),
            color=P, sw=HAIR, dash="2 1.5")
    c.text(cx + cw * 0.72 - 4, y0 + h - 6, "next question", size=SMALL, italic=True, color=P, anchor="end")


def columns(x, w, size=SIZE, optional=True):
    """The three columns of the branches (Fig. 1b, 2c): (centres, widths, Web's "(optional)"). Bubbles in a column
    share a width: Ask and Answer; Web, Reuse and Deposit; Answer and Review."""
    extra = " (optional)" if optional else ""

    def natural(label, more=""):
        return width(label, size, True) + width(more, size) + 9

    widths = (max(natural("Ask"), natural("Answer")), max(natural("Web", extra), natural("Reuse"), natural("Deposit")),
              max(natural("Answer"), natural("Review")))
    c1, c3 = x + 6 + widths[0] / 2, x + w - 6 - widths[2] / 2
    c2 = (c1 + c3) / 2
    _need(c2 - widths[1] / 2 - (c1 + widths[0] / 2) >= 10, "the branches are too wide for their panel")
    return (c1, c2, c3), widths, extra


def question_branch(c, x, y, w, size=SIZE, optional=True, split=4, top=10, bottom=8, shown=False):
    """The each-question branch on its named background from (x, y) over width w: Ask; Web (optional, dashed) above
    Reuse; Answer, with "shown at once" below it if `shown`. Returns (the background's bottom, Ask/Answer's centre y,
    Reuse's bottom, centres, widths)."""
    ph = size + 6
    (c1, c2, c3), (left, mid, right), extra = columns(x, w, size, optional)
    half = (ph + split) / 2
    qb = y + top + ph + split + ph + bottom
    yt = y + top + half + ph / 2
    c.region(x, y, w, qb - y, "each question")
    pill(c, c1, yt, "Ask", size=size, pw=left)
    pill(c, c2, yt - half, "Web", size=size, dash="2.5 1.5", extra=extra, pw=mid)
    pill(c, c2, yt + half, "Reuse", size=size, pw=mid)
    pill(c, c3, yt, "Answer", size=size, pw=right)
    if shown:
        c.text(c3, yt + ph / 2 + SMALL + 1.5, "shown at once", size=SMALL, italic=True, color=INK2, anchor="middle")
        _need(yt + ph / 2 + SMALL + 3 <= qb, "\"shown at once\" overflows its branch")
    for dy in (-half, half):
        c.arrow([(c1 + left / 2, yt), (c2 - mid / 2, yt + dy)], color=INK2, sw=LINE, gap=1.2)
        c.arrow([(c2 + mid / 2, yt + dy), (c3 - right / 2, yt)], color=INK2, sw=LINE, gap=1.2)
    return qb, yt, yt + half + ph / 2, (c1, c2, c3), (left, mid, right)


def loops(c, x, y, w, height, size=SIZE, optional=True, seed_lines=("initial WOP seed",), split=4, top=10,
          bottom=8, store_scale=1.0, shown=False):
    """Panel 1b over (x, y, w, height): two branches around the ontology, which closes the cycle between them.

    Each question (above): Ask; then Web (optional, dashed) and, below it, Reuse, which reads the ontology; then
    Answer, shown at once (written below it if `shown`). After each answer, in the background (below): Answer;
    Deposit, into the ontology once the session's second turn has returned the findings, each Added or Needs checking;
    then, dashed because only the findings that need checking and a sample of Added ones go on, Review, whose verdicts
    go back to the ontology. The ontology starts from the initial WOP seed. The two backgrounds are equally tall, and
    the gaps above and below the ontology take whatever height is left, so the panel is filled; returns the bottom y.
    `optional` writes "(optional)" after Web."""
    ph = size + 6
    sw_, sh = 2.4 * ph * store_scale, 1.7 * ph * store_scale
    region = top + ph + split + ph + bottom
    gap = (height - 2 * region - sh) / 2
    _need(gap >= 9, "the branches are too tall for their panel (gap %.1f)" % gap)
    qb, _, reuse_bottom, (c1, c2, c3), (left, mid, right) = question_branch(c, x, y, w, size, optional, split, top,
                                                                             bottom, shown)
    # The ontology between them: read by Reuse, written by Deposit and Review, started by the seed.
    st = qb + gap
    store(c, c2 - sw_ / 2, st, w=sw_, h=sh, color=RESEARCHER, sw=LINE)
    c.text(c2 + sw_ / 2 + 4, st + 7, "ontology", size=SMALL, bold=True, color=RESEARCHER)
    c.arrow([(c2, st + 0.5), (c2, reuse_bottom + 0.5)], color=RESEARCHER, sw=LINE, gap=0.6)
    seed_y = st + sh * 0.55
    c.arrow([(c2 - sw_ / 2 - 22, seed_y), (c2 - sw_ / 2 - 0.5, seed_y)], color=STATUS["Reviewed"], sw=LINE, gap=0.5)
    lead = SMALL * 1.15
    c.lines(c2 - sw_ / 2 - 25, seed_y + 2.3 - (len(seed_lines) - 1) * lead / 2, list(seed_lines), size=SMALL,
            bold=True, color=STATUS["Reviewed"], anchor="end", lead=lead)
    # After each answer.
    ay = st + sh + gap
    ab = ay + region
    yb = ay + top + (region - top - bottom) / 2
    c.region(x, ay, w, ab - ay, AFTER)
    pill(c, c1, yb, "Answer", size=size, pw=left)
    pill(c, c2, yb, "Deposit", size=size, pw=mid)
    pill(c, c3, yb, "Review", size=size, pw=right)
    c.arrow([(c1 + left / 2, yb), (c2 - mid / 2, yb)], color=INK2, sw=LINE, gap=1.2)
    c.arrow([(c2 + mid / 2, yb), (c3 - right / 2, yb)], color=INK2, sw=LINE, gap=1.2, dash="2.5 1.5")
    c.arrow([(c2, yb - ph / 2), (c2, st + sh + 0.5)], color=RESEARCHER, sw=LINE, gap=0.6)
    c.arrow([(c3 - right / 2 + 5, yb - ph / 2), (c2 + sw_ / 2 + 0.5, st + sh * 0.75)], color=RESEARCHER, sw=LINE,
            gap=0.8)
    return ab


def fig1b(c, F, x0, y0, w, h):
    top = y0 + 17  # below the panel's title, room for the first region's name
    bottom = loops(c, x0 + 1, top, w - 2, y0 + h - top, split=5, top=10, bottom=7, store_scale=1.15, shown=True)
    _need(bottom <= y0 + h + 0.01, "panel 1b overflows (%.1f > %.1f)" % (bottom, y0 + h))


def fig1c(c, F, x0, y0, w, h):
    labels, counts = F["labels"], F["byPolymer"]
    abbreviation = {v[0]: k for k, v in F["abbreviations"].items() if len(v) == 1}
    fam = labels[F["family"]]
    # Spine: family, polymers (with their findings by status), grades.
    fx, fy = x0 + 2, y0 + 17
    name = abbreviation.get(fam, fam.replace(" family", "")) + " family"
    node(c, fx, fy, width(name, SMALL, True) + 10, 12, name, None, color=INK2, fill=BAND, sw=HAIR, size=SMALL)
    x_line, y = fx + 6, fy + 20
    most = max(sum(counts[m].values()) for m in F["members"])
    bar_x, bar_w = x_line + 39, 36
    anchor = None
    for member in F["members"]:
        label = labels[member]
        abbr = abbreviation.get(label, label)
        c.path("M %s %s L %s %s L %s %s" % (x_line, fy + 12, x_line, y + 5.5, x_line + 5, y + 5.5), stroke=MUTED,
               sw=HAIR, cap="butt")
        node(c, x_line + 5, y, 30, 11, abbr, None, color=INK2, sw=HAIR, size=SMALL)
        counter, xx = counts[member], bar_x
        for status in STATUS:
            seg = bar_w * counter[status] / most
            if seg:
                c.rect(xx, y + 2.5, seg, 6, fill=STATUS[status])
                xx += seg
        c.text(xx + 3, y + 8, n(sum(counter.values())), size=SMALL, color=INK2)
        y += 16
        for grade in GRADES.get(label, []):
            gx = x_line + 17
            c.path("M %s %s L %s %s L %s %s" % (x_line + 11, y - 5, x_line + 11, y + 5, gx, y + 5),
                   stroke=MUTED, sw=HAIR, dash="1.5 1", cap="butt")
            gw = width(grade, SMALL) + 8
            node(c, gx, y, gw, 10, grade, None, color=MUTED, sw=HAIR, size=SMALL, bold=False, dash="1.5 1")
            if anchor is None and grade in finding(F, CARD)["material"]:
                anchor = (gx + gw, y + 5)
            y += 13
        y += 2
    # One status legend.
    ly = y0 + h - 10
    legend(c, x0 + 2, ly, ["Reviewed", "Added"], size=SMALL, gap=6)
    legend(c, x0 + 2, ly + 8.5, ["Needs checking", "Rejected"], size=SMALL, gap=6)
    # The finding card, as the released snapshot carries it (no excerpt).
    row = finding(F, CARD)
    kx, ky = x0 + 98, y0 + 16
    kw = w - 98
    label_w = width("conditions", SMALL) + 5
    lead = SMALL * 1.15
    fields = [("statement", row["statement"]), ("material", row["material"]), ("property", row["property"]),
              ("value", value_of(row)), ("conditions", row["conditions"]), ("source", "doi:" + row["source"]["doi"]),
              ("locator", row["locator"])]
    body = [(key, wrap(text, kw - label_w - 7, SMALL)) for key, text in fields]
    kh = 13 + sum(len(lines) * lead + 1.3 for _, lines in body) + 13
    c.rect(kx, ky, kw, 12, rx=3, fill=BAND)
    c.rect(kx, ky + 6, kw, 6, fill=BAND)
    c.line(kx, ky + 12, kx + kw, ky + 12, stroke=GRID, sw=HAIR)
    c.rect(kx, ky, kw, kh, rx=3, fill="none", stroke=INK2, sw=LINE)
    c.text(kx + 4, ky + 8.6, row["id"], size=SMALL, bold=True, color=INK2)
    yy = ky + 12 + lead + 1.5
    for key, lines in body:
        c.text(kx + 4, yy, key, size=SMALL, color=MUTED)
        c.lines(kx + label_w + 3, yy, lines, size=SMALL, lead=lead, bold=key == "value")
        yy += len(lines) * lead + 1.3
    c.text(kx + 4, yy + 3, "status", size=SMALL, color=MUTED)
    badge(c, kx + label_w + 3, yy - 3.6, row["statusLabel"], size=SMALL)
    if anchor:
        c.arrow([anchor, (kx - 1, anchor[1])], color=MUTED, sw=HAIR, dash="1.5 1")
    _need(ky + kh <= y0 + h, "the finding card overflows panel c (%.1f > %.1f)" % (ky + kh, y0 + h))


def fig1d(c, F, x0, y0, w, h):
    # Per question: the store grows.
    c.text(x0 + 2, y0 + 22, "Per question: knowledge grows and is reused", size=SMALL, bold=True)
    gx, gy, gw, gh = x0 + 30, y0 + 31, 92, 48
    ends = [(0, 0)] + [(run.get("lastAnswer") or 0, run["endState"]["findings"]["total"])
                       for run in F["growth"]["byRun"]]
    xmax, ymax = max(e[0] for e in ends), max(e[1] for e in ends)
    _need(ymax == F["counts"]["findings"], "growth curve ends at %d findings" % ymax)
    pts = [(gx + gw * a / xmax, gy + gh - gh * f / ymax) for a, f in ends]
    area = " ".join("L %.2f %.2f" % p for p in pts)
    c.path("M %s %s %s L %s %s Z" % (gx, gy + gh, area, gx + gw, gy + gh), fill=tinted(RESEARCHER, 0.16),
           stroke=None)
    c.path("M " + " L ".join("%.2f %.2f" % p for p in pts), stroke=RESEARCHER, sw=LINE)
    c.line(gx, gy + gh, gx + gw + 3, gy + gh, stroke=INK2, sw=HAIR)
    c.line(gx, gy - 2, gx, gy + gh, stroke=INK2, sw=HAIR)
    c.text(gx + gw + 3, gy + gh + 8, "questions", size=SMALL, color=INK2, anchor="end")
    c.text(gx - 3, gy + 4, "findings", size=SMALL, color=INK2, anchor="end")
    # Headline counts.
    tiles = [(n(F["questions"]), "questions"), (n(F["counts"]["findings"]), "findings"),
             (n(F["counts"]["sources"]), "sources"), (n(F["counts"]["polymers"]), "polymers")]
    tw, th = 54, 25
    tx, ty = x0 + w - 2 * tw - 4, y0 + 29
    for k, (num, label) in enumerate(tiles):
        x, y = tx + (k % 2) * (tw + 4), ty + (k // 2) * (th + 4)
        c.rect(x, y, tw, th, rx=2.5, fill=BAND)
        c.text(x + tw / 2, y + 12, num, size=LETTER, bold=True, anchor="middle")
        c.text(x + tw / 2, y + 20.5, label, size=SMALL, anchor="middle", color=INK2)
    # Per round: the researcher's prompt is revised, one edit at a time.
    ry = y0 + 112
    c.text(x0 + 2, ry, "Per round: the researcher’s prompt is revised", size=SMALL, bold=True)
    bx, by, bw, bh = x0 + 30, ry + 9, 42, 17
    step = (w - 30 - bw / 2 - 12) / 3
    c.text(x0 + 2, by + bh + 32, "prompt", size=SMALL, color=MUTED)
    version = 0
    for k in range(4):
        x = bx + k * step
        if k < 3:
            c.rect(x, by, bw, bh, rx=2.5, fill=SURFACE, stroke=INK2, sw=HAIR)
            c.text(x + bw / 2, by + 7, "round %d" % (k + 1), size=SMALL, bold=True, anchor="middle")
            for j in range(9):
                c.line(x + 6 + j * 4, by + 10.5, x + 6 + j * 4, by + 14, stroke=MUTED, sw=HAIR)
            c.arrow([(x + bw + 1, by + bh / 2), (x + step - 1, by + bh / 2)], color=INK2, sw=HAIR)
            adopted = F["decisions"][k]
            dx = x + bw + (step - bw) / 2
            color = RESEARCHER if adopted else MUTED
            c.circle(dx, by + bh + 12, 4.8, fill=SURFACE, stroke=color, sw=LINE)
            if adopted:
                check(c, dx - 2.5, by + bh + 9.7, s=5, color=color, sw=LINE)
            else:
                cross(c, dx - 1.9, by + bh + 10.1, s=3.8, color=color, sw=LINE)
        else:
            c.text(x + 8, by + bh / 2 + 2.3, "…", size=SIZE, color=INK2)
        px = x + bw / 2
        c.text(px, by + bh + 32, "v%d" % version, size=SIZE, bold=True, anchor="middle", color=RESEARCHER)
        if k < 3:
            adopted = F["decisions"][k]
            c.arrow([(px + 7, by + bh + 29.5), (px + step - 7, by + bh + 29.5)],
                    color=RESEARCHER if adopted else LIGHT, sw=LINE if adopted else HAIR,
                    dash=None if adopted else "2 1.5")
            version += 1 if adopted else 0


def figure1(F):
    return page("Figure 1: an ontology that accumulates source-qualified knowledge",
                "Schematic overview. Values and the finding card are from knowledge snapshot %s; counts from A1 on KF."
                % F["kf"]["SNAPSHOT_ID"], F, [(160, [fig1a, fig1b]), (182, [fig1c, fig1d])])


# ------------------------------------------------------------------------------------------------ Figure 2

def chip(c, x, y, label, size=SMALL, bold=True, color=INK2, fill=SURFACE, w=None, dash=None, sw=HAIR,
         anchor="start", text_color=INK, italic=False):
    """A small rounded box holding one line, top left (x, y) (or top centre with anchor "middle"); returns its
    width."""
    cw = w or width(label, size, bold, italic) + 8
    ch = size + 4.5
    if anchor == "middle":
        x -= cw / 2
    c.rect(x, y, cw, ch, rx=2.5, fill=fill, stroke=color, sw=sw, dash=dash)
    c.text(x + cw / 2, y + ch / 2 + size * 0.36, label, size=size, bold=bold, italic=italic, color=text_color,
           anchor="middle")
    return cw


def boxed(c, x, y, w, title, lines, min_h=0, sw=HAIR, color=INK2):
    """A top-aligned box: a bold title (SIZE) and short lines (SMALL); returns its height."""
    lead, pad = SMALL * 1.18, 3.5
    h = max(min_h, pad + SIZE * 0.8 + 2.5 + len(lines) * lead + 3)
    c.rect(x, y, w, h, rx=2.5, fill=SURFACE, stroke=color, sw=sw)
    c.text(x + pad, y + pad + SIZE * 0.78, title, size=SIZE, bold=True)
    c.lines(x + pad, y + pad + SIZE * 0.78 + 2.5 + lead, lines, size=SMALL, lead=lead, color=INK2)
    for line in lines:
        _need(width(line, SMALL) <= w - 2 * pad, "%r overflows its box" % line)
    return h


def diamond(c, x, y, w, h, label, size=SMALL):
    c.polygon([(x, y - h / 2), (x + w / 2, y), (x, y + h / 2), (x - w / 2, y)], fill=SURFACE, stroke=INK2, sw=HAIR)
    c.text(x, y + size * 0.35, label, size=size, bold=True, anchor="middle")


def fig2a(c, F, x0, y0, w, h):
    t = F["byType"]
    green = STATUS["Reviewed"]
    # Seed layer: polymer concepts and the records they link to, all from the initial WOP seed.
    sy, sh = y0 + 16, 62
    c.region(x0, sy, w, sh, "seed layer")
    cy = sy + 28.5
    c.lines(x0 + 33, cy - 1.5, ["initial", "WOP seed"], size=SMALL, bold=True, color=green, anchor="end", lead=7.5)
    bx, bw, bh = x0 + 46, 42, 30
    c.arrow([(x0 + 35, cy), (bx - 0.5, cy)], color=green, sw=LINE, gap=0.5)
    c.rect(bx, cy - bh / 2, bw, bh, rx=2.5, fill=SURFACE, stroke=INK2, sw=LINE)
    c.lines(bx + bw / 2, cy - 6, ["Polymer", "concepts"], size=SMALL, bold=True, anchor="middle", lead=7.2)
    c.text(bx + bw / 2, cy + 10.5, n(t["PolymerConcept"]), size=SMALL, anchor="middle", color=INK2)
    grid = [("Structure", "Facet"), ("Process", "Section"), ("Evidence", "Document")]
    cw = max(width(k, SMALL, True) + width(" " + n(t[k]), SMALL) + 8 for row in grid for k in row)
    gx, ch, gap = x0 + w - 3 - 2 * cw - 4, 10.5, 3
    gy = cy - (3 * ch + 2 * gap) / 2
    for r, row in enumerate(grid):
        for k, key in enumerate(row):
            x, y = gx + k * (cw + 4), gy + r * (ch + gap)
            c.rect(x, y, cw, ch, rx=2, fill=SURFACE, stroke=INK2, sw=HAIR)
            c.text(x + 4, y + 7.5, [(key, {"bold": True}), (" " + n(t[key]), {"color": INK2})], size=SMALL)
    # One link from the concepts to the records they are linked to through claims.
    brace = gx - 6
    c.path("M %s %s L %s %s L %s %s L %s %s" % (gx - 2, gy, brace, gy, brace, gy + 3 * ch + 2 * gap, gx - 2,
                                                gy + 3 * ch + 2 * gap), stroke=INK2, sw=HAIR, cap="butt")
    c.arrow([(bx + bw, cy), (brace - 0.5, cy)], color=INK2, sw=LINE, gap=0.5)
    c.text((bx + bw + brace) / 2, sy + sh - 4, "%s claims" % n(t["Claim"]), size=SMALL, color=INK2,
           anchor="middle")
    # Knowledge layer: what the loop deposits and reviews.
    ky, kh = sy + sh + 15, 50
    c.region(x0, ky, w, kh, "knowledge layer")
    fx, fw, fh = x0 + 94, 100, 36
    ft = ky + 9
    rowy = ft + fh / 2
    c.rect(fx, ft, fw, fh, rx=2.5, fill=SURFACE, stroke=RESEARCHER, sw=LINE)
    c.text(fx + 4, ft + 8.5, "Finding", size=SIZE, bold=True)
    for r, pair in enumerate((("Reviewed", "Added"), ("Needs checking", "Rejected"))):
        xx = fx + 4
        for status in pair:
            xx += badge(c, xx, ft + 12.5 + r * 11.5, status, size=SMALL) + 3
        _need(xx <= fx + fw, "status badges overflow the Finding box")
    for label, x, bw_ in (("Source note", x0 + 40, 46), ("Review", fx + fw + 8, x0 + w - 2 - fx - fw - 8)):
        c.rect(x, rowy - 8, bw_, 16, rx=2.5, fill=SURFACE, stroke=INK2, sw=HAIR)
        c.text(x + bw_ / 2, rowy + 2.4, label, size=SMALL, bold=True, anchor="middle")
    c.arrow([(x0 + 86, rowy), (fx, rowy)], color=INK2, sw=HAIR, both=True, gap=0.6)
    c.arrow([(fx + fw + 8, rowy), (fx + fw, rowy)], color=INK2, sw=HAIR, gap=0.6)
    c.text(x0 + 28, rowy + 2.4, "deposit", size=SMALL, bold=True, color=RESEARCHER, anchor="end")
    c.arrow([(x0 + 29.5, rowy), (x0 + 40, rowy)], color=RESEARCHER, sw=LINE, gap=0.5)
    # A finding is filed under a polymer concept of the seed.
    elbow = ky - 6
    c.arrow([(fx + 16, ft), (fx + 16, elbow), (bx + bw / 2, elbow), (bx + bw / 2, cy + bh / 2 + 0.5)],
            color=RESEARCHER, sw=LINE, gap=0.5)
    c.text(bx + bw / 2 + 4, elbow - 2, "polymer id", size=SMALL, color=RESEARCHER)
    _need(ky + kh <= y0 + h, "panel 2a overflows (%.1f > %.1f)" % (ky + kh, y0 + h))


def fig2b(c, F, x0, y0, w, h):
    trade, abbreviations = F["trade"], F["abbreviations"]
    # Resolution: a name to a seed identity.
    c.text(x0 + 2, y0 + 20, "Resolution", size=SMALL, bold=True)
    rows = [("EVOH44", "grade", "Ethylene–vinyl alcohol copolymer"),
            ("Ultem", "trade name", trade["Ultem"]),
            ("HDPE", "abbreviation", abbreviations["HDPE"][0]),
            ("PEI", "ambiguous", " or ".join(abbreviations["PEI"]))]
    _need(abbreviations["EVOH"] == [rows[0][2]] and len(abbreviations["PEI"]) == 2, "resolution examples")
    y = y0 + 25
    for name, kind, target in rows:
        cw = chip(c, x0 + 2, y, name, size=SMALL)
        c.text(x0 + 2, y + 17.5, kind, size=SMALL, italic=True, color=MUTED)
        c.arrow([(x0 + 3 + cw, y + 5.25), (x0 + 43, y + 5.25)], sw=HAIR, gap=0.5)
        lines = wrap(target, 64, SMALL)
        _need(len(lines) <= 2, "%s wraps to more than two lines" % target)
        c.lines(x0 + 45, y + 7.5, lines, size=SMALL, lead=7.3)
        y += 22
    # Lineage: a search for HDPE keeps its family, not its siblings.
    ly = y + 1
    labels = F["labels"]
    pe = next(i for i, l in labels.items() if l == "Polyethylene family")
    hd = next(i for i, l in labels.items() if l == abbreviations["HDPE"][0])
    siblings = {labels[i] for i, up in F["broader"].items() if pe in up and i != hd}
    sib = [a for a in ("LDPE", "LLDPE") if abbreviations[a][0] in siblings]
    _need(pe in F["broader"][hd] and len(sib) == 2, "HDPE and its siblings under the polyethylene family")
    fam = chip(c, x0 + 2, ly, "Polyethylene family", color=RESEARCHER, fill=tinted(RESEARCHER, 0.16), sw=LINE)
    for k, (abbr, kept) in enumerate([("HDPE", True)] + [(a, False) for a in sib]):
        kx = x0 + 2 + k * 33
        c.line(x0 + 2 + fam / 2, ly + 11, kx + 14, ly + 16, stroke=MUTED, sw=HAIR)
        chip(c, kx, ly + 16, abbr, w=28, color=RESEARCHER if kept else LIGHT,
             fill=tinted(RESEARCHER, 0.16) if kept else SURFACE, sw=LINE if kept else HAIR,
             text_color=INK if kept else MUTED)
    # Search: the search_knowledge tool, reading the ontology, feeding Reuse.
    sx = x0 + 114
    sw_ = x0 + w - sx
    c.text(sx, y0 + 20, "Search", size=SMALL, bold=True)
    bx = sx + 28
    bw = x0 + w - 1 - bx
    chip(c, bx + bw / 2, y0 + 25, "“HDPE tensile modulus”", bold=False, italic=True, anchor="middle")
    top = y0 + 43
    c.arrow([(bx + bw / 2, y0 + 35.5), (bx + bw / 2, top - 0.5)], sw=HAIR, gap=0.5)
    lo, hi = F["limits"]
    steps = ["names expanded", "full-text match", "polymer lineage only", "ranked: %d–%d" % (lo, hi),
             "+%d same source" % F["sameSource"], "+%d source notes" % F["notes"]]
    lead = 7.3
    bh = 16.5 + len(steps) * lead + 4
    c.rect(bx, top, bw, bh, rx=2.5, fill=SURFACE, stroke=RESEARCHER, sw=LINE)
    c.text(bx + 4, top + 8.5, "search_knowledge", size=SMALL, bold=True, color=RESEARCHER)
    c.lines(bx + 4, top + 16.5, steps, size=SMALL, lead=lead, color=INK2)
    gy = top + 16.5 + (len(steps) - 1) * lead - 2.3
    for k, status in enumerate(("Reviewed", "Added", "Needs checking")):
        c.circle(bx + bw - 22 + k * 7, gy, 2.6, fill=STATUS[status])
    store(c, sx, top + 16, w=22, h=19, color=RESEARCHER, sw=LINE)
    c.arrow([(sx + 22, top + 25.5), (bx - 0.5, top + 25.5)], color=RESEARCHER, sw=LINE, gap=0.5)
    pill(c, bx + bw / 2, top + bh + 13, "Reuse", size=SMALL)
    c.arrow([(bx + bw / 2, top + bh), (bx + bw / 2, top + bh + 6.5)], sw=HAIR, gap=0.3)
    _need(top + bh + 19.5 <= y0 + h, "panel 2b overflows")
    _need(sw_ >= bw, "search column")


def fig2c(c, F, x0, y0, w, h):
    d = F["depths"]["standard"]
    qb, yt, _, (c1, c2, c3), _ = question_branch(c, x0 + 1, y0 + 16, w - 2, split=3, top=9, bottom=5)
    # Inputs: the one prompt, and the budget of the standard depth.
    iy = qb + 7
    c.arrow([(c1, iy - 1), (c1, yt + (SIZE + 6) / 2 + 0.5)], sw=HAIR, gap=0.5)
    document(c, x0 + 4, iy + 1, w=9, h=11, color=RESEARCHER, lines=2)
    c.text(x0 + 16, iy + 8, [("prompt ", {"bold": True}), (F["prompt"], {"color": INK2})], size=SMALL)
    c.text(x0 + 4, iy + 21, "%d min · ~%d searches · ~%d sources" % (d["seconds"] // 60, d["searches"],
                                                                       d["sources"]), size=SMALL, color=INK2)
    # The answer: three kinds of statement, shown at once (the findings follow in the second turn, Fig. 2d).
    lines = [[("source facts", {"bold": True}), (", cited", {"color": INK2})], [("Interpretation:", {"bold": True})],
             [("Background:", {"bold": True})], [("shown at once", {"color": INK2, "italic": True})]]
    lead = SMALL * 1.16
    aw = width("source facts", SMALL, True) + width(", cited", SMALL) + 12
    ax = x0 + w - 2 - aw
    ah = 4 + len(lines) * lead + 2
    c.arrow([(c3, yt + (SIZE + 6) / 2), (c3, iy - 0.5)], color=INK2, sw=LINE, gap=0.6)
    c.rect(ax, iy, aw, ah, rx=2.5, fill=SURFACE, stroke=INK2, sw=LINE)
    c.lines(ax + 4.5, iy + 3 + lead, lines, size=SMALL, lead=lead)
    _need(iy + ah <= y0 + h, "panel 2c overflows (%.1f > %.1f)" % (iy + ah, y0 + h))


def fig2d(c, F, x0, y0, w, h):
    c.region(x0, y0 + 16, w, h - 16, AFTER)
    y1, y2, y3 = y0 + 31, y0 + 58, y0 + 83
    ph = SIZE + 6
    # Deposit: the second turn returns the findings; each is valid, then new, then Added or Needs checking by how the
    # value was obtained. The first pill keeps Answer's width, so the row is laid out as before.
    aw = pill(c, x0 + 4 + (width("Answer", SIZE, True) + 9) / 2, y1, "Turn 2", pw=width("Answer", SIZE, True) + 9)
    for cx, dw, label, exit_ in ((x0 + 60, 34, "valid?", "dropped"), (x0 + 94, 30, "new?", "not saved")):
        diamond(c, cx, y1, dw, 15, label)
        c.arrow([(cx, y1 + 7.5), (cx, y1 + 11.5)], sw=HAIR, gap=0.2)
        c.text(cx, y1 + 17.5, exit_, size=SMALL, italic=True, color=MUTED, anchor="middle")
    dep = x0 + 132
    dw = pill(c, dep, y1, "Deposit")
    c.arrow([(x0 + 4 + aw, y1), (x0 + 43, y1)], sw=HAIR, gap=0.6)
    c.arrow([(x0 + 77, y1), (x0 + 79, y1)], sw=HAIR, gap=0.2)
    c.arrow([(x0 + 109, y1), (dep - dw / 2, y1)], sw=HAIR, gap=0.6)
    added, check = x0 + 118, x0 + 168
    status_box(c, added - 17, y2 - 6.5, 34, 13, "Added")
    status_box(c, check - 28, y2 - 6.5, 56, 13, "Needs checking")
    c.arrow([(dep - 4, y1 + ph / 2), (added + 4, y2 - 6.5)], sw=HAIR, gap=0.6)
    c.arrow([(dep + 4, y1 + ph / 2), (check - 8, y2 - 6.5)], sw=HAIR, gap=0.6)
    c.text(dep - 3, y1 + 15, "read", size=SMALL, italic=True, color=INK2)
    c.text(dep + 20, y1 + 12, "derived", size=SMALL, italic=True, color=INK2)
    # Review: all that need checking and 1 in 5 Added; its verdicts set the status.
    rv = check
    rw = pill(c, rv, y3, "Review")
    c.arrow([(rv - 4, y2 + 6.5), (rv - 4, y3 - ph / 2)], sw=HAIR, gap=0.4, dash="2 1.5")
    c.arrow([(rv + 4, y3 - ph / 2), (rv + 4, y2 + 6.5)], sw=HAIR, gap=0.4)
    c.text(rv - 7, y2 + 14.5, "all", size=SMALL, italic=True, color=INK2, anchor="end")
    c.arrow([(added + 6, y2 + 6.5), (rv - rw / 2, y3)], sw=HAIR, gap=0.6, dash="2 1.5")
    c.text(added + 8, y3 + 2.3, "1 in %d" % round(1 / F["spot"]), size=SMALL, italic=True, color=INK2,
           anchor="end")
    vx = rv + rw / 2 + 6
    vw = x0 + w - 3 - vx
    status_box(c, vx, y3 - 14, vw, 13, "Reviewed")
    status_box(c, vx, y3 + 1, vw, 13, "Rejected")
    c.arrow([(rv + rw / 2, y3 - 2), (vx - 0.3, y3 - 7.5)], sw=HAIR, gap=0.3)
    c.arrow([(rv + rw / 2, y3 + 2), (vx - 0.3, y3 + 7.5)], sw=HAIR, gap=0.3)
    _need(vw >= width("Reviewed", SMALL, True) + 6, "panel 2d verdicts are too narrow (%.1f)" % vw)
    _need(y3 + 14 <= y0 + h - 2, "panel 2d overflows")


def fig2e(c, F, x0, y0, w, h):
    old, new = F["edit"]
    steps = [("Round", ["%d tasks" % F["perRound"], "through the loop"]),
             ("Records", ["measures, reviews,", "checks, answers"]),
             ("Improver", ["one edit: ≤%s →" % n(old), "≤%s characters" % n(new)]),
             ("Comparison", ["%d development" % F["dev"], "questions, same day"]),
             ("Rule", ["no more contradicted;", "no fewer complete,", "no fewer sourced;",
                       "tokens ≤ %.2f×, ≥ %d pairs" % (F["tokenLimit"], F["minPairs"])])]
    gap, ow = 10, 66
    # Each box as wide as its longest line, and the room left shared equally.
    natural = [max(width(title, SIZE, True), *(width(line, SMALL) for line in lines)) + 8 for title, lines in steps]
    spare = (w - ow - gap * len(steps) - sum(natural)) / len(steps)
    _need(spare >= 0, "panel 2e is too narrow for its steps")
    widths_ = [nw + spare for nw in natural]
    top = y0 + 15
    hh = max(boxed(Canvas(1, 1, ""), 0, 0, bw_, title, lines) for bw_, (title, lines) in zip(widths_, steps))
    x = x0
    for k, (bw, (title, lines)) in enumerate(zip(widths_, steps)):
        boxed(c, x, top, bw, title, lines, min_h=hh, sw=LINE if title in ("Improver", "Rule") else HAIR)
        if k < len(steps) - 1:
            c.arrow([(x + bw, top + 14), (x + bw + gap, top + 14)], sw=LINE, gap=0.5)
        x += bw + gap
    bw = widths_[0]
    half = (hh - 4) / 2
    fork = x - gap / 2
    c.path("M %s %s L %s %s" % (x - gap, top + hh / 2, fork, top + hh / 2), stroke=INK2, sw=LINE)
    c.arrow([(fork, top + hh / 2), (fork, top + half / 2), (x - 0.5, top + half / 2)], sw=LINE, gap=0.3)
    c.arrow([(fork, top + hh / 2), (fork, top + half + 4 + half / 2), (x - 0.5, top + half + 4 + half / 2)], sw=LINE,
            gap=0.3)
    c.rect(x, top, ow, half, rx=2.5, fill=tinted(RESEARCHER, 0.16), stroke=RESEARCHER, sw=LINE)
    c.text(x + ow / 2, top + half / 2 + 2.4, "adopt the edit", size=SMALL, bold=True, color=RESEARCHER,
           anchor="middle")
    c.rect(x, top + half + 4, ow, half, rx=2.5, fill=SURFACE, stroke=MUTED, sw=HAIR)
    c.text(x + ow / 2, top + half + 4 + half / 2 + 2.4, "keep the prompt", size=SMALL, bold=True, color=INK2,
           anchor="middle")
    bottom = top + hh + 6
    back, mid = x0 + bw / 2, (x + ow / 2 + x0 + bw / 2) / 2
    hole = width("next round", SMALL, italic=True) / 2 + 3
    c.path("M %s %s L %s %s L %s %s" % (x + ow / 2, top + hh, x + ow / 2, bottom, mid + hole, bottom), stroke=INK2,
           sw=HAIR)
    c.arrow([(mid - hole, bottom), (back, bottom), (back, top + hh + 0.5)], sw=HAIR, gap=0.4)
    c.text(mid, bottom + SMALL * 0.36, "next round", size=SMALL, italic=True, color=INK2, anchor="middle")
    _need(bottom + 2 <= y0 + h, "panel 2e overflows (%.1f > %.1f)" % (bottom + 2, y0 + h))


def figure2(F):
    return page("Figure 2: the ontology and its research loop",
                "Methods schematic. Facts from docs/core-loop.md, docs/model.md and the code at tags study-freeze-2 and "
                "study-freeze-4 (released, 0.13.0).",
                F, [(145, [fig2a, fig2b]), (103, [fig2c, fig2d]), (73, [fig2e])])


def figure_toc(F):
    """The TOC graphic (3.25 x 1.75 in): the two loops of Fig. 1b, the counts, and one saved finding."""
    W, H = 3.25, 1.75
    c = Canvas(W, H, "TOC graphic: research agents that remember",
               "Reduced Figure 1. Finding from knowledge snapshot %s; counts from A1 on KF." % F["kf"]["SNAPSHOT_ID"])
    right = 156  # where the counts and the finding begin
    with c.group("loops"):
        bottom = loops(c, 1, 6, right - 5, H * 72 - 8.5, size=SMALL, optional=False, seed_lines=("initial", "WOP seed"),
                       split=2, top=7, bottom=4)
        _need(bottom <= H * 72 - 1, "TOC loops overflow (%.1f)" % bottom)
    with c.group("counts"):
        tiles = [(n(F["questions"]), "questions"), (n(F["counts"]["findings"]), "findings"),
                 (n(F["counts"]["sources"]), "sources"), (n(F["counts"]["polymers"]), "polymers")]
        tw, th = (W * 72 - right - 2 - 3) / 2, 24
        for k, (num, label) in enumerate(tiles):
            x, y = right + (k % 2) * (tw + 3), 2 + (k // 2) * (th + 3)
            c.rect(x, y, tw, th, rx=2.5, fill=BAND)
            c.text(x + tw / 2, y + 11.5, num, size=LETTER, bold=True, anchor="middle")
            c.text(x + tw / 2, y + 20, label, size=SMALL, anchor="middle", color=INK2)
    with c.group("finding"):
        row = finding(F, CARD)
        abbr = re.search(r"\(([^)]+)\)\s*$", row["property"])
        _need(abbr and abbr.group(1) == "Tg", "TOC property abbreviation")
        kx, ky, kw = right, 2 + 2 * 27 + 2, W * 72 - right - 2
        kh = H * 72 - 2 - ky
        c.rect(kx, ky, kw, kh, rx=3, fill=SURFACE, stroke=INK2, sw=LINE)
        badge(c, kx + 4, ky + 4, row["statusLabel"], size=SMALL)
        lead = SMALL * 1.18
        y = c.lines(kx + 4, ky + 21, wrap(row["material"].split(";")[0], kw - 8, SMALL), size=SMALL, lead=lead)
        c.text(kx + 4, y + 1.5, [("T", {}), ("g", {"sub": True}), (" " + value_of(row), {})], size=SMALL, bold=True)
        doi = row["source"]["doi"]
        cut = doi.index("/") + 1
        c.lines(kx + 4, ky + kh - 4 - lead, ["doi:" + doi[:cut], doi[cut:]], size=SMALL, color=INK2, lead=lead)
    return c


# ------------------------------------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(HERE))
    args = parser.parse_args()
    F = facts()
    written = []
    for name, draw in (("fig1", figure1), ("fig2", figure2), ("toc", figure_toc)):
        written += kit.export(draw(F), name, args.out)
    print("\n".join(written))


if __name__ == "__main__":
    main()
