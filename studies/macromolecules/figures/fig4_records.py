#!/usr/bin/env python3
"""The records panels of Figure 4 (4b's campaign part, 4d, 4e), drawn from experiment A1's outputs on KF only (no
store, no trace, no engine). Fig. 4a and 4c, and 4b's held-out rungs (near, mid, far), come from Part A's runs and are
drawn later; the assembled file here is the records part alone. Every number drawn or written in a caption is read from
these files, never typed in:

- 4b similarity: `loop-kf/revisits.json` (one row per campaign revisit with its first ask's tokens and web calls). Per
  rung (exact, paraphrase, sibling), each pair's ratio of new tokens and of web calls, and their medians with bootstrap
  95% intervals over pairs (2,000 draws, seed 7, as `ablation/analyze.py`); the medians must equal the file's summary.
- 4d reuse: `loop-kf/reuse.json` (share of findings returned to at least k later sessions and cited by at least k later
  answers; the dose response of the 655 campaign first asks, with Wilson 95% intervals from its counts).
- 4e scaffold trajectory: `loop-kf/trajectory.json` (per stage: the 200-task run and campaign waves 1-3).

Writes `fig4b`, `fig4d`, `fig4e` and `fig4_records` (PDF, SVG, PNG) to `analysis/figures/` (or `--out`) and the
`fig4_records` entry of `figures/manifest.json`. Commit this script before rendering, so the revision in the pins is on
record.

    OOPC_STUDY_ROOT=<main checkout> python -B fig4_records.py [--inputs DIR] [--out DIR]
"""
import argparse, math, random, statistics, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

JSON = ["loop-kf/revisits.json", "loop-kf/reuse.json", "loop-kf/trajectory.json"]
SOURCES = {"4b": ["loop-kf/revisits.json"], "4d": ["loop-kf/reuse.json"], "4e": ["loop-kf/trajectory.json"]}
SIZES = {"4b": (3.2, 2.15), "4d": (3.8, 2.15), "4e": (7.0, 1.8)}
RUNGS = ["exact", "paraphrase", "sibling"]
STAGES = ["run200", "wave1", "wave2", "wave3"]
STAGE_SHORT = {"run200": "200-task", "wave1": "Wave 1", "wave2": "Wave 2", "wave3": "Wave 3"}
DRAWS, SEED, CAP = 2000, 7, 2.0  # bootstrap as ablation/analyze.py; ratios above CAP are drawn at the edge


def load(base=None):
    return S.inputs(JSON, base)


def n(v):
    return "{:,}".format(v)


def median_ci(values):
    """Median with a bootstrap 95% interval over the values (resampled with replacement)."""
    rng = random.Random(SEED)
    draws = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(DRAWS))
    return statistics.median(values), draws[int(0.025 * DRAWS)], draws[int(0.975 * DRAWS)]


def wilson(k, total, z=1.959964):
    p = k / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return centre - half, centre + half


# ----------------------------------------------------------------------------------------------- 4b

def ratios(data):
    """{rung: {"tokens": [...], "web": [...]}} of the campaign revisit pairs, checked against the file's summary."""
    r = data["loop-kf/revisits.json"]
    out = {}
    for rung in RUNGS:
        pairs = [p for p in r["pairs"] if p["run"] == "campaign" and p["type"] == rung]
        out[rung] = {"tokens": [p["tokenRatio"] for p in pairs],
                     "web": [p["webRatio"] for p in pairs if p["webRatio"] is not None]}
        summary = r["summary"]["campaignByType"][rung]
        for key, field in (("tokens", "medianTokenRatio"), ("web", "medianWebRatio")):
            if round(statistics.median(out[rung][key]), 3) != summary[field]:
                raise SystemExit("revisits.json: the %s pairs' %s median is not the summary's" % (rung, key))
        if len(pairs) != summary["pairs"]:
            raise SystemExit("revisits.json: %s has %d pairs, the summary %d" % (rung, len(pairs), summary["pairs"]))
    return out


def draw_b(fig, size, data):
    values = ratios(data)
    labels = ["%s (%d)" % (rung.capitalize(), len(values[rung]["tokens"])) for rung in RUNGS]
    left = S.text_width(fig, labels, S.SMALL) + 0.08
    gs = S.grid(fig, size, 1, 2, left=left, right=0.1, top=0.36, bottom=0.36, wspace=0.12)
    stats = {}
    for j, (key, title) in enumerate((("tokens", "New tokens"), ("web", "Web calls"))):
        ax = fig.add_subplot(gs[j])
        ax.axvline(1, color=S.AXIS, lw=S.LINE * 0.8, zorder=1)
        for i, rung in enumerate(RUNGS):
            v = values[rung][key]
            jitter = [((k * 0.618034) % 1 - 0.5) * 0.42 for k in range(len(v))]
            inside = [(min(x, CAP), i + d) for x, d in zip(sorted(v), jitter)]
            ax.plot([x for x, _ in inside if x < CAP], [y for x, y in inside if x < CAP], ls="none", marker="o",
                    ms=2.2, mfc=S.LIGHT, mec="none", zorder=2)
            over = [y for x, y in inside if x >= CAP]
            if over:
                ax.plot([CAP * 0.985] * len(over), over, ls="none", marker=">", ms=2.6, mfc=S.MUTED, mec="none",
                        zorder=2)
            m, lo, hi = median_ci(v)
            stats[(rung, key)] = (m, lo, hi, len(v), sum(x == 0 for x in v), len(over))
            ax.plot([lo, hi], [i, i], color=S.INK, lw=1.2, zorder=3, solid_capstyle="butt")
            ax.plot(m, i, marker="o", ms=4, mfc=S.INK, mec=S.SURFACE, mew=0.6, zorder=4)
            ax.annotate("%.2f" % m, (m, i), xytext=(0, 4.5), textcoords="offset points", ha="center", va="bottom",
                        fontsize=S.TINY, color=S.INK, zorder=5,
                        bbox=dict(boxstyle="square,pad=0.1", fc=S.SURFACE, ec="none"))
        ax.set_xlim(0, CAP)
        ax.set_ylim(len(RUNGS) - 0.5, -0.5)
        ax.set_xticks([0, 0.5, 1, 1.5, 2])
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: "{:g}".format(x)))
        ax.grid(axis="x")
        ax.set_yticks(range(len(RUNGS)))
        ax.set_yticklabels(labels if j == 0 else [])
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
        ax.set_title(title, fontsize=S.SMALL)
        ax.set_xlabel("Revisit / first ask", fontsize=S.TINY, labelpad=1)
    fig.text(left / size[0], 1 - 0.05 / size[1], "Campaign revisits. Points: pairs; dot and bar: median, 95% CI",
             ha="left", va="top", fontsize=S.TINY, color=S.INK2)
    S.letter(fig, "b")
    parts = []
    for rung in RUNGS:
        t, w = stats[(rung, "tokens")], stats[(rung, "web")]
        parts.append("%s %.2f (%.2f-%.2f) and %.2f (%.2f-%.2f), %d pairs (%d with a web ratio, %d of them revisits "
                     "without the web)" % (rung, t[0], t[1], t[2], w[0], w[1], w[2], t[3], w[3], w[4]))
    clipped = sum(stats[k][5] for k in stats)
    return ("4b, records part: campaign revisits against their first asks, each pair's ratio of new tokens and of web "
            "calls with the median and a bootstrap 95%% interval over pairs; median token and web ratios: %s. %d "
            "ratios above %g are drawn at the edge; a pair whose first ask made no web call has no web ratio. The "
            "held-out rungs (near, mid, far) come from Part A." % ("; ".join(parts), clipped, CAP))


# ----------------------------------------------------------------------------------------------- 4d

def draw_d(fig, size, data, ratios=(1.1, 1.0), wspace=0.42):
    """The reuse curves (left) and the dose response (right), their widths in `ratios`."""
    r = data["loop-kf/reuse.json"]
    gs = S.grid(fig, size, 1, 2, left=0.56, right=0.08, top=0.3, bottom=0.42, width_ratios=list(ratios),
                wspace=wspace)
    ax = fig.add_subplot(gs[0])
    curves = (("ccdfReturnedSessions", "Returned (sessions)", S.INK, "o"),
              ("ccdfCitedAnswers", "Cited (answers)", S.MUTED, "^"))
    for key, name, colour, marker in curves:
        pts = [p for p in r[key]["points"] if p["k"] >= 1 and p["findings"] > 0]
        ax.plot([p["k"] for p in pts], [p["share"] for p in pts], color=colour, lw=S.LINE, marker=marker, ms=2.2,
                mec="none", label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("k, later sessions or answers", fontsize=S.TINY, labelpad=1)
    ax.set_ylabel("Share of findings with at least k", fontsize=S.TINY)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "{:g}".format(v)))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "{:g}".format(v)))
    ax.grid(which="major")
    ax.legend(loc="lower left", fontsize=S.TINY, handlelength=1.4, borderaxespad=0.1)
    ax.set_title("Reuse of the %s findings" % n(r["totals"]["findings"]), fontsize=S.TINY)
    bx = fig.add_subplot(gs[1])
    dose = r["doseResponse"]["primary"]["bins"]
    x = np.arange(len(dose))
    shares = [b["citingFinding"] / b["firstAsks"] for b in dose]
    bounds = [wilson(b["citingFinding"], b["firstAsks"]) for b in dose]
    bx.bar(x, [100 * s for s in shares], width=0.62, color=S.INK2, lw=0, zorder=2)
    bx.errorbar(x, [100 * s for s in shares], yerr=[[100 * (s - lo) for s, (lo, _) in zip(shares, bounds)],
                                                    [100 * (hi - s) for s, (_, hi) in zip(shares, bounds)]],
                fmt="none", ecolor=S.INK, elinewidth=0.7, capsize=1.5, capthick=0.7, zorder=3)
    for i, (s, (_, hi)) in enumerate(zip(shares, bounds)):
        bx.annotate("%.0f%%" % (100 * s), (i, 100 * hi), xytext=(0, 1.5), textcoords="offset points", ha="center",
                    va="bottom", fontsize=S.TINY, color=S.INK)
    bx.set_xticks(x)
    bx.set_xticklabels(["%s\nn=%d" % (b["bin"].replace("-", "–"), b["firstAsks"]) for b in dose], fontsize=S.TINY)
    bx.tick_params(axis="x", length=0)
    bx.set_ylim(0, 100 * max(hi for _, hi in bounds) * 1.18)
    bx.yaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))
    bx.yaxis.set_major_locator(ticker.MultipleLocator(20))
    bx.grid(axis="y")
    bx.set_xlabel("Earlier questions on the polymer", fontsize=S.TINY, labelpad=1)
    bx.set_title("First asks citing a finding", fontsize=S.TINY)
    S.letter(fig, "d")
    t = r["totals"]
    total = sum(b["firstAsks"] for b in dose)
    return ("4d: reuse of the %s findings in KF: the share returned by at least k later sessions' searches and cited by "
            "at least k later answers (log-log); %s%% were returned at least once and %s%% cited (%s citations), "
            "median %d answers from deposit to first citation. Right: of the %d campaign first asks, the share citing "
            "a finding by the number of earlier campaign questions on the polymer (Wilson 95%% intervals): %s." % (
                n(t["findings"]), S.pct(t["everReturnedShare"]), S.pct(t["everCitedShare"]),
                n(t["citationsOfFindings"]), r["firstCitationLag"]["answers"]["median"], total,
                ", ".join("%s %.0f%% (%d of %d)" % (b["bin"], 100 * b["citingFinding"] / b["firstAsks"],
                                                   b["citingFinding"], b["firstAsks"]) for b in dose)))


# ----------------------------------------------------------------------------------------------- 4e

MEASURES = [("Findings flagged by the researcher", lambda s: 100 * s["flagged"]["researcherFlaggedShare"], "%"),
            ("Empty excerpts as saved", lambda s: 100 * s["excerpts"]["emptyShare"], "%"),
            ("Review tokens per research token", lambda s: s["reviewPerResearchToken"], ""),
            ("Answers without the web", lambda s: 100 * s["answersWithoutWeb"] / s["answers"], "%")]


def value_text(v, unit):
    if unit == "%":
        return "0" if v == 0 else ("%.2f" % v if v < 1 else "%.1f" % v)
    return "%.2f" % v


def draw_e(fig, size, data, rows=1, margins=None, footer=True):
    """The four measures side by side (`rows` 1) or in a grid of `rows` rows, the stage labels under the bottom row
    only; `margins` overrides the grid's margins and spacing (inches, as `style.grid`)."""
    t = data["loop-kf/trajectory.json"]["stages"]
    stages = [s for s in STAGES if s in t]
    prompts = [next(iter(t[s]["promptVersions"])) for s in stages]
    models = [next(iter(t[s]["models"])) for s in stages]
    cols = -(-len(MEASURES) // rows)
    layout = {"left": 0.32, "right": 0.1, "top": 0.36, "bottom": 0.42, "wspace": 0.42, **(margins or {})}
    gs = S.grid(fig, size, rows, cols, **layout)
    x = np.arange(len(stages))
    changes = [i for i in range(1, len(stages)) if models[i] != models[i - 1]]
    for j, (title, value, unit) in enumerate(MEASURES):
        ax = fig.add_subplot(gs[j] if rows == 1 else gs[j // cols, j % cols])
        v = [value(t[s]) for s in stages]
        for c in changes:
            ax.axvline(c - 0.5, color=S.MUTED, lw=S.HAIR, ls=(0, (3, 2)), zorder=1)
            if j == 0:
                ax.text(c - 0.45, 1.0, "model\nchange", transform=ax.get_xaxis_transform(), ha="left", va="top",
                        fontsize=S.TINY, color=S.INK2)
        ax.plot(x, v, color=S.INK2, lw=S.LINE, marker="o", ms=3.4, mfc=S.INK2, mec=S.SURFACE, mew=0.6, zorder=3)
        top = max(v) * 1.3 or 1
        for i, y in enumerate(v):
            before, after = (v[i - 1] if i else None), (v[i + 1] if i + 1 < len(v) else None)
            near = [w for w in (before, after) if w is not None]
            if y > 0 and all(y < w for w in near):  # a dip: under its point, off the lines
                if y > 0.15 * top:
                    offset, ha, va = (0, -3.5), "center", "top"
                elif y > 0.08 * top:  # little room below: under and left, beneath the line coming down
                    offset, ha, va = (-2.5, -1.5), "right", "top"
                else:  # at the foot: above and right, over the line going up
                    offset, ha, va = (2, 4.5), "left", "bottom"
            elif after is not None and after > y and (before is None or before < y):  # rising: above and left
                offset, ha, va = (-2, 2.5), "right", "bottom"
            elif before is not None and before > y and (after is None or after < y):  # falling: above and right
                offset, ha, va = (2, 2.5), "left", "bottom"
            else:
                offset, ha, va = (0, 3), "center", "bottom"
            ax.annotate(value_text(y, unit), (i, y), xytext=offset, textcoords="offset points", ha=ha, va=va,
                        fontsize=S.TINY, color=S.INK, zorder=4,
                        bbox=dict(boxstyle="square,pad=0.1", fc=S.SURFACE, ec="none"))
        ax.set_ylim(0, top)
        ax.set_xlim(-0.4, len(stages) - 0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(["%s\n%s" % (STAGE_SHORT[s].replace("Wave ", "W"), p[:6]) for s, p in zip(stages, prompts)],
                           fontsize=S.TINY)
        ax.tick_params(axis="x", length=0)
        if j // cols < rows - 1:
            ax.tick_params(axis="x", labelbottom=False)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(3))
        if unit == "%":
            ax.yaxis.set_major_formatter(ticker.PercentFormatter(decimals=0))
        ax.grid(axis="y")
        ax.set_title(title, fontsize=S.TINY)
    if footer:
        fig.text(layout["left"] / size[0], 0.02, "Stage and its researcher prompt (first 6 hex digits)", ha="left",
                 va="bottom", fontsize=S.TINY, color=S.INK2)
    S.letter(fig, "e")
    rows = []
    for title, value, unit in MEASURES:
        rows.append("%s %s" % (title.lower(), " → ".join(value_text(value(t[s]), unit) + unit for s in stages)))
    return ("4e: the scaffold across the 200-task run and campaign waves 1-3 (prompts %s; model %s), the shares of the "
            "stage's findings or answers and its review tokens per research token: %s (%s answers). Each measure is on its own axis, because two of them start "
            "at zero." % (", ".join(prompts), " then ".join(dict.fromkeys(models)), "; ".join(rows),
                          " → ".join("%d of %d" % (t[s]["answersWithoutWeb"], t[s]["answers"]) for s in stages)))


DRAW = {"4b": draw_b, "4d": draw_d, "4e": draw_e}


def assemble(data):
    """The records part of Fig. 4 at 7 in wide: b beside d, then e."""
    h1, h2 = SIZES["4b"][1], SIZES["4e"][1]
    fig = plt.figure(figsize=(S.DOUBLE, h1 + h2))
    top, bottom = fig.subfigures(2, 1, height_ratios=[h1, h2], hspace=0)
    b, d = top.subfigures(1, 2, width_ratios=[SIZES["4b"][0], SIZES["4d"][0]], wspace=0)
    for key, sub in (("4b", b), ("4d", d), ("4e", bottom)):
        DRAW[key](sub, SIZES[key], data)
    return fig


def render(base=None, out=None):
    """Draws every panel and the assembled records part from the A1 outputs in `base` (default analysis/) into `out`
    (default analysis/figures/) and records them in the manifest; returns the manifest entry."""
    S.setup()
    data = load(base)
    pinned = S.pins(data, "fig4_records.py")
    panels, captions = [], {}
    for key, draw in DRAW.items():
        fig = plt.figure(figsize=SIZES[key])
        captions[key] = draw(fig, SIZES[key], data)
        files = S.save(fig, "fig" + key, pinned, captions[key], out)
        panels.append({"panel": key, "files": files, "sources": SOURCES[key], "caption": captions[key]})
    whole = ("Figure 4, records part (4a, 4c and the held-out rungs of 4b come from Part A). "
             + " ".join(captions.values()))
    files = S.save(assemble(data), "fig4_records", pinned, whole, out)
    entry = {"pins": pinned, "panels": panels, "assembled": {"files": files, "panels": list(DRAW), "sources": JSON}}
    S.record("fig4_records", entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Fig. 4's records panels from A1's outputs on KF.")
    parser.add_argument("--inputs", type=Path, help="read the A1 outputs here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figures and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    for panel in entry["panels"]:
        print(panel["caption"])
    print("wrote", ", ".join(f for p in entry["panels"] for f in p["files"]), ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
