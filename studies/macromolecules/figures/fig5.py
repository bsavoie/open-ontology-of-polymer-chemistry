#!/usr/bin/env python3
"""Figure 5, the case studies and the planted wrong findings (experiment A5), drawn from `a5/results.json` only (written
by `part_a/a5_results.py` from the records; no store, trace or engine). Every number drawn or written in a caption is
read from that file, never typed in. Each panel shows all five replicates (r1 is the 2026-10-16 run, r2–r5 Part A's).

The blind scoring stores counts per answer, not each value, so panels a–c draw those counts rather than the values
themselves (the figure sketches asked for one mark per value and, in c, each polymer's rank; neither is in the records):

- 5a cs1, conditions travel: per answer (polymer × arm × replicate), the sourced Tg values that name their method and
  also give a condition, that name only their method, and that name neither (stacked above zero), and the values given
  without a citation (below zero); under each bar whether it gave sourced DSC and DMA values and its contradicted
  statements.
- 5b cs2, conflicting values: per answer, sourced oxygen-permeability values with and without a condition (above zero)
  and uncited values (below); under each bar whether its explanation of the spread is labelled as interpretation, and
  its contradicted statements.
- 5c cs3, screening: per replicate and arm, the polymers ranked with a sourced value and the polymers ranked at all (of
  the nine the two questions name), and the new tokens and web calls over the two questions.
- 5d cs4, unanswerable: per question and replicate, new tokens and web calls of the first asking (through the normal
  loop, saved and reviewed) and of the repeats in other words by R (on that store) and P; under each arm, how many
  answers said not found, how many gave a value as reported, and the contradicted statements.
- 5e E9, planted wrong findings: per plant, the share of answers that present the planted value as the source's result,
  give the source's value and flag the planted value, on the untouched store (C), before review (A) and after one review
  (B); pooled over five replicates, with the replicates' range, beside the 2026-10-13 run scored by the same rubric.

Writes `fig5a` … `fig5e` and `fig5` (PDF, SVG, PNG) to `analysis/figures/` (or `--out`) and the `fig5` entry of
`figures/manifest.json`. Commit this script before rendering, so the revision in the pins is on record.

Colours: the arms keep their fixed colours (`style.ARM`: R, the researcher on KF, is KF's blue; R0, the researcher on
an empty store, the ramp's light end; P neutral), with lighter steps of an arm's colour for the parts of a stacked bar.
Panel e's three measures use the reference palette's first slot (blue), second (orange) and the neutral secondary ink;
checked with the dataviz skill's validator on white (`--pairs all`, 2026-10-20): CVD separation worst 18.3 (protan),
normal vision worst 21.8; the grey fails only the chroma floor, as a neutral is meant to.

    OOPC_STUDY_ROOT=<main checkout> python -B fig5.py [--inputs DIR] [--out DIR]
"""
import argparse, collections, statistics, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
from matplotlib.legend_handler import HandlerTuple  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

INPUT = "a5/results.json"
SOURCES = {key: [INPUT] for key in ("5a", "5b", "5c", "5d", "5e")}
SIZES = {"5a": (3.5, 2.45), "5b": (3.5, 2.45), "5c": (3.5, 2.3), "5d": (3.5, 2.3), "5e": (7.0, 2.1)}

TONES = {"R": [S.ARM["KF"], S.ARM["KF1"], S.ARM["K0"]], "P": [S.ARM["P"], S.MUTED, S.LIGHT]}  # dark to light
ARM_COLOUR = {"R": S.ARM["KF"], "R0": S.ARM["K0"], "P": S.ARM["P"], "first": S.ARM["KF"]}
ARM_LABEL = {"R": "R", "R0": "R0", "P": "P", "first": "First asking"}
MEASURE = {"presentsPlanted": ("#eb6834", "presents the planted value"),
           "givesSource": ("#2a78d6", "gives the source's value"),
           "flagsPlanted": (S.INK2, "flags the planted value")}
STAGE = {"C": "C\nuntouched", "A": "A\nbefore\nreview", "B": "B\nafter\nreview"}
# Display names only; the question ids and their order come from the data.
QUESTION = {"tpu": "TPU", "fkm": "FKM", "pva": "PVA", "pvdc": "PVDC", "phbv": "PHBV", "ppc": "PPC",
            "barrier": "barrier ranking", "biodegradable": "biodegradable ranking",
            "fepm-creep": "FEPM creep at 200 °C", "novoloid": "novoloid oxygen permeability", "pox-loi": "PEtOx LOI"}
O2 = r"O$\mathregular{_2}$"  # Arial has no subscript two; mathtext in the regular font draws one
LABEL = dict(QUESTION, **{"novoloid": "novoloid %s permeability" % O2, "fepm-creep": "FEPM creep"})
PLANT = {"gross": "Gross slip", "unit": "Wrong unit", "phase": "Other phase", "conditions": "Wrong load",
         "subtle": "Subtle number"}
QMARK = ["o", "s", "^"]
REVIEW_WORD = {"unsupported": "rejected", "uncertain": "uncertain", "supported": "supported"}


def load(base=None):
    return S.inputs([INPUT], base)


def rows(data, study):
    return [r for r in data[INPUT]["caseStudies"]["answers"] if r["study"] == study]


def questions(data, study):
    """The study's question ids in their recorded order."""
    seen = []
    for r in rows(data, study):
        if r["question"] not in seen:
            seen.append(r["question"])
    return seen


def replicates(data):
    return data[INPUT]["caseStudies"]["replicates"]


def blind(row, key):
    return (row.get("blind") or {}).get(key) or 0


def below(ax, x, depth, text, h_ax, **kw):
    """Text under the axes at data x, `depth` inches below its bottom."""
    ax.text(x, -depth / h_ax, text, transform=ax.get_xaxis_transform(), ha=kw.pop("ha", "center"), va="center",
            fontsize=kw.pop("fontsize", S.TINY), clip_on=False, **kw)


def mark_below(ax, x, depth, filled, colour, h_ax, size=2.6, marker="s"):
    ax.plot([x], [-depth / h_ax], transform=ax.get_xaxis_transform(), marker=marker, ms=size, ls="none",
            mfc=colour if filled else S.SURFACE, mec=colour, mew=0.6, clip_on=False)


def digit(ax, x, depth, value, h_ax):
    below(ax, x, depth, str(value), h_ax, color=S.INK if value else S.LIGHT, fontweight="bold" if value else "normal")


# ----------------------------------------------------------------------------------------------- 5a and 5b

def bars(fig, size, data, study, parts, flag, flag_label, ylabel, letter):
    """Per answer, stacked sourced values (parts: (label, function of a row) from darkest to lightest) above zero and
    uncited values below; under each bar a flag marker and its contradicted statements."""
    reps, qs = replicates(data), questions(data, study)
    left, right, top, bottom = 0.66, 0.05, 0.34, 0.56
    gs = S.grid(fig, size, left=left, right=right, top=top, bottom=bottom)
    ax = fig.add_subplot(gs[0])
    h_ax = size[1] - top - bottom
    found = {(r["question"], r["arm"], r["replicate"]): r for r in rows(data, study)}
    arms = ["R", "P"]
    step, arm_gap, q_gap = 1.0, 1.1, 1.9
    positions, x = {}, 0.0
    for q in qs:
        for arm in arms:
            for k in reps:
                positions[(q, arm, k)] = x
                x += step
            x += arm_gap - step
        x += q_gap - arm_gap
    top_value, low_value = 0, 0
    for (q, arm, k), x in positions.items():
        r = found.get((q, arm, k))
        if not r:
            continue
        base = 0
        for (label, value), colour in zip(parts, TONES[arm]):
            v = value(r)
            if v:
                ax.bar(x, v, bottom=base, width=0.78, color=colour, edgecolor=S.SURFACE, linewidth=0.3, zorder=2)
            base += v
        top_value = max(top_value, base)
        u = blind(r, "uncitedValues")
        if u:
            ax.bar(x, -u, width=0.78, color=S.SURFACE, edgecolor=TONES[arm][0], linewidth=0.6, zorder=2)
        low_value = max(low_value, u)
        mark_below(ax, x, 0.08, flag(r), TONES[arm][0], h_ax)
        digit(ax, x, 0.19, r["contradicted"] or 0, h_ax)
    ax.axhline(0, color=S.INK2, lw=S.HAIR, zorder=3)
    ax.set_ylim(-low_value * 1.08 - 0.5, top_value * 1.08 + 0.5)
    ax.set_xlim(min(positions.values()) - 0.8, max(positions.values()) + 0.8)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(5, integer=True))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "%d" % abs(v)))
    ax.grid(axis="y")
    ax.set_ylabel(ylabel, fontsize=S.SMALL)
    for q in qs:
        for arm in arms:
            xs = [positions[(q, arm, k)] for k in reps]
            below(ax, sum(xs) / len(xs), 0.31, arm, h_ax, color=S.INK2)
        xs = [positions[(q, arm, k)] for arm in arms for k in reps]
        below(ax, sum(xs) / len(xs), 0.44, LABEL.get(q, q), h_ax, fontsize=S.SMALL, color=S.INK)
    x0 = min(positions.values()) - 0.8
    below(ax, x0, 0.08, flag_label, h_ax, ha="right", color=S.INK2)
    below(ax, x0, 0.19, "Contradicted", h_ax, ha="right", color=S.INK2)
    handles = [(Patch(color=TONES["R"][i]), Patch(color=TONES["P"][i])) for i in range(len(parts))]
    handles.append((Patch(facecolor=S.SURFACE, edgecolor=TONES["R"][0], linewidth=0.6),
                    Patch(facecolor=S.SURFACE, edgecolor=TONES["P"][0], linewidth=0.6)))
    labels = [p[0] for p in parts] + ["Uncited (drawn below 0)"]
    fig.legend(handles, labels, handler_map={tuple: HandlerTuple(ndivide=None, pad=0.15)}, loc="upper left",
               bbox_to_anchor=(left / size[0], 1 - 0.03 / size[1]), ncol=2, fontsize=S.TINY, handlelength=1.6,
               columnspacing=1.0, borderaxespad=0)
    S.letter(fig, letter)
    return positions


def totals(data, study, arm, key):
    return sum(blind(r, key) for r in rows(data, study) if r["arm"] == arm)


def draw_a(fig, size, data):
    study = "cs1-conditions"
    parts = [("Method and condition", lambda r: blind(r, "withConditions")),
             ("Method only", lambda r: blind(r, "withMethod") - blind(r, "withConditions")),
             ("No method", lambda r: blind(r, "tgValues") - blind(r, "withMethod"))]
    bars(fig, size, data, study, parts, lambda r: bool(blind(r, "bothDscAndDma")), "DSC and DMA",
         "Tg values per answer", "a")
    reps, qs = replicates(data), questions(data, study)
    t = {arm: {k: totals(data, study, arm, k) for k in ("tgValues", "withMethod", "withConditions", "uncitedValues",
                                                        "bothDscAndDma")} for arm in ("R", "P")}
    contra = {arm: sum(r["contradicted"] or 0 for r in rows(data, study) if r["arm"] == arm) for arm in ("R", "P")}
    return ("5a, cs1 (conditions travel): Tg of %s, asked of the researcher on KF (R) and a plain session (P) in %d "
            "replicates; one bar per answer, replicates left to right. Above zero, the sourced Tg values the blind "
            "scorer counted, split into those naming their method and a condition, their method only, or neither; "
            "below zero, values without a citation. The records keep these counts per answer, not each value, so "
            "counts are drawn. Over the %d replicates R gave %d sourced values (%d with a method, %d also with a "
            "condition) and %d uncited; P %d sourced (%d, %d) and %d uncited. Sourced DSC and DMA values for the "
            "polymer (filled square): R %d of %d answers, P %d. Contradicted statements (digits): R %d, P %d." % (
                ", ".join(QUESTION.get(q, q) for q in qs), len(reps), len(reps), t["R"]["tgValues"],
                t["R"]["withMethod"], t["R"]["withConditions"], t["R"]["uncitedValues"], t["P"]["tgValues"],
                t["P"]["withMethod"], t["P"]["withConditions"], t["P"]["uncitedValues"], t["R"]["bothDscAndDma"],
                len(reps) * len(qs), t["P"]["bothDscAndDma"], contra["R"], contra["P"]))


def draw_b(fig, size, data):
    study = "cs2-conflicts"
    parts = [("With a condition", lambda r: blind(r, "withConditions")),
             ("No condition", lambda r: blind(r, "sourcedValues") - blind(r, "withConditions"))]
    bars(fig, size, data, study, parts, lambda r: bool(blind(r, "explanationLabelled")), "Labelled",
         "%s permeability values per answer" % O2, "b")
    reps, qs = replicates(data), questions(data, study)
    t = {arm: {k: totals(data, study, arm, k) for k in ("sourcedValues", "withConditions", "uncitedValues",
                                                        "explainsDifferences", "explanationLabelled")}
         for arm in ("R", "P")}
    contra = {arm: sum(r["contradicted"] or 0 for r in rows(data, study) if r["arm"] == arm) for arm in ("R", "P")}
    least = min(blind(r, "withConditions") for r in rows(data, study) if r["arm"] == "R")
    return ("5b, cs2 (conflicting values): oxygen permeability of %s films, why published values differ; R and P, "
            "%d replicates, one bar per answer. Above zero, sourced permeability, permeance or transmission values "
            "with and without a stated condition (thickness, temperature, humidity, crystallinity, processing); below "
            "zero, uncited values (counts per answer, as the records keep them). R gave %d sourced values (%d with a "
            "condition; at least %d with a condition in every answer) and %d uncited; P %d (%d) and %d. Every answer "
            "explained the spread (R %d, P %d of %d); the explanation was labelled as interpretation (filled square) "
            "in R %d and P %d. Contradicted statements: R %d, P %d." % (
                ", ".join(QUESTION.get(q, q) for q in qs), len(reps), t["R"]["sourcedValues"],
                t["R"]["withConditions"], least, t["R"]["uncitedValues"], t["P"]["sourcedValues"],
                t["P"]["withConditions"], t["P"]["uncitedValues"], t["R"]["explainsDifferences"],
                t["P"]["explainsDifferences"], len(reps) * len(qs), t["R"]["explanationLabelled"],
                t["P"]["explanationLabelled"], contra["R"], contra["P"]))


# ----------------------------------------------------------------------------------------------- 5c

def per_arm(data, study, arm, k, key, blind_key=False):
    mine = [r for r in rows(data, study) if r["arm"] == arm and r["replicate"] == k]
    return sum((blind(r, key) if blind_key else (r[key] or 0)) for r in mine)


def dodge(reps, width=0.32):
    n = len(reps)
    return {k: (i - (n - 1) / 2) * (width / max(n - 1, 1)) for i, k in enumerate(reps)}


def draw_c(fig, size, data):
    study, arms = "cs3-screening", ["R", "R0", "P"]
    reps = replicates(data)
    off = dodge(reps)
    left, top, bottom = 0.62, 0.34, 0.42
    gs = S.grid(fig, size, 2, 2, left=left, right=0.08, top=top, bottom=bottom, width_ratios=[1.2, 1],
                wspace=0.55, hspace=0.35)
    ax = fig.add_subplot(gs[:, 0])
    h_ax = size[1] - top - bottom
    asked = max(per_arm(data, study, "R", k, "polymersAsked", True) for k in reps)
    for k in reps:
        ys = [per_arm(data, study, a, k, "rankedWithSourcedValue", True) for a in arms]
        xs = [i + off[k] for i in range(len(arms))]
        ax.plot(xs, ys, color=S.LIGHT, lw=0.6, zorder=1)
        for i, a in enumerate(arms):
            ranked = per_arm(data, study, a, k, "polymersRanked", True)
            ax.plot(xs[i], ranked, marker="o", ms=3.4, mfc=S.SURFACE, mec=ARM_COLOUR[a], mew=0.6, ls="none", zorder=2)
            ax.plot(xs[i], ys[i], marker="o", ms=3.4, mfc=ARM_COLOUR[a], mec=S.SURFACE, mew=0.3, ls="none", zorder=3)
    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels(arms)
    ax.set_xlim(-0.5, len(arms) - 0.5)
    ax.set_ylim(0, asked + 0.6)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(3))
    ax.set_ylabel("Polymers of %d" % asked, fontsize=S.SMALL)
    ax.grid(axis="y")
    for i, a in enumerate(arms):
        below(ax, i, 0.24, " ".join(str(per_arm(data, study, a, k, "contradicted")) for k in reps), h_ax,
              color=S.INK)
    below(ax, -0.55, 0.24, "Contradicted", h_ax, ha="right", color=S.INK2)
    handles = [plt.Line2D([], [], marker="o", ms=3.4, ls="none", mfc=S.INK2, mec=S.SURFACE, mew=0.3),
               plt.Line2D([], [], marker="o", ms=3.4, ls="none", mfc=S.SURFACE, mec=S.INK2, mew=0.6)]
    fig.legend(handles, ["Ranked with a sourced value", "Ranked"], loc="upper left",
               bbox_to_anchor=(left / size[0], 1 - 0.03 / size[1]), ncol=2, fontsize=S.TINY, borderaxespad=0)
    tokens = {a: [per_arm(data, study, a, k, "newTokens") / 1e3 for k in reps] for a in arms}
    web = {a: [per_arm(data, study, a, k, "webCalls") for k in reps] for a in arms}
    for row, (values, label) in enumerate(((tokens, "New tokens (k)"), (web, "Web calls"))):
        sub = fig.add_subplot(gs[row, 1])
        for i, a in enumerate(arms):
            xs = [i + off[k] for k in reps]
            sub.plot(xs, values[a], marker="o", ms=2.8, ls="none", mfc=ARM_COLOUR[a], mec=S.SURFACE, mew=0.3,
                     zorder=3)
            m = statistics.median(values[a])
            sub.plot([i - 0.28, i + 0.28], [m, m], color=S.INK, lw=0.9, zorder=4, solid_capstyle="butt")
        sub.set_xlim(-0.5, len(arms) - 0.5)
        sub.set_ylim(0, max(max(v) for v in values.values()) * 1.12)
        sub.yaxis.set_major_locator(ticker.MaxNLocator(3))
        sub.set_xticks(range(len(arms)))
        sub.set_xticklabels(arms if row else [])
        sub.set_title(label + ", two questions", fontsize=S.TINY, loc="left", pad=1.5, color=S.INK2)
        sub.grid(axis="y")
    S.letter(fig, "c")
    ranked = {a: [per_arm(data, study, a, k, "rankedWithSourcedValue", True) for k in reps] for a in arms}
    contra = {a: [per_arm(data, study, a, k, "contradicted") for k in reps] for a in arms}
    kinds = collections.Counter(kind for r in rows(data, study) if r["arm"] == "R" for kind in r["contradictedKinds"])
    own = (", all %d of the checker's kind inference, the researcher's own interpretations (CL-24: unit conversions "
           "and orderings)" % sum(kinds.values())) if kinds and set(kinds) == {"inference"} else (
        " (kinds: %s)" % ", ".join("%s %d" % kv for kv in sorted(kinds.items())) if kinds else "")
    return ("5c, cs3 (screening): two rankings by oxygen permeability naming %d polymers, answered by R, by the "
            "researcher on an empty store (R0) and by P in %d replicates (lines join a replicate's arms). Left: "
            "polymers ranked with a sourced value with units (filled) and ranked at all (hollow), counted by the blind "
            "scorer; per replicate R %s, R0 %s, P %s (each polymer's rank is not in the records). Right: new tokens "
            "and web calls over the two questions per replicate (bar: median); median tokens R %.0fk, R0 %.0fk, P "
            "%.0fk; web calls R %s, R0 %s, P %s. Contradicted statements per replicate (digits): R %s%s; R0 %s; "
            "P %s." % (
                asked, len(reps), "/".join(map(str, ranked["R"])), "/".join(map(str, ranked["R0"])),
                "/".join(map(str, ranked["P"])), statistics.median(tokens["R"]), statistics.median(tokens["R0"]),
                statistics.median(tokens["P"]), "/".join(map(str, web["R"])), "/".join(map(str, web["R0"])),
                "/".join(map(str, web["P"])), "/".join(map(str, contra["R"])), own, "/".join(map(str, contra["R0"])),
                "/".join(map(str, contra["P"]))))


# ----------------------------------------------------------------------------------------------- 5d

def draw_d(fig, size, data):
    reps = replicates(data)
    cs4 = rows(data, "cs4-first") + rows(data, "cs4-repeat")
    stages = [("cs4-first", "first"), ("cs4-repeat", "R"), ("cs4-repeat", "P")]
    labels = ["First asking", "Repeat, R", "Repeat, P"]
    qs = questions(data, "cs4-first")
    offset = {q: (i - (len(qs) - 1) / 2) * 0.2 for i, q in enumerate(qs)}
    left, top, bottom = 0.62, 0.3, 0.62
    gs = S.grid(fig, size, 2, 1, left=left, right=0.08, top=top, bottom=bottom, hspace=0.25)
    h_ax = size[1] - top - bottom
    axes = [fig.add_subplot(gs[0])]
    axes.append(fig.add_subplot(gs[1], sharex=axes[0]))
    pick = lambda study, arm, q, k: next(r for r in cs4 if r["study"] == study and r["arm"] == arm
                                         and r["question"] == q and r["replicate"] == k)
    for ax, key, scale, label in ((axes[0], "newTokens", 1e3, "New tokens (k)"), (axes[1], "webCalls", 1,
                                                                                 "Web calls")):
        for qi, q in enumerate(qs):
            medians = []
            for si, (study, arm) in enumerate(stages):
                values = [(pick(study, arm, q, k)[key] or 0) / scale for k in reps]
                x = si + offset[q]
                ax.plot([x] * len(values), values, marker=QMARK[qi], ms=2.6, ls="none", mfc=ARM_COLOUR[arm],
                        mec=S.SURFACE, mew=0.3, alpha=0.75, zorder=2)
                medians.append(statistics.median(values))
            ax.plot([si + offset[q] for si in range(len(stages))], medians, color=S.INK, lw=0.8, marker=QMARK[qi],
                    ms=3.4, mfc=S.SURFACE, mec=S.INK, mew=0.7, zorder=3)
        ax.set_ylabel(label, fontsize=S.SMALL)
        ax.set_ylim(0, None)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(3))
        ax.grid(axis="y")
    axes[1].set_xticks(range(len(stages)))
    axes[1].set_xticklabels(labels)
    axes[1].set_xlim(-0.5, len(stages) - 0.5)
    plt.setp(axes[0].get_xticklabels(), visible=False)
    for si, (study, arm) in enumerate(stages):
        mine = [r for r in cs4 if r["study"] == study and r["arm"] == arm]
        below(axes[1], si, 0.25, "%d of %d" % (sum(bool(blind(r, "saysNotFound")) for r in mine), len(mine)), h_ax / 2,
              color=S.INK)
        below(axes[1], si, 0.36, "%d" % sum(bool(blind(r, "givesValueAsReported")) for r in mine), h_ax / 2,
              color=S.INK)
        below(axes[1], si, 0.47, " ".join(str(sum(r["contradicted"] or 0 for r in mine if r["replicate"] == k))
                                             for k in reps), h_ax / 2, color=S.INK)
    for depth, text in ((0.25, "Not found"), (0.36, "Value given"), (0.47, "Contradicted")):
        below(axes[1], -0.5, depth, text, h_ax / 2, ha="right", color=S.INK2)
    handles = [plt.Line2D([], [], color=S.INK, lw=0.8, marker=QMARK[i], ms=3.4, mfc=S.SURFACE, mec=S.INK, mew=0.7)
               for i in range(len(qs))]
    fig.legend(handles, [LABEL.get(q, q) for q in qs], loc="upper left", bbox_to_anchor=(
        left / size[0], 1 - 0.03 / size[1]), ncol=3, fontsize=S.TINY, borderaxespad=0, columnspacing=0.8)
    S.letter(fig, "d")
    pairs = []
    for k in reps:
        for q in qs:
            pairs.append(pick("cs4-repeat", "R", q, k)["newTokens"] / pick("cs4-first", "first", q, k)["newTokens"])
    web = {arm: sum(r["webCalls"] or 0 for r in cs4 if (r["study"], r["arm"]) == (s, arm)) for s, arm in stages}
    tok = {arm: statistics.median([r["newTokens"] for r in cs4 if (r["study"], r["arm"]) == (s, arm)]) / 1e3
           for s, arm in stages}
    found = sum(bool(blind(r, "saysNotFound")) for r in cs4)
    valued = sum(bool(blind(r, "givesValueAsReported")) for r in cs4)
    notes = [((r.get("deposit") or {}).get("notes") or 0) for r in cs4 if r["study"] == "cs4-first"]
    contra = {arm: sum(r["contradicted"] or 0 for r in cs4 if (r["study"], r["arm"]) == (s, arm)) for s, arm in stages}
    review = collections.Counter((r.get("deposit") or {}).get("reviewStatus") for r in cs4 if r["study"] == "cs4-first")
    return ("5d, cs4 (unanswerable): %s, first asked through the normal loop on a copy of KF (answer saved, %d to %d "
            "source notes per asking; deposit review: %s), then asked again in other words by R on that store and "
            "by P; %d replicates. Small marks: each replicate (marker by question); open marks and lines: medians. "
            "Median new tokens %.0fk first, %.0fk R repeat, %.0fk P repeat; the R-repeat/first token ratio's median "
            "over the %d pairs %.2f (repeat cheaper in %d). Web calls %d, %d and %d. %d of %d answers said no "
            "published value was found and %d gave a value as reported (blind scorer). Contradicted statements: "
            "first %d, R %d, P %d." % (
                ", ".join(QUESTION.get(q, q) for q in qs), min(notes), max(notes),
                ", ".join("%s %d" % kv for kv in sorted(review.items(), key=lambda kv: str(kv[0]))), len(reps),
                tok["first"], tok["R"],
                tok["P"], len(pairs), statistics.median(pairs), sum(p < 1 for p in pairs), web["first"], web["R"],
                web["P"], found, len(cs4), valued, contra["first"], contra["R"], contra["P"]))


# ----------------------------------------------------------------------------------------------- 5e

def shares(answers, case, arm, key, by_replicate=True):
    mine = [r for r in answers if r["case"] == case and r["arm"] == arm]
    pooled = sum(bool(r[key]) for r in mine) / len(mine) if mine else None
    if not by_replicate:
        return pooled, None, None, len(mine)
    per = collections.defaultdict(list)
    for r in mine:
        per[r["replicate"]].append(bool(r[key]))
    values = [sum(v) / len(v) for v in per.values()]
    return pooled, min(values), max(values), len(mine)


def draw_e(fig, size, data):
    e9 = data[INPUT]["e9"]
    cases, arms = e9["cases"], ["C", "A", "B"]
    now, then = e9["answers"], e9["record20261013"]["answers"]
    gs = S.grid(fig, size, 1, len(cases), left=0.42, right=0.05, top=0.62, bottom=0.42, wspace=0.18)
    old_review = e9["record20261013"]["reviewVerdicts"]
    off = {k: (i - 1) * 0.15 for i, k in enumerate(MEASURE)}
    reviews = e9["reviews"]
    axes = []
    for ci, case in enumerate(cases):
        ax = fig.add_subplot(gs[ci], sharey=axes[0] if axes else None)
        axes.append(ax)
        for key, (colour, _) in MEASURE.items():
            xs = [i + off[key] for i in range(len(arms))]
            old = [shares(then, case, a, key, False)[0] for a in arms]
            ax.plot(xs, old, marker="o", ms=6.2, ls="none", mfc="none", mec=colour, mew=0.7, zorder=5)
            got = [shares(now, case, a, key) for a in arms]
            for x, (p, lo, hi, n) in zip(xs, got):
                ax.plot([x, x], [lo, hi], color=colour, lw=1.4, alpha=0.45, solid_capstyle="butt", zorder=3)
            ax.plot(xs, [g[0] for g in got], color=colour, lw=S.LINE, marker="o", ms=3.4, mfc=colour, mec=S.SURFACE,
                    mew=0.3, zorder=4)
        rejected = sum((r["verdicts"].get(case) or {}).get("status") == "unsupported" for r in reviews.values())
        ax.set_title("%s\nrejected in %d of %d reviews" % (PLANT.get(case, case), rejected, len(reviews)),
                     fontsize=S.TINY, loc="left", pad=2, color=S.INK)
        ax.set_xticks(range(len(arms)))
        ax.set_xticklabels([STAGE[a] for a in arms], fontsize=S.TINY, linespacing=0.9)
        ax.set_xlim(-0.45, len(arms) - 0.55)
        ax.set_ylim(-0.06, 1.06)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(0.5))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "%d%%" % round(100 * v)))
        ax.grid(axis="y")
        ax.axvspan(1.5, 2.45, color=S.BAND, lw=0, zorder=0)
        if ci:
            plt.setp(ax.get_yticklabels(), visible=False)
    axes[0].set_ylabel("Share of answers", fontsize=S.SMALL)
    handles = [plt.Line2D([], [], color=c, lw=S.LINE, marker="o", ms=3.4, mfc=c, mec=S.SURFACE, mew=0.3)
               for c, _ in MEASURE.values()]
    labels = [label for _, label in MEASURE.values()]
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.42 / size[0], 1 - 0.02 / size[1]), ncol=3,
               fontsize=S.TINY, borderaxespad=0, columnspacing=1.2, handlelength=1.8)
    words = collections.defaultdict(list)
    for case in cases:
        words[REVIEW_WORD.get((old_review.get(case) or {}).get("status"), "not reviewed")].append(PLANT[case].lower())
    fig.text(0.42 / size[0], 1 - 0.19 / size[1], "Dots: the freeze, pooled over %d replicates (bar: their range). "
             "Rings: the 2026-10-13 run (its review: %s)." % (len(e9["replicates"]), "; ".join(
                 "%s %s" % (", ".join(v), k) for k, v in sorted(words.items(), key=lambda kv: -len(kv[1])))),
             ha="left", va="top", fontsize=S.TINY, color=S.INK2)
    S.letter(fig, "e")
    o, old = e9["overall"], e9["record20261013"]["counts"]
    verdicts = collections.Counter((v or {}).get("status") for r in reviews.values() for v in r["verdicts"].values())
    old_verdicts = collections.Counter(v["status"] for v in e9["record20261013"]["reviewVerdicts"].values())
    return ("5e, E9 (planted wrong findings): %d Reviewed findings replaced by wrong versions filed as Added without "
            "an excerpt, one question each, answered on the untouched store KF (C, once per replicate), on the "
            "planted store before review (A, twice) and after one normal review (B, twice), in %d replicates at the "
            "freeze (filled marks: shares pooled over the replicates, n = %d, %d and %d per plant; bars: the range of "
            "the replicates' shares) and once on 2026-10-13 on K3 under the earlier freeze and prompt (rings; n = %d, "
            "%d, %d), "
            "all scored blind by one rubric. The reviewer rejected %d of the %d plants at the freeze (2026-10-13: %d "
            "rejected, %d uncertain). Before review no answer presented a planted value (%d of %d; 2026-10-13 %d of "
            "%d) and all flagged it (%d of %d; 2026-10-13 %d of %d), giving the source's value in %d. After review "
            "none presented one (%d of %d) and %d of %d gave the source's value (2026-10-13 %d of %d); C gave it in "
            "%d of %d." % (
                len(cases), len(e9["replicates"]), o["C"]["byCase"][cases[0]]["answers"], o["A"]["byCase"][cases[0]]["answers"],
                o["B"]["byCase"][cases[0]]["answers"], old["C"]["byCase"][cases[0]]["answers"],
                old["A"]["byCase"][cases[0]]["answers"], old["B"]["byCase"][cases[0]]["answers"],
                verdicts["unsupported"], sum(verdicts.values()), old_verdicts["unsupported"], old_verdicts["uncertain"],
                o["A"]["presentsPlanted"], o["A"]["answers"], old["A"]["presentsPlanted"], old["A"]["answers"],
                o["A"]["flagsPlanted"], o["A"]["answers"], old["A"]["flagsPlanted"], old["A"]["answers"],
                o["A"]["givesSource"], o["B"]["presentsPlanted"], o["B"]["answers"], o["B"]["givesSource"],
                o["B"]["answers"], old["B"]["givesSource"], old["B"]["answers"], o["C"]["givesSource"],
                o["C"]["answers"]))


# ----------------------------------------------------------------------------------------------- assembly

DRAW = {"5a": draw_a, "5b": draw_b, "5c": draw_c, "5d": draw_d, "5e": draw_e}


def assemble(data):
    """Fig. 5 at 7 in wide: a beside b; c beside d; e across. Each panel keeps its own size."""
    heights = [SIZES["5a"][1], SIZES["5c"][1], SIZES["5e"][1]]
    fig = plt.figure(figsize=(S.DOUBLE, sum(heights)))
    first, second, third = fig.subfigures(3, 1, height_ratios=heights, hspace=0)
    a, b = first.subfigures(1, 2, width_ratios=[SIZES["5a"][0], SIZES["5b"][0]], wspace=0)
    c, d = second.subfigures(1, 2, width_ratios=[SIZES["5c"][0], SIZES["5d"][0]], wspace=0)
    for key, sub in (("5a", a), ("5b", b), ("5c", c), ("5d", d), ("5e", third)):
        DRAW[key](sub, SIZES[key], data)
    return fig


def render(base=None, out=None):
    """Draws every panel and the assembled figure from `a5/results.json` in `base` (default analysis/) into `out`
    (default analysis/figures/) and records them in the manifest; returns the manifest entry."""
    S.setup()
    data = load(base)
    pinned = S.pins(data, "fig5.py")
    meta = data[INPUT]["meta"]
    pinned["records"] = meta.get("records")
    panels, captions = [], {}
    for key, draw in DRAW.items():
        fig = plt.figure(figsize=SIZES[key])
        captions[key] = draw(fig, SIZES[key], data)
        files = S.save(fig, "fig" + key, pinned, captions[key], out)
        panels.append({"panel": key, "files": files, "sources": SOURCES[key], "caption": captions[key]})
    whole = ("Figure 5, the case studies and the planted wrong findings, five replicates each (A5; code study-freeze-2, "
             "prompt %s, KF). " % meta["prompt"]) + " ".join(captions.values())
    files = S.save(assemble(data), "fig5", pinned, whole, out)
    entry = {"pins": pinned, "panels": panels, "assembled": {"files": files, "panels": list(DRAW), "sources": [INPUT]}}
    S.record("fig5", entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Fig. 5 from A5's results.")
    parser.add_argument("--inputs", type=Path, help="read a5/results.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figures and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    for panel in entry["panels"]:
        print(panel["caption"])
    print("wrote", ", ".join(f for p in entry["panels"] for f in p["files"]), ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
