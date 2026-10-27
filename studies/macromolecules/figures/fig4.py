#!/usr/bin/env python3
"""Figure 4 of the paper, assembled: performance, reuse, scaling and self-improvement, at 7 in wide (ACS double
column). Every panel is drawn by the panel scripts' own functions from recorded results only; every number drawn or
written in the caption is read from these files, never typed in:

- a, memory ablation (A2, with E8's Claude Code column): `fig4ac.draw_a` from `a2a3e8/results.json`.
- b, the similarity ladder (A4's exact, paraphrase and sibling rungs, A2's near, mid and far strata):
  `fig4b.draw` from `a4/results.json`.
- c, scaling with the store's size (A2 and A3), from `a2a3e8/results.json`: `fig4ac`'s cells (`c_tokens`,
  `c_shares`, `c_findings_axis`) with the strata as rows and two measures as columns, so the panel fits beside b and d.
  Contradicted statements per answer (4c's middle row, near zero everywhere) are written in the caption, not drawn.
- d, reuse of KF's findings: `fig4_records.draw_d` from `loop-kf/reuse.json`.
- e, scaffold self-improvement. Left, the campaign's trajectory across its prompt versions
  (`fig4_records.draw_e` in a 2 × 2 grid, from `loop-kf/trajectory.json`); right, Part B's crossing pooled over the five
  restarts with each restart's estimate (`fig_restarts_final.draw_crossing`, from `restarts-final/results.json`): the
  knowledge alone (P0·S5 vs E0), the prompt alone (P5·S0 vs E0), the system (P5·S5 vs E0) and the prompt on the grown
  store (P5·S5 vs P0·S5), new tokens and web calls, all 60 held-out questions and the 20 near ones.

Left in the supporting information: the campaign revisits against their own first asks (`fig4_records`, files
`fig4b.*`), Part B's growth curves, parent split and per-arm quality (`fig_restarts_final`), and 4c's contradicted row
(`fig4c.*`).

Colours (`style.py`; no new colour): the arms keep their fixed colours in a and c (P neutral, the stores a blue ramp,
the web-off arms orange, A3's resampled stores magenta). b, d and e compare arms or stages rather than show one store,
so they are drawn in neutral inks, as `fig4b` does: e's pooled estimates are the dark ink (not Part B's figure's KF
blue, which means the store KF in a and c), each restart an open circle.

Writes `fig4` (PDF, SVG, 200 dpi PNG) to `analysis/figures/` (or `--out`) and the `fig4` entry of
`figures/manifest.json`, keeping the others. Commit this script before rendering, so the revision in the pins is on
record.

    OOPC_STUDY_ROOT=<main checkout> python -B fig4.py [--inputs DIR] [--out DIR]
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
import fig4ac, fig4b, fig4_records, fig_restarts_final as fig_b  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

NAME = "fig4"
KF_INPUTS = [fig4ac.INPUT, fig4b.INPUT, "loop-kf/reuse.json", "loop-kf/trajectory.json"]
SOURCES = {"a": [fig4ac.INPUT], "b": [fig4b.INPUT], "c": [fig4ac.INPUT], "d": ["loop-kf/reuse.json"],
           "e": ["loop-kf/trajectory.json", fig_b.INPUT]}
DRAWN_BY = {"a": "fig4ac.draw_a", "b": "fig4b.draw", "c": "fig4.draw_c (fig4ac's 4c cells, strata as rows)",
            "d": "fig4_records.draw_d",
            "e": "fig4_records.draw_e (2 × 2) and fig_restarts_final.draw_crossing (four comparisons)"}
W = S.DOUBLE
A_H, B_H, D_H, E_H = 2.3, 2.25, 2.0, 2.2  # row heights, inches; c spans b and d
LEFT_W = 3.5  # b and d; c takes the rest
E_LEFT_W = 3.25  # the campaign's trajectory; the crossing takes the rest
SIZE = (W, A_H + B_H + D_H + E_H)
CROSSING = fig_b.COMPARISONS[:4]  # knowledge alone, prompt alone, system, prompt on the grown store
STRATA = fig4ac.STRATA
TOKENS_YLIM = (0.3, 3.6)  # c's token ratios: 4c's range with headroom for the slopes above the marks and gridline
D_RATIOS, D_WSPACE = (0.85, 1.25), 0.35  # d's two plots: the bars wider, so their counts stay apart at 3.5 in


# ----------------------------------------------------------------------------------------------- inputs and pins

def load(base=None):
    """The KF results (refused unless pinned to KF) and Part B's final evaluation (refused unless pinned and
    cross-checked), as {"kf": {name: data}, "b": data}."""
    return {"kf": S.inputs(KF_INPUTS, base), "b": fig_b.load(base)}


def pins(data):
    """KF's pins as its inputs record them, A2/A3/E8's and A4's run records, and Part B's pins."""
    pinned = S.pins(data["kf"], NAME + ".py")
    pinned["records"] = {"a2a3e8": fig4ac.records(data["kf"]), "a4": fig4b.records(data["kf"])}
    part_b = fig_b.pins(data["b"], NAME + ".py")
    pinned["partB"] = {k: v for k, v in part_b.items() if k not in ("figureScript", "figureRevision")}
    return pinned


# ----------------------------------------------------------------------------------------------- c, strata as rows

def draw_c(fig, size, data):
    """4c with the strata as rows (near, mid, far) and two columns sharing x, findings in the store (log): new tokens
    against K0 and the share of answers (citing a saved finding; with the web off, a sourced result and complete)."""
    width, height = size
    left, right, top, bottom, cgap, rgap = 0.5, 0.16, 0.86, 0.36, 0.36, 0.1
    cw = (width - left - right - cgap) / 2
    rh = (height - top - bottom - 2 * rgap) / 3
    cells = {}
    for ri in range(len(STRATA)):
        y = bottom + (2 - ri) * (rh + rgap)
        for ci, x in enumerate((left, left + cw + cgap)):
            cells[(ri, ci)] = fig4ac.axes(fig, size, x, y, cw, rh, sharex=cells.get((0, 0)),
                                          sharey=cells.get((0, ci)))
    for ri, stratum in enumerate(STRATA):
        # the slopes in the upper corner, above every ratio, where the narrower cells leave no room below
        fig4ac.c_tokens(cells[(ri, 0)], stratum, data, title=False, labels=ri == 0, slopes="upper")
        fig4ac.c_shares(cells[(ri, 1)], stratum, data)
    cells[(0, 0)].set_ylim(TOKENS_YLIM)
    fig4ac.store_labels(cells[(0, 1)], data)
    for (ri, ci), ax in cells.items():
        fig4ac.c_findings_axis(ax, data)
        if ri < len(STRATA) - 1:
            ax.tick_params(axis="x", labelbottom=False)
    for ri, stratum in enumerate(STRATA):
        cells[(ri, 0)].set_ylabel(fig4ac.TITLE[stratum], fontsize=S.SIZE, labelpad=3)
    column_top = (height - top + 0.17) / height
    for ci, text in enumerate(("New tokens against K0 (log)", "Share of answers")):
        fig.text((left + ci * (cw + cgap)) / width, column_top, text, ha="left", va="bottom", fontsize=S.SMALL,
                 color=S.INK)
    fig.text((left + cw + cgap / 2) / width, 0.02 / height, "Findings in the store (log scale)", ha="center",
             va="bottom", fontsize=S.SMALL)
    upper, lower, shapes = fig4ac.c_legend_items()
    order = upper[:5] + lower[2:] + upper[5:] + lower[:2] + shapes  # by column: A2's stores; A3; web off and shapes
    fig.legend([h for h, _ in order], [label for _, label in order], loc="upper left",
               bbox_to_anchor=(left / width, 1 - 0.02 / height), ncol=3, fontsize=S.TINY, borderaxespad=0,
               columnspacing=0.9, handletextpad=0.25, labelspacing=0.18)
    S.letter(fig, "c")
    return cells


# ----------------------------------------------------------------------------------------------- d

def draw_d(fig, size, data):
    """4d at this width, its two reuse curves labelled where they run (a legend would cross the cited curve)."""
    fig4_records.draw_d(fig, size, data, ratios=D_RATIOS, wspace=D_WSPACE)
    ax = fig.axes[0]
    ax.get_legend().remove()
    r = data["loop-kf/reuse.json"]

    def points(key):
        return [(p["k"], p["share"]) for p in r[key]["points"] if p["k"] >= 1 and p["findings"] > 0]
    returned = points("ccdfReturnedSessions")
    k, share = next((p for p in returned if p[1] < 0.1), returned[-1])  # where returns fall below a tenth
    ax.text(k, share * 3, "returned\n(sessions)", ha="left", va="bottom", fontsize=S.TINY, color=S.INK,
            linespacing=1.0)
    cited = points("ccdfCitedAnswers")
    _, low = min(cited, key=lambda p: abs(p[0] - 5))  # under the cited curve's knee
    ax.text(cited[0][0] * 1.12, low / 3, "cited\n(answers)", ha="left", va="top", fontsize=S.TINY, color=S.INK2,
            linespacing=1.0)


# ----------------------------------------------------------------------------------------------- e

def draw_e(left_fig, right_fig, left_size, right_size, data):
    """e: the campaign's trajectory (left) and Part B's crossing (right), each with a heading."""
    fig4_records.draw_e(left_fig, left_size, data["kf"], rows=2,
                        margins={"left": 0.34, "right": 0.12, "top": 0.42, "bottom": 0.42, "wspace": 0.5,
                                 "hspace": 0.62})
    lw, lh = left_size
    left_fig.text(0.22 / lw, 1 - 0.035 / lh, "Campaign: the scaffold across prompt versions", ha="left", va="top",
                  fontsize=S.SIZE, color=S.INK)
    rw, rh = right_size
    label_w, gap, bottom, top = 1.3, 0.14, 0.36, 0.36
    w = (rw - 0.06 - label_w - gap - 0.06) / 2
    fig_b.draw_crossing(right_fig, data["b"], 0.06, bottom, label_w, w, gap, rh - bottom - top, size=right_size,
                        comparisons=CROSSING, colour=S.INK)
    right_fig.text(0.06 / rw, 1 - 0.035 / rh, "Part B: prompt × store, five restarts", ha="left", va="top",
                   fontsize=S.SIZE, color=S.INK)


# ----------------------------------------------------------------------------------------------- figure

def draw(data):
    S.setup()
    fig = plt.figure(figsize=SIZE)
    row_a, middle, row_e = fig.subfigures(3, 1, height_ratios=[A_H, B_H + D_H, E_H], hspace=0)
    left, right = middle.subfigures(1, 2, width_ratios=[LEFT_W, W - LEFT_W], wspace=0)
    sub_b, sub_d = left.subfigures(2, 1, height_ratios=[B_H, D_H], hspace=0)
    e_left, e_right = row_e.subfigures(1, 2, width_ratios=[E_LEFT_W, W - E_LEFT_W], wspace=0)
    fig4ac.draw_a(row_a, (W, A_H), data["kf"])
    fig4b.draw(sub_b, (LEFT_W, B_H), data["kf"])
    draw_c(right, (W - LEFT_W, B_H + D_H), data["kf"])
    draw_d(sub_d, (LEFT_W, D_H), data["kf"])
    draw_e(e_left, e_right, (E_LEFT_W, E_H), (W - E_LEFT_W, E_H), data)
    return fig


# ----------------------------------------------------------------------------------------------- caption

num, signed = fig_b.num, fig_b.signed


def ci(v, places=2):
    """An estimate with its 95% interval: "0.52 (0.41–0.57)", "−0.108 (−0.159 to −0.051)"."""
    centre = v.get("median", v.get("estimate", v.get("ratio")))
    joint = " to " if v["low"] < 0 else "–"
    return "%s (%s%s%s)" % (num(centre, places), num(v["low"], places), joint, num(v["high"], places))


def diff(v):
    """A difference in web calls per answer with its interval: "−4.1 (−5.8 to −2.2)"."""
    return "%s (%s to %s)" % (signed(v["estimate"], 1), signed(v["low"], 1), signed(v["high"], 1))


def thousands(v):
    return "{:,}".format(int(v))


def triple(A2, arm, key):
    return "/".join(str(A2["byStratum"][s]["arms"][arm][key]) for s in STRATA)


def series(items, last=" and "):
    """"a, b and c"."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + last + items[-1]


def caption_a(kf):
    v = kf[fig4ac.INPUT]
    A2, E8 = v["A2"], v["E8"]
    e8 = E8["byStratum"]["near"]["arms"]
    pk = {s: A2["byStratum"][s]["paired"]["KF"] for s in STRATA}
    arm = lambda s, a, k: A2["byStratum"][s]["arms"][a][k]  # noqa: E731
    questions = {s: pk[s]["tokens"]["n"] for s in STRATA}
    return (
        "(a) Memory ablation (A2): %d held-out questions (%s), %d replicates, %d answers per arm and stratum; in the "
        "fourth column, E8: the %d near questions answered once by the researcher on Claude Code (K0c, KFc). Left, the "
        "share of answers that are complete (filled circles), give a sourced result (squares) and pass (open "
        "circles), and contradicted statements per answer (count printed). Near/mid/far: contradicted P %s, K0 %s, "
        "KF %s; sourced result P %s, K0 %s, KF %s; passes P %s, K0 %s, KF %s. Claude Code: %d and %d contradicted "
        "statements (in %d and %d of %d answers), sourced result %d and %d. Middle, the KF/K0 ratio of new tokens "
        "(filled) and time (open): near %s, time %s; mid %s; far %s; Claude Code KFc/K0c %s. Right, web calls per "
        "answer, K0 to KF: near %.1f to %.1f (KF answered %d of %d without the web), mid %.1f to %.1f, far %.1f to "
        "%.1f; Claude Code %.1f to %.1f. The engines count tokens differently, so only ratios within an engine are "
        "compared." % (
            sum(questions.values()), series("%d %s" % (questions[s], s) for s in STRATA), A2["replicates"],
            arm("near", "KF", "answered"), e8["KFc"]["answered"],
            triple(A2, "P", "contradicted"), triple(A2, "K0", "contradicted"), triple(A2, "KF", "contradicted"),
            triple(A2, "P", "resultGiven"), triple(A2, "K0", "resultGiven"), triple(A2, "KF", "resultGiven"),
            triple(A2, "P", "pass"), triple(A2, "K0", "pass"), triple(A2, "KF", "pass"),
            e8["K0c"]["contradicted"], e8["KFc"]["contradicted"], e8["K0c"]["answersContradicted"],
            e8["KFc"]["answersContradicted"], e8["KFc"]["answered"], e8["K0c"]["resultGiven"], e8["KFc"]["resultGiven"],
            ci(pk["near"]["tokens"]), ci(pk["near"]["seconds"]), ci(pk["mid"]["tokens"]), ci(pk["far"]["tokens"]),
            ci(E8["byStratum"]["near"]["paired"]["KFc"]["tokens"]),
            arm("near", "K0", "meanWebCalls"), arm("near", "KF", "meanWebCalls"), arm("near", "KF", "noWeb"),
            arm("near", "KF", "answered"), arm("mid", "K0", "meanWebCalls"), arm("mid", "KF", "meanWebCalls"),
            arm("far", "K0", "meanWebCalls"), arm("far", "KF", "meanWebCalls"), e8["K0c"]["meanWebCalls"],
            e8["KFc"]["meanWebCalls"]))


def caption_b(kf):
    found = fig4b.rungs(kf)
    a4 = [r for r in found if r["kind"] == "A4"]
    totals = {r["answers"] for r in found}
    no_web = (series(["%d" % r["noWeb"] for r in found]) + " of %d" % totals.pop() if len(totals) == 1
              else series(["%d of %d" % (r["noWeb"], r["answers"]) for r in found]))
    return (
        "(b) Cost against similarity to past work, KF against K0 paired per question: A4's %d campaign first asks "
        "with findings in KF asked again exactly, in other words and as a sibling (%d replicates), then A2's near, mid "
        "and far strata. Filled circles, new tokens (median ratio; light points, each question's ratio): %s. Open "
        "squares, web calls (KF's mean over K0's): %s. KF answered without the web in %s answers (exact to far). The "
        "campaign's revisits against their own first asks, under earlier prompts, are another estimand (Supporting "
        "Information)." % (
            a4[0]["questions"], a4[0]["replicates"],
            series("%s %s" % (r["group"], ci(r["p"]["tokens"])) for r in found),
            series("%s %s" % (r["group"], ci(dict(r["p"]["webRatioInterval"], ratio=r["p"]["webRatio"])))
                   for r in found), no_web))


def caption_c(kf):
    v = kf[fig4ac.INPUT]
    A2, A3 = v["A2"], v["A3"]
    findings = A2["storeFindings"]
    resampled = fig4ac.resampled_stores(kf)
    sl2, sl3 = A2["estimates"]["slope"], A3["estimates"]["slope"]
    cov = A3["estimates"]["coverage"]["parentInStore"]
    arm = lambda s, a, k: A2["byStratum"][s]["arms"][a][k]  # noqa: E731
    web_on = [A2["byStratum"]["all"]["arms"][a]["contradicted"] for a in fig4ac.STORES]
    con_a3 = sum(s["byStratum"]["all"]["contradicted"] for s in A3["stores"].values())
    n_a3 = sum(s["byStratum"]["all"]["answered"] for s in A3["stores"].values())
    sizes = sorted({s["size"] for s in resampled.values()})
    seeds = len(resampled) // len(sizes)
    return (
        "(c) Scaling with the store's size: rows near, mid and far; x, findings in the store. Dotted lines, A2's "
        "stores (%d replicates): K0, KF200, KF1 and KF2 (KF cut at the end of the 200-task run and of campaign waves 1 "
        "and 2: %s, %s and %s findings) and KF (bars, 95%% intervals); small marks, A3's %d stores resampled from KF's "
        "questions (%s questions × %d seeds, %s–%s findings; one answer per question); open diamonds, A3's K0 and KF "
        "answered the same day. Left, new tokens against K0, with each stratum's within-question slope of log tokens "
        "on log findings in A2 and A3: near %s and %s, mid %s and %s, far %s and %s; in A3, a near question's own "
        "campaign parent in the store multiplies its tokens by %s (%s–%s). Right, answers citing a saved finding "
        "(circles; near, K0 to KF: %s of %d) and, with the web off (MF1 on KF1, MF on KF), answers giving a sourced "
        "result (filled squares; near %d and %d, far %d and %d of %d) and complete (open squares). Contradicted "
        "statements, near zero and not drawn: A2's web-on stores %s in %d answers each (K0 to KF), the web-off MF1 "
        "%d and MF %d; A3 %d in %s answers." % (
            A2["replicates"], thousands(findings["KF200"]), thousands(findings["KF1"]), thousands(findings["KF2"]),
            len(resampled), series([str(z) for z in sizes]), seeds,
            thousands(min(s["findings"] for s in resampled.values())),
            thousands(max(s["findings"] for s in resampled.values())),
            ci(sl2["near"], 3), ci(sl3["near"], 3), ci(sl2["mid"], 3), ci(sl3["mid"], 3), ci(sl2["far"], 3),
            ci(sl3["far"], 3), num(cov["multiplier"]), num(cov["multiplierLow"]), num(cov["multiplierHigh"]),
            "/".join(str(arm("near", a, "citingFindings")) for a in fig4ac.STORES), arm("near", "KF", "answered"),
            arm("near", "MF1", "resultGiven"), arm("near", "MF", "resultGiven"), arm("far", "MF1", "resultGiven"),
            arm("far", "MF", "resultGiven"), arm("near", "MF", "answered"),
            "/".join(map(str, web_on)), A2["byStratum"]["all"]["arms"]["K0"]["answered"],
            A2["byStratum"]["all"]["arms"]["MF1"]["contradicted"], A2["byStratum"]["all"]["arms"]["MF"]["contradicted"],
            con_a3, thousands(n_a3)))


def caption_d(kf):
    r = kf["loop-kf/reuse.json"]
    t = r["totals"]
    dose = r["doseResponse"]["primary"]["bins"]
    return (
        "(d) Reuse of KF's %s findings: the share returned by at least k later sessions' searches and cited by at "
        "least k later answers (%s%% returned at least once, %s%% cited; %s citations; median %d answers from deposit "
        "to first citation); right, the share of the %d campaign first asks citing a finding against the number of "
        "earlier campaign questions on the polymer (Wilson 95%% intervals): %s after %s earlier questions." % (
            thousands(t["findings"]), S.pct(t["everReturnedShare"]), S.pct(t["everCitedShare"]),
            thousands(t["citationsOfFindings"]), r["firstCitationLag"]["answers"]["median"],
            sum(b["firstAsks"] for b in dose),
            series(["%.0f%%" % (100 * b["citingFinding"] / b["firstAsks"]) for b in dose]),
            series([b["bin"].replace("-", "–") for b in dose])))


def caption_e(kf, b):
    t = kf["loop-kf/trajectory.json"]["stages"]
    stages = [s for s in fig4_records.STAGES if s in t]
    prompts = [next(iter(t[s]["promptVersions"])) for s in stages]
    models = list(dict.fromkeys(next(iter(t[s]["models"])) for s in stages))
    change = next(i for i, s in enumerate(stages) if next(iter(t[s]["models"])) == models[-1])
    trajectory = "; ".join("%s %s" % (title[0].lower() + title[1:], " → ".join(
        fig4_records.value_text(value(t[s]), unit) + unit for s in stages))
        for title, value, unit in fig4_records.MEASURES)
    p = b["meta"]["pins"]
    restarts = sorted(p["restarts"])
    rounds = len(p["restarts"][restarts[0]]["snapshots"]) - 1
    adopted = sum(len(x["adoptedRounds"]) for x in p["restarts"].values())
    s5 = [x["snapshots"]["S%d" % rounds]["findings"] for x in p["restarts"].values()]
    cross = b["crossing"]

    def comparison(key):
        c = cross[key]["pooled"]
        return "%s, near %s; web calls %s, near %s" % (ci(c["all"]["tokens"]), ci(c["near"]["tokens"]),
                                                       diff(c["all"]["webCalls"]), diff(c["near"]["webCalls"]))
    quality = {key: cross[key]["quality"]["all"] for key, _, _ in CROSSING}
    answers = b["arms"]["E0"]["all"]["answers"] * len(restarts)
    return (
        "(e) Scaffold self-improvement. Left, the campaign's four stages (the 200-task run and waves 1–3; researcher "
        "prompts %s; model %s, then %s from %s, dashed line): %s. Right, Part B: %d restarts of the loop from an "
        "empty store, %d rounds each, an improver session proposing one prompt edit per round, kept only if it passed "
        "a fixed rule on a development set (%d of %d kept); P0 is the frozen prompt and S0 the empty store, P%d and "
        "S%d a restart's prompt and store after its last round (%s–%s findings), and E0, P0 on S0, is one arm shared "
        "by the restarts. Pooled over the restarts (filled; hierarchical bootstrap 95%% interval, restarts then "
        "questions) and per restart (open circles), the new-token ratio and the difference in web calls per answer, "
        "all %d held-out questions and the %d near ones: knowledge alone (P0·S%d vs E0) %s; prompt alone "
        "(P%d·S0 vs E0) %s; system (P%d·S%d vs E0) %s; prompt on the grown store (P%d·S%d vs P0·S%d) %s. "
        "Contradicted statements in the %d answers of each comparison (E0's counted once per restart): %d, %d and %d "
        "against E0's %d, and %d against P0·S%d's %d; sourced results %d, %d and %d against %d." % (
            ", ".join(x[:6] for x in prompts), models[0], models[-1],
            fig4_records.STAGE_SHORT[stages[change]].lower(), trajectory,
            len(restarts), rounds, adopted, len(restarts) * rounds, rounds, rounds, thousands(min(s5)),
            thousands(max(s5)),
            b["meta"]["pins"]["questions"], b["meta"]["strata"]["near"],
            rounds, comparison("knowledge"), rounds, comparison("prompt"), rounds, rounds, comparison("system"),
            rounds, rounds, rounds, comparison("promptOnGrown"),
            answers, quality["knowledge"]["arm"]["contradicted"], quality["prompt"]["arm"]["contradicted"],
            quality["system"]["arm"]["contradicted"], quality["knowledge"]["reference"]["contradicted"],
            quality["promptOnGrown"]["arm"]["contradicted"], rounds,
            quality["promptOnGrown"]["reference"]["contradicted"],
            quality["knowledge"]["arm"]["resultGiven"], quality["prompt"]["arm"]["resultGiven"],
            quality["system"]["arm"]["resultGiven"], quality["knowledge"]["reference"]["resultGiven"]))


def captions(data):
    kf, b = data["kf"], data["b"]
    findings = kf[fig4ac.INPUT]["A2"]["storeFindings"]
    again = b["rechecks"]
    head = (
        "Figure 4. Performance, reuse, scaling and self-improvement. Each answer was checked against its cited sources "
        "by a Codex checker session, all of a question's arms together; token ratios are medians of per-question "
        "paired ratios with bootstrap 95%% intervals. P, the plain session; K0, the researcher on test 1's store (%s "
        "findings); KF, the researcher on the frozen knowledge base (%s findings). Passes (a) are drawn as secondary "
        "marks: checking %d of Part B's answers again changed %d pass verdicts and %d contradicted counts." % (
            thousands(findings["K0"]), thousands(findings["KF"]), again["answers"],
            again["answers"] - again["agree"]["pass"], again["answers"] - again["agree"]["contradicted"]))
    return {"head": head, "a": caption_a(kf), "b": caption_b(kf), "c": caption_c(kf), "d": caption_d(kf),
            "e": caption_e(kf, b)}


# ----------------------------------------------------------------------------------------------- render

def render(base=None, out=None):
    """Draws Figure 4 from the results in `base` (default analysis/) into `out` (default analysis/figures/) and
    records it in the manifest; returns the manifest entry."""
    data = load(base)
    pinned = pins(data)
    parts = captions(data)
    text = " ".join(parts.values())
    files = S.save(draw(data), NAME, pinned, text, out)
    sources = list(dict.fromkeys(x for panel in SOURCES.values() for x in panel))
    entry = {"pins": pinned,
             "panels": [{"panel": key, "sources": SOURCES[key], "drawnBy": DRAWN_BY[key], "caption": parts[key]}
                        for key in SOURCES],
             "assembled": {"files": files, "panels": list(SOURCES), "sources": sources, "caption": text},
             "note": "Figure 4 of the paper, assembled from the panel scripts' functions. In the supporting "
                     "information: the campaign revisits (fig4b.*, fig4_records), Part B's growth curves, parent "
                     "split and per-arm quality (fig_restarts_final), and 4c's contradicted row (fig4c.*), whose "
                     "counts are in the caption."}
    S.record(NAME, entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Figure 4, assembled from the panel scripts and recorded results.")
    parser.add_argument("--inputs", type=Path, help="read the results here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figure and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    print(entry["assembled"]["caption"])
    print("wrote", ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
