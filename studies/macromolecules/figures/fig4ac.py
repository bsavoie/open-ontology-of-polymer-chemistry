#!/usr/bin/env python3
"""Figure 4a (memory ablation, with E8's second engine) and 4c (scaling with the store's size), drawn from
`a2a3e8/results.json` only (written by `part_a/a2a3e8_results.py` from A2, A3 and E8's pre-registered reports and rows;
no store, trace or engine). Every number drawn or written in a caption is read from that file, never typed in.

- 4a, A2 and E8. Left, one column per stratum (near, mid, far; 20 questions × 3 replicates = 60 answers per arm) for P,
  K0 and KF, and a fourth for the 20 near questions answered by the researcher on Claude Code (E8: K0c, KFc, one
  answer each): the share of answers that are complete, that give a sourced result and that pass (hollow, second:
  CL-21), and below them contradicted statements per answer, with each count printed. Middle, a forest plot of the paired
  KF/K0 ratio (median over questions of each arm's pooled replicates, bootstrap 95% interval) of new tokens and of time
  per stratum, and KFc/K0c on Claude Code beside it; a line at 1. Right, the mean web calls per answer, K0 to KF.
- 4c, A2 and A3: x is the findings in the store (log), with A2's K0, KF200, KF1, KF2 and KF marked; one column per
  stratum; three rows sharing x. Row 1, new tokens against K0 (paired ratio, log): A2's store arms with their intervals,
  A3's 20 resampled stores (100, 200, 400 and 800 of KF's questions × 5 seeds) as small marks and A3's same-day K0 and
  KF anchors as open diamonds; each stratum's within-question scaling slope (A2 and A3) is written in the panel. Row 2,
  contradicted statements per answer, the web-off arms MF1 and MF included. Row 3, the share of answers citing a
  saved finding (web on and off) and, with the web off, the share giving a sourced result and the share complete.

Writes `fig4a`, `fig4c` and the assembled `fig4ac` (PDF, SVG, 200 dpi PNG) to `analysis/figures/` (or `--out`) and the
`fig4ac` entry of `figures/manifest.json`, keeping the others. Commit this script before rendering, so the revision in
the pins is on record.

Colours: the arms keep their fixed colours (`style.ARM`: P neutral; the stores a blue ramp, light to dark with size;
the web-off arms orange; A3's resampled stores the magenta ramp by size); E8's K0c and KFc take K0's and KF's colours,
as they answer on the same stores. Measures are told apart by marker shape, not colour, so no new colour is added.

    OOPC_STUDY_ROOT=<main checkout> python -B fig4ac.py [--inputs DIR] [--out DIR]
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

INPUT = "a2a3e8/results.json"
SOURCES = {"4a": [INPUT], "4c": [INPUT]}
SIZES = {"4a": (7.0, 2.62), "4c": (7.0, 3.9)}
STRATA = ["near", "mid", "far"]
TITLE = {"near": "Near", "mid": "Mid", "far": "Far"}
STORES = ["K0", "KF200", "KF1", "KF2", "KF"]  # A2's researcher arms with web on
MEMORY = ["MF1", "MF"]  # web off, on KF1 and KF
E8_COLOUR = {"K0c": S.ARM["K0"], "KFc": S.ARM["KF"]}
MS, MS_SMALL = 3.6, 2.3  # marker sizes, points


def load(base=None):
    return S.inputs([INPUT], base)


def axes(fig, size, x, y, w, h, **kw):
    """Axes at (x, y) with width w and height h, in inches from the bottom left of `fig` (a figure or subfigure)."""
    W, H = size
    return fig.add_axes([x / W, y / H, w / W, h / H], **kw)


def num(x, places=2):
    return ("%.*f" % (places, x)).replace("-", "−")


def ci(v, places=2):
    if not v or "low" not in v:
        return "\u2013"
    centre = v.get("median", v.get("mean", v.get("estimate")))
    return "%s (%s%s%s)" % (num(centre, places), num(v["low"], places), " to " if v["low"] < 0 else "–",
                            num(v["high"], places))


def share(counts, key):
    return counts[key] / counts["answered"] if counts["answered"] else float("nan")


def thousands(v):
    return "{:,}".format(int(v))


def dot(ax, x, y, colour, marker="o", ms=MS, hollow=False, z=4, see_through=False, **kw):
    """One mark; `hollow` marks have a white face, or none when `see_through` (a ring over another mark)."""
    face = ("none" if see_through else S.SURFACE) if hollow else colour
    ax.plot([x], [y], marker=marker, ms=ms, ls="none", mfc=face, mec=colour if hollow else S.SURFACE,
            mew=0.7 if hollow else 0.3, zorder=z, clip_on=False, **kw)


# ----------------------------------------------------------------------------------------------- 4a

MEASURES = [("complete", "o", False, "complete"), ("resultGiven", "s", False, "sourced result"),
            ("pass", "o", True, "passes (second)")]


def quality(ax_s, ax_c, arms, counts, colours, labels):
    """Shares (complete, sourced result, pass) above, contradicted statements per answer below, per arm."""
    off = {"complete": -0.24, "resultGiven": 0.0, "pass": 0.24}
    for i, arm in enumerate(arms):
        c = counts[arm]
        for key, marker, hollow, _ in MEASURES:
            dot(ax_s, i + off[key], share(c, key), colours[arm], marker, MS + (0.6 if hollow else 0), hollow)
        per = c["contradicted"] / c["answered"]
        ax_c.bar(i, per, width=0.5, color=colours[arm], lw=0, zorder=3)
        ax_c.text(i, per, "%d" % c["contradicted"], ha="center", va="bottom", fontsize=S.TINY, color=S.INK,
                  fontweight="bold" if c["contradicted"] else "normal")
    for ax in (ax_s, ax_c):
        ax.set_xlim(-0.55, len(arms) - 0.45)
        ax.set_xticks(range(len(arms)))
    ax_s.set_xticklabels([])
    ax_c.set_xticklabels(labels, fontsize=S.SMALL)
    ax_s.set_ylim(0, 1.06)
    ax_s.yaxis.set_major_locator(ticker.FixedLocator([0, 0.5, 1]))
    ax_s.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "%d%%" % round(100 * v)))
    ax_s.grid(axis="y")
    ax_c.set_ylim(0, 1.75)
    ax_c.yaxis.set_major_locator(ticker.FixedLocator([0, 1]))
    ax_c.grid(axis="y")
    ax_c.tick_params(axis="x", length=0, pad=2)


def draw_a(fig, size, data):
    v = data[INPUT]
    A2, E8 = v["A2"], v["E8"]
    W, H = size
    top, bottom, gap, contra_h = 0.47, 0.27, 0.07, 0.4
    share_h = H - top - bottom - gap - contra_h
    left, qw, qgap, e8gap = 0.45, 0.74, 0.1, 0.24
    codex_arms = ["P", "K0", "KF"]
    cols = []
    for i, stratum in enumerate(STRATA):
        x = left + i * (qw + qgap)
        part = A2["byStratum"][stratum]["arms"]
        cols.append((x, qw, TITLE[stratum], codex_arms, part, dict(S.ARM), codex_arms,
                     part["KF"]["answered"]))
    x = left + 3 * (qw + qgap) + e8gap - qgap
    e8 = E8["byStratum"]["near"]["arms"]
    cols.append((x, qw * 0.8, "Near, Claude Code", ["K0c", "KFc"], e8, E8_COLOUR, ["K0c", "KFc"],
                 e8["KFc"]["answered"]))
    first = None
    for x, w, title, arms, counts, colours, labels, n in cols:
        ax_s = axes(fig, size, x, bottom + contra_h + gap, w, share_h, sharey=first[0] if first else None)
        ax_c = axes(fig, size, x, bottom, w, contra_h, sharey=first[1] if first else None)
        quality(ax_s, ax_c, arms, counts, colours, labels)
        ax_s.set_title("%s\n%d answers per arm" % (title, n), fontsize=S.TINY, loc="left", pad=2, color=S.INK,
                       linespacing=1.0)
        if first:
            plt.setp(ax_s.get_yticklabels(), visible=False)
            plt.setp(ax_c.get_yticklabels(), visible=False)
        else:
            first = (ax_s, ax_c)
            ax_s.set_ylabel("Share of answers", fontsize=S.SMALL)
            ax_c.set_ylabel("Contradicted\nper answer", fontsize=S.TINY, linespacing=1.0)
    divider = cols[3][0] - e8gap / 2
    fig.add_artist(plt.Line2D([divider / W] * 2, [bottom / H, (H - top + 0.25) / H], color=S.AXIS, lw=S.HAIR))

    # forest plot and web calls, one row per stratum and E8's near row below a gap
    fx, fw, wx, ww = 4.38, 1.55, 6.08, 0.86
    fy, fh = bottom, H - top - bottom
    ax_f = axes(fig, size, fx, fy, fw, fh)
    ax_w = axes(fig, size, wx, fy, ww, fh, sharey=ax_f)
    rows = [(TITLE[s], A2["byStratum"][s]["paired"]["KF"], A2["byStratum"][s]["arms"], "K0", "KF") for s in STRATA]
    rows.append(("Near,\nClaude Code", E8["byStratum"]["near"]["paired"]["KFc"], e8, "K0c", "KFc"))
    ys = [4.0, 3.0, 2.0, 0.75]
    for y, (label, p, counts, ref, arm) in zip(ys, rows):
        colour = S.ARM["KF"]
        for key, dy, hollow in (("tokens", 0.14, False), ("seconds", -0.14, True)):
            r = p[key]
            ax_f.plot([r["low"], r["high"]], [y + dy] * 2, color=colour, lw=S.LINE, solid_capstyle="butt", zorder=3)
            dot(ax_f, r["median"], y + dy, colour, "o", MS + (0.4 if hollow else 0.4), hollow, z=4)
        ax_f.text(p["tokens"]["high"] * 1.07, y + 0.14, num(p["tokens"]["median"]), ha="left", va="center",
                  fontsize=S.TINY, color=S.INK)
        a, b = counts[ref]["meanWebCalls"], counts[arm]["meanWebCalls"]
        ax_w.plot([a, b], [y, y], color=S.LIGHT, lw=1.4, solid_capstyle="butt", zorder=2)
        dot(ax_w, a, y, S.ARM["K0"], "o", MS + 0.4)
        dot(ax_w, b, y, S.ARM["KF"], "o", MS + 0.4)
    ax_f.axvline(1, color=S.INK2, lw=S.HAIR, zorder=1)
    ax_f.set_xscale("log")
    ax_f.set_xlim(0.15, 2.6)
    ax_f.xaxis.set_major_locator(ticker.FixedLocator([0.25, 0.5, 1, 2]))
    ax_f.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: ("%g" % v)))
    ax_f.xaxis.set_minor_locator(ticker.NullLocator())
    ax_f.set_yticks(ys)
    ax_f.set_yticklabels([r[0] for r in rows], fontsize=S.SMALL, linespacing=1.0)
    ax_f.set_ylim(0.2, 4.55)
    ax_f.tick_params(axis="y", length=0)
    ax_f.grid(axis="x")
    ax_f.set_xlabel("Paired ratio, KF/K0 (KFc/K0c)", fontsize=S.SMALL)
    ax_f.axhspan(0.2, 1.38, color=S.BAND, lw=0, zorder=0)
    ax_w.axhspan(0.2, 1.38, color=S.BAND, lw=0, zorder=0)
    ax_w.set_xlim(0, 11.5)
    ax_w.xaxis.set_major_locator(ticker.FixedLocator([0, 5, 10]))
    ax_w.tick_params(axis="y", length=0, labelleft=False)
    ax_w.grid(axis="x")
    ax_w.set_xlabel("Web calls per answer", fontsize=S.SMALL)
    ax_f.set_title("New tokens (filled) and time (open)", fontsize=S.TINY, loc="left", pad=2, color=S.INK)
    ax_w.set_title("K0 (light), KF (dark)", fontsize=S.TINY, loc="left", pad=2, color=S.INK)

    # legend
    arm_handles = [Patch(facecolor=S.ARM[a], edgecolor="none") for a in codex_arms]
    arm_labels = ["P, plain", "K0, {} findings".format(thousands(A2["storeFindings"]["K0"])),
                  "KF, {} findings".format(thousands(A2["storeFindings"]["KF"]))]
    measure_handles = [plt.Line2D([], [], marker=m, ms=MS + (0.6 if h else 0), ls="none",
                                  mfc=S.SURFACE if h else S.INK2, mec=S.INK2, mew=0.7 if h else 0.3)
                       for _, m, h, _ in MEASURES]
    measure_labels = [label for *_, label in MEASURES]
    fig.legend(arm_handles + measure_handles, arm_labels + measure_labels, loc="upper left",
               bbox_to_anchor=(0.32 / W, 1 - 0.02 / H), ncol=6, fontsize=S.TINY, borderaxespad=0, columnspacing=1.0,
               handletextpad=0.3)
    S.letter(fig, "a")

    # caption
    pk = {s: A2["byStratum"][s]["paired"]["KF"] for s in STRATA}
    arm = lambda s, a, k: A2["byStratum"][s]["arms"][a][k]  # noqa: E731
    triple = lambda a, k: "/".join(str(arm(s, a, k)) for s in STRATA)  # noqa: E731
    ep, codex = E8["byStratum"]["near"]["paired"]["KFc"], E8["codex"]["arms"]
    return ("4a, memory ablation (A2) and a second engine (E8). A2: test 1's 60 held-out questions (near, mid, far: 20 "
            "each), %d replicates, answered by P (plain), the researcher on K0 (%s findings) and on KF (%s) with the "
            "web on, each question's answers checked together by one Codex checker; %d answers per arm and stratum. E8: "
            "the 20 near questions answered once by the researcher on Claude Code on K0 (K0c) and KF (KFc), checked by "
            "the same Codex checker. Left: the share of answers that are complete (filled circles), give a sourced "
            "result (squares) and pass (open circles; second, as two checks of the same answers move passes by up to 2 "
            "in 20); below, contradicted statements per answer, with the count printed. Near/mid/far: complete P %s, "
            "K0 %s, KF %s; sourced result P %s, K0 %s, KF %s; contradicted P %s, K0 %s, KF %s; passes P %s, K0 %s, KF "
            "%s. Claude Code (of 20): complete K0c %d, KFc %d; sourced result %d, %d; contradicted statements %d and "
            "%d (in %d and %d answers; A2's Codex K0 and KF had %d and %d on the same questions in 60 answers each); "
            "passes %d, %d. Middle: the paired KF/K0 ratio (median over questions of each arm's replicates pooled, "
            "bootstrap 95%% interval) of new tokens (filled) and time (open): near %s, time %s; mid %s; far %s; on "
            "Claude Code KFc/K0c %s, time %s. Right: mean web calls per answer, K0 to KF: near %.1f to %.1f, mid %.1f to "
            "%.1f, far %.1f to %.1f; KF answered %d of 60 near questions without the web; on Claude Code %.1f to %.1f "
            "(KFc %d of 20 without the web). The two engines count tokens differently; only ratios within an engine are "
            "compared." % (
                A2["replicates"], thousands(A2["storeFindings"]["K0"]), thousands(A2["storeFindings"]["KF"]),
                arm("near", "KF", "answered"),
                triple("P", "complete"), triple("K0", "complete"), triple("KF", "complete"),
                triple("P", "resultGiven"), triple("K0", "resultGiven"), triple("KF", "resultGiven"),
                triple("P", "contradicted"), triple("K0", "contradicted"), triple("KF", "contradicted"),
                triple("P", "pass"), triple("K0", "pass"), triple("KF", "pass"),
                e8["K0c"]["complete"], e8["KFc"]["complete"], e8["K0c"]["resultGiven"], e8["KFc"]["resultGiven"],
                e8["K0c"]["contradicted"], e8["KFc"]["contradicted"], e8["K0c"]["answersContradicted"],
                e8["KFc"]["answersContradicted"], codex["K0"]["contradicted"], codex["KF"]["contradicted"],
                e8["K0c"]["pass"], e8["KFc"]["pass"],
                ci(pk["near"]["tokens"]), ci(pk["near"]["seconds"]), ci(pk["mid"]["tokens"]), ci(pk["far"]["tokens"]),
                ci(ep["tokens"]), ci(ep["seconds"]),
                arm("near", "K0", "meanWebCalls"), arm("near", "KF", "meanWebCalls"), arm("mid", "K0", "meanWebCalls"),
                arm("mid", "KF", "meanWebCalls"), arm("far", "K0", "meanWebCalls"), arm("far", "KF", "meanWebCalls"),
                arm("near", "KF", "noWeb"), e8["K0c"]["meanWebCalls"], e8["KFc"]["meanWebCalls"], e8["KFc"]["noWeb"]))


# ----------------------------------------------------------------------------------------------- 4c

def resampled_stores(data):
    """A3's 20 resampled stores (100, 200, 400 and 800 questions × 5 seeds), by name."""
    return {a: s for a, s in data[INPUT]["A3"]["stores"].items() if s["size"]}


def store_labels(ax, data):
    """A2's store names above the axes, at their findings."""
    findings = data[INPUT]["A2"]["storeFindings"]
    for a in STORES:
        ax.text(findings[a], 1.0, a, transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=S.TINY,
                color=S.INK2)


def c_tokens(tok, stratum, data, title=True, labels=True, slopes="lower"):
    """4c's row 1 in one stratum: new tokens against K0 (paired ratio, log) for A2's stores with their intervals, A3's
    resampled stores and same-day anchors, and the within-question slopes written in the panel's `slopes` ("lower" or
    "upper") left corner; with the stratum as the title and the stores named above when `title` and `labels`."""
    A2, A3 = data[INPUT]["A2"], data[INPUT]["A3"]
    findings = A2["storeFindings"]
    part, a3s = A2["byStratum"][stratum], A3["byStratum"][stratum]
    xs = [findings[a] for a in STORES]
    ys = [1.0] + [part["paired"][a]["tokens"]["median"] for a in STORES[1:]]
    tok.plot(xs, ys, color=S.LIGHT, lw=0.7, zorder=2)
    for a, x, y in zip(STORES, xs, ys):
        if a != "K0":
            t = part["paired"][a]["tokens"]
            tok.plot([x, x], [t["low"], t["high"]], color=S.ARM[a], lw=S.LINE, solid_capstyle="butt", zorder=3)
        dot(tok, x, y, S.ARM[a], "o", MS + 0.4, z=5)
    for name, s in resampled_stores(data).items():
        t = s["byStratum"][stratum]["tokensVsK0"]
        dot(tok, s["findings"], t["median"], S.RESAMPLED[s["size"]], "o", MS_SMALL, z=4)
    kfa = a3s["paired"]["KF"]["tokens"]
    dot(tok, A3["stores"]["KF"]["findings"], kfa["median"], S.ARM["KF"], "D", MS + 1.2, True, 6, True)
    dot(tok, A3["stores"]["K0"]["findings"], 1.0, S.ARM["K0"], "D", MS + 1.2, True, 6, True)
    tok.axhline(1, color=S.INK2, lw=S.HAIR, zorder=1)
    tok.set_yscale("log")
    tok.set_ylim(0.3, 2.4)
    tok.yaxis.set_major_locator(ticker.FixedLocator([0.5, 1, 2]))
    tok.yaxis.set_minor_locator(ticker.NullLocator())
    tok.yaxis.set_major_formatter(ticker.FuncFormatter(lambda val, _: "%g" % val))
    s2, s3 = A2["estimates"]["slope"][stratum], A3["estimates"]["slope"][stratum]
    lower = slopes == "lower"
    tok.text(0.03, 0.05 if lower else 0.95, "slope A2 %s\nslope A3 %s" % (ci(s2), ci(s3)), transform=tok.transAxes,
             ha="left", va="bottom" if lower else "top", fontsize=S.TINY, color=S.INK2, linespacing=1.05)
    if title:
        tok.set_title("%s (20 questions)" % TITLE[stratum], fontsize=S.SMALL, loc="left", pad=11, color=S.INK)
    if labels:
        store_labels(tok, data)


def c_contradicted(con, stratum, data):
    """4c's row 2 in one stratum: contradicted statements per answer, the web-off arms included."""
    A2, A3 = data[INPUT]["A2"], data[INPUT]["A3"]
    findings, part = A2["storeFindings"], A2["byStratum"][stratum]
    for a in STORES + MEMORY:
        c = part["arms"][a]
        dot(con, findings[a], c["contradicted"] / c["answered"], S.ARM[a], "s" if a in MEMORY else "o",
            MS + 0.4, z=5)
    for name, s in resampled_stores(data).items():
        c = s["byStratum"][stratum]
        dot(con, s["findings"], c["contradicted"] / c["answered"], S.RESAMPLED[s["size"]], "o", MS_SMALL, z=4)
    for a in ("K0", "KF"):
        c = A3["stores"][a]["byStratum"][stratum]
        dot(con, A3["stores"][a]["findings"], c["contradicted"] / c["answered"], S.ARM[a], "D", MS + 1.2, True, 6,
            True)
    con.set_ylim(-0.012, 0.17)
    con.yaxis.set_major_locator(ticker.FixedLocator([0, 0.05, 0.1, 0.15]))
    con.yaxis.set_major_formatter(ticker.FuncFormatter(lambda val, _: "%g" % val))


def c_shares(sh, stratum, data):
    """4c's row 3 in one stratum: the share of answers citing a saved finding (web on and off) and, with the web off,
    the share giving a sourced result and the share complete."""
    A2, A3 = data[INPUT]["A2"], data[INPUT]["A3"]
    findings, part = A2["storeFindings"], A2["byStratum"][stratum]
    xs = [findings[a] for a in STORES]
    cite = [share(part["arms"][a], "citingFindings") for a in STORES]
    sh.plot(xs, cite, color=S.LIGHT, lw=0.7, zorder=2)
    for a, x, y in zip(STORES, xs, cite):
        dot(sh, x, y, S.ARM[a], "o", MS + 0.4, z=5)
    for name, s in resampled_stores(data).items():
        dot(sh, s["findings"], share(s["byStratum"][stratum], "citingFindings"), S.RESAMPLED[s["size"]], "o",
            MS_SMALL, z=4)
    for a in ("K0", "KF"):
        dot(sh, A3["stores"][a]["findings"], share(A3["stores"][a]["byStratum"][stratum], "citingFindings"),
            S.ARM[a], "D", MS + 1.2, True, 6, True)
    mx = [findings[a] for a in MEMORY]
    sourced = [share(part["arms"][a], "resultGiven") for a in MEMORY]
    sh.plot(mx, sourced, color=S.ARM["MF"], lw=0.7, zorder=2)
    for a, x in zip(MEMORY, mx):
        c = part["arms"][a]
        dot(sh, x, share(c, "resultGiven"), S.ARM[a], "s", MS + 0.4, z=5)
        dot(sh, x, share(c, "complete"), S.ARM[a], "s", MS + 1.4, hollow=True, z=5)
        dot(sh, x, share(c, "citingFindings"), S.ARM[a], "o", MS + 0.4, z=5)
    sh.set_ylim(-0.04, 1.06)
    sh.yaxis.set_major_locator(ticker.FixedLocator([0, 0.5, 1]))
    sh.yaxis.set_major_formatter(ticker.FuncFormatter(lambda val, _: "%d%%" % round(100 * val)))


def c_findings_axis(ax, data):
    """4c's shared x: findings in the store (log), A2's stores marked by dotted lines."""
    findings = data[INPUT]["A2"]["storeFindings"]
    ax.set_xscale("log")
    ax.set_xlim(100, 13000)
    ax.xaxis.set_major_locator(ticker.FixedLocator([100, 1000, 10000]))
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda val, _: thousands(val)))
    ax.xaxis.set_minor_locator(ticker.LogLocator(subs=range(2, 10)))
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())
    for a in STORES:
        ax.axvline(findings[a], color=S.GRID, lw=S.HAIR, ls=(0, (2, 2)), zorder=0)
    ax.grid(axis="y")


def c_mark(colour, marker="o", ms=MS + 0.4, hollow=False):
    """A legend handle drawn as 4c draws its marks."""
    return plt.Line2D([], [], marker=marker, ms=ms, ls="none", mfc="none" if hollow else colour,
                      mec=colour if hollow else S.SURFACE, mew=0.7 if hollow else 0.3)


def c_legend_items():
    """4c's legend entries as (handle, label): A2's web-on stores and A3's anchors, the web-off arms and A3's stores,
    and the three marker shapes of the share row."""
    upper = [(c_mark(S.ARM[a]), a) for a in STORES] + [(c_mark(S.INK2, "D", MS + 1.2, True), "A3 same-day K0, KF")]
    lower = [(c_mark(S.ARM[a], "s"), "%s (web off)" % a) for a in MEMORY] + [
        (c_mark(S.RESAMPLED[z], ms=MS_SMALL + 0.6), "A3, %d questions" % z) for z in sorted(S.RESAMPLED)]
    shapes = [(plt.Line2D([], [], marker="o", ms=MS + 0.4, ls="none", mfc=S.INK2, mec=S.SURFACE, mew=0.3),
               "cites a saved finding"),
              (plt.Line2D([], [], marker="s", ms=MS + 0.4, ls="none", mfc=S.INK2, mec=S.SURFACE, mew=0.3),
               "sourced result (web off)"),
              (plt.Line2D([], [], marker="s", ms=MS + 1.4, ls="none", mfc=S.SURFACE, mec=S.INK2, mew=0.7),
               "complete (web off)")]
    return upper, lower, shapes


def draw_c(fig, size, data):
    W, H = size
    left, right, top, bottom, cgap, rgap = 0.62, 0.1, 0.62, 0.36, 0.24, 0.1
    cw = (W - left - right - 2 * cgap) / 3
    rh = (H - top - bottom - 2 * rgap) / 3
    grid_axes = {}
    for ci_, stratum in enumerate(STRATA):
        for ri in range(3):
            x = left + ci_ * (cw + cgap)
            y = bottom + (2 - ri) * (rh + rgap)
            share_y = grid_axes.get((0, ri))
            ax = axes(fig, size, x, y, cw, rh, sharey=share_y, sharex=grid_axes.get((ci_, 0)) if ri else None)
            grid_axes[(ci_, ri)] = ax
    for ci_, stratum in enumerate(STRATA):
        tok, con, sh = (grid_axes[(ci_, r)] for r in range(3))
        c_tokens(tok, stratum, data)
        c_contradicted(con, stratum, data)
        c_shares(sh, stratum, data)
    for (ci_, ri), ax in grid_axes.items():
        c_findings_axis(ax, data)
        if ri < 2:
            ax.tick_params(axis="x", labelbottom=False)
        if ci_:
            ax.tick_params(axis="y", labelleft=False)
    grid_axes[(0, 0)].set_ylabel("New tokens\nagainst K0", fontsize=S.SMALL, linespacing=1.0)
    grid_axes[(0, 1)].set_ylabel("Contradicted\nper answer", fontsize=S.SMALL, linespacing=1.0)
    grid_axes[(0, 2)].set_ylabel("Share of\nanswers", fontsize=S.SMALL, linespacing=1.0)
    grid_axes[(1, 2)].set_xlabel("Findings in the store (log scale)", fontsize=S.SMALL)

    # legend: two rows, A2's web-on stores and the anchors above, the web-off arms and A3's stores below
    upper, lower, shapes = c_legend_items()
    order = [item for pair in zip(upper, lower) for item in pair]
    fig.legend([h for h, _ in order], [label for _, label in order], loc="upper left",
               bbox_to_anchor=(left / W, 1 - 0.02 / H), ncol=6, fontsize=S.TINY, borderaxespad=0, columnspacing=1.1,
               handletextpad=0.25)
    grid_axes[(2, 2)].legend([h for h, _ in shapes], [label for _, label in shapes],
                             loc="center right", fontsize=S.TINY, borderaxespad=0.1, handletextpad=0.3,
                             labelspacing=0.15)
    S.letter(fig, "c")
    return caption_c(data)


def caption_c(data):
    v = data[INPUT]
    A2, A3 = v["A2"], v["A3"]
    findings = A2["storeFindings"]
    resampled = resampled_stores(data)
    sl2, sl3 = A2["estimates"]["slope"], A3["estimates"]["slope"]
    cov = A3["estimates"]["coverage"]
    arm = lambda s, a, k: A2["byStratum"][s]["arms"][a][k]  # noqa: E731
    by_size = A3["bySize"]
    near = lambda a: A2["byStratum"]["near"]["paired"][a]["tokens"]  # noqa: E731
    con_all = {a: A2["byStratum"]["all"]["arms"][a]["contradicted"] for a in STORES + MEMORY}
    con_a3 = sum(s["byStratum"]["all"]["contradicted"] for s in A3["stores"].values())
    n_a3 = sum(s["byStratum"]["all"]["answered"] for s in A3["stores"].values())
    return ("4c, scaling with the store's size, controlled (A2, three replicates) and resampled (A3, one answer per "
            "question and store). x: findings in the store (log scale); dotted lines and labels mark A2's stores K0 "
            "(%s findings; test 1's 2026-10-01 store), KF200, KF1 and KF2 (KF cut at the end of the 200-task run and of "
            "campaign waves 1 and 2: %s, %s and %s) and KF (%s). Small marks: A3's 20 resampled stores, nested random "
            "subsets of KF's questions at 100, 200, 400 and 800 questions × 5 seeds (%s–%s findings); open diamonds: "
            "A3's K0 and KF answered the same day. Row 1: new tokens against K0, the paired ratio (median over the 20 "
            "questions of each store's pooled answers over K0's; bars, A2's bootstrap 95%% intervals). Near: KF200 %s, "
            "KF1 %s, KF2 %s, KF %s; A3's KF %s; A3's 800-question stores %s–%s. The within-question slope of log new "
            "tokens on log findings is near %s (A3 %s), mid %s (A3 %s), far %s (A3 %s). In A3's near questions the "
            "store's size adds nothing once the question's own campaign parent is in the store (coverage model: "
            "parent present × %s (%s–%s), log findings %s). Row 2: contradicted statements per answer; A2's web-on "
            "stores %s of 180 answers each (K0 to KF), the web-off MF1 and MF %d and %d; A3 %d in %s answers. Row 3: "
            "the share of "
            "answers citing a saved finding (circles), web on and off, and with the web off the share giving a sourced "
            "result (filled squares) and complete (open squares; an honest \"not found\" counts as complete). Near "
            "answers citing a finding: K0 to KF %s of 60; A3, the five seeds together, %s of 100 at 100 to 800 "
            "questions, with %s of the 100 near parents present. Web off, near: sourced result MF1 %d and MF %d of 60, "
            "citing MF1 %d and MF %d; mid %d and %d; far %d and %d." % (
                thousands(findings["K0"]), thousands(findings["KF200"]), thousands(findings["KF1"]),
                thousands(findings["KF2"]), thousands(findings["KF"]),
                thousands(min(s["findings"] for s in resampled.values())),
                thousands(max(s["findings"] for s in resampled.values())),
                ci(near("KF200")), ci(near("KF1")), ci(near("KF2")), ci(near("KF")),
                ci(A3["byStratum"]["near"]["paired"]["KF"]["tokens"]),
                num(min(s["byStratum"]["near"]["tokensVsK0"]["median"] for s in resampled.values() if s["size"] == 800)),
                num(max(s["byStratum"]["near"]["tokensVsK0"]["median"] for s in resampled.values() if s["size"] == 800)),
                ci(sl2["near"], 3), ci(sl3["near"], 3), ci(sl2["mid"], 3), ci(sl3["mid"], 3), ci(sl2["far"], 3),
                ci(sl3["far"], 3), num(cov["parentInStore"]["multiplier"]), num(cov["parentInStore"]["multiplierLow"]),
                num(cov["parentInStore"]["multiplierHigh"]), ci(cov["logFindings"], 3),
                "/".join(str(con_all[a]) for a in STORES), con_all["MF1"], con_all["MF"], con_a3, thousands(n_a3),
                "/".join(str(arm("near", a, "citingFindings")) for a in STORES),
                "/".join(str(sum(by_size[str(z)]["nearCiting"])) for z in (100, 200, 400, 800)),
                "/".join(str(sum(by_size[str(z)]["nearParents"])) for z in (100, 200, 400, 800)),
                arm("near", "MF1", "resultGiven"), arm("near", "MF", "resultGiven"), arm("near", "MF1", "citingFindings"),
                arm("near", "MF", "citingFindings"), arm("mid", "MF1", "resultGiven"), arm("mid", "MF", "resultGiven"),
                arm("far", "MF1", "resultGiven"), arm("far", "MF", "resultGiven")))


# ----------------------------------------------------------------------------------------------- assembly

DRAW = {"4a": draw_a, "4c": draw_c}


def assemble(data):
    """Fig. 4a above 4c at 7 in wide; each panel keeps its own size."""
    heights = [SIZES["4a"][1], SIZES["4c"][1]]
    fig = plt.figure(figsize=(S.DOUBLE, sum(heights)))
    upper, lower = fig.subfigures(2, 1, height_ratios=heights, hspace=0)
    draw_a(upper, SIZES["4a"], data)
    draw_c(lower, SIZES["4c"], data)
    return fig


def records(data):
    """The pins' record of A2, A3 and E8's runs: folder, report time, harness and run revisions, and when they ran."""
    meta = data[INPUT]["meta"]
    return {e: {"folder": r["folder"], "reportAt": r.get("reportAt"),
                "harnessRevisions": sorted({f.get("harnessRevision") for f in r["folders"].values()
                                            if f.get("harnessRevision")}),
                "runRevisions": sorted({x for f in r["folders"].values() for x in f.get("runRevisions") or []}),
                "ran": [min((f["ranFrom"] for f in r["folders"].values() if f.get("ranFrom")), default=None),
                        max((f["ranTo"] for f in r["folders"].values() if f.get("ranTo")), default=None)]}
            for e, r in (meta.get("records") or {}).items()}


def render(base=None, out=None):
    """Draws 4a, 4c and the assembled figure from `a2a3e8/results.json` in `base` (default analysis/) into `out`
    (default analysis/figures/) and records them in the manifest; returns the manifest entry."""
    S.setup()
    data = load(base)
    pinned = S.pins(data, "fig4ac.py")
    meta = data[INPUT]["meta"]
    pinned["records"] = records(data)
    panels, captions = [], {}
    for key, draw in DRAW.items():
        fig = plt.figure(figsize=SIZES[key])
        captions[key] = draw(fig, SIZES[key], data)
        files = S.save(fig, "fig" + key, pinned, captions[key], out)
        panels.append({"panel": key, "files": files, "sources": SOURCES[key], "caption": captions[key]})
    whole = ("Figure 4a and 4c, memory and scaling on the frozen knowledge base (A2, A3, E8; code study-freeze-2, "
             "prompt %s, KF %s). " % (meta["prompt"], meta["knowledgeSnapshot"])) + " ".join(captions.values())
    files = S.save(assemble(data), "fig4ac", pinned, whole, out)
    entry = {"pins": pinned, "panels": panels, "assembled": {"files": files, "panels": list(DRAW), "sources": [INPUT]}}
    S.record("fig4ac", entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Fig. 4a and 4c from A2, A3 and E8's results.")
    parser.add_argument("--inputs", type=Path, help="read a2a3e8/results.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figures and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    for panel in entry["panels"]:
        print(panel["caption"])
    print("wrote", ", ".join(f for p in entry["panels"] for f in p["files"]), ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
