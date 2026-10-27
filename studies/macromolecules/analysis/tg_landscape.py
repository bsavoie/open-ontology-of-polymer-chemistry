#!/usr/bin/env python3
"""Fig. 3d data: the Tg (and Tm) landscape of the best-covered polymers in KF, one row per finding (experiment A1).

Reads, read-only: the frozen copy of KF (`kf.store()`; property, value, unit and conditions, the conditions only to
read a method from), the property map built on it (`properties-kf/finding_classes.csv`: each finding's class and the
method labels of its property string and conditions) and the polymer labels and classes of `dataset-kf/coverage.json`.
Writes `.oopc/study/analysis/tg-landscape/` (or `--out`):

- `tg_landscape.csv`: one row per Tg or Tm finding of the chosen polymers whose value reads as one temperature:
  polymer id, label, class and rank by median Tg; property (Tg, Tm); finding id; status (Reviewed, Added, Needs
  checking, Rejected); the value and unit as saved; the value in °C (kelvin converted; "x ± y" gives x; "about x"
  gives x) and how it was read (`parse`); the method (DSC, DMA, other, none; see `method`), where it was read
  (`method_from`: property or conditions) and the property map's method labels.
- `tg_landscape.json`: KF's pins, the rules, the polymers in order of median Tg, the method split of every Tg (and
  Tm) finding with a readable value, the findings without one (ranges, several values, bounds, "not detected"), the
  findings of the map's Tg and Tm classes whose property is not a Tg or Tm value, and, for every polymer with DSC and
  DMA Tg values, whether the DMA median lies above the DSC median.

A Tg finding is one the property map puts in its glass-transition class whose property string names a glass
transition or Tg and is not a derived quantity (a correction, accuracy, error, uncertainty, reproducibility, change or
ΔTg); likewise Tm with melting. Chosen polymers: those with at least MIN_TG Tg findings with a readable value, at most
MOST of them, ranked by that count. No text beyond the saved property, value, unit and method labels is written.

    python -B tg_landscape.py [--out DIR]
"""
import argparse, collections, csv, json, re, sqlite3, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import analysis_dir  # noqa: E402
from analysis import kf  # noqa: E402
from analysis.properties import rules  # noqa: E402

OUT = analysis_dir("tg-landscape")
CLASSES = analysis_dir("properties-kf") / "finding_classes.csv"
COVERAGE = analysis_dir("dataset-kf") / "coverage.json"
PROPERTIES = {"glass-transition-temperature": "Tg", "melting-temperature": "Tm"}
STATUS = {"supported": "Reviewed", "accepted": "Added", "uncertain": "Needs checking", "unsupported": "Rejected"}
MIN_TG, MOST = 3, 40

NUMBER = r"[-+]?\d+(?:\.\d+)?"
APPROXIMATE = re.compile(r"^(approximately|approx\.?|about|around|ca\.?|~|∼|≈|of the order of)\s*", re.I)
NOT_OBSERVED = re.compile(r"^(absent|not (detected|visible|observed|seen)|no\b.*\b(peak|transition)s?|none)\b", re.I)
SINGLE = re.compile(r"^(%s)$" % NUMBER)
UNCERTAINTY = re.compile(r"^(%s)\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?$" % NUMBER)
RANGE = re.compile(r"^(%s)\s*(?:–|—|-|to)\s*(%s)$" % (NUMBER, NUMBER))
CELSIUS = {"°c", "℃", "° c", "degc", "c"}

NAMES = {"Tg": re.compile(r"glass[- ]transition|\btg\b"), "Tm": re.compile(r"melt|\btm")}
DERIVED = re.compile(r"correction|accuracy|error|uncertaint|reproducib|repeatab|δ ?t[gm]\b|change|shift|difference|"
                     r"increase|decrease|depression|elevation")
# Methods, on rules.normalize text (′ and ″ become ' and ''). A run of heating alone ("first heating") names no method.
DSC = re.compile(r"\b(?:tm|m)?dsc\w*|calorimetr|\bastm ?(?:d3418|e1356|d7426|e794)|\biso ?11357")
DMA = re.compile(r"\bdma\b|\bdmta\b|\bdms\b|dynamic[- ]mechanical|\btan ?(?:δ|delta)|loss[- ]factor|"
                 r"(?:storage|loss)[- ]modulus|\be'{1,2}(?![\w'])|\biso ?6721|\bastm ?(?:d4065|d5418|d5023|d5026|d7028|e1640)")
OTHER = {"TMA", "DTA", "dielectric spectroscopy", "rheometry", "ellipsometry", "PALS"}  # rules.method labels
NEGATED = re.compile(r"\b(?:not|no|without|rather than|instead of)\b(?:[\s-]+[\w'-]+){0,4}?[\s-]+(?:(?:tm|m)?dsc|dma|dmta)\b")
RULES = {
    "tg": "a finding of the map's glass-transition class whose property names a glass transition or Tg and is not a "
          "derived quantity (correction, accuracy, error, uncertainty, reproducibility, change, ΔTg); Tm likewise",
    "value": "one temperature: a number, 'x ± y' (x) or 'about x' (x), in °C or K (converted); ranges, several values, "
             "bounds and 'not detected' have none and stay out of the split, the comparison and the plot",
    "method": "read from the property string, else from the conditions, never from the statement: DSC (DSC, TMDSC, "
              "calorimetry, ASTM D3418, E1356, D7426, E794, ISO 11357), DMA (DMA, DMTA, DMS, dynamic mechanical, tan δ, "
              "loss factor, storage or loss modulus, E′ or E″, ISO 6721, ASTM D4065, D5418, D5023, D5026, D7028, E1640), "
              "other (TMA, DTA, dielectric spectroscopy, rheometry, ellipsometry, PALS), else none; a method named after "
              "'not', 'no', 'without', 'rather than' or 'instead of' (within four words) does not count; a text naming "
              "both DSC and DMA is 'DSC and DMA', kept out of the comparison; a heating run alone names no method",
}


def celsius(value, unit):
    """(value_c, low_c, high_c, parse) for a saved value and unit; value_c is None unless the value is one
    temperature (parse then says why; a range keeps its ends)."""
    text = (value or "").strip().replace("−", "-")
    unit = (unit or "").strip().lower()
    if NOT_OBSERVED.match(text):
        return None, None, None, "not observed"
    approximate = bool(APPROXIMATE.match(text))
    text = APPROXIMATE.sub("", text)
    if re.match(r"^[<>≤≥]", text):
        return None, None, None, "bound"
    found = SINGLE.match(text) or UNCERTAINTY.match(text)
    if found:
        low = high = float(found.group(1))
        parse = "uncertainty" if UNCERTAINTY.match(text) else "number"
    elif RANGE.match(text):
        low, high = sorted(float(x) for x in RANGE.match(text).groups())
        parse = "range"
    elif len(re.findall(NUMBER, text)) > 1 and re.search(r"\band\b|[;,/]", text):
        return None, None, None, "several values"
    else:
        return None, None, None, "unparsed"
    if unit == "k":
        low, high = low - 273.15, high - 273.15
    elif unit not in CELSIUS:
        return None, None, None, "unit not °C or K"
    parse = ("approximate " if approximate else "") + parse + (" (from K)" if unit == "k" else "")
    return (round(low, 2) if low == high else None), round(low, 2), round(high, 2), parse


def _group(text):
    text = NEGATED.sub(" ", rules.normalize(text))
    dsc, dma = bool(DSC.search(text)), bool(DMA.search(text))
    if dsc or dma:
        return "DSC and DMA" if dsc and dma else "DSC" if dsc else "DMA"
    return "other" if set((rules.method(text) or "").split("; ")) & OTHER else None


def method(prop, conditions):
    """(method, where it was read): the property string first, then the conditions (RULES["method"])."""
    for where, text in (("property", prop), ("conditions", conditions)):
        group = _group(text)
        if group:
            return group, where
    return "none", ""


def is_value_of(name, prop):
    """Does the property string name Tg (or Tm) as a value, not a derived quantity?"""
    text = rules.normalize(prop)
    return bool(NAMES[name].search(text)) and not DERIVED.search(text)


def median(values):
    return round(statistics.median(values), 2) if values else None


def build(store, classes_path=CLASSES, coverage_path=COVERAGE):
    """(landscape rows, summary), from a store and the property map's per-finding classes."""
    labels = {p["id"]: p for p in json.loads(Path(coverage_path).read_text())["polymers"]}
    with open(classes_path, newline="") as fh:
        classes = {r["finding_id"]: r for r in csv.DictReader(fh)}
    db = sqlite3.connect(Path(store).resolve().as_uri() + "?mode=ro", uri=True)
    found = db.execute("SELECT id, subject, status, property, value, unit, conditions FROM findings ORDER BY id").fetchall()
    db.close()
    rows, excluded = [], []
    for fid, subject, status, prop, value, unit, conditions in found:
        c = classes.get(fid) or {}
        name = PROPERTIES.get(c.get("property_class"))
        if not name:
            continue
        if not is_value_of(name, prop):
            excluded.append({"finding_id": fid, "property": name, "propertyString": prop or ""})
            continue
        value_c, low, high, parse = celsius(value, unit)
        group, where = method(prop, conditions)
        rows.append({"polymer_id": subject or "", "property": name, "finding_id": fid,
                     "status": STATUS.get(status, status), "value": value or "", "unit": unit or "",
                     "value_c": value_c, "low_c": low, "high_c": high, "parse": parse, "method": group,
                     "method_from": where, "method_in_string": c.get("method") or "",
                     "method_in_conditions": c.get("method_in_conditions") or ""})
    readable = [r for r in rows if r["value_c"] is not None]
    tg = [r for r in readable if r["property"] == "Tg"]
    counts = collections.Counter(r["polymer_id"] for r in tg if r["polymer_id"])
    chosen = [p for p, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= MIN_TG][:MOST]

    def values(polymer, prop, group=None):
        return [r["value_c"] for r in readable if r["polymer_id"] == polymer and r["property"] == prop
                and (group is None or r["method"] == group)]
    order = sorted(chosen, key=lambda p: (median(values(p, "Tg")), p))
    rank = {p: i for i, p in enumerate(order, 1)}
    landscape = []
    for r in readable:
        if r["polymer_id"] in rank:
            p = labels.get(r["polymer_id"], {})
            landscape.append(dict(polymer_rank=rank[r["polymer_id"]], polymer_id=r["polymer_id"],
                                  polymer_label=p.get("label", ""), polymer_class=p.get("class") or "", **{
                                      k: v for k, v in r.items() if k != "polymer_id"}))
    landscape.sort(key=lambda r: (r["polymer_rank"], r["property"], r["value_c"], r["finding_id"]))
    both = []
    for p in sorted({r["polymer_id"] for r in tg if r["polymer_id"]}):
        dsc, dma = values(p, "Tg", "DSC"), values(p, "Tg", "DMA")
        if dsc and dma:
            both.append({"polymer_id": p, "label": labels.get(p, {}).get("label", ""), "dsc": len(dsc), "dma": len(dma),
                         "medianDsc": median(dsc), "medianDma": median(dma),
                         "dmaMinusDsc": round(median(dma) - median(dsc), 2), "inLandscape": p in rank})
    differences = [b["dmaMinusDsc"] for b in both]
    unreadable = [r for r in rows if r["value_c"] is None]
    summary = {
        "rules": dict(RULES, selection="polymers with at least %d Tg findings with a readable value, at most %d, ranked "
                                       "by that count; their Tg and Tm findings with a readable value; polymer_rank "
                                       "orders them by median Tg" % (MIN_TG, MOST)),
        "polymers": [{"rank": rank[p], "id": p, "label": labels.get(p, {}).get("label", ""),
                      "class": labels.get(p, {}).get("class"), "tgFindings": len(values(p, "Tg")),
                      "tmFindings": len(values(p, "Tm")), "medianTg": median(values(p, "Tg")),
                      "medianTm": median(values(p, "Tm")),
                      "tgByMethod": dict(collections.Counter(r["method"] for r in landscape
                                                             if r["polymer_id"] == p and r["property"] == "Tg"))}
                     for p in order],
        "rows": {"landscape": len(landscape), "Tg": sum(r["property"] == "Tg" for r in landscape),
                 "Tm": sum(r["property"] == "Tm" for r in landscape)},
        "tgFindings": sum(r["property"] == "Tg" for r in rows), "tgWithReadableValue": len(tg),
        "tgReadableWithoutPolymerId": sum(not r["polymer_id"] for r in tg),
        "tmFindings": sum(r["property"] == "Tm" for r in rows),
        "tmWithReadableValue": sum(r["property"] == "Tm" for r in readable),
        "tgMethodSplit": dict(collections.Counter(r["method"] for r in tg).most_common()),
        "tgMethodFrom": dict(collections.Counter(r["method_from"] or "none" for r in tg).most_common()),
        "tgMethodSplitLandscape": dict(collections.Counter(r["method"] for r in landscape if r["property"] == "Tg")
                                       .most_common()),
        "tmMethodSplit": dict(collections.Counter(r["method"] for r in readable if r["property"] == "Tm").most_common()),
        "parse": dict(collections.Counter(r["parse"] for r in rows).most_common()),
        "statusLandscape": dict(collections.Counter(r["status"] for r in landscape).most_common()),
        "withoutReadableValue": [{k: r[k] for k in ("finding_id", "polymer_id", "property", "value", "unit", "low_c",
                                                    "high_c", "parse", "method")} for r in unreadable],
        "notTgOrTmValues": excluded,
        "dmaAboveDsc": {"about": "polymers with DSC and DMA Tg values (readable values, any status): the median of the "
                                 "DMA values against the median of the DSC values",
                        "polymers": len(both), "dmaAbove": sum(d > 0 for d in differences),
                        "dmaBelow": sum(d < 0 for d in differences), "equal": sum(d == 0 for d in differences),
                        "medianDifference": median(differences), "byPolymer": both},
    }
    return landscape, summary


def main():
    parser = argparse.ArgumentParser(description="Fig. 3d: the Tg landscape of KF.")
    parser.add_argument("--out", type=Path, help="write the outputs here instead")
    args = parser.parse_args()
    out = args.out or OUT
    out.mkdir(parents=True, exist_ok=True)
    landscape, summary = build(kf.store())
    with open(out / "tg_landscape.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(landscape[0]))
        writer.writeheader()
        writer.writerows(landscape)
    (out / "tg_landscape.json").write_text(json.dumps({"meta": kf.meta("tg_landscape.py"), **summary},
                                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("polymers %d, rows %d; Tg methods %s of %d readable; DMA above DSC in %d of %d polymers, median %+.2f" % (
        len(summary["polymers"]), len(landscape), summary["tgMethodSplit"], summary["tgWithReadableValue"],
        summary["dmaAboveDsc"]["dmaAbove"], summary["dmaAboveDsc"]["polymers"], summary["dmaAboveDsc"]["medianDifference"]))


if __name__ == "__main__":
    main()
