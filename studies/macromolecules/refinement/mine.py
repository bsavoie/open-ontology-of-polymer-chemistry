"""Part C, step 1: mine the researcher's traces for lookup failures against KF (`ontology-refinement-plan.md`,
"Procedure", 1. Mine). No engine is called anywhere; everything comes from the records and from replaying recorded
searches.

    python -B studies/macromolecules/refinement/mine.py check     # replay fidelity -> mine/replay-check.json
    python -B studies/macromolecules/refinement/mine.py mine      # the check, then answers, misses, hops, dossier
    python -B studies/macromolecules/refinement/mine.py effects   # the drop step, after overlay.py check
    python -B studies/macromolecules/refinement/mine.py summary   # prints mine/summary.json

Run it with OOPC_STUDY_CODE at the code under test (`study-freeze-3`, `.oopc/study/freeze-3`; `effects` refuses
anything else, and `check` and `mine` replay only stores without its tables, where it searches as freeze-2 did) and,
from a worktree, OOPC_STUDY_ROOT at the main checkout. Outputs go to `pins.folder("mine")` (private):
`replay-check.json`, `pool.json`, `answers.jsonl`, `excluded.json`, `misses.json`, `hops.json`, `summary.json`,
`dossier/batch-NN.json` and (`effects`) `effects.json`. Mining refuses unless `questions/hashes.json` fixes H, N and L
(the plan fixes all three before mining); the sets' digest is recorded in `pool.json` and `summary.json`.

**The base.** Replays run on a private copy of KF, `mine/workspaces/KF`, made by `driver.workspace`'s read-only backup
of `pins.KF` and refused unless its fingerprint and graph release are KF's. Neither KF's frozen copy nor the live store
is opened through `oopc`; other sqlite files are opened read-only. Everything is measured against the base as it is
now, not the store at the time of an answer (plan, 1.4).

**The derivation pool.** Every completed live-loop answer (`ROOT/.oopc/loop/questions`) and every completed answer of a
Part A researcher arm on KF with web search on (an arm whose plan fingerprint is KF's; the experiment folders of
`pins.PART_A`, and for A5 the case-study and planted folders its `experiment.json` lists). Excluded, by question text
(case and spacing ignored): test 1's 60 held-out questions (H, so every A2, A3 and E8 answer) and the withheld sets
`N.json` and `L.json`. Web-off arms, failed answers and plans that are not driver plans are also left out, and so is
a live answer that started at or after CUTOFF (2026-10-21T00:00Z: the hourly loop job runs again). The first mining
pins the pool: `pool.json` lists its answer ids with their digest, and every later mining takes exactly those answers
(a later one is left out; a pinned one gone is refused). `excluded.json` lists each answer left out with its reason.
An answer is normalized into one record: its origin, question, the
question's polymers and property where the generator recorded them (`pins.CAMPAIGN`, the 200-task run's questions, a
Part A plan), its ordered steps, its citations, what it reported and (live answers) what it deposited.

**Steps.** The order is the session's own: its raw stream when one ends with this answer's text (as the engine layer
parses it: `engines.parse_codex_stream` / `parse_claude_stream`, which also give a page open's outcome), else the
record (`observedTools`, or a driver item's `webActions` after its store searches). A store step is joined to its trace
event (`knowledge.search_knowledge`: arguments, status, and the ids its payload holds, since the events' `result_ids`
are empty for these findings, which carry `id` rather than `@id`). Older loop records name no web action; there a step
with a URL is an open whose outcome is "unrecorded" (counted as opened) and one with only a query is a search.

**Replay.** `replay(root, q, limit)` calls exactly what the tool calls, `knowledge.search(root, q, limit or 10,
compact=True)`, and returns the ids in the order the tool recorded them (reviewed, added and awaiting-review findings,
then notes). A finding is "returned" by a search (`returned`) when that call, with the query and limit recorded,
returns it, same-source and linked findings included: that is what "the first ten" means throughout. `check` replays
every recorded search of Part A's KF arms (all of them, held-out questions and web-off arms included: it derives
nothing) and must reproduce the recorded ids exactly; `mine` refuses otherwise.

**Relevance.** A finding is relevant to a question when it is not unsupported, is about the question's polymer lineage
(its graph id in the lineage, or its statement or material naming one of the polymers' names, as the search's own
filter reads them; a material the graph does not know is matched by its words) and is on its property. The property is
the one the question's generator recorded, else the question's topic (its first sentence without the polymer it is
"for" and the template's verbs). When the question's polymer is not known (no graph id, no name), no finding is
relevant. Classes come from A1's property map (`pins.PROPERTY_MAP`) for a wording it holds,
else from A1's ordered rules (`analysis/properties/rules.py`). The question's wording is taken part by part ("water
uptake and dimensional swelling" is two parts): a part with a class is met by a finding sharing it (when the finding
has a class), a part without one by a shared significant word (stemmed as the search stems; broad words such as
"temperature" and "effects" do not count). A property read from the question's text, whose class the rules may take
from a side word ("cast ... and dried" is "drying"), is met by a shared class or a shared word.

**Misses** (four kinds), each with a stable id (`m-` and a hash of its answer, kind, scope, step and finding):
- `saved-again`: a finding the answer reported that the store's duplicate rule (`knowledge.same_fact`, same source)
  matches to a base finding saved before the answer by another question, while none of the answer's replayed searches
  returns that finding. For Part A arms, which saved nothing, the findings they reported stand in.
- `unresolved-name`: the question's polymer (its recorded material, else a name in its text) is one the graph does not
  know; or a store query names no polymer the graph knows but holds a candidate name (a poly- or nylon name, an
  abbreviation in capitals, a parenthesized name, or the question's unknown material) the graph does not have, so it
  ran unfiltered; and the material of every base finding without a polymer id (scope "finding"). Candidate names are
  leads found by pattern. A query naming a polymer the graph has but the search does not read as written ("PPy": an
  abbreviation of three letters or fewer counts only in capitals) is counted (`unfilteredKnownName`), not a miss: no
  edit of the closed list fixes it.
- `late-find`: a cited finding not returned by the answer's first search for its polymer (the first store search
  whose polymers' lineage holds the finding's polymer, else the first whose polymer names its text mentions, else the
  first) nor by any search before it. Property does not pick that search: whether the query's wording reaches the
  finding's property is what the dossier tests.
- `empty-then-web`: a store search that returned no finding, followed later by a web search naming the same polymer
  (lineage, or a name of its) and sharing a property word with it.

**Hops.** A web hop is the run of web searches since the previous open, plus the next page open; searches with no open
after them form a search-only hop. Finds within a page and other actions are not hops. Each hop has a stable id (`h-`
and a hash of its answer, kind and steps). Each open is classed in order (plan, Procedure step 1.3): `failed` (the page
did not open), `repeat` (a page the answer had already read), `new-knowledge` (the base holds no finding or note with
its source key), then for a held source by what the answer took from it (`taken`: its reported findings from it, its
deposits from it, the saved findings from it it cites, its source notes for it, the addresses it cites there):
`unused` (nothing: neither ontology nor accumulation), `unsaved-detail` (something, but nothing that matches a saved
finding from the source: its deposits, cited findings, or a saved finding the store's duplicate rule matches to a
reported one), `reached-now` (a matched finding is returned on the base by a store search before the open: the base
has caught up since the answer, which only happens to live answers) and `held-unreached` (no earlier store search
returns a matched finding on the base). A held source records when the base came to hold it (`heldSince`): before the
answer, by the answer's own deposit, or later; a live answer's opens are mostly of sources it then saved itself, so on
the base as it is now they test whether the same searches would reach them next time. A page is identified with a
source by its URL's key, a DOI in its URL, the answer's own source notes and findings (a URL it says it read that DOI
at) and the base's notes read there. A store search after the first is a store hop: `repeat` (no new finding),
`new-polymer` (it names a polymer, by graph lineage or a name the graph lacks, that no earlier search named),
`held-unreached` (it returns a relevant finding no earlier search returned) or `other`. `classify(answer, root)`
replays the earlier searches on a refined workspace (only on the code under test, `pins.frozen`) and splits
`held-unreached` into `reachable` (a matched target, all of a store hop's new relevant findings, returned by a store
search before the hop) and `still-unreached`; with `build`, a callable giving a workspace for a set of edit groups
(`pins.GROUPS`), each reachable hop is attributed to the groups that reach it alone ("joint" if none does).

**Dossier.** Misses and held-unreached hops grouped by candidate source pair, else unknown name, else polymer and
property, about 25 groups a batch, each listing the ids of its misses and hops (`misses`, `hops`: what an edit cites,
`propose.cited`): counts, example answers and steps, the queries, the missed findings, and candidate
features: a blank polymer id or a material the graph lacks (name), no query word in the finding's property wording
(property term), a source returned or opened earlier in the answer sharing a DOI stem, a title or a Crossref relation
(the cached Crossref records, `ROOT/.oopc/loop/crossref`) with the held source (source link). Sources that only
co-occur in a trace are listed under `lookAt`: a reason to look, never evidence of a link (AGENTS.md).

**Edit effects** (`mine.py effects`, the drop step of the plan's Procedure step 4; `run_effects`). After `propose.py
assemble` and `overlay.py check`, on the code under test, from derivation data only (the pinned pool's answers, misses
and hops): each approved edit in force gets a root carrying that edit alone (`overlay.edit_root`: a release of the
seed plus a graph edit, or a KF copy with a store edit's rows or polymer id, and upkeep's rule against its release),
built under `mine/effects-roots/` and deleted after its replay. On it, `measure` counts by id the misses it fixes (fixed
on the root and not on the base), the held-unreached hops it makes reachable, and the results it loses (a finding a
search returned and its answer cited, which the same call no longer returns). Only the searches the replay rule
(`affected`) selects are replayed: those whose query mentions a name whose graph entry, lineage or filed findings the
edit changes, or a property term it adds, and those that return on the base a source it links or a finding it
re-indexes; every other search returns on the root what it returns on the base. An edit whose results lost exceed its
misses fixed plus hops made reachable goes to `overlay/excluded.json` with its numbers. Then the group roots' totals
(`overlay.root_for` per group and all groups, with the exclusions) are measured the same way, for the attribution.
`effects.json` names the hashes of its inputs (the overlay's three files, the pinned pool, answers, misses and hops)
and the code's commit; it is saved after each edit, so a rerun on the same inputs resumes, and `overlay.py build`
refuses unless it matches the inputs in force.
"""
import argparse, collections, contextlib, datetime, functools, hashlib, json, os, re, shutil, sqlite3, subprocess, sys
import time, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from analysis.properties import rules  # noqa: E402
from refinement import pins  # noqa: E402
from oopc import engines, knowledge  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, digest, locked, now, read_json, resolve_release  # noqa: E402

TOOL = "knowledge.search_knowledge"
CUTOFF = "2026-10-21T00:00:00+00:00"  # live answers started before it make the pool, then pinned in mine/pool.json
FORMATS = {"pool": "oopc-refinement-pool-v1", "effects": "oopc-refinement-effects-v1"}
BATCH = 25  # dossier groups per batch
SHOWN = {"examples": 5, "queries": 10, "findings": 10, "lookAt": 5}  # how much of a group the dossier shows
RELATIONS = {"is-supplement-to": "supplement-of", "is-supplemented-by": "supplement-of", "has-preprint": "version-of",
             "is-preprint-of": "version-of", "has-version": "version-of", "is-version-of": "version-of"}
GROUPED = ("reviewed", "added", "unreviewed")
MISS_KINDS = ("saved-again", "unresolved-name", "late-find", "empty-then-web")
WEB_CLASSES = ("failed", "repeat", "new-knowledge", "unused", "unsaved-detail", "reached-now", "held-unreached",
               "search-only")
STORE_CLASSES = ("repeat", "new-polymer", "held-unreached", "other")
OPENED = ("opened", "unrecorded")  # an open counted as having read its page
GENERIC = {"value", "values", "reported", "report", "published", "measured", "measurement", "measurements", "property",
           "properties", "data", "result", "results", "typical", "range", "level", "levels", "give", "describe",
           "what", "find", "primary", "source", "sources", "procedure", "used", "measure", "specimen", "specimens",
           "method", "methods", "conditions", "condition", "include", "details", "open", "literature", "study",
           "state", "explicitly", "missing", "requested", "label", "reasoning", "preserve", "inconsistencies",
           "comparison", "change", "changes", "effect", "how", "does", "one", "with", "has", "been", "for", "from",
           "under", "using", "use", "polymer", "polymers", "material", "materials", "sample", "samples", "test",
           "tests", "reports", "uncertainty", "units", "unit", "numerical", "quantitative", "bounded", "interpret",
           "needed", "covered", "parts", "saved", "findings", "gaps", "exact", "locations", "grade", "neat",
           "effects", "behavior", "behaviour", "temperature", "temperatures", "dependence", "distinguishing",
           "inferring", "limits", "limitations", "versus", "specified", "processed", "film", "films"}
NOT_NAMES = {"dsc", "dma", "dmta", "tga", "tma", "astm", "iso", "din", "jis", "iec", "ul", "ftir", "nmr", "gpc", "sec",
             "xrd", "waxd", "waxs", "saxs", "sem", "tem", "afm", "uv", "vis", "uv-vis", "hdt", "mfi", "mfr", "loi",
             "cte", "otr", "wvtr", "wvp", "ph", "mw", "mn", "pdi", "tg", "tm", "tc", "td", "rh", "doi", "pmc", "pdf",
             "si", "cas", "usa", "eu", "nist", "tappi", "bs", "gb", "mpa", "gpa", "kpa", "kj", "hz", "rpm", "ppm",
             "phr", "wt", "vol", "xps", "edx", "eds", "icp", "bet", "lcst", "ucst", "dp", "ds", "ir", "raman",
             "polymer", "polymers", "polymeric", "polymerization", "polymerisation", "polydispersity", "polymorph",
             "polymorphs", "polymorphism", "poly", "co", "vs", "dsc-", "tga-", "or", "and", "nylon"}
NAME_PATTERNS = (re.compile(r"\bpoly\s*\((?:[^()]|\([^()]*\))*\)[\w-]*", re.I),  # poly(vinyl butyral)
                 re.compile(r"\bpoly[a-z][a-z-]*(?:\s+(?:\d[\d,/]*|acid|alcohol|glycol|ether|ester|ketone|sulfone|oxide"
                            r"|[a-z]+(?:ate|ide|ene|one|yl|al|ether|ester))\b)*", re.I),  # polylactic acid
                 re.compile(r"\bnylon[\s-]?\d[\d,/]*", re.I),
                 re.compile(r"(?<![\w-])[A-Z][A-Za-z]*[A-Z][A-Za-z0-9-]*(?![\w-])"),  # PEEK, PA610, PVDF-HFP
                 re.compile(r"(?<![\w-])[a-z][A-Z]{2,}[A-Za-z0-9-]*(?![\w-])"),  # iPP, sPS
                 re.compile(r"\(([A-Z][\w-]{1,20})\)"))  # (Kynol)
CITED = re.compile(r"(?<![\w:])((?:finding|note):[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9])")
DOI_IN_URL = re.compile(r"(10\.\d{4,9}/[^\s?#&]+)", re.I)


def _norm(text):
    return " ".join((text or "").split()).casefold()


def _key(doi="", url=""):
    return knowledge.source_key(doi or "", url or "")


def _title(text):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return " ".join(words) if len(words) >= 4 else ""


def _ident(prefix, *parts):
    """A stable id for a miss ("m") or hop ("h"): a hash of what identifies it in the pool (its answer, kind and steps
    or finding), so the same pool mined again gives the same ids, which the curator cites and the effects count."""
    return "%s-%s" % (prefix, hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12])


def _git(folder, *args):
    try:
        return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def meta():
    """What every output carries: the pins, the code's commit (and which freeze tag it is) and the harness's."""
    code = _git(common.CODE, "rev-parse", "HEAD")
    tags = {t: _git(common.ROOT, "rev-parse", t + "^{commit}") for t in (pins.TAG, pins.BASE_TAG)}
    dirty = _git(common.STUDY, "status", "--porcelain", "--", "refinement")
    return {"pins": pins.PINS, "code": {"path": str(common.CODE), "commit": code,
                                        "tag": next((t for t, c in tags.items() if c and c == code), None)},
            "harness": (_git(common.STUDY, "rev-parse", "--short=12", "HEAD") or "") + ("-dirty" if dirty else ""),
            "at": now()}


# ----- the base, and replay -----

def base_root(out, kf=None, *, expected=None, release=None):
    """The private copy of KF every replay runs on (`out/workspaces/KF`), made once by `driver.workspace`'s read-only
    backup and refused unless its fingerprint (`expected`, default KF's pins) and graph release are KF's."""
    kf = Path(kf or pins.KF)
    if not (kf / ".oopc/loop/knowledge.sqlite").exists():
        raise SystemExit("KF's frozen copy is not at %s (analysis/kf.py makes it)" % kf)
    root = driver.workspace(out, "KF", releases=kf, store=kf)
    found = driver.fingerprint(root)
    if found != (expected or pins.PINS["kf"]):
        raise SystemExit("The base copy %s is not KF (%s); nothing mined" % (root, found))
    current = read_json(root / "releases/current.json")["release_id"]
    if current != (release or pins.PINS["release"]):
        raise SystemExit("The base copy's graph release is %s, not KF's" % current)
    return root


def result_ids(result):
    """A search result's ids as the tool records them: reviewed, added and awaiting-review findings, then notes."""
    return ([f["id"] for group in GROUPED for f in result.get(group) or []]
            + [n["id"] for n in result.get("notes") or []])


_REPLAYS = {}


def _replayed(root, query, limit):
    """A replay's ids and its findings (what the call returns: matches, polymer-only fill, same-source and linked
    findings), cached per (root, query, limit)."""
    key = (str(Path(root).resolve()), query, limit)
    if key not in _REPLAYS:
        result = knowledge.search(root, query, 10 if limit is None else limit, compact=True)
        _REPLAYS[key] = {"ids": result_ids(result),
                         "findings": [f["id"] for group in GROUPED for f in result.get(group) or []]}
    return _REPLAYS[key]


def replay(root, query, limit=None):
    """The ids the researcher's `search_knowledge` returns for (query, limit) on the workspace `root`, in the order it
    records them: exactly the call the tool makes, `knowledge.search(root, q, args.get("limit", 10), compact=True)`."""
    return list(_replayed(root, query, limit)["ids"])


def returned(root, query, limit=None):
    """The findings the same call returns. A finding is "returned" by a search when this call returns it, same-source
    and linked findings included; that is what "the first ten" means everywhere in Part C."""
    return list(_replayed(root, query, limit)["findings"])


def replayable(step):
    return step.get("type") == "store" and step.get("status") == "ok" and isinstance(step.get("q"), str)


@functools.lru_cache(maxsize=None)
def _parts(root, text, strict=True):
    """The polymers a text names on `root`'s graph, as the search reads them: (name, names, ids) each, and its other
    words."""
    polymers, words = knowledge._query_parts(root, text or "", strict=strict)
    return (tuple((p["name"], frozenset(p["names"]), frozenset(p["ids"])) for p in polymers), tuple(words))


def _ids(root, text, strict=True):
    polymers = _parts(str(root), text, strict)[0]
    return frozenset().union(*(p[2] for p in polymers)) if polymers else frozenset()


def _labels(root):
    return knowledge._graph_families(root)[2]


def candidate_names(text):
    """Candidate polymer names in `text`: poly- and nylon names, abbreviations in capitals, parenthesized names. Leads
    for the curator, found by pattern."""
    found = []
    for pattern in NAME_PATTERNS:
        for match in pattern.finditer(text or ""):
            name = (match.group(1) if pattern.groups else match.group(0)).strip(" ,;.-")
            if len(name) >= 2 and name.lower() not in NOT_NAMES and not name.isdigit() and not any(
                    name.lower() in f.lower() for f in found):
                found.append(name)
    return found


def known_name(root, name):
    """Whether `root`'s graph has the name (in any case), whether or not the search reads it as written there."""
    return bool(knowledge.polymer_ids(str(root), name) or _parts(str(root), name, False)[0])


def names_in(text, root):
    """The candidate names in `text` that `root`'s graph does not have."""
    return [n for n in candidate_names(text) if not known_name(root, n)]


def topic(question):
    """A question's property wording when its generator recorded none: its first sentence without the polymer it is
    "for" and the template's verbs ("find one open primary study of ...", "explain ... using one open primary
    study")."""
    first = re.split(r"(?<=[.?!])\s", (question or "").strip(), maxsplit=1)[0]
    first = re.sub(r"^for [^,]{1,160},\s*", "", first, flags=re.I)
    first = re.sub(r"^(find one open primary study of|explain|assess|describe, from a primary source,|describe|"
                   r"report)\s+", "", first, flags=re.I)
    return re.sub(r"\s+using one open primary study$", "", first.rstrip(" .?!"), flags=re.I)


# ----- the store, read-only -----

class Store:
    """What mining reads of a workspace's store: findings, notes, merges, deposits, and (freeze-3) links and terms."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        db = sqlite3.connect(knowledge.database(self.root).as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.findings = {r["id"]: dict(r) for r in db.execute(
                "SELECT id, question_id, statement, material, property, value, unit, subject, source_title, "
                "source_url, source_doi, status, created_at FROM findings ORDER BY rowid")}
            self.notes = {r["id"]: dict(r) for r in db.execute("SELECT * FROM notes ORDER BY rowid")}
            self.merged = dict(db.execute("SELECT id, into_id FROM merged").fetchall()) if "merged" in tables else {}
            self.deposits = ({r["question_id"]: dict(r) for r in db.execute("SELECT * FROM deposits")}
                             if "deposits" in tables else {})
            self.links = ([dict(r) for r in db.execute("SELECT * FROM source_links")]
                          if "source_links" in tables else [])
            self.terms = ([dict(r) for r in db.execute("SELECT * FROM property_terms")]
                          if "property_terms" in tables else [])
        finally:
            db.close()
        self.by_source, self.by_question = collections.defaultdict(list), collections.defaultdict(list)
        self.note_keys, self.read_urls, self.titles = collections.defaultdict(list), {}, {}
        for fid, f in self.findings.items():
            f["key"] = _key(f["source_doi"], f["source_url"])
            if f["key"]:
                self.by_source[f["key"]].append(fid)
                self.titles.setdefault(f["key"], f["source_title"] or "")
            self.by_question[f["question_id"]].append(fid)
        for nid, n in self.notes.items():
            n["key"] = _key(n.get("doi"), n.get("url"))
            if n["key"]:
                self.note_keys[n["key"]].append(nid)
                if n.get("read_url"):
                    self.read_urls.setdefault(_key("", n["read_url"]), n["key"])
                if not self.titles.get(n["key"]):
                    self.titles[n["key"]] = n.get("title") or ""
        self.held = set(self.by_source) | set(self.note_keys)
        self.linked = collections.defaultdict(set)
        for link in self.links:
            self.linked[link["a"]].add(link["b"])
            self.linked[link["b"]].add(link["a"])

    def resolve(self, identifier):
        """A finding id, followed through merges (`upkeep.duplicates`) to the finding it now is; None if unknown."""
        seen = set()
        while identifier not in self.findings and identifier in self.merged and identifier not in seen:
            seen.add(identifier)
            identifier = self.merged[identifier]
        return identifier if identifier in self.findings else None


def _fact(row):
    return {"statement": row["statement"], "material": row["material"], "property": row["property"],
            "value": row["value"], "unit": row["unit"], "sourceDoi": row["source_doi"], "sourceUrl": row["source_url"]}


# ----- properties -----

def property_words(text):
    """Significant words of a property wording, stemmed as the search stems them."""
    return {knowledge.stem(w) for w in re.findall(r"[a-z][a-z0-9-]+", (text or "").lower())
            if len(w) >= 3 and w not in knowledge.STOPWORDS and w not in GENERIC}


def parts(text):
    """A property wording's parts: "water uptake and dimensional swelling" is two."""
    found = [p for p in re.split(r"\s*(?:,|;|/|\band\b|\bor\b|\bversus\b|\bvs\.?)\s*", text or "")
             if rules.normalize(p)]
    return found or [text or ""]


class Properties:
    """Property classes from A1's map of KF (`pins.PROPERTY_MAP`), and its ordered rules for other wordings."""

    def __init__(self, path=None):
        path = Path(path) if path else pins.PROPERTY_MAP
        self.map = read_json(path) if path.exists() else {}
        self.source = str(path) if path.exists() else None
        self._classes = {}

    def classes(self, text):
        """A wording's classes: A1's map entry when the map holds the whole wording, else its parts' (split at commas,
        "and", "or", "versus"), each by the map, else by A1's ordered rules."""
        if text not in self._classes:
            entry = self.map.get(rules.normalize(text or ""))
            if entry:
                found = {entry.get("class")}
            else:
                found = set()
                for part in parts(text):
                    key = rules.normalize(part)
                    entry = self.map.get(key)
                    found.add(entry.get("class") if entry else rules.classify(key)[0])
            self._classes[text] = frozenset(found - {None})
        return self._classes[text]

    def same(self, question, finding, loose=False):
        """Whether a finding is on the question's property, part by part of the question's wording: a part with a class
        needs the finding to share it (when the finding has one), a part without one a shared word; `loose` (a property
        read from the question's text, whose class the rules may take from a side word) also accepts a shared word."""
        theirs, words = self.classes(finding), property_words(finding)
        for part in parts(question):
            mine = self.classes(part)
            if mine and theirs:
                if mine & theirs:
                    return True
                if not loose:
                    continue
            if property_words(part) & words:
                return True
        return False

    def label(self, text):
        found = sorted(self.classes(text))
        return found[0] if found else rules.normalize(text or "")


# ----- the records -----

def _question_texts(path):
    value = read_json(path)
    items = value.get("questions", []) if isinstance(value, dict) else value
    return {_norm(q["question"]) for q in items if isinstance(q, dict) and isinstance(q.get("question"), str)}


def withheld(heldout=None, folder=None):
    """The withheld question texts by set: H (test 1's held-out questions), and N and L once `questions.py` writes
    them (`H.json`, `N.json`, `L.json` in the questions folder, each question's text under `question`)."""
    heldout = Path(heldout or pins.HELDOUT)
    if not heldout.exists():
        raise SystemExit("The held-out questions are not at %s; nothing mined" % heldout)
    sets = {"H": _question_texts(heldout)}
    folder = Path(folder or pins.FOLDERS["questions"])
    for name in pins.SETS:  # questions.py's files; its H is test 1's held-out set again
        if pins.set_path(name, folder).exists():
            sets[name] = sets.get(name, set()) | _question_texts(pins.set_path(name, folder))
    return sets


def fixed_sets(folder=None):
    """The digest of the withheld sets as `questions/hashes.json` fixes them, refused unless it fixes H, N and L and
    each file is still its hash: the plan fixes all three before mining, so no withheld trace enters the pool."""
    folder = Path(folder or pins.FOLDERS["questions"])
    if not (folder / "hashes.json").exists():
        raise SystemExit("The withheld sets are not fixed by hash yet (questions.py hashes); nothing mined")
    sets = read_json(folder / "hashes.json").get("sets") or {}
    for name in pins.SETS:
        path = pins.set_path(name, folder)
        if name not in sets or not path.exists() or digest(read_json(path)) != sets[name]:
            raise SystemExit("%s is not the set questions/hashes.json fixes; nothing mined" % path.name)
    return digest({name: sets[name] for name in pins.SETS})


def stream_answer(path):
    """The answer text a raw session stream ends with, as the engine layer parses it."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    claude = Path(path).name.endswith("-claude-code.jsonl")
    parse = engines.parse_claude_stream if claude else engines.parse_codex_stream
    answer = parse(text)[0]
    try:
        value = json.loads(answer) if answer else None
    except ValueError:
        return None
    return value.get("answer") if isinstance(value, dict) and isinstance(value.get("answer"), str) else None


def stream_tools(path):
    """A session's tools in the order its stream reports them (as the engine layer parses them, with each web action's
    outcome), and each MCP call's arguments in the same order."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    claude = Path(path).name.endswith("-claude-code.jsonl")
    tools = (engines.parse_claude_stream if claude else engines.parse_codex_stream)(text)[2]
    arguments = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if claude and event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and str(block.get("name") or "").startswith("mcp__")):
                    arguments.append(block.get("input") if isinstance(block.get("input"), dict) else {})
        elif not claude and event.get("type") == "item.completed" and isinstance(event.get("item"), dict) \
                and event["item"].get("type") == "mcp_tool_call":
            value = event["item"].get("arguments")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = {}
            arguments.append(value if isinstance(value, dict) else {})
    return tools, arguments


class Streams:
    """Raw session streams in some folders, found by the answer text they end with (an answer two streams end with is
    matched to neither)."""

    def __init__(self, folders):
        self.folders, self._map = [Path(f) for f in folders], None

    def find(self, text):
        if not text:
            return None
        if self._map is None:
            self._map = {}
            for folder in self.folders:
                for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
                    found = stream_answer(path)
                    if found:
                        self._map.setdefault(found, []).append(path)
        paths = self._map.get(text) or []
        return paths[0] if len(paths) == 1 else None


def steps_from(tools, arguments=None):
    """Ordered steps from a session's tools: `store` (with its query and limit when the stream gave them), `graph`
    (an older graph tool), `web-search`, `open` (url and outcome), `find` (within a page) and `other`."""
    steps, given = [], iter(arguments) if arguments is not None else None
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "mcp_tool_call":
            args = next(given, None) if given is not None else None
            if tool.get("tool") == "search_knowledge":
                step = {"type": "store"}
                if isinstance(args, dict) and isinstance(args.get("q"), str):
                    step.update(q=args["q"], limit=args.get("limit"))
                steps.append(step)
            else:
                steps.append({"type": "graph", "tool": tool.get("tool")})
        elif tool.get("type") == "web_search":
            action, inferred = tool.get("action"), False
            if not action:  # loop records before 2026-10-13 name no action
                action = "open" if tool.get("url") else "search" if tool.get("query") else "other"
                inferred = True
            if action == "search":
                step = {"type": "web-search", "query": tool.get("query") or ""}
            elif action in ("open", "find"):
                step = {"type": action, "url": tool.get("url") or (tool.get("query") if action == "open" else "") or "",
                        "outcome": tool.get("outcome") or "unrecorded"}
                if action == "find":
                    step["query"] = tool.get("query") or ""
            else:
                step = {"type": "other"}
            if inferred:
                step["actionFrom"] = "fields"
            steps.append(step)
    return steps


def web_steps(actions):
    """A driver item's web actions (`parity.web_actions`) as steps."""
    return steps_from([dict(a, type="web_search") for a in actions or [] if isinstance(a, dict)])


def trace_searches(root, run_id):
    """A trace's knowledge searches in order (read from its files, never through `TraceStore`, which opens the run for
    writing): arguments, status, and the ids the tool recorded with the sources of the findings among them."""
    path = Path(root) / ".oopc/runs" / str(run_id)
    if not run_id or not (path / "events.jsonl").exists():
        return None
    found = []
    for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("operation") != TOOL:
            continue
        args = (event.get("request") or {}).get("arguments") or {}
        value = {"sequence": event["sequence"], "q": args.get("q"), "limit": args.get("limit"),
                 "status": event.get("status")}
        if event.get("status") == "ok":
            payload = read_json(path / "payloads" / (event["payload_hash"] + ".json"))
            result = payload.get("result") or {}
            value["recorded"] = event.get("result_ids") or result_ids(result)
            sources = [f.get("source") or {} for g in GROUPED for f in result.get(g) or []]
            value["recordedSources"] = sorted({_key(s.get("doi"), s.get("url")) for s in sources} - {""})
        found.append(value)
    return found


def pair(steps, events):
    """Join each store step to its trace event: by query and limit when the stream gave them, else the next in order.
    Events no step claims are appended, marked unordered."""
    used = set()
    for step in steps:
        if step["type"] != "store":
            continue
        if isinstance(step.get("q"), str):
            match = next((i for i, e in enumerate(events) if i not in used and e["q"] == step["q"]
                          and (step.get("limit") is None or e.get("limit") == step.get("limit"))), None)
        else:
            match = next((i for i in range(len(events)) if i not in used), None)
        if match is None:
            step["status"] = "no-event"
            continue
        used.add(match)
        step.update(events[match])
    steps += [dict(e, type="store", unordered=True) for i, e in enumerate(events) if i not in used]
    return steps


def cited(answer):
    """The finding and note ids and the URLs an answer cites (its citations and backticked spans)."""
    text = answer.get("answer") if isinstance(answer.get("answer"), str) else ""
    spans = [c for c in answer.get("citations") or [] if isinstance(c, str)] + re.findall(r"`([^`]+)`", text)
    ids = CITED.findall(" ".join(spans) + " " + text)
    urls = [s.strip() for s in spans if s.strip().startswith(("http://", "https://"))]
    ids = list(dict.fromkeys(ids))
    return {"findings": [i for i in ids if i.startswith("finding:")],
            "notes": [i for i in ids if i.startswith("note:")], "urls": list(dict.fromkeys(urls))}


def reported(answer):
    """The findings an answer reported, as a deposit would clean them."""
    found = []
    for item in answer.get("findings") or []:
        value = knowledge.clean_finding(item)
        if value:
            found.append({k: value[k] for k in ("statement", "material", "property", "value", "unit", "sourceTitle",
                                                 "sourceUrl", "sourceDoi")})
    return found


def sources(answer):
    return [{k: s.get(k) or "" for k in ("title", "url", "doi", "readUrl")}
            for s in answer.get("sources") or [] if isinstance(s, dict)]


def _record(ident, origin, detail, question, answer, *, root, run_id, tools, arguments, order, metadata, started):
    steps = steps_from(tools, arguments)
    events = trace_searches(root, run_id)
    if events is not None:
        pair(steps, events)
    for index, step in enumerate(steps):
        step["i"] = index
    return {"id": ident, "origin": origin, "detail": detail, "questionId": question["id"],
            "question": question["question"], "materials": metadata.get("materials") or [],
            "property": metadata.get("property"), "kind": metadata.get("kind"), "root": str(root), "runId": run_id,
            "trace": events is not None, "orderFrom": order, "steps": steps, "cited": cited(answer),
            "reported": reported(answer), "sources": sources(answer), "startedAt": started}


def question_metadata(campaign=None, observation=None):
    """Material and property of the loop's generated questions, by question id: the campaign's, the 200-task run's."""
    found = {}
    for path in (Path(observation or pins.OBSERVATION), Path(campaign or pins.CAMPAIGN)):
        if path.exists():
            for q in read_json(path):
                materials = q.get("materials") or ([q["material"]] if q.get("material") else [])
                found[q["taskId"]] = {"materials": materials, "property": q.get("property"), "kind": q.get("kind")}
    return found


def live_answers(root=None, *, streams=None, metadata=None, excluded=None):
    """Every completed live-loop answer, normalized."""
    root = Path(root or common.ROOT)
    excluded = excluded if excluded is not None else []
    metadata = question_metadata() if metadata is None else metadata
    index = Streams(pins.LIVE_STREAMS if streams is None else streams)
    folder = root / ".oopc/loop/questions"
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        try:
            question = read_json(path / "question.json")
        except (OSError, ValueError):
            excluded.append({"id": "loop/" + path.name, "reason": "unreadable question record"})
            continue
        if question.get("status") != "completed" or not (path / "result.json").exists():
            excluded.append({"id": "loop/" + path.name, "reason": "not completed"})
            continue
        result = read_json(path / "result.json")
        answer = result.get("answer") if isinstance(result.get("answer"), dict) else {}
        stream = index.find(answer.get("answer"))
        tools, arguments = stream_tools(stream) if stream else (result.get("observedTools") or [], None)
        yield _record("loop/" + path.name, "loop", {"kind": question.get("origin"), "engine": question.get("engine"),
                                                    "stream": stream.name if stream else None},
                      question, answer, root=root, run_id=question.get("runId"), tools=tools, arguments=arguments,
                      order="stream" if stream else "record", metadata=metadata.get(path.name, {}),
                      started=question.get("startedAt") or question.get("submittedAt"))


def part_a_folders(part_a=None):
    """Part A's driver run folders: each experiment's `folders`, and the case-study and planted folders A5 lists."""
    for experiment, name in (part_a or pins.PART_A).items():
        base = common.run_dir(name)
        layout = read_json(base / "experiment.json") if (base / "experiment.json").exists() else {}
        folders = [base / f for f in layout.get("folders", [])]
        for group in layout.get("caseStudies", []) + layout.get("planted", []):
            folders += sorted(p.parent for p in common.run_dir(group).glob("*/plan.json"))
        if (base / "plan.json").exists():
            folders.append(base)
        for folder in folders:
            yield experiment, folder


def driver_answers(folder, *, origin, fingerprint=None, arms=None, web=None, streams=True, excluded=None):
    """The completed answers of a driver folder's researcher arms (those named in `arms`, else those whose plan
    store fingerprint is `fingerprint`, default KF's), normalized; `web` keeps only arms with web search on (True) or
    off (False)."""
    folder = Path(folder)
    excluded = excluded if excluded is not None else []
    plan = read_json(folder / "plan.json")
    name = folder.relative_to(common.run_dir("")) if folder.is_relative_to(common.run_dir("")) else folder
    if "arms" not in plan:
        excluded.append({"id": str(name), "reason": "not a driver plan"})
        return
    index = Streams([folder / "streams"]) if streams else None
    for number, question in enumerate(plan["questions"]):
        for arm in plan["arms"]:
            if arm["kind"] != "researcher" or (arms is not None and arm["name"] not in arms) or (
                    arms is None and plan.get("stores", {}).get(arm["name"]) != (fingerprint or pins.PINS["kf"])):
                continue
            ident = "%s/%04d-%s" % (name, number, arm["name"])
            if web is not None and bool(arm.get("web")) != web:
                excluded.append({"id": ident, "reason": "web search off"})
                continue
            path = folder / "items" / ("%04d-%s.json" % (number, arm["name"]))
            item = read_json(path) if path.exists() else {}
            answered = item.get("answer") if isinstance(item.get("answer"), dict) else None
            if not answered or "error" in answered or not answered.get("runId"):
                excluded.append({"id": ident, "reason": "no completed answer"})
                continue
            answer = answered.get("answer") if isinstance(answered.get("answer"), dict) else {}
            stream = index.find(answer.get("answer")) if index else None
            if stream:
                tools, arguments, order = (*stream_tools(stream), "stream")
                actions = None
            else:
                tools, arguments, order = [], None, "events-then-web"
                actions = answered.get("webActions")
            metadata = {"materials": [question["material"]] if question.get("material") else question.get("materials"),
                        "property": question.get("property"), "kind": question.get("kind")}
            record = _record(ident, origin, {"folder": str(name), "arm": arm["name"], "item": path.stem,
                                             "web": bool(arm.get("web")), "stream": stream.name if stream else None},
                             question, answer, root=arm["root"], run_id=answered["runId"], tools=tools,
                             arguments=arguments, order=order, metadata=metadata, started=None)
            if actions is not None:  # no stream: the store searches first, then the web actions in their order
                record["steps"] = ([s for s in record["steps"] if s["type"] == "store"] + web_steps(actions))
                for index_, step in enumerate(record["steps"]):
                    step["i"] = index_
            yield record


def _before(when, cutoff):
    try:
        return datetime.datetime.fromisoformat(when) < datetime.datetime.fromisoformat(cutoff)
    except (TypeError, ValueError):
        return False


def pool(*, live_root=None, part_a=None, fingerprint=None, heldout=None, questions=None, streams=None, metadata=None,
         pinned=None, cutoff=CUTOFF):
    """The derivation pool and what was left out of it, with the reason. Without `pinned`, a live answer counts only
    when it started before `cutoff` (the hourly loop job runs again, so the live folder grows); with `pinned`, the
    answer ids `pool.json` fixed, the pool is exactly those answers, and one of them gone is refused."""
    excluded = []
    sets = withheld(heldout, questions)
    answers = []

    def keep(record):
        hit = sorted(name for name, texts in sets.items() if _norm(record["question"]) in texts)
        if hit:
            excluded.append({"id": record["id"], "reason": "withheld question (%s)" % ", ".join(hit)})
        elif pinned is not None and record["id"] not in pinned:
            excluded.append({"id": record["id"], "reason": "not in the pinned pool (pool.json)"})
        elif pinned is None and record["origin"] == "loop" and not _before(record["startedAt"], cutoff):
            excluded.append({"id": record["id"], "reason": "started after the pool's cutoff, %s" % cutoff})
        else:
            answers.append(record)
    for record in live_answers(live_root, streams=streams, metadata=metadata, excluded=excluded):
        keep(record)
    for experiment, folder in part_a_folders(part_a):
        for record in driver_answers(folder, origin=experiment, fingerprint=fingerprint, web=True, excluded=excluded):
            keep(record)
    gone = sorted(set(pinned or ()) - {a["id"] for a in answers})
    if gone:
        raise SystemExit("%d answers of the pinned pool are gone or changed (%s); nothing mined"
                         % (len(gone), ", ".join(gone[:5])))
    return answers, excluded


def pinned_pool(out):
    """mine/pool.json's answer ids, refused unless they are still its digest; None before the first mining."""
    path = Path(out) / "pool.json"
    if not path.exists():
        return None
    value = read_json(path)
    if value.get("format") != FORMATS["pool"] or digest(value["answers"]) != value.get("digest"):
        raise SystemExit("mine/pool.json is not a pool its digest fixes; nothing mined")
    return value


# ----- the fidelity check -----

def check(out, base, *, part_a=None, fingerprint=None):
    """Replay every recorded search of Part A's KF arms on the base; write `replay-check.json` and return it. `ok` only
    when there was something to check and every replay reproduced the recorded ids exactly."""
    total, differences, answers = collections.Counter(), [], collections.Counter()
    for experiment, folder in part_a_folders(part_a):
        for record in driver_answers(folder, origin=experiment, fingerprint=fingerprint, streams=False):
            answers[experiment] += 1
            for step in record["steps"]:
                if not replayable(step) or "recorded" not in step:
                    continue
                got = replay(base, step["q"], step.get("limit"))
                total[experiment, "searches"] += 1
                if got == step["recorded"]:
                    total[experiment, "matched"] += 1
                    continue
                differences.append({"answer": record["id"], "runId": record["runId"], "sequence": step["sequence"],
                                    "q": step["q"], "limit": step.get("limit"), "recorded": step["recorded"],
                                    "replayed": got,
                                    "onlyRecorded": [i for i in step["recorded"] if i not in got],
                                    "onlyReplayed": [i for i in got if i not in step["recorded"]]})
    searches = sum(v for (e, k), v in total.items() if k == "searches")
    value = {"ok": searches > 0 and not differences, "searches": searches, "matched": searches - len(differences),
             "differing": len(differences), "answers": sum(answers.values()),
             "byExperiment": {e: {"answers": answers[e], "searches": total[e, "searches"],
                                  "matched": total[e, "matched"]} for e in sorted(answers)},
             "differences": differences[:20], "base": driver.fingerprint(base), "meta": meta()}
    atomic_json(Path(out) / "replay-check.json", value, private=True)
    return value


# ----- mining -----

def doi_in(url):
    """A DOI written in a URL's path (publisher pages: /doi/full/10.1002/...), without page suffixes."""
    match = DOI_IN_URL.search(urllib.parse.unquote(url or ""))
    if not match:
        return ""
    doi, before = match.group(1).lower().rstrip("/."), None
    while doi != before:
        before = doi
        doi = re.sub(r"(/(full|abstract|abs|pdf|epdf|pdfdirect|html|meta|references|figures?|tables?)|\.pdf)$", "",
                     doi).rstrip("/.")
    return doi


def window(item, answer):
    """Where a missed finding should have been reached by: the steps before this index (a web hop: before its open; a
    store hop: before it; a late find, an empty search or an unfiltered query: up to and including that search; a
    finding saved again or an unknown name of the question: the whole answer)."""
    if "class" in item:
        return item["steps"][-1] if item["kind"] == "web" else item["steps"][0]
    if item["kind"] == "saved-again" or "step" not in item:
        return len(answer["steps"])
    return item["step"] + 1


def doi_stem(doi):
    return re.sub(r"(\.s\d{3}|\.sup[\w-]*|/suppl[\w./-]*|_si_?\d*|/v\d+|v\d+)$", "", (doi or "").lower())


class Miner:
    """Misses, hops and the dossier against one base workspace."""

    def __init__(self, base, *, property_map=None, crossref=None):
        self.base = Path(base).resolve()
        self.store = Store(self.base)
        self.props = Properties(property_map)
        self.crossref = Path(crossref) if crossref else pins.CROSSREF
        self._stores = {str(self.base): self.store}
        self.counts = collections.Counter()  # things that are not misses or hops, for the summary

    def store_of(self, root):
        root = str(Path(root).resolve())
        if root not in self._stores:
            self._stores[root] = Store(root)
        return self._stores[root]

    # -- a question's polymers and property on a workspace's graph --

    def context(self, answer, root=None):
        root = str(Path(root or self.base).resolve())
        polymers, unresolved = [], []
        for material in answer.get("materials") or []:
            found = _parts(root, material, False)[0]
            polymers += found
            if not found:
                unresolved.append(material)
        if not answer.get("materials"):
            polymers = list(_parts(root, answer["question"])[0])
        ids = frozenset().union(*(p[2] for p in polymers)) if polymers else frozenset()
        ids |= frozenset(i for i in answer.get("polymerIds") or [] if isinstance(i, str) and knowledge.WOP.match(i))
        names, unknown = set().union(*(p[1] for p in polymers)) if polymers else set(), set()
        for material in unresolved:
            for name in [re.sub(r"\([^()]*\)", " ", material)] + re.findall(r"\(([^()]{2,40})\)", material):
                unknown.add(knowledge._words(name).strip())
        if not answer.get("materials") and not polymers:
            unknown |= {knowledge._words(n).strip() for n in names_in(answer["question"], root)}
        return {"ids": ids, "lineage": frozenset(knowledge.lineage(root, set(ids))), "names": (names | unknown) - {""},
                "unknown": unknown - {""}, "unresolved": unresolved,
                "property": answer.get("property") or topic(answer["question"]),
                "propertyFrom": "recorded" if answer.get("property") else "question"}

    def about(self, finding, ctx):
        if not ctx["lineage"] and not ctx["names"]:
            return None  # the question's polymer is not known: not judged
        if finding["subject"] and finding["subject"] in ctx["lineage"]:
            return True
        topic = knowledge._words((finding["statement"] or "") + " " + (finding["material"] or ""))
        return any(knowledge._mentions(topic, n) for n in ctx["names"])

    def on_property(self, text, ctx):
        return self.props.same(ctx["property"], text, ctx["propertyFrom"] == "question") if ctx["property"] else True

    def relevant(self, fid, ctx, store=None):
        """Not unsupported, about the question's polymer and on its property. When the question's polymer is not
        known (`about` is None), no finding is relevant: a property alone does not make one so."""
        finding = (store or self.store).findings.get(fid)
        return bool(finding and finding["status"] != knowledge.UNSUPPORTED and self.about(finding, ctx)
                    and self.on_property(finding["property"], ctx))

    # -- per answer --

    def replay_steps(self, answer, root=None):
        """Each recorded store search of the answer replayed on `root` (default the base)."""
        root = root or self.base
        return {s["i"]: _replayed(root, s["q"], s.get("limit")) for s in answer["steps"] if replayable(s)}

    def target(self, answer, url):
        """The source keys a page is identified with, and by what."""
        keys, how = [], []
        key = _key("", url)

        def add(value, reason):
            if value and value not in keys:
                keys.append(value)
                how.append(reason)
        add(key, "url")
        doi = doi_in(url)
        add("doi:" + doi if doi else "", "doi in url")
        for note in answer["sources"]:
            if key and key in (_key("", note["url"]), _key("", note["readUrl"])):
                add(_key(note["doi"], note["url"]), "the answer's source note")
        for finding in answer["reported"]:
            if key and key == _key("", finding["sourceUrl"]):
                add(_key(finding["sourceDoi"], finding["sourceUrl"]), "the answer's finding")
        add(self.store.read_urls.get(key, ""), "a saved note read there")
        return keys, how

    def hops(self, answer, ctx=None, replays=None):
        """The answer's web hops and store hops, classed against the base."""
        ctx = ctx or self.context(answer)
        replays = self.replay_steps(answer) if replays is None else replays
        found, run, opened, returned, earlier_ids = [], [], set(), set(), []
        for step in answer["steps"]:
            if step["type"] == "store" and step["i"] in replays:
                got = [f for f in replays[step["i"]]["findings"]]
                if earlier_ids:  # a store search after the first
                    found.append(self._store_hop(answer, ctx, step, got, returned, earlier_ids))
                earlier_ids.append(step["i"])
                returned |= set(got)
            elif step["type"] == "web-search":
                run.append(step)
            elif step["type"] == "open":
                found.append(self._web_hop(answer, run, step, opened, returned))
                if step["outcome"] in OPENED:
                    opened |= set(found[-1]["target"]["keys"])
                run = []
        if run:
            found.append({"answer": answer["id"], "origin": answer["origin"], "kind": "web",
                          "steps": [s["i"] for s in run], "open": None, "searches": [s["query"] for s in run],
                          "class": "search-only"})
        for number, hop in enumerate(found):
            hop["hop"] = number
            hop["id"] = _ident("h", answer["id"], hop["kind"], hop["steps"])
        return found

    def _web_hop(self, answer, run, step, opened, returned):
        keys, how = self.target(answer, step["url"])
        hop = {"answer": answer["id"], "origin": answer["origin"], "kind": "web",
               "steps": [s["i"] for s in run] + [step["i"]], "open": step["i"], "searches": [s["query"] for s in run],
               "url": step["url"], "outcome": step["outcome"], "target": {"keys": keys, "resolvedBy": how}}
        held = [k for k in keys if k in self.store.held]
        hop["target"]["held"] = held
        if step["outcome"] not in OPENED:
            hop["class"] = "failed"
        elif set(keys) & opened:
            hop["class"] = "repeat"
        elif not held:
            hop["class"] = "new-knowledge"
        else:
            used, matched = self.taken(answer, keys)
            hop["target"].update(used=used, matched=matched, heldSince=self.held_since(held, answer))
            hop["class"] = ("unused" if not any(used.values()) else "unsaved-detail" if not matched
                            else "reached-now" if set(matched) & returned else "held-unreached")
        return hop

    def taken(self, answer, keys):
        """What an answer took from a source (any of `keys`), counted by kind: its reported findings from it, its
        deposits from it (a live answer's base findings saved for its question), the saved findings from it that it
        cites, its source notes for it and the addresses it cites there; and the saved findings from it, not
        unsupported, that are those deposits or cited findings or match a reported finding by the store's duplicate
        rule (`knowledge.same_fact`)."""
        keys = set(keys)
        in_source = lambda f: (self.store.findings.get(f) or {}).get("key") in keys  # noqa: E731
        reported = [f for f in answer["reported"] if _key(f["sourceDoi"], f["sourceUrl"]) in keys]
        deposits = {f for f in answer.get("deposited") or [] if in_source(f)}
        cited = {f for f in map(self.store.resolve, answer["cited"]["findings"]) if f and in_source(f)}
        notes = [n for n in answer["sources"] if keys & {_key(n["doi"], n["url"]), _key("", n["readUrl"])}]
        urls = [u for u in answer["cited"]["urls"] if keys & {_key("", u), "doi:" + (doi_in(u) or "-")}]
        matched = [f for k in sorted(keys) for f in self.store.by_source.get(k, [])
                   if self.store.findings[f]["status"] != knowledge.UNSUPPORTED
                   and (f in deposits or f in cited
                        or any(knowledge.same_fact(r, _fact(self.store.findings[f])) for r in reported))]
        return ({"findings": len(reported), "deposits": len(deposits), "cited": len(cited), "notes": len(notes),
                 "citations": len(urls)}, list(dict.fromkeys(matched)))

    def held_since(self, keys, answer):
        """When the base came to hold a source: "before" the answer (saved by another question), by "this answer"
        itself, or only "later"."""
        rows = [self.store.findings[f] for k in keys for f in self.store.by_source.get(k, [])] + [
            self.store.notes[n] for k in keys for n in self.store.note_keys.get(k, [])]
        if any(r["question_id"] != answer["questionId"] and (not answer.get("startedAt")
                                                            or (r["created_at"] or "") < answer["startedAt"])
               for r in rows):
            return "before"
        return "this answer" if any(r["question_id"] == answer["questionId"] for r in rows) else "later"

    def polymers_of(self, query):
        """What a query names: graph ids (with their lineage) and the names the graph does not have."""
        ids = set(_ids(self.base, query))
        return (knowledge.lineage(str(self.base), ids) if ids else set()) | {
            "name:" + _norm(n) for n in names_in(query, self.base)}

    def _store_hop(self, answer, ctx, step, got, returned, earlier):
        new = [f for f in got if f not in returned]
        hop = {"answer": answer["id"], "origin": answer["origin"], "kind": "store", "steps": [step["i"]],
               "q": step["q"], "new": new}
        mine = self.polymers_of(step["q"])
        before = set().union(*(self.polymers_of(s["q"]) for s in answer["steps"] if s["i"] in earlier))
        relevant = [f for f in new if self.relevant(f, ctx)]
        hop["newRelevant"] = relevant
        if not new:
            hop["class"] = "repeat"
        elif mine and before and not (mine & before):
            hop["class"] = "new-polymer"
        else:
            hop["class"] = "held-unreached" if relevant else "other"
        return hop

    def misses(self, answer, ctx=None, replays=None):
        ctx = ctx or self.context(answer)
        replays = self.replay_steps(answer) if replays is None else replays
        stores = [s for s in answer["steps"] if s["i"] in replays]
        returned = set().union(*(set(replays[s["i"]]["findings"]) for s in stores)) if stores else set()
        found = []

        def miss(kind, **fields):
            found.append(dict({"id": _ident("m", answer["id"], kind, fields.get("scope"), fields.get("step"),
                                            fields.get("finding"), fields.get("held")),
                               "kind": kind, "answer": answer["id"], "origin": answer["origin"]}, **fields))
        # 1. saved again
        seen = set()
        for finding in answer["reported"]:
            key = _key(finding["sourceDoi"], finding["sourceUrl"])
            held = [i for i in self.store.by_source.get(key, []) if self._earlier(i, answer)
                    and knowledge.same_fact(finding, _fact(self.store.findings[i]))]
            if not held or tuple(held) in seen:
                continue
            seen.add(tuple(held))
            if returned & set(held):
                self.counts["savedAgainReturned"] += 1
            else:
                miss("saved-again", held=held, reported=finding["statement"][:300],
                     steps=[s["i"] for s in stores])
        # 2. unresolved names
        if ctx["unresolved"]:
            miss("unresolved-name", scope="question", names=ctx["unresolved"])
        elif not answer.get("materials") and not ctx["ids"]:
            names = names_in(answer["question"], self.base)
            if names:
                miss("unresolved-name", scope="question", names=names)
        unknown = sorted(ctx["unknown"])
        for step in stores:
            if _parts(str(self.base), step["q"])[0]:
                continue
            words = knowledge._words(step["q"])
            names = names_in(step["q"], self.base) + [n for n in unknown if knowledge._mentions(words, n)]
            if names:
                miss("unresolved-name", scope="query", step=step["i"], q=step["q"], names=list(dict.fromkeys(names)))
            elif any(known_name(self.base, n) for n in candidate_names(step["q"])):
                self.counts["unfilteredKnownName"] += 1  # a name the graph has, not read as written (PPy, pa66)
            else:
                self.counts["unfilteredWithoutName"] += 1
        # 3. late finds (two cited ids that merges made one finding count once)
        late = set()
        for fid in answer["cited"]["findings"]:
            resolved = self.store.resolve(fid)
            if not resolved:
                self.counts["citedNotInBase"] += 1
                continue
            if not stores or resolved in late:
                continue
            late.add(resolved)
            anchor = self._anchor(self.store.findings[resolved], stores)
            upto = [s for s in stores if s["i"] <= anchor["i"]]
            if not any(resolved in replays[s["i"]]["findings"] for s in upto):
                later = next((s["i"] for s in stores if resolved in replays[s["i"]]["findings"]), None)
                miss("late-find", finding=resolved, step=anchor["i"], q=anchor["q"], returnedAt=later)
        # 4. empty, then the web (on the base: a search that came back empty when it ran may not be empty now)
        self.counts["emptyAsRecorded"] += sum(1 for s in stores if s.get("recorded") is not None
                                              and not [i for i in s["recorded"] if not i.startswith("note:")])
        self.counts["emptyOnBase"] += sum(1 for s in stores if not replays[s["i"]]["findings"])
        for step in stores:
            if replays[step["i"]]["findings"]:
                continue
            web = next((w for w in answer["steps"] if w["i"] > step["i"] and w["type"] == "web-search"
                        and self._same_topic(step["q"], w["query"])), None)
            if web:
                miss("empty-then-web", step=step["i"], q=step["q"], web=web["i"], webQuery=web["query"])
        return found

    def _earlier(self, fid, answer):
        """A base finding saved before the answer, by another question, and not hidden as unsupported."""
        f = self.store.findings[fid]
        return (f["status"] != knowledge.UNSUPPORTED and f["question_id"] != answer["questionId"]
                and (not answer.get("startedAt") or (f["created_at"] or "") < answer["startedAt"]))

    def _anchor(self, finding, stores):
        """The answer's first store search for the finding's polymer."""
        topic = knowledge._words((finding["statement"] or "") + " " + (finding["material"] or ""))
        for step in stores:
            lineage = knowledge.lineage(str(self.base), set(_ids(self.base, step["q"])))
            if finding["subject"] and finding["subject"] in lineage:
                return step
        for step in stores:
            if any(knowledge._mentions(topic, n) for p in _parts(str(self.base), step["q"])[0] for n in p[1]):
                return step
        return stores[0]

    def _same_topic(self, query, web):
        """A web search for the same polymer (lineage or one of its names) and property (a shared word) as a store
        query."""
        polymers, words = _parts(str(self.base), query)
        names = set().union(*(p[1] for p in polymers)) if polymers else set()
        names |= {knowledge._words(n).strip() for n in names_in(query, self.base)}
        target = knowledge._words(web)
        ids = set().union(*(p[2] for p in polymers)) if polymers else set()
        same_polymer = (bool(ids and _ids(self.base, web) & knowledge.lineage(str(self.base), ids))
                        or any(knowledge._mentions(target, n) for n in names if n))
        rest = {knowledge.stem(w) for w in words if len(w) >= 3 and w not in GENERIC}
        return same_polymer and bool(rest & {knowledge.stem(w) for w in target.split()})

    def unannotated(self):
        """Base findings with no polymer id (scope "finding" of the unresolved-name misses)."""
        return [{"id": _ident("m", None, "unresolved-name", "finding", None, fid, None), "kind": "unresolved-name",
                 "answer": None, "origin": "store", "scope": "finding", "finding": fid, "names": [f["material"] or ""]}
                for fid, f in self.store.findings.items() if not f["subject"] and f["status"] != knowledge.UNSUPPORTED]

    def analyze(self, answer):
        """Adds the answer's deposit (loop answers: the base findings saved for its question, and the duplicates its
        deposit recorded) and replayed ids to its record; returns its misses and hops."""
        if answer["origin"] == "loop":
            deposit = self.store.deposits.get(answer["questionId"]) or {}
            answer["deposited"] = list(self.store.by_question.get(answer["questionId"], []))
            answer["duplicates"] = {"count": deposit.get("duplicates") or 0,
                                    "of": json.loads(deposit.get("duplicate_of") or "[]")}
        ctx, replays = self.context(answer), self.replay_steps(answer)
        for step in answer["steps"]:
            if step["i"] in replays:
                step["replayed"] = replays[step["i"]]["ids"]
        return self.misses(answer, ctx, replays), self.hops(answer, ctx, replays)

    # -- under a refined workspace --

    def reachable(self, answer, hop, root):
        """Whether a held-unreached hop's target is returned on `root` by a store search before it."""
        last = hop["steps"][-1] if hop["kind"] == "web" else hop["steps"][0]
        got = set()
        for step in answer["steps"]:
            if step["i"] < last and replayable(step):
                got |= set(_replayed(root, step["q"], step.get("limit"))["findings"])
        if hop["kind"] == "web":
            return bool(got & set(hop["target"].get("matched") or []))
        return bool(hop["newRelevant"]) and set(hop["newRelevant"]) <= got

    def classify(self, answer, root=None, build=None):
        """The answer's hops on the base; with a refined workspace `root`, held-unreached hops split into `reachable`
        and `still-unreached`; with `build` (edit groups -> workspace root), each reachable hop's groups. A refined
        root is searched only by the code under test (`pins.frozen`): freeze-2 would ignore its links and terms."""
        hops = self.hops(answer)
        if root is None:
            return hops
        pins.frozen()
        for hop in hops:
            if hop["class"] != "held-unreached":
                continue
            hop["refined"] = "reachable" if self.reachable(answer, hop, root) else "still-unreached"
            if hop["refined"] == "reachable" and build is not None:
                alone = [g for g in pins.GROUPS if self.reachable(answer, hop, build(frozenset([g])))]
                hop["groups"] = alone or ["joint"]
        return hops

    def fixed(self, miss, answer, root):
        """Whether an edit's workspace `root` fixes a miss."""
        if miss["kind"] == "unresolved-name":
            if miss["scope"] == "finding":
                finding = self.store_of(root).findings.get(miss["finding"]) or {}
                return bool(finding.get("subject")) or bool(_parts(str(Path(root).resolve()), finding.get("material")
                                                                    or "", False)[0])
            if miss["scope"] == "query":
                return bool(_parts(str(Path(root).resolve()), miss["q"])[0])
            ctx = self.context(answer, root)
            return not ctx["unresolved"] and bool(ctx["ids"])
        steps = {s["i"]: s for s in answer["steps"] if replayable(s)}
        got = lambda i: set(_replayed(root, steps[i]["q"], steps[i].get("limit"))["findings"])  # noqa: E731
        if miss["kind"] == "saved-again":
            return any(set(miss["held"]) & got(i) for i in steps)
        if miss["kind"] == "late-find":
            return miss["finding"] in got(miss["step"])
        return bool(got(miss["step"]))  # empty-then-web: the search now returns a finding

    # -- the dossier --

    def features(self, answer, item, findings):
        """Candidate edit features of missed findings in an answer, from what came before them in it."""
        stop = window(item, answer)
        earlier = [s for s in answer["steps"] if s["i"] < stop]
        queries = [s["q"] for s in earlier if replayable(s)] or ([item["q"]] if item.get("q") else [])
        words = set().union(*(set(_parts(str(self.base), q)[1]) for q in queries)) if queries else set()
        sources = []
        for step in earlier:
            if step["type"] == "store":
                sources += step.get("recordedSources") or []
                sources += [self.store.findings[f]["key"] for f in step.get("replayed") or []
                            if f in self.store.findings]
            elif step["type"] == "open" and step["outcome"] in OPENED:
                sources += self.target(answer, step["url"])[0]
        sources = [k for k in dict.fromkeys(sources) if k]
        names, terms, pairs, look = [], [], [], []
        for fid in findings:
            f = self.store.findings.get(fid)
            if not f:
                continue
            if not f["subject"]:
                names.append({"finding": fid, "why": "no polymer id", "material": f["material"]})
            elif f["material"] and not _parts(str(self.base), f["material"], False)[0]:
                names.append({"finding": fid, "why": "material the graph does not know", "material": f["material"]})
            if words and not any(knowledge._has_word(knowledge._words(f["property"]), w) for w in words):
                terms.append({"finding": fid, "property": f["property"], "queryWords": sorted(words)[:12]})
            for other in sources:
                if other == f["key"]:
                    continue
                evidence = self.related(other, f["key"])
                if evidence:
                    pairs.append({"a": other, "b": f["key"], "evidence": evidence})
                else:
                    look.append({"a": other, "b": f["key"]})
        unique = lambda rows: list({json.dumps(r, sort_keys=True): r for r in rows}.values())  # noqa: E731
        return {"name": unique(names), "property-term": unique(terms), "source-link": unique(pairs)}, unique(look)

    def related(self, a, b):
        """What two sources share that could state a link: a DOI stem, a title, a Crossref relation."""
        evidence = []
        if a.startswith("doi:") and b.startswith("doi:"):
            x, y = a[4:], b[4:]
            if doi_stem(x) == doi_stem(y) or x.startswith(y + ".") or y.startswith(x + ".") or x.startswith(y + "/") \
                    or y.startswith(x + "/"):
                evidence.append({"kind": "doi-stem"})
            for one, two in ((x, y), (y, x)):
                for relation, ids in self._relations(one).items():
                    if two in ids:
                        evidence.append({"kind": "crossref", "relation": relation, "of": one,
                                         "as": RELATIONS.get(relation)})
        first, second = _title(self.store.titles.get(a)), _title(self.store.titles.get(b))
        if first and first == second:
            evidence.append({"kind": "title", "title": self.store.titles.get(a)})
        return evidence

    @functools.lru_cache(maxsize=None)
    def _relations(self, doi):
        path = self.crossref / (hashlib.sha1(doi.lower().encode("utf-8")).hexdigest() + ".json")
        try:
            message = read_json(path).get("message") or {}
        except (OSError, ValueError):
            return {}
        return {name: {str(r.get("id") or "").lower() for r in items if isinstance(r, dict)}
                for name, items in (message.get("relation") or {}).items() if isinstance(items, list)}

    def _finding_view(self, fid):
        f = self.store.findings[fid]
        labels = _labels(str(self.base))
        return {"id": fid, "statement": (f["statement"] or "")[:300], "material": f["material"],
                "property": f["property"], "propertyClass": sorted(self.props.classes(f["property"])),
                "subject": f["subject"], "subjectLabel": labels.get(f["subject"]) if f["subject"] else None,
                "source": {"key": f["key"], "title": f["source_title"], "doi": f["source_doi"], "url": f["source_url"]}}

    def dossier(self, answers, misses, hops):
        """Misses and held-unreached hops grouped by candidate source pair, unknown name, or polymer and property."""
        by_id = {a["id"]: a for a in answers}
        labels = _labels(str(self.base))
        groups = {}
        items = [("miss", m) for m in misses] + [("hop", h) for h in hops if h["class"] == "held-unreached"]
        for what, item in items:
            answer = by_id.get(item["answer"])
            if item["kind"] == "saved-again":
                findings = item["held"]
            elif item["kind"] == "late-find":
                findings = [item["finding"]]
            elif what == "hop":
                findings = item["target"]["matched"] if item["kind"] == "web" else item["newRelevant"]
            elif item.get("scope") == "finding":
                findings = [item["finding"]]
            else:
                findings = []
            candidates, look = self.features(answer, item, findings) if answer else (
                {"name": [], "property-term": [], "source-link": []}, [])
            if item["kind"] == "unresolved-name":
                name = item["names"][0] if item.get("names") else ""
                key = ("name", _norm(name))
            elif candidates["source-link"]:
                pair_ = candidates["source-link"][0]
                key = ("source-pair",) + tuple(sorted((pair_["a"], pair_["b"])))
            else:
                ctx = self.context(answer) if answer else {"ids": frozenset(), "property": None}
                first = self.store.findings.get(findings[0]) if findings else None
                polymer = (labels.get(first["subject"]) if first and first["subject"] else None) or ", ".join(
                    sorted(labels.get(i, i) for i in ctx["ids"])) or ", ".join(answer.get("materials") or []) or "?"
                prop = self.props.label(first["property"]) if first else (
                    self.props.label(ctx["property"]) if ctx.get("property") else self.props.label(item.get("q") or ""))
                key = ("polymer-property", polymer, prop)
            group = groups.setdefault(key, {"by": key[0], "key": list(key[1:]), "count": 0, "misses": [], "hops": [],
                                            "kinds": collections.Counter(), "answers": set(), "examples": [],
                                            "queries": [], "findings": [], "candidates": {
                                                "name": [], "property-term": [], "source-link": []},
                                            "lookAt": []})
            group["count"] += 1
            group["misses" if what == "miss" else "hops"].append(item["id"])  # every id an edit may cite
            group["kinds"][("hop:%s:%s" % (item["kind"], item["class"])) if what == "hop" else item["kind"]] += 1
            if answer:
                group["answers"].add(answer["id"])
                if len(group["examples"]) < SHOWN["examples"]:
                    group["examples"].append({"id": item["id"], "answer": answer["id"],
                                              "question": answer["question"][:300],
                                              "steps": item.get("steps") or ([item["step"]] if "step" in item else []),
                                              "kind": item["kind"]})
                stop = window(item, answer)
                for step in answer["steps"]:
                    if replayable(step) and step["i"] < stop and step["q"] not in group["queries"] \
                            and len(group["queries"]) < SHOWN["queries"]:
                        group["queries"].append(step["q"])
            if item.get("names") and item["kind"] == "unresolved-name":
                row = {"names": item["names"], "scope": item["scope"]}
                if row not in group["candidates"]["name"]:
                    group["candidates"]["name"].append(row)
            for fid in findings:
                if fid in self.store.findings and all(f["id"] != fid for f in group["findings"]) \
                        and len(group["findings"]) < SHOWN["findings"]:
                    group["findings"].append(self._finding_view(fid))
            for kind in group["candidates"]:
                for row in candidates[kind]:
                    if row not in group["candidates"][kind]:
                        group["candidates"][kind].append(row)
            for row in look:
                if row not in group["lookAt"] and len(group["lookAt"]) < SHOWN["lookAt"]:
                    group["lookAt"].append(row)
        ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["by"], g["key"]))
        for number, group in enumerate(ordered, 1):
            group.update(group="g-%04d" % number, kinds=dict(group["kinds"]), answers=len(group["answers"]))
            if group["lookAt"]:
                group["lookAtNote"] = ("These sources only co-occurred in a trace: a reason to look, never evidence "
                                       "of a link.")
        return ordered


# ----- edit effects -----

_VIEWS = {}
SHOWN_LOST = 50  # lost results listed per root (all are counted)


def _graph(root):
    """What search reads of a workspace's graph: each name (lower case) with its other names, each name with its
    polymer ids, and every polymer."""
    root = str(Path(root).resolve())
    names = knowledge.polymer_aliases(root)
    ids = knowledge._POLYMER_IDS.get(str(resolve_release(root)), {})
    up, down, labels = knowledge._graph_families(root)
    linked = {p for links in (up, down) for found in links.values() for p in found}
    return names, ids, set(labels) | set(up) | set(down) | linked | {p for found in ids.values() for p in found}


def _terms(text):
    names = json.loads(text or "[]")
    return tuple(n for n in names if isinstance(n, str)) if isinstance(names, list) else ()


def _view(root):
    """What search reads of a workspace's store that an edit can change: each finding's polymer id and indexed text,
    the source links and the property terms (read only, cached per root)."""
    key = str(Path(root).resolve())
    if key not in _VIEWS:
        db = sqlite3.connect(knowledge.database(key).as_uri() + "?mode=ro", uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            _VIEWS[key] = {"subjects": {i: s or "" for i, s in db.execute("SELECT id, subject FROM findings")},
                           "text": dict(db.execute("SELECT id, text FROM findings_fts")),
                           "links": (set(db.execute("SELECT a, relation, b FROM source_links"))
                                     if "source_links" in tables else set()),
                           "terms": ({t: _terms(n) for t, n in db.execute("SELECT term, names FROM property_terms")}
                                     if "property_terms" in tables else {})}
        finally:
            db.close()
    return _VIEWS[key]


def difference(miner, root):
    """What search reads differently on the workspace `root` than on the base: the names whose graph entry differs
    (their other names or polymer ids), the polymers whose lineage differs, the findings whose polymer id differs
    (base id, root id), the findings whose index text differs (an annotation edit re-indexes its finding), and the
    source links and property terms that differ. `phrases` are the names a search's query must mention to be replayed
    (`affected`), `renamed` the names whose entry differs."""
    base, root = str(miner.base), str(Path(root).resolve())
    (a_names, a_ids, a_polymers), (b_names, b_ids, b_polymers) = _graph(base), _graph(root)
    names = {n for n in set(a_names) | set(b_names) | set(a_ids) | set(b_ids)
             if a_names.get(n) != b_names.get(n) or a_ids.get(n) != b_ids.get(n)}
    moved = {p for p in a_polymers | b_polymers if knowledge.lineage(base, {p}) != knowledge.lineage(root, {p})}
    mine_, theirs = _view(base), _view(root)
    if set(mine_["subjects"]) != set(theirs["subjects"]):
        raise SystemExit("%s does not hold exactly the base's findings" % root)
    subjects = {f: (mine_["subjects"][f], s) for f, s in theirs["subjects"].items() if s != mine_["subjects"][f]}
    filed = {s for pair in subjects.values() for s in pair if s}
    polymers = moved | knowledge.lineage(base, filed) | knowledge.lineage(root, filed)
    terms = {t for t in set(mine_["terms"]) | set(theirs["terms"]) if mine_["terms"].get(t) != theirs["terms"].get(t)}
    links = mine_["links"] ^ theirs["links"]
    named = names | {n for n, found in list(a_ids.items()) + list(b_ids.items()) if found & polymers}
    named |= {n for t in terms for n in mine_["terms"].get(t, ()) + theirs["terms"].get(t, ())}
    return {"names": sorted(names), "lineage": sorted(moved), "subjects": subjects, "polymers": sorted(polymers),
            "reindexed": {f for f, t in theirs["text"].items() if t != mine_["text"].get(f)},
            "links": sorted(links), "sources": {k for a, _, b in links for k in (a, b)}, "terms": sorted(terms),
            "phrases": {knowledge._words(n).strip() for n in named} - {""},
            "renamed": {knowledge._words(n).strip() for n in names} - {""}}


def _mentions_any(text, phrases):
    words = knowledge._words(text)
    return any(" %s " % p in words for p in phrases)


def affected(miner, diff, q, limit):
    """The replay rule: whether the search (q, limit) can return something else on a root than on the base, given what
    the root reads differently (`difference`). It is replayed when
    1. its query mentions, as whole words (`knowledge._words`, which both the search's reading of polymer names and its
       expansion by other names imply), a name whose graph entry differs, a name of a polymer whose lineage differs, or
       a name of a polymer in the lineage of a polymer id some finding's id changed from or to;
    2. its query mentions a name of a property term that differs (freeze-3 reads a term only when a query names it);
    3. on the base it returns a finding or note from a source a differing link joins (freeze-3 follows links only from
       the sources a search returns); or
    4. on the base it returns a finding whose index text differs.
    Otherwise it returns on the root what it returns on the base: search reads the graph only through names, families
    and lineages, and the store through the findings and these tables. What the rule leaves out: re-indexing one
    finding's text (an annotation) shifts the full-text ranking's corpus statistics for every query by a hair; a search
    not returning that finding is taken as unchanged."""
    if _mentions_any(q, diff["phrases"]):
        return True
    if diff["sources"] or diff["reindexed"]:
        got, store = _replayed(miner.base, q, limit), miner.store
        if diff["reindexed"] & set(got["findings"]):
            return True
        keys = {store.findings[i]["key"] for i in got["findings"] if i in store.findings}
        keys |= {store.notes[i]["key"] for i in got["ids"] if i in store.notes}
        return bool(keys & diff["sources"])
    return False


def _may_fix(miss, answer, diff):
    """Whether a root can fix an unresolved name at all: only through a name whose graph entry differs, mentioned
    where the miss names it, or (a finding's material) a polymer id the root gives the finding. Every other miss is
    settled by replayed searches."""
    if miss["kind"] != "unresolved-name":
        return True
    if miss["scope"] == "finding" and miss["finding"] in diff["subjects"]:
        return True
    texts = {"finding": miss.get("names") or [], "query": [miss.get("q") or ""]}.get(miss["scope"]) or (
        list((answer or {}).get("materials") or []) + [(answer or {}).get("question") or ""])
    return any(_mentions_any(t, diff["renamed"]) for t in texts)


def pool_searches(answers):
    """The derivation pool's recorded searches, each (query, limit) once."""
    return list(dict.fromkeys((s["q"], s.get("limit")) for a in answers for s in a["steps"] if replayable(s)))


def measure(miner, root, answers, misses, hops, *, searches=None, before=None):
    """A root's effect on the derivation pool against the base: the misses it fixes (fixed on the root and not on the
    base), the held-unreached hops it makes reachable, and the results it loses (a finding a search returned and its
    answer cited, which the same call no longer returns), by their ids. Only the searches the replay rule selects
    (`affected`) are replayed on the root; for the rest the base's result stands in. `before` caches whether the base
    already fixes a miss, across roots."""
    started = time.monotonic()
    root = Path(root).resolve()
    diff = difference(miner, root)
    searches = pool_searches(answers) if searches is None else searches
    selected = 0
    for q, limit in searches:
        if affected(miner, diff, q, limit):
            selected += 1
        else:
            _REPLAYS[(str(root), q, limit)] = _replayed(miner.base, q, limit)
    by_id, before = {a["id"]: a for a in answers}, {} if before is None else before
    fixed = []
    for m in misses:
        answer = by_id.get(m["answer"])
        if not _may_fix(m, answer, diff):
            continue
        if m["id"] not in before:
            before[m["id"]] = miner.fixed(m, answer, miner.base)
        if not before[m["id"]] and miner.fixed(m, answer, root):
            fixed.append(m)
    reachable = [h for h in hops if h["class"] == "held-unreached" and miner.reachable(by_id[h["answer"]], h, root)]
    lost = []
    for answer in answers:
        cited = {miner.store.resolve(f) for f in answer["cited"]["findings"]} - {None}
        for step in answer["steps"]:
            if not replayable(step):
                continue
            was = set(returned(miner.base, step["q"], step.get("limit"))) & cited
            if was:
                lost += [{"answer": answer["id"], "step": step["i"], "finding": f}
                         for f in sorted(was - set(returned(root, step["q"], step.get("limit"))))]
    return {"missesFixed": len(fixed), "hopsReachable": len(reachable), "resultsLost": len(lost),
            "byKind": dict(collections.Counter(m["kind"] for m in fixed)),
            "byHop": dict(collections.Counter(h["kind"] for h in reachable)),
            "fixed": [m["id"] for m in fixed], "reachable": [h["id"] for h in reachable], "lost": lost[:SHOWN_LOST],
            "changes": {"names": len(diff["names"]), "lineages": len(diff["lineage"]),
                        "polymerIds": len(diff["subjects"]), "reindexed": len(diff["reindexed"]),
                        "links": len(diff["links"]), "terms": len(diff["terms"])},
            "searches": {"pool": len(searches), "replayed": selected},
            "seconds": round(time.monotonic() - started, 1)}


def forget(miner):
    """Drop every cached replay, store, view and graph of a root that no longer exists (an edit's root, deleted after
    its replay), so the caches stay small and a later root at the same path is read afresh."""
    gone = functools.lru_cache(maxsize=None)(lambda path: not os.path.exists(path))
    for key in [k for k in _REPLAYS if gone(k[0])]:
        del _REPLAYS[key]
    for cache in (_VIEWS, miner._stores, knowledge._ALIASES, knowledge._POLYMER_IDS, knowledge._FAMILIES):
        for key in [k for k in cache if gone(k)]:
            del cache[key]
    _parts.cache_clear()


def dropped(effect):
    """An edit that loses more results than it fixes misses and makes hops reachable (plan, Procedure step 4)."""
    return effect["resultsLost"] > effect["missesFixed"] + effect["hopsReachable"]


def effects(miner, edits, build, answers, misses, hops, *, done=None, cites=None, save=None):
    """Each edit's effect on the derivation pool, with that edit alone (`measure`). `build(edit)` is a context
    manager giving a workspace root that carries the edit alone and is deleted when the block ends; the caches that
    held it are dropped then (`forget`). `done`: effects already measured, kept; `cites`: edit -> the miss and hop ids
    its curator cited, counted as fixed or reachable; `save(value)` is called after each edit. Only the code under test
    searches a refined root (`pins.frozen`)."""
    pins.frozen()
    value, searches, before = dict(done or {}), pool_searches(answers), {}
    for edit in edits:
        if edit in value:
            continue
        with build(edit) as root:
            value[edit] = measure(miner, root, answers, misses, hops, searches=searches, before=before)
        forget(miner)
        if cites and edit in cites:
            misses_, hops_ = (set(x) for x in cites[edit])
            value[edit]["cited"] = {"misses": len(misses_), "fixed": len(misses_ & set(value[edit]["fixed"])),
                                    "hops": len(hops_), "reachable": len(hops_ & set(value[edit]["reachable"]))}
        if save:
            save(value)
    return value


def effect_inputs(commit, out=None):
    """What the edit effects are measured on: the overlay's three files, the mined outputs (the pinned pool, answers,
    misses and hops), by SHA-256 (None when absent), and the code's commit. `overlay.py build` refuses unless
    `mine/effects.json` names exactly these."""
    out, folder = Path(out or pins.FOLDERS["mine"]), pins.FOLDERS["overlay"]
    paths = [folder / n for n in ("edits.json", "graph-overlay.json", "store-overlay.json")]
    paths += [out / n for n in ("pool.json", "answers.jsonl", "misses.json", "hops.json")]
    return {"files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths},
            "code": commit}


@contextlib.contextmanager
def _temporary(folder, in_force, plain):
    """A builder for `effects`: each edit's root under `folder/<edit>`, deleted after its replay."""
    from refinement import overlay

    def build(edit):
        target = Path(folder) / edit
        shutil.rmtree(target, ignore_errors=True)
        try:
            yield overlay.edit_root(target, [edit], in_force=in_force, plain=plain)
        finally:
            shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(folder, ignore_errors=True)
    try:
        yield contextlib.contextmanager(build)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_effects(out=None):
    """The drop step (plan, Procedure step 4), after `overlay.py check` and before `overlay.py build`, from
    derivation data only (the mined pool): each approved edit in force, alone, on its own root (`overlay.edit_root`, in
    `mine/effects-roots/`, deleted after its replay); an edit whose results lost exceed its misses fixed plus hops made
    reachable goes to `overlay/excluded.json` with its numbers; then the group roots' totals (`overlay.root_for` per
    group and all groups together, with the exclusions), for the attribution. Writes `mine/effects.json` after every
    edit, so a rerun on the same inputs resumes; on other inputs it is refused."""
    from refinement import overlay
    commit = pins.frozen()
    out = Path(out) if out else pins.folder("mine")
    if not (out / "pool.json").exists():
        raise SystemExit("mine/pool.json is missing: run mine.py mine first")
    overlay.checked()
    inputs, path = effect_inputs(commit, out), out / "effects.json"
    value = read_json(path) if path.exists() else {"format": FORMATS["effects"], "inputs": inputs, "edits": {}}
    if value.get("format") != FORMATS["effects"] or value.get("inputs") != inputs:
        raise SystemExit("mine/effects.json was measured on other inputs (overlay files, mined pool or code); move it "
                         "and the exclusions it wrote aside before measuring again")
    in_force = overlay.overlays()
    active, excluded = in_force[0], in_force[3]
    answers, misses, hops = load(out)
    if any("id" not in item for item in misses + hops):
        raise SystemExit("mine/misses.json or hops.json has no ids (mined before they had them): mine again first")
    with locked(pins.folder("overlay") / "build.lock"):
        plain = overlay.seed_root()
    miner = Miner(base_root(out))
    value["rule"] = " ".join(affected.__doc__.split())

    def save(edits):
        atomic_json(path, dict(value, edits=edits, complete=False, at=now()), private=True)
    cites = {e: (active[e].get("misses") or [], active[e].get("hops") or []) for e in active}
    with _temporary(out / "effects-roots", in_force, plain) as build:
        edits = effects(miner, sorted(active), build, answers, misses, hops, done=value["edits"], cites=cites,
                        save=save)
    approved = read_json(pins.FOLDERS["overlay"] / "edits.json")["edits"]
    for eid, effect in edits.items():
        effect["type"] = approved[eid]["type"]
    value["dropped"] = sorted(e for e, effect in edits.items() if dropped(effect))
    new = {e: "the derivation-pool replay (mine/effects.json): it loses %d results and fixes %d misses and makes %d "
              "hops reachable" % (edits[e]["resultsLost"], edits[e]["missesFixed"], edits[e]["hopsReachable"])
           for e in value["dropped"] if e not in excluded}
    if new:
        atomic_json(pins.folder("overlay") / "excluded.json",
                    {"format": overlay.FORMATS["excluded"], "edits": dict(excluded, **new)}, private=True)
    groups = {}
    for name in list(pins.GROUPS) + ["all"]:
        root = overlay.root_for(list(pins.GROUPS) if name == "all" else [name])
        groups[name] = dict(measure(miner, root, answers, misses, hops), root=str(root))
    value.update(edits=edits, groups=groups, complete=True, at=now(), meta=meta())
    atomic_json(path, value, private=True)
    return value


# ----- outputs -----

def _counts(rows, field, by="origin"):
    found = collections.defaultdict(collections.Counter)
    for row in rows:
        found[row[by] or "store"][row[field]] += 1
    return {k: dict(v) for k, v in sorted(found.items())}


def summarize(answers, excluded, misses, hops, groups, check_value, miner):
    steps = collections.defaultdict(collections.Counter)
    for answer in answers:
        steps[answer["origin"]]["answers"] += 1
        steps[answer["origin"]]["order:" + answer["orderFrom"]] += 1
        for step in answer["steps"]:
            steps[answer["origin"]][step["type"]] += 1
            if replayable(step):
                steps[answer["origin"]]["replayed"] += 1
    web = [h for h in hops if h["kind"] == "web"]
    store = [h for h in hops if h["kind"] == "store"]
    with_unreached = {h["answer"] for h in hops if h["class"] == "held-unreached"}
    reasons = collections.Counter(e["reason"] for e in excluded)
    return {"pool": {"answers": len(answers), "byOrigin": dict(collections.Counter(a["origin"] for a in answers)),
                     "loopByKind": dict(collections.Counter(a["detail"]["kind"] for a in answers
                                                            if a["origin"] == "loop")),
                     "steps": {k: dict(v) for k, v in sorted(steps.items())}},
            "excluded": {"total": len(excluded), "byReason": dict(reasons)},
            "misses": {"byKind": dict(collections.Counter(m["kind"] for m in misses)),
                       "byOrigin": _counts(misses, "kind"),
                       "unresolvedByScope": dict(collections.Counter(m["scope"] for m in misses
                                                                     if m["kind"] == "unresolved-name")),
                       "lateFindsNeverReturned": sum(m["kind"] == "late-find" and m["returnedAt"] is None
                                                     for m in misses),
                       "answersWithAMiss": len({m["answer"] for m in misses if m["answer"]})},
            "hops": {"web": {"total": len(web), "byClass": dict(collections.Counter(h["class"] for h in web)),
                             "byOrigin": _counts(web, "class"),
                             "heldSince": {c: dict(collections.Counter(h["target"]["heldSince"] for h in web
                                                                       if h["class"] == c))
                                           for c in ("unused", "unsaved-detail", "reached-now", "held-unreached")}},
                     "store": {"total": len(store), "byClass": dict(collections.Counter(h["class"] for h in store)),
                               "byOrigin": _counts(store, "class")},
                     "answersWithHeldUnreached": len(with_unreached)},
            "other": dict(miner.counts),
            "dossier": {"groups": len(groups), "batches": -(-len(groups) // BATCH) if groups else 0,
                        "byGroupKind": dict(collections.Counter(g["by"] for g in groups))},
            "replayCheck": {k: check_value[k] for k in ("ok", "searches", "matched", "differing", "answers")},
            "propertyMap": miner.props.source, "base": driver.fingerprint(miner.base), "meta": meta()}


def write(out, answers, excluded, misses, hops, groups, summary):
    out = Path(out)
    atomic_bytes(out / "answers.jsonl", "".join(json.dumps(a, ensure_ascii=False, sort_keys=True) + "\n"
                                                for a in answers).encode("utf-8"), private=True)
    atomic_json(out / "excluded.json", excluded, private=True)
    atomic_json(out / "misses.json", misses, private=True)
    atomic_json(out / "hops.json", hops, private=True)
    folder = out / "dossier"
    folder.mkdir(exist_ok=True, mode=0o700)
    for old in folder.glob("batch-*.json"):
        old.unlink()
    batches = [groups[i:i + BATCH] for i in range(0, len(groups), BATCH)]
    for number, batch in enumerate(batches, 1):
        value = {"batch": number, "of": len(batches), "edits": list(pins.TYPES),
                 "linkRelations": list(pins.LINK_RELATIONS), "groups": batch,
                 "ids": "Each group lists under `misses` and `hops` the ids of its misses and hops; an edit cites "
                        "those it answers.",
                 "rule": "Co-occurrence in a trace is a reason to look, never evidence of a link; a link stands "
                         "only on what a source states (its heading, Crossref's relation metadata, the citing "
                         "passage)."}
        atomic_bytes(folder / ("batch-%02d.json" % number),
                     (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8"), private=True)
    atomic_json(out / "summary.json", summary, private=True)


def mine(out=None, *, kf=None, expected=None, release=None, live_root=None, part_a=None, heldout=None, questions=None,
         streams=None, metadata=None, property_map=None, crossref=None, cutoff=CUTOFF):
    """The check, then the pool's answers, misses, hops, summary and dossier; refused unless questions/hashes.json
    fixes H, N and L and the check passes. The first mining pins the pool (`pool.json`); later ones mine exactly it."""
    out = Path(out) if out else pins.folder("mine")
    sets = fixed_sets(questions)
    base = base_root(out, kf, expected=expected, release=release)
    check_value = check(out, base, part_a=part_a, fingerprint=expected)
    if not check_value["ok"]:
        first = check_value["differences"][:3]
        raise SystemExit("Replay does not reproduce the recorded searches (%d of %d differ%s); nothing mined. First: %s"
                         % (check_value["differing"], check_value["searches"],
                            "" if check_value["searches"] else ": nothing to check", json.dumps(first)[:2000]))
    pinned = pinned_pool(out)
    answers, excluded = pool(live_root=live_root, part_a=part_a, fingerprint=expected, heldout=heldout,
                             questions=questions, streams=streams, metadata=metadata,
                             pinned=set(pinned["answers"]) if pinned else None, cutoff=cutoff)
    if pinned is None:
        ids = sorted(a["id"] for a in answers)
        pinned = {"format": FORMATS["pool"], "cutoff": cutoff, "answers": ids, "digest": digest(ids),
                  "questionSets": sets, "at": now()}
        atomic_json(out / "pool.json", pinned, private=True)
    miner = Miner(base, property_map=property_map, crossref=crossref)
    misses, hops = [], []
    for answer in answers:
        found, hopped = miner.analyze(answer)
        misses += found
        hops += hopped
    misses += miner.unannotated()
    groups = miner.dossier(answers, misses, hops)
    summary = summarize(answers, excluded, misses, hops, groups, check_value, miner)
    summary.update(questionSets=sets, pinnedPool={"digest": pinned["digest"], "cutoff": pinned["cutoff"]})
    write(out, answers, excluded, misses, hops, groups, summary)
    return summary


def load(out=None):
    """The mined outputs: answers, misses and hops."""
    out = Path(out) if out else pins.FOLDERS["mine"]
    answers = [json.loads(line) for line in (out / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return answers, read_json(out / "misses.json"), read_json(out / "hops.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("check", "mine", "effects", "summary"))
    args = parser.parse_args(argv)
    if args.command == "check":
        out = pins.folder("mine")
        value = check(out, base_root(out))
        print(json.dumps({k: value[k] for k in ("ok", "searches", "matched", "differing", "answers", "byExperiment")},
                         indent=1))
        if not value["ok"]:
            print(json.dumps(value["differences"][:3], indent=1)[:4000])
            raise SystemExit(1)
    elif args.command == "mine":
        print(json.dumps(mine(), indent=1))
    elif args.command == "effects":
        value = run_effects()
        print(json.dumps({"edits": len(value["edits"]), "dropped": value["dropped"],
                          "groups": {g: {k: v[k] for k in ("missesFixed", "hopsReachable", "resultsLost")}
                                     for g, v in value["groups"].items()}}, indent=1))
    else:
        print((pins.FOLDERS["mine"] / "summary.json").read_text())


if __name__ == "__main__":
    main()
