#!/usr/bin/env python3
"""The build of Part B's five restarts (restart-study-plan.md, Measures, "The build"), drawn from
`restarts-build/results.json` only (written by `recursive/build_results.py` from the restarts' records; no store, trace
or engine). Every number drawn or written in the caption is read from that file, never typed in.

- a: per restart, findings against tasks answered, stacked by status (Reviewed, Added, Needs checking, Rejected, each
  with its status in S5, credited to the task that saved it, in the order tasks finished); the snapshots S1–S5 marked
  where they were taken.
- b: distinct sources (by the store's own key, CL-23) against tasks answered, one line per restart, S1–S5 marked.
- c: polymers with a finding against tasks answered, one line per restart, S1–S5 marked.
- d: the improver's edit of each round and restart, adopted (filled) or rejected (hollow), with the dev rules that
  rejected it.

Writes `fig_restarts_build` (PDF, SVG, 200 dpi PNG) to `analysis/figures/` (or `--out`) and its entry in
`figures/manifest.json`, keeping the others. Commit this script before rendering, so the revision in the pins is on
record.

Colours: statuses keep their fixed colours (`style.STATUS`, stacked in the fixed order, so Reviewed and Rejected are
never adjacent). The restarts are replicates of one process, not categories, so their lines share one neutral ink and
are named at their ends; no new colour is added.

    OOPC_STUDY_ROOT=<main checkout> python -B fig_restarts_build.py [--inputs DIR] [--out DIR]
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402
from matplotlib import ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

INPUT = "restarts-build/results.json"
NAME = "fig_restarts_build"
SIZE = (7.0, 4.15)
RULE_CODE = {"fewer complete": "C", "fewer sourced": "S", "more contradicted": "X", "tokens > 1.10": "T",
             "too few pairs": "P"}
RULE_WORD = {"C": "fewer complete", "S": "fewer sourced", "X": "more contradicted", "T": "tokens > 1.10",
             "P": "too few pairs"}


def load(base=None):
    """The build's results; refused, drawing nothing, if missing, if a snapshot was not as taken or if the build
    reported a cross-check mismatch."""
    path = Path(base) / INPUT if base else S.common.analysis_dir(INPUT)
    if not path.exists():
        raise SystemExit("missing input %s; run recursive/build_results.py first" % INPUT)
    data = S.jread(path)
    restarts = data.get("restarts") or {}
    if not restarts or set(restarts) != set((data.get("meta") or {}).get("pins") or {}):
        raise SystemExit("%s carries no pins for its restarts" % INPUT)
    if not all(s.get("asTaken") for r in restarts.values() for s in r["snapshots"].values()):
        raise SystemExit("%s was built on a snapshot that is not as taken" % INPUT)
    if (data.get("crossChecks") or {}).get("count"):
        raise SystemExit("%s reports %d cross-check mismatches" % (INPUT, data["crossChecks"]["count"]))
    return data


def pins(data, script=NAME + ".py"):
    meta = data["meta"]
    restarts = {name: {k: p[k] for k in ("tag", "promptVersion", "model", "improverModel", "release", "seed")}
                for name, p in meta["pins"].items()}
    for name, p in meta["pins"].items():
        restarts[name]["snapshots"] = {k: v["sha256"] for k, v in p["snapshots"].items()}
        restarts[name]["prompts"] = p["prompts"]
    return {"restarts": restarts, "inputAnalysisRevision": [meta.get("analysisRevision")],
            "inputs": {INPUT: {"builder": meta.get("builder"), "builtAt": meta.get("builtAt")}},
            "figureScript": "studies/macromolecules/figures/" + script, "figureRevision": S.revision()}


def n(v):
    return "{:,}".format(v)


def span(values, f=n):
    lo, hi = min(values), max(values)
    return f(lo) if lo == hi else "%s–%s" % (f(lo), f(hi))


def spread_labels(ends, gap):
    """Label positions for line ends `ends` ({name: y}), at least `gap` apart, kept in order and centred on them."""
    order = sorted(ends, key=lambda k: ends[k])
    ys = [ends[k] for k in order]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    shift = (sum(ends[k] for k in order) - sum(ys)) / len(ys)
    return {k: y + shift for k, y in zip(order, ys)}


def snapshot_points(r, key):
    xs, ys = [], []
    for k in range(1, len(r["snapshots"])):
        s = r["snapshots"]["S%d" % k]
        xs.append(s["tasksAnswered"])
        ys.append(s[key] if key != "findings" else s["findings"])
    return xs, ys


def axes(fig, x, y, w, h, **kw):
    W, H = SIZE
    return fig.add_axes([x / W, y / H, w / W, h / H], **kw)


def draw_a(fig, data, top):
    """Five small panels of findings by status; `top` is the inch height of the panels' top edge."""
    restarts = data["restarts"]
    names = list(restarts)
    ymax = max(r["snapshots"]["S%d" % (len(r["snapshots"]) - 1)]["findings"] for r in restarts.values())
    left, gap, width, height = 0.48, 0.12, 1.15, 1.18
    out = []
    for i, name in enumerate(names):
        r = restarts[name]
        c = r["curve"]
        ax = axes(fig, left + i * (width + gap), top - height, width, height)
        ax.stackplot(c["tasks"], *[c[s] for s in S.STATUS_ORDER], colors=[S.STATUS[s] for s in S.STATUS_ORDER],
                     lw=0, zorder=2)
        xs, ys = snapshot_points(r, "findings")
        ax.plot(xs, ys, ls="none", marker="o", ms=2.4, mfc=S.SURFACE, mec=S.INK, mew=0.6, zorder=4, clip_on=False)
        if i == 0:
            for k, (x, y) in enumerate(zip(xs, ys), 1):
                ax.annotate("S%d" % k, (x, y), xytext=(-1, 3.5), textcoords="offset points", ha="right", va="bottom",
                            fontsize=S.TINY, color=S.INK2)
        last = r["snapshots"]["S%d" % (len(r["snapshots"]) - 1)]
        ax.set_title("%s  %s findings" % (name, n(last["findings"])), fontsize=S.SMALL, pad=2)
        ax.set_xlim(0, 500)
        ax.set_ylim(0, ymax * 1.08)
        ax.xaxis.set_major_locator(ticker.MultipleLocator(250))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(100))
        ax.yaxis.set_major_locator(ticker.MultipleLocator(1000))
        S.thousands(ax)
        ax.grid(axis="y")
        if i:
            ax.tick_params(labelleft=False)
        else:
            ax.set_ylabel("Findings", fontsize=S.SMALL)
        out.append(ax)
    fig.text((left + 2 * (width + gap) + width / 2) / SIZE[0], (top - height - 0.27) / SIZE[1], "Tasks answered",
             ha="center", va="top", fontsize=S.SMALL)
    totals = {s: [r["snapshots"]["S%d" % (len(r["snapshots"]) - 1)]["byStatus"][s] for r in restarts.values()]
              for s in S.STATUS_ORDER}
    handles = [plt.Rectangle((0, 0), 1, 1, color=S.STATUS[s], lw=0) for s in S.STATUS_ORDER]
    labels = ["%s %s" % (s, span(totals[s])) for s in S.STATUS_ORDER]
    handles.append(plt.Line2D([], [], ls="none", marker="o", ms=2.6, mfc=S.SURFACE, mec=S.INK, mew=0.6))
    labels.append("snapshot S1–S5")
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(1 - 0.06 / SIZE[0], 1 - 0.02 / SIZE[1]), ncol=5,
               fontsize=S.TINY, handlelength=0.9, columnspacing=1.0, borderaxespad=0)
    fig.text(0.0, 1.0, "a", fontsize=S.LETTER, fontweight="bold", ha="left", va="top")
    return out


def draw_lines(fig, data, box, key, ylabel, letter, ymax_pad=1.1):
    restarts = data["restarts"]
    x, y, w, h = box
    ax = axes(fig, x, y, w, h)
    ends = {}
    for name, r in restarts.items():
        c = r["curve"]
        ax.plot(c["tasks"], c[key], color=S.INK2, lw=0.8, zorder=2, solid_joinstyle="round")
        xs, ys = snapshot_points(r, key)
        ax.plot(xs, ys, ls="none", marker="o", ms=2.2, mfc=S.SURFACE, mec=S.INK, mew=0.5, zorder=3)
        ends[name] = (c["tasks"][-1], c[key][-1])
    top = max(v for _, v in ends.values()) * ymax_pad
    ax.set_ylim(0, top)
    ax.set_xlim(0, 500)
    gap = top * 0.075
    placed = spread_labels({k: v for k, (_, v) in ends.items()}, gap)
    for name, (ex, ey) in ends.items():
        ax.annotate(name, (ex, ey), xytext=(510, placed[name]), textcoords="data", ha="left", va="center",
                    fontsize=S.TINY, color=S.INK2, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=S.LIGHT, lw=0.4, shrinkA=0, shrinkB=0.5))
    ax.xaxis.set_major_locator(ticker.MultipleLocator(100))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(4))
    S.thousands(ax)
    ax.grid(axis="y")
    ax.set_xlabel("Tasks answered", fontsize=S.SMALL)
    ax.set_ylabel(ylabel, fontsize=S.SMALL)
    fig.text((x - 0.42) / SIZE[0], (y + h + 0.2) / SIZE[1], letter, fontsize=S.LETTER, fontweight="bold", ha="left",
             va="top")
    return ax


def draw_d(fig, data, box):
    restarts = data["restarts"]
    names = list(restarts)
    x, y, w, h = box
    ax = axes(fig, x, y, w, h)
    rounds = max(len(r["rounds"]) for r in restarts.values())
    for i, name in enumerate(names):
        for row in restarts[name]["rounds"]:
            dev = row["dev"]
            adopted = dev["adopted"]
            ax.plot(row["round"], i, ls="none", marker="o", ms=5.2, mfc=S.INK if adopted else S.SURFACE, mec=S.INK,
                    mew=0.8, zorder=3)
            if not adopted:
                ax.annotate("".join(RULE_CODE.get(rule, "?") for rule in dev["rejectedBy"]), (row["round"], i),
                            xytext=(4.2, 0), textcoords="offset points", ha="left", va="center", fontsize=S.TINY,
                            color=S.INK2)
        count = sum(row["dev"]["adopted"] for row in restarts[name]["rounds"])
        ax.annotate("%d" % count, (rounds + 0.75, i), ha="center", va="center", fontsize=S.SMALL, color=S.INK,
                    annotation_clip=False)
    ax.annotate("total", (rounds + 0.75, -0.75), ha="center", va="center", fontsize=S.TINY, color=S.INK2,
                annotation_clip=False)
    ax.set_xlim(0.5, rounds + 0.5)
    ax.set_ylim(len(names) - 0.5, -0.5)
    ax.set_xticks(range(1, rounds + 1))
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=S.SMALL)
    ax.tick_params(axis="both", length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_xlabel("Round", fontsize=S.SMALL)
    for k in range(1, rounds):
        ax.axvline(k + 0.5, color=S.GRID, lw=S.HAIR, zorder=0)
    used = sorted({RULE_CODE[rule] for r in restarts.values() for row in r["rounds"] for rule in row["dev"]["rejectedBy"]},
                  key=lambda c: "CSXTP".index(c))
    handles = [plt.Line2D([], [], ls="none", marker="o", ms=4.6, mfc=S.INK, mec=S.INK, mew=0.8),
               plt.Line2D([], [], ls="none", marker="o", ms=4.6, mfc=S.SURFACE, mec=S.INK, mew=0.8)]
    ax.legend(handles, ["adopted", "rejected"], loc="lower left", bbox_to_anchor=(-0.02, 1.0), ncol=2,
              fontsize=S.TINY, handletextpad=0.2, columnspacing=0.8, borderaxespad=0.1)
    words = ["%s %s" % (c, RULE_WORD[c]) for c in used]
    half = (len(words) + 1) // 2
    ax.text(-0.02, -0.3, "Rejected by:\n" + ",  ".join(words[:half]) + ("\n" + ",  ".join(words[half:]) if words[half:] else ""),
            transform=ax.transAxes, ha="left", va="top", fontsize=S.TINY, color=S.INK2, linespacing=1.3)
    fig.text((x - 0.42) / SIZE[0], (y + h + 0.2) / SIZE[1], "d", fontsize=S.LETTER, fontweight="bold", ha="left",
             va="top")
    return ax


def draw(data):
    S.setup()
    fig = plt.figure(figsize=SIZE)
    draw_a(fig, data, top=SIZE[1] - 0.36)
    row = (0.42, 1.55)  # bottom and height of b and c, inches
    draw_lines(fig, data, (0.48, row[0], 1.55, row[1]), "sources", "Distinct sources", "b")
    draw_lines(fig, data, (2.88, row[0], 1.55, row[1]), "polymers", "Polymers with a finding", "c", ymax_pad=1.15)
    draw_d(fig, data, (5.3, row[0] + 0.4, 1.3, row[1] - 0.4))
    return fig


def caption(data):
    restarts = data["restarts"]
    last = {name: r["snapshots"]["S%d" % (len(r["snapshots"]) - 1)] for name, r in restarts.items()}
    first = {name: r["snapshots"]["S1"] for name, r in restarts.items()}
    p1, p4, conv = data["predictions"]["1"], data["predictions"]["4-build"], data["convergence"]
    added_findings = [a for v in p1["restarts"].values() for a in v["findingsAdded"]]
    last_polymers = [v["polymersAdded"][-1] for v in p1["restarts"].values()]
    first_polymers = [v["polymersAdded"][0] for v in p1["restarts"].values()]
    rules = conv["rejectionsByRule"]
    return (
        "Build of the five restarts R1–R5, each from an empty store over five rounds of 100 tasks (%s tasks answered "
        "in all), from their records. (a) Findings against tasks answered, stacked by their status in S5 and credited "
        "to the task that saved them; circles mark the snapshots S1–S5. Each round added %s findings; the final stores "
        "hold %s findings (largest %.1f%% above smallest): Reviewed %s, Added %s, Needs checking %s, Rejected %s (the "
        "last two too few to show). (b) Distinct sources by the store's key, %s at S5 (%s with URL query strings kept, "
        "CL-23); %s source notes. (c) Polymers with a finding (any status): %s at S1, %s at S5; round 1 added %s, round "
        "5 added %s. (d) The improver's one edit per round, adopted when the 30 dev questions showed no more "
        "contradicted statements, no fewer complete or sourced answers and a median paired token ratio at most 1.10: "
        "%d of %d adopted (%s per restart); rejections by rule (an edit can fail several): fewer complete %d, fewer "
        "sourced %d, more contradicted %d, tokens above 1.10 %d. Prediction 1 %s; the build half of prediction 4 %s." % (
            n(sum(v["tasksAnswered"] for v in last.values())), span(added_findings),
            span([v["findings"] for v in last.values()]), 100 * p1["spreadOverSmallest"],
            span([v["byStatus"]["Reviewed"] for v in last.values()]), span([v["byStatus"]["Added"] for v in last.values()]),
            span([v["byStatus"]["Needs checking"] for v in last.values()]),
            span([v["byStatus"]["Rejected"] for v in last.values()]),
            span([v["sources"] for v in last.values()]), span([v["sourcesKeepingQuery"] for v in last.values()]),
            span([v["notes"] for v in last.values()]), span([v["polymers"] for v in first.values()]),
            span([v["polymers"] for v in last.values()]), span(first_polymers), span(last_polymers),
            p4["total"], p4["proposed"], span(list(p4["adopted"].values())), rules.get("fewer complete", 0),
            rules.get("fewer sourced", 0), rules.get("more contradicted", 0), rules.get("tokens > 1.10", 0),
            p1["verdict"], p4["verdict"]))


def render(base=None, out=None):
    """Draws the figure from the build's results in `base` (default analysis/) into `out` (default analysis/figures/)
    and records it in the manifest; returns the manifest entry."""
    data = load(base)
    pinned = pins(data)
    text = caption(data)
    files = S.save(draw(data), NAME, pinned, text, out)
    entry = {"pins": pinned, "panels": [{"panel": "restarts-build", "files": files, "sources": [INPUT], "caption": text}],
             "assembled": {"files": files, "panels": ["a", "b", "c", "d"], "sources": [INPUT]}}
    S.record(NAME, entry, out)
    return entry


def main():
    parser = argparse.ArgumentParser(description="The restarts' build figure from recursive/build_results.py's results.")
    parser.add_argument("--inputs", type=Path, help="read restarts-build/results.json here instead of analysis/")
    parser.add_argument("--out", type=Path, help="write the figure and manifest here instead of analysis/figures")
    args = parser.parse_args()
    entry = render(args.inputs, args.out)
    print(entry["panels"][0]["caption"])
    print("wrote", ", ".join(entry["assembled"]["files"]))


if __name__ == "__main__":
    main()
