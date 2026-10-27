#!/usr/bin/env python3
"""Build the E3 property map from the frozen K3 knowledge store.

Reads the store read-only, normalizes every finding's free-text `property`,
assigns each normalized string to one class of vocabulary.json (stored manual
assignments in manual.json first, then the ordered rules in rules.py), and
writes:

  map.json                      normalized string -> class, method, assignedBy, findings
  top200.md                     the 200 most frequent strings with their class
  SUMMARY.md                    counts by class, category and kind; coverage; polymer pairs
  check_sample.json             strings for a blind agreement check (no classes)
  findings_by_subject_class.csv polymer x property class finding counts (heatmap input)
  finding_classes.csv           finding id, subject, status, class, method (no text)

Standard library only; no engine calls, no network. Usage:
  python build.py [path/to/knowledge.sqlite]
  python build.py --kf [--out DIR]   # experiment A1: KF's frozen copy, into properties-kf

Ran as `.oopc/study/analysis/properties/build.py`; moved to the repository on 2026-10-13 unchanged except imports
and paths. Its inputs (rules.py, vocabulary.json, manual.json) are tracked beside it; it still writes its outputs to
`.oopc/study/analysis/properties/`, not beside this file.

`--kf` (2026-10-18) reads the frozen copy of KF (`kf.store()`) and the polymer classes of `dataset-kf/coverage.json`,
writes to `.oopc/study/analysis/properties-kf/` (or `--out`), and adds meta.json: KF's pins (`kf.meta`), the strings
neither the rules nor a stored assignment cover, and the strings new since K3's map. A new string is assigned by the
rules or the stored assignments only; one they do not cover stays unclassified (no model call).
"""
import argparse
import collections
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # the tracked inputs: rules.py, vocabulary.json, manual.json
sys.path.insert(0, str(HERE.parents[1]))  # studies/macromolecules, for common
from common import ROOT, analysis_dir, run_dir  # noqa: E402

OUT = analysis_dir("properties")  # the private folder it ran in and writes to
DEFAULT_STORE = run_dir("2026-10-ablation") / "workspaces/K3/.oopc/loop/knowledge.sqlite"
COVERAGE = analysis_dir("dataset") / "coverage.json"  # E2 output: polymer id -> primaryClass
SEED = "oopc-property-check"
STATUS = {"accepted": "Added", "supported": "Reviewed", "uncertain": "Needs checking", "unsupported": "Rejected"}

DECISIONS = [
    "Property versus condition: a string is a material property when it names the measured response of the "
    "material. The temperature, rate, load, humidity, duration, geometry, atmosphere or medium of the measurement are "
    "test conditions even when they are temperatures (HDT is a property, the HDT test stress a condition; the "
    "crystallization half-time is a property, the isothermal crystallization temperature a preparation set point; "
    "DSC melt-hold and thermal-history erasure temperatures are thermal-program conditions).",
    "Processing settings (moulding, extrusion, compounding, printing, curing, annealing, drying, drawing) are "
    "specimen-or-preparation details, not properties, even when they set the specimen's state. Exceptions: maximum or "
    "ultimate draw ratio and melt-spinning feasibility are material properties (processability).",
    "Composition is split: the polymer's own composition (comonomer, vinyl acetate, acrylonitrile or hard-segment "
    "content, degree of substitution, acetyl content, degree of hydrolysis or deacetylation, monomer and reactivity "
    "ratios) is a molecular material property; added components (fillers, plasticizers and oils, cure system, "
    "additives, blend and formulation ratios) are composition-or-formulation.",
    "Intrinsic viscosity, viscosity number and K-value are molecular (molar-mass indices); the viscosity of a "
    "polymer solution at stated concentration (for example cellulose-ether grade viscosity in cP) is solution "
    "behaviour; melt and complex viscosity are rheology.",
    "Unqualified Young's or elastic modulus is filed as tensile modulus; unqualified Izod impact strength as notched "
    "Izod (the ASTM D256 default). Every Charpy strength string states notched or unnotched (a deferral rule for "
    "Charpy without a notch statement never fired).",
    "Glass transition and melting temperatures pool all methods and phases: DSC onset, midpoint and inflection, DMA "
    "tan δ and E'' peaks and E' onset, TMA; soft- and hard-segment Tg; multiple melting peaks, onset and end. The "
    "method is a separate field; DMA tan δ Tg typically lies above DSC Tg, so Fig. 3d should mark method. The "
    "equilibrium melting temperature is its own class.",
    "Oxygen permeability versus OTR and WVP versus WVTR follow the agent's label; units are not normalized and "
    "vary within a class. Six oxygen strings whose own wording flags a mislabel were reassigned by hand.",
    "Elastomer volume or mass change in oils and fuels is volume swell (hardness and elastomer behaviour); equilibrium "
    "swelling of gels and networks in water or solvents is swelling ratio (barrier and transport); swelling-derived "
    "crosslink density and gel or sol fraction are crosslink density.",
    "Changes relative to a reference: after ageing or exposure (heat, UV, oil, water) they are property retention "
    "after ageing (degradation category); after a change in composition or processing (ΔTg with a filler, HDT gain, "
    "percent increase in tensile strength) they go to the category's other class, so value classes such as Tg, HDT "
    "and tensile strength hold absolute values that can be plotted.",
    "Reported statistics (standard deviation, coefficient of variation, experimental error), definitions and "
    "calculation constants (reference enthalpy of a 100% crystalline polymer, solvent molar volume) are analysis "
    "criteria (method-or-instrument kind), not the property they qualify.",
    "HDT, Vicat and service temperature are counted under thermal transitions and thermal properties, as on data "
    "sheets, although they are thermo-mechanical indices; brittleness temperature is under impact and fracture.",
    "TGA quantities are kept apart: onset, temperature at a stated mass loss (a 'T at 2% loss' labelled Tonset goes "
    "to the latter), temperature of maximum rate, residue (char yield) and stage mass loss.",
    "Water: uptake by immersion (24 h, saturation) is water absorption; equilibrium uptake from humid air, moisture "
    "regain and water content are moisture sorption.",
    "A string naming two properties ('dsc glass transition temperature; dsc melting temperature') takes the first. "
    "Grade, supplier and identity strings are kind other and counted neither as properties nor as conditions. The "
    "23 findings with an empty property string are the only unclassified ones.",
]
FILES = [
    ("vocabulary.json", "kinds, categories and classes (id, label, definition, category, kind)"),
    ("rules.py", "normalization, ordered regex rules and the method extractor"),
    ("manual.json", "stored manual assignments; they take precedence over rules"),
    ("build.py", "reads the store read-only and writes everything below"),
    ("map.json", "normalized string -> class, method, assignedBy, findings, withoutAbbreviation, rawVariants"),
    ("top200.md", "the 200 most frequent strings with class, for the owner's skim"),
    ("check_sample.json", "strings for the blind agreement check, without classes"),
    ("findings_by_subject_class.csv", "finding counts per (polymer id, property class), with polymer class"),
    ("finding_classes.csv", "per finding: id, subject, status, class, method in string, method in conditions "
     "(labels only, no text)"),
]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import rules  # noqa: E402
from analysis import kf  # noqa: E402  (KF's pins and frozen copy)


def load_findings(store):
    con = sqlite3.connect(Path(store).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute("select id, property, value, unit, subject, status, conditions from findings order by id").fetchall()
    finally:
        con.close()
    return rows


def assign(strings, manual):
    """class, method and assignedBy for every normalized string."""
    out = {}
    for s in strings:
        if s in manual:
            m = manual[s]
            out[s] = (m["class"], m.get("method", rules.method(s)), "model")
            continue
        cls, _ = rules.classify(s)
        if cls:
            out[s] = (cls, rules.method(s), "rule")
        else:
            out[s] = ("unclassified", rules.method(s), "none")
    return out


def method_group(in_string, in_conditions):
    """DSC, DMA, other or none: a finding's method for the Tg split here and in Fig. 3d, from the methods named in its
    property string and in its conditions (rules.method labels; DSC wins when both are named)."""
    both = (in_string or "") + " " + (in_conditions or "")
    return "DSC" if "DSC" in both else "DMA" if "DMA" in both else "other" if both.strip() else "none"


def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "n/a"


def main(argv):
    global OUT, COVERAGE
    parser = argparse.ArgumentParser(description="Build the E3 property map from a store, read-only.")
    parser.add_argument("store", nargs="?", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--kf", action="store_true", help="read KF's frozen copy and write to properties-kf")
    parser.add_argument("--out", type=Path, help="write the outputs here instead")
    args = parser.parse_args(argv[1:])
    store, name = args.store, "K3"
    if args.kf:
        store, name, OUT = kf.store(), "KF", analysis_dir("properties-kf")
        COVERAGE = analysis_dir("dataset-kf") / "coverage.json"
    OUT = args.out or OUT
    OUT.mkdir(parents=True, exist_ok=True)
    vocab = json.loads((HERE / "vocabulary.json").read_text())
    classes = {c["id"]: c for c in vocab["classes"]}
    cats = {c["id"]: c for c in vocab["categories"]}
    manual = json.loads((HERE / "manual.json").read_text())
    for s, m in manual.items():
        if m["class"] not in classes:
            raise SystemExit("manual.json: unknown class %r for %r" % (m["class"], s))
    for cls, _, _ in rules.R:
        if cls and cls not in classes:
            raise SystemExit("rules.py: unknown class %r" % cls)

    rows = load_findings(store)
    raw_by_norm = collections.defaultdict(set)
    finds = collections.defaultdict(list)
    cond_method = {}
    for fid, prop, value, unit, subject, status, conditions in rows:
        s = rules.normalize(prop)
        raw_by_norm[s].add(prop or "")
        finds[s].append((fid, value or "", unit or "", subject or "", STATUS.get(status, status)))
        cond_method[fid] = rules.method(rules.normalize(conditions))
    strings = sorted(finds, key=lambda s: (-len(finds[s]), s))
    assigned = assign(strings, manual)
    unused_manual = sorted(set(manual) - set(strings))

    # ---- map.json
    mapping = {}
    for s in strings:
        cls, meth, by = assigned[s]
        mapping[s] = {"class": cls, "method": meth, "assignedBy": by, "findings": len(finds[s]),
                      "withoutAbbreviation": rules.strip_abbreviation(s), "rawVariants": len(raw_by_norm[s])}
    (OUT / "map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n")

    # ---- per-finding table and polymer pairs
    polymers = {}
    if COVERAGE.exists():
        cov = json.loads(COVERAGE.read_text())
        polymers = {p["id"]: p for p in cov["polymers"]}
        class_order = cov.get("classOrder", [])
    else:
        class_order = []
    with open(OUT / "finding_classes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["finding_id", "subject", "status", "property_class", "category", "kind", "method",
                    "method_in_conditions"])
        for s in strings:
            cls, meth, _ = assigned[s]
            for fid, _, _, subject, status in finds[s]:
                w.writerow([fid, subject, status, cls, classes[cls]["category"], classes[cls]["kind"], meth or "",
                            cond_method[fid] or ""])
    pair = collections.Counter()
    for s in strings:
        cls = assigned[s][0]
        for _, _, _, subject, _ in finds[s]:
            if subject:
                pair[(subject, cls)] += 1
    with open(OUT / "findings_by_subject_class.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subject", "polymer_label", "polymer_class", "property_class", "category", "kind", "findings"])
        for (subject, cls), n in sorted(pair.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1])):
            p = polymers.get(subject, {})
            w.writerow([subject, p.get("label", ""), p.get("class", ""), cls, classes[cls]["category"],
                        classes[cls]["kind"], n])

    # ---- check_sample.json: strings covering 80% of findings + seeded random 200 of the rest
    total = len(rows)
    cum, head = 0, []
    for s in strings:
        if cum >= 0.8 * total:
            break
        head.append(s)
        cum += len(finds[s])
    rest = sorted(set(strings) - set(head))
    rnd = random.Random(SEED)
    tail = sorted(rnd.sample(rest, min(200, len(rest))), key=lambda s: (-len(finds[s]), s))

    def sample_row(s, stratum):
        units = collections.Counter(u for _, _, u, _, _ in finds[s] if u).most_common(3)
        values = []
        for _, v, _, _, _ in finds[s]:
            v = v.strip()
            if v and v not in values:
                values.append(v[:60])
            if len(values) == 3:
                break
        return {"string": s, "stratum": stratum, "findings": len(finds[s]),
                "units": [u for u, _ in units], "exampleValues": values}

    check = {
        "about": ("Blind agreement check for the E3 property map. Classify each string into one class id of "
                  "vocabulary.json using the string, its units and example values; do not consult map.json. "
                  "Stratum 'head': the most frequent strings, which together cover 80% of findings; "
                  "stratum 'random': a seeded random sample of the remaining strings."),
        "vocabulary": "vocabulary.json",
        "seed": SEED,
        "findingsTotal": total,
        "head": {"strings": len(head), "findings": cum},
        "random": {"strings": len(tail), "of": len(rest), "findings": sum(len(finds[s]) for s in tail)},
        "strings": [sample_row(s, "head") for s in head] + [sample_row(s, "random") for s in tail],
    }
    (OUT / "check_sample.json").write_text(json.dumps(check, ensure_ascii=False, indent=1) + "\n")

    # ---- top200.md
    L = ["# Top 200 property strings and their class", "",
         "The 200 most frequent normalized `property` strings in %s (%d findings, %d strings), with the class "
         "assigned in map.json. `by`: rule = rules.py, model = stored manual assignment. Kind abbreviations: "
         "prop = material property, cond = test condition, spec = specimen or preparation, meth = method or "
         "instrument, comp = composition or formulation." % (name, total, len(strings)), "",
         "| # | findings | string | class | category | kind | method | by |",
         "| ---: | ---: | --- | --- | --- | --- | --- | --- |"]
    KA = {"material-property": "prop", "test-condition": "cond", "specimen-or-preparation": "spec",
          "method-or-instrument": "meth", "composition-or-formulation": "comp", "other": "other"}
    cum200 = 0
    for i, s in enumerate(strings[:200], 1):
        cls, meth, by = assigned[s]
        c = classes[cls]
        cum200 += len(finds[s])
        L.append("| %d | %d | %s | %s | %s | %s | %s | %s |" % (
            i, len(finds[s]), (s or "(empty)").replace("|", "\\|"), cls, c["category"], KA[c["kind"]],
            meth or "", by))
    L += ["", "These 200 strings carry %d findings (%s)." % (cum200, pct(cum200, total))]
    (OUT / "top200.md").write_text("\n".join(L) + "\n")

    # ---- SUMMARY.md
    by_class = collections.Counter()
    str_class = collections.Counter()
    by_by = collections.Counter()
    str_by = collections.Counter()
    for s in strings:
        cls, _, by = assigned[s]
        by_class[cls] += len(finds[s])
        str_class[cls] += 1
        by_by[by] += len(finds[s])
        str_by[by] += 1
    kind_f = collections.Counter()
    kind_s = collections.Counter()
    cat_f = collections.Counter()
    cat_s = collections.Counter()
    cat_classes = collections.defaultdict(set)
    for cls, n in by_class.items():
        c = classes[cls]
        kind_f[c["kind"]] += n
        kind_s[c["kind"]] += str_class[cls]
        cat_f[c["category"]] += n
        cat_s[c["category"]] += str_class[cls]
        cat_classes[c["category"]].add(cls)
    mp = [c for c in classes.values() if c["kind"] == "material-property"]
    mp_counts = sorted(((by_class[c["id"]], c["id"]) for c in mp), reverse=True)
    n1 = sum(1 for n, _ in mp_counts if n >= 1)
    n10 = sum(1 for n, _ in mp_counts if n >= 10)
    n50 = sum(1 for n, _ in mp_counts if n >= 50)
    mp_ids = {c["id"] for c in mp}
    pairs_all = len(pair)
    pairs_mp = sum(1 for (subj, cls) in pair if cls in mp_ids)
    poly_mp = {subj for (subj, cls) in pair if cls in mp_ids}
    mp_findings_with_subject = sum(n for (subj, cls), n in pair.items() if cls in mp_ids)
    n_bases = len({rules.strip_abbreviation(s) for s in strings})
    n_raw = len({p for v in raw_by_norm.values() for p in v})
    unclassified = [s for s in strings if assigned[s][0] == "unclassified"]
    meth_f = collections.Counter()
    for s in strings:
        m = assigned[s][1]
        if m:
            for part in m.split("; "):
                meth_f[part] += len(finds[s])
    tg_meth = collections.Counter()
    tm_meth = collections.Counter()
    tg_any = collections.Counter()
    for s in strings:
        cls, m, _ = assigned[s]
        if cls == "glass-transition-temperature":
            tg_meth[m or "(none in string)"] += len(finds[s])
            for f in finds[s]:
                tg_any[method_group(m, cond_method[f[0]])] += 1
        if cls == "melting-temperature":
            tm_meth[m or "(none in string)"] += len(finds[s])

    S = []
    w = S.append
    w("# E3 property map: summary")
    w("")
    w("Built by `build.py` from the frozen %s store (`%s`, opened read-only). Study analysis table, not ontology "
      "vocabulary. Inputs: `vocabulary.json` (classes), `rules.py` (normalization, ordered rules, method field), "
      "`manual.json` (stored manual assignments, which take precedence over rules)." % (name, store.relative_to(ROOT))
      if store.is_relative_to(ROOT) else "Built by `build.py` from `%s`." % store)
    w("")
    w("## Strings")
    w("")
    w("| | count |")
    w("| --- | ---: |")
    w("| findings | %d |" % total)
    w("| distinct raw `property` strings | %d |" % n_raw)
    w("| distinct normalized strings (NFKC, lowercase, dashes, quotes, whitespace) | %d |" % len(strings))
    w("| distinct normalized strings without the parenthesized abbreviation | %d |" % n_bases)
    w("| findings with an empty `property` | %d |" % len(finds.get("", [])))
    w("")
    w("## Vocabulary")
    w("")
    w("%d classes in %d categories: %d material-property classes in %d categories, and %d classes for test "
      "conditions, specimen and preparation, method and instrument, composition and formulation, and other." % (
          len(classes), len(cats), len(mp), sum(1 for c in cats.values() if c["kind"] == "material-property"),
          len(classes) - len(mp)))
    w("")
    w("## How strings were assigned")
    w("")
    w("| assigned by | strings | share of strings | findings | share of findings |")
    w("| --- | ---: | ---: | ---: | ---: |")
    for by in ("rule", "model", "none"):
        if str_by[by] or by != "none":
            w("| %s | %d | %s | %d | %s |" % (by, str_by[by], pct(str_by[by], len(strings)), by_by[by],
                                              pct(by_by[by], total)))
    w("")
    w("`rule`: first matching rule in `rules.py`. `model`: assigned by hand by the analysing session (Claude) after "
      "reading the string with sample values, units and, where needed, the finding statements; this includes %d "
      "strings the rules deliberately defer (changes, statistics, dependences) or do not match, and overrides of "
      "rule errors found while reviewing every rule-assigned string class by class." % str_by["model"])
    w("")
    w("## Findings by kind")
    w("")
    w("| kind | findings | share | strings |")
    w("| --- | ---: | ---: | ---: |")
    for k in vocab["kinds"]:
        w("| %s | %d | %s | %d |" % (k, kind_f[k], pct(kind_f[k], total), kind_s[k]))
    w("")
    w("Material properties: %d findings (%s); test conditions, specimen and preparation details, methods and "
      "instruments, and composition or formulation together: %d findings (%s)." % (
          kind_f["material-property"], pct(kind_f["material-property"], total),
          total - kind_f["material-property"] - kind_f["other"],
          pct(total - kind_f["material-property"] - kind_f["other"], total)))
    w("")
    w("## Material-property categories")
    w("")
    w("| category | findings | strings | classes with ≥1 finding | classes with ≥10 |")
    w("| --- | ---: | ---: | ---: | ---: |")
    for cid, c in sorted(((k, v) for k, v in cats.items() if v["kind"] == "material-property"),
                         key=lambda kv: -cat_f[kv[0]]):
        used = [x for x in cat_classes[cid] if by_class[x] > 0]
        w("| %s | %d | %d | %d | %d |" % (c["label"], cat_f[cid], cat_s[cid], len(used),
                                          sum(1 for x in used if by_class[x] >= 10)))
    w("")
    w("## Non-property categories")
    w("")
    w("| category | findings | strings |")
    w("| --- | ---: | ---: |")
    for cid, c in sorted(((k, v) for k, v in cats.items() if v["kind"] != "material-property"),
                         key=lambda kv: -cat_f[kv[0]]):
        w("| %s | %d | %d |" % (c["label"], cat_f[cid], cat_s[cid]))
    w("")
    w("## Number of properties")
    w("")
    w("Distinct material-property classes with at least 1 finding: **%d**; at least 10: **%d**; at least 50: "
      "**%d** (of %d material-property classes in the vocabulary)." % (n1, n10, n50, len(mp)))
    w("")
    w("(polymer id, property class) pairs with at least one finding: **%d** over all classes; **%d** for "
      "material-property classes, covering %d polymers and %d findings with a polymer id." % (
          pairs_all, pairs_mp, len(poly_mp), mp_findings_with_subject))
    w("")
    if polymers:
        w("### Polymer class × property category (material-property findings with a polymer id)")
        w("")
        mp_cats = [k for k, v in sorted(cats.items(), key=lambda kv: -cat_f[kv[0]]) if v["kind"] == "material-property"
                   and cat_f[k] > 0]
        grid = collections.Counter()
        for (subj, cls), n in pair.items():
            if cls in mp_ids:
                grid[(polymers.get(subj, {}).get("class") or "(not in graph)", classes[cls]["category"])] += n
        pcs = [c for c in class_order if any(grid[(c, k)] for k in mp_cats)]
        w("| polymer class | " + " | ".join(cats[k]["label"] for k in mp_cats) + " |")
        w("| --- |" + " ---: |" * len(mp_cats))
        for pc in pcs:
            w("| %s | " % pc + " | ".join(str(grid[(pc, k)]) for k in mp_cats) + " |")
        w("")
        w("Polymer class is the graph's `primaryClass` facet, read from the E2 output `dataset/coverage.json`. "
          "Per-polymer counts are in `findings_by_subject_class.csv`.")
        w("")
    w("## Classes")
    w("")
    w("| class | category | kind | findings | strings |")
    w("| --- | --- | --- | ---: | ---: |")
    for cls, n in sorted(by_class.items(), key=lambda kv: (-kv[1], kv[0])):
        c = classes[cls]
        w("| %s | %s | %s | %d | %d |" % (cls, c["category"], c["kind"], n, str_class[cls]))
    unused = sorted(c for c in classes if by_class[c] == 0)
    w("")
    w("Vocabulary classes with no finding (%d): %s." % (len(unused), ", ".join(unused) or "none"))
    w("")
    w("## Method field")
    w("")
    w("A method or standard is recorded when the string names one (DSC, DMA, TGA, WAXD/XRD, ASTM D256, ...); "
      "the map's method field reads the string only. Findings whose string names a method: %d (%s)." % (
          sum(len(finds[s]) for s in strings if assigned[s][1]), pct(sum(len(finds[s]) for s in strings
                                                                          if assigned[s][1]), total)))
    w("")
    w("| method | findings |")
    w("| --- | ---: |")
    for m, n in meth_f.most_common(15):
        w("| %s | %d |" % (m, n))
    w("")
    w("Glass transition temperature findings by method in the string: " +
      ", ".join("%s %d" % (m, n) for m, n in tg_meth.most_common()) + ".")
    w("Counting also methods named in the finding's `conditions` (column `method_in_conditions` of "
      "`finding_classes.csv`, method labels only), glass transition findings split DSC %d, DMA %d (no DSC), other "
      "method %d, none %d." % (tg_any["DSC"], tg_any["DMA"], tg_any["other"], tg_any["none"]))
    w("Melting temperature findings by method in the string: " +
      ", ".join("%s %d" % (m, n) for m, n in tm_meth.most_common()) + ".")
    w("")
    w("## Unclassified")
    w("")
    nunc = sum(len(finds[s]) for s in unclassified)
    w("%d strings, %d findings (%s of findings): %s." % (
        len(unclassified), nunc, pct(nunc, total),
        ", ".join("`%s` (%d)" % (s or "(empty)", len(finds[s])) for s in unclassified) or "none"))
    if unused_manual:
        w("")
        w("Manual assignments not matching any current string (%d): %s." % (
            len(unused_manual), ", ".join("`%s`" % s for s in unused_manual)))
    w("")
    w("## Blind check sample")
    w("")
    w("`check_sample.json`: %d head strings covering %d findings (%s) and %d strings drawn with seed `%s` from the "
      "remaining %d; classes are withheld." % (len(head), cum, pct(cum, total), len(tail), SEED, len(rest)))
    w("")
    w("## Decisions a polymer chemist might question")
    w("")
    for i, d in enumerate(DECISIONS, 1):
        w("%d. %s" % (i, d))
    w("")
    w("## Files")
    w("")
    for f, d in FILES:
        w("- `%s`: %s" % (f, d))
    w("")
    (OUT / "SUMMARY.md").write_text("\n".join(S) + "\n")
    if args.kf:  # the pins, and what neither the rules nor a stored assignment covers
        previous = analysis_dir("properties") / "map.json"  # K3's map, as built on 2026-10-13
        before = json.loads(previous.read_text()) if previous.exists() else None
        new = [s for s in strings if before is not None and s not in before]

        def count(group):
            return {"strings": len(group), "findings": sum(len(finds[s]) for s in group)}
        (OUT / "meta.json").write_text(json.dumps({
            "meta": kf.meta("properties/build.py"),
            "unassigned": dict(count(unclassified), nonEmpty=count([s for s in unclassified if s])),
            "newSinceK3": before and dict(count(new), **{by: count([s for s in new if assigned[s][2] == by])
                                                         for by in ("rule", "model", "none")}),
        }, ensure_ascii=False, indent=1) + "\n")
    print("strings %d, findings %d, rule %d/%d, model %d/%d, unclassified %d/%d" % (
        len(strings), total, str_by["rule"], by_by["rule"], str_by["model"], by_by["model"],
        len(unclassified), nunc))


if __name__ == "__main__":
    main(sys.argv)
