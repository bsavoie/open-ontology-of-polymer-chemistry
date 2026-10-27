#!/usr/bin/env python3
"""Figure 4b, the similarity ladder: what the store saves as a question moves away from the questions behind its
findings. Drawn from `a4/results.json` only (written by `part_a/a4_results.py` from the records of experiments A4 and
A2; no store, trace or engine). Every number drawn or written in the caption is read from that file, never typed in.

One estimand on one axis: KF against K0, the researcher answering the same question on each store, both answers
checked together on the same day, paired per question with replicates pooled. Left, A4's 30 campaign first asks asked
again exactly, in other words and as a sibling (two replicates); right, A2's held-out near, mid and far strata (20
questions each, three replicates; its K0 and KF arms only). Per rung:

- new tokens: the median paired KF/K0 ratio (filled circle) with its bootstrap 95% interval over questions, over each
  question's own pooled ratio (light points);
- web calls: KF's mean over K0's (open square; a ratio of means, since KF often makes none) with its interval from
  the same resampling.

The campaign revisits against their own first asks (`fig4_records.py`'s panel, files `fig4b.*`) are another estimand:
each revisit against a first ask answered under an earlier prompt on the store of its day, with web calls as a median of
pair ratios. They stay in the records panel and are named in the caption only, never drawn on this axis.

Writes `fig4b_ladder` (PDF, SVG, PNG; `fig4b.*` are the records panel's) to `analysis/figures/` (or `--out`) and the
`fig4b` entry of `figures/manifest.json`. Commit this script before rendering, so the revision in the pins is on record.

Greys only: the arms' fixed colours (`style.ARM`) mean stores in Fig. 4, and both series here are ratios of KF to K0,
so the two series are told apart by marker shape and fill, with a legend and the values written beside them.

    OOPC_STUDY_ROOT=<main checkout> python -B fig4b.py [--inputs DIR] [--out DIR]
"""
import argparse, math, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

INPUT = "a4/results.json"
NAME, KEY = "fig4b_ladder", "fig4b"
SIZE = (3.5, 2.55)
RUNGS = [("A4", "byRung", "exact", "Exact"), ("A4", "byRung", "paraphrase", "Paraphrase"),
         ("A4", "byRung", "sibling", "Sibling"), ("A2", "byStratum", "near", "Near"),
         ("A2", "byStratum", "mid", "Mid"), ("A2", "byStratum", "far", "Far")]
X = [0, 1, 2, 3.5, 4.5, 5.5]
GROUPS = {"A4": "Campaign questions asked again (A4)", "A2": "Held-out questions (A2)"}
TOKENS_DX, WEB_DX, SPREAD = -0.14, 0.17, 0.11  # offsets in category units
YLIM = (0.04, 4.0)


def load(base=None):
    return S.inputs([INPUT], base)


def rungs(data):
    """Per rung: (experiment, label, questions, replicates, paired estimates, KF's no-web answers, KF's answers),
    checked: each token median recomputed from the per-question ratios must agree with the file's."""
    value = data[INPUT]
    out = []
    for kind, key, group, label in RUNGS:
        part = value[kind][key][group]
        p = part["paired"]
        again = math.exp(statistics.median(math.log(r) for r in p["questionTokenRatios"]))
        if abs(again - p["tokens"]["median"]) > 0.002 or len(p["questionTokenRatios"]) != p["tokens"]["n"]:
            raise SystemExit("%s: the %s question ratios do not give the file's median" % (INPUT, group))
        out.append({"kind": kind, "group": group, "label": label, "questions": part["questions"],
                    "replicates": part["answers"] // (2 * part["questions"]), "p": p,
                    "noWeb": part["arms"]["KF"]["noWeb"], "answers": part["arms"]["KF"]["answered"]})
    return out


def jitter(n):
    return [((k * 0.618034) % 1 - 0.5) * 2 * SPREAD for k in range(n)]


def label(ax, x, y, text, above):
    """A value above its interval (tokens) or beside its marker (web calls, whose interval can reach the axis)."""
    ax.annotate(text, (x, y), xytext=(0, 2.5) if above else (3.5, 0), textcoords="offset points",
                ha="center" if above else "left", va="bottom" if above else "center", fontsize=S.TINY, color=S.INK,
                zorder=6, bbox=dict(boxstyle="square,pad=0.08", fc=S.SURFACE, ec="none"))


def draw(fig, size, data):
    found = rungs(data)
    gs = S.grid(fig, size, 1, 1, left=0.44, right=0.06, top=0.36, bottom=0.52)
    ax = fig.add_subplot(gs[0])
    ax.set_yscale("log")
    ax.set_ylim(*YLIM)
    ax.set_xlim(X[0] - 0.5, X[-1] + 0.75)
    ax.axhline(1, color=S.AXIS, lw=S.LINE * 0.8, zorder=1)
    ax.axvline((X[2] + X[3]) / 2, color=S.GRID, lw=S.HAIR, zorder=1)
    over = 0
    for x, r in zip(X, found):
        p = r["p"]
        points = p["questionTokenRatios"]
        inside = [min(max(v, YLIM[0]), YLIM[1]) for v in points]
        over += sum(v != w for v, w in zip(points, inside))
        ax.plot([x + TOKENS_DX + d for d in jitter(len(points))], inside, ls="none", marker="o", ms=1.7,
                mfc=S.LIGHT, mec="none", zorder=2)
        t = p["tokens"]
        ax.plot([x + TOKENS_DX] * 2, [t["low"], t["high"]], color=S.INK, lw=1.1, solid_capstyle="butt", zorder=3)
        ax.plot(x + TOKENS_DX, t["median"], marker="o", ms=4.2, mfc=S.INK, mec=S.SURFACE, mew=0.6, zorder=4)
        label(ax, x + TOKENS_DX, t["high"], "%.2f" % t["median"], True)
        w = p["webRatioInterval"]
        ax.plot([x + WEB_DX] * 2, [w["low"], w["high"]], color=S.INK2, lw=1.1, solid_capstyle="butt", zorder=3)
        ax.plot(x + WEB_DX, p["webRatio"], marker="s", ms=3.6, mfc=S.SURFACE, mec=S.INK2, mew=1.0, zorder=4)
        label(ax, x + WEB_DX, p["webRatio"], "%.2f" % p["webRatio"], False)
    ax.set_xticks(X)
    ax.set_xticklabels([r["label"] for r in found], fontsize=S.SMALL)
    ax.tick_params(axis="x", length=0, pad=2)
    ax.yaxis.set_major_locator(ticker.FixedLocator([0.05, 0.1, 0.2, 0.5, 1, 2]))
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "{:g}".format(v)))
    ax.grid(axis="y", which="major")
    ax.set_ylabel("KF / K0, paired (log scale)", fontsize=S.SMALL)
    ax.set_xlabel("Similarity to the questions behind the store's findings, high to low", fontsize=S.TINY, labelpad=3)
    for kind in GROUPS:
        xs = [x for x, r in zip(X, found) if r["kind"] == kind]
        first = next(r for r in found if r["kind"] == kind)
        ax.text(statistics.mean(xs), 1.015, "%s\n%d questions × %d replicates per rung" % (
            GROUPS[kind], first["questions"], first["replicates"]), transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=S.TINY, color=S.INK2, linespacing=1.15)
    handles = [Line2D([], [], ls="none", marker="o", ms=4.2, mfc=S.INK, mec=S.SURFACE, mew=0.6),
               Line2D([], [], ls="none", marker="s", ms=3.6, mfc=S.SURFACE, mec=S.INK2, mew=1.0),
               Line2D([], [], ls="none", marker="o", ms=1.7, mfc=S.LIGHT, mec="none")]
    fig.legend(handles, ["New tokens, median ratio", "Web calls, ratio of means", "One question's tokens"],
               loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3,
               fontsize=S.TINY, handlelength=0.9, handletextpad=0.35, columnspacing=0.9, borderaxespad=0.1)
    S.letter(fig, "b")
    return caption(found, data[INPUT], over)


def caption(found, value, over):
    a4 = [r for r in found if r["kind"] == "A4"]
    a2 = [r for r in found if r["kind"] == "A2"]

    def series(rows):
        return "; ".join("%s %.2f (%.2f-%.2f) and %.2f (%.2f-%.2f)" % (
            r["group"], r["p"]["tokens"]["median"], r["p"]["tokens"]["low"], r["p"]["tokens"]["high"],
            r["p"]["webRatio"], r["p"]["webRatioInterval"]["low"], r["p"]["webRatioInterval"]["high"]) for r in rows)
    c = value["campaign"]["byRung"]
    return ("4b: cost against similarity to past work, KF (8,899 findings) against K0 (150), the researcher answering "
            "the same question on each and both answers checked together the same day; paired per question, "
            "replicates pooled; log scale, line at 1. Left (A4): %d campaign first asks with findings in KF, asked "
            "again exactly, in other words and as a sibling, %d replicates. Right (A2): the held-out near, mid and far "
            "strata, %d questions each, %d replicates (its K0 and KF arms). Filled circles: median paired ratio of new "
            "tokens with a bootstrap 95%% interval over questions (light points: each question's ratio); open "
            "squares: KF's mean web calls over K0's, with the same resampling. Tokens and web calls: %s; %s. KF "
            "answered without the web in %s answers. %sThe campaign revisits against their own first asks (records "
            "panel, fig4b: tokens %s, web %s as medians of pair ratios) compare a revisit with a first ask under an "
            "earlier prompt on the store of its day, another estimand, and are not drawn here." % (
                a4[0]["questions"], a4[0]["replicates"], a2[0]["questions"], a2[0]["replicates"], series(a4),
                series(a2), ", ".join("%d of %d" % (r["noWeb"], r["answers"]) for r in found),
                ("%d question ratios outside the axis are drawn at its edge. " % over) if over else "",
                ", ".join("%.2f" % c[r["group"]]["medianTokenRatio"] for r in a4),
                ", ".join("%.2f" % c[r["group"]]["medianWebRatio"] for r in a4)))


def records(data):
    """The pins' record of A4's and A2's run folders and harness revisions, and the campaign revisits' source."""
    meta = data[INPUT]
    out = {kind: {"folders": sorted(meta[kind]["records"]["folders"]),
                  "harnessRevisions": meta[kind]["records"]["harnessRevisions"]} for kind in ("A4", "A2")}
    out["campaign"] = meta["campaign"]["source"]
    return out


def render(base=None, out=None):
    """Draws Fig. 4b from `a4/results.json` in `base` (default analysis/) into `out` (default analysis/figures/) and
    records it in the manifest; returns the manifest entry."""
    S.setup()
    data = load(base)
    pinned = S.pins(data, "fig4b.py")
    pinned["records"] = records(data)
    fig = plt.figure(figsize=SIZE)
    text = draw(fig, SIZE, data)
    files = S.save(fig, NAME, pinned, text, out)
    entry = {"pins": pinned, "panels": [{"panel": "4b", "files": files, "sources": [INPUT], "caption": text}],
             "note": "Fig. 4b drawn from Part A (A4 and A2, KF against K0); the files fig4b.* are the records panel "
                     "of the campaign revisits (fig4_records)."}
    S.record(KEY, entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Fig. 4b, the similarity ladder, from a4/results.json.")
    parser.add_argument("--inputs", type=Path, help="read a4/results.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figure and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    print(entry["panels"][0]["caption"])
    print("wrote", ", ".join(entry["panels"][0]["files"]))


if __name__ == "__main__":
    main()
