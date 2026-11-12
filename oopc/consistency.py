"""Consistency of new findings with saved knowledge: which saved findings each new finding is compared with, and the
conflicts a review finds between them (owner, 2026-11-05).

Comparing every new finding with every saved one would be too expensive, so each is compared with a small tranche:
the saved findings most likely to conflict with it and most informative if they do (`tranche`). Candidates are the
saved findings filed under its polymer, its families or members (or, unfiled, naming its material) and every other
finding from its source; each is scored on its polymer and property relation, a shared source, comparable values and
values in tension (`score`), the top `consistencyDepth` per new finding are kept (at most `PER_SOURCE` from one
source), and the answer's budget of saved findings (`5 × depth`, at least one per new finding, at most 100) is shared
out a pair at a time, each new finding's most telling first, so every new finding is compared. The ranking is
deterministic: on an unchanged store an answer is compared with the same tranche.

After a deposit the tranche is screened (`screen`): the deposit's `consistency` is `none` (nothing related), `pending`
(related findings, none in tension) or `tension`. The screen looks for qualitative inconsistency (owner, 2026-11-05),
not measurement uncertainty: values far apart for materials described alike at test temperatures within 20 degrees
or not given, or opposite outcomes in words (soluble and insoluble, brittle and ductile) (`in_tension`). It reads a
value with an uncertainty, in scientific notation or as a bound (`_range`), a finding's test temperature from its
conditions (`_temperature`) and an outcome's words (`_outcome`). The review that runs anyway after an answer carries
the check; an answer with nothing else to review is reviewed only when a pair is in tension. The reviewer is told that
a stated difference makes values consistent only when it plausibly accounts for their difference, and returns only the
pairs that cannot both be right, each read as `new-misread`, `saved-misread`, `sources-disagree` or `unresolved`, and
`record` keeps every one in the `conflicts` table. By default (`conflictResolution` `reviewer`) its reading takes
effect; with `person` nothing changes status and the conflict waits for a person to `settle` it. Findings in a
conflict nobody has settled away are linked (`conflictsWith`), which search shows, so an answer can report both.
"""
from __future__ import annotations

import json
import math
import re

from . import knowledge, units
from .util import digest, now

MAX_DEPTH = 25
PER_SOURCE = 3  # Saved findings from one source in one new finding's tranche.
UNFILED = 2000  # Unfiled saved findings a filed new finding is scored against (the most recent).
TENSION_GAP = 0.25  # Comparable values whose ranges are further apart than this share of the larger are in tension;
TEMPERATURE_GAP = 20.0  # temperatures, whose scales have different zeros, when more than this many degrees apart
# (and test temperatures this far apart may explain any difference);
SAME_MATERIAL = 0.5  # either only when their materials share this share of their words (a grade, not just the polymer).
# Outcomes in words (owner, 2026-11-05): a negator, a prefixed antonym (soluble, insoluble) or one of a short list of
# opposites makes two outcomes opposite; a partial outcome is neither.
NEGATORS = {"not", "no", "cannot", "without", "never", "none", "non", "un"}
PREFIXES = ("non", "in", "un", "im", "ir", "il")
OPPOSITES = {"ductil": ("brittl", True), "amorphou": ("crystallin", True), "semicrystallin": ("crystallin", False),
             "opaqu": ("transparent", True), "fail": ("pass", True), "absent": ("present", True),
             "hydrophilic": ("hydrophobic", True), "decreas": ("increas", True)}  # A stem: its opposite's, negated.
PARTIAL = {"partial", "partially", "partly", "slightly"}
OUTCOME_FILLER = knowledge.STOPWORDS | {"yes", "could", "can", "would", "been", "being", "it", "has", "have", "had",
                                        "very", "highly", "completely", "fully", "totally", "readily", "freely",
                                        "easily", "entirely"}
READINGS = ("new-misread", "saved-misread", "sources-disagree", "unresolved")
SETTLEMENTS = ("new-misread", "saved-misread", "sources-disagree", "no-conflict")
RESOLUTIONS = ("reviewer", "person")
STATES = ("none", "pending", "tension", "checked", "skipped")
WEIGHT = {knowledge.SUPPORTED: 1.0, knowledge.ACCEPTED: 0.9}  # Needs checking: 0.8.
MATERIAL_FILLER = {"film", "films", "neat", "sample", "samples", "specimen", "specimens", "pellet", "pellets", "resin",
                   "grade", "grades", "the", "of", "and", "with", "a", "commercial", "polymer", "plate", "plates", "sheet",
                   "sheets", "bar", "bars", "powder"}
FIELDS = ("id", "question_id", "status", "statement", "material", "property", "value", "unit", "conditions", "subject",
          "source_title", "source_url", "source_doi", "locator", "detail")

INSTRUCTION = (
    "Consistency with saved knowledge. This is a comparison, not a source check: the verdicts and excerpts above are "
    "for the findings in findings only, and a finding listed only under consistency gets no verdict. consistency.new "
    "lists findings this answer saved, each with compareWith: the ids (s1, s2, ...) of the saved findings in "
    "consistency.saved most related to it (the same polymer or its family, the same or a related property, other "
    "readings of its source). A source there is a DOI or URL, with its title when the pair is in tension; a material or "
    "property is left out when the statement says it. Compare each new finding with these by what they state, without "
    "opening their sources. A stated difference (grade, composition, molecular weight, processing, specimen, test "
    "method, rate, temperature or humidity) makes different values consistent only when it plausibly accounts for "
    "the difference in size and direction, for example a transition between the two temperatures; differences within "
    "what measurement and rounding allow are no conflict either: report nothing for these. Values far apart under "
    "nearly identical conditions, or opposite outcomes (soluble and insoluble, brittle and ductile) a few tens of "
    "degrees apart with nothing between them to explain it, cannot both be right as stated. Only for a pair that "
    "cannot both be right as stated, open both sources (their capturedText first, when given) and return one "
    "conflict: finding (the new id), with (the saved finding's id, such as s3), reading, and one sentence of reason "
    "saying what each source shows. Readings: new-misread when the new finding misstates its source; saved-misread "
    "when the saved finding misstates its source; sources-disagree when both read their sources correctly and the sources report different values; unresolved "
    "when a source cannot be opened or read, or you cannot tell. Report only conflicts, never pairs that agree, and at "
    "most one conflict per pair. Return an empty conflicts list when there are none.\n\n")


# ----- the tranche -----

def _features(row, cache):
    """What scoring reads of a finding row, computed once per row."""
    if row["id"] not in cache:
        prop, unit = row["property"] or "", " ".join((row["unit"] or "").split())
        value = _range(row["value"], unit)
        cache[row["id"]] = {
            "property": knowledge.property_words(prop), "aliases": _aliases(prop),
            "material": frozenset(knowledge._tokens(row["material"]) - MATERIAL_FILLER),
            "statement": knowledge._words(row["statement"]), "range": value, "unit": unit,
            "outcome": _outcome(row["value"]) if value is None else None, "setting": _setting(prop),
            "source": knowledge.source_key(row["source_doi"], row["source_url"]),
            "conditions": frozenset(knowledge._tokens(row["conditions"])),
            "temperature": _temperature(row["conditions"])}
    return cache[row["id"]]


def _setting(prop):
    """Whether a property is worded as a test's setting or a specimen's dimension ("film thickness", "DSC heating
    rate", `knowledge.TEST_SETTING`), read on its head before any qualifier, so "water absorption at 50% relative
    humidity" stays a property. Specimens and settings differ by design: the first trial of the wider value reading
    flagged eight film thicknesses of one grade's specimens (71 ± 3 µm and 200 µm), all false alarms."""
    head = re.split(r"\s+(?:at|in|under|after|for|of|with|during)\s+|[(,;]", prop or "", maxsplit=1)[0]
    return bool(knowledge.TEST_SETTING.search(head))


def _aliases(prop):
    """The abbreviations a property's wording gives in parentheses ("Glass transition temperature (Tg)" gives tg)."""
    return {knowledge.property_words(inner) for inner in re.findall(r"\(([^()]{1,20})\)", prop or "")} - {frozenset()}


_SCALAR = r"(?:[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*[×x·*]\s*10\^[-+]?\d+|[eE][-+]?\d+)?|10\^[-+]?\d+)"
_ABOUT = r"(?:(?:≈|~|∼|ca\.?|about|approximately|approx\.?|around)\s*)?"
_VALUE = re.compile(r"%s(%s)(?:\s*(?:-|–|—|to)\s*(%s))?" % (_ABOUT, _SCALAR, _SCALAR))
_UNCERTAIN = re.compile(r"%s\(?\s*(%s)\s*(?:±|\+/-|\+-)\s*(%s)\s*\)?(?:\s*[×x·*]\s*10\^([-+]?\d+))?"
                        % (_ABOUT, _SCALAR, _SCALAR))
_BOUND = re.compile(r"(<=|>=|<|>|≤|≥|below|under|less than|at most|up to|above|over|more than|greater than|at least)"
                    r"\s*(%s)" % _SCALAR)
_UPPER = {"<=", "<", "≤", "below", "under", "less than", "at most", "up to"}
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def _scalar(text):
    """A number as written (4.1, 4.1e2, 4.1 × 10^2, 10^2) as its mantissa and its power of ten (None when not given)."""
    if text.startswith("10^"):
        return 1.0, int(text[3:])
    found = re.search(r"\s*(?:[×x·*]\s*10\^|[eE])([-+]?\d+)$", text)
    return (float(text[:found.start()]), int(found.group(1))) if found else (float(text), None)


def _pair(first, second, power=None):
    """Two numbers written together; a power of ten written once (on the second, or after both) is both's."""
    (a, power_a), (b, power_b) = _scalar(first), _scalar(second)
    power_a = next((p for p in (power_a, power_b, power) if p is not None), 0)
    power_b = next((p for p in (power_b, power, power_a) if p is not None), 0)
    return float("%re%d" % (a, power_a)), float("%re%d" % (b, power_b))


def _range(value, unit=""):
    """A value as (low, high): one number or a range ("45", "-5", ".5", "+10", "55–60", "110-120", "≈1.2", "around 12",
    "1,200", "1,5", "2 to 4"); with an uncertainty, its range ("55.3 ± 0.2", "55.3 +/- 0.2" are 55.1–55.5); in
    scientific notation ("6.88 × 10⁻¹⁰", "6.88×10^-10", "1.9·10^5", "4.1e2", "(4.41 ± 0.01) × 10⁻¹⁶"); a bound as an
    open interval ("<5", "≤4.8", "below 1", "up to 5" from minus infinity; ">80", "≥2", "above 3", "at least 2" to
    infinity); each followed by "%" or by the finding's own unit ("40%", "55 MPa" when its unit is MPa). None for
    anything else (a cell with several values "352; 2.3", "93.84; SD 2.19", dimensions "80 × 10 × 4", text), which is
    left uncompared rather than read as another interval."""
    text = " ".join((value or "").split())
    for tail in ("%", " ".join((unit or "").split())):  # A unit written after the number.
        if tail and len(text) > len(tail) and text.endswith(tail):
            text = text[:-len(tail)].rstrip()
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^" + m.group(0).translate(_SUPERSCRIPT), text)  # 10⁻¹⁰: 10^-10
    text = re.sub(r"\^\s*", "^", text.replace("−", "-"))
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # 1,200
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)  # 1,5
    found = _BOUND.fullmatch(text)
    if found:
        bound = _pair(found.group(2), found.group(2))[0]
        return (-math.inf, bound) if found.group(1) in _UPPER else (bound, math.inf)
    found = _UNCERTAIN.fullmatch(text)
    if found:
        middle, spread = _pair(found.group(1), found.group(2), found.group(3) and int(found.group(3)))
        return middle - abs(spread), middle + abs(spread)
    found = _VALUE.fullmatch(text)
    if not found:
        return None
    numbers = _pair(found.group(1), found.group(2) or found.group(1))
    return min(numbers), max(numbers)


_DEGREES = re.compile(
    r"(?<![\w.^])([-+]?\d+(?:\.\d+)?)((?:\s*(?:and|or|to|-|–|—)\s*[-+]?\d+(?:\.\d+)?)*)(?:\s*±\s*\d+(?:\.\d+)?)?"
    r"\s*(°\s*C|º\s*C|℃|K)(?![^\W\d_])(?!\s*(?:/|·|per\b)?\s*(?:min|s|sec|h|hr|hour|day)\b)")  # Not a rate.
_ROOM = re.compile(r"\b(?:room|ambient)[\s-]+temperature\b|\bRT\b", re.I)


def _temperature(conditions):
    """The temperature, in °C, that a finding's conditions give ("23 °C", "23°C", "25 ± 2 °C", "296 K", "−40 °C";
    room or ambient temperature, RT, as 23 °C), or None when they give none or several distinct ones (a test and a
    processing temperature, a range). A rate ("10 °C/min", "5 K/min") is no temperature."""
    text = (conditions or "").replace("−", "-")
    found = [23.0] * len(_ROOM.findall(text))
    for match in _DEGREES.finditer(text):
        numbers = [match.group(1)] + re.findall(r"[-+]?\d+(?:\.\d+)?", match.group(2))
        found += [float(n) - (273.15 if match.group(3) == "K" else 0) for n in numbers]
    return sum(found) / len(found) if found and max(found) - min(found) <= 5 else None


def _stem(word):
    """A crude stem for comparing outcomes: "increase", "increases", "increased" and "increasing" read alike."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix) and not word.endswith("ss"):
            word = word[:-len(suffix)]
            break
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def _outcome(value):
    """A value in words as its stems, the stems it negates (a negator's next word, or a listed opposite's stem) and
    whether it is partial; None when it has no words."""
    text = re.sub(r"n't\b", " not", (value or "").lower()).replace("semi-", "semi")
    words = re.findall(r"[^\W\d_]+", text)
    if not words:
        return None
    stems, negated, pending = set(), set(), False
    for word in words:
        if word in NEGATORS:
            pending = not pending
            continue
        if word in OUTCOME_FILLER:
            continue
        stem, flip = OPPOSITES.get(_stem(word), (_stem(word), False))
        stems.add(stem)
        if pending != flip:
            negated ^= {stem}
        pending = False
    if pending:  # A lone "no" or "none" negates the whole outcome.
        negated ^= {""}
    return frozenset(stems), frozenset(negated), bool(PARTIAL & set(words))


def _unprefixed(outcome, other):
    """An outcome with each word that is a prefixed antonym of one of the other's (insoluble beside soluble) read as
    that word negated."""
    stems, negated, partial = set(outcome[0]), set(outcome[1]), outcome[2]
    for word in outcome[0] - other[0]:
        rest = next((word[len(p):] for p in PREFIXES if word.startswith(p) and word[len(p):] in other[0]
                     and len(word) - len(p) >= 4), None)
        if rest:
            stems = stems - {word} | {rest}
            negated = negated - {word} ^ ({rest} if word not in negated else set())
    return frozenset(stems), frozenset(negated), partial


def opposite(first, second):
    """Whether two outcomes in words are opposite: their words largely shared (half or more), and a word they share
    negated in one only ("could not be melt-spun" and "melt-spun", "insoluble" and "soluble", "ductile" and
    "brittle"; "no" and "yes"). Two ways of saying one outcome ("insoluble", "not soluble") and partial outcomes
    ("partially soluble") are not."""
    if not first or not second or first[2] or second[2]:
        return False
    first = _unprefixed(first, second)
    second = _unprefixed(second, first)
    union = first[0] | second[0]
    if union and len(first[0] & second[0]) / len(union) < 0.5:
        return False
    differ = first[1] ^ second[1]
    return bool(differ) and differ <= (first[0] & second[0]) | {""}


def _comparable(a, b):
    """Both values' ranges in one unit (b converted into a's when they differ), and the unit's dimension; None when
    they cannot be compared."""
    if not a["range"] or not b["range"]:
        return None
    first, second = units.get_unit(a["unit"]), units.get_unit(b["unit"])
    plain = lambda u: re.sub(r"[\s°]", "", u.lower()).replace("μ", "µ")  # noqa: E731
    if first and second and first.dimension == second.dimension:
        try:  # A bound's infinite end stays infinite.
            converted = tuple(v if math.isinf(v) else units.convert_value(v, b["unit"], a["unit"]) for v in b["range"])
        except ValueError:
            return None
        return a["range"], converted, first.dimension
    if a["unit"] and plain(a["unit"]) == plain(b["unit"]) or not a["unit"] and not b["unit"]:
        return a["range"], b["range"], first.dimension if first else None
    return None


def _overlap(first, second):
    return len(first & second) / len(first | second) if first and second else 0.0


def in_tension(a, b, same_property):
    """Whether two findings of one property look incompatible: values far apart under nearly the same conditions, or
    opposite outcomes in words (`opposite`). From one source: the same material and conditions read as values that
    cannot be one number (one cell read twice), or as opposite outcomes. From two: materials described alike
    (`SAME_MATERIAL`) at test temperatures within `TEMPERATURE_GAP` degrees or not given (further apart, temperature may
    explain it), with comparable ranges further apart than `TENSION_GAP` of the larger (and `TEMPERATURE_GAP` degrees
    for temperatures), or opposite outcomes. A bound is in tension only with a value beyond it by more than that.
    Different grades, specimens or settings differ by design and are left to the reviewer's reading, not flagged.
    Temperatures are compared by their difference alone, which does not depend on the unit they are written in."""
    if not same_property or a.get("setting") or b.get("setting"):  # A test's setting or a specimen's dimension.
        return False
    same_source = bool(a["source"]) and a["source"] == b["source"]
    if same_source:
        if not a["material"] or a["material"] != b["material"] or a["conditions"] != b["conditions"]:
            return False
    elif _overlap(a["material"], b["material"]) < SAME_MATERIAL:
        return False
    elif a["temperature"] is not None and b["temperature"] is not None \
            and abs(a["temperature"] - b["temperature"]) > TEMPERATURE_GAP:
        return False
    compared = _comparable(a, b)
    if not compared:
        return a["range"] is None and b["range"] is None and opposite(a["outcome"], b["outcome"])
    (low, high), (other_low, other_high), dimension = compared
    gap = max(other_low - high, low - other_high)  # How far apart the ranges are; negative when they overlap.
    scale = max(abs(v) for v in (low, high, other_low, other_high) if math.isfinite(v))
    if same_source:
        return gap > 1e-9 * scale
    if dimension == "temperature":
        return gap > TEMPERATURE_GAP
    return gap > 0 and scale > 0 and gap / scale > TENSION_GAP


def _material_relation(a, b):
    overlap = _overlap(a["material"], b["material"])
    return 0.6 * overlap if overlap >= 0.34 else 0.0


def _property_relation(a, b, terms_a, terms_b):
    """1.0 for the same property (one term, the same words, or one's words the other's abbreviation); less for most
    words shared (three in five or more), or one's property named in the other's statement; 0 for unrelated."""
    if terms_a & terms_b:
        return 1.0
    first, second = a["property"], b["property"]
    if first and (first == second or first in b["aliases"] or second in a["aliases"]):
        return 1.0
    if first and second:  # Half the words in common is another property ("tensile strength at break", "tensile
        overlap = len(first & second) / len(first | second)  # yield strength"): a gap between them is no conflict.
        if overlap >= 0.6:
            return 0.7 * overlap
    for one, other in ((first, b), (second, a)):  # "Tg" beside "...a glass transition temperature (Tg) of 58 °C".
        word = next(iter(one)) if len(one) == 1 else ""
        if 2 <= len(word) <= 5 and knowledge._mentions(other["statement"], word):
            return 0.5
    return 0.0


def score(new, other, new_features, other_features, family, terms=None):
    """How likely and how telling a conflict between a new finding and a saved one would be, with whether their values
    are in tension; (0, False) when they are not about the same polymer and a related property."""
    terms = terms or {}
    if new["subject"] and other["subject"]:
        polymer = 1.0 if new["subject"] == other["subject"] else 0.6 if other["subject"] in family else 0.0
    else:
        polymer = _material_relation(new_features, other_features)
    prop = _property_relation(new_features, other_features, terms.get(new["id"], set()), terms.get(other["id"], set()))
    if not polymer or not prop:
        return 0.0, False
    tension = in_tension(new_features, other_features, prop == 1.0)
    # On one polymer, the same grade or specimen (shared material words) is the more telling comparison.
    value = (polymer + prop + 0.4 * _overlap(new_features["material"], other_features["material"])
             + (0.5 if new_features["source"] and new_features["source"] == other_features["source"] else 0)
             + (0.3 if _comparable(new_features, other_features) else 0) + (1.0 if tension else 0))
    return round(value * WEIGHT.get(other["status"], 0.8), 4), tension


def _rows(db, sql, args=()):
    return [dict(zip(FIELDS, row)) for row in db.execute("SELECT %s FROM findings %s" % (", ".join(FIELDS), sql), args)]


def _terms(db, ids):
    """Each finding's property terms, when a reflection has put terms in force."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finding_terms'").fetchone():
        return {}
    found = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for finding, term in db.execute("SELECT finding_id, term FROM finding_terms WHERE finding_id IN (%s)"
                                        % ",".join("?" * len(part)), part):
            found.setdefault(finding, set()).add(term)
    return found


def _candidates(root, db, new, features, by_subject, by_source):
    """Saved findings that could conflict with `new`: for a filed one, those filed under its polymer's lineage and the
    unfiled ones; for an unfiled one, those naming its material and property; and every finding of its source.
    Rejected ones and its own answer's never."""
    found, family = {}, set()
    if new["subject"]:
        family = knowledge.lineage(root, {new["subject"]})
        key = frozenset(family)
        if key not in by_subject:
            by_subject[key] = _rows(db, "WHERE status != ? AND subject IN (%s)" % ",".join("?" * len(family)),
                                    (knowledge.UNSUPPORTED, *sorted(family)))
        found.update((r["id"], r) for r in by_subject[key])
        # And the unfiled findings, scored by their material words (few: 188 of 8,976 in 2026-11), loaded once.
        if None not in by_subject:
            by_subject[None] = _rows(db, "WHERE status != ? AND (subject IS NULL OR subject = '') ORDER BY rowid DESC "
                                         "LIMIT ?", (knowledge.UNSUPPORTED, UNFILED))
        found.update((r["id"], r) for r in by_subject[None])
    else:  # An unfiled new finding: the findings that name its material and property.
        phrase = knowledge._match(" ".join(filter(None, [new["material"], new["property"]])))
        if phrase:
            found.update((r["id"], r) for r in (dict(zip(FIELDS, row)) for row in db.execute(
                "SELECT %s FROM findings_fts x JOIN findings f ON f.id = x.id WHERE findings_fts MATCH ? AND f.status != ? "
                "ORDER BY rank LIMIT 300" % ", ".join("f." + k for k in FIELDS), (phrase, knowledge.UNSUPPORTED))))
    source = features["source"]
    if source:
        if source not in by_source:
            needle = source.split(":", 1)[1]
            by_source[source] = [r for r in _rows(db, "WHERE status != ? AND (instr(lower(source_doi), ?) OR "
                                                      "instr(lower(source_url), ?))", (knowledge.UNSUPPORTED, needle, needle))
                                 if knowledge.source_key(r["source_doi"], r["source_url"]) == source]
        found.update((r["id"], r) for r in by_source[source])
    return [r for r in found.values() if r["question_id"] != new["question_id"]], family


def build(root, db, question_id, depth):
    """The tranche for an answer's findings: `new` maps each new finding id to the saved ids it is compared with (most
    telling first), `saved` holds those saved rows, `rows` the new ones, `pairs` every kept pair with its score, and
    `tension` the pairs in tension."""
    depth = max(0, min(int(depth or 0), MAX_DEPTH))
    empty = {"new": {}, "saved": {}, "rows": {}, "pairs": [], "tension": [], "depth": depth}
    if not depth:
        return empty
    news = _rows(db, "WHERE question_id=? AND status != ? ORDER BY rowid", (question_id, knowledge.UNSUPPORTED))
    if not news:
        return empty
    cache, by_subject, by_source, ranked = {}, {}, {}, []
    pools = {}
    for new in news:
        features = _features(new, cache)
        pools[new["id"]] = _candidates(root, db, new, features, by_subject, by_source)
    terms = _terms(db, sorted({new["id"] for new in news} | {r["id"] for rows, _ in pools.values() for r in rows}))
    for new in news:
        rows, family = pools[new["id"]]
        scored = []
        for row in rows:
            value, tension = score(new, row, _features(new, cache), _features(row, cache), family, terms)
            if value > 0:
                scored.append((value, tension, row))
        scored.sort(key=lambda item: (-item[0], item[2]["id"]))
        per_source, kept = {}, []
        for value, tension, row in scored:
            source = _features(row, cache)["source"]
            if per_source.get(source, 0) >= PER_SOURCE:
                continue
            per_source[source] = per_source.get(source, 0) + 1
            kept.append((value, tension, row))
            if len(kept) >= depth:
                break
        if kept:
            ranked.append((new["id"], kept))
    # The budget of saved findings in the prompt is shared out a pair at a time: each new finding's most telling pair
    # first (those in tension first among them), then each one's second, so every new finding is compared.
    cap = min(100, max(10, 5 * depth, len(ranked)))
    rounds = [sorted(((kept[at][1], kept[at][0], new_id, kept[at][2]) for new_id, kept in ranked if at < len(kept)),
                     key=lambda item: (-item[0], -item[1], item[2], item[3]["id"])) for at in range(depth)]
    value = dict(empty, rows={new["id"]: new for new in news})
    for tension, score_, new_id, row in (pair for pairs in rounds for pair in pairs):
        if row["id"] not in value["saved"] and len(value["saved"]) >= cap:
            continue
        value["saved"][row["id"]] = row
        value["new"].setdefault(new_id, []).append(row["id"])
        value["pairs"].append({"finding": new_id, "with": row["id"], "score": score_, "tension": tension})
        if tension:
            value["tension"].append((new_id, row["id"]))
    order = {(p["finding"], p["with"]): -p["score"] for p in value["pairs"]}
    for new_id, ids in value["new"].items():
        ids.sort(key=lambda i: (order[(new_id, i)], i))
    return value


def _state(db, question_id):
    row = db.execute("SELECT consistency FROM deposits WHERE question_id=?", (question_id,)).fetchone()
    return row[0] if row else None


def screen(root, question_id, depth):
    """After a deposit: whether its findings have related saved findings, and whether any values are in tension (which
    is what sends an answer with nothing else waiting to review). Once per deposit; returns the state."""
    if not depth or not knowledge.database(root).exists():
        return None
    with knowledge.connect(root, write=True) as db:
        if _state(db, question_id) is not None:
            return _state(db, question_id)
        found = build(root, db, question_id, depth)
        state = "tension" if found["tension"] else "pending" if found["pairs"] else "none"
        db.execute("UPDATE deposits SET consistency=? WHERE question_id=?", (state, question_id))
    return state


def tranche(root, question_id, depth):
    """The tranche to put before a reviewer now, or None when this answer's consistency is not waiting to be checked
    (checked already, nothing related, deposited before the check existed) or the check is off."""
    if not depth or not knowledge.database(root).exists():
        return None
    with knowledge.connect(root) as db:
        if _state(db, question_id) not in ("pending", "tension"):
            return None
        return build(root, db, question_id, depth)


def unchecked(root, question_id, found):
    """A review with nothing to source-check found no tension now: the answer leaves the review queue unchecked
    (`skipped` when the check is off, else `pending` or `none` by what the tranche holds)."""
    state = "skipped" if found is None else "pending" if found["pairs"] else "none"
    with knowledge.connect(root, write=True) as db:
        if _state(db, question_id) in ("pending", "tension"):
            db.execute("UPDATE deposits SET consistency=? WHERE question_id=?", (state, question_id))


# ----- the reviewer's part -----

LABELS = {knowledge.SUPPORTED: "Reviewed", knowledge.ACCEPTED: "Added", knowledge.UNREVIEWED: "Needs checking",
          knowledge.UNCERTAIN: "Needs checking"}


def _said(text, statement):
    """Whether the statement already says `text` (its words, ignoring case)."""
    words = knowledge._tokens(text)
    return bool(words) and words <= knowledge._tokens(statement)


def _view(row, full=False, identifier=None):
    """A finding as the reviewer compares it, by what it states (in the trial of 2026-11-05 the comparison was three
    quarters of a review prompt, sources a quarter of that): its source as one address (its DOI, else its URL), short
    fields, no locator, and no material or property the statement already says. One in a pair in tension (`full`),
    whose sources the reviewer is likely to open, keeps its source's title and addresses, its locator and longer
    fields."""
    limits = (400, 200, 120, 300, 160) if full else (250, 120, 80, 120, 0)  # No locator unless its source may be opened.
    statement = (row["statement"] or "")[:limits[0]]
    value = {"id": identifier or row["id"], "statement": statement,
             "material": "" if not full and _said(row["material"], statement) else (row["material"] or "")[:limits[1]],
             "property": "" if not full and _said(row["property"], statement) else (row["property"] or "")[:limits[2]],
             "value": row["value"], "unit": row["unit"], "conditions": (row["conditions"] or "")[:limits[3]],
             "locator": (row["locator"] or "")[:limits[4]]}
    if full:
        value["source"] = {k: v for k, v in (("title", (row["source_title"] or "")[:200]), ("url", row["source_url"]),
                                             ("doi", row["source_doi"])) if v}
    else:
        value["source"] = row["source_doi"] or row["source_url"]
    return {k: v for k, v in value.items() if v}


def _refs(found):
    """Short ids for the saved findings (s1, s2, ...) in the order they are given, and back."""
    refs = {identifier: "s%d" % n for n, identifier in enumerate(found["saved"], 1)}
    return refs, {ref: identifier for identifier, ref in refs.items()}


def section(root, found, listed):
    """The prompt's `consistency` part: each new finding (by id alone when the source check lists it) with the ids it
    is compared with, and each saved finding once, with its status. A saved finding in tension carries the passages of
    its source's captured text around its value, as does a new one in tension that the source check does not list."""
    from . import sources
    tense, refs = {i for pair in found["tension"] for i in pair}, _refs(found)[0]

    def captured(row, identifier=None):
        view = _view(row, full=row["id"] in tense, identifier=identifier)
        if root is not None and row["id"] in tense and view.get("source"):
            text = sources.evidence(root, view["source"], row["value"], row["statement"], row["locator"],
                                    row["conditions"], limit=1500)
            if text:
                view["capturedText"] = text
        return view
    new = [{"id": i, "compareWith": [refs[s] for s in ids]} if i in listed else
           dict(captured(found["rows"][i]), compareWith=[refs[s] for s in ids]) for i, ids in found["new"].items()]
    saved = [dict(captured(row, refs[row["id"]]), status=LABELS.get(row["status"], row["status"]))
             for row in found["saved"].values()]
    return {"new": new, "saved": saved}


def render(section):
    """The `consistency` part as JSON with one finding a line: an indented dump spent a tenth of it on layout."""
    def lines(items):
        return ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in items)
    return '{\n "new": [\n%s\n ],\n "saved": [\n%s\n ]}' % (lines(section["new"]), lines(section["saved"]))


def parse(answer, found):
    """The conflicts a reviewer returned for pairs it was offered, one per pair (a saved finding named by its short id
    or its own); anything else is ignored."""
    offered = {(new, saved) for new, ids in (found or {}).get("new", {}).items() for saved in ids}
    back = _refs(found)[1] if found else {}
    kept = {}
    for item in (answer or {}).get("conflicts") or []:
        if not isinstance(item, dict):
            continue
        pair = (item.get("finding"), back.get(item.get("with"), item.get("with")))
        if pair in offered and item.get("reading") in READINGS and pair not in kept:
            reason = " ".join(str(item.get("reason") or "").split())
            reason = re.sub(r"(?<![\w:])s\d+(?![\w-])", lambda m: back.get(m.group(0), m.group(0)), reason)  # s1: its id.
            kept[pair] = {"finding": pair[0], "with": pair[1], "reading": item["reading"], "reason": reason[:600]}
    return list(kept.values())


# ----- recording and settling -----

def _identifier(question_id, finding, other):
    return "conflict:%s-%s" % (question_id[:12], digest([finding, other])[:10])


def _linked(db, identifier, other, add):
    row = db.execute("SELECT detail FROM findings WHERE id=?", (identifier,)).fetchone()
    if row is None:
        return
    current = list((json.loads(row[0]) if row[0] else {}).get("conflictsWith") or [])
    if add:
        changed = current if other in current else current + [other]
    else:
        changed = [i for i in current if i != other]
    if changed != current:
        knowledge._set_detail(db, identifier, conflictsWith=changed or None)


def _link(db, first, second, add=True):
    _linked(db, first, second, add)
    _linked(db, second, first, add)


def _reject(db, identifier, other, conflict, reason, *, by, engine, stamp):
    """A finding a conflict showed misstates its source: Rejected; a Reviewed one judged so by a second reviewer (not a
    person) becomes Needs checking, as a second review's unsupported verdict makes it. A spot check or recheck it was
    waiting for is called off, so a later review cannot undo the decision. Returns whether it changed."""
    row = db.execute("SELECT status, detail FROM findings WHERE id=?", (identifier,)).fetchone()
    if row is None or row[0] == knowledge.UNSUPPORTED:
        return False
    reviewed = row[0] == knowledge.SUPPORTED and by != "person"
    status = knowledge.UNCERTAIN if reviewed else knowledge.UNSUPPORTED
    said = ("A person judged that it conflicts with %s and misstates its source: %s" if by == "person" else
            "A consistency review found it conflicts with %s and misstates its source: %s") % (other, reason)
    db.execute("UPDATE findings SET status=?, review_reason=?, reviewer_engine=?, reviewed_at=? WHERE id=?",
               (status, said[:600], engine, stamp, identifier))
    detail = json.loads(row[1]) if row[1] else {}
    calls_off = {key: "called-off" for key in ("spotCheck", "recheck") if detail.get(key) == "pending"}
    knowledge._set_detail(db, identifier, conflict={"id": conflict, "with": other, "by": by, "at": stamp}, **calls_off)
    return True


def record(db, question_id, conflicts, verdicts, *, engine, stamp, resolution, compared):
    """A review's conflicts, inside its transaction. With `reviewer` resolution its reading takes effect (a new
    finding the same review found supported is not rejected: that conflict is unresolved); with `person` the conflict
    waits, with the reviewer's reading as a suggestion. Findings in a conflict left standing are linked. A finding
    changes status once per review, from the status it had before it, however many conflicts name it."""
    changed = set()
    for item in conflicts:
        finding, other, reading = item["finding"], item["with"], item["reading"]
        identifier = _identifier(question_id, finding, other)
        if db.execute("SELECT 1 FROM conflicts WHERE id=?", (identifier,)).fetchone():
            continue
        applied = reading
        if resolution == "person":
            applied = None
        elif reading == "new-misread" and (verdicts.get(finding) or {}).get("verdict") == knowledge.SUPPORTED:
            applied = "unresolved"
        if applied in ("new-misread", "saved-misread"):
            target, partner = (finding, other) if applied == "new-misread" else (other, finding)
            if target not in changed and _reject(db, target, partner, identifier, item["reason"], by="reviewer",
                                                 engine=engine, stamp=stamp):
                changed.add(target)
        else:
            _link(db, finding, other)
        settled = applied in ("new-misread", "saved-misread", "sources-disagree")
        db.execute("INSERT INTO conflicts (id, question_id, finding_id, other_id, reading, reason, engine, found_at, "
                   "status, resolution, settled_by, settled_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            identifier, question_id, finding, other, reading, item["reason"], engine, stamp,
            "settled" if settled else "open", applied if settled else None, "reviewer" if settled else None,
            stamp if settled else None, None))
    db.execute("UPDATE deposits SET consistency='checked', consistency_compared=? WHERE question_id=?",
               (compared, question_id))


def settle(root, identifier, resolution, note="", person=None):
    """A person settles an open conflict: the new finding misstates its source, the saved one does (either is then
    Rejected, judged by a person), the sources disagree (both stay, linked), or there is no conflict (both stay,
    unlinked). Nothing a person does marks a finding Reviewed. One write transaction that reads the conflict's status
    first, so it never waits for a review's engine session, and two people settling one conflict cannot both win.
    `person`, on a host several people share (`people`), is recorded as who settled it."""
    if resolution not in SETTLEMENTS:
        raise ValueError("A conflict is settled as one of: " + ", ".join(SETTLEMENTS))
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("A note is text of at most 1000 characters")
    with knowledge.connect(root, write=True) as db:
        row = db.execute("SELECT * FROM conflicts WHERE id=?", (identifier,)).fetchone()
        if row is None or row["status"] != "open":
            raise ValueError("No open conflict %s" % identifier)
        new, saved = _live(db, row["finding_id"]), _live(db, row["other_id"])
        stamp, reason = now(), " ".join(note.split()) or row["reason"] or "no reason given"
        if resolution in ("new-misread", "saved-misread"):
            target, other = (new, saved) if resolution == "new-misread" else (saved, new)
            if target is None:
                raise ValueError("That finding is no longer saved; settle the conflict another way")
            _reject(db, target, other or "a finding no longer saved", identifier, reason, by="person",
                    engine="person", stamp=stamp)
        if new and saved and new != saved:
            _link(db, new, saved, add=resolution == "sources-disagree")
        db.execute("UPDATE conflicts SET status='settled', resolution=?, settled_by='person', settled_at=?, note=?, "
                   "settled_person=? WHERE id=?", (resolution, stamp, note.strip()[:1000] or None,
                                                   (person or {}).get("name"), identifier))
    return conflict(root, identifier)


def _live(db, identifier):
    """A finding id, or the one it was merged into (`upkeep.duplicates`); None when neither is saved."""
    seen = set()
    while identifier and identifier not in seen:
        if db.execute("SELECT 1 FROM findings WHERE id=?", (identifier,)).fetchone():
            return identifier
        seen.add(identifier)
        found = db.execute("SELECT into_id FROM merged WHERE id=?", (identifier,)).fetchone()
        identifier = found[0] if found else None
    return None


def merged(db, removed, keeper):
    """Before `upkeep.duplicates` deletes a finding merged into another, its conflict links move to the one it keeps."""
    row = db.execute("SELECT detail FROM findings WHERE id=?", (removed,)).fetchone()
    for other in (json.loads(row[0]) if row and row[0] else {}).get("conflictsWith") or []:
        _linked(db, other, removed, False)
        if other != keeper:
            _link(db, keeper, other)


def _conflict_view(db, row):
    ids = {key: _live(db, row[key]) for key in ("finding_id", "other_id")}
    findings = {r["id"]: knowledge.finding_view(r) for r in db.execute(
        "SELECT * FROM findings WHERE id IN (?, ?)", (ids["finding_id"], ids["other_id"]))}
    return {"id": row["id"], "questionId": row["question_id"], "finding": findings.get(ids["finding_id"]),
            "other": findings.get(ids["other_id"]), "reading": row["reading"], "reason": row["reason"],
            "engine": row["engine"], "foundAt": row["found_at"], "status": row["status"],
            "resolution": row["resolution"], "settledBy": row["settled_by"], "settledAt": row["settled_at"],
            "note": row["note"], **({"settledByName": row["settled_person"]}
                                    if "settled_person" in row.keys() and row["settled_person"] else {})}


def conflict(root, identifier):
    with knowledge.connect(root) as db:
        row = db.execute("SELECT * FROM conflicts WHERE id=?", (identifier,)).fetchone()
        return _conflict_view(db, row) if row else None


def conflicts(root, status=None, limit=50):
    """Conflicts newest first (`open` ones waiting for a person, or `settled`), each with both findings."""
    if not knowledge.database(root).exists():
        return []
    with knowledge.connect(root) as db:
        where, args = ("WHERE status=?", (status,)) if status else ("", ())
        rows = db.execute("SELECT * FROM conflicts %s ORDER BY found_at DESC, id LIMIT ?" % where,
                          (*args, int(limit))).fetchall()
        return [_conflict_view(db, row) for row in rows]


def stats(root):
    """Conflicts by status and reading, and answers by consistency state."""
    empty = {"open": 0, "settled": 0, "readings": {}, "answers": {}}
    if not knowledge.database(root).exists():
        return empty
    with knowledge.connect(root) as db:
        statuses = dict(db.execute("SELECT status, COUNT(*) FROM conflicts GROUP BY status").fetchall())
        readings = dict(db.execute("SELECT reading, COUNT(*) FROM conflicts GROUP BY reading").fetchall())
        answers = dict(db.execute("SELECT consistency, COUNT(*) FROM deposits WHERE consistency IS NOT NULL "
                                  "GROUP BY consistency").fetchall())
    return {"open": statuses.get("open", 0), "settled": statuses.get("settled", 0), "readings": readings,
            "answers": answers}
