#!/usr/bin/env python3
"""Strategy 3 of the structure estimates (`docs/exec-plans/active/structure-estimates-plan.md`): what a normalized
property class and a numeric value in a canonical unit on each saved finding could gain. Offline, from records already
collected; the only engine calls are the blind relevance judgements of step 3.

Inputs, read only: KF through its frozen copy (`analysis/kf.py`; sqlite opened `?mode=ro`, the seed graph release it
links), A1's property map of KF (`pins.PROPERTY_MAP`) and vocabulary (`analysis/properties/vocabulary.json`), Part C's
withheld questions (`questions/H.json`, `N.json`, `L.json`), lookup records (`lookup/searches/`, `lookup/judge/`), the
derivation pool's late finds (`mine/misses.json`, `mine/answers.jsonl`) and the screen's B answers (their store
calls, `lookup.issued`). Writes only under `ROOT/.oopc/study/analysis/structure/classes/` (private).

**1. How much of KF can be structured** (`structure`). Every finding not rejected (unsupported) gets the class A1's map
gives its property string (`rules.normalize`; a string the map lacks goes to A1's ordered rules), and that class's kind
(material property, test condition, specimen or preparation, method or instrument, composition, other). Its value is
parsed (`parse_value`): a number, a number with an uncertainty (`a ± b`, also `(a ± b) × 10ⁿ`), a range (`a–b`, `a to
b`; reversed ranges ordered), or an approximate number (`~`, `about`, `ca.`) is **numeric**; a bound (`>`, `less
than`), a list (`a; b`, `50 × 50 × 2`), words and empty values are not. Ranges and uncertainties are kept as intervals.
A unit is **normalizable** when `oopc.units.get_unit` knows it after NFKC and trimming (a unit written at the end of the
value, when the unit field is empty or repeats it, counts as the unit). Reported for all findings and for the
material-property kind, with the units that would add most if the profile grew.

**2. A class-based first search** (`class_search`), for each withheld question: one call per asked polymer (each
material the seed graph resolves, then the question's other polymer ids together; `oracle=False` uses the materials
alone), returning KF findings whose subject is in that polymer's lineage on the seed graph (`knowledge.lineage`) and
whose class is one of the asked classes; ranked reviewed > added > needs checking, then filed under the asked polymer
itself before its families or members, then saved order. Variants (VARIANTS): the first 10 (`limit`, as today's
default) or all of them; alone, with the same-source findings today's search adds (`+source`: up to 12 per call, from
the returned findings' sources in order; `knowledge.SAME_SOURCE`), or with every finding of those sources
(`+allsource`: a value carrying its own conditions, method and specimen). The asked classes come two ways: `curated`
(L's own `propertyClass`; for H and N the classes in QUESTION_CLASSES, written from the vocabulary before any result
was computed, as a researcher picking classes would) and `rules` (A1's map and rules on the property wording, part by
part, `mine.Properties`). The class search is also measured added to today's first search (COMBINED).

**3. Recall** against the blind judge. The judge's pool is everything Part C's searches returned (`lookup.pool`); its
verdicts stay where they are. Class-search findings outside that pool are judged blind by exactly Part C's procedure
(`lookup.judge_question`: the same prompt, schema, shuffle seed and one Codex session per question, judging only
findings not judged before), with `lookup.folder` pointed at this folder's `lookup/`, never at Part C's. Recall is
reported against Part C's relevant findings alone (as Part C measured, 0.76 first search, 0.90 all searches), and
against the grown pool (Part C's relevant plus newly judged relevant), where today's searches are measured again; and
as bounds (unjudged findings all irrelevant, all relevant). The relevant findings a search misses are sorted by why a
class search misses them (`missed`).

**4. Late finds** (`late_finds`): of the pool's late finds (`mine/misses.json`), those a class-based first search for
the answer's question (its materials' polymers on the seed graph, its recorded property or topic mapped by `rules`)
returns, with why the others are not returned (no subject or outside the lineage; another class; past the first ten).
Pool answers carry no curated classes, so their classes are the rules'.
A lenient reading counts a late find as reachable when it is in the lineage and on the question's property by mining's
own test (`Miner.on_property`), whatever class the rules give the question. **Later searches** (`later_searches`): the
screen B answers' store calls after the first whose returned findings (as Part C replayed them on KF, `lookup/searches`)
a class-based first search had all returned already; also counting only the judged-relevant ones, beside the answer's
own first call.

**5. Tables** (`tables`): N's comparison questions and L's value questions answerable from saved values alone (every
asked polymer has a class-matched finding in its lineage that is numeric with a normalizable unit, in one dimension
across the polymers; also with any unit when the polymers share it, and filed under the asked polymer itself); and,
over KF's material-property findings, (polymer, class) pairs with two or more normalized values whose intervals,
widened by the tolerance (TOLERANCE: 10% relative, 5 K for temperatures; and a loose 50%, 20 K), do not overlap.

**6. Predictions** (plan, "Predictions", 3): each checked, met or not.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<.oopc/study/freeze-3> OOPC_STUDY_CODEX_FLOOR=0 \\
        python -B studies/macromolecules/structure/classes.py judge [--limit-calls N] [--hours H]
    ... python -B studies/macromolecules/structure/classes.py report
"""
import argparse, collections, json, re, sqlite3, statistics, sys, time, unicodedata
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from analysis import kf  # noqa: E402
from analysis.properties import rules  # noqa: E402
from refinement import lookup, mine, pins, questions  # noqa: E402
from oopc import knowledge, units  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, now, read_json  # noqa: E402

OUT = common.analysis_dir("structure") / "classes"
VOCABULARY = common.STUDY / "analysis/properties/vocabulary.json"
LIMIT, SAME_SOURCE = lookup.LIMIT, knowledge.SAME_SOURCE  # today's default limit and same-source cap
STATUS_RANK = {knowledge.SUPPORTED: 0, knowledge.ACCEPTED: 1}  # then needs checking (unreviewed, uncertain)
VARIANTS = {"first10": (LIMIT, 0), "first10+source": (LIMIT, SAME_SOURCE), "first10+allsource": (LIMIT, None),
            "all": (None, 0), "all+source": (None, SAME_SOURCE), "all+allsource": (None, None)}
MAPPINGS = ("curated", "rules")
COMBINED = ("curated/first10", "curated/first10+source")  # also measured added to today's first search
TOLERANCE = {"stated": (0.10, 5.0), "loose": (0.50, 20.0)}  # (relative, kelvin for temperatures)
PREDICTION = {"classShare": 0.80, "numericNormalizableShare": 0.60, "recall": 0.85, "lateAvoided": 1 / 3}

TGA = ("decomposition-onset-temperature", "decomposition-temperature-at-mass-loss",
       "max-decomposition-rate-temperature", "char-yield", "thermal-mass-loss", "thermal-degradation-other")
DECOMPOSITION = TGA[:3]
TENSILE = ("tensile-strength", "tensile-yield-strength", "tensile-modulus", "elongation-at-break")
NOTCHED = ("notched-izod-impact", "notched-charpy-impact", "impact-strength-other")
# The classes a researcher would pick for each H and N property wording, written from the vocabulary before any result
# of this module was computed (L questions carry their own `propertyClass`). Conditions, methods and specimens are not
# picked: the same-source findings bring them, as today's search does.
QUESTION_CLASSES = {
    "swelling ratio of a crosslinked gel": ("swelling-ratio",),
    "melting and crystallization temperatures": ("melting-temperature", "crystallization-temperature"),
    "cloud point in water": ("cloud-point-lcst",),
    "volume swell in oil or fuel": ("volume-swell",),
    "volume swell in fuel": ("volume-swell",),
    "volume swell in oil or a solvent": ("volume-swell",),
    "notched impact strength": NOTCHED,
    "glass transition temperature (Tg)": ("glass-transition-temperature",),
    "glass transition temperature": ("glass-transition-temperature",),
    "glass transition temperature by DMA": ("glass-transition-temperature",),
    "solution viscosity or thermal gelation temperature": ("solution-viscosity", "gelation-temperature"),
    "solution viscosity at a stated concentration": ("solution-viscosity",),
    "intrinsic viscosity or solution viscosity": ("intrinsic-viscosity", "solution-viscosity"),
    "thermal degradation by TGA": TGA,
    "thermal stability by TGA": TGA,
    "thermal stability": TGA,
    "thermal decomposition temperature by TGA": DECOMPOSITION,
    "thermal decomposition temperature": DECOMPOSITION,
    "tensile properties of hydrated membranes": TENSILE,
    "tensile properties of cast films": TENSILE,
    "tensile properties of films": TENSILE,
    "oxygen permeability": ("oxygen-permeability", "oxygen-transmission-rate"),
    "solubility or water uptake as a function of degree of substitution": ("solubility", "water-absorption",
                                                                           "moisture-sorption"),
    "tensile modulus and yield strength": ("tensile-modulus", "tensile-yield-strength"),
    "tensile modulus and tensile strength": ("tensile-modulus", "tensile-strength"),
    "tensile strength and elongation at break": ("tensile-strength", "elongation-at-break"),
    "tensile strength": ("tensile-strength",),
    "tensile strength of regenerated films": ("tensile-strength",),
    "tensile strength of vulcanizates": ("tensile-strength",),
    "elongation at break": ("elongation-at-break",),
    "tensile elongation at break": ("elongation-at-break",),
    "flexural modulus and strength": ("flexural-modulus", "flexural-strength"),
    "Shore A hardness of a vulcanizate": ("shore-a-hardness",),
    "Shore A hardness and tensile strength": ("shore-a-hardness", "tensile-strength"),
    "Shore hardness": ("shore-a-hardness", "shore-d-hardness", "hardness-other"),
    "water uptake": ("water-absorption", "moisture-sorption"),
    "water absorption": ("water-absorption",),
    "water absorption at saturation": ("water-absorption",),
    "water uptake and dimensional swelling": ("water-absorption", "moisture-sorption", "dimensional-stability",
                                              "swelling-ratio"),
    "dielectric constant and loss": ("dielectric-constant", "dielectric-loss"),
    "degree of crystallinity from DSC or WAXD": ("degree-of-crystallinity",),
    "glass transition and melting temperatures by DSC": ("glass-transition-temperature", "melting-temperature"),
    "glass transition and melting temperatures (Tg, Tm) by DSC": ("glass-transition-temperature",
                                                                  "melting-temperature"),
    "melting temperature and crystallinity by DSC": ("melting-temperature", "degree-of-crystallinity"),
    "melting temperature and crystallinity": ("melting-temperature", "degree-of-crystallinity"),
    "melting temperature": ("melting-temperature",),
    "melting or order-disorder transition of the hard phase": ("melting-temperature", "other-transition-temperature"),
    "fracture toughness (KIC or GIC)": ("fracture-toughness",),
    "methanol or gas crossover": ("gas-permeability-other", "membrane-separation", "barrier-other"),
    "water-vapor or gas permeability": ("water-vapor-permeability", "water-vapor-transmission-rate",
                                        "oxygen-permeability", "oxygen-transmission-rate", "co2-permeability",
                                        "gas-permeability-other"),
    "heat deflection temperature": ("heat-deflection-temperature",),
    "melt flow rate or melt viscosity": ("melt-flow-rate", "melt-viscosity"),
    "cure kinetics (activation energy) by DSC": ("cure-kinetics",),
    "creep or stress relaxation": ("creep-stress-relaxation",),
    "optical absorption or band gap": ("optical-absorption-emission", "electronic-structure"),
    "thermal conductivity": ("thermal-conductivity",),
    "crosslink density by equilibrium swelling": ("crosslink-density",),
    "tensile strength retained after heat aging": ("property-retention-after-aging",),
    "electrical conductivity of films": ("electrical-conductivity",),
    "Seebeck coefficient": ("thermoelectric",),
    "biodegradation in compost or soil": ("biodegradation",),
}


# ----- values and units -----

SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[-+]?\.\d+"
EXP = r"(?:\s*[eE]\s*[-+]?\d+|\s*[×x*·]\s*10\s*\^?\s*[-+]?\d+)"
SCI = r"(?:%s)%s?" % (NUM, EXP)
APPROX = r"(?:~|≈|∼|about|approx\.?|approximately|ca\.?|circa|around|nearly|roughly)"
BOUND = (r"(?:<=|>=|<|>|≤|≥|≲|≳|less than|more than|greater than|lower than|higher than|over|above|below|under|"
         r"up to|at least|at most|exceeds?|exceeding|not less than|not more than)")
PM = r"(?:±|\+/-|\+-)"
PATTERNS = (
    ("point", re.compile(r"(%s)" % SCI)),
    ("approx", re.compile(r"%s\s*(%s)" % (APPROX, SCI), re.I)),
    ("uncertainty", re.compile(r"(?:%s\s*)?\(?\s*(%s)\s*%s\s*(%s)\s*\)?(%s)?" % (APPROX, NUM, PM, NUM, EXP), re.I)),
    ("uncertainty", re.compile(r"(?:%s\s*)?(%s)\s*%s\s*(%s)" % (APPROX, SCI, PM, SCI), re.I)),
    ("uncertainty", re.compile(r"(%s)\s*\(\s*(?:sd|s\.d\.|std|iqr|%s)?\s*:?\s*(%s)\s*\)" % (SCI, PM, NUM), re.I)),
    ("range", re.compile(r"between\s+(%s)\s+and\s+(%s)" % (SCI, SCI), re.I)),
    ("range", re.compile(r"(?:from\s+)?(%s)\s*(?:–|—|‒|-|to|~)\s*(%s)" % (SCI, SCI), re.I)),
    ("bound", re.compile(r"%s\s*(%s)" % (BOUND, SCI), re.I)),
)
NUMERIC = ("point", "approx", "uncertainty", "range")


def _clean(text):
    text = unicodedata.normalize("NFKC", text or "").translate(SUPERSCRIPTS)
    return re.sub(r"\s+", " ", text.replace("−", "-").replace(" ", " ")).strip()


def _number(text):
    """A number written as NUM with an optional exponent (`1.2e-3`, `1.2 × 10-3`, `1,200`)."""
    text = text.replace(" ", "")
    match = re.fullmatch(r"(%s)(?:[eE]([-+]?\d+)|[×x*·]10\^?([-+]?\d+))?" % NUM, text)
    base = float(match.group(1).replace(",", ""))
    power = match.group(2) or match.group(3)
    return base * 10 ** int(power) if power else base


def unit_of(unit):
    """The registered unit `oopc.units` gives a unit string (after NFKC and trimming), or None."""
    return units.get_unit(unicodedata.normalize("NFKC", unit or "").strip())


def parse_value(value, unit=""):
    """A finding's value as {kind, low, high, center, unit}: kind is one of NUMERIC, "bound", "list", "text" or
    "empty"; low/high/center are numbers for NUMERIC kinds (an interval for a range or an uncertainty); `unit` is the
    unit string it is in (the unit field, or a unit written after the number when the field is empty or repeats it)."""
    raw, unit = _clean(value), (unit or "").strip()
    if not raw:
        return {"kind": "empty", "unit": unit}
    text, written = raw, unit
    cleaned = _clean(unit)
    if cleaned and text.endswith(cleaned) and len(text) > len(cleaned):
        text = text[:-len(cleaned)].strip()
    elif not cleaned:
        tail = re.fullmatch(r"(.*?\d\)?)\s*([^\d\s][^\d]{0,11})", text)
        if tail and unit_of(tail.group(2)):
            text, written = tail.group(1).strip(), tail.group(2).strip()
    for kind, pattern in PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        if kind in ("point", "approx"):
            x = _number(match.group(1))
            return {"kind": kind, "low": x, "high": x, "center": x, "unit": written}
        if kind == "uncertainty":
            a, b = _number(match.group(1)), abs(_number(match.group(2)))
            if len(match.groups()) == 3 and match.group(3):
                scale = _number("1" + match.group(3))
                a, b = a * scale, b * scale
            return {"kind": kind, "low": a - b, "high": a + b, "center": a, "unit": written}
        if kind == "range":
            a, b = sorted((_number(match.group(1)), _number(match.group(2))))
            return {"kind": kind, "low": a, "high": b, "center": (a + b) / 2, "unit": written}
        return {"kind": "bound", "unit": written}
    if re.search(r"\d\s*(?:[;,]|\band\b)\s*[-+(]?\d", text) or re.search(r"\d\s*[×x]\s*\d", text):
        return {"kind": "list", "unit": written}
    return {"kind": "text", "unit": written}


def normalized(parsed):
    """A numeric parsed value in its dimension's SI unit ({dimension, low, high, iri}), or None when the value is not
    numeric or `oopc.units` cannot normalize its unit."""
    unit = unit_of(parsed.get("unit")) if parsed["kind"] in NUMERIC else None
    if unit is None:
        return None
    si = lambda x: x * unit.multiplier + unit.offset  # noqa: E731
    return {"dimension": unit.dimension, "low": si(parsed["low"]), "high": si(parsed["high"]), "iri": unit.iri}


# ----- the store, read only -----

class Index:
    """KF's findings not rejected, each with its class, the class's kind, its source key, its parsed and normalized
    value, by subject."""

    def __init__(self, database, property_map, vocabulary):
        self.vocabulary = vocabulary
        self.kinds = {c["id"]: c["kind"] for c in vocabulary["classes"]}
        self.labels = {c["id"]: c["label"] for c in vocabulary["classes"]}
        db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute("SELECT rowid AS position, id, statement, material, property, value, unit, subject, "
                              "status, source_doi, source_url FROM findings WHERE status != ? ORDER BY rowid",
                              (knowledge.UNSUPPORTED,)).fetchall()
        finally:
            db.close()
        self.findings = {}
        self.by_subject, self.by_source = collections.defaultdict(list), collections.defaultdict(list)
        for row in rows:
            f = dict(row)
            f["class"] = finding_class(f["property"], property_map)
            f["assignedBy"] = (property_map.get(rules.normalize(f["property"] or "")) or {}).get("assignedBy", "none")
            f["rulesClass"] = rules.classify(rules.normalize(f["property"] or ""))[0] if f["property"] else None
            f["kind"] = self.kinds.get(f["class"], "other")
            f["key"] = knowledge.source_key(f["source_doi"], f["source_url"])
            f["parsed"] = parse_value(f["value"], f["unit"])
            f["normalized"] = normalized(f["parsed"])
            self.findings[f["id"]] = f
            if f["subject"]:
                self.by_subject[f["subject"]].append(f["id"])
            if f["key"]:
                self.by_source[f["key"]].append(f["id"])


def finding_class(text, property_map):
    """A1's class for a property string: its map entry, else the first of A1's rules that classes it, else
    "unclassified"."""
    key = rules.normalize(text or "")
    entry = property_map.get(key)
    if entry:
        return entry["class"]
    return rules.classify(key)[0] or "unclassified" if key else "unclassified"


def kf_root():
    """KF's frozen copy (checked by its fingerprint), whose graph release is the seed."""
    return kf.store().parents[2]


def index(root=None):
    root = Path(root or kf_root())
    return Index(knowledge.database(root), read_json(pins.PROPERTY_MAP), read_json(VOCABULARY))


# ----- a class-based first search -----

def asked_groups(question, root, oracle=True):
    """The asked polymers, one search each: each material the graph resolves (its ids), then (`oracle`) the
    question's other polymer ids together."""
    groups, claimed = [], set()
    for material in question.get("materials") or []:
        ids = questions.resolved(str(root), material)
        if ids and not ids <= claimed:
            groups.append(sorted(ids))
            claimed |= ids
    rest = sorted(set(question.get("polymerIds") or []) - claimed) if oracle else []
    return groups + ([rest] if rest else [])


def asked_classes(question, mapping, props):
    """The asked classes: `curated` (L's own class, else QUESTION_CLASSES) or `rules` (A1's map and rules)."""
    if mapping == "curated":
        if question.get("propertyClass"):
            return (question["propertyClass"],)
        return QUESTION_CLASSES[question["property"]]
    return tuple(sorted(props.classes(question["property"])))


def class_rows(idx, family, wanted):
    """The findings filed under the polymers `family` whose class is in `wanted`."""
    return [idx.findings[i] for s in family for i in idx.by_subject.get(s, ()) if idx.findings[i]["class"] in wanted]


def class_search(idx, root, groups, classes, limit=LIMIT, same=SAME_SOURCE, lineage=None):
    """The findings a class-based first search returns, in order: per asked polymer group, the findings filed in its
    lineage with one of `classes` (reviewed, added, needs checking; the asked polymer itself first; saved order), the
    first `limit` (None: all), then up to `same` other findings from their sources (None: all). One call per group, as
    today's canonical query is one per material."""
    lineage = lineage or (lambda ids: knowledge.lineage(str(root), set(ids)))
    wanted, found = set(classes), []
    for ids in groups:
        family = lineage(ids)
        rows = class_rows(idx, family, wanted)
        rows.sort(key=lambda f: (STATUS_RANK.get(f["status"], 2), f["subject"] not in ids, f["position"]))
        rows = rows[:limit] if limit is not None else rows
        got = [f["id"] for f in rows]
        extra, seen = [], set(got)
        for key in dict.fromkeys(f["key"] for f in rows if f["key"]):
            for other in idx.by_source[key]:
                if other not in seen:
                    seen.add(other)
                    extra.append(other)
        found += got + (extra if same is None else extra[:same])
    return list(dict.fromkeys(found))


# ----- step 1: how much can be structured -----

def share(n, d):
    return n / d if d else None


def structure(idx, top_units=20):
    """Step 1: classes, kinds, numeric values and normalizable units over KF's findings not rejected."""
    findings = list(idx.findings.values())
    mp = [f for f in findings if f["kind"] == "material-property"]

    def counts(rows):
        kinds = collections.Counter(f["parsed"]["kind"] for f in rows)
        numeric = [f for f in rows if f["parsed"]["kind"] in NUMERIC]
        normal = [f for f in numeric if f["normalized"]]
        return {"findings": len(rows), "classed": sum(f["class"] != "unclassified" for f in rows),
                "classShare": share(sum(f["class"] != "unclassified" for f in rows), len(rows)),
                "valueKinds": dict(kinds), "numeric": len(numeric), "numericShare": share(len(numeric), len(rows)),
                "numericEmptyUnit": sum(not (f["parsed"]["unit"] or "").strip() for f in numeric),
                "normalizable": len(normal), "normalizableShare": share(len(normal), len(rows)),
                "normalizableOfNumeric": share(len(normal), len(numeric))}

    used = collections.Counter(f["class"] for f in findings)
    mp_classes = [c for c in idx.vocabulary["classes"] if c["kind"] == "material-property"]
    missing = collections.Counter(unicodedata.normalize("NFKC", f["parsed"]["unit"] or "").strip() or "(none)"
                                  for f in mp if f["parsed"]["kind"] in NUMERIC and not f["normalized"])
    gained, running = [], 0
    for unit, n in missing.most_common(top_units):
        running += n
        gained.append({"unit": unit, "findings": n, "cumulativeShareOfMaterialProperty": share(
            sum(1 for f in mp if f["normalized"]) + running, len(mp))})
    per_class = []
    for cls, n in used.most_common():
        if idx.kinds.get(cls) != "material-property":
            continue
        rows = [f for f in mp if f["class"] == cls]
        per_class.append({"class": cls, "findings": n, "numeric": sum(f["parsed"]["kind"] in NUMERIC for f in rows),
                          "normalizable": sum(bool(f["normalized"]) for f in rows),
                          "topUnit": collections.Counter((f["parsed"]["unit"] or "").strip() for f in rows
                                                         ).most_common(1)[0][0]})
    ruled = [f for f in findings if f["rulesClass"]]
    return {"all": counts(findings), "materialProperty": counts(mp),
            "assignedBy": dict(collections.Counter(f["assignedBy"] for f in findings)),
            "rulesAlone": {"classed": len(ruled), "share": share(len(ruled), len(findings)),
                           "agreeWithMap": sum(f["rulesClass"] == f["class"] for f in ruled),
                           "agreeShare": share(sum(f["rulesClass"] == f["class"] for f in ruled), len(ruled)),
                           "agreeShareOfAll": share(sum(f["rulesClass"] == f["class"] for f in ruled), len(findings))},
            "byKind": dict(collections.Counter(f["kind"] for f in findings)),
            "classesWithFindings": {"materialProperty": sum(1 for c in mp_classes if used[c["id"]]),
                                    "materialPropertyInVocabulary": len(mp_classes),
                                    "any": sum(1 for c in used if c != "unclassified"),
                                    "vocabulary": len(idx.vocabulary["classes"])},
            "unclassified": used.get("unclassified", 0), "unitsToAdd": gained, "perClass": per_class}


# ----- steps 2 and 3: recall -----

def part_c(folder=None):
    """Part C's lookup folder (read only)."""
    return Path(folder or pins.FOLDERS["lookup"])


@contextmanager
def lookup_folder(folder, make=True):
    """`lookup`'s functions reading and writing `folder` instead of Part C's. (Not `unittest.mock`: importing unittest
    turns the host engines off, `engines.host_engines_allowed`.)"""
    folder = Path(folder)
    if make:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = lookup.folder
    lookup.folder = lambda: folder
    try:
        yield folder
    finally:
        lookup.folder = saved


def verdicts_in(folder, question_id):
    with lookup_folder(folder, make=False):
        return lookup.verdicts(question_id)


def todays(stored):
    """What today's searches returned on B (KF, seed graph), as Part C replayed them: the first search (the canonical
    queries) and all searches (canonical and issued)."""
    first = [i for s in stored["queries"] if "canonical" in s["origins"] for i in s["returned"]["B"]]
    every = [i for s in stored["queries"] for i in s["returned"]["B"]]
    return {"first": list(dict.fromkeys(first)), "all": list(dict.fromkeys(every))}


def searches_of(idx, root, question, props, oracle=True):
    """Every class-based search of a question: by mapping and variant, the ids returned."""
    groups = asked_groups(question, root, oracle)
    value = {}
    for mapping in MAPPINGS:
        classes = asked_classes(question, mapping, props)
        for name, (limit, same) in VARIANTS.items():
            value["%s/%s" % (mapping, name)] = class_search(idx, root, groups, classes, limit, same) if classes else []
    return {"groups": groups, "classes": {m: list(asked_classes(question, m, props)) for m in MAPPINGS},
            "returned": value}


def every_search(idx, root, question, props):
    """Every class search of a question, with and without the question's polymer ids: label -> ids."""
    plain = searches_of(idx, root, question, props, oracle=False)["returned"]
    return {**searches_of(idx, root, question, props)["returned"], **{k + "/no-oracle": v for k, v in plain.items()}}


def outside(question_id, returned, partc=None):
    """The class-search findings Part C's judge never saw for this question."""
    target = part_c(partc) / "searches" / (question_id + ".json")
    pooled = set(lookup.pool(read_json(target))) if target.exists() else set()
    return sorted({i for ids in returned.values() for i in ids} - pooled)


def question_row(idx, root, question, props, out, partc=None):
    """One withheld question: today's and the class searches' returned findings, and recall against Part C's relevant
    findings, the grown pool and the bounds."""
    target = part_c(partc) / "searches" / (question["id"] + ".json")
    stored = read_json(target) if target.exists() else {"queries": []}
    pool = set(lookup.pool(stored))
    partc_verdicts = {i: v for i, v in verdicts_in(part_c(partc), question["id"]).items() if i in pool}
    mine_verdicts = verdicts_in(Path(out) / "lookup", question["id"])
    grown = dict(partc_verdicts, **{i: v for i, v in mine_verdicts.items() if i not in partc_verdicts})
    today = todays(stored)
    oracle, plain = searches_of(idx, root, question, props), searches_of(idx, root, question, props, oracle=False)
    row = {k: question.get(k) for k in ("id", "set", "kind", "group", "stratum", "property")}
    row.update(groups=oracle["groups"], groupsWithoutOracle=plain["groups"], classes=oracle["classes"],
               pool=len(pool), partcRelevant=sum(partc_verdicts.values()), grownRelevant=sum(grown.values()),
               unjudged=0, recall={})
    good = {i for i, r in partc_verdicts.items() if r}
    grown_good = {i for i, r in grown.items() if r}
    unknown = set()
    combined = {"today/first+%s" % k: list(dict.fromkeys(today["first"] + oracle["returned"][k])) for k in COMBINED}
    searched = [("today/first", today["first"]), ("today/all", today["all"])] + list(oracle["returned"].items()) + [
        ("%s/no-oracle" % k, v) for k, v in plain["returned"].items()] + list(combined.items())
    for label, ids in searched:
        unjudged = {i for i in ids if i not in grown}
        unknown |= unjudged
        found = len(set(ids) & grown_good)
        row["recall"][label] = {
            "returned": len(ids), "unjudged": len(unjudged),
            "partc": share(len(set(ids) & good), len(good)) if good else None,
            "grown": share(found, len(grown_good)) if grown_good else None,
            "upper": share(found + len(unjudged), len(grown_good) + len(unjudged)) if grown_good else None}
    row["unjudged"] = len(unknown)
    row["relevant"] = sorted(grown_good)
    row["returned"] = {"today/first": today["first"], "today/all": today["all"], **oracle["returned"]}
    return row


def recall_summary(rows, labels):
    """Mean recall per label over the questions with relevant findings: against Part C's relevant findings (the
    questions Part C counted), and over the grown pool's questions, judged (`grown`) and with every unjudged finding
    counted relevant (`upper`); unjudged findings counted irrelevant give `grown` again, the lower bound."""
    value = {}
    for label in labels:
        got = {}
        for measure in ("partc", "grown", "upper"):
            xs = [r["recall"][label][measure] for r in rows if r["recall"][label][measure] is not None]
            got[measure] = statistics.mean(xs) if xs else None
            got[measure + "Questions"] = len(xs)
        got["returnedMean"] = statistics.mean(r["recall"][label]["returned"] for r in rows) if rows else None
        got["unjudged"] = sum(r["recall"][label]["unjudged"] for r in rows)
        value[label] = got
    return value


# ----- the blind judge (step 3) -----

def judge(out=None, runner=None, hours=6, limit_calls=200, partc=None, root=None, labels=None):
    """Judge, blind and by Part C's procedure, the class-search findings outside Part C's pool, one Codex session per
    question (findings judged before are never judged again), at most `limit_calls` sessions; all in `out/lookup`."""
    out = Path(out or OUT)
    root = Path(root or kf_root())
    idx, props = index(root), mine.Properties(pins.PROPERTY_MAP)
    labels = labels if labels is not None else knowledge._graph_families(part_c(partc) / "workspaces" / pins.OPLUS)[2]
    state = {"status": "running", "startedAt": now(), "judged": 0, "failed": 0, "skipped": 0, "sessions": 0}
    with lookup_folder(out / "lookup") as folder:
        guard = runner or driver.Guard(time.time() + hours * 3600, base=folder)
        try:
            for question in lookup.withheld():
                new = outside(question["id"], every_search(idx, root, question, props), partc)
                if not new:
                    continue
                if state["sessions"] >= limit_calls:
                    state["skipped"] += 1
                    continue
                stored = {"queries": [{"q": "class search", "limit": 0, "origins": ["class"],
                                       "returned": {pins.B: new, pins.OPLUS: []},
                                       "pooled": {pins.B: [], pins.OPLUS: []}}]}
                done = lookup.judge_question(guard, question, stored, {pins.B: root}, labels)
                if done is not None:
                    state["sessions"] += 1
                    state["judged" if driver._ok(done.get("result")) else "failed"] += 1
            state["status"] = "completed"
        except driver.Stop as stop:
            state.update(status="stopped", stopReason=stop.args[0])
        state["finishedAt"] = now()
        atomic_json(folder / "state.json", state, private=True)
    return state


def judge_totals(out):
    """What this estimate's judge did: sessions (with attempts), questions, findings judged and found relevant."""
    calls = [read_json(p) for p in sorted((Path(out) / "lookup/judge").glob("*/call-*.json"))]
    done = [c for c in calls if driver._ok(c.get("result"))]
    return {"questions": len({c["question"] for c in calls}), "sessions": len(calls), "completed": len(done),
            "failed": len(calls) - len(done), "attempts": sum(len(c.get("attempts") or []) for c in calls),
            "judged": sum(len(c["result"]["relevant"]) for c in done),
            "relevant": sum(sum(c["result"]["relevant"].values()) for c in done),
            "models": sorted({c["result"].get("model") or "" for c in done})}


# ----- step 4: late finds and later searches -----

def late_finds(idx, root, misses, answers, props, miner=None):
    """Of the derivation pool's late finds, those a class-based first search for the answer's question returns, by
    variant; why the others are not; and the lenient reading (in the lineage and on the property by mining's test)."""
    miner = miner or mine.Miner(root)
    by_answer = {a["id"]: a for a in answers}
    late = [m for m in misses if m["kind"] == "late-find"]
    rows, cache = [], {}
    for item in late:
        answer = by_answer[item["answer"]]
        if answer["id"] not in cache:
            ctx = miner.context(answer)
            groups = [sorted(ids) for ids in (questions.resolved(str(root), m) for m in answer.get("materials") or [])
                      if ids] or ([sorted(ctx["ids"])] if ctx["ids"] else [])
            classes = tuple(sorted(props.classes(ctx["property"]))) if ctx["property"] else ()
            lineage = set().union(*(knowledge.lineage(str(root), set(g)) for g in groups)) if groups else set()
            cache[answer["id"]] = (ctx, groups, classes, lineage, {
                name: set(class_search(idx, root, groups, classes, limit, same)) if groups and classes else set()
                for name, (limit, same) in VARIANTS.items()})
        ctx, groups, classes, lineage, got = cache[answer["id"]]
        finding = idx.findings.get(item["finding"])
        row = {"id": item["id"], "answer": item["answer"], "finding": item["finding"], "classes": list(classes),
               "neverReturned": item.get("returnedAt") is None}
        if finding is None:
            row.update(reason="rejected or merged", returned={k: False for k in VARIANTS}, lenient=False)
        else:
            row["findingClass"], row["findingKind"] = finding["class"], finding["kind"]
            row["returned"] = {k: item["finding"] in got[k] for k in VARIANTS}
            in_lineage = bool(finding["subject"]) and finding["subject"] in lineage
            row["lenient"] = in_lineage and miner.on_property(finding["property"], ctx)
            if row["returned"]["first10+source"]:
                row["reason"] = "returned"
            elif not groups:
                row["reason"] = "question polymer unknown"
            elif not classes:
                row["reason"] = "no class for the question's property"
            elif not finding["subject"]:
                row["reason"] = "finding not filed under a polymer"
            elif not in_lineage:
                row["reason"] = "finding outside the asked lineage"
            elif row["returned"]["all+source"]:
                row["reason"] = "past the first ten (or same-source cap)"
            elif finding["kind"] != "material-property":
                row["reason"] = "condition, method or specimen finding of a source not returned"
            else:
                row["reason"] = "another property class"
        rows.append(row)
    summary = {"lateFinds": len(rows), "returned": {k: sum(r["returned"][k] for r in rows) for k in VARIANTS},
               "lenient": sum(r["lenient"] for r in rows),
               "reasons": dict(collections.Counter(r["reason"] for r in rows)),
               "byKind": dict(collections.Counter(r.get("findingKind", "-") for r in rows)),
               "neverReturned": sum(r["neverReturned"] for r in rows),
               "returnedNeverReturned": {k: sum(r["returned"][k] and r["neverReturned"] for r in rows)
                                         for k in VARIANTS}}
    summary["share"] = {k: share(v, len(rows)) for k, v in summary["returned"].items()}
    summary["lenientShare"] = share(summary["lenient"], len(rows))
    return rows, summary


def later_searches(rows, issued, partc=None, mapping="curated"):
    """The screen B answers' store calls after the first (as Part C replayed them on KF): how many returned only
    findings a class-based first search had returned (`covered`; empty calls counted apart), and of the calls that
    returned judged-relevant findings, how many returned none it had not (`relevantCovered`). Beside each variant,
    the same against the answer's own first call (`own first call`, what a later call already repeats today) and
    against that call and the class search together (`own first call+first10+source`)."""
    by_id = {r["id"]: r for r in rows}
    found = collections.Counter()
    per_variant = collections.defaultdict(collections.Counter)
    for question_id, calls in issued.items():
        row = by_id.get(question_id)
        target = part_c(partc) / "searches" / (question_id + ".json")
        if row is None or not target.exists():
            continue
        stored = {(s["q"], s["limit"]): s["returned"]["B"] for s in read_json(target)["queries"]}
        relevant = verdicts_in(part_c(partc), question_id)
        own = set(stored.get(tuple(calls[0]), ())) if calls else set()
        firsts = {name: set(row["returned"]["%s/%s" % (mapping, name)]) for name in VARIANTS}
        firsts["own first call"] = own
        firsts["own first call+first10+source"] = own | firsts["first10+source"]
        for query, limit in calls[1:]:
            got = stored.get((query, limit))
            if got is None:
                found["notReplayed"] += 1
                continue
            found["later"] += 1
            if not got:
                found["empty"] += 1
                continue
            good = {i for i in got if relevant.get(i)}
            for name, first in firsts.items():
                per_variant[name]["covered"] += set(got) <= first
                per_variant[name]["withRelevant"] += bool(good)
                per_variant[name]["relevantCovered"] += bool(good) and good <= first
    found["answers"] = sum(1 for q in issued if q in by_id)
    found["answersWithLater"] = sum(1 for q, c in issued.items() if q in by_id and len(c) > 1)
    return {**found, "byVariant": {k: dict(v) for k, v in per_variant.items()}}


# ----- step 5: tables and conflicts -----

def table_answerable(idx, root, question, classes, groups, lineage=None):
    """Whether saved values alone answer the question: every asked polymer group has a class-matched finding in its
    lineage that is numeric with a normalizable unit, in one dimension shared by the groups (`strict`); numeric with
    the same unit string in every group (`anyUnit`); and `strict` filed under the asked polymers themselves
    (`exact`)."""
    lineage = lineage or (lambda ids: knowledge.lineage(str(root), set(ids)))
    wanted = set(classes)
    per_group = []
    for ids in groups:
        family = lineage(ids)
        rows = class_rows(idx, family, wanted)
        per_group.append({"ids": ids, "rows": rows})
    if not per_group:
        return {"strict": False, "anyUnit": False, "exact": False, "groups": 0}

    def dims(rows):
        return {f["normalized"]["dimension"] for f in rows if f["normalized"]}

    def shared(sets):
        return bool(sets) and bool(set.intersection(*sets))
    strict = shared([dims(g["rows"]) for g in per_group])
    exact = shared([dims([f for f in g["rows"] if f["subject"] in g["ids"]]) for g in per_group])
    any_unit = shared([{_clean(f["parsed"]["unit"]).lower() for f in g["rows"] if f["parsed"]["kind"] in NUMERIC}
                       for g in per_group])
    return {"strict": strict, "anyUnit": any_unit, "exact": exact, "groups": len(per_group),
            "values": [sum(bool(f["normalized"]) for f in g["rows"]) for g in per_group]}


def conflicts(idx, tolerance):
    """(polymer, class) pairs over material-property findings with two or more normalized values in the pair's main
    dimension, and those holding two values whose intervals, widened by the tolerance (relative, or kelvin for a
    temperature), do not overlap; split by whether some conflicting values come from different sources."""
    relative, kelvin = tolerance
    pairs = collections.defaultdict(list)
    for f in idx.findings.values():
        if f["kind"] == "material-property" and f["subject"] and f["normalized"]:
            pairs[f["subject"], f["class"]].append(f)
    value = collections.Counter()
    examples = []
    for (subject, cls), rows in pairs.items():
        dimension = collections.Counter(f["normalized"]["dimension"] for f in rows).most_common(1)[0][0]
        mixed = len({f["normalized"]["dimension"] for f in rows}) > 1
        rows = [f for f in rows if f["normalized"]["dimension"] == dimension]
        if len(rows) < 2:
            continue
        value["pairs"] += 1
        value["values"] += len(rows)
        value["mixedDimensions"] += mixed
        value["twoValues"] += len(rows) == 2

        def widen(f):
            n = f["normalized"]
            pad = kelvin if dimension == "temperature" else relative * max(abs(n["low"]), abs(n["high"]))
            return n["low"] - pad, n["high"] + pad
        clash, across = False, False
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                (a0, a1), (b0, b1) = widen(a), widen(b)
                if a1 < b0 or b1 < a0:
                    clash = True
                    across = across or a["key"] != b["key"]
        value["conflicting"] += clash
        value["conflictingAcrossSources"] += across
        value["twoValuesConflicting"] += clash and len(rows) == 2
        if clash and len(examples) < 10:
            examples.append({"subject": subject, "class": cls, "values": len(rows)})
    return dict(value, share=share(value["conflicting"], value["pairs"]),
                twoValuesShare=share(value["twoValuesConflicting"], value["twoValues"]), examples=examples)


def tables(idx, root, rows_by_id, withheld):
    value = {}
    for mapping in MAPPINGS:
        part = {}
        for label, chosen in (("N/comparison", [q for q in withheld if q["set"] == "N" and q["kind"] == "comparison"]),
                              ("L/value", [q for q in withheld if q["set"] == "L" and q["group"] == "value"])):
            got = [dict(table_answerable(idx, root, q, rows_by_id[q["id"]]["classes"][mapping],
                                         rows_by_id[q["id"]]["groups"]), id=q["id"]) for q in chosen]
            part[label] = {"questions": len(got), **{k: sum(g[k] for g in got) for k in ("strict", "anyUnit", "exact")},
                           "rows": got}
        value[mapping] = part
    return value


# ----- report -----

def predictions(value):
    """The plan's prediction 3, each part met or not, on the main estimate (all findings not rejected; the curated
    classes, the first ten with today's same-source findings), with the other readings beside it."""
    s, mp = value["structure"]["all"], value["structure"]["materialProperty"]
    recall_value = value["recall"]["curated/first10+source"]
    late = value["lateFinds"]["summary"]["share"]
    others = {k: (value["recall"].get(k) or {}).get("grown") for k in (
        "today/first", "curated/first10+allsource", "curated/all+allsource", "rules/first10+source",
        "curated/first10+source/no-oracle", "today/first+curated/first10+source")}
    return {
        "classShare": {"predicted": ">= 0.80", "measured": s["classShare"],
                       "rulesAlone": (value["structure"].get("rulesAlone") or {}).get("agreeShareOfAll"),
                       "met": s["classShare"] >= PREDICTION["classShare"]},
        "numericNormalizableShare": {"predicted": ">= 0.60", "measured": s["normalizableShare"],
                                     "materialProperty": mp["normalizableShare"], "numeric": s.get("numericShare"),
                                     "met": s["normalizableShare"] >= PREDICTION["numericNormalizableShare"]},
        "recall": {"predicted": ">= 0.85", "measured": recall_value["grown"], "againstPartC": recall_value["partc"],
                   "others": others, "met": (recall_value["grown"] or 0) >= PREDICTION["recall"]},
        "lateFindsAvoided": {"predicted": ">= 1/3", "measured": late["first10+source"],
                             "others": {k: v for k, v in late.items() if k != "first10+source"},
                             "met": (late["first10+source"] or 0) >= PREDICTION["lateAvoided"]}}


def subsets(rows):
    groups = collections.OrderedDict(all=rows)
    for name in pins.SETS:
        chosen = [r for r in rows if r["set"] == name]
        groups[name] = chosen
        key = "group" if name == "L" else "stratum"
        for sub in dict.fromkeys(r[key] for r in chosen):
            groups["%s/%s" % (name, sub)] = [r for r in chosen if r[key] == sub]
    return groups


LABELS = ("today/first", "today/all") + tuple("%s/%s" % (m, v) for m in MAPPINGS for v in VARIANTS) + tuple(
    "%s/%s/no-oracle" % (m, v) for m in MAPPINGS for v in VARIANTS) + tuple("today/first+" + k for k in COMBINED)


SHOWN = ("today/first", "today/all", "curated/first10+source", "curated/first10+allsource", "rules/first10+source",
         "today/first+curated/first10+source")


def missed(rows, idx, root, label, mapping="curated"):
    """Why the relevant findings (grown pool) a search did not return were not returned by a class-based first search:
    not filed under a polymer; filed outside the asked lineage; another material-property class; a condition, method,
    specimen or composition finding whose source holds a class-matched finding in the lineage (cut by the cap or the
    first ten) or none (its source's values have other classes, or other polymers); a class match past the first ten.
    Counted per question and finding."""
    value = collections.Counter()
    for r in rows:
        family = set().union(*(knowledge.lineage(str(root), set(g)) for g in r["groups"])) if r["groups"] else set()
        wanted = set(r["classes"][mapping])
        got = set(r["returned"].get(label) or ())
        for i in r["relevant"]:
            if i in got:
                continue
            f = idx.findings.get(i)
            if f is None:
                value["rejected since"] += 1
            elif not f["subject"]:
                value["not filed under a polymer"] += 1
            elif f["subject"] not in family:
                value["filed outside the asked lineage"] += 1
            elif f["class"] in wanted:
                value["class match past the first ten"] += 1
            elif f["kind"] == "material-property":
                value["another material-property class"] += 1
            elif any(idx.findings[j]["class"] in wanted and idx.findings[j]["subject"] in family
                     for j in idx.by_source.get(f["key"], ())):
                value["condition etc.: its source has a class match (cut by a cap)"] += 1
            else:
                value["condition etc.: its source has no class match in the lineage"] += 1
    return dict(value, total=sum(value.values()))


def build(out=None, partc=None, root=None):
    out = Path(out or OUT)
    root = Path(root or kf_root())
    idx, props = index(root), mine.Properties(pins.PROPERTY_MAP)
    withheld = lookup.withheld()
    rows = [question_row(idx, root, q, props, out, partc) for q in withheld]
    by_id = {r["id"]: r for r in rows}
    misses, answers = read_json(pins.FOLDERS["mine"] / "misses.json"), [
        json.loads(line) for line in (pins.FOLDERS["mine"] / "answers.jsonl").read_text().splitlines() if line]
    late_rows, late_summary = late_finds(idx, root, misses, answers, props)
    issued = lookup.issued()
    value = {"meta": kf.meta("structure/classes.py"), "at": now(), "questions": len(rows),
             "structure": structure(idx),
             "recall": recall_summary(rows, LABELS),
             "recallBySubset": {name: recall_summary(chosen, SHOWN) for name, chosen in subsets(rows).items()},
             "missed": {label: missed(rows, idx, root, label) for label in (
                 "curated/first10+source", "curated/all+allsource", "today/first")},
             "classless": {m: sum(not r["classes"][m] for r in rows) for m in MAPPINGS},
             "judge": judge_totals(out),
             "lateFinds": {"summary": late_summary},
             "laterSearches": {m: later_searches(rows, issued, partc, m) for m in MAPPINGS},
             "tables": tables(idx, root, by_id, withheld),
             "conflicts": {name: conflicts(idx, tol) for name, tol in TOLERANCE.items()}}
    value["predictions"] = predictions(value)
    atomic_json(out / "rows.json", rows, private=True)
    atomic_json(out / "late.json", late_rows, private=True)
    atomic_json(out / "report.json", value, private=True)
    atomic_bytes(out / "report.md", markdown(value).encode("utf-8"), private=True)
    return value


def markdown(value):
    fmt = lambda x: "–" if x is None else "%.2f" % x if isinstance(x, float) else str(x)  # noqa: E731
    st = value["structure"]
    s, mp = st["all"], st["materialProperty"]
    lines = ["# Structure strategy 3: property class and numeric value (offline estimate)", "",
             "Built %s from KF (%s findings not rejected). Every definition is in `structure/classes.py`." % (
                 value["at"], s["findings"]), "", "## 1. How much of KF can be structured", "",
             "| | All findings | Material-property findings |", "| --- | ---: | ---: |"]
    for key, label in (("classShare", "a class from A1's map"), ("numericShare", "numeric value"),
                       ("normalizableShare", "numeric with a unit oopc.units normalizes"),
                       ("normalizableOfNumeric", "normalizable, of numeric")):
        lines.append("| %s | %s | %s |" % (label, fmt(s[key]), fmt(mp[key])))
    rules_alone = st["rulesAlone"]
    lines += ["", "A1's map was built on KF itself: by its rules for %s findings and by hand for %s. A1's rules alone "
              "class %s of the findings (%s), and give the map's class to %s (%s of all findings)." % (
                  st["assignedBy"].get("rule", 0), st["assignedBy"].get("model", 0), rules_alone["classed"],
                  fmt(rules_alone["share"]), rules_alone["agreeWithMap"], fmt(rules_alone["agreeShareOfAll"])),
              "Value kinds (all): " + ", ".join("%s %d" % kv for kv in sorted(s["valueKinds"].items())) + ".",
              "Numeric values with an empty unit: %d (material-property %d)." % (
                  s["numericEmptyUnit"], mp["numericEmptyUnit"]),
              "Findings by kind: " + ", ".join("%s %d" % kv for kv in sorted(st["byKind"].items())) + ".",
              "Classes with findings: %(materialProperty)d of %(materialPropertyInVocabulary)d material-property "
              "classes; %(any)d of %(vocabulary)d classes of any kind." % st["classesWithFindings"], "",
              "Units that would add most (material-property findings, numeric, not normalizable):", "",
              "| Unit | Findings | Normalizable share of material-property findings if added (cumulative) |",
              "| --- | ---: | ---: |"]
    for u in st["unitsToAdd"]:
        lines.append("| %s | %d | %s |" % (u["unit"], u["findings"], fmt(u["cumulativeShareOfMaterialProperty"])))
    lines += ["", "## 2–3. First-search recall (mean over questions with relevant findings)", "",
              "partc: against Part C's relevant findings (its 120 questions); grown: Part C's relevant findings and "
              "the newly judged ones (unjudged counted irrelevant: the lower bound); upper: unjudged counted relevant. "
              "Questions without a class: curated %s, rules %s." % (
                  value["classless"]["curated"], value["classless"]["rules"]),
              "", "| Search | partc | grown | upper | Returned (mean) | Unjudged |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for label, got in value["recall"].items():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (label, fmt(got["partc"]), fmt(got["grown"]),
                                                          fmt(got["upper"]), fmt(got["returnedMean"]), got["unjudged"]))
    shown = SHOWN
    lines += ["", "By subset (grown pool):", "", "| Group | Questions | " + " | ".join(shown) + " |",
              "| --- |" + " ---: |" * (len(shown) + 1)]
    for name, got in value["recallBySubset"].items():
        lines.append("| %s | %s | %s |" % (name, got["today/first"]["grownQuestions"], " | ".join(
            fmt(got[k]["grown"]) for k in shown)))
    lines += ["", "Relevant findings (grown pool) a search did not return, by why a class search misses them:", ""]
    for label, got in value["missed"].items():
        lines.append("- %s: %s." % (label, ", ".join("%s %d" % kv for kv in sorted(got.items()))))
    late = value["lateFinds"]["summary"]
    lines += ["", "## 4. Late finds and later searches", "",
              "%d late finds. Returned by a class-based first search (rules classes): " % late["lateFinds"] + ", ".join(
                  "%s %d (%s)" % (k, late["returned"][k], fmt(late["share"][k])) for k in VARIANTS)
              + "; lenient (in the lineage and on the property by mining's test): %d (%s)." % (
                  late["lenient"], fmt(late["lenientShare"])),
              "Why not returned (first10+source): " + ", ".join("%s %d" % kv for kv in sorted(late["reasons"].items()))
              + ".", "Late finds by kind: " + ", ".join("%s %d" % kv for kv in sorted(late["byKind"].items()))
              + ".", ""]
    for mapping, got in value["laterSearches"].items():
        lines += ["Screen B later store calls (%s classes): %d answers (%d with a later call), %d later calls (%d "
                  "empty, %d not replayed)." % (mapping, got.get("answers", 0), got.get("answersWithLater", 0),
                                                got.get("later", 0), got.get("empty", 0), got.get("notReplayed", 0)),
                  "", "| First search | Later calls covered | Calls with relevant results | Their relevant results "
                  "all covered |", "| --- | ---: | ---: | ---: |"]
        for k, v in got["byVariant"].items():
            lines.append("| %s | %d | %d | %d |" % (k, v.get("covered", 0), v.get("withRelevant", 0),
                                                    v.get("relevantCovered", 0)))
        lines.append("")
    lines += ["## 5. Tables", ""]
    for mapping, part in value["tables"].items():
        for label, got in part.items():
            lines.append("%s, %s: %d questions; answerable from saved values: normalizable in one dimension %d, any "
                         "unit shared %d, normalizable and filed under the asked polymer itself %d." % (
                             mapping, label, got["questions"], got["strict"], got["anyUnit"], got["exact"]))
    lines.append("")
    for name, got in value["conflicts"].items():
        lines.append("Conflicts, %s tolerance (%s relative, %s K): %d (polymer, class) pairs with two or more "
                     "normalized values (%d values); %d conflicting (%s), %d of them across sources; pairs with "
                     "exactly two values: %d, %d conflicting (%s)." % (
                         name, TOLERANCE[name][0], TOLERANCE[name][1], got.get("pairs", 0), got.get("values", 0),
                         got.get("conflicting", 0), fmt(got["share"]), got.get("conflictingAcrossSources", 0),
                         got.get("twoValues", 0), got.get("twoValuesConflicting", 0), fmt(got.get("twoValuesShare"))))
    lines += ["", "## 6. Predictions (plan, strategy 3)", "", "| Prediction | Predicted | Measured | Met | Other "
              "readings |", "| --- | --- | ---: | --- | --- |"]
    for key, got in value["predictions"].items():
        other = {k: v for k, v in got.items() if k not in ("predicted", "measured", "met")}
        flat = {}
        for k, v in other.items():
            flat.update({"%s %s" % (k, kk): vv for kk, vv in v.items()} if isinstance(v, dict) else {k: v})
        lines.append("| %s | %s | %s | %s | %s |" % (key, got["predicted"], fmt(got["measured"]),
                                                     "yes" if got["met"] else "no",
                                                     "; ".join("%s %s" % (k, fmt(v)) for k, v in flat.items())))
    j = value["judge"]
    lines += ["", "Blind judge (this estimate, Part C's procedure, Codex %s): %d sessions (%d attempts) on %d "
              "questions, %d completed, %d failed; %d findings judged, %d relevant." % (
                  ", ".join(j["models"]) or "–", j["sessions"], j["attempts"], j["questions"], j["completed"],
                  j["failed"], j["judged"], j["relevant"])]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["judge", "report", "outside"])
    parser.add_argument("--hours", type=float, default=6)
    parser.add_argument("--limit-calls", type=int, default=200)
    args = parser.parse_args(argv)
    if args.command == "judge":
        out = judge(hours=args.hours, limit_calls=args.limit_calls)
    elif args.command == "outside":  # what the judge would judge, without judging
        root = kf_root()
        idx, props = index(root), mine.Properties(pins.PROPERTY_MAP)
        out = {q["id"]: len(outside(q["id"], every_search(idx, root, q, props))) for q in lookup.withheld()}
        out = {"questions": sum(1 for v in out.values() if v), "findings": sum(out.values()),
               "largest": sorted(out.values())[-10:]}
    else:
        out = build()
        out = {k: out[k] for k in ("structure", "recall", "predictions")}
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:20000])


if __name__ == "__main__":
    main()
