#!/usr/bin/env python3
"""Part B's performance (restart-study-plan.md, Measures "Performance", Analysis), drawn from
`restarts-final/results.json` only (written by `recursive/final_results.py` from the final evaluation's records; no
store, trace or engine). Every number drawn or written in the caption is read from that file, never typed in.

- a: knowledge alone, the growth curve P0 × S0…S5: per stratum (near, mid, far), the median paired new-token ratio of
  each snapshot's P0 arm against E0 (P0 × S0) against the findings in the store; one thin line per restart and the
  pooled estimate over the five (median over restart × question pairs) with its hierarchical bootstrap 95% interval.
- b: the same arms' mean web calls per answer.
- c: near questions on P0 × S1…S5 against E0, split by whether the question's own campaign parent has a finding in the
  store: median paired token ratio by snapshot, pooled over restarts with hierarchical intervals.
- d: the same split, mean web calls per answer.
- e: the crossing: knowledge alone (P0S5 vs E0), the prompt alone (P5S0 vs E0), the system (P5S5 vs E0), the prompt on
  the grown store (P5S5 vs P0S5) and the store under the final prompt (P5S5 vs P5S0), on all 60 and on the 20 near
  questions: pooled estimate with its hierarchical interval and the five restarts' own.
- f: quality per arm: contradicted statements, sourced results and passes of 60, one dot per arm, grouped as P0 × S0…S5,
  P<k> × S<k> (only the arms whose prompt is not P0) and P5 × S0.

Writes `fig_restarts_final` (PDF, SVG, 200 dpi PNG) to `analysis/figures/` (or `--out`) and its entry in
`figures/manifest.json`, keeping the others. Commit this script before rendering, so the revision in the pins is on
record.

Colours (`style.py`; no new colour): the restarts are replicates of one process, not categories, so each restart's
line or dot is the light neutral ink; what is pooled over the five restarts is KF's blue (`style.ARM["KF"]`), the store
the researcher answers with at its largest. In c and d the questions with their parent in the store are that blue and
those without it the muted neutral, an emphasis pair (CVD separation 25 under protanopia by the dataviz validator),
each named on the panel.

    OOPC_STUDY_ROOT=<main checkout> python -B fig_restarts_final.py [--inputs DIR] [--out DIR]
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

INPUT = "restarts-final/results.json"
NAME = "fig_restarts_final"
SIZE = (7.0, 6.35)
RESTARTS = ("R1", "R2", "R3", "R4", "R5")
STRATA = ("near", "mid", "far")
ROUNDS = 5
POOLED, REPLICATE, OTHER = S.ARM["KF"], S.LIGHT, S.MUTED
COMPARISONS = (("knowledge", "Knowledge alone", "P0·S5 vs E0"), ("prompt", "Prompt alone", "P5·S0 vs E0"),
               ("system", "System", "P5·S5 vs E0"), ("promptOnGrown", "Prompt on grown store", "P5·S5 vs P0·S5"),
               ("storeUnderP5", "Knowledge under P5", "P5·S5 vs P5·S0"))
RATIO = (0.33, 2.3)  # the token-ratio axes, log scale


def load(base=None):
    """The final evaluation's results; refused, drawing nothing, if missing, unpinned or with cross-check mismatches."""
    path = Path(base) / INPUT if base else S.common.analysis_dir(INPUT)
    if not path.exists():
        raise SystemExit("missing input %s; run recursive/final_results.py first" % INPUT)
    data = S.jread(path)
    pins = (data.get("meta") or {}).get("pins") or {}
    if set(pins.get("restarts") or {}) != set(RESTARTS) or not pins.get("tag"):
        raise SystemExit("%s carries no pins for its restarts" % INPUT)
    if (data.get("crossChecks") or {}).get("count"):
        raise SystemExit("%s reports %d cross-check mismatches" % (INPUT, data["crossChecks"]["count"]))
    return data


def pins(data, script=NAME + ".py"):
    meta = data["meta"]
    p = meta["pins"]
    return {"tag": p["tag"], "code": p["code"], "harness": p["harness"], "promptP0": p["promptP0"],
            "models": p.get("models"), "checker": p.get("checker"), "preparedAt": p["preparedAt"],
            "restarts": {r: {"snapshots": {k: (v or {}).get("sha256") if isinstance(v, dict) else v
                                           for k, v in x["snapshots"].items()},
                             "prompts": x["prompts"], "adoptedRounds": x["adoptedRounds"]}
                         for r, x in p["restarts"].items()},
            "inputAnalysisRevision": [meta.get("analysisRevision")],
            "inputs": {INPUT: {"builder": meta.get("builder"), "builtAt": meta.get("builtAt")}},
            "figureScript": "studies/macromolecules/figures/" + script, "figureRevision": S.revision()}


# ----------------------------------------------------------------------------------------------- helpers

def num(x, places=2):
    """A number with a true minus sign; a value that rounds to zero is written without one."""
    x = 0.0 if round(x, places) == 0 else x
    return ("%.*f" % (places, x)).replace("-", "−")


def signed(x, places=1):
    """A difference with its sign; zero (after rounding) without one."""
    if round(x, places) == 0:
        return num(0.0, places)
    return ("%+.*f" % (places, x)).replace("-", "−")


def span(values, places=2, f=None):
    """"lo–hi", or "lo to hi" when lo is negative."""
    f = f or (lambda v: num(v, places))
    lo, hi = min(values), max(values)
    return f(lo) if f(lo) == f(hi) else "%s%s%s" % (f(lo), " to " if f(lo)[:1] in "+\u2212" else "–", f(hi))


def axes(fig, x, y, w, h, size=SIZE, **kw):
    """Axes at (x, y), w wide and h high, in inches from the bottom left of `fig` (a figure or subfigure of `size`)."""
    W, H = size
    return fig.add_axes([x / W, y / H, w / W, h / H], **kw)


def letter(fig, text, x, y):
    fig.text(x / SIZE[0], y / SIZE[1], text, fontsize=S.LETTER, fontweight="bold", ha="left", va="top", color=S.INK)


def ratio_axis(ax, label=True):
    ax.set_yscale("log")
    ax.set_ylim(*RATIO)
    ax.yaxis.set_major_locator(ticker.FixedLocator([0.5, 0.7, 1, 1.4, 2]))
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: ("%g" % v)))
    ax.axhline(1, color=S.AXIS, lw=S.HAIR, zorder=1)
    if not label:
        ax.tick_params(labelleft=False)


def findings_axis(ax, xmax, labels=True):
    ax.set_xlim(-150, xmax)
    ax.xaxis.set_major_locator(ticker.FixedLocator([0, 2000, 4000]))
    ax.xaxis.set_minor_locator(ticker.FixedLocator([1000, 3000]))
    S.thousands(ax, "x")
    if not labels:
        ax.tick_params(labelbottom=False)


def interval(entry):
    return entry["estimate"], entry["low"], entry["high"]


# ----------------------------------------------------------------------------------------------- a, b: growth

def growth(data):
    """{stratum: {restart: (findings, token ratios, mean web calls)}} and the pooled curve with its intervals."""
    cur, e0 = data["curves"], data["arms"]["E0"]
    per, pooled = {}, {}
    for s in STRATA:
        per[s] = {r: ([p["findings"] for p in cur["growth"][r]], [p[s]["tokens"]["median"] for p in cur["growth"][r]],
                      [p[s]["counts"]["meanWebCalls"] for p in cur["growth"][r]]) for r in RESTARTS}
        xs = [m["findings"] for m in cur["growthMean"]]
        tok = [(1.0, 1.0, 1.0)] + [interval(cur["growthPooled"]["S%d" % k][s]["tokens"]) for k in range(1, ROUNDS + 1)]
        base = e0[s]["meanWebCalls"]
        web = [(base, base, base)] + [tuple(base + v for v in interval(cur["growthPooled"]["S%d" % k][s]["webCalls"]))
                                      for k in range(1, ROUNDS + 1)]
        pooled[s] = (xs, tok, web)
    return per, pooled


def draw_growth(fig, data, x0, top, w, h, gap, row_gap):
    per, pooled = growth(data)
    xmax = max(max(v[0]) for s in STRATA for v in per[s].values()) * 1.06
    rows = []
    for row, (key, ylabel) in enumerate((("tokens", "New tokens vs E0 (ratio)"), ("web", "Web calls per answer"))):
        y = top - h - row * (h + row_gap)
        out = []
        for i, s in enumerate(STRATA):
            ax = axes(fig, x0 + i * (w + gap), y, w, h)
            for r in RESTARTS:
                xs, tok, web = per[s][r]
                ax.plot(xs, tok if key == "tokens" else web, color=REPLICATE, lw=0.7, zorder=2, solid_joinstyle="round")
            xs, tok, web = pooled[s]
            series = tok if key == "tokens" else web
            ax.fill_between(xs, [v[1] for v in series], [v[2] for v in series], color=POOLED, alpha=0.13, lw=0, zorder=1)
            ax.plot(xs, [v[0] for v in series], color=POOLED, lw=1.3, zorder=3, marker="o", ms=2.6, mec=S.SURFACE,
                    mew=0.5)
            if key == "tokens":
                ratio_axis(ax, label=i == 0)
                ax.set_title(s.capitalize(), fontsize=S.SIZE, pad=2, loc="left")
            else:
                ax.set_ylim(0, 9.5)
                ax.yaxis.set_major_locator(ticker.MultipleLocator(2))
                if i:
                    ax.tick_params(labelleft=False)
            findings_axis(ax, xmax)
            ax.grid(axis="y")
            if i == 0:
                ax.set_ylabel(ylabel, fontsize=S.SMALL)
            out.append(ax)
        if row:
            fig.text((x0 + 1.5 * w + gap) / SIZE[0], (y - 0.2) / SIZE[1], "Findings in the store (P0 × S0…S5)",
                     ha="center", va="top", fontsize=S.SMALL)
        rows.append(out)
    # legend once, inside the near token panel's lower left
    handles = [plt.Line2D([], [], color=REPLICATE, lw=0.7), plt.Line2D([], [], color=POOLED, lw=1.3, marker="o", ms=2.6,
                                                                       mec=S.SURFACE, mew=0.5)]
    rows[0][2].legend(handles, ["R1–R5", "pooled, 95% interval"], loc="upper left", fontsize=S.TINY,
                      handlelength=1.4, borderaxespad=0.3, frameon=False)
    return rows


# ----------------------------------------------------------------------------------------------- c, d: parent split

def draw_parents(fig, data, x, top, w, h, row_gap):
    """c and d: both measures paired against E0 per question, as in a and e (the two groups hold different questions,
    so a group's own mean web calls would mix in E0's differences between questions)."""
    pa = data["parents"]
    ks = list(range(1, ROUNDS + 1))
    counts = [pa["perStore"]["S%d" % k]["split"]["with"]["answers"] // len(RESTARTS) for k in ks]
    out, handles = [], []
    for row, key in enumerate(("tokens", "webCalls")):
        y = top - h - row * (h + row_gap)
        ax = axes(fig, x, y, w, h)
        for flag, color, dx in (("with", POOLED, -0.1), ("without", OTHER, 0.1)):
            pts = [(k + dx, *interval(pa["perStore"]["S%d" % k]["split"][flag][key])) for k in ks
                   if pa["perStore"]["S%d" % k]["split"][flag]["answers"]]
            xs = [p[0] for p in pts]
            ax.vlines(xs, [p[2] for p in pts], [p[3] for p in pts], color=color, lw=0.8, zorder=2)
            line, = ax.plot(xs, [p[1] for p in pts], color=color, lw=0.9, marker="o", ms=3.0,
                            mfc=color if flag == "with" else S.SURFACE, mec=color, mew=0.8, zorder=3)
            if row == 0:
                handles.append(line)
        if key == "tokens":
            ax.set_yscale("log")
            ax.set_ylim(0.2, 3.4)
            ax.yaxis.set_major_locator(ticker.FixedLocator([0.25, 0.35, 0.5, 0.7, 1, 1.4, 2]))
            ax.yaxis.set_minor_locator(ticker.NullLocator())
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "%g" % v))
            ax.axhline(1, color=S.AXIS, lw=S.HAIR, zorder=1)
            ax.set_ylabel("New tokens vs E0 (ratio)", fontsize=S.SMALL)
            ax.set_title("Near questions", fontsize=S.SIZE, pad=2, loc="left")
            ax.legend(handles, ["campaign parent in the store", "parent not in the store"], loc="upper left",
                      fontsize=S.TINY, handlelength=1.6, borderaxespad=0.2)
        else:
            ax.axhline(0, color=S.AXIS, lw=S.HAIR, zorder=1)
            ax.set_ylim(-8.8, 5.2)
            ax.yaxis.set_major_locator(ticker.MultipleLocator(4))
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: num(v, 0) if v else "0"))
            ax.set_ylabel("Web calls vs E0 (difference)", fontsize=S.SMALL)
        ax.set_xlim(0.5, ROUNDS + 0.5)
        ax.set_xticks(ks)
        ax.set_xticklabels(["S%d\n%d" % (k, c) for k, c in zip(ks, counts)] if row else ["S%d" % k for k in ks],
                           linespacing=1.1)
        ax.grid(axis="y")
        if row:
            ax.set_xlabel("Snapshot · with parent", fontsize=S.SMALL)
        out.append(ax)
    return out


# ----------------------------------------------------------------------------------------------- e: crossing

def draw_crossing(fig, data, x, y, label_w, w, gap, h, size=SIZE, comparisons=COMPARISONS, colour=POOLED):
    """The crossing's token ratios and web-call differences, all 60 and near, one row pair per comparison, in a
    figure or subfigure of `size` (positions in inches); `colour` draws the pooled estimates."""
    cross = data["crossing"]
    rows = []
    for key, name, arms in comparisons:
        for which in ("all", "near"):
            rows.append((key, name, arms, which))
    n = len(rows)
    ax_t = axes(fig, x + label_w, y, w, h, size)
    ax_w = axes(fig, x + label_w + w + gap, y, w, h, size)
    for i, (key, name, arms, which) in enumerate(rows):
        yy = i + (0.12 if which == "all" else -0.12)
        c = cross[key]
        for ax, metric in ((ax_t, "tokens"), (ax_w, "webCalls")):
            est, lo, hi = interval(c["pooled"][which][metric])
            ax.hlines(yy, lo, hi, color=colour, lw=1.1, zorder=3)
            ax.plot(est, yy, "o", color=colour, ms=3.2, mec=S.SURFACE, mew=0.5, zorder=4)
            per = [c["perRestart"][which][r][metric]["median" if metric == "tokens" else "mean"] for r in RESTARTS]
            ax.plot(per, [yy] * len(per), "o", ms=2.0, mfc="none", mec=S.INK2, mew=0.5, zorder=2, alpha=0.8)
    for ax in (ax_t, ax_w):
        ax.set_ylim(n - 0.4, -0.6)
        ax.set_yticks(range(n))
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
        for k in range(2, n, 2):
            ax.axhline(k - 0.5, color=S.GRID, lw=S.HAIR, zorder=0)
        ax.grid(axis="x")
    ax_t.set_yticklabels(["all 60" if r[3] == "all" else "near 20" for r in rows], fontsize=S.TINY, color=S.INK2)
    ax_w.tick_params(labelleft=False)
    ax_t.set_xscale("log")
    ax_t.set_xlim(*RATIO)
    ax_t.xaxis.set_major_locator(ticker.FixedLocator([0.5, 1, 2]))
    ax_t.xaxis.set_minor_locator(ticker.FixedLocator([0.7, 1.4]))
    ax_t.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: "%g" % v))
    ax_t.xaxis.set_minor_formatter(ticker.NullFormatter())
    ax_t.axvline(1, color=S.AXIS, lw=S.HAIR, zorder=1)
    ax_t.set_xlabel("New tokens (ratio)", fontsize=S.SMALL)
    ax_w.axvline(0, color=S.AXIS, lw=S.HAIR, zorder=1)
    ax_w.set_xlim(-7, 4)
    ax_w.xaxis.set_major_locator(ticker.MultipleLocator(3))
    ax_w.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: num(v, 0) if v else "0"))
    ax_w.set_xlabel("Web calls (difference)", fontsize=S.SMALL)
    for i in range(0, n, 2):
        _, name, arms, _ = rows[i]
        ax_t.annotate(name, (0, i), xycoords=("axes fraction", "data"), xytext=(-label_w * 72 + 2, 0),
                      textcoords="offset points", ha="left", va="center", fontsize=S.SMALL, color=S.INK,
                      annotation_clip=False)
        ax_t.annotate(arms, (0, i + 1), xycoords=("axes fraction", "data"), xytext=(-label_w * 72 + 2, 0),
                      textcoords="offset points", ha="left", va="center", fontsize=S.TINY, color=S.INK2,
                      annotation_clip=False)
    handles = [plt.Line2D([], [], color=colour, lw=1.1, marker="o", ms=3.2, mec=S.SURFACE, mew=0.5),
               plt.Line2D([], [], ls="none", marker="o", ms=2.0, mfc="none", mec=S.INK2, mew=0.5)]
    ax_w.legend(handles, ["pooled, 95% interval", "each restart"], loc="lower right", bbox_to_anchor=(1.0, 1.0),
                ncol=2, fontsize=S.TINY, handlelength=1.2, borderaxespad=0.1, columnspacing=0.8)
    return ax_t, ax_w


# ----------------------------------------------------------------------------------------------- f: quality

def slots(data):
    """The arm slots of panel f in order: (group, label, {restart or 'E0': arm name})."""
    names = set(data["arms"])
    out = [("P0", "S0", {"E0": "E0"})]
    out += [("P0", "S%d" % k, {r: "%s-P0-S%d" % (r, k) for r in RESTARTS}) for k in range(1, ROUNDS + 1)]
    out += [("Pk", "S%d" % k, {r: "%s-P%d-S%d" % (r, k, k) for r in RESTARTS if "%s-P%d-S%d" % (r, k, k) in names})
            for k in range(1, ROUNDS + 1)]
    out += [("P5", "S0", {r: "%s-P5-S0" % r for r in RESTARTS if "%s-P5-S0" % r in names})]
    return out


def draw_quality(fig, data, x, y, w, h, gap):
    arms = data["arms"]
    groups = slots(data)
    measures = (("contradicted", "Contradicted", (-0.4, 3.6), 1), ("resultGiven", "Sourced result", (51.5, 60.6), 2),
                ("pass", "Passes", (51.5, 60.6), 2))
    offsets = {r: (i - 2) * 0.13 for i, r in enumerate(RESTARTS)}
    offsets["E0"] = 0.0
    xs = []
    position = 0.0
    for i, (group, label, members) in enumerate(groups):
        if i and group != groups[i - 1][0]:
            position += 0.6
        xs.append(position)
        position += 1.0
    out = []
    for row, (key, label, ylim, step) in enumerate(measures):
        ax = axes(fig, x, y + (len(measures) - 1 - row) * (h + gap), w, h)
        for (group, slot_label, members), px in zip(groups, xs):
            for who, name in members.items():
                value = arms[name]["all"][key]
                ax.plot(px + offsets[who], value, "o", ms=2.3 if who != "E0" else 3.0,
                        mfc=S.INK if who == "E0" else S.SURFACE, mec=S.INK2 if who != "E0" else S.INK, mew=0.6,
                        zorder=3, clip_on=False)
        ax.set_ylim(*ylim)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(step if key == "contradicted" else 4))
        ax.set_xlim(xs[0] - 0.55, xs[-1] + 0.55)
        ax.set_ylabel(label, fontsize=S.TINY, labelpad=3)
        ax.tick_params(axis="y", labelsize=S.TINY)
        ax.grid(axis="y")
        for i in range(1, len(groups)):
            if groups[i][0] != groups[i - 1][0]:
                ax.axvline((xs[i] + xs[i - 1]) / 2, color=S.GRID, lw=S.HAIR, zorder=0)
        ax.set_xticks(xs)
        if row < len(measures) - 1:
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xticklabels([("E0" if g[2].get("E0") else g[1]) for g in groups], fontsize=S.TINY)
            for group, text in (("P0", "P0"), ("Pk", "P<k>, edited"), ("P5", "P5")):
                mine = [px for (g, _, _), px in zip(groups, xs) if g == group]
                ax.annotate(text, ((min(mine) + max(mine)) / 2, 0), xycoords=("data", "axes fraction"),
                            xytext=(0, -10), textcoords="offset points", ha="center", va="top", fontsize=S.TINY,
                            color=S.INK2, annotation_clip=False)
        if row == 0:
            ax.set_title("Quality per arm, of 60 answers", fontsize=S.SIZE, pad=3, loc="left")
        ax.tick_params(axis="x", length=0)
        out.append(ax)
    return out


# ----------------------------------------------------------------------------------------------- figure, caption

def draw(data):
    S.setup()
    fig = plt.figure(figsize=SIZE)
    W, H = SIZE
    top, h, row_gap = H - 0.32, 1.2, 0.36
    draw_growth(fig, data, 0.52, top, 1.25, h, 0.12, row_gap)
    draw_parents(fig, data, 5.38, top, 1.5, h, row_gap)
    letter(fig, "a", 0.02, top + 0.26)
    letter(fig, "b", 0.02, top - h - row_gap + 0.14)
    letter(fig, "c", 4.86, top + 0.26)
    letter(fig, "d", 4.86, top - h - row_gap + 0.14)
    bottom_top = top - 2 * h - row_gap - 0.72
    eh = bottom_top - 0.5
    draw_crossing(fig, data, 0.02, 0.5, 1.28, 1.42, 0.16, eh)
    letter(fig, "e", 0.02, bottom_top + 0.2)
    fig.text(0.24 / W, (bottom_top + 0.2) / H, "The crossing", fontsize=S.SIZE, ha="left", va="top", color=S.INK)
    qh = (eh - 2 * 0.1) / 3
    draw_quality(fig, data, 4.9 + 0.45, 0.5 + 0.12, 1.53, qh - 0.04, 0.1)
    letter(fig, "f", 4.86, bottom_top + 0.2)
    return fig


def caption(data):
    cur, cross, arms, pa = data["curves"], data["crossing"], data["arms"], data["parents"]
    meta = data["meta"]
    gp = cur["growthPooled"]
    e0 = arms["E0"]
    ks = range(1, ROUNDS + 1)
    tok = lambda s: [gp["S%d" % k][s]["tokens"]["estimate"] for k in ks]  # noqa: E731
    web_s5 = {s: cur["growthMean"][ROUNDS][s]["meanWebCalls"]["mean"] for s in STRATA}  # = E0 + the pooled difference
    split = {flag: [pa["perStore"]["S%d" % k]["split"][flag] for k in ks if pa["perStore"]["S%d" % k]["split"][flag]["answers"]]
             for flag in ("with", "without")}
    with_n = [pa["perStore"]["S%d" % k]["split"]["with"]["answers"] // 5 for k in ks]
    c = lambda key, which, m: cross[key]["pooled"][which][m]  # noqa: E731

    def ci_text(v, places=2, f=num):
        return "%s (%s to %s)" % (f(v["estimate"], places), f(v["low"], places), f(v["high"], places)) \
            if f is signed or v["low"] < 0 else "%s (%s–%s)" % (f(v["estimate"], places), f(v["low"], places),
                                                               f(v["high"], places))

    def comparison(key):
        return "%s and %s on all 60, %s and %s on near" % (
            ci_text(c(key, "all", "tokens")), ci_text(c(key, "all", "webCalls"), 1, signed),
            ci_text(c(key, "near", "tokens")), ci_text(c(key, "near", "webCalls"), 1, signed))

    p0 = ["%s-P0-S%d" % (r, k) for r in RESTARTS for k in ks]
    edited = [n for n in arms if n != "E0" and "-P0-" not in n]
    q = lambda names, key: span([arms[n]["all"][key] for n in names], 0, lambda v: "%d" % v)  # noqa: E731
    verdicts = {p["id"]: p["verdict"] for p in data["predictions"]}
    return (
        "Performance of the five restarts on test 1's 60 held-out questions (20 near, 20 mid, 20 far): %d arms × 60 = "
        "%s answers, each question's arms answered in turn and checked together by one Codex checker. E0 is P0 on the "
        "empty store, shared by all restarts. (a) Knowledge alone: the median paired new-token ratio of P0 on each "
        "snapshot against E0, by stratum, against the findings in the store; thin lines R1–R5, blue the pooled estimate "
        "(median over restart × question pairs) with its hierarchical bootstrap 95%% interval (restarts, then "
        "questions). Near: %s at S1–S5 (S5 interval %s–%s); mid %s; far %s. (b) Mean web calls per answer of the same "
        "arms: near %s (E0) to %s at S5, mid %s to %s, far %s to %s. (c, d) Near questions on P0 × S1–S5 against E0, "
        "split by whether the question's own campaign parent (asked 4 per round, so %s of 20 at S1–S5) has a finding in "
        "the store, pooled over restarts with hierarchical 95%% intervals: token ratio %s with it and %s without; "
        "web-call difference %s with it and %s without. (e) The "
        "crossing, pooled (blue, hierarchical 95%% interval) and per restart (open circles), token ratio and web-call "
        "difference: knowledge alone (P0·S5 vs E0) %s; prompt alone (P5·S0 vs E0) %s; system (P5·S5 vs E0) %s; prompt "
        "on the grown store (P5·S5 vs P0·S5) %s; knowledge under the final prompt (P5·S5 vs P5·S0) %s. (f) Quality per arm "
        "(of 60 answers; one dot per restart, E0 filled), grouped as P0 × S0–S5, the arms carrying adopted edits "
        "(P<k> × S<k> where P<k> is not P0) and P5 × S0: contradicted statements E0 %d, P0 arms %s, arms carrying "
        "adopted edits %s (%d in all %s answers); sourced result E0 %d, P0 arms %s, edited arms on S1–S5 %s, P5 × S0 "
        "%s; passes E0 %d, P0 arms %s, edited arms %s; complete answers %s in every arm (not drawn). Predictions "
        "(analyst's rules set before the numbers): 2 %s, 3 %s, 4 (held-out half) %s, 5 %s." % (
            len(arms), "{:,}".format(meta["answers"]),
            ", ".join(num(v) for v in tok("near")), num(gp["S5"]["near"]["tokens"]["low"]),
            num(gp["S5"]["near"]["tokens"]["high"]), span(tok("mid")), span(tok("far")),
            num(e0["near"]["meanWebCalls"], 1), num(web_s5["near"], 1), num(e0["mid"]["meanWebCalls"], 1),
            num(web_s5["mid"], 1), num(e0["far"]["meanWebCalls"], 1), num(web_s5["far"], 1),
            ", ".join(map(str, with_n)),
            span([x["tokens"]["estimate"] for x in split["with"]]), span([x["tokens"]["estimate"] for x in split["without"]]),
            span([x["webCalls"]["estimate"] for x in split["with"]], 1, lambda v: signed(v, 1)),
            span([x["webCalls"]["estimate"] for x in split["without"]], 1, lambda v: signed(v, 1)),
            comparison("knowledge"), comparison("prompt"), comparison("system"), comparison("promptOnGrown"),
            comparison("storeUnderP5"),
            e0["all"]["contradicted"], q(p0, "contradicted"), q(edited, "contradicted"), data["contradicted"]["total"],
            "{:,}".format(meta["answers"]), e0["all"]["resultGiven"], q(p0, "resultGiven"),
            q([n for n in edited if not n.endswith("-S0")], "resultGiven"),
            ", ".join(str(arms["%s-P5-S0" % r]["all"]["resultGiven"]) for r in RESTARTS), e0["all"]["pass"],
            q(p0, "pass"), q(edited, "pass"), q(list(arms), "complete"), verdicts.get("2"), verdicts.get("3"),
            verdicts.get("4-heldout"), verdicts.get("5")))


def render(base=None, out=None):
    """Draws the figure from the final evaluation's results in `base` (default analysis/) into `out` (default
    analysis/figures/) and records it in the manifest; returns the manifest entry."""
    data = load(base)
    pinned = pins(data)
    text = caption(data)
    files = S.save(draw(data), NAME, pinned, text, out)
    entry = {"pins": pinned, "panels": [{"panel": "restarts-final", "files": files, "sources": [INPUT], "caption": text}],
             "assembled": {"files": files, "panels": ["a", "b", "c", "d", "e", "f"], "sources": [INPUT]}}
    S.record(NAME, entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="The restarts' performance figure from recursive/final_results.py.")
    parser.add_argument("--inputs", type=Path, help="read restarts-final/results.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figure and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    print(entry["panels"][0]["caption"])
    print("wrote", ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
