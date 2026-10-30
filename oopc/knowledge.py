"""The knowledge the loop accumulates: findings, source notes and their reviews.

A finding is one source-qualified value a researcher read: a statement with its
material, property, value, unit and conditions, plus the source, an exact
locator and the shortest verbatim span of the source that shows the value.

By default a finding the researcher read in a source's text or a table is
`accepted` (added on its judgement, not independently checked) and one it read
off a figure, converted or combined goes to review as `unreviewed`. In the
"review everything" mode every finding starts `unreviewed`. A share of accepted
findings (`spot_check_rate`, 20% by default) is also sampled for review, to
measure how often the researcher's judgement is wrong.

There is one review queue: an answer's flagged and sampled findings are checked
together by one reviewer call after the answer is delivered, and each takes the
reviewer's verdict (`supported`, `unsupported` or `uncertain`, with a reason). A
failed review is retried once. Searches return the most relevant findings and
the other findings saved from the same sources; unsupported ones are hidden.

A finding that repeats one already known (same source and the same fact) is not
saved again; the deposit records which existing finding it matched.

Source notes record what each source a researcher actually read supports. They
are leads for later questions, never reviewed facts.

Everything lives in one private SQLite file under `.oopc/loop/`.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .util import now, private_sqlite, sqlite_close, sqlite_open

UNREVIEWED, SUPPORTED, UNSUPPORTED, UNCERTAIN = "unreviewed", "supported", "unsupported", "uncertain"
ACCEPTED = "accepted"  # Added on the researcher's judgement; not independently reviewed.
VERDICTS = (SUPPORTED, UNSUPPORTED, UNCERTAIN)
STATUSES = (ACCEPTED, UNREVIEWED) + VERDICTS
FINDING_FIELDS = ("statement", "material", "property", "value", "unit", "conditions", "subject",
                  "sourceTitle", "sourceUrl", "sourceDoi", "locator", "excerpt")
NOTE_FIELDS = ("title", "url", "doi", "locator", "supports", "conditions")
LIMITS = {"statement": 2000, "excerpt": 1200, "conditions": 1500, "locator": 500, "sourceTitle": 500,
          "sourceUrl": 1000, "sourceDoi": 200, "material": 500, "property": 300, "value": 200, "unit": 100}
MAX_FINDINGS, MAX_NOTES = 40, 40
WOP = re.compile(r"^wop-\d{6}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, question_id TEXT, origin TEXT, statement TEXT,
    material TEXT, property TEXT, value TEXT, unit TEXT, conditions TEXT, subject TEXT, source_title TEXT,
    source_url TEXT, source_doi TEXT, locator TEXT, excerpt TEXT, status TEXT, review_reason TEXT,
    reviewer_engine TEXT, reviewed_at TEXT, producer_engine TEXT, created_at TEXT, detail TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, question_id TEXT, origin TEXT, title TEXT, url TEXT,
    doi TEXT, locator TEXT, excerpts TEXT, supports TEXT, conditions TEXT, created_at TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS deposits (question_id TEXT PRIMARY KEY, origin TEXT, engine TEXT, deposited_at TEXT,
    findings INTEGER, notes INTEGER, dropped INTEGER, review_status TEXT, review_attempts INTEGER DEFAULT 0,
    reviewed_at TEXT, review_engine TEXT, review_error TEXT);
CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, question_id TEXT, engine TEXT, started_at TEXT,
    finished_at TEXT, status TEXT, reason TEXT, seconds REAL, usage TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS merged (id TEXT PRIMARY KEY, into_id TEXT, merged_at TEXT, row TEXT);
"""
ADDED_COLUMNS = {"deposits": {"duplicates": "INTEGER DEFAULT 0", "duplicate_of": "TEXT"}, "notes": {"read_url": "TEXT"}}


def folder(root):
    return Path(root).resolve() / ".oopc" / "loop"


def database(root):
    return folder(root) / "knowledge.sqlite"


@contextmanager
def connect(root):
    path = database(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite_open(private_sqlite(path), timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            present = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
            for name, kind in columns.items():
                if name not in present:
                    db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, kind))
        with db:
            yield db
    finally:
        sqlite_close(db)


def _text(value, limit=2000):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


# How the researcher got a value. Only a value read off a figure, converted or calculated, or combined from more than
# one place is reviewed before use (owner, 2026-10-14: free-form doubt flags caught 1 error in 1,868); a value read in
# the text or a table is added at once, and a random sample of those is reviewed.
DERIVATIONS = {"read": "", "figure": "Read from a figure", "converted": "Converted or calculated",
               "combined": "Combined from more than one place"}


def clean_finding(item):
    """A well-formed finding, or None. Needs a statement, a source and a locator or excerpt."""
    if not isinstance(item, dict):
        return None
    value = {key: _text(item.get(key), LIMITS.get(key, 2000)) for key in FINDING_FIELDS}
    if value["sourceDoi"] and not value["sourceUrl"]:
        value["sourceUrl"] = "https://doi.org/" + value["sourceDoi"].removeprefix("https://doi.org/")
    if not WOP.match(value["subject"]):
        value["subject"] = ""
    if not value["statement"] or not (value["sourceUrl"] or value["sourceDoi"]) or not (value["locator"] or value["excerpt"]):
        return None
    derivation = item.get("derivation")
    if derivation in DERIVATIONS:
        value["needsReview"], value["reviewFlag"] = derivation != "read", DERIVATIONS[derivation]
    else:  # Answers stored before 2026-10-14 carry the researcher's own flag and reason.
        value["needsReview"] = item.get("needsReview") is not False
        value["reviewFlag"] = _text(item.get("reviewFlag"), 300)
    return value


SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


SIGN = r"(?:(?<![\w.])[-−–](?=\d))?"  # a minus that starts a number, not one between numbers ("10-20")


def _numbers(text):
    """The numbers in `text` with their signs, written alike: "1,200" and "1200", "45.0" and "45", "10⁻²⁰" and
    "10-20", "−134.3" and "-134.3" (but not "134.3": a sign makes another number)."""
    text = (text or "").translate(SUPERSCRIPTS)
    text = re.sub(r"(?<=\d)[,  ](?=\d{3}\b)", "", text)
    numbers = set()
    for n in re.findall(SIGN + r"\d+(?:[.,]\d+)?", text):
        n = re.sub(r"^[−–]", "-", n)
        numbers.add(n.replace(",", ".").rstrip("0").rstrip(".") if re.search(r"[.,]", n) else n)
    return numbers


UNIT_WORDS = {"wt", "vol", "mol", "phr", "min", "mm", "cm", "nm", "µm", "μm", "mg", "kg", "mpa", "gpa", "kpa", "pa",
              "kv", "hz", "khz", "mhz", "ghz", "kj", "mj", "ev", "ppm", "rpm", "ml", "µl", "days", "weeks", "hours", "to",
              "and", "or", "approximately", "about"}


def bare_excerpt(excerpt, unit=""):
    """An excerpt that shows a number but no label ("107", "45 %", "650 MPa", "10 to 40"): once the unit is removed,
    no word of two letters or more (other than a unit word), no sample code (A4, M710, PA12) and no symbol (σ, ΔH) is
    left. An empty excerpt is bare too; "Tg 58.5 °C", "A4 56.8 40.6" and "∆H (J/g) | 46.52" are not."""
    text = (excerpt or "").replace(unit or "\0", " ")
    words = re.findall(r"[^\W\d_]{2,}", text)
    if [w for w in words if w.lower() not in UNIT_WORDS and w.lower() not in (unit or "").lower().split()]:
        return False
    code = re.search(r"(?<![\w.])[A-Za-z]{1,4}-?\d+[A-Za-z\d-]*(?![\w.])", text)
    return not (code or re.search(r"[Ͱ-Ͽ∆]", text))


def clean_note(item):
    if not isinstance(item, dict):
        return None
    value = {key: _text(item.get(key), 1000) for key in NOTE_FIELDS}
    excerpts = [_text(entry, LIMITS["excerpt"]) for entry in (item.get("excerpts") or []) if isinstance(entry, str) and entry.strip()]
    value["excerpts"] = excerpts[:5]
    read = _text(item.get("readUrl"), 1000)
    value["readUrl"] = read if re.match(r"https?://[^\s/@]+(/|$)", read) else ""
    if not (value["url"] or value["doi"]) or not (value["supports"] or value["excerpts"]):
        return None
    return value


def _finding_text(finding):
    return " ".join(str(finding.get(key) or "") for key in ("statement", "material", "property", "value", "unit",
                                                             "conditions", "sourceTitle", "excerpt", "subject"))


def _note_text(note):
    return " ".join([note["title"] or "", note["supports"] or "", note["conditions"] or "", note["locator"] or "",
                     *note["excerpts"]])


def source_key(doi, url):
    """One key per document: its DOI when known (also from a doi.org URL), else its URL without scheme or query."""
    doi = (doi or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    doi = doi or (re.match(r"^https?://(?:dx\.)?doi\.org/(.+)$", (url or "").strip().lower()) or [None, ""])[1]
    if doi:
        return "doi:" + doi
    url = re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).split("#")[0].split("?")[0].rstrip("/")
    return "url:" + url if url else ""


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower()))


def same_fact(a, b):
    """Same source and the same numbers, and either a near-identical statement or the same
    property, value, unit and material."""
    if not source_key(a["sourceDoi"], a["sourceUrl"]) or source_key(a["sourceDoi"], a["sourceUrl"]) != source_key(b["sourceDoi"], b["sourceUrl"]):
        return False
    # Rows of one table read alike and differ only in their numbers: different numbers, different facts.
    # Read as written, with their signs (a table's −134.3 J/g and its text's 134.3 J/g are two readings): not through
    # `_numbers`, whose "1.0"/"1" and "m²"/"m2" readings made a modulus and a yield strength of one film alike.
    numbers = lambda f: {re.sub(r"^[−–]", "-", n) for n in
                         re.findall(SIGN + r"\d+(?:\.\d+)?", (f["statement"] or "") + " " + (f["value"] or ""))}
    if numbers(a) != numbers(b):
        return False
    first, second = _tokens(a["statement"]), _tokens(b["statement"])
    overlap = len(first & second) / len(first | second) if first and second else 0
    if overlap >= 0.75:
        return True
    # The same reported number for the same property and material, said differently.
    same = lambda key: (a[key] or "").strip().lower() == (b[key] or "").strip().lower()
    if overlap >= 0.4 and bool(a["value"]) and all(same(key) for key in ("value", "unit", "property", "material")):
        return True
    # The same number in the same unit, for a material one of them names more specifically ("Agilent PMMA" and
    # "Agilent PMMA, Mp series"). The values themselves must agree (a grade number in one statement is not a value),
    # and a control, blank or reference is another specimen.
    material = lambda f: _tokens(f["material"]) - {"neat"}
    first, second = material(a), material(b)
    return (bool(_numbers(a["value"])) and _numbers(a["value"]) == _numbers(b["value"]) and same("unit")
            and bool(first and second) and (first <= second or second <= first)
            and not (first ^ second) & {"control", "controls", "blank", "blanks", "reference"})


def _row_fact(row):
    return {"statement": row["statement"], "material": row["material"], "property": row["property"],
            "value": row["value"], "unit": row["unit"], "sourceDoi": row["source_doi"], "sourceUrl": row["source_url"]}


def _known_match(db, finding):
    """An existing finding with the same fact, preferring one that is not unsupported."""
    key = source_key(finding["sourceDoi"], finding["sourceUrl"])
    if not key:
        return None
    needle = key.split(":", 1)[1]
    rows = db.execute("SELECT * FROM findings WHERE instr(lower(source_doi), ?) OR instr(lower(source_url), ?)",
                      (needle, needle)).fetchall()
    matches = [row for row in rows if same_fact(finding, _row_fact(row))]
    return min(matches, key=lambda row: row["status"] == UNSUPPORTED) if matches else None


def sampled(identifier, rate):
    """A stable per-finding draw, so a spot-check sample never depends on timing."""
    return int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) / 0x100000000 < rate


def deposit(root, question_id, answer, *, engine, origin="ask", review_mode="researcher", spot_check_rate=0.2,
            question=""):
    """Save a finished answer's findings and notes. Idempotent per question.

    With `review_mode="researcher"`, findings the researcher did not flag are
    accepted at once and flagged ones wait for review; with `"all"` every finding
    waits for review. A sample of accepted findings joins the same review.
    """
    raw_findings = answer.get("findings") if isinstance(answer.get("findings"), list) else []
    raw_notes = answer.get("sources") if isinstance(answer.get("sources"), list) else []
    findings = [f for f in (clean_finding(item) for item in raw_findings[:MAX_FINDINGS]) if f]
    notes = [n for n in (clean_note(item) for item in raw_notes[:MAX_NOTES]) if n]
    dropped = len(raw_findings[:MAX_FINDINGS]) - len(findings)
    stamp = now()
    with connect(root) as db:
        if db.execute("SELECT 1 FROM deposits WHERE question_id=?", (question_id,)).fetchone():
            return deposit_summary(root, question_id)
        kept, duplicate_of = [], []
        for finding in findings:
            match = _known_match(db, finding) or next((f for f in kept if same_fact(finding, f)), None)
            if match is None:
                kept.append(finding)
            elif isinstance(match, sqlite3.Row) and match["status"] == UNSUPPORTED:
                # A fact found unsupported before comes back: keep it, but only after review.
                kept.append(dict(finding, needsReview=True, reviewFlag="A matching finding was judged unsupported before"))
            else:
                duplicate_of.append(match["id"] if isinstance(match, sqlite3.Row) else "")
        # A finding is filed under the polymer its material names, else the one polymer its question is about
        # ("Viton A-200" in a question about FKM): the context says which polymer a trade or grade name means. A
        # finding that names several polymers (a blend) is filed under the question's only when that settles it.
        # A name the graph gives to unrelated polymers is settled from the question and what the answer says of the
        # source, and written out; one the context cannot settle is never added unreviewed in that form.
        settled = []
        for finding in kept:
            context = " ".join([question or "", finding["sourceTitle"], _note_context(notes, finding)])
            finding, unsettled = settle_names(root, finding, context)
            if unsettled:
                finding.update(needsReview=True, reviewFlag=ambiguity_flag(unsettled),
                               ambiguous=[n["name"] for n in unsettled])
            settled.append(finding)
        findings = [dict(f, subject=f["subject"] or file_subject(root, f, question)[0]) for f in settled]
        statuses = [UNREVIEWED if review_mode == "all" or finding["needsReview"] else ACCEPTED for finding in findings]
        identifiers = ["finding:%s-%d" % (question_id[:12], index) for index in range(1, len(findings) + 1)]
        spot = [status == ACCEPTED and sampled(identifier, spot_check_rate) for identifier, status in zip(identifiers, statuses)]
        db.execute("INSERT INTO deposits (question_id, origin, engine, deposited_at, findings, notes, dropped, review_status, "
                   "duplicates, duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (question_id, origin, engine, stamp, len(findings), len(notes), dropped,
                    "pending" if UNREVIEWED in statuses or any(spot) else "nothing-to-review", len(duplicate_of),
                    json.dumps([d for d in duplicate_of if d])))
        for identifier, finding, status, sample in zip(identifiers, findings, statuses, spot):
            detail = {"reviewMode": review_mode, "needsReview": finding["needsReview"]}
            if finding["reviewFlag"]:
                detail["reviewFlag"] = finding["reviewFlag"]
            for key in ("asWritten", "ambiguous"):
                if finding.get(key):
                    detail[key] = finding[key]
            if sample:
                detail["spotCheck"] = "pending"
            _insert_finding(db, identifier, question_id, origin, finding,
                            status=status, producer_engine=engine, created_at=stamp, detail=detail)
        for index, note in enumerate(notes, 1):
            _insert_note(db, "note:%s-%d" % (question_id[:12], index), question_id, origin, note, created_at=stamp)
    return deposit_summary(root, question_id)


def _meant(polymers):
    """The ids the named polymers stand for: a name the graph gives to several polymers ("PEI") means the one of them
    the text also names in full ("Polyetherimide (PEI)"), else all of them."""
    single = set().union(*(p["ids"] for p in polymers if len(p["ids"]) == 1)) if polymers else set()
    return set().union(*((p["ids"] & single) or p["ids"] for p in polymers)) if polymers else set()


def _note_context(notes, finding):
    """What an answer's source notes say of a finding's source (title, what it supports, conditions, excerpts)."""
    key = source_key(finding.get("sourceDoi"), finding.get("sourceUrl"))
    return " ".join(" ".join([n.get("title", ""), n.get("supports", ""), n.get("conditions", ""), *n.get("excerpts", [])])
                    for n in notes if key and source_key(n.get("doi"), n.get("url")) == key)


def infer_subject(root, finding):
    """The graph polymer id a finding's material names, when it names exactly one polymer."""
    for text, strict in ((finding.get("material"), False), (finding.get("statement"), True)):
        polymers, _ = _query_parts(root, text or "", strict=strict)
        ids = _meant(polymers)
        if len(ids) == 1:
            return next(iter(ids))
        if ids:
            return ""
    return ""


def _named_ids(root, text, strict=True):
    polymers, _ = _query_parts(root, text or "", strict=strict)
    return _meant(polymers)


def _ancestors(root, identifier):
    up, found, todo = _graph_families(root)[0], set(), [identifier]
    while todo:
        for parent in up.get(todo.pop(), ()):
            if parent not in found:
                found.add(parent)
                todo.append(parent)
    return found


def file_subject(root, finding, question=""):
    """The polymer id a finding belongs under and the rule that decided ("" and why when none does): its own text naming
    one polymer; a member named beside its own family, the member; a name the graph gives to two polymers (PEI, PFA),
    settled by the polymer its question names; a text that names no polymer, its question's one polymer."""
    own = infer_subject(root, finding)
    if own:
        return own, "own text"
    named = _named_ids(root, (finding.get("material") or "") + "; " + (finding.get("statement") or ""), strict=False)
    asked = _named_ids(root, question)
    if named:
        narrowest = {i for i in named if not any(i in _ancestors(root, j) for j in named if j != i)}
        if len(narrowest) == 1:
            return next(iter(narrowest)), "member over its family"
        settled = named & lineage(root, asked) if asked else set()
        return (next(iter(settled)), "question") if len(settled) == 1 else ("", "several polymers")
    return (next(iter(asked)), "question") if len(asked) == 1 else ("", "no polymer named")


def question_subject(root, question):
    """The graph polymer id of the one polymer a question names, or "" when it names none, several, or an
    ambiguous one."""
    polymers, _ = _query_parts(root, question or "")
    ids = set().union(*(p["ids"] for p in polymers)) if polymers else set()
    return next(iter(ids)) if len(ids) == 1 else ""


def ambiguous_polymers(root, text, strict=True):
    """Names in `text` that the graph gives to unrelated polymers (PEI: polyetherimide or polyethyleneimine), unless
    the text also names one of them unambiguously; each with the polymers it could mean."""
    polymers, _ = _query_parts(root, text or "", strict=strict)
    named = set().union(*(p["ids"] for p in polymers if len(p["ids"]) == 1)) if polymers else set()
    labels = _graph_families(root)[2]
    found = []
    for p in polymers:
        ids = sorted(p["ids"])
        if len(ids) > 1 and not named & p["ids"] and any(b not in lineage(root, {a}) for a in ids for b in ids):
            written = re.search(r"(?<![\w-])" + re.escape(p["name"]) + r"(?![\w-])", text, re.I)
            found.append({"name": written.group(0) if written else p["name"],
                          "options": [{"id": i, "label": labels.get(i, i)} for i in ids]})
    return found


def settle_names(root, finding, context=""):
    """A finding whose material or statement uses a name the graph gives to unrelated polymers (PEI, PFA), with each
    such name settled by `context` (its question, its source's title and notes, the source's captured text) and written
    out as the polymer meant ("Polyetherimide (PEI)"), so the stored label cannot be misread later. Returns the finding
    (with the replaced text in `asWritten`) and the names the context could not settle, each with the polymers it could
    mean. A name is settled when the context names exactly one of its polymers (or a family or member of one) in full."""
    finding, unsettled, labels = dict(finding), [], _graph_families(root)[2]
    polymers, _ = _query_parts(root, context or "", strict=False)
    named = lineage(root, set().union(*(p["ids"] for p in polymers if len(p["ids"]) == 1))) if polymers else set()
    for name in ambiguous_polymers(root, (finding.get("material") or "") + "; " + (finding.get("statement") or ""),
                                   strict=False):
        meant = [o["id"] for o in name["options"] if o["id"] in named]
        if len(meant) != 1:
            unsettled.append(name)
            continue
        _write_out(finding, name["name"], labels.get(meant[0], meant[0]))
    # An abbreviation that is also a common word (MC: methyl cellulose or moisture content) never names a polymer in a
    # finding's text by itself; written in capitals where the context names its polymer in full, it is written out.
    text = (finding.get("material") or "") + " " + (finding.get("statement") or "")
    plain = lambda s: re.sub(r"[‐‑–—-]", "-", s).lower()
    for word in _common_word_names(root, text):
        meant = sorted(polymer_ids(root, word) & named)
        # Already written out: the polymer's name is there, or the abbreviation is defined in parentheses.
        if len(meant) == 1 and plain(labels.get(meant[0], meant[0])) not in plain(text) and "(%s)" % word not in text:
            _write_out(finding, word, labels.get(meant[0], meant[0]))
    return finding, unsettled


def _common_word_names(root, text):
    """Abbreviations written in capitals that name a polymer but are also common words (MC, MF, CR)."""
    return [w for w in dict.fromkeys(re.findall(r"(?<![\w-])([A-Z]{2,3})(?![\w-])", text or ""))
            if w.lower() in AMBIGUOUS and polymer_ids(root, w)]


def may_misread(root, text):
    """Whether a finding's text uses a polymer name that its own words do not settle: one the graph gives to unrelated
    polymers (PEI), or an abbreviation that is also a common word (MC)."""
    return bool(ambiguous_polymers(root, text, strict=False) or _common_word_names(root, text))


def _write_out(finding, name, label):
    """Replace the first standalone `name` in a finding's material, else its statement, with "Label (name)" (a family
    record's label without its "family": "Phenol–formaldehyde resin (PF)")."""
    label = re.sub(r"\s+family$", "", label, flags=re.I)
    written = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
    for key in ("material", "statement"):
        if written.search(finding.get(key) or ""):
            finding.setdefault("asWritten", {}).setdefault(key, finding[key])
            finding[key] = written.sub(label + " (" + name + ")", finding[key], 1)
            return


def ambiguity_flag(unsettled):
    return "Ambiguous polymer name: " + "; ".join("%s could be %s" % (n["name"], " or ".join(o["label"] for o in n["options"]))
                                                   for n in unsettled)


def _insert_finding(db, identifier, question_id, origin, finding, *, status, producer_engine, created_at,
                    review_reason="", reviewer_engine="", reviewed_at="", detail=None):
    cursor = db.execute("INSERT OR IGNORE INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        identifier, question_id, origin, finding["statement"], finding["material"], finding["property"],
        finding["value"], finding["unit"], finding["conditions"], finding["subject"], finding["sourceTitle"],
        finding["sourceUrl"], finding["sourceDoi"], finding["locator"], finding["excerpt"], status, review_reason,
        reviewer_engine, reviewed_at, producer_engine, created_at,
        json.dumps(detail, ensure_ascii=False) if detail is not None else None))
    if cursor.rowcount:
        db.execute("INSERT INTO findings_fts VALUES (?,?)", (identifier, _finding_text(finding)))


def _insert_note(db, identifier, question_id, origin, note, *, created_at):
    cursor = db.execute("INSERT OR IGNORE INTO notes (id, question_id, origin, title, url, doi, locator, excerpts, supports, "
                        "conditions, created_at, read_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
        identifier, question_id, origin, note["title"], note["url"], note["doi"], note["locator"],
        json.dumps(note["excerpts"], ensure_ascii=False), note["supports"], note["conditions"], created_at,
        note.get("readUrl", "")))
    if cursor.rowcount:
        db.execute("INSERT INTO notes_fts VALUES (?,?)", (identifier, _note_text(note)))


def finding_view(row, full=False, compact=False):
    """`compact` is what a researcher's search gets: enough to cite or to decide to open it."""
    limit = 250 if compact else None if full else 400
    cut = (lambda text, n: (text or "")[:n]) if compact else (lambda text, n: text)
    value = {"id": row["id"], "status": row["status"], "statement": cut(row["statement"], 300),
             "material": cut(row["material"], 120), "property": cut(row["property"], 80), "value": row["value"],
             "unit": row["unit"], "conditions": cut(row["conditions"], 300), "subject": row["subject"],
             "source": {k: v for k, v in (("title", cut(row["source_title"], 200)), ("url", row["source_url"]),
                                          ("doi", row["source_doi"])) if v},
             "locator": cut(row["locator"], 120), "excerpt": (row["excerpt"] or "")[:limit] if limit else row["excerpt"]}
    if row["status"] in VERDICTS:
        # In a search, a supported verdict needs no reason; an inconclusive one keeps the qualifier left open.
        reason = "" if compact and row["status"] == SUPPORTED else cut(row["review_reason"], 160)
        value["review"] = {"verdict": row["status"], "reason": reason, "engine": row["reviewer_engine"],
                           "reviewedAt": "" if compact else row["reviewed_at"]}
        value["review"] = {k: v for k, v in value["review"].items() if v}
    detail = json.loads(row["detail"]) if row["detail"] else {}
    if detail.get("reviewFlag"):
        value["reviewFlag"] = cut(detail["reviewFlag"], 160)
    if not compact:
        value["producerEngine"] = row["producer_engine"]
    if detail.get("originalStatement") and not compact:
        value["originalStatement"] = detail["originalStatement"]  # An imported label rewritten as a sentence.
    if detail.get("titleAsWritten") and not compact:
        value["titleAsWritten"] = detail["titleAsWritten"]  # The researcher's title, replaced by its DOI's.
    if full:
        value.update(questionId=row["question_id"], origin=row["origin"], producerEngine=row["producer_engine"],
                     createdAt=row["created_at"])
        # What a reviewer is asked to return besides its verdict.
        value["asks"] = [ask for ask, wanted in (("material", detail.get("ambiguous")),
                                                 ("excerpt", detail.get("needsExcerpt"))) if wanted] or None
    return {k: v for k, v in value.items() if v not in ("", None, {})}


def note_view(row, compact=False):
    excerpts = json.loads(row["excerpts"] or "[]")
    trim = (lambda text, n: (text or "")[:n]) if compact else (lambda text, n: text)
    if compact:
        excerpts = [e[:200] for e in excerpts[:1]]
    value = {"id": row["id"], "title": trim(row["title"], 300), "url": row["url"], "doi": row["doi"],
             "locator": trim(row["locator"], 160), "excerpts": excerpts, "supports": trim(row["supports"], 200),
             "conditions": trim(row["conditions"], 150),
             "readUrl": row["read_url"] if "read_url" in row.keys() else ""}
    return {k: v for k, v in value.items() if v not in ("", None, [])}


SUFFIXES = ("ations", "ation", "ings", "ing", "ities", "ity", "ies", "ed", "es", "s")


def stem(word):
    """A crude stem, so "melting" also finds "melted" and "crystallinity" finds "crystalline"."""
    for suffix in SUFFIXES:
        if len(word) >= 6 and word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def _match(query, extra=()):
    tokens = [stem(t) for t in re.findall(r"[\w-]+", query or "", flags=re.UNICODE) if len(t) > 1][:16]
    tokens += [t for t in extra if t.lower() not in {x.lower() for x in tokens}][:12]
    return " OR ".join('"' + token.replace('"', '""') + '"*' for token in tokens)


_GRAPH_NAMES = {}
_ALIASES = {}


def _graph_names(release):
    """Each graph polymer record's id and names (name, abbreviations, other names, trade names), cached per release.
    A trade name is in the seed only when its scope is one polymer (independent review, 2026-10-14)."""
    if str(release) not in _GRAPH_NAMES:
        found = []
        database_path = release / "graph.sqlite"
        if database_path.exists():
            db = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
            try:
                for (text,) in db.execute("SELECT json FROM records WHERE type='PolymerConcept'"):
                    record = json.loads(text)
                    found.append((record.get("@id") if isinstance(record.get("@id"), str) else None,
                                  [record.get("label"), record.get("canonicalName"), *(record.get("abbreviations") or []),
                                   *(record.get("alternateNames") or []),
                                   *(t.get("name") for t in record.get("tradeNames") or [] if isinstance(t, dict))]))
            finally:
                db.close()
        _GRAPH_NAMES[str(release)] = found
    return _GRAPH_NAMES[str(release)]


ONTOLOGY = "ontology.json"  # The ontology overlay `reflect` writes: reviewed names, polymer ids and property terms.
_OVERLAY = {}


def ontology_edits(root):
    """The edits in the workspace's ontology overlay (`.oopc/loop/ontology.json`, written by `reflect`), applied and
    reverted, cached until the file changes. Empty when there is none."""
    path = folder(root) / ONTOLOGY
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _OVERLAY.get(str(path), (None,))[0] != key:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        edits = value.get("edits") if isinstance(value, dict) else None
        _OVERLAY[str(path)] = (key, [e for e in edits or [] if isinstance(e, dict)])
    return _OVERLAY[str(path)][1]


def ontology_names(root):
    """The names the overlay adds to graph polymers, as (polymer id, name) pairs, in the order they were applied."""
    return tuple((e["fields"]["polymer"], e["fields"]["name"]) for e in ontology_edits(root)
                 if e.get("type") == "name" and e.get("status") == "applied" and isinstance(e.get("fields"), dict)
                 and isinstance(e["fields"].get("polymer"), str) and isinstance(e["fields"].get("name"), str))


def _name_index(root):
    """Name groups and the polymer ids each name belongs to, from the graph's polymer records and the names the
    ontology overlay adds to them, cached per release and overlay."""
    from .util import resolve_release
    try:
        release = resolve_release(root)
    except (ValueError, FileNotFoundError):
        return {}, {}
    added = ontology_names(root)
    key = (str(release), added)
    if key not in _ALIASES:
        groups, ids = {}, {}
        for identifier, names in _graph_names(release):
            names = names + [name for polymer, name in added if identifier and polymer == identifier]
            names = [n.strip() for n in names if isinstance(n, str) and 2 <= len(n.strip()) <= 60]
            names += [n for n in map(_without_generic_tail, names) if n and n not in names]
            for name in names:
                groups.setdefault(name.lower(), set()).update(n for n in names if n.lower() != name.lower())
                if identifier:
                    ids.setdefault(name.lower(), set()).add(identifier)
        _ALIASES[key] = (groups, ids)
    return _ALIASES[key]


def polymer_aliases(root):
    """Name groups from the graph's polymer records (name, abbreviations, other names, trade names) and the names the
    ontology overlay adds to them."""
    return _name_index(root)[0]


_FAMILIES = {}


def _graph_families(root):
    """The graph's broader and narrower links between polymers, and their labels, cached per release."""
    from .util import resolve_release
    try:
        release = resolve_release(root)
    except (ValueError, FileNotFoundError):
        return {}, {}, {}
    if str(release) not in _FAMILIES:
        up, down, labels = {}, {}, {}
        database_path = release / "graph.sqlite"
        if database_path.exists():
            db = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
            try:
                for subject, predicate, obj in db.execute("SELECT subject, predicate, object FROM edges "
                                                          "WHERE predicate IN ('broader', 'narrower')"):
                    (up if predicate == "broader" else down).setdefault(subject, set()).add(obj)
                labels = dict(db.execute("SELECT id, label FROM records WHERE type='PolymerConcept'"))
            finally:
                db.close()
        _FAMILIES[str(release)] = (up, down, labels)
    return _FAMILIES[str(release)]


def lineage(root, ids):
    """The polymers `ids`, every broader family above them and every narrower member below them; not siblings,
    so a search for HDPE finds polyethylene-family findings but not LDPE ones."""
    up, down, _ = _graph_families(root)
    found = set(ids)
    for links in (up, down):
        todo = list(ids)
        while todo:
            for other in links.get(todo.pop(), ()):
                if other not in found:
                    found.add(other)
                    todo.append(other)
    return found


def _without_generic_tail(name):
    """A name without a trailing "family", and without a trailing "resin" when two words remain, so
    "phenol–formaldehyde novolac" names the "Phenol–formaldehyde resin family" (a lone "silicone" names nothing)."""
    shorter = re.sub(r"\s+family$", "", name, flags=re.I)
    rest = re.sub(r"\s+resins?$", "", shorter, flags=re.I)
    if rest != shorter and len(_words(rest).split()) >= 2:
        shorter = rest
    return shorter if shorter != name and len(shorter) >= 4 else None


def polymer_ids(root, name):
    """The graph polymer ids a name belongs to (empty when the graph has none)."""
    return _name_index(root)[1].get(name.lower(), set())


def expand(root, query, terms=()):
    """Other names for polymers named in the query, so "PCL" also finds "polycaprolactone", then the other names of the
    property terms it names (`terms`, from `_property_terms`), so "Tg" also finds "glass transition"."""
    lower = " " + re.sub(r"[^\w()-]+", " ", (query or "").lower()) + " "
    extra = []
    for name, others in polymer_aliases(root).items():
        if " " + name + " " in lower:
            for other in sorted(others):
                extra.extend(re.findall(r"[\w-]+", other, flags=re.UNICODE))
    for term in terms:
        for other in term["others"]:
            extra.extend(re.findall(r"[\w-]+", other, flags=re.UNICODE))
    generic = {"poly", "family", "polymer", "polymers", "resin", "resins", "copolymer", "copolymers", "grade", "grades",
               "the", "of", "and", "acid", "type", "general"}
    return list(dict.fromkeys(t for t in extra if len(t) > 1 and t.lower() not in generic))


STOPWORDS = {"a", "an", "and", "or", "of", "the", "in", "on", "at", "for", "to", "by", "with", "from", "as", "is",
             "are", "was", "were", "be", "what", "how", "does", "do", "did", "which", "that", "this", "vs", "versus",
             "between", "under", "after", "before", "its", "their", "into", "than", "per", "neat"}
# Short polymer abbreviations that are also common technical words; they never restrict a search to a material.
AMBIGUOUS = {"ir", "ms", "co", "ca", "pi", "pt", "ec", "ce", "cf", "rf", "up", "ar", "cr", "cn", "br", "bf", "ep", "mc",
             "ve", "io", "ak", "cm", "mf", "uf", "pf", "nr", "pen", "cap", "san", "par", "pod", "pox", "ver", "pha"}


def _words(text):
    """Lower-case words, with a grade number split from the name before it: "EVOH44" is "evoh 44", "PA6" is "pa 6"."""
    text = re.sub(r"(?<=[^\W\d_]{2})(?=\d)", " ", (text or "").lower())
    return " " + " ".join(re.findall(r"\w+", text, flags=re.UNICODE)) + " "


def _query_parts(root, query, strict=True):
    """The polymers a query names (each with its other names and graph ids) and its remaining words. With
    `strict` off (a finding's material), a three-letter abbreviation that is also a common word (PEN, SAN) counts
    when written in capitals; two-letter ones (IR, CO) never do."""
    lower, polymers, used = _words(query), [], set()
    # Capitals, also after a one-letter tacticity prefix (iPP, sPP).
    capitals = {w.lower() for w in re.findall(r"[^\W\d_]+", query or "") if w.isupper() or re.fullmatch(r"[a-z][A-Z]{2,}", w)}
    for name, others in sorted(polymer_aliases(root).items(), key=lambda item: -len(item[0])):
        phrase = _words(name).strip()
        if not phrase or " " + phrase + " " not in lower or any(set(phrase.split()) <= u for u in used):
            continue
        if len(phrase) <= 3 and ((phrase in AMBIGUOUS and (strict or len(phrase) < 3)) or phrase not in capitals):
            continue
        names = {phrase} | {_words(o).replace(" family ", " ").strip() for o in others}
        # A finding's text names the polymer by these; an abbreviation that is also a common word ("cm", "cn") never
        # counts there, where no capitals can be checked.
        names = {n for n in names if n and n not in AMBIGUOUS}
        polymers.append({"name": name, "names": names or {phrase}, "ids": polymer_ids(root, name)})
        used.add(frozenset(phrase.split()))
    named = set().union(*(set(n.split()) for p in polymers for n in p["names"])) if polymers else set()
    words = [w for w in dict.fromkeys(lower.split()) if len(w) > 1 and w not in STOPWORDS and w not in named]
    return polymers, words


def _mentions(text, name):
    """A whole-word mention, allowing a grade number after it (PHBV28, EVOH44, PLA1)."""
    return re.search(r"(?<!\w)" + re.escape(name) + r"\d*(?!\w)", text) is not None


def _has_word(text, word):
    word = stem(word)
    tail = r"\w*" if len(word) >= 4 else r"(?:\d*|s|es)"
    return re.search(r"(?<!\w)" + re.escape(word) + tail + r"(?!\w)", text) is not None


FILL = 10  # Findings that match only the polymer a query names fill a result up to this many.
SAME_SOURCE = 12  # Other findings from the sources a search returns, so a source already read is not read again.
TERMS = ("property_terms", "finding_terms")  # Read by search only when a store has both (`reflect` writes them).


def _property_terms(db, query, polymers):
    """The property terms `query` names, each with its names, its other names as written, the query words that name
    it and the findings annotated to it. A name counts when it is in the query as whole words, longest names first,
    outside the words a polymer the query names takes ("density" names nothing in "high-density polyethylene"). A
    one-letter name (E, ρ) never counts, as no one-letter word does elsewhere in search."""
    lower = _words(query)
    for p in polymers:
        lower = re.sub(r"(?<= )" + re.escape(_words(p["name"]).strip()) + r"(?= )", "|", lower)
    terms = {}
    for term, names in db.execute("SELECT term, names FROM property_terms ORDER BY term"):
        names = json.loads(names or "[]")
        terms[term] = [n for n in (names if isinstance(names, list) else []) if isinstance(n, str)]
    found = {}
    for phrase, term in sorted({(_words(n).strip(), t) for t, names in terms.items() for n in names},
                               key=lambda item: (-len(item[0]), item)):
        if len(phrase) > 1 and " " + phrase + " " in lower:
            found.setdefault(term, set()).update(phrase.split())
            lower = re.sub(r"(?<= )" + re.escape(phrase) + r"(?= )", "|", lower)
    named = []
    for term, words in found.items():
        names = [n for n in terms[term] if len(_words(n).strip()) > 1]
        annotated = {i for (i,) in db.execute("SELECT finding_id FROM finding_terms WHERE term=?", (term,))}
        named.append({"term": term, "words": words, "names": {_words(n).strip() for n in names},
                      "others": [n for n in names if not set(_words(n).split()) <= words], "findings": annotated})
    return named


def _relevant(rows, about, text, subject, polymers, words, limit, terms=()):
    """Rows about a polymer the query names (when it names one), most query words matched first.

    `about` is the text that says what a row is about; `text` is everything the query words may match.
    A row matching the polymer but none of the other words ("PNIPAM cloud point" for "PNIPAM LCST") is
    kept only to fill a short result, since vocabulary differs between questions and sources. The query
    words naming a property term (`terms`) are also matched by a row annotated to the term or mentioning
    any of its names."""
    matched, polymer_only = [], []
    for position, row in enumerate(rows):
        topic = _words(about(row))
        if polymers and not any((subject(row) and subject(row) in p["lineage"]) or any(_mentions(topic, n) for n in p["names"])
                                for p in polymers):
            continue
        body = _words(text(row))
        named = set().union(*(t["words"] for t in terms
                              if row["id"] in t["findings"] or any(_mentions(body, n) for n in t["names"])))
        covered = sum(w in named or _has_word(body, w) for w in words) / len(words) if words else 1
        if covered:
            matched.append((-covered, position, row))
        elif polymers:
            polymer_only.append(row)
    matched = [row for _, _, row in sorted(matched, key=lambda item: item[:2])][:limit]
    return matched + polymer_only[:max(0, min(limit, FILL) - len(matched))]


def search(root, q, limit=10, compact=False):
    """The saved findings most relevant to `q`, then source notes. Unsupported findings never appear.

    Relevance decides which findings are returned: when the query names a polymer, only findings
    about that polymer (by any of its names or its graph id), ranked by how many of the other
    query words they match. `limit` (at least 10) is the total of these across statuses. Then come up to
    `SAME_SOURCE` other findings saved from the sources of the findings and notes returned. The result is grouped
    by status (reviewed, added on a researcher's judgement, awaiting review or inconclusive) only for display.

    A store may also hold property terms (tables `property_terms` and `finding_terms`), read only when both exist
    and hold a term. For a term the query names (`_property_terms`), findings written with its other names are found
    too; the query words naming it count as matched in a finding annotated to it or mentioning any of its names; and
    when the query names a polymer, the findings annotated to the term and filed under that polymer, its families or
    its members are candidates too. Notes are searched as without terms. Without these tables, or with them empty,
    a search returns what it returned before they existed."""
    phrase = _match(q, expand(root, q))
    empty = {"reviewed": [], "added": [], "unreviewed": [], "notes": []}
    if not phrase or not database(root).exists():
        return empty
    limit = min(max(int(limit), 10), 25)
    polymers, words = _query_parts(root, q)
    for polymer in polymers:
        polymer["lineage"] = lineage(root, polymer["ids"])
    with connect(root) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                                               "(?, ?)", TERMS)}
        terms = _property_terms(db, q, polymers) if set(TERMS) <= tables else []
        rows = db.execute("SELECT f.* FROM findings_fts x JOIN findings f ON f.id=x.id WHERE findings_fts MATCH ? "
                          "AND f.status != ? ORDER BY rank LIMIT 500",
                          (_match(q, expand(root, q, terms)) if terms else phrase, UNSUPPORTED)).fetchall()
        notes = db.execute("SELECT n.* FROM notes_fts x JOIN notes n ON n.id=x.id WHERE notes_fts MATCH ? "
                           "ORDER BY rank LIMIT 200", (phrase,)).fetchall()
        ids = sorted(set().union(*(p["ids"] for p in polymers))) if polymers else []
        if ids:  # Findings filed under the polymer's graph id but naming it some other way.
            seen = {row["id"] for row in rows}
            rows += [row for row in db.execute("SELECT * FROM findings WHERE status != ? AND subject IN (%s)"
                                               % ",".join("?" * len(ids)), (UNSUPPORTED, *ids)) if row["id"] not in seen]
        family = sorted(set().union(*(p["lineage"] for p in polymers))) if terms and polymers else []
        if family:  # Findings annotated to a property term the query names, filed under the polymer's lineage.
            seen, asked = {row["id"] for row in rows}, [t["term"] for t in terms]
            marks = lambda items: ",".join("?" * len(items))
            rows += [row for row in db.execute("SELECT * FROM findings WHERE status != ? AND subject IN (%s) AND id IN "
                                               "(SELECT finding_id FROM finding_terms WHERE term IN (%s)) ORDER BY rowid"
                                               % (marks(family), marks(asked)), (UNSUPPORTED, *family, *asked))
                     if row["id"] not in seen]
        fields = lambda row, keys: " ".join(str(row[k] or "") for k in keys)
        # A finding is about what its statement and material say, not its source's title: a PCL control in a
        # PHBV-blend paper is a PCL finding.
        rows = _relevant(rows, lambda r: fields(r, ("statement", "material")),
                         lambda r: fields(r, ("statement", "material", "property", "conditions", "source_title", "excerpt")),
                         lambda r: r["subject"], polymers, words, limit, terms)
        notes = _relevant(notes, lambda n: fields(n, ("title", "supports", "conditions")),
                          lambda n: fields(n, ("title", "supports", "conditions", "locator", "excerpts")),
                          lambda n: "", polymers, words, 3 if compact else limit)
        rows += _same_source(db, rows, notes)
    views, titled = {}, set()
    for row in rows:
        views[row["id"]] = finding_view(row, compact=compact)
        key = source_key(row["source_doi"], row["source_url"])
        if compact and key in titled:  # A source's title is given once per result.
            views[row["id"]]["source"].pop("title", None)
        titled.add(key)
    return {"reviewed": [views[r["id"]] for r in rows if r["status"] == SUPPORTED],
            "added": [views[r["id"]] for r in rows if r["status"] == ACCEPTED],
            "unreviewed": [views[r["id"]] for r in rows if r["status"] in {UNREVIEWED, UNCERTAIN}],
            "notes": [note_view(n, compact=compact) for n in notes]}


def _same_source(db, rows, notes):
    """Saved findings from the sources of `rows` and `notes` that `rows` does not already hold, most relevant
    source first: what a researcher would otherwise reopen the source to read."""
    keys = [source_key(r["source_doi"], r["source_url"]) for r in rows] + [source_key(n["doi"], n["url"]) for n in notes]
    seen, extra = {r["id"] for r in rows}, []
    for key in dict.fromkeys(k for k in keys if k):
        needle = key.split(":", 1)[1]
        for row in db.execute("SELECT * FROM findings WHERE status != ? AND (instr(lower(source_doi), ?) OR "
                              "instr(lower(source_url), ?)) ORDER BY rowid", (UNSUPPORTED, needle, needle)):
            if row["id"] not in seen and source_key(row["source_doi"], row["source_url"]) == key:
                seen.add(row["id"])
                extra.append(row)
    return extra[:SAME_SOURCE]


def get(root, identifier):
    """A finding or note by id. A finding merged into another as a duplicate (`upkeep.duplicates`) resolves to the one
    it was merged into, so answers that cite it still resolve."""
    if not isinstance(identifier, str) or not database(root).exists():
        return None
    with connect(root) as db:
        row = db.execute("SELECT * FROM findings WHERE id=?", (identifier,)).fetchone()
        value = finding_view(row, full=True) if row else None
        if not value:
            merged = db.execute("SELECT into_id FROM merged WHERE id=?", (identifier,)).fetchone()
            row = db.execute("SELECT * FROM findings WHERE id=?", (merged[0],)).fetchone() if merged else None
            value = dict(finding_view(row, full=True), mergedFrom=identifier) if row else None
        if not value:
            row = db.execute("SELECT * FROM notes WHERE id=?", (identifier,)).fetchone()
            value = dict(note_view(row), kind="note") if row else None
    return value


def apply_titles(root, question_id=None, *, fetch=None, cached_only=False):
    """File findings and notes (one question's, or all) under their DOI's Crossref title, so a typed title ("vinimidazole")
    never reaches an answer. A title the researcher wrote that names another work is kept in the finding's detail
    (`titleAsWritten`). DOIs Crossref does not know, or that cannot be reached now, keep their titles."""
    from . import sources
    empty = {"dois": 0, "resolved": 0, "retitled": 0, "differed": 0}
    if not database(root).exists():
        return empty
    where, args = ("WHERE question_id=?", (question_id,)) if question_id else ("", ())
    with connect(root) as db:
        findings = db.execute("SELECT id, source_title, source_doi, source_url FROM findings " + where, args).fetchall()
        notes = db.execute("SELECT id, title, doi, url FROM notes " + where, args).fetchall()
    doi = lambda given, url: sources.clean_doi(given) or sources.doi_of(url)
    wanted = sorted({d for d in [doi(r["source_doi"], r["source_url"]) for r in findings]
                     + [doi(n["doi"], n["url"]) for n in notes] if d})
    titles = {}
    for value in wanted:  # Network outside any transaction.
        found = sources.metadata(root, value, fetch=fetch, cached_only=cached_only)
        if found and found.get("title"):
            titles[value] = found["title"]
    counts = dict(empty, dois=len(wanted), resolved=len(titles))
    # Crossref's spacing around formatting (a subscript, an italic word) is unreliable; a title that differs only in
    # spacing or case keeps the researcher's.
    spacing = lambda text: re.sub(r"\s+", "", text or "").lower()
    with connect(root) as db:
        for row in findings:
            title = titles.get(doi(row["source_doi"], row["source_url"]))
            if not title or spacing(title) == spacing(row["source_title"]):
                continue
            if row["source_title"] and not sources.same_title(row["source_title"], title):
                counts["differed"] += 1
                _set_detail(db, row["id"], titleAsWritten=row["source_title"])
            db.execute("UPDATE findings SET source_title=? WHERE id=?", (title, row["id"]))
            _reindex(db, row["id"])
            counts["retitled"] += 1
        for note in notes:
            title = titles.get(doi(note["doi"], note["url"]))
            if title and spacing(title) != spacing(note["title"]):
                db.execute("UPDATE notes SET title=? WHERE id=?", (title, note["id"]))
                _reindex_note(db, note["id"])
    return counts


def _row_fields(row):
    """A stored finding row in the field names deposit uses."""
    return {"statement": row["statement"], "material": row["material"], "property": row["property"],
            "value": row["value"], "unit": row["unit"], "conditions": row["conditions"], "subject": row["subject"],
            "sourceTitle": row["source_title"], "sourceUrl": row["source_url"], "sourceDoi": row["source_doi"],
            "locator": row["locator"], "excerpt": row["excerpt"]}


def read_url(root, doi, url):
    """Where a researcher last read this source, if it noted a reading copy (a navigation lead, not proof)."""
    key = source_key(doi, url)
    if not key or not database(root).exists():
        return ""
    with connect(root) as db:
        for row in db.execute("SELECT doi, url, read_url FROM notes WHERE read_url != '' ORDER BY created_at DESC"):
            if source_key(row["doi"], row["url"]) == key:
                return row["read_url"]
    return ""


def about(root, subject, limit=100):
    """Findings about one polymer record, for its page. Unsupported findings are omitted."""
    if not isinstance(subject, str) or not WOP.match(subject) or not database(root).exists():
        return []
    with connect(root) as db:
        rows = db.execute("SELECT * FROM findings WHERE subject=? AND status != ? ORDER BY status='supported' DESC, "
                          "created_at DESC LIMIT ?", (subject, UNSUPPORTED, limit)).fetchall()
    return [finding_view(r) for r in rows]


def for_question(root, question_id):
    if not database(root).exists():
        return []
    with connect(root) as db:
        rows = db.execute("SELECT * FROM findings WHERE question_id=? ORDER BY rowid", (question_id,)).fetchall()
    return [finding_view(r) for r in rows]


def recent(root, status=None, limit=50):
    """Newest first; `status` is one status or a list of them."""
    if not database(root).exists():
        return []
    statuses = [status] if isinstance(status, str) else list(status or [])
    with connect(root) as db:
        if statuses:
            rows = db.execute("SELECT * FROM findings WHERE status IN (%s) ORDER BY COALESCE(NULLIF(reviewed_at,''), "
                              "created_at) DESC LIMIT ?" % ",".join("?" * len(statuses)), (*statuses, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM findings ORDER BY COALESCE(NULLIF(reviewed_at,''), created_at) DESC LIMIT ?",
                              (limit,)).fetchall()
    return [finding_view(r) for r in rows]


# ---------------------------------------------------------------------------
# The review queue: an answer's flagged findings and its sample of added ones,
# checked together by one reviewer call after the answer is delivered.

# Waiting for review: flagged findings, sampled Added ones, and any finding checked again for its label or excerpt.
TO_REVIEW = ("(status='unreviewed' OR (status='accepted' AND json_extract(detail, '$.spotCheck')='pending') "
             "OR json_extract(detail, '$.recheck')='pending')")
MAX_REVIEW_ATTEMPTS = 2


def deposit_summary(root, question_id):
    if not database(root).exists():
        return None
    with connect(root) as db:
        row = db.execute("SELECT * FROM deposits WHERE question_id=?", (question_id,)).fetchone()
        if row is None:
            return None
        counts = dict(db.execute("SELECT status, COUNT(*) FROM findings WHERE question_id=? GROUP BY status",
                                 (question_id,)).fetchall())
        waiting = db.execute("SELECT COUNT(*) FROM findings WHERE question_id=? AND " + TO_REVIEW, (question_id,)).fetchone()[0]
    given_up = row["review_attempts"] >= MAX_REVIEW_ATTEMPTS
    return {"findings": row["findings"], "notes": row["notes"], "dropped": row["dropped"],
            "duplicates": row["duplicates"] or 0, "duplicateOf": json.loads(row["duplicate_of"] or "[]"),
            "reviewStatus": row["review_status"], "reviewAttempts": row["review_attempts"], "reviewedAt": row["reviewed_at"],
            "reviewEngine": row["review_engine"], "reviewError": row["review_error"], "counts": counts,
            "waitingReview": 0 if given_up else waiting}


def summary(root):
    if not database(root).exists():
        return {"findings": {}, "notes": 0, "pendingReviews": 0, "questionsWithDeposits": 0}
    with connect(root) as db:
        findings = dict(db.execute("SELECT status, COUNT(*) FROM findings GROUP BY status").fetchall())
        origins = dict(db.execute("SELECT origin, COUNT(*) FROM findings WHERE status=? GROUP BY origin", (SUPPORTED,)).fetchall())
        notes = db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        deposits = db.execute("SELECT COUNT(*) FROM deposits").fetchone()[0]
    return {"findings": findings, "supportedByOrigin": origins, "notes": notes, "pendingReviews": len(review_queue(root)),
            "questionsWithDeposits": deposits}


SNAPSHOT_FORMAT = "oopc-knowledge-snapshot-v1"
STATUS_LABELS = {SUPPORTED: "Reviewed", ACCEPTED: "Added", UNREVIEWED: "Needs checking", UNCERTAIN: "Needs checking",
                 UNSUPPORTED: "Rejected"}
LOCAL_PATH = re.compile(r"file:|(?<![\w.])(/Users/|/home/|/private/|/var/folders/|/tmp/)|\b[A-Za-z]:\\")


def export(root, destination):
    """A public snapshot of the knowledge: every finding with its source, locator, status and review verdict, and every
    source note. Questions, traces, excerpts and researcher flags stay private. The snapshot is named by a hash of its
    content and graph release, written whole or not at all, and never over an existing folder."""
    from .util import canonical, digest, resolve_release
    destination = Path(destination)
    if destination.exists():
        raise ValueError("The destination exists; a snapshot is never written over another")
    labels = _graph_families(root)[2]
    with connect(root) as db:
        findings = [{k: v for k, v in {
            "id": row["id"], "statement": row["statement"], "material": row["material"], "property": row["property"],
            "value": row["value"], "unit": row["unit"], "conditions": row["conditions"], "polymer": row["subject"],
            "polymerLabel": labels.get(row["subject"]), "source": {k: v for k, v in (
                ("title", row["source_title"]), ("url", row["source_url"]), ("doi", row["source_doi"])) if v},
            "locator": row["locator"], "status": row["status"], "statusLabel": STATUS_LABELS[row["status"]],
            "review": {k: v for k, v in (("verdict", row["status"]), ("reason", row["review_reason"]),
                                         ("engine", row["reviewer_engine"]), ("reviewedAt", row["reviewed_at"]))
                       if v} if row["status"] in VERDICTS else None,
            "producerEngine": row["producer_engine"], "origin": row["origin"], "createdAt": row["created_at"],
        }.items() if v not in ("", None, {})} for row in db.execute("SELECT * FROM findings ORDER BY id")]
        notes = [{k: v for k, v in {
            "id": row["id"], "title": row["title"], "url": row["url"], "doi": row["doi"], "readUrl": row["read_url"],
            "locator": row["locator"], "supports": row["supports"], "conditions": row["conditions"],
            "createdAt": row["created_at"]}.items() if v not in ("", None)}
            for row in db.execute("SELECT * FROM notes ORDER BY id")]
    for record in findings + notes:
        text = json.dumps(record, ensure_ascii=False)
        if LOCAL_PATH.search(text):
            raise ValueError("%s names a local path; nothing was written" % record["id"])
    release = resolve_release(root).name
    files = {"findings.jsonl": b"".join(canonical(f) + b"\n" for f in findings),
             "notes.jsonl": b"".join(canonical(n) + b"\n" for n in notes)}
    statuses = {}
    for f in findings:
        statuses[f["statusLabel"]] = statuses.get(f["statusLabel"], 0) + 1
    manifest = {"format": SNAPSHOT_FORMAT, "graphRelease": release,
                "snapshotId": "oopc-knowledge-" + digest({"graphRelease": release, "findings": findings, "notes": notes})[:24],
                "counts": {"findings": len(findings), "byStatus": statuses, "notes": len(notes),
                           "polymers": len({f["polymer"] for f in findings if f.get("polymer")}),
                           "sources": len(({source_key(f["source"].get("doi", ""), f["source"].get("url", ""))
                                            for f in findings} | {source_key(n.get("doi", ""), n.get("url", ""))
                                                                  for n in notes}) - {""})},
                "lastRecordAt": max([r["createdAt"] for r in findings + notes if r.get("createdAt")], default=None),
                "files": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in files.items()},
                "withheld": "Questions, traces, verbatim excerpts, researcher review flags and local paths."}
    staging = destination.with_name("." + destination.name + ".partial")
    if staging.exists():
        raise ValueError("A partial snapshot is in the way: %s" % staging)
    staging.mkdir(parents=True)
    try:
        for name, data in files.items():
            (staging / name).write_bytes(data)
        (staging / "manifest.json").write_bytes(json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8") + b"\n")
        staging.rename(destination)
    except BaseException:
        for path in staging.glob("*"):
            path.unlink()
        staging.rmdir()
        raise
    return manifest


def import_snapshot(root, folder):
    """Start an empty knowledge store from a public snapshot, so a published study can be run again. The snapshot's
    files must match their hashes and its id, and its graph release must be the one in use. Findings keep their ids,
    statuses and review verdicts; they have no excerpts and belong to no question. Never merges into a store that
    already holds knowledge."""
    from .util import digest, resolve_release
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != SNAPSHOT_FORMAT:
        raise ValueError("Not a knowledge snapshot: %s" % folder)
    data = {name: (folder / name).read_bytes() for name in ("findings.jsonl", "notes.jsonl")}
    for name, value in data.items():
        if digest(value) != manifest["files"][name]["sha256"]:
            raise ValueError("%s does not match the manifest" % name)
    findings = [json.loads(line) for line in data["findings.jsonl"].decode("utf-8").splitlines() if line]
    notes = [json.loads(line) for line in data["notes.jsonl"].decode("utf-8").splitlines() if line]
    release = resolve_release(root).name
    if manifest["graphRelease"] != release:
        raise ValueError("The snapshot was made with graph release %s; this workspace uses %s"
                         % (manifest["graphRelease"], release))
    if "oopc-knowledge-" + digest({"graphRelease": release, "findings": findings, "notes": notes})[:24] != manifest["snapshotId"]:
        raise ValueError("The snapshot's content does not match its id")
    with connect(root) as db:
        if db.execute("SELECT (SELECT COUNT(*) FROM findings) + (SELECT COUNT(*) FROM notes)").fetchone()[0]:
            raise ValueError("This workspace already holds knowledge; a snapshot only starts an empty one")
        detail = {"snapshot": manifest["snapshotId"]}
        for f in findings:
            source, review = f.get("source") or {}, f.get("review") or {}
            _insert_finding(db, f["id"], "snapshot", f.get("origin", "research"), {
                "statement": f.get("statement", ""), "material": f.get("material", ""), "property": f.get("property", ""),
                "value": f.get("value", ""), "unit": f.get("unit", ""), "conditions": f.get("conditions", ""),
                "subject": f.get("polymer", ""), "sourceTitle": source.get("title", ""), "sourceUrl": source.get("url", ""),
                "sourceDoi": source.get("doi", ""), "locator": f.get("locator", ""), "excerpt": ""},
                status=f["status"], producer_engine=f.get("producerEngine", ""), created_at=f.get("createdAt", ""),
                review_reason=review.get("reason", ""), reviewer_engine=review.get("engine", ""),
                reviewed_at=review.get("reviewedAt", ""), detail=detail)
        for n in notes:
            _insert_note(db, n["id"], "snapshot", "snapshot", {
                "title": n.get("title", ""), "url": n.get("url", ""), "doi": n.get("doi", ""), "locator": n.get("locator", ""),
                "excerpts": [], "supports": n.get("supports", ""), "conditions": n.get("conditions", ""),
                "readUrl": n.get("readUrl", "")}, created_at=n.get("createdAt", ""))
    return {"snapshotId": manifest["snapshotId"], "findings": len(findings), "notes": len(notes)}


def review_queue(root):
    """Answers with findings waiting for review, oldest first; a review that failed twice is not retried."""
    if not database(root).exists():
        return []
    with connect(root) as db:
        rows = db.execute("SELECT d.question_id FROM deposits d WHERE d.review_attempts < ? AND EXISTS (SELECT 1 FROM "
                          "findings f WHERE f.question_id=d.question_id AND " + TO_REVIEW.replace("status", "f.status")
                          .replace("detail", "f.detail") + ") ORDER BY d.deposited_at", (MAX_REVIEW_ATTEMPTS,)).fetchall()
    return [row[0] for row in rows]


def findings_to_review(root, question_id):
    with connect(root) as db:
        rows = db.execute("SELECT * FROM findings WHERE question_id=? AND " + TO_REVIEW + " ORDER BY rowid",
                          (question_id,)).fetchall()
        producer = db.execute("SELECT engine FROM deposits WHERE question_id=?", (question_id,)).fetchone()
    return [finding_view(r, full=True) for r in rows], (producer[0] if producer else None)


def _set_detail(db, identifier, **changes):
    row = db.execute("SELECT detail FROM findings WHERE id=?", (identifier,)).fetchone()
    detail = dict(json.loads(row[0]) if row and row[0] else {}, **changes)
    detail = {k: v for k, v in detail.items() if v is not None}  # None removes a key.
    db.execute("UPDATE findings SET detail=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), identifier))


def record_review(root, question_id, *, engine, verdicts, started_at, seconds, usage, notes=""):
    """Apply one review. Each finding takes its verdict; a flagged finding the reviewer skipped becomes uncertain,
    and a sampled added finding it skipped stays added. A Reviewed finding checked again for its label or excerpt
    (`recheck`) keeps its review unless this one finds it unsupported, which makes it Needs checking. A finding saved
    with a usable excerpt missing takes the span its reviewer quoted; one whose polymer name was ambiguous takes the
    material its reviewer wrote out, and stays Needs checking when the reviewer could not settle it."""
    stamp = now()
    with connect(root) as db:
        rows = db.execute("SELECT * FROM findings WHERE question_id=? AND " + TO_REVIEW, (question_id,)).fetchall()
        for row in rows:
            identifier, status, detail = row["id"], row["status"], json.loads(row["detail"] or "{}")
            verdict = verdicts.get(identifier)
            if status == SUPPORTED:
                _set_detail(db, identifier, recheck=verdict["verdict"] if verdict else "not-assessed")
                if verdict and verdict["verdict"] == UNSUPPORTED:
                    db.execute("UPDATE findings SET status=?, review_reason=?, reviewer_engine=?, reviewed_at=? WHERE id=?",
                               (UNCERTAIN, ("A second review found it unsupported: " + verdict["reason"])[:600], engine,
                                stamp, identifier))
            else:
                if status == ACCEPTED:
                    _set_detail(db, identifier, spotCheck=verdict["verdict"] if verdict else "not-assessed",
                                recheck=(verdict["verdict"] if verdict else "not-assessed") if "recheck" in detail else None)
                    if verdict is None:
                        continue
                verdict = verdict or {"verdict": UNCERTAIN, "reason": "The reviewer did not assess this finding."}
                db.execute("UPDATE findings SET status=?, review_reason=?, reviewer_engine=?, reviewed_at=? WHERE id=?",
                           (verdict["verdict"], verdict["reason"][:600], engine, stamp, identifier))
            if not verdict or verdict["verdict"] == UNSUPPORTED:
                continue
            given = verdict.get("excerpt") or ""
            if verdict["verdict"] == SUPPORTED and given and (detail.get("needsExcerpt") or
                                                              bare_excerpt(row["excerpt"], row["unit"])) \
                    and not bare_excerpt(given, row["unit"]):
                _set_detail(db, identifier, excerptFrom={"reviewer": engine, "at": stamp, "was": row["excerpt"] or ""},
                            needsExcerpt=None)
                db.execute("UPDATE findings SET excerpt=? WHERE id=?", (given[:LIMITS["excerpt"]], identifier))
                _reindex(db, identifier)
            if detail.get("ambiguous"):
                _relabel(root, db, row, detail, verdict.get("material") or "", engine, stamp)
        db.execute("UPDATE deposits SET review_status='reviewed', review_attempts=review_attempts+1, reviewed_at=?, "
                   "review_engine=?, review_error=NULL WHERE question_id=?", (stamp, engine, question_id))
        db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "review:%s:%s" % (question_id[:12], stamp), question_id, engine, started_at, stamp, "completed", "",
            seconds, json.dumps(usage or {}), (notes or "")[:2000]))
    return deposit_summary(root, question_id)


def _reindex(db, identifier):
    """Index a finding for search again from its stored text; every write to a field `_finding_text` reads calls it."""
    row = db.execute("SELECT * FROM findings WHERE id=?", (identifier,)).fetchone()
    db.execute("DELETE FROM findings_fts WHERE id=?", (identifier,))
    db.execute("INSERT INTO findings_fts VALUES (?,?)", (identifier, _finding_text(_row_fields(row))))


def _note_row_text(row):
    return _note_text(dict(row, excerpts=json.loads(row["excerpts"] or "[]")))


def _reindex_note(db, identifier):
    row = db.execute("SELECT * FROM notes WHERE id=?", (identifier,)).fetchone()
    db.execute("DELETE FROM notes_fts WHERE id=?", (identifier,))
    db.execute("INSERT INTO notes_fts VALUES (?,?)", (identifier, _note_row_text(row)))


def _relabel(root, db, row, detail, material, engine, stamp):
    """A finding whose polymer name was ambiguous takes the material its reviewer wrote out from the source, and the
    polymer id that names; without one that settles it, it is Needs checking rather than stored ambiguous."""
    material = " ".join(material.split())[:LIMITS["material"]]
    if material and not ambiguous_polymers(root, material + "; " + (row["statement"] or ""), strict=False):
        subject = file_subject(root, {"material": material, "statement": row["statement"]})[0] or row["subject"]
        written = dict(detail.get("asWritten") or {})
        written.setdefault("material", row["material"])
        _set_detail(db, row["id"], asWritten=written, ambiguous=None, relabelled={"reviewer": engine, "at": stamp})
        db.execute("UPDATE findings SET material=?, subject=? WHERE id=?", (material, subject, row["id"]))
        _reindex(db, row["id"])
    else:
        names = ", ".join(detail["ambiguous"])
        db.execute("UPDATE findings SET status=?, review_reason=?, reviewer_engine=?, reviewed_at=? WHERE id=?",
                   (UNCERTAIN, "Its polymer name (%s) is still ambiguous." % names, engine, stamp, row["id"]))


def record_review_failure(root, question_id, *, engine, reason, message, started_at, seconds=None, usage=None):
    """A failed review is retried once on a later run; after that its sampled findings stay added, unchecked."""
    stamp = now()
    with connect(root) as db:
        db.execute("UPDATE deposits SET review_status='failed', review_attempts=review_attempts+1, review_error=? "
                   "WHERE question_id=?", (reason + ": " + message[:300], question_id))
        attempts = db.execute("SELECT review_attempts FROM deposits WHERE question_id=?", (question_id,)).fetchone()[0]
        if attempts >= MAX_REVIEW_ATTEMPTS:
            for (identifier,) in db.execute("SELECT id FROM findings WHERE question_id=? AND status=? AND "
                                            "json_extract(detail, '$.spotCheck')='pending'", (question_id, ACCEPTED)).fetchall():
                _set_detail(db, identifier, spotCheck="failed")
        db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "review:%s:%s" % (question_id[:12], stamp), question_id, engine, started_at, stamp, "failed", reason,
            seconds, json.dumps(usage or {}), message[:2000]))


def failed_review_engine(root, question_id):
    """The engine of this answer's last review attempt if that attempt failed, so a retry can use another."""
    if not database(root).exists():
        return None
    with connect(root) as db:
        row = db.execute("SELECT engine, status FROM reviews WHERE question_id=? ORDER BY finished_at DESC LIMIT 1",
                         (question_id,)).fetchone()
    return row["engine"] if row and row["status"] == "failed" else None


def spot_check_stats(root):
    """How often the sampled findings added on the researcher's judgement held up when reviewed."""
    empty = {"checked": 0, "supported": 0, "unsupported": 0, "uncertain": 0, "pending": 0, "failed": 0,
             "unsupportedRate": None}
    if not database(root).exists():
        return empty
    with connect(root) as db:
        rows = db.execute("SELECT json_extract(detail, '$.spotCheck'), COUNT(*) FROM findings "
                          "WHERE json_extract(detail, '$.spotCheck') IS NOT NULL GROUP BY 1").fetchall()
    counts = dict(rows)
    value = dict(empty, **{k: counts.get(k, 0) for k in ("supported", "unsupported", "uncertain", "pending", "failed")})
    value["checked"] = value["supported"] + value["unsupported"] + value["uncertain"]
    value["unsupportedRate"] = round(value["unsupported"] / value["checked"], 3) if value["checked"] else None
    return value


def reviews(root, limit=30):
    if not database(root).exists():
        return []
    with connect(root) as db:
        rows = db.execute("SELECT * FROM reviews ORDER BY finished_at DESC LIMIT ?", (limit,)).fetchall()
    return [{"questionId": r["question_id"], "engine": r["engine"], "startedAt": r["started_at"],
             "finishedAt": r["finished_at"], "status": r["status"], "reason": r["reason"], "seconds": r["seconds"]}
            for r in rows]


# ---------------------------------------------------------------------------
# The researcher's tools: the knowledge above, traced. The graph supplies polymer names to search, not tools.

KNOWLEDGE_SPECS = {
    "search_knowledge": ("Search what earlier questions found. Name the polymer and the property: when the query names "
                         "a polymer, only findings about it are returned, most relevant first, up to `limit` in total. "
                         "Results are grouped as reviewed findings (checked against their sources by a separate reviewer), "
                         "added findings (saved on an earlier researcher's judgement), findings that still need checking, "
                         "and source notes (leads; readUrl is where a source was read before). After these come the other "
                         "findings saved from the same sources. Cite reviewed and added findings by id instead of "
                         "re-reading their sources. Call this first.",
                         {"q": {"type": "string"}, "limit": {"type": "integer", "minimum": 10, "maximum": 25}}, ["q"]),
}


def research_tools(root, release, run_id, agent_id):
    """`search_knowledge`, each call recorded in the question's trace."""
    from .mcp import MCP

    class ResearchTools(MCP):
        def tools(self):
            return {"tools": [{"name": name, "description": description,
                               "inputSchema": {"type": "object", "properties": props, "required": required,
                                               "additionalProperties": False},
                               "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
                              for name, (description, props, required) in KNOWLEDGE_SPECS.items()]}

        def call(self, name, args):
            if name not in KNOWLEDGE_SPECS:
                raise ValueError("Unknown tool")
            _, props, required = KNOWLEDGE_SPECS[name]
            if (not isinstance(args, dict) or set(args) - set(props) or any(k not in args for k in required)
                    or not isinstance(args.get(required[0]), str) or len(args[required[0]]) > 2000
                    or ("limit" in args and type(args["limit"]) is not int)):
                self.run.record("knowledge." + name, {"tool": name, "arguments": args},
                                {"error": "Invalid arguments"}, agent_id=self.agent_id, status="error")
                raise ValueError(name + " needs " + ", ".join(required))
            result = search(self.root, args["q"], args.get("limit", 10), compact=True)
            self.run.record("knowledge." + name, {"tool": name, "arguments": args},
                            {"result": result}, agent_id=self.agent_id, kind="access")
            return result

    return ResearchTools(root, release, run_id, agent_id)
