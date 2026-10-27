#!/usr/bin/env python3
"""Figure 3, the knowledge base as a polymer dataset, drawn from experiment A1's outputs on KF only (no store, no
trace, no engine). Each panel is its own file and the assembled figure is one more; every number drawn or written in
a caption is read from these files, never typed in:

- 3a growth: `dataset-kf/growth.json` (one point per answer with a deposit, in deposit order; findings by their status
  in KF, credited to the answer that saved them; stage runs and the prompt and model change markers).
- 3b polymer coverage: `dataset-kf/coverage.json` (every polymer of the graph release with its class and findings).
- 3c property coverage: `properties-kf/findings_by_subject_class.csv` (findings with a polymer id by polymer class,
  property class, category and kind), `finding_classes.csv` (every finding's kind) and `meta.json` (the pins).
- 3d Tg landscape: `tg-landscape/tg_landscape.csv` (one row per Tg or Tm finding with one readable temperature) and
  `tg_landscape.json` (polymers in order of median Tg, method split, the DMA against DSC comparison).
- 3e sources: `dataset-kf/sources.json` (sources by type; publication years of the DOI sources Crossref knows).
- 3f record quality: `dataset-kf/completeness.json` (field presence; campaign spot checks of sampled Added findings and
  outcomes of findings flagged at save, by the status they ended with).

Writes `fig3a` … `fig3f` and `fig3` (PDF, SVG, PNG) to `analysis/figures/` (or `--out`) and the `fig3` entry of
`figures/manifest.json`. Commit this script before rendering, so the revision in the pins is on record.

    OOPC_STUDY_ROOT=<main checkout> python -B fig3.py [--inputs DIR] [--out DIR]
"""
import argparse, collections, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import colors, ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

JSON = ["dataset-kf/growth.json", "dataset-kf/coverage.json", "dataset-kf/sources.json", "dataset-kf/completeness.json",
        "properties-kf/meta.json", "tg-landscape/tg_landscape.json"]
CSV = ["properties-kf/findings_by_subject_class.csv", "properties-kf/finding_classes.csv", "tg-landscape/tg_landscape.csv"]
SOURCES = {"3a": ["dataset-kf/growth.json"], "3b": ["dataset-kf/coverage.json"],
           "3c": ["properties-kf/findings_by_subject_class.csv", "properties-kf/finding_classes.csv",
                  "properties-kf/meta.json", "dataset-kf/coverage.json"],
           "3d": ["tg-landscape/tg_landscape.csv", "tg-landscape/tg_landscape.json"],
           "3e": ["dataset-kf/sources.json"], "3f": ["dataset-kf/completeness.json"]}
SIZES = {"3a": (2.6, 2.5), "3b": (4.4, 2.5), "3c": (7.0, 2.25), "3d": (3.75, 3.9), "3e": (3.25, 1.95),
         "3f": (3.25, 1.95)}

# Display names only; the classes, categories and kinds themselves come from the data.
CLASS_SHORT = {"commodity thermoplastic": "Commodity", "engineering thermoplastic": "Engineering",
               "high performance polymer": "High-performance", "elastomer": "Elastomer",
               "thermoplastic elastomer": "Thermoplastic elastomer", "thermoset": "Thermoset",
               "fiber and textile": "Fibre and textile", "natural and semisynthetic": "Natural, semisynthetic",
               "biodegradable and biomedical": "Biodegradable, biomedical",
               "water soluble and hydrogel": "Water-soluble, hydrogel", "functional and specialty": "Functional, specialty"}
CATEGORY = {"thermal-transitions": "Thermal transitions", "thermal-stability": "Thermal stability",
            "mechanical": "Mechanical", "impact-fracture": "Impact, fracture", "hardness-elastomer": "Hardness, elastomer",
            "rheology-cure": "Rheology, cure", "barrier-transport": "Barrier, transport", "optical": "Optical",
            "electrical": "Electrical", "morphology": "Morphology", "molecular": "Molecular", "solution": "Solution",
            "degradation-environment": "Degradation", "density-dimensional": "Density, dimensions",
            "flammability": "Flammability", "surface-adhesion": "Surface, adhesion", "biological": "Biological",
            "other-property": "Other property"}
KINDS = [("material-property", "Material property", "#3f3e3a"),
         ("test-condition", "Test condition", "#7d7c75"),
         ("specimen-or-preparation", "Specimen, preparation", "#aeada6"),
         ("method-or-instrument|composition-or-formulation|other", "Method, formulation, other", "#d8d7d0")]
TYPE_SHORT = {"journal article": "Journal article", "technical data sheet/manufacturer": "Data sheet", "patent": "Patent",
              "government/report": "Report", "thesis": "Thesis", "other web": "Other web", "standard": "Standard",
              "book/chapter": "Book, chapter", "preprint": "Preprint"}
FIELDS = [("conditions", "Conditions"), ("locator", "Locator"), ("excerpt", "Excerpt"), ("unit", "Unit"),
          ("numericValue", "Numeric value"), ("polymerId", "Polymer id")]
METHOD_MARK = {"DSC": ("o", "DSC"), "DMA": ("^", "DMA"), "other": ("s", "Other method"), "none": ("D", "Not stated"),
               "DSC and DMA": ("X", "DSC and DMA")}
STAGE_SHORT = {"before the 200-task run": "", "200-task run": "200", "wave 1": "W1", "wave 2": "W2", "wave 3": "W3"}


def load(base=None):
    data = S.inputs(JSON, base)
    for name in CSV:
        data[name] = S.rows(name, base)
    return data


def n(v):
    return "{:,}".format(v)


# ----------------------------------------------------------------------------------------------- 3a

def draw_a(fig, size, data):
    g = data["dataset-kf/growth.json"]
    points = g["points"]
    x = np.array([p["answer"] for p in points])
    end = points[-1]
    right = S.text_width(fig, ["%s sources" % n(end["sources"]), "%s notes" % n(end["notes"]),
                               "%d polymers" % end["polymers"]], S.TINY) + 0.08
    gs = S.grid(fig, size, 3, 1, left=0.47, right=right, top=0.3, bottom=0.33, height_ratios=[2.3, 1.1, 0.9],
                hspace=0.18)
    axes = [fig.add_subplot(gs[0])]
    axes += [fig.add_subplot(gs[i], sharex=axes[0]) for i in (1, 2)]
    runs = [r for r in g["byRun"] if r["answers"]]
    for ax in axes:
        for i, r in enumerate(runs):
            if i % 2:
                ax.axvspan(r["firstAnswer"] - 0.5, r["lastAnswer"] + 0.5, color=S.BAND, lw=0, zorder=0)
        ax.grid(axis="y")
    changes = sorted({m["answer"] for m in g["markers"] if m["kind"] in ("prompt version", "model change")})
    for ax in axes:
        for c in changes:
            ax.axvline(c - 0.5, color=S.MUTED, lw=S.HAIR, ls=(0, (3, 2)), zorder=1)
    stacks = [np.array([p["findings"][s] for p in points]) for s in S.STATUS_ORDER]
    labels = ["%s %s" % (s, n(end["findings"][s])) for s in S.STATUS_ORDER]
    axes[0].stackplot(x, *stacks, colors=[S.STATUS[s] for s in S.STATUS_ORDER], labels=labels, lw=0, zorder=2)
    axes[0].legend(loc="upper left", handlelength=0.9, borderaxespad=0.1)
    axes[0].set_ylabel("Findings")
    axes[0].set_ylim(0, end["findings"]["total"] * 1.04)
    for key, colour, name in (("notes", S.INK, "notes"), ("sources", S.MUTED, "sources")):
        axes[1].plot(x, [p[key] for p in points], color=colour, lw=S.LINE, zorder=2)
        axes[1].annotate("%s %s" % (n(end[key]), name), (x[-1], end[key]), xytext=(3, 0), textcoords="offset points",
                         va="center", fontsize=S.TINY, color=S.INK, annotation_clip=False)
    axes[1].set_ylabel("Count")
    axes[1].set_ylim(0, max(end["notes"], end["sources"]) * 1.12)
    axes[2].plot(x, [p["polymers"] for p in points], color=S.INK2, lw=S.LINE, zorder=2)
    axes[2].annotate("%d polymers" % end["polymers"], (x[-1], end["polymers"]), xytext=(3, 0),
                     textcoords="offset points", va="center", fontsize=S.TINY, color=S.INK, annotation_clip=False)
    axes[2].set_ylabel("Polymers")
    axes[2].set_ylim(0, end["polymers"] * 1.15)
    axes[2].set_xlabel("Answers with a deposit, in order")
    axes[2].set_xlim(0, x[-1])
    for ax in axes:
        S.thousands(ax)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(3))
        ax.yaxis.label.set_size(S.SMALL)
    for ax in axes[:2]:
        plt.setp(ax.get_xticklabels(), visible=False)
    for r in runs:
        name = STAGE_SHORT.get(r["run"], r["run"])
        if name:
            axes[0].text((r["firstAnswer"] + r["lastAnswer"]) / 2, 1.02, name, transform=axes[0].get_xaxis_transform(),
                         ha="center", va="bottom", fontsize=S.TINY, color=S.INK2)
    S.letter(fig, "a")
    ends = ", ".join(n(r["endState"]["findings"]["total"]) for r in g["byRun"])
    return ("3a: growth over the %s answers with a deposit, in deposit order: %s findings stacked by their status in KF "
            "(%s Reviewed, %s Added, %s Needs checking, %s Rejected), credited to the answer that saved them; %s source "
            "notes, %s distinct sources and %d polymers with a finding. Findings at the ends of the imported seed, the "
            "store before the 200-task run, the 200-task run and waves 1-3: %s. Dashed lines mark the first answer "
            "under a new prompt (%s) or model (%s); shaded bands: %s." % (
                n(g["answers"]["withDepositRow"]), n(end["findings"]["total"]),
                *(n(end["findings"][s]) for s in S.STATUS_ORDER), n(end["notes"]), n(end["sources"]), end["polymers"],
                ends, ", ".join("%s at %d" % (m["promptVersion"], m["answer"]) for m in g["markers"]
                                if m["kind"] == "prompt version"),
                ", ".join("%s at %d" % (m["label"], m["answer"]) for m in g["markers"] if m["kind"] == "model change"),
                " and ".join(r["run"] for i, r in enumerate(runs) if i % 2)))


# ----------------------------------------------------------------------------------------------- 3b

def draw_b(fig, size, data):
    c = data["dataset-kf/coverage.json"]
    order = c["classOrder"]
    polymers = collections.defaultdict(list)
    for p in c["polymers"]:
        polymers[p["class"]].append(p)
    unknown = sorted((k for k in polymers if k not in order), key=str)
    gs = S.grid(fig, size, left=0.42, right=0.08, top=0.32, bottom=0.62)
    ax = fig.add_subplot(gs[0])
    gap, pos, starts = 4, 0, []
    xs, heights, empty = [], [], []
    for k in order + unknown:
        group = sorted(polymers[k], key=lambda p: (-p["findings"], p["label"]))
        starts.append((k, pos, pos + len(group) - 1, sum(p["findings"] > 0 for p in group), len(group)))
        for p in group:
            if p["findings"]:
                xs.append(pos)
                heights.append(p["findings"])
            else:
                empty.append(pos)
            pos += 1
        pos += gap
    ax.bar(xs, heights, width=0.8, bottom=0, color=S.INK2, lw=0, zorder=2)
    ax.plot(empty, [0.8] * len(empty), ls="none", marker="|", ms=2.2, mew=0.4, color=S.MUTED, zorder=2)
    ax.set_yscale("log")
    top = max(heights)
    ax.set_ylim(0.7, top * 2.2)
    ax.set_xlim(-gap / 2, pos - gap / 2)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "{:g}".format(v)))
    ax.grid(axis="y", which="major")
    ax.set_xticks([(a + b) / 2 for _, a, b, _, _ in starts])
    ax.set_xticklabels([CLASS_SHORT.get(k, k) for k, *_ in starts], rotation=35, ha="right",
                       rotation_mode="anchor", fontsize=S.TINY)
    ax.tick_params(axis="x", length=0, pad=2)
    for k, a, b, covered, total in starts:
        ax.text((a + b) / 2, top * 1.45, "%d/%d" % (covered, total), ha="center", va="bottom", fontsize=S.TINY,
                color=S.INK2)
        ax.plot([a - 0.4, b + 0.4], [0.7, 0.7], color=S.AXIS, lw=S.HAIR, clip_on=False, solid_capstyle="butt")
    ax.spines["bottom"].set_visible(False)
    ax.set_ylabel("Findings per polymer (log)")
    fig.text(0.42 / size[0], 1 - 0.04 / size[1], "n/N above a class: polymers with findings / polymers in the "
             "class;  ticks at the foot: polymers without findings", ha="left", va="top", fontsize=S.TINY,
             color=S.INK2)
    S.letter(fig, "b")
    s = c["summary"]
    covered = sorted(c["classes"], key=lambda k: (k["withFindings"] / k["polymers"], k["class"]))[:3]
    return ("3b: findings per polymer for all %d polymers of the graph release, grouped by class and sorted within "
            "class (log scale); %d have findings, %d with at least 10 and %d with at least 50; the %d without findings "
            "are ticks at the foot; %s findings (%s%%) without a polymer id are not drawn. Least covered classes: %s." % (
                s["polymers"], s["withFindings"], s["atLeast10"], s["atLeast50"], s["polymers"] - s["withFindings"],
                n(s["findingsWithoutPolymerId"]), S.pct(s["shareWithoutPolymerId"]),
                ", ".join("%s %d of %d" % (k["class"], k["withFindings"], k["polymers"]) for k in covered)))


# ----------------------------------------------------------------------------------------------- 3c

def kind_group(kind):
    return next(i for i, (keys, _, _) in enumerate(KINDS) if kind in keys.split("|"))


def draw_c(fig, size, data):
    rows = data["properties-kf/findings_by_subject_class.csv"]
    order = data["dataset-kf/coverage.json"]["classOrder"]
    cells, kinds = collections.Counter(), collections.defaultdict(collections.Counter)
    for r in rows:
        k = int(r["findings"])
        kinds[r["polymer_class"]][kind_group(r["kind"])] += k
        if r["kind"] == "material-property":
            cells[(r["polymer_class"], r["category"])] += k
    classes = [k for k in order if k in kinds] + sorted(k for k in kinds if k not in order)
    totals = collections.Counter()
    for (k, cat), v in cells.items():
        totals[cat] += v
    cats = sorted(totals, key=lambda cat: (-totals[cat], cat))
    grid = np.ma.masked_equal(np.array([[cells[(k, cat)] for cat in cats] for k in classes], dtype=float), 0)
    left = S.text_width(fig, [CLASS_SHORT.get(k, k) for k in classes]) + 0.12
    # heatmap, colour bar, room for its ticks, side bar; the side bar's totals sit in the right margin
    gs = S.grid(fig, size, 1, 4, left=left, right=0.33, top=0.3, bottom=0.78, width_ratios=[len(cats), 0.3, 1.5, 7.0],
                wspace=0.04)
    ax = fig.add_subplot(gs[0])
    cmap = colors.LinearSegmentedColormap.from_list("oopc-sequential", S.SEQUENTIAL)
    norm = colors.LogNorm(vmin=1, vmax=grid.max())
    mesh = ax.pcolormesh(grid, cmap=cmap, norm=norm, edgecolors=S.SURFACE, linewidth=0.6)
    ax.set_xlim(0, len(cats))
    ax.set_ylim(len(classes), 0)
    ax.set_xticks(np.arange(len(cats)) + 0.5)
    ax.set_xticklabels([CATEGORY.get(cat, cat) for cat in cats], rotation=40, ha="right", rotation_mode="anchor",
                       fontsize=S.TINY)
    ax.set_yticks(np.arange(len(classes)) + 0.5)
    ax.set_yticklabels([CLASS_SHORT.get(k, k) for k in classes], fontsize=S.SMALL)
    ax.tick_params(length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_title("Material-property findings by polymer class and property category", fontsize=S.SMALL)
    cax = fig.add_subplot(gs[1])
    bar = fig.colorbar(mesh, cax=cax)
    bar.outline.set_visible(False)
    bar.ax.tick_params(labelsize=S.TINY, length=2, width=S.HAIR)
    bar.ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "{:g}".format(v)))
    bar.set_label("Findings (log)", fontsize=S.TINY, labelpad=1)
    side = fig.add_subplot(gs[3])
    for i, k in enumerate(classes):
        total, start = sum(kinds[k].values()), 0.0
        for j, (_, name, colour) in enumerate(KINDS):
            share = 100 * kinds[k][j] / total
            side.barh(i + 0.5, share, left=start, height=0.62, color=colour, lw=0, label=name if i == 0 else None)
            start += share
        side.annotate(n(total), (100, i + 0.5), xytext=(2, 0), textcoords="offset points", va="center",
                      fontsize=S.TINY, color=S.INK2, annotation_clip=False)
    side.set_ylim(len(classes), 0)
    side.set_xlim(0, 100)
    side.set_yticks([])
    side.spines["left"].set_visible(False)
    side.set_xticks([0, 25, 50, 75, 100])
    side.xaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))
    side.set_xlabel("Share of the class's findings, by kind", fontsize=S.TINY, labelpad=1)
    side.set_title("All findings with a polymer id", fontsize=S.SMALL)
    side.legend(loc="upper left", bbox_to_anchor=(-0.3, -0.2), ncol=2, fontsize=S.TINY, handlelength=0.8,
                borderaxespad=0)
    S.letter(fig, "c")
    found = data["properties-kf/finding_classes.csv"]
    per_kind = collections.Counter(r["kind"] for r in found)
    pairs = sum(1 for r in rows if r["kind"] == "material-property")
    with_id = sum(int(r["findings"]) for r in rows)
    material = collections.Counter(r["property_class"] for r in found if r["kind"] == "material-property")
    return ("3c: the %s findings with a polymer id, by the graph's polymer class (rows) and the property map's %d "
            "material-property categories with findings (columns; shade: findings, log scale; blank: none), and the "
            "share of each class's findings by kind (right; totals at the bar ends). Over all %s findings %s%% are "
            "material properties, %s%% test conditions, %s%% specimen and preparation, %s%% methods, %s%% "
            "formulation and %s%% other; %d material-property classes have findings, in %s (polymer, property) "
            "pairs." % (
                n(with_id), len(cats), n(len(found)), S.pct(per_kind["material-property"] / len(found)),
                S.pct(per_kind["test-condition"] / len(found)), S.pct(per_kind["specimen-or-preparation"] / len(found)),
                S.pct(per_kind["method-or-instrument"] / len(found)),
                S.pct(per_kind["composition-or-formulation"] / len(found)), S.pct(per_kind["other"] / len(found)),
                len(material), n(pairs)))


# ----------------------------------------------------------------------------------------------- 3d

def draw_d(fig, size, data):
    tg = data["tg-landscape/tg_landscape.json"]
    rows = [r for r in data["tg-landscape/tg_landscape.csv"] if r["property"] == "Tg"]
    polymers = tg["polymers"]
    drawn = collections.Counter(r["polymer_id"] for r in rows)
    labels = ["%s (%d)" % (p["label"] or p["id"], drawn[p["id"]]) for p in polymers]
    left = S.text_width(fig, labels, S.TINY) + 0.1
    gs = S.grid(fig, size, left=left, right=0.1, top=0.34, bottom=0.33)
    ax = fig.add_subplot(gs[0])
    row = {p["id"]: i for i, p in enumerate(polymers)}
    seen = collections.Counter()
    offsets = [0, -0.22, 0.22, -0.11, 0.11]
    for r in sorted(rows, key=lambda r: (int(r["polymer_rank"]), float(r["value_c"]), r["finding_id"])):
        i = row[r["polymer_id"]]
        y = i + offsets[seen[i] % len(offsets)]
        seen[i] += 1
        marker = METHOD_MARK.get(r["method"], ("D", r["method"]))[0]
        colour = S.STATUS.get(r["status"], S.MUTED)
        ax.plot(float(r["value_c"]), y, marker=marker, ms=3.4 if marker != "D" else 2.8, mfc=colour, mec=S.SURFACE,
                mew=0.35, ls="none", zorder=3)
        if r["status"] == "Rejected":  # never beside Reviewed by colour alone
            ax.plot(float(r["value_c"]), y, marker="x", ms=3.4, mec=S.INK, mew=0.5, ls="none", zorder=4)
    for i, p in enumerate(polymers):
        ax.plot([p["medianTg"]] * 2, [i - 0.45, i + 0.45], color=S.INK, lw=0.9, zorder=4, solid_capstyle="butt")
    ax.set_yticks(range(len(polymers)))
    ax.set_yticklabels(labels, fontsize=S.TINY)
    ax.set_ylim(len(polymers) - 0.5, -0.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x")
    values = [float(r["value_c"]) for r in rows]
    ax.set_xlim(min(values) - 15, max(values) + 15)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(100))
    ax.set_xlabel("Tg (°C)")
    methods = collections.Counter(r["method"] for r in rows)
    statuses = collections.Counter(r["status"] for r in rows)
    marks = [plt.Line2D([], [], marker=METHOD_MARK[m][0], ls="none", mfc=S.INK2, mec=S.SURFACE, mew=0.3, ms=3.6,
                        label="%s %d" % (METHOD_MARK[m][1], methods[m])) for m in METHOD_MARK if methods[m]]
    shades = [plt.Line2D([], [], marker="o", ls="none", mfc=S.STATUS[s], mec=S.SURFACE, mew=0.3, ms=3.6,
                         label="%s %d" % (s, statuses[s])) for s in S.STATUS_ORDER if statuses[s]]
    shades.append(plt.Line2D([], [], color=S.INK, marker="|", ls="none", ms=5, mew=0.8, label="Median Tg"))
    width = max(len(marks), len(shades))
    marks += [plt.Line2D([], [], ls="none", label=" ")] * (width - len(marks))
    shades += [plt.Line2D([], [], ls="none", label=" ")] * (width - len(shades))
    # one row of methods over one row of statuses: the legend fills column by column
    fig.legend(handles=[h for pair in zip(marks, shades) for h in pair], loc="upper left",
               bbox_to_anchor=(0.06, 1 - 0.02 / size[1]), ncol=width, fontsize=S.TINY, handletextpad=0.2,
               columnspacing=0.9, borderaxespad=0)
    S.letter(fig, "d", x=0.0)
    both = tg["dmaAboveDsc"]
    split = tg["tgMethodSplit"]
    return ("3d: Tg findings with one readable temperature for the %d polymers with at least 3 such values, sorted by "
            "median Tg (black tick), one point per finding (%d points: DSC %d, DMA %d, other %d, method not stated %d), "
            "marker by method (read from the property, else the conditions), colour by status (%s). Over all %d "
            "readable Tg findings: DSC %d, DMA %d, other %d, not stated %d. In the %d polymers with both DSC and DMA "
            "values, DMA's median is above DSC's in %d, median difference %+.1f °C." % (
                len(polymers), len(rows), methods["DSC"], methods["DMA"], methods["other"], methods["none"],
                ", ".join("%s %d" % (s, statuses[s]) for s in S.STATUS_ORDER if statuses[s]), tg["tgWithReadableValue"],
                split.get("DSC", 0), split.get("DMA", 0), split.get("other", 0), split.get("none", 0),
                both["polymers"], both["dmaAbove"], both["medianDifference"]))


# ----------------------------------------------------------------------------------------------- 3e

def draw_e(fig, size, data):
    s = data["dataset-kf/sources.json"]
    types = sorted(s["byType"], key=lambda t: (t["sources"], t["name"]))
    names = [TYPE_SHORT.get(t["name"], t["name"]) for t in types]
    left = S.text_width(fig, names, S.TINY) + 0.08
    gs = S.grid(fig, size, 1, 2, left=left, right=0.08, top=0.3, bottom=0.33, width_ratios=[1.0, 1.15], wspace=0.28)
    ax = fig.add_subplot(gs[0])
    y = np.arange(len(types))
    yielded = np.array([t["yieldedFindings"] for t in types])
    total = np.array([t["sources"] for t in types])
    ax.barh(y, yielded, height=0.66, color=S.INK2, lw=0, label="Yielded findings")
    ax.barh(y, total - yielded, left=yielded, height=0.66, color=S.LIGHT, lw=0, label="Read without")
    for i, v in enumerate(total):
        ax.annotate(n(v), (v, i), xytext=(2, 0), textcoords="offset points", va="center", fontsize=S.TINY,
                    color=S.INK2, annotation_clip=False)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=S.TINY)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, total.max() * 1.25)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(3))
    S.thousands(ax, "x")
    ax.set_xlabel("Sources", fontsize=S.SMALL)
    ax.grid(axis="x")
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.06, 1 - 0.02 / size[1]), ncol=2,
               fontsize=S.TINY, handlelength=0.8, borderaxespad=0)
    hx = fig.add_subplot(gs[1])
    years = s["publicationYear"]
    yx = np.array([r["year"] for r in years])
    ys = np.array([r["sources"] for r in years])
    yy = np.array([r["yieldedFindings"] for r in years])
    hx.bar(yx, yy, width=0.85, color=S.INK2, lw=0)
    hx.bar(yx, ys - yy, bottom=yy, width=0.85, color=S.LIGHT, lw=0)
    median = s["summary"]["medianYear"]
    hx.axvline(median, color=S.INK, lw=S.HAIR, zorder=3)
    hx.annotate("median %d" % median, (median, ys.max()), xytext=(-2, 0), textcoords="offset points", ha="right",
                va="top", fontsize=S.TINY, color=S.INK)
    hx.set_xlim(yx.min() - 1, yx.max() + 1)
    hx.xaxis.set_major_locator(ticker.MultipleLocator(20))
    hx.set_xlabel("Publication year (DOI sources)", fontsize=S.SMALL)
    hx.set_ylabel("Sources", fontsize=S.SMALL)
    hx.grid(axis="y")
    S.letter(fig, "e")
    ss = s["summary"]
    return ("3e: the %s distinct sources by type, split into %s that yielded findings and %s read without (bar ends: "
            "sources of the type); right, publication years of the %s DOI sources Crossref knows (%d-%d, median %d), "
            "split the same way. Journal articles %s, data sheets %s, patents %s." % (
                n(ss["sources"]), n(ss["yieldedFindings"]), n(ss["readWithoutFindings"]), n(ss["sourcesWithYear"]),
                ss["yearRange"][0], ss["yearRange"][1], median,
                *(n(next((t["sources"] for t in s["byType"] if t["name"] == k), 0))
                  for k in ("journal article", "technical data sheet/manufacturer", "patent"))))


# ----------------------------------------------------------------------------------------------- 3f

def draw_f(fig, size, data):
    c = data["dataset-kf/completeness.json"]
    names = [name for _, name in FIELDS]
    left = S.text_width(fig, names, S.TINY) + 0.08
    gs = S.grid(fig, size, 1, 2, left=left, right=0.16, top=0.3, bottom=0.42, width_ratios=[0.75, 1.75], wspace=0.2)
    ax = fig.add_subplot(gs[0])
    shares = [100 * c["fields"][k]["share"] for k, _ in FIELDS]
    y = np.arange(len(FIELDS))
    ax.barh(y, shares, height=0.62, color=S.INK2, lw=0)
    for i, v in enumerate(shares):
        ax.text(v - 2, i, "%.1f%%" % v, ha="right", va="center", fontsize=S.TINY, color=S.SURFACE)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=S.TINY)
    ax.set_ylim(len(FIELDS) - 0.5, -0.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 50, 100])
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))
    ax.set_xlabel("Findings with the field", fontsize=S.TINY, labelpad=1)
    ax.set_title("Completeness (%s)" % n(c["findings"]), fontsize=S.TINY)
    bx = fig.add_subplot(gs[1])
    spot = c["spotChecksOfAdded"]["campaign"]
    flagged = c["flaggedOutcomes"]["campaign"]
    bars = [("Spot checks of sampled Added findings", [(S.OUTCOME[k], k.replace("unsupported", "rejected"),
                                                       spot.get(k, {}).get("total", 0))
                                                      for k in ("supported", "uncertain", "unsupported")]),
            ("Findings flagged at save", [(s, s, flagged.get(s, 0)) for s in ("Reviewed", "Needs checking", "Rejected")])]
    for i, (title, parts) in enumerate(bars):
        total, start = sum(v for *_, v in parts), 0.0
        for status, _, v in parts:
            bx.barh(i, 100 * v / total, left=start, height=0.34, color=S.STATUS[status], lw=0)
            start += 100 * v / total
        bx.text(0, i - 0.25, "%s (%s)" % (title, n(total)), ha="left", va="bottom", fontsize=S.TINY, color=S.INK)
        bx.text(0, i + 0.23, ", ".join("%s %s" % (n(v), word) for _, word, v in parts), ha="left", va="top",
                fontsize=S.TINY, color=S.INK2)
    bx.set_ylim(1.72, -0.72)
    bx.set_yticks([])
    bx.spines["left"].set_visible(False)
    bx.set_xlim(0, 100)
    bx.set_xticks([0, 50, 100])
    bx.xaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))
    bx.set_title("Campaign reviews, by the status given", fontsize=S.TINY)
    handles = [plt.Rectangle((0, 0), 1, 1, color=S.STATUS[s], lw=0) for s in ("Reviewed", "Needs checking", "Rejected")]
    fig.legend(handles, ["Reviewed", "Needs checking", "Rejected"], loc="lower right",
               bbox_to_anchor=(1 - 0.04 / size[0], 0.01), ncol=3, fontsize=S.TINY, handlelength=0.8, borderaxespad=0,
               columnspacing=0.6)
    S.letter(fig, "f")
    f = c["fields"]
    return ("3f: field completeness over the %s findings (%s), and campaign reviews by the status they gave: spot checks "
            "of sampled Added findings %s supported, %s uncertain, %s rejected; findings flagged at save (by the "
            "researcher or the save step's excerpt check) ended %s Reviewed, %s Needs checking, %s Rejected." % (
                n(c["findings"]), ", ".join("%s %s%%" % (name.lower(), S.pct(f[k]["share"])) for k, name in FIELDS),
                *(n(spot.get(k, {}).get("total", 0)) for k in ("supported", "uncertain", "unsupported")),
                n(flagged.get("Reviewed", 0)), n(flagged.get("Needs checking", 0)), n(flagged.get("Rejected", 0))))


DRAW = {"3a": draw_a, "3b": draw_b, "3c": draw_c, "3d": draw_d, "3e": draw_e, "3f": draw_f}


def assemble(data):
    """Fig. 3 at 7 in wide: a and b; c; d beside e over f. Each panel keeps its own size."""
    w, (ha, hc, hd) = S.DOUBLE, (SIZES["3a"][1], SIZES["3c"][1], SIZES["3d"][1])
    fig = plt.figure(figsize=(w, ha + hc + hd))
    top, middle, bottom = fig.subfigures(3, 1, height_ratios=[ha, hc, hd], hspace=0)
    a, b = top.subfigures(1, 2, width_ratios=[SIZES["3a"][0], SIZES["3b"][0]], wspace=0)
    d, right = bottom.subfigures(1, 2, width_ratios=[SIZES["3d"][0], SIZES["3e"][0]], wspace=0)
    e, f = right.subfigures(2, 1, height_ratios=[SIZES["3e"][1], SIZES["3f"][1]], hspace=0)
    for key, sub in (("3a", a), ("3b", b), ("3c", middle), ("3d", d), ("3e", e), ("3f", f)):
        DRAW[key](sub, SIZES[key], data)
    return fig


def render(base=None, out=None):
    """Draws every panel and the assembled figure from the A1 outputs in `base` (default analysis/) into `out`
    (default analysis/figures/) and records them in the manifest; returns the manifest entry."""
    S.setup()
    data = load(base)
    pinned = S.pins({k: v for k, v in data.items() if isinstance(v, dict)}, "fig3.py")
    panels, captions = [], {}
    for key, draw in DRAW.items():
        fig = plt.figure(figsize=SIZES[key])
        captions[key] = draw(fig, SIZES[key], data)
        files = S.save(fig, "fig" + key, pinned, captions[key], out)
        panels.append({"panel": key, "files": files, "sources": SOURCES[key], "caption": captions[key]})
    whole = "Figure 3, the knowledge base KF as a polymer dataset. " + " ".join(captions.values())
    files = S.save(assemble(data), "fig3", pinned, whole, out)
    entry = {"pins": pinned, "panels": panels,
             "assembled": {"files": files, "panels": list(DRAW), "sources": sorted({s for v in SOURCES.values()
                                                                                    for s in v})}}
    S.record("fig3", entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Fig. 3 from A1's outputs on KF.")
    parser.add_argument("--inputs", type=Path, help="read the A1 outputs here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figures and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    for panel in entry["panels"]:
        print(panel["caption"])
    print("wrote", ", ".join(f for p in entry["panels"] for f in p["files"]), ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
