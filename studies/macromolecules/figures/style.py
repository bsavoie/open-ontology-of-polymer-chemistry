"""The fixed look of every Macromolecules figure, the pins each file carries, and the one manifest of what was drawn.

Fig. 3 and 4 are drawn by scripts from recorded results only (study plan, "Figures" and "Statistics"). Every script
imports this module for its colours, sizes and fonts, reads its inputs with `inputs()` (which refuses outputs whose pins
are not KF's), and writes each panel with `save()`: a PDF and an SVG (vector) and a 200 dpi PNG preview, each carrying
the pins in its metadata, into `analysis/figures/` (private, like the records it is drawn from). `record()` keeps
`figures/manifest.json`: every file, its sources, its pins and a caption whose numbers come from the data.

Colours (ACS rule: one fixed colour per status and per arm across all figures). Checked with the dataviz skill's
`validate_palette.js` on a white surface (2026-10-19):

- STATUS, in stacking order Reviewed, Added, Needs checking, Rejected: adjacent pairs pass (worst colour-vision
  difference 12.3, Needs checking against Added under protanopia; normal vision 15.3 or more). Reviewed and Rejected
  are not told apart under protanopia (3.9), so they are never drawn side by side: a stack keeps Added and Needs
  checking between them, every panel has a legend or labels, and a scatter that shows Rejected must also mark it.
  Added and Needs checking are below 3:1 contrast on white, so they always come with a legend and labels.
- ARM: P is neutral; the stores the researcher answers with (K0, K200 or KF200, K1 or KF1, K2 or KF2, K3 or KF) are
  one blue ramp, light to dark with size; the web-off arms (M1 or MF1, M3 or MF) an orange ramp; A3's resampled stores
  (100, 200, 400, 800 questions) a magenta ramp. Each ramp passes the ordinal checks (monotone lightness, steps at least
  0.06 apart, light end at least 2:1 on white); the three families at matched lightness pass all-pairs (worst 13.1).
  Steps of one ramp are told apart by lightness and labels, not hue.
- SEQUENTIAL: one violet ramp for magnitude (heatmaps), monotone in lightness; its light end is faint on white, so
  a zero is left blank rather than given the lightest step. Neutral inks (INK, INK2, MUTED, LIGHT) for
  single-series marks, text and axes.
"""
import csv, datetime as dt, json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402
from analysis import kf  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STATUS = {"Reviewed": "#0a7e3a", "Added": "#15b194", "Needs checking": "#eda100", "Rejected": "#e34948"}
STATUS_ORDER = list(STATUS)
# Review outcomes drawn as the status they give a finding.
OUTCOME = {"supported": "Reviewed", "uncertain": "Needs checking", "unsupported": "Rejected"}

_BLUE = ["#7cb4fc", "#4e95ed", "#3077cd", "#0b5bae", "#004182"]
_ORANGE = ["#fd923e", "#af5b0b"]
ARM = {"P": "#52514e",
       "K0": _BLUE[0], "K200": _BLUE[1], "KF200": _BLUE[1], "K1": _BLUE[2], "KF1": _BLUE[2],
       "K2": _BLUE[3], "KF2": _BLUE[3], "K3": _BLUE[4], "KF": _BLUE[4],
       "M1": _ORANGE[0], "MF1": _ORANGE[0], "M3": _ORANGE[1], "MF": _ORANGE[1]}
RESAMPLED = {100: "#fb83bf", 200: "#d863a0", 400: "#b54481", 800: "#942464"}  # A3, by questions in the store

SEQUENTIAL = ["#dad0ff", "#c3b0fd", "#ad8dfd", "#9575e2", "#7d5cc7", "#6744ac", "#4c258c"]  # OKLCH hue 295, L .88-.38
INK, INK2, MUTED = "#1a1a19", "#52514e", "#898781"  # text, secondary text and single-series marks, ticks
LIGHT = "#bdbcb4"  # the lighter of two neutral series
GRID, AXIS, BAND = "#e1e0d9", "#c3c2b7", "#f3f2ee"  # gridlines, axis lines, background bands
SURFACE = "#ffffff"

DOUBLE, SINGLE = 7.0, 3.33  # ACS column widths, inches
FONT = ["Arial", "Helvetica", "DejaVu Sans"]
SIZE, SMALL, TINY, LETTER = 7.0, 6.5, 5.5, 9.0  # points; nothing below 5.5 (ACS: at least 4.5 at final size)
LINE, HAIR = 1.0, 0.5  # data lines and axes, points
DPI = 200
OUT = common.analysis_dir("figures")


def setup():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": FONT, "font.size": SIZE,
        "axes.titlesize": SIZE, "axes.labelsize": SIZE, "axes.labelcolor": INK, "axes.edgecolor": AXIS,
        "axes.linewidth": HAIR, "axes.spines.top": False, "axes.spines.right": False, "axes.titlelocation": "left",
        "axes.titlepad": 3, "axes.labelpad": 2, "axes.axisbelow": True,
        "xtick.labelsize": SMALL, "ytick.labelsize": SMALL, "xtick.color": INK2, "ytick.color": INK2,
        "xtick.labelcolor": INK, "ytick.labelcolor": INK,
        "xtick.major.width": HAIR, "ytick.major.width": HAIR, "xtick.minor.width": HAIR * 0.6,
        "ytick.minor.width": HAIR * 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "xtick.minor.size": 1.5, "ytick.minor.size": 1.5, "xtick.major.pad": 1.5, "ytick.major.pad": 1.5,
        "grid.color": GRID, "grid.linewidth": HAIR, "lines.linewidth": LINE, "lines.markersize": 3.5,
        "legend.fontsize": SMALL, "legend.frameon": False, "legend.handlelength": 1.2, "legend.handletextpad": 0.4,
        "legend.borderaxespad": 0.2, "legend.labelspacing": 0.25, "legend.columnspacing": 0.8,
        "patch.linewidth": 0, "text.color": INK, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "pdf.fonttype": 42, "svg.fonttype": "none", "svg.hashsalt": "oopc-macromolecules",
    })


def letter(fig, text, x=0.0, y=1.0):
    """The panel letter at the top left of a figure or subfigure."""
    fig.text(x, y, text, fontsize=LETTER, fontweight="bold", ha="left", va="top", color=INK)


def grid(fig, size, rows=1, cols=1, left=0.4, right=0.1, top=0.25, bottom=0.3, **kw):
    """A gridspec on a figure or subfigure of `size` (width, height in inches) with margins in inches, so a panel
    lays out the same alone and in the assembled figure."""
    w, h = size
    return fig.add_gridspec(rows, cols, left=left / w, right=1 - right / w, top=1 - top / h, bottom=bottom / h, **kw)


def text_width(fig, strings, size=SMALL):
    """The widest of `strings` at `size` points, in inches, as `fig` would draw it."""
    root = getattr(fig, "figure", fig) or fig
    renderer = root.canvas.get_renderer()
    widest = 0.0
    for s in strings:
        t = root.text(0, 0, s, fontsize=size)
        widest = max(widest, t.get_window_extent(renderer).width / root.dpi)
        t.remove()
    return widest


def thousands(ax, axis="y"):
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: "{:,.0f}".format(v))
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


# ----------------------------------------------------------------------------------------------- inputs and pins

def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def inputs(names, base=None):
    """{name: data} for A1's JSON outputs (names like "dataset-kf/growth.json", under analysis/ or `base`). Raises
    SystemExit, drawing nothing, if a file is missing or its pins are not KF's. A CSV carries no pins: read it with
    `rows` beside the JSON of the same build, whose pins vouch for it."""
    out = {}
    for name in names:
        path = Path(base) / name if base else common.analysis_dir(name)
        if not path.exists():
            raise SystemExit("missing input %s; run the A1 builds first" % name)
        data = jread(path)
        meta = data.get("meta") or {}
        if (meta.get("knowledgeSnapshot"), meta.get("storeFingerprint"), meta.get("graphRelease")) != (
                kf.SNAPSHOT_ID, kf.FINGERPRINT, kf.RELEASE_ID):
            raise SystemExit("%s is not built on KF (%s)" % (name, meta.get("knowledgeSnapshot")))
        out[name] = data
    return out


def rows(name, base=None):
    path = Path(base) / name if base else common.analysis_dir(name)
    if not path.exists():
        raise SystemExit("missing input %s; run the A1 builds first" % name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=common.STUDY, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def revision():
    """The figure scripts' commit, with "-dirty" when `figures/` has changes not committed."""
    head = _git("rev-parse", "--short=12", "HEAD")
    dirty = _git("status", "--porcelain", "--", str(Path(__file__).resolve().parent))
    return head and head + ("-dirty" if dirty else "")


def pins(data, script):
    """The pins block of a panel: KF's pins as its inputs record them, the inputs' analysis revisions, and the figure
    script and its revision."""
    metas = [d["meta"] for d in data.values()]
    first = metas[0]
    return {"store": first["store"], "knowledgeSnapshot": first["knowledgeSnapshot"],
            "storeFingerprint": first["storeFingerprint"], "graphRelease": first["graphRelease"],
            "prompt": first["prompt"], "codeTag": first["codeTag"],
            "inputAnalysisRevision": sorted({m.get("analysisRevision") for m in metas}),
            "inputs": {name: {"builder": d["meta"].get("builder"), "builtAt": d["meta"].get("builtAt")}
                       for name, d in data.items()},
            "figureScript": "studies/macromolecules/figures/" + script, "figureRevision": revision()}


# ----------------------------------------------------------------------------------------------- output

def save(fig, name, pinned, caption, out=None):
    """Writes `name`.pdf, .svg and .png with the pins and caption in their metadata; returns the file names."""
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(pinned, ensure_ascii=False, sort_keys=True)
    title = "Macromolecules study, " + name
    creator = "%s %s" % (pinned["figureScript"], pinned["figureRevision"])
    fig.savefig(out / (name + ".pdf"), metadata={"Title": title, "Subject": caption, "Keywords": text,
                                                 "Creator": creator, "CreationDate": None})
    fig.savefig(out / (name + ".svg"), metadata={"Title": title, "Description": caption + "\nPins: " + text,
                                                 "Creator": creator, "Date": None})
    fig.savefig(out / (name + ".png"), dpi=DPI, metadata={"Title": title, "Description": caption, "Pins": text,
                                                          "Software": creator})
    plt.close(fig)
    return [name + ext for ext in (".pdf", ".svg", ".png")]


def record(key, entry, out=None):
    """Sets one script's entry (`key`: fig3, fig4_records) in figures/manifest.json, keeping the others."""
    out = Path(out or OUT)
    path = out / "manifest.json"
    manifest = jread(path) if path.exists() else {}
    manifest.setdefault("about", "Every figure file drawn from recorded results, with its sources (under "
                                 ".oopc/study/analysis/), its pins and a caption whose numbers come from the data.")
    manifest.setdefault("figures", {})[key] = dict(entry, drawnAt=dt.datetime.now(dt.timezone.utc)
                                                   .isoformat(timespec="seconds"))
    text = json.dumps(manifest, ensure_ascii=False, indent=1)
    if "/Users/" in text:
        raise SystemExit("refusing to write a local path into the manifest")
    path.write_text(text + "\n", encoding="utf-8")


def pct(share, places=1):
    """A share as a percentage for captions: one decimal, two below 1%, "0" for nothing."""
    value = 100 * share
    if value == 0:
        return "0"
    return "%.*f" % (2 if value < 1 else places, value)
