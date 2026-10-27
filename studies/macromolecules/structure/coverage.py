#!/usr/bin/env python3
"""Structure strategy 2, a coverage summary at search time (docs/exec-plans/active/structure-estimates-plan.md): what
one line saying what the store holds for the asked polymer, by property class ("PEEK: Tg 12, tensile modulus 5;
nothing on creep"), could save, estimated offline from the records. No engine is called and nothing under the run
folders is written; stores are opened read-only (sqlite `?mode=ro`, through `mine.Store`) and the graph through
`oopc`'s read-only readers.

**Records.**
- The Part C screen (`pins.FOLDERS["screen"]`, s1..s8): each question's B, B0 and O+ items (`answer.metrics`:
  newTokens, knowledgeLookups, webCalls; `webActions`), and each arm's traces (`workspaces/<arm>/.oopc/runs/<runId>/`:
  `events.jsonl` and every `search_knowledge` call's exact returned payload under `payloads/`). The questions are the
  plans' (H, N and L: polymer ids, materials, property, set, stratum and group).
- The derivation pool (`mine/answers.jsonl`): every answer whose material and property its generator recorded, its
  trace and payloads read in its own workspace, its new tokens from the live loop's `result.json` usage
  (`calls.new_tokens`) or its Part A driver item's metrics, its text from the same records.
- KF (`pins.KF`; its findings through `mine.Store`) and its graph release (lineage: `knowledge.lineage`, inside
  `mine.Miner.context`), A1's property map and rules (`mine.Properties`) and A1's vocabulary for each class's kind.
- The blind relevance judge of the withheld questions (`lookup/judge/`), as a check on the class-level coverage.

**1. Coverage.** A question's asked polymers are its polymer ids and the polymers its materials name on KF's graph,
with every broader family and narrower member, and their names (`mine.Miner.context`). A finding is about them as
mining reads it (its `subject` in the lineage, or its statement or material naming one of the names) and on the asked
property by mining's rule (`mine.Properties.same`: a part of the property's wording with an A1 class is met by a
finding of that class, a part without one by a shared significant word) or, since A1's classes split what a reader
would take as the same property, by a finding in the same A1 category sharing a significant word with a part of it
(`Coverage.near`: "notched impact strength" and a notched Izod value; the class-only result is kept as `strict`).
Rejected findings are hidden from searches and not counted. **covered**: the store holds a finding about the asked
polymers on the asked property; **polymer-only**: findings about them, none on the property; **nothing**: none about
them. A property with no part A1's map or rules can class (`unmapped`) is matched by words only and counted; `partial`
marks a covered question with some part of its property not covered. The line's content is the material-property
classes of the polymers' findings with their counts (`line`). For a live-loop pool answer the store is KF as it was
when the answer started (findings created before it by other questions); for a Part A answer (run on KF) and the
screen, all of KF.

**2. Payloads.** Each payload the answer received is measured in characters of its JSON text (`json.dumps(result,
ensure_ascii=False)`, the tool's MCP text content) and in tokens as characters / CHARS_PER_TOKEN (4; no tokenizer is
installed, and JSON full of ids and punctuation tokenizes denser than prose, so this probably understates tokens).
Payload tokens are the text the session read; the reasoning it spent on them is not counted. A payload finding is
**on target** when it is about the asked polymers and on the asked property. Each search after the first is classed:
`new-polymer` (it names a polymer, by graph lineage or a name the graph lacks, that no earlier search named:
`mine.Miner.polymers_of`), `productive` (an on-target finding no earlier search returned: a reformulation that
worked), `after-exhaustion` (nothing new on target, and the earlier searches had returned every on-target finding the
store holds) or `unproductive`; and whether its words besides the polymers re-ask the asked property (`asks`).
**Avoidable**, on a polymer-only or nothing answer: every later search that is neither new-polymer nor productive
(`later`), plus the first payload's findings that are not on target (`estimate`; its source notes are leads and are
kept). On a covered answer, both variants: the after-exhaustion searches that re-ask the property (the line's count
shows nothing more is saved); a productive reformulation is not cut, since the line says more is saved. A line needs
the first search to name a polymer the graph knows (`feasible`: the estimate where it does, 0 elsewhere).

**3. Shares** of each answer's new tokens (uncached input plus output): the mean over answers with a bootstrap 95%
interval over questions (DRAWS, SEED; a question's answers resampled together), the median and the pooled share (sum
over sum), per coverage class and per set, stratum and group; beside the measured mid penalty: the screen's B/B0
median paired token ratio on H/mid (`analyze.ratio_ci`), the same with B's avoidable tokens taken off, and the mean
paired B - B0 difference (`analyze.diff_ci`). The blind judge's relevant findings check the polymer-only and nothing
classes: the estimate is also given without the questions where it found one.

**4. CL-18** (rough, by pattern). An answer's absence statements (a sentence or table cell matching ABSENT: a value or
detail not reported, found, given, stated, specified, provided or available, or no data) are classed by what they
blame (first match: `store`, the saved findings; `own`, the answer's own evidence or search; `source`, a paper,
datasheet, passage, table and the like; else `unattributed`) and by the material-property classes A1's map and rules
find in their words. Counted: (a) statements naming a class the store held findings of for the asked polymers, and
(a') of these the ones whose class none of the answer's searches returned for them (what the line would have shown);
(b) statements in an answer that used no web at all, so they rest on the store alone, by blame; (c) statements
blaming a source in an answer that searched the web but opened no page (weaker: search results can carry page text).
Strict candidates: (a') naming an asked class, or (b) blaming a source (the store's silence read as the source's);
loose: any (a'), (b) blaming a source or nothing, and (c). Screen B and O+ answers, and every pool answer.

**5. Prediction 2** (plan, written before computing), judged on the screen's B answers with the `estimate` variant:
polymer-only and nothing 10-25% of new tokens (mean share inside), covered about 0 (mean share under COVERED_ZERO,
a threshold chosen here), overall under 8%.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main checkout>/.oopc/study/freeze-3 \\
        python3 -B studies/macromolecules/structure/coverage.py [--out DIR]

Writes `rows.json`, `report.json` and `report.md` under `ROOT/.oopc/study/analysis/structure/coverage/` (private).
"""
import argparse, collections, json, random, re, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from ablation import analyze  # noqa: E402  (test 1's paired ratio and difference with their intervals)
from analysis.properties import rules  # noqa: E402
from refinement import mine, pins  # noqa: E402
from oopc import calls, knowledge  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, now, read_json  # noqa: E402

OUT = common.analysis_dir("structure") / "coverage"
VOCABULARY = Path(rules.__file__).resolve().parent / "vocabulary.json"  # A1's classes, each with its kind
CHARS_PER_TOKEN = 4
DRAWS, SEED = 2000, 7
CLASSES = ("covered", "polymer-only", "nothing")
SPARSE = ("polymer-only", "nothing")
LATER = ("new-polymer", "productive", "after-exhaustion", "unproductive")
VARIANTS = ("later", "estimate", "feasible")
MATERIAL = "material-property"
COVERED_ZERO = 0.02
PREDICTION = {"sparse": (0.10, 0.25), "covered": COVERED_ZERO, "overall": 0.08}
FIELDS = ("subject", "statement", "material", "property", "status")
ABSENT = re.compile(
    r"\b(?:not\s+(?:been\s+)?(?:reported|found|given|stated|specified|provided|available|listed|recorded|included|"
    r"identified|located|retrieved|established|disclosed|quantified)\b|not\s+in\s+the\s+saved|"
    r"(?:does|do|did)\s+not\s+(?:report|give|state|specify|provide|include|list|contain|mention|disclose|quantify)\b|"
    r"could\s+not\s+(?:find|locate|identify|confirm|be\s+found)\b|unavailable\b|"
    r"no\s+(?:data|value|values|numerical|measured|reported|published)\b|"
    r"\bno\b[^.;|]{0,80}?\b(?:was|were)\s+(?:found|reported|given|located|identified)\b)", re.I)
# The absence wording itself, taken out before a statement's words are classed (its property words stay).
ABSENT_WORDS = re.compile(
    r"\b(?:not|no|none|cannot|could|does|do|did|was|were|is|are|been|be|reported|found|given|stated|specified|"
    r"provided|available|unavailable|listed|recorded|included|identified|located|retrieved|established|disclosed|"
    r"quantified|report|give|state|specify|provide|include|list|contain|mention|disclose|quantify|find|locate|"
    r"confirm|data|numerical|measured|published|in|the|saved)\b", re.I)
STORE = re.compile(r"\bsaved\s+(?:finding|knowledge|evidence|record|note|value|result|entr)\w*|\bthe\s+store\b|"
                   r"\bknowledge\s+(?:base|store)\b", re.I)
SOURCE = re.compile(r"\b(?:paper|study|article|source|datasheet|data\s+sheet|tds|patent|passage|abstract|text|"
                    r"table|figure|report|authors?|reference|document|page|section|entry|supplier|manufacturer|"
                    r"literature|publication|thesis|excerpt|snippet|website|chapter|handbook|methods?)\b", re.I)
OWN = re.compile(r"\b(?:evidence|retrieved|available\s+evidence|this\s+answer|I\s+(?:could|did|found))\b|\bhere\b",
                 re.I)
SEGMENTS = re.compile(r"(?<=[.!?])\s+|\n+|\|")
NOISE = re.compile(r"`[^`]*`|https?://\S+|\*+|(?:finding|note):\S+")


def tokens(chars):
    return chars / CHARS_PER_TOKEN


def r4(value):
    return None if value is None else round(value, 4)


# ----- KF and coverage -----

class Coverage:
    """KF as the estimate reads it: its findings (rejected ones left out, as searches hide them) and its graph, with
    A1's property classes and their kinds."""

    def __init__(self, root=None, property_map=None, vocabulary=None):
        self.root = Path(root or pins.KF).resolve()
        self.miner = mine.Miner(self.root, property_map=property_map)
        self.props = self.miner.props
        self.findings = [dict(f, topic=knowledge._words("%s %s" % (f["statement"] or "", f["material"] or "")))
                         for f in self.miner.store.findings.values() if f["status"] != knowledge.UNSUPPORTED]
        classes = read_json(Path(vocabulary or VOCABULARY))["classes"]
        self.kinds = {c["id"]: c.get("kind") for c in classes}
        self.categories = {c["id"]: c.get("category") for c in classes}
        self._same, self._material, self._cache, self._asks = {}, {}, {}, {}

    def context(self, question):
        """The asked polymers (ids, lineage, names) and property, as mining reads a question (`Miner.context`)."""
        materials = list(question.get("materials") or []) or ([question["material"]] if question.get("material")
                                                               else [])
        ids = question.get("polymerIds") or []
        return self.miner.context({"question": question.get("question") or "", "materials": materials,
                                   "property": question.get("property"),
                                   "polymerIds": [i for i in ids if isinstance(i, str)]}, self.root)

    def about(self, finding, ctx):
        if finding.get("subject") and finding["subject"] in ctx["lineage"]:
            return True
        topic = finding.get("topic") or knowledge._words("%s %s" % (finding.get("statement") or "",
                                                                    finding.get("material") or ""))
        return any(n in topic and knowledge._mentions(topic, n) for n in ctx["names"])

    def near(self, asked, prop):
        """A finding's wording in the same A1 category as a part of the asked wording and sharing a significant word
        with it: "notched impact strength" (impact-strength-other) and a notched Izod finding, or "Shore A hardness"
        and an indentation hardness in Shore A2, which A1's classes keep apart."""
        theirs = {self.categories.get(c) for c in self.props.classes(prop)} - {None}
        words = mine.property_words(prop)
        return any(theirs & {self.categories.get(c) for c in self.props.classes(part)}
                   and mine.property_words(part) & words for part in mine.parts(asked))

    def on_property(self, prop, ctx, relaxed=True):
        """Whether a finding's property wording is on the asked property: mining's rule (`Properties.same`), and with
        `relaxed` also a wording `near` it."""
        key = (ctx["property"], prop or "", ctx["propertyFrom"], relaxed)
        if key not in self._same:
            asked = ctx["property"]
            self._same[key] = (not asked or self.props.same(asked, prop or "", ctx["propertyFrom"] == "question")
                               or (relaxed and self.near(asked, prop or "")))
        return self._same[key]

    def asks(self, query, ctx):
        """Whether a search's words other than the polymers it names are on the asked property (a class or a shared
        significant word): a search re-asking the asked property."""
        key = (query, ctx["property"])
        if key not in self._asks:
            words = " ".join(mine._parts(str(self.root), query or "")[1])
            self._asks[key] = bool(ctx["property"]) and self.props.same(ctx["property"], words, True)
        return self._asks[key]

    def on_target(self, finding, ctx):
        return (finding.get("status") != knowledge.UNSUPPORTED and self.about(finding, ctx)
                and self.on_property(finding.get("property"), ctx))

    def material_classes(self, text):
        """The material-property classes A1's map and rules give a wording (test conditions, specimens and methods
        left out: a line counts properties)."""
        if text not in self._material:
            self._material[text] = frozenset(c for c in self.props.classes(text or "") if self.kinds.get(c) == MATERIAL)
        return self._material[text]

    def classify(self, ctx, before=None, exclude=None):
        """The question's coverage on KF (as it was at `before`, without question `exclude`'s own findings)."""
        key = (ctx["lineage"], frozenset(ctx["names"]), ctx["property"], ctx["propertyFrom"], before, exclude)
        if key in self._cache:
            return self._cache[key]
        parts = mine.parts(ctx["property"] or "")
        mapped = [bool(self.props.classes(p)) for p in parts]
        value = {"coverage": None, "strict": None, "polymerFindings": 0, "onProperty": 0, "onPropertyIds": [],
                 "askedClasses": sorted(self.props.classes(ctx["property"] or "")), "parts": len(parts),
                 "partsMapped": sum(mapped), "unmapped": not any(mapped), "partial": False, "line": []}
        if ctx["lineage"] or ctx["names"]:
            polymer = [f for f in self.findings if (before is None or (f["created_at"] or "") < before)
                       and (exclude is None or f["question_id"] != exclude) and self.about(f, ctx)]
            on = [f for f in polymer if self.on_property(f["property"], ctx)]
            strict = any(self.on_property(f["property"], ctx, relaxed=False) for f in on)
            line = collections.Counter(c for f in polymer for c in self.material_classes(f["property"]))
            covered_parts = [any(self.on_property(f["property"], dict(ctx, property=p)) for f in on) for p in parts]
            value.update(coverage="covered" if on else "polymer-only" if polymer else "nothing",
                         strict="covered" if strict else "polymer-only" if polymer else "nothing",
                         polymerFindings=len(polymer), onProperty=len(on), onPropertyIds=sorted(f["id"] for f in on),
                         partial=bool(on) and not all(covered_parts), line=line.most_common())
        self._cache[key] = value
        return value

    def feasible(self, query):
        """Whether a search for `query` names a polymer the graph knows, so it could carry the line."""
        return bool(mine._ids(self.root, query or ""))

    def polymers_of(self, query):
        return set(self.miner.polymers_of(query or ""))

    def resolve(self, identifier):
        return self.miner.store.resolve(identifier) or identifier


# ----- payloads and the later searches -----

def searches(root, run_id):
    """A run's `search_knowledge` calls in order, each ok call's exact payload measured: sequence, query, limit,
    status, characters, and its entries (findings and notes, each with its characters and the fields a judgement
    reads). None when the trace is not there. Read from the trace's files, never through `TraceStore`."""
    path = Path(root) / ".oopc/runs" / str(run_id)
    if not run_id or not (path / "events.jsonl").exists():
        return None
    found = []
    for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("operation") != mine.TOOL:
            continue
        args = (event.get("request") or {}).get("arguments") or {}
        item = {"sequence": event.get("sequence") or 0, "q": args["q"] if isinstance(args.get("q"), str) else "",
                "limit": args.get("limit"), "status": event.get("status"), "chars": 0, "entries": []}
        if event.get("status") == "ok":
            result = read_json(path / "payloads" / (event["payload_hash"] + ".json")).get("result") or {}
            item["chars"] = len(json.dumps(result, ensure_ascii=False))
            for group in mine.GROUPED + ("notes",):
                for entry in result.get(group) or []:
                    if isinstance(entry, dict):
                        item["entries"].append(dict({k: entry.get(k) for k in FIELDS}, id=entry.get("id"),
                                                    note=group == "notes",
                                                    chars=len(json.dumps(entry, ensure_ascii=False)) + 2))
        found.append(item)
    return sorted(found, key=lambda s: s["sequence"])


def measure(found, ctx, cover, kf):
    """An answer's store searches against its question's coverage: payload sizes, the first payload's part off target,
    and each later search's class with its characters."""
    ok = [s for s in found or [] if s["status"] == "ok"]
    value = {"searches": len(ok), "failedSearches": len(found or []) - len(ok),
             "payloadChars": sum(s["chars"] for s in ok), "firstChars": 0, "firstOffChars": 0, "firstNoteChars": 0,
             "firstOnTarget": 0, "returnedOnTarget": 0, "later": {k: 0 for k in LATER},
             "laterChars": {k: 0 for k in LATER}, "reask": {k: 0 for k in LATER}, "reaskChars": {k: 0 for k in LATER},
             "feasible": False, "firstQuery": None, "returnedClasses": []}
    if not ok:
        return value
    target = {}
    for s in ok:
        for e in s["entries"]:
            if not e["note"]:
                e["resolved"] = kf.resolve(e["id"])
                target[e["resolved"]] = target.get(e["resolved"]) or kf.on_target(e, ctx)
    on = lambda e: not e["note"] and target[e["resolved"]]  # noqa: E731
    first = ok[0]
    held = set(cover["onPropertyIds"])
    seen = {e["resolved"] for e in first["entries"] if on(e)}
    named = kf.polymers_of(first["q"])
    value.update(firstChars=first["chars"], firstQuery=first["q"], feasible=kf.feasible(first["q"]),
                 firstOffChars=sum(e["chars"] for e in first["entries"] if not e["note"] and not on(e)),
                 firstNoteChars=sum(e["chars"] for e in first["entries"] if e["note"]), firstOnTarget=len(seen))
    for s in ok[1:]:
        got = {e["resolved"] for e in s["entries"] if on(e)}
        theirs = kf.polymers_of(s["q"])
        kind = ("new-polymer" if theirs and named and not theirs & named else "productive" if got - seen
                else "after-exhaustion" if held <= seen else "unproductive")
        value["later"][kind] += 1
        value["laterChars"][kind] += s["chars"]
        if kf.asks(s["q"], ctx):
            value["reask"][kind] += 1
            value["reaskChars"][kind] += s["chars"]
        seen |= got
        named |= theirs
    value["returnedOnTarget"] = len(seen)
    value["returnedClasses"] = sorted({c for s in ok for e in s["entries"] if not e["note"] and kf.about(e, ctx)
                                       for c in kf.material_classes(e.get("property"))})
    return value


def saving(coverage, got):
    """Avoidable characters (later searches only, estimate) for one answer, by its coverage class; None when the class
    is unknown. Polymer-only and nothing: every later search that is neither new-polymer nor productive, plus the
    first payload's off-target findings. Covered: the later searches re-asking the asked property after the store's
    on-target findings had all been returned."""
    if coverage in SPARSE:
        cut = got["laterChars"]["after-exhaustion"] + got["laterChars"]["unproductive"]
        return cut, cut + got["firstOffChars"]
    if coverage == "covered":
        return got["reaskChars"]["after-exhaustion"], got["reaskChars"]["after-exhaustion"]
    return None, None


# ----- CL-18 -----

def absences(text):
    """The answer's absence statements: sentences, lines and table cells matching ABSENT."""
    return [s.strip() for s in SEGMENTS.split(text or "") if ABSENT.search(s or "")]


def blame(statement):
    """What an absence statement blames, first match: the saved findings (`store`), the answer's own evidence or
    search (`own`: "the evidence used here", "I could not confirm"), a source (`source`: a paper, datasheet, passage),
    or nothing it names (`unattributed`)."""
    return ("store" if STORE.search(statement) else "own" if OWN.search(statement)
            else "source" if SOURCE.search(statement) else "unattributed")


def statement_classes(statement, kf):
    """The material-property classes in an absence statement's words, without the citations, the absence phrase and
    what it blames."""
    clean = ABSENT_WORDS.sub(" ", OWN.sub(" ", SOURCE.sub(" ", STORE.sub(" ", NOISE.sub(" ", statement)))))
    return sorted(kf.material_classes(" ".join(clean.split())))


def cl18(text, reading, cover, returned, kf, asked=()):
    """One answer's absence statements, each with what it blames, its classes, whether one is an asked class, the
    classes the store held for the asked polymers (the line, `cover["line"]`) and of those the ones none of the
    answer's searches returned (`returned`); and the counts: (a) held, (a') held and not returned, (b) in an answer
    that used no web at all (`reading` "store-only": the statement rests on the store alone), split by blame, and (c)
    in an answer that searched the web but opened no page (`reading` "no-page"; the engines' search results can carry
    page text, so this is weaker), blaming a source. Candidates: strict (a') naming an asked class (`aAsked`: the
    statement is about the asked result, not a detail of one source) or (b, blaming a source); loose: any (a'),
    (b, blaming a source or nothing) and (c)."""
    held = {c for c, _ in (cover or {}).get("line") or []}
    items = []
    for statement in absences(text):
        classes = statement_classes(statement, kf)
        on_hand = sorted(set(classes) & held)
        items.append({"text": statement[:300], "blame": blame(statement), "classes": classes,
                      "asked": bool(set(classes) & set(asked)), "held": on_hand,
                      "heldNotReturned": sorted(set(on_hand) - set(returned))})
    b = items if reading == "store-only" else []
    c = [i for i in items if reading == "no-page" and i["blame"] == "source"]
    strict = [i for i in items if (i["heldNotReturned"] and i["asked"]) or (i in b and i["blame"] == "source")]
    loose = [i for i in items if i["heldNotReturned"] or (i in b and i["blame"] in ("source", "unattributed"))
             or i in c]
    return {"statements": len(items), "reading": reading,
            "byBlame": dict(collections.Counter(i["blame"] for i in items)),
            "a": sum(bool(i["held"]) for i in items), "aNotReturned": sum(bool(i["heldNotReturned"]) for i in items),
            "aAsked": sum(bool(i["heldNotReturned"]) and i["asked"] for i in items), "b": len(b),
            **{"b" + k.capitalize(): sum(i["blame"] == k for i in b) for k in ("store", "source", "own",
                                                                             "unattributed")},
            "c": len(c), "strict": len(strict), "loose": len(loose), "items": items}


def reading_web(metrics, actions):
    """How a screen answer read: `store-only` (no web call), `no-page` (web searches, no page that opened) or
    `opened`."""
    if any(a.get("action") in ("open", "find") and a.get("outcome") in mine.OPENED for a in actions or []):
        return "opened"
    return "no-page" if (metrics or {}).get("webCalls") or actions else "store-only"


def reading_steps(steps):
    """The same for a pool answer, from its steps."""
    if any(s.get("type") in ("open", "find") and s.get("outcome") in mine.OPENED for s in steps or []):
        return "opened"
    return "no-page" if any(s.get("type") in ("web-search", "open", "find") for s in steps or []) else "store-only"


# ----- rows -----

def judge_relevant(question_id, folder=None):
    """The blind judge's relevant findings for a withheld question (lookup), or None when it was not judged."""
    calls_ = sorted((Path(folder or pins.FOLDERS["lookup"]) / "judge" / question_id).glob("call-*.json"))
    found = [read_json(p).get("result") for p in calls_]
    found = [r for r in found if isinstance(r, dict) and isinstance(r.get("relevant"), dict)]
    if not found:
        return None
    return sorted({i for r in found for i, rel in r["relevant"].items() if rel})


def answer_row(base, kf, ctx, cover, found, new_tokens):
    """One answer's row: its coverage, store searches and avoidable characters, tokens and shares."""
    got = measure(found, ctx, cover, kf)
    later, estimate = saving(cover["coverage"], got)
    row = dict(base, coverage=cover["coverage"], strict=cover["strict"], unmapped=cover["unmapped"],
               partial=cover["partial"], parts=cover["parts"], partsMapped=cover["partsMapped"],
               askedClasses=cover["askedClasses"], polymerFindings=cover["polymerFindings"],
               onProperty=cover["onProperty"], line=cover["line"][:6], newTokens=new_tokens,
               traced=found is not None, **{k: v for k, v in got.items() if k != "returnedClasses"})
    row["payloadTokens"] = tokens(got["payloadChars"])
    row["laterSearches"] = sum(got["later"].values())
    avoid = {"later": later, "estimate": estimate, "feasible": estimate if got["feasible"] else
             (0 if estimate is not None else None)}
    row["avoidableTokens"] = {k: None if v is None else tokens(v) for k, v in avoid.items()}
    row["share"] = {k: (tokens(v) / new_tokens if v is not None and new_tokens else None) for k, v in avoid.items()}
    return row, got["returnedClasses"]


def screen_rows(kf, base=None, judged=None):
    """The screen's B answers (token rows) and its B and O+ answers' CL-18 rows, and B0's new tokens for pairing."""
    base = Path(base or pins.FOLDERS["screen"])
    rows, absent = [], []
    for name in read_json(base / "experiment.json")["folders"]:
        folder = base / name
        plan = read_json(folder / "plan.json")
        roots = {a["name"]: Path(a["root"]) for a in plan["arms"]}
        for index, question in enumerate(plan["questions"]):
            items = {}
            for arm in roots:
                path = folder / "items" / ("%04d-%s.json" % (index, arm))
                items[arm] = read_json(path) if path.exists() else {}
            ctx = kf.context(question)
            cover = kf.classify(ctx)
            info = dict({k: question.get(k) for k in ("set", "stratum", "group", "kind")}, id=question["id"],
                        questionId=question["id"], origin="screen", arm=pins.B)
            answered = {arm: (items[arm].get("answer") or {}) for arm in items}
            b = answered.get(pins.B) or {}
            if not driver._ok(b) or not b.get("answer"):
                continue
            found = searches(roots[pins.B], b.get("runId"))
            metrics = b.get("metrics") or {}
            row, returned = answer_row(info, kf, ctx, cover, found, metrics.get("newTokens"))
            b0 = (answered.get("B0") or {}).get("metrics") or {}
            row.update(knowledgeLookups=metrics.get("knowledgeLookups"), webCalls=metrics.get("webCalls"),
                       b0NewTokens=b0.get("newTokens") if driver._ok(answered.get("B0")) else None,
                       b0WebCalls=b0.get("webCalls") if driver._ok(answered.get("B0")) else None)
            if judged is not None:
                relevant = judged(question["id"])
                row["judgeRelevant"] = None if relevant is None else len(relevant)
            rows.append(row)
            for arm in (pins.B, pins.OPLUS):
                answer = answered.get(arm) or {}
                if not driver._ok(answer) or not answer.get("answer"):
                    continue
                theirs = returned if arm == pins.B else measure(searches(roots[arm], answer.get("runId")), ctx, cover,
                                                                kf)["returnedClasses"]
                text = (answer.get("answer") or {}).get("answer") or ""
                absent.append(dict(info, arm=arm, coverage=cover["coverage"],
                                   **cl18(text, reading_web(answer.get("metrics"), answer.get("webActions")), cover,
                                        theirs, kf,
                                        cover["askedClasses"])))
    return rows, absent


def pool_answers(path=None):
    path = Path(path or pins.FOLDERS["mine"] / "answers.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pool_record(answer, live=None, harness=None):
    """A pool answer's new tokens and text: the live loop's `result.json` (usage through `calls.new_tokens`), or its
    Part A driver item's metrics and answer."""
    if answer["origin"] == "loop":
        path = Path(live or common.ROOT / ".oopc/loop/questions") / answer["questionId"] / "result.json"
        result = read_json(path) if path.exists() else {}
        body = result.get("answer") if isinstance(result.get("answer"), dict) else {}
        return calls.new_tokens(result.get("usage")), body.get("answer") or ""
    detail = answer.get("detail") or {}
    path = Path(harness or common.run_dir("")) / detail.get("folder", "") / "items" / (detail.get("item", "") + ".json")
    item = read_json(path) if path.exists() else {}
    got = item.get("answer") if isinstance(item.get("answer"), dict) else {}
    body = got.get("answer") if isinstance(got.get("answer"), dict) else {}
    return (got.get("metrics") or {}).get("newTokens"), body.get("answer") or ""


def pool_rows(kf, answers=None, live=None, harness=None):
    """The pool's answers whose material and property are recorded (token rows), and every pool answer's CL-18 row
    (class-level only where its polymers are known)."""
    rows, absent = [], []
    for answer in pool_answers() if answers is None else answers:
        new_tokens, text = pool_record(answer, live, harness)
        known = bool(answer.get("materials")) and bool(answer.get("property"))
        ctx = kf.context({"question": answer["question"], "materials": answer.get("materials"),
                          "property": answer.get("property") or ""})
        live_answer = answer["origin"] == "loop"
        cover = kf.classify(ctx, before=answer.get("startedAt") if live_answer else None,
                            exclude=answer["questionId"] if live_answer else None) \
            if (ctx["lineage"] or ctx["names"]) else None
        info = {"id": answer["id"], "questionId": answer["questionId"], "origin": answer["origin"],
                "kind": answer.get("kind"), "set": "pool"}
        found = searches(answer["root"], answer.get("runId"))
        returned = []
        if known and cover is not None:
            row, returned = answer_row(info, kf, ctx, cover, found, new_tokens)
            row.update(knowledgeLookups=sum(s["type"] == "store" for s in answer["steps"]),
                       webCalls=sum(s["type"] in ("web-search", "open") for s in answer["steps"]))
            rows.append(row)
        elif cover is not None:
            returned = measure(found, ctx, cover, kf)["returnedClasses"]
        absent.append(dict(info, arm="pool", coverage=(cover or {}).get("coverage"),
                           **cl18(text, reading_steps(answer["steps"]), cover, returned, kf,
                                (cover or {}).get("askedClasses") or ())))
    return rows, absent


# ----- statistics -----

def _clusters(rows, key):
    found = collections.defaultdict(list)
    for r in rows:
        value = key(r)
        if value is not None:
            found[r["questionId"]].append(value)
    return found


def mean_ci(rows, key):
    """The mean of `key` over answers, with a bootstrap 95% interval over questions (a question's answers together)."""
    clusters = _clusters(rows, key)
    values = [v for vs in clusters.values() for v in vs]
    if not values:
        return None
    value = {"n": len(values), "questions": len(clusters), "mean": r4(statistics.mean(values)),
             "median": r4(statistics.median(values))}
    if len(clusters) >= 3:
        ids, rng, draws = sorted(clusters), random.Random(SEED), []
        for _ in range(DRAWS):
            sample = [v for q in rng.choices(ids, k=len(ids)) for v in clusters[q]]
            draws.append(sum(sample) / len(sample))
        draws.sort()
        value.update(low=r4(draws[int(0.025 * DRAWS)]), high=r4(draws[int(0.975 * DRAWS)]))
    return value


def pooled_ci(rows, numerator, denominator):
    """Sum of `numerator` over sum of `denominator`, with the same bootstrap."""
    clusters = _clusters(rows, lambda r: (numerator(r), denominator(r)) if numerator(r) is not None
                         and denominator(r) else None)
    pairs = [p for ps in clusters.values() for p in ps]
    if not pairs:
        return None
    ratio = lambda s: sum(a for a, _ in s) / sum(b for _, b in s)  # noqa: E731
    value = {"n": len(pairs), "share": r4(ratio(pairs))}
    if len(clusters) >= 3:
        ids, rng = sorted(clusters), random.Random(SEED)
        draws = sorted(ratio([p for q in rng.choices(ids, k=len(ids)) for p in clusters[q]]) for _ in range(DRAWS))
        value.update(low=r4(draws[int(0.025 * DRAWS)]), high=r4(draws[int(0.975 * DRAWS)]))
    return value


def mean(values):
    values = [v for v in values if v is not None]
    return r4(statistics.mean(values)) if values else None


def summary(rows):
    """Per coverage class (and polymer-only with nothing as `sparse`, and all): answers, new tokens, searches, later
    searches by class, payload tokens, avoidable tokens and the shares of new tokens per variant."""
    value = {"answers": len(rows), "byCoverage": dict(collections.Counter(r["coverage"] for r in rows))}
    groups = {"all": rows, **{c: [r for r in rows if r["coverage"] == c] for c in CLASSES},
              "sparse": [r for r in rows if r["coverage"] in SPARSE]}
    for name, chosen in groups.items():
        priced = [r for r in chosen if r["newTokens"]]
        value[name] = {
            "answers": len(chosen), "questions": len({r["questionId"] for r in chosen}),
            "feasible": sum(r["feasible"] for r in chosen), "unmapped": sum(r["unmapped"] for r in chosen),
            "partial": sum(r["partial"] for r in chosen), "meanNewTokens": mean(r["newTokens"] for r in chosen),
            "meanSearches": mean(r["searches"] for r in chosen),
            "meanLaterSearches": mean(r["laterSearches"] for r in chosen),
            "later": {k: sum(r["later"][k] for r in chosen) for k in LATER},
            "reask": {k: sum(r["reask"][k] for r in chosen) for k in LATER},
            "meanPayloadTokens": mean(r["payloadTokens"] for r in chosen),
            "meanFirstTokens": mean(tokens(r["firstChars"]) for r in chosen),
            "meanFirstOffTokens": mean(tokens(r["firstOffChars"]) for r in chosen),
            "meanAvoidableTokens": {k: mean(r["avoidableTokens"][k] for r in chosen) for k in VARIANTS},
            "share": {k: mean_ci(priced, lambda r, k=k: r["share"][k]) for k in VARIANTS},
            "pooledShare": {k: pooled_ci(priced, lambda r, k=k: r["avoidableTokens"][k], lambda r: r["newTokens"])
                            for k in VARIANTS}}
    return value


def subsets(rows, key="set"):
    """Rows by group: all, each set, each stratum within H and N, each group and tertile within L, each pool origin."""
    groups = collections.OrderedDict(all=rows)
    for name in dict.fromkeys(r[key] for r in rows):
        chosen = [r for r in rows if r[key] == name]
        groups[name] = chosen
        fields = ("origin",) if name == "pool" else ("group", "stratum") if name == "L" else ("stratum",)
        for field in fields:
            for sub in dict.fromkeys(r.get(field) for r in chosen):
                groups["%s/%s" % (name, sub)] = [r for r in chosen if r.get(field) == sub]
    return groups


def mid_penalty(rows):
    """The measured mid penalty on the screen (B against B0, H/mid), beside the B answers' avoidable tokens there; and
    the same on every polymer-only or nothing question."""
    value = {}
    for name, chosen in (("H/mid", [r for r in rows if r["set"] == "H" and r.get("stratum") == "mid"]),
                         ("sparse", [r for r in rows if r["coverage"] in SPARSE]),
                         ("all", rows)):
        paired = [{"B": {"newTokens": r["newTokens"]}, "B0": {"newTokens": r["b0NewTokens"]},
                   "line": {"newTokens": r["newTokens"] - (r["avoidableTokens"]["estimate"] or 0)}} for r in chosen
                  if r["newTokens"] and r.get("b0NewTokens")]
        differences = [r["newTokens"] - r["b0NewTokens"] for r in chosen if r["newTokens"] and r.get("b0NewTokens")]
        avoid = {k: mean(r["avoidableTokens"][k] for r in chosen) for k in VARIANTS}
        extra = mean(differences)
        value[name] = {"questions": len(chosen), "byCoverage": dict(collections.Counter(r["coverage"] for r in chosen)),
                       "ratio": analyze.ratio_ci(paired, "B", "B0", "newTokens"),
                       "ratioWithLine": analyze.ratio_ci(paired, "line", "B0", "newTokens"),
                       "difference": analyze.diff_ci(paired, "B", "B0", "newTokens"),
                       "meanB": mean(r["newTokens"] for r in chosen),
                       "meanB0": mean(r["b0NewTokens"] for r in chosen),
                       "meanAvoidableTokens": avoid,
                       "avoidableOverExtra": {k: (r4(avoid[k] / extra) if avoid[k] is not None and extra else None)
                                              for k in VARIANTS},
                       "meanSearches": {"B": mean(r["searches"] for r in chosen),
                                        "laterB": mean(r["laterSearches"] for r in chosen)}}
    return value


def covered_detail(rows):
    """Covered answers: whether a line would cut reformulation searches (later searches returning on-target findings
    the earlier ones did not, `productive`)."""
    chosen = [r for r in rows if r["coverage"] == "covered"]
    with_later = [r for r in chosen if r["laterSearches"]]
    return {"answers": len(chosen), "withLaterSearches": len(with_later),
            "later": {k: sum(r["later"][k] for r in chosen) for k in LATER},
            "answersWithReformulation": sum(bool(r["later"]["productive"]) for r in chosen),
            "answersWithAfterExhaustion": sum(bool(r["later"]["after-exhaustion"]) for r in chosen),
            "reask": {k: sum(r["reask"][k] for r in chosen) for k in LATER},
            "answersWithReaskAfterExhaustion": sum(bool(r["reask"]["after-exhaustion"]) for r in chosen),
            "firstReturnedAll": sum(r["firstOnTarget"] >= r["onProperty"] for r in chosen),
            "medianHeld": statistics.median([r["onProperty"] for r in chosen]) if chosen else None,
            "medianFirstOnTarget": statistics.median([r["firstOnTarget"] for r in chosen]) if chosen else None,
            "medianReturnedOnTarget": statistics.median([r["returnedOnTarget"] for r in chosen]) if chosen else None,
            "laterTokens": {k: mean(tokens(r["laterChars"][k]) for r in chosen) for k in LATER},
            "partial": sum(r["partial"] for r in chosen)}


def judge_check(rows):
    """Class-level coverage against the blind judge (a relevant finding anywhere in the question's pooled results; the
    judge also counts a finding giving the method, specimen or conditions of a value of the property), and the
    polymer-only and nothing estimate without the questions where it found one (a line saying "nothing" would have
    been wrong or misleading there)."""
    found = collections.defaultdict(collections.Counter)
    for r in rows:
        relevant = r.get("judgeRelevant")
        found[r["coverage"]]["not judged" if relevant is None else "relevant" if relevant else "none relevant"] += 1
    sparse = [r for r in rows if r["coverage"] in SPARSE]
    kept = [r for r in sparse if not r.get("judgeRelevant") and r["newTokens"]]
    return {"byCoverage": {k: dict(v) for k, v in found.items()},
            "sparseWithRelevant": sorted(r["id"] for r in sparse if r.get("judgeRelevant")),
            "sparseConsistent": {"answers": len(kept), **{k: mean_ci(kept, lambda r, k=k: r["share"][k])
                                                           for k in VARIANTS}}}


CL18_KEYS = ("a", "aNotReturned", "aAsked", "b", "bStore", "bSource", "bOwn", "bUnattributed", "c", "strict",
             "loose")


def cl18_summary(items):
    """Answers with absence statements, what they blame, and each count of `cl18` in statements and answers, with the
    candidates' share of answers."""
    value = {"answers": len(items), "withAbsence": sum(bool(i["statements"]) for i in items),
             "statements": sum(i["statements"] for i in items),
             "byBlame": dict(sum((collections.Counter(i["byBlame"]) for i in items), collections.Counter())),
             "reading": dict(collections.Counter(i["reading"] for i in items))}
    for key in CL18_KEYS:
        value[key] = {"statements": sum(i[key] for i in items), "answers": sum(bool(i[key]) for i in items)}
    for key in ("strict", "loose"):
        value[key]["share"] = r4(value[key]["answers"] / len(items)) if items else None
    return value


def verdict(screen):
    """Prediction 2 against the screen's B answers (estimate variant)."""
    sparse = (screen["sparse"]["share"]["estimate"] or {}).get("mean")
    covered = (screen["covered"]["share"]["estimate"] or {}).get("mean")
    overall = (screen["all"]["share"]["estimate"] or {}).get("mean")
    low, high = PREDICTION["sparse"]
    parts = {"sparse": {"rule": "polymer-only and nothing: avoidable store payload 10-25% of new tokens",
                        "value": sparse, "met": None if sparse is None else low <= sparse <= high},
             "covered": {"rule": "covered: about 0 (mean share under %.2f)" % PREDICTION["covered"],
                         "value": covered, "met": None if covered is None else covered < PREDICTION["covered"]},
             "overall": {"rule": "overall: under 8% of new tokens", "value": overall,
                         "met": None if overall is None else overall < PREDICTION["overall"]}}
    judged = [p["met"] for p in parts.values() if p["met"] is not None]
    parts["verdict"] = ("met" if judged and all(judged) else "not met" if judged and not any(judged)
                        else "partly met" if judged else "pending")
    return parts


# ----- report -----

def report(kf, screen=None, pool=None, judged=judge_relevant):
    rows, absent = screen_rows(kf, screen, judged)
    prow, pabsent = pool_rows(kf) if pool is None else pool_rows(kf, **pool)
    unmapped = {"screen": sum(r["unmapped"] for r in rows),
                "screenPartlyMapped": sum(0 < r["partsMapped"] < r["parts"] for r in rows),
                "pool": sum(r["unmapped"] for r in prow)}
    value = {"at": now(), "charsPerToken": CHARS_PER_TOKEN, "draws": DRAWS, "seed": SEED,
             "kf": {"root": str(kf.root), "findingsRead": len(kf.findings)},
             "classification": {
                 "screen": {name: dict(collections.Counter(r["coverage"] for r in chosen))
                            for name, chosen in subsets(rows).items()},
                 "pool": {name: dict(collections.Counter(r["coverage"] for r in chosen))
                          for name, chosen in subsets(prow).items()},
                 "strict": {"screen": dict(collections.Counter(r["strict"] for r in rows)),
                            "pool": dict(collections.Counter(r["strict"] for r in prow)),
                            "movedByRelaxation": {"screen": sum(r["coverage"] != r["strict"] for r in rows),
                                                  "pool": sum(r["coverage"] != r["strict"] for r in prow)}},
                 "unmapped": unmapped,
                 "feasible": {"screen": sum(r["feasible"] for r in rows), "pool": sum(r["feasible"] for r in prow)},
                 "untraced": {"screen": sum(not r["traced"] for r in rows), "pool": sum(not r["traced"] for r in prow)},
                 "poolLeftOut": len(pabsent) - len(prow)},
             "screen": {name: summary(chosen) for name, chosen in subsets(rows).items()},
             "pool": {name: summary(chosen) for name, chosen in subsets(prow).items()},
             "midPenalty": mid_penalty(rows),
             "covered": {"screen": covered_detail(rows), "pool": covered_detail(prow)},
             "judge": judge_check(rows),
             "cl18": {"screenB": cl18_summary([i for i in absent if i["arm"] == pins.B]),
                      "screenOplus": cl18_summary([i for i in absent if i["arm"] == pins.OPLUS]),
                      **{"pool/%s" % o: cl18_summary([i for i in pabsent if i["origin"] == o])
                         for o in dict.fromkeys(i["origin"] for i in pabsent)},
                      "pool": cl18_summary(pabsent)}}
    value["prediction"] = verdict(value["screen"]["all"])
    return value, rows + prow, absent + pabsent


def fmt(x, places=2):
    if x is None:
        return "–"
    return ("%%.%df" % places) % x if isinstance(x, float) else str(x)


def pct(x):
    return "–" if x is None else "%.1f%%" % (100 * x)


def ci(v, key="mean", percent=True):
    if not v:
        return "–"
    show = pct if percent else fmt
    return "%s (%s–%s)" % (show(v[key]), show(v.get("low")), show(v.get("high"))) if "low" in v else show(v[key])


def markdown(value):
    c = value["classification"]
    lines = ["# Coverage summary at search time: offline estimate", "",
             "Tokens are characters / %d of each `search_knowledge` payload's JSON text as recorded (no tokenizer; "
             "probably an understatement for JSON); the reasoning spent on a payload is not counted. Shares are of "
             "each "
             "answer's new tokens (uncached input plus output): means over answers with bootstrap 95%% intervals over "
             "questions. Avoidable, on polymer-only and nothing answers: later searches that neither name a new "
             "polymer "
             "nor return a new on-target finding (`later`), plus the first payload's off-target findings (`estimate`); "
             "on covered answers: later searches re-asking the asked property after every on-target finding held had "
             "been returned (both variants). `feasible`: the estimate where the first query names a polymer the graph "
             "knows, 0 elsewhere." % CHARS_PER_TOKEN, "",
             "## Coverage classes", "", "| Group | Covered | Polymer-only | Nothing |", "| --- | ---: | ---: | ---: |"]
    for part in ("screen", "pool"):
        for name, counts in c[part].items():
            lines.append("| %s %s | %s | %s | %s |" % (part, name, *(counts.get(k, 0) for k in CLASSES)))
    lines += ["", "- A1 class only (without the same-category, shared-word rule): screen %s, pool %s; questions "
              "the rule "
              "moves: screen %d, pool %d." % (
                  ", ".join("%s %d" % (k, c["strict"]["screen"].get(k, 0)) for k in CLASSES),
                  ", ".join("%s %d" % (k, c["strict"]["pool"].get(k, 0)) for k in CLASSES),
                  c["strict"]["movedByRelaxation"]["screen"], c["strict"]["movedByRelaxation"]["pool"]),
              "- Properties with no part A1's map or rules can class (matched by words): screen %d (%d more partly "
              "mapped), pool %d." % (c["unmapped"]["screen"], c["unmapped"]["screenPartlyMapped"],
                                     c["unmapped"]["pool"]),
              "- First query names a polymer the graph knows (a line is possible): screen %d of %d, pool %d of %d. "
              "Answers without a trace: screen %d, pool %d. Pool answers without a recorded material and property, "
              "or whose polymer is not known (left out of the token estimate): %d." % (
                  c["feasible"]["screen"], value["screen"]["all"]["all"]["answers"], c["feasible"]["pool"],
                  value["pool"]["all"]["all"]["answers"], c["untraced"]["screen"], c["untraced"]["pool"],
                  c["poolLeftOut"]), ""]
    for part in ("screen", "pool"):
        lines += ["## Savings, %s%s" % (part, " (B arm)" if part == "screen" else ""), "",
                  "| Group | Class | Answers | Mean new tokens | Searches | Later (re-ask) | Payload tok | "
                  "Avoidable tok | Share later | Share estimate | Share feasible | Pooled estimate |",
                  "| --- | --- |" + " ---: |" * 10]
        for name, got in value[part].items():
            for cls in ("all",) + CLASSES + ("sparse",):
                s = got[cls]
                if not s["answers"]:
                    continue
                lines.append("| %s | %s | %d | %s | %s | %s (%s) | %s | %s | %s | %s | %s | %s |" % (
                    name, cls, s["answers"], fmt(s["meanNewTokens"], 0), fmt(s["meanSearches"]),
                    sum(s["later"].values()), sum(s["reask"].values()), fmt(s["meanPayloadTokens"], 0),
                    fmt(s["meanAvoidableTokens"]["estimate"], 0), ci(s["share"]["later"]),
                    ci(s["share"]["estimate"]), ci(s["share"]["feasible"]),
                    ci(s["pooledShare"]["estimate"], "share")))
        later = value[part]["all"]
        lines += ["", "Later searches by class (all answers): %s; re-asking the asked property: %s." % (
            ", ".join("%s %d" % kv for kv in later["all"]["later"].items()),
            ", ".join("%s %d" % kv for kv in later["all"]["reask"].items())), ""]
    lines += ["## The measured mid penalty beside the estimate (screen)", "",
              "| Group | Questions | B/B0 tokens (median paired) | With the line (B − avoidable)/B0 | "
              "B − B0 tokens "
              "(mean) | Avoidable tok (estimate) | Avoidable / (B − B0) | Searches B | Later B |",
              "| --- |" + " ---: |" * 8]
    for name, m in value["midPenalty"].items():
        lines.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            name, m["questions"], ci(m["ratio"], "median", False), ci(m["ratioWithLine"], "median", False),
            ci(m["difference"], "mean", False),
            fmt(m["meanAvoidableTokens"]["estimate"], 0), fmt(m["avoidableOverExtra"]["estimate"]),
            fmt(m["meanSearches"]["B"]), fmt(m["meanSearches"]["laterB"])))
    lines += ["", "## Covered answers: would a line cut reformulation searches?", ""]
    for part in ("screen", "pool"):
        d = value["covered"][part]
        lines.append("- %s: %d covered answers (%d partly), %d with a later search; later searches %s. %d answers "
                     "made a productive reformulation (a later search returning on-target findings the earlier ones "
                     "had not): the line would show more saved, so it does not cut these. %d answers re-asked the "
                     "property after every on-target finding held had been returned (the cut counted). The first "
                     "search returned every on-target finding held in %d answers (median held %s, returned by the "
                     "first search %s, by all searches %s)." % (
                         part, d["answers"], d["partial"], d["withLaterSearches"],
                         ", ".join("%s %d (re-ask %d)" % (k, n, d["reask"][k]) for k, n in d["later"].items()),
                         d["answersWithReformulation"], d["answersWithReaskAfterExhaustion"], d["firstReturnedAll"],
                         d["medianHeld"], d["medianFirstOnTarget"], d["medianReturnedOnTarget"]))
    j = value["judge"]
    lines += ["", "## Class-level coverage against the blind judge (screen)", "",
              "| Class | Judge: relevant in pool | None relevant | Not judged |", "| --- | ---: | ---: | ---: |"]
    for cls in CLASSES:
        got = j["byCoverage"].get(cls, {})
        lines.append("| %s | %d | %d | %d |" % (cls, got.get("relevant", 0), got.get("none relevant", 0),
                                                got.get("not judged", 0)))
    k = j["sparseConsistent"]
    lines += ["", "Polymer-only or nothing questions with a judge-relevant finding (method, specimen and formulation "
              "findings count for the judge): %d. Without them (%d answers) the share is later %s, estimate %s." % (
                  len(j["sparseWithRelevant"]), k["answers"], ci(k["later"]), ci(k["estimate"])), "",
              "## CL-18: absence statements a line could bear on (rough)", "",
              "| Answers | N | Store-only answers | With absence | Statements | (a) class held | (a') held, not "
              "returned | (b) store-only | (b) blaming a source | (b) unattributed | (c) no page, blaming a source | "
              "Strict | Loose |", "| --- |" + " ---: |" * 12]
    for name, s in value["cl18"].items():
        cell = lambda key: "%d / %d" % (s[key]["statements"], s[key]["answers"])  # noqa: E731
        lines.append("| %s | %d | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s (%s) | %s (%s) |" % (
            name, s["answers"], s["reading"].get("store-only", 0), s["withAbsence"], s["statements"], cell("a"),
            cell("aNotReturned"), cell("b"), cell("bSource"), cell("bUnattributed"), cell("c"), cell("strict"),
            pct(s["strict"]["share"]), cell("loose"), pct(s["loose"]["share"])))
    lines += ["", "Cells are statements / answers; candidate shares are of answers. (b): answers that used no web "
              "at all, so a statement rests on the store alone; blaming a source there is the CL-18 pattern. Strict: "
              "(a') naming an asked class (%s) or (b) blaming a source; loose: any (a'), (b) blaming a source or "
              "nothing, and (c)." % ", ".join("%s %d" % (k, v["aAsked"]["statements"])
                                              for k, v in value["cl18"].items()), "",
              "## Prediction 2 (screen, B arm, estimate)", ""]
    p = value["prediction"]
    for key in ("sparse", "covered", "overall"):
        lines.append("- %s: %s; %s." % (p[key]["rule"], pct(p[key]["value"]),
                                        {True: "met", False: "not met", None: "pending"}[p[key]["met"]]))
    lines.append("- Verdict: **%s**." % p["verdict"])
    return "\n".join(lines) + "\n"


def run(out=None):
    kf = Coverage()
    found = driver.fingerprint(kf.root)
    if found != pins.PINS["kf"]:
        raise SystemExit("%s is not KF (%s); nothing estimated" % (kf.root, found))
    value, rows, absent = report(kf)
    value["meta"] = mine.meta()
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(out / "rows.json", {"answers": rows, "absences": absent}, private=True)
    atomic_json(out / "report.json", value, private=True)
    atomic_bytes(out / "report.md", markdown(value).encode("utf-8"), private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", help="output folder (default %s)" % OUT)
    args = parser.parse_args()
    got = run(args.out)
    print(markdown(got))
