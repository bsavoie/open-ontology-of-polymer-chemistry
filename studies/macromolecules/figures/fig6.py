#!/usr/bin/env python3
"""Figure 6, refining the ontology from answer traces (Part C, Stage 1), drawn from `refinement/results.json` only
(written by `refinement/analysis.py` from the records; no store, trace or engine). Every number drawn or written in a
caption is read from that file, never typed in.

- 6a The build: edits proposed by the curator, approved by the reviewer and in force after the drop step, by type
  (names, polymer-id annotations, property terms). The misses fixed are not drawn per type: each edit's replay counts
  the misses it fixes alone, so per-type sums overlap (393 against 197 distinct); the text gives the distinct count.
- 6b The withheld screen's web hops on B (KF, seed graph), by what they reached, for each question set: limited by
  accumulation (new knowledge, unsaved detail, reached now), avoidable by the ontology (held but unreached), failed
  opens, and the rest (repeats and searches that ended without an open).
- 6c One point per withheld question: the accumulation effect log(B/B0) against the ontology effect log(O+/B), in web
  steps (web calls + 1), marked by set.
- 6d The case studies: web calls per answer on B0, O0, B and O+ (mean over 15 answers), with the range of the five
  replicates' means.

Writes `fig6a` … `fig6d` and `fig6` (PDF, SVG, PNG) to `analysis/figures/` (or `--out`) and the `fig6` entry of
`figures/manifest.json`. Commit this script before rendering, so the revision in the pins is on record.

Colours: 6a's three stages are steps of the sequential violet (ordinal, direct-labelled); 6b's accumulation and
ontology classes are the reference palette's first slot (blue) and second (orange), checked with the dataviz skill's
validator on white (2026-10-27: CVD separation 23.6 protan, normal vision 32.7, both above 3:1), with the two neutral
inks for the classes neither removes; 6c is one neutral series told apart by marker; 6d keeps the stores' fixed
colours (`style.ARM`: K0 the ramp's light end, KF its dark end), open for the seed graph and filled for the refined one.

    OOPC_STUDY_ROOT=<main checkout> python -B fig6.py [--inputs DIR] [--out DIR]
"""
import argparse, math, sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

TYPES = [("name", "Names"), ("annotation", "Polymer ids"), ("property-term", "Property terms")]
STAGES = [("proposed", "proposed", style.SEQUENTIAL[1]), ("approvedByReviewer", "approved", style.SEQUENTIAL[3]),
          ("inForce", "in force", style.SEQUENTIAL[6])]
ACCUMULATION, ONTOLOGY = "#3077cd", "#eb6834"
CLASSES = [("accumulation", ("new-knowledge", "unsaved-detail", "reached-now"), ACCUMULATION, "accumulation"),
           ("ontology", ("held-unreached",), ONTOLOGY, "ontology"),
           ("failed", ("failed",), style.LIGHT, "failed open"),
           ("other", ("repeat", "search-only", "unused"), style.MUTED, "other")]
SETS = [("H", "H held-out"), ("N", "N new"), ("L", "L targeted")]
MARKERS = {"H": "o", "N": "s", "L": "^"}
CASES = [("C5", "C5\naccumulation\nalone"), ("C4", "C4\nproperty\nwording"), ("C1", "C1\nunknown\nname"),
         ("C6", "C6\nnothing\nsaved"), ("C8", "C8\nrisk")]
ARMS = [("B0", "K0", False), ("O0", "K0", True), ("B", "KF", False), ("O+", "KF", True)]


def panel_a(fig, data, size):
    edits = data["build"]["edits"]
    ax = fig.add_subplot(style.grid(fig, size, left=0.75, right=0.2, top=0.38, bottom=0.32)[0])
    for i, (key, label) in enumerate(TYPES):
        for stage, _, colour in STAGES:
            ax.barh(i, edits[stage][key], height=0.62, color=colour, zorder=2)
        ax.text(edits["proposed"][key] + 3, i, "%d / %d / %d" % tuple(edits[s][key] for s, _, _ in STAGES),
                va="center", fontsize=style.SMALL, color=style.INK2)
    ax.set_yticks(range(len(TYPES)), [t for _, t in TYPES])
    ax.invert_yaxis()
    ax.set_xlim(0, max(edits["proposed"].values()) * 1.45)
    ax.set_xlabel("edits")
    ax.grid(axis="x")
    ax.tick_params(axis="y", length=0)
    x = 0
    for _, label, colour in STAGES:
        ax.add_patch(plt.Rectangle((x, 1.04), 0.035, 0.07, color=colour, transform=ax.transAxes, clip_on=False))
        ax.text(x + 0.045, 1.075, label, transform=ax.transAxes, va="center", fontsize=style.SMALL)
        x += 0.27


def panel_b(fig, data, size):
    groups = data["screen"]["hops"]["groups"]
    ax = fig.add_subplot(style.grid(fig, size, left=0.75, right=0.15, top=0.38, bottom=0.32)[0])
    rows = [(key, label) for key, label in SETS]
    for i, (key, _) in enumerate(rows):
        web = groups[key]["web"]
        left = 0
        for _, kinds, colour, _ in CLASSES:
            n = sum(web.get(k, 0) for k in kinds)
            if n:
                ax.barh(i, n, left=left, height=0.62, color=colour, edgecolor=style.SURFACE, linewidth=0.6, zorder=2)
            left += n
        ax.text(left + 3, i, "%d" % groups[key]["webHops"], va="center", fontsize=style.SMALL, color=style.INK2)
    ax.set_yticks(range(len(rows)), [label for _, label in rows])
    ax.invert_yaxis()
    ax.set_xlabel("web hops on B (KF, seed graph)")
    ax.grid(axis="x")
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(groups[k]["webHops"] for k, _ in rows) * 1.12)
    x = 0
    for _, _, colour, label in CLASSES:
        ax.add_patch(plt.Rectangle((x, 1.04), 0.03, 0.07, color=colour, transform=ax.transAxes, clip_on=False))
        ax.text(x + 0.04, 1.075, label, transform=ax.transAxes, va="center", fontsize=style.SMALL)
        x += 0.04 + style.text_width(fig, [label]) / (size[0] - 0.9) + 0.05


def panel_c(fig, data, size):
    points = data["screen"]["points"]
    ax = fig.add_subplot(style.grid(fig, size, left=0.48, right=0.12, top=0.3, bottom=0.42)[0])
    lim = 1.02 * max(max(abs(p["accumulation"]["web"]), abs(p["ontology"]["web"])) for p in points)
    ax.fill_between([-lim, 0, lim], [lim, 0, lim], [lim, lim, lim], color=style.BAND, zorder=0, linewidth=0)
    ax.fill_between([-lim, 0, lim], [-lim, 0, -lim], [-lim, -lim, -lim], color=style.BAND, zorder=0, linewidth=0)
    ax.axhline(0, color=style.AXIS, linewidth=style.HAIR, zorder=1)
    ax.axvline(0, color=style.AXIS, linewidth=style.HAIR, zorder=1)
    for key, label in SETS:
        sel = [p for p in points if p["set"] == key]
        ax.scatter([p["accumulation"]["web"] for p in sel], [p["ontology"]["web"] for p in sel], s=9,
                   marker=MARKERS[key], facecolor="none", edgecolor=style.INK2, linewidth=0.6, alpha=0.8,
                   label=label, zorder=2)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("accumulation effect, log(B/B0)")
    ax.set_ylabel("ontology effect, log(O+/B)")
    web = data["screen"]["groups"]["all"]["attribution"]["web"]
    ax.text(0.03, 0.97, "ontology larger: %d" % web["ontologyLarger"], transform=ax.transAxes, va="top",
            fontsize=style.TINY, color=style.INK2)
    ax.text(0.97, 0.62, "accumulation\nlarger: %d\nties: %d" % (web["accumulationLarger"], web["ties"]),
            transform=ax.transAxes, ha="right", va="bottom", fontsize=style.TINY, color=style.INK2)  # in the white region
    ax.legend(loc="upper right", fontsize=style.TINY, handletextpad=0.2, borderaxespad=0.1)


def panel_d(fig, data, size):
    cases = data["cases"]["cases"]
    ax = fig.add_subplot(style.grid(fig, size, left=0.42, right=0.1, top=0.3, bottom=0.62)[0])
    width = 0.17
    for i, (case, _) in enumerate(CASES):
        arms = cases[case]["arms"]
        for j, (arm, store, refined) in enumerate(ARMS):
            if arm not in arms:
                continue
            x = i + (j - 1.5) * width
            colour = style.ARM[store]
            reps = arms[arm]["webCallsByReplicate"]
            ax.plot([x, x], [reps["min"], reps["max"]], color=colour, linewidth=style.LINE, zorder=2)
            ax.scatter([x], [arms[arm]["webCalls"]["mean"]], s=16, marker="o", linewidth=0.8, edgecolor=colour,
                       facecolor=colour if refined else style.SURFACE, zorder=3)
    ax.set_xticks(range(len(CASES)), [label for _, label in CASES])
    ax.tick_params(axis="x", length=0)
    ax.set_ylabel("web calls per answer")
    ax.set_ylim(0, None)
    ax.grid(axis="y")
    handles = [plt.Line2D([], [], marker="o", linestyle="", markersize=4, markeredgewidth=0.8,
                          markeredgecolor=style.ARM[store], markerfacecolor=style.ARM[store] if refined
                          else style.SURFACE, label=arm) for arm, store, refined in ARMS]
    ax.legend(handles=handles, loc="upper right", ncol=4, fontsize=style.SMALL, columnspacing=0.6)


PANELS = [("a", panel_a, (3.3, 1.55)), ("b", panel_b, (3.7, 1.55)), ("c", panel_c, (2.55, 2.6)),
          ("d", panel_d, (4.45, 2.6))]


def caption(data):
    edits = data["build"]["edits"]
    web = data["screen"]["groups"]["all"]["attribution"]["web"]
    hops = data["screen"]["hops"]["groups"]["all"]
    return ("Refining the ontology from answer traces. (a) Edits proposed, approved and in force by type (%d, %d, "
            "%d in all). (b) Web hops on B by what they reached (%d in %d "
            "answers). (c) Accumulation and ontology effects per withheld question, log ratios of web steps "
            "(accumulation larger in %d, ontology in %d, ties %d). (d) Case studies: web calls per answer on B0, O0, "
            "B and O+, with the range of five replicates." % (
                edits["proposedTotal"], edits["approvedTotal"], edits["inForceTotal"], hops["webHops"],
                hops["answers"], web["accumulationLarger"], web["ontologyLarger"], web["ties"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=None, help="directory holding refinement/results.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    path = Path(args.inputs) / "results.json" if args.inputs else style.common.analysis_dir("refinement/results.json")
    data = style.jread(path)
    meta = data["meta"]
    pinned = {"knowledgeSnapshot": meta["pins"]["knowledgeSnapshot"], "graphRelease": meta["pins"]["release"],
              "prompt": meta["pins"]["promptVersion"], "codeTag": meta["pins"]["tag"],
              "codeUnderTest": meta["codeUnderTest"], "inputAnalysisRevision": [meta["analysisRevision"]],
              "inputs": {"refinement/results.json": {"builtAt": meta["builtAt"]}},
              "figureScript": "studies/macromolecules/figures/fig6.py", "figureRevision": style.revision()}
    style.setup()
    files = []
    for letter, draw, size in PANELS:
        fig = plt.figure(figsize=size)
        draw(fig, data, size)
        style.letter(fig, letter)
        files += style.save(fig, "fig6" + letter, pinned, caption(data), args.out)
    fig = plt.figure(figsize=(style.DOUBLE, 1.55 + 2.6))
    top, bottom = fig.subfigures(2, 1, height_ratios=[1.55, 2.6])
    for sub, row in ((top, PANELS[:2]), (bottom, PANELS[2:])):
        parts = sub.subfigures(1, 2, width_ratios=[row[0][2][0], row[1][2][0]])
        for part, (letter, draw, size) in zip(parts, row):
            draw(part, data, size)
            style.letter(part, letter)
    files += style.save(fig, "fig6", pinned, caption(data), args.out)
    style.record("fig6", {"files": files, "sources": ["refinement/results.json"], "pins": pinned,
                          "caption": caption(data)}, args.out)
    print("\n".join(files))


if __name__ == "__main__":
    main()
