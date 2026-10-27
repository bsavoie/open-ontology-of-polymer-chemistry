#!/usr/bin/env python3
"""Part B's build, from the five restarts' records only (restart-study-plan.md, Measures, "The build, from each
restart's records"; Predictions 1 and 4). No engine call and no network; every store is opened read only.

What it reads, per restart R<n> (under `.oopc/loop/harness/2026-10-restarts/R<n>/`, read only):

- `baseline.json` (the pins), `rounds.json` (the 500 tasks with round, kind, revisit, parent and near-parent flags),
  `snapshots.json` (S0–S5 as taken) and `runs.jsonl` (the harness commit of every run);
- `snapshots/S1` … `S5`: each knowledge store, whose fingerprint is recomputed exactly as `driver.fingerprint` does and
  must equal the one recorded when it was taken; S0 is the empty store. Findings by status (Reviewed, Added, Needs
  checking, Rejected), source notes, distinct sources by the store's own key (freeze-2's `knowledge.source_key`, which
  drops a URL's query string: CL-23; the count with the query string kept is given beside it, as A1 does), polymers
  with a finding (any status), findings without a polymer id, and field completeness (excerpt first);
- `workspace/.oopc/loop/questions/<task>/` (`question.json`, `result.json`): each task's final state, failure reason,
  new tokens, web calls and citations, by freeze-2's own `parity._metrics`;
- `waves/wave-<r>/checks/`: the 12 whole-answer checks of each round, their measures recomputed from the statements as
  freeze-2's `reviewer.measures` does (and compared with the stored ones) and every contradicted statement;
- `activity.jsonl`: tasks that failed for a transient reason and were asked again, and failed reviews;
- `improver/round-<r>.json` and `round-<r>-records.json`, `prompts/`, `eval/round-<r>/dev/decision.json`: each
  proposal, its lengths, the rules that decided it, the dev measures and the median paired token ratio. The records the
  improver read are compared with what this script computes; a disagreement is listed under `crossChecks`.

Review outcomes are those of each round's findings in S5, credited to the round of the task that saved them; that a
finding's status in S<r> equals its status in S5 is checked. The growth curve credits each finding, with its status in
S5, to the task that saved it, in the order tasks finished; it must meet every snapshot's counts at the round ends.

The one-line summaries of each improver diagnosis and expected effect, and the kind of change each edit makes, are the
analyst's reading of the proposal's text (`EDITS`, 2026-10-20), pinned to the candidate prompt's version: an edit whose
version differs stops the build.

Writes `analysis/restarts-build/results.json` and `results.md` (tables, then prediction 1 and the build half of
prediction 4 judged; the held-out half of prediction 4 waits for the final evaluation).

    OOPC_STUDY_ROOT=<main checkout> python -B build_results.py [--base DIR] [--out DIR]
"""
import argparse, collections, datetime as dt, hashlib, json, os, re, sqlite3, statistics, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
_ROOT = Path(os.environ.get("OOPC_STUDY_ROOT") or HERE.parents[3]).resolve()
FREEZE2 = _ROOT / ".oopc/study/freeze-2"  # tag study-freeze-2, whose code wrote every record read here
if FREEZE2.exists():
    os.environ.setdefault("OOPC_STUDY_CODE", str(FREEZE2))
sys.path.insert(0, str(HERE.parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402  (puts the code that wrote the records first on sys.path)
from oopc import knowledge, parity  # noqa: E402

BASE = common.run_dir("2026-10-restarts")
OUT = common.analysis_dir("restarts-build")
COUNT = 5
STATUS = {"supported": "Reviewed", "accepted": "Added", "unreviewed": "Needs checking", "uncertain": "Needs checking",
          "unsupported": "Rejected"}
ORDER = ["Reviewed", "Added", "Needs checking", "Rejected"]
FIELDS = (("excerpt", "excerpt"), ("locator", "locator"), ("conditions", "conditions"), ("unit", "unit"),
          ("polymerId", "subject"))
DERIVED = {"Read from a figure": "figure", "Converted or calculated": "converted",
           "Combined from more than one place": "combined"}
RULES = {"noMoreContradicted": "more contradicted", "noFewerComplete": "fewer complete",
         "noFewerSourced": "fewer sourced", "tokensWithinLimit": "tokens > 1.10", "enoughPairs": "too few pairs"}
TRANSIENT = ("quota", "rate-limited", "not-signed-in", "interrupted")
LOCAL_PATH = re.compile(r"file:|(?<![\w.])(/Users/|/home/|/private/|/var/folders/|/tmp/)|\b[A-Za-z]:\\")

# The kinds of change, from the edits' text (analyst, 2026-10-20). Each family names what the edit asks the researcher
# to do differently; an edit belongs to exactly one.
FAMILIES = {
    "claims": "scope absence and attribution claims to what was read",
    "web-stop": "stop web searching sooner",
    "store-first": "answer from saved knowledge and search the web less",
    "reopen-source": "reopen a cited finding's own source for a missing detail",
    "store-search": "fewer repeated knowledge searches",
    "non-journal": "say when a patent or data sheet answers 'a published study'",
    "material-labels": "keep the source's own material and property labels",
    "excerpts": "save excerpts that cover the answer's claims",
}
# (restart, round): candidate version, family, what the edit says, the improver's diagnosis and expected effect, each
# summarised in one line by the analyst from the proposal's text (the improver's own counts, not re-verified here).
EDITS = {
    (1, 1): ("bb9111b399d9", "claims", "cite a source only for what the passage read states; abstract-only sources only for the abstract",
             "Task 93 cited a paper for a grade ordering it does not state; abstract-only citations drew uncertain checks (86, 77).",
             "Fewer contradicted statements and access-uncertain verdicts; completeness and cost unchanged."),
    (1, 2): ("e4dadf6a9a3c", "claims", "a detail not seen is 'not stated in the part read'; never a reason why it is missing",
             "Both failed checks (190, 158) said a detail was absent from parts of a source not read, or guessed why.",
             "Fewer contradicted statements; completeness and cost unchanged."),
    (1, 3): ("10eaaeded8d1", "web-stop", "failed opens count toward the budget; once it is spent, start no new source",
             "No accuracy problem; 10 of 100 tasks used 13-20 web calls chasing sources that would not open.",
             "Tail tasks fall to about 8-10 web calls; median tokens 3-8% lower."),
    (1, 4): ("0e8763ef3903", "non-journal", "name a patent or data sheet as such when it answers 'a published study'",
             "Task 355 failed completeness: it answered 'a published study' from a data sheet without saying it is no study.",
             "More complete answers; contradicted statements and cost unchanged."),
    (1, 5): ("562bbf0fd10b", "claims", "differences in the sources' units, no unrequested percentages, bounds kept when rounding",
             "The round's only unsupported statement (485) was an unrequested relative change rounded past its bound.",
             "About one fewer contradicted statement in 30; tokens slightly lower."),
    (2, 1): ("029811c3d3fc", "claims", "read the methods section or leave a condition empty; never 'unspecified' for an unread section",
             "Two rejected findings and one contradiction wrote 'method unspecified' for methods an unread section states.",
             "Fewer contradicted statements and rejected findings; tokens up under 3%."),
    (2, 2): ("d6a4969179ef", "store-first", "one read of a cited source; if it fails, a saved excerpt still counts as evidence",
             "Task 121 called a value in a saved finding's excerpt unconfirmed after its source would not open.",
             "Fewer contradicted statements; slightly fewer web calls."),
    (2, 3): ("3241b6278545", "store-first", "no retry of unopenable sources; at most one web search when findings give the values",
             "9 of 20 revisits searched the web although saved findings covered them; 3 cost more than their parents.",
             "Revisits 20-40% cheaper; completeness unchanged."),
    (2, 4): ("245951bcd301", "reopen-source", "read a finding's source methods once for a missing standard or condition",
             "Answers from saved findings never reopened the source, so stated conditions were reported missing (358).",
             "0-2 more complete answers in 30; tokens up 0-5%."),
    (2, 5): ("cc6886b6cf9d", "excerpts", "up to eight excerpts, chosen to show every value and condition the answer uses",
             "6 of 8 unsupported check statements were uncertain because the saved excerpts left out their passages.",
             "1-2 of 12 checks move from uncertain to pass; tokens up 1-2%."),
    (3, 1): ("4ac3c040866d", "store-first", "answer from saved findings; at most two searches for missing details, none if already searched",
             "3 of 20 revisits (93, 97, 47) searched the web again although saved findings covered them.",
             "Revisits fall to 15-25k tokens and 0-2 web calls; tokens 5-10% lower."),
    (3, 2): ("a1930def585b", "store-search", "search properties together; one retry, then stop searching the store",
             "7 of 8 sampled answers repeated knowledge searches that returned the same results or none.",
             "Median tokens 3-6% lower; web calls unchanged."),
    (3, 3): ("eb0a42b16c4c", "web-stop", "a source that would not open counts; no screenshots; stop when searches are spent",
             "7 of 9 sampled first asks chased sources that would not open; 8 of 80 used 12-19 web calls.",
             "Median web calls down about 1; tokens 8-15% lower."),
    (3, 4): ("613d692785a7", "web-stop", "if only an abstract opens, look for no more copies and report only the abstract",
             "Abstract-only or blocked key papers drove the high-call tail (321, 400) and one uncertain check.",
             "Median web calls down 0.5-1; tokens 5-10% lower."),
    (3, 5): ("e040fb32fa64", "material-labels", "keep a trade name, grade or foreign property term as the source gives it",
             "All 4 rejected findings carried a material or property label the source does not state (441, 453, 493).",
             "Rejected findings fall to 0-1; cost unchanged."),
    (4, 1): ("09289901d1f0", "web-stop", "failed opens count toward a detail's two searches; stop after two",
             "8 of 12 sampled answers kept trying paywalled or failing leads for one detail, then reported it not found.",
             "Median web calls down 1-2; tokens 5-10% lower."),
    (4, 2): ("713373f14069", "store-first", "when findings give the main values, at most one search or read per missing detail",
             "5 of 19 revisits searched the web for secondary details after saved findings gave the main values.",
             "Those revisits fall to 1-3 web calls; their tokens 10-20% lower."),
    (4, 3): ("ac1e4b94bcff", "non-journal", "say in the answer that a patent or data sheet is not a journal study",
             "The only failed check (296) answered 'a published study' from a data sheet, saying so only in limitations.",
             "About 1-2 more complete answers in 30; cost unchanged."),
    (4, 4): ("39ac38488722", "claims", "no statements in the answer about what a page or copy showed; those go in limitations",
             "All 3 uncertain checks held statements about the session or copies of a source, which no source confirms.",
             "1-2 more passes in 30; contradicted and completeness unchanged."),
    (4, 5): ("b554120161c8", "store-search", "one knowledge retry per material with all its properties, then the web",
             "10 first asks made 5-12 knowledge searches; six cited at most one finding and answered from the web.",
             "Tokens 10-20% lower on those tasks, 3-5% at the median."),
    (5, 1): ("af906e253c77", "material-labels", "take every name and class from the source; a trade name with its supplier",
             "All 5 rejected findings added a polymer name or class the source does not state (26, 56).",
             "Fewer rejected findings; tokens up under 1%."),
    (5, 2): ("fbadb4692a82", "claims", "check a source's general methods before calling a condition absent; no unit from context",
             "Both failed checks called a condition absent (101) or added a unit (104) the source does not attach.",
             "The two failures become passes; tokens up 1-3%."),
    (5, 3): ("fc1418bbb0a5", "store-first", "cite a note's verbatim excerpt without reopening; do not re-chase noted failures",
             "7 of 22 revisits used 35 web calls, reopening sources saved only as notes.",
             "Revisit token ratio from 0.38 toward 0.30; median tokens 3-8% lower."),
    (5, 4): ("87b34d477eb4", "web-stop", "stop after three web searches that find no usable source",
             "9 answers spent 6-16 web calls that found nothing usable and ended 'not found'.",
             "Median web calls down about 0.5; tokens 3-6% lower."),
    (5, 5): ("5ac96a14b9b7", "reopen-source", "open a cited finding's source at its locator before searching elsewhere",
             "A failed check (412) and four other answers left out details the cited finding's own source gives.",
             "Fewer contradicted statements, about one more complete in 30; tokens within 3%."),
}


# ----------------------------------------------------------------------------------------------- small helpers

def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe(path):
    return jread(path) if Path(path).exists() else None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def share(part, whole, digits=4):
    return round(part / whole, digits) if whole else None


def version(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def trim(text, limit=300):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def database(root):
    return Path(root) / ".oopc/loop/knowledge.sqlite"


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    return db


def fingerprint(path):
    """`driver.fingerprint` of the store at `path` (a knowledge.sqlite, or None for the empty store S0)."""
    rows = [[], []]
    if path is not None and Path(path).exists():
        db = connect(path)
        rows = [db.execute("SELECT * FROM findings ORDER BY id").fetchall(),
                db.execute("SELECT * FROM notes ORDER BY id").fetchall()]
        db.close()
    return {"findings": len(rows[0]), "notes": len(rows[1]),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]}


def query_key(doi, url, key=None):
    """The store's source key with a URL's query string kept (CL-23), as A1's `dataset_build.query_key`."""
    found = (key or knowledge.source_key)(doi, url)
    if not found.startswith("url:"):
        return found
    return "url:" + re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).split("#")[0].rstrip("/")


def flag_kind(flag):
    """Why a finding waited for review: a derivation (figure, converted, combined), a fact found unsupported before,
    or an ambiguous polymer name."""
    if not flag:
        return None
    if flag in DERIVED:
        return DERIVED[flag]
    if flag.startswith("A matching finding was judged unsupported"):
        return "matches a rejected finding"
    if flag.startswith("Ambiguous polymer name"):
        return "ambiguous polymer name"
    return "other"


def reason_kind(reason):
    """A rejected finding's reason by keyword (analyst, 2026-10-20; every reason is listed in full beside it): the
    title as saved does not match the source's, a converted or calculated value the source does not state, a material
    or property label the source does not give, else a method, condition or scope the source does not support."""
    text = (reason or "").lower()
    if "supplied title" in text:
        return "title differs"
    if re.search(r"calculat|convert|conversion", text):
        return "converted value not stated"
    if re.search(r"identif|identity|polymer chemistry|claimed polymer name", text):
        return "material or property label"
    return "method, condition or scope"


def check_measures(check):
    """freeze-2's `reviewer.measures` on a stored check; None for a check without a verdict."""
    if not isinstance(check, dict) or not check.get("verdict"):
        return None
    statements = [s for s in check.get("statements") or [] if isinstance(s, dict)]
    completeness = next((s.get("verdict") for s in statements if s.get("kind") == "completeness"), None)
    return {"contradicted": sum(s.get("verdict") == "unsupported" and s.get("category") != "source-access"
                                for s in statements),
            "complete": completeness == "supported" if completeness else None,
            "resultGiven": check.get("resultGiven") if isinstance(check.get("resultGiven"), bool) else None,
            "pass": check.get("verdict") == "pass",
            "accessUncertain": sum(s.get("verdict") != "supported" and s.get("category") == "source-access"
                                   for s in statements),
            "statements": len(statements)}


def metrics(result):
    """New tokens, web calls, knowledge lookups and seconds by freeze-2's `parity._metrics`, and citations of saved
    findings, as test 2's `recursive.records` counts them."""
    m = parity._metrics(result)
    cited = [c for c in (result.get("answer") or {}).get("citations") or [] if isinstance(c, str)]
    return {"newTokens": m["newTokens"], "webCalls": m["webCalls"], "knowledgeLookups": m["knowledgeLookups"],
            "seconds": m["seconds"], "citations": len(cited), "findingCitations": sum(c.startswith("finding:") for c in cited)}


# ----------------------------------------------------------------------------------------------- stores

def load_store(path):
    """Findings, notes and reviews of the store at `path` (None or missing: empty)."""
    if path is None or not Path(path).exists():
        return [], [], []
    db = connect(path)
    db.row_factory = sqlite3.Row
    findings = [dict(r) for r in db.execute("SELECT id, question_id, status, subject, source_doi, source_url, excerpt, "
                                            "locator, conditions, unit, review_reason, detail FROM findings ORDER BY id")]
    for f in findings:
        f["detail"] = json.loads(f["detail"] or "{}")
    notes = [dict(r) for r in db.execute("SELECT id, question_id, doi, url FROM notes ORDER BY id")]
    reviews = [dict(r) for r in db.execute("SELECT question_id, status, reason FROM reviews ORDER BY finished_at")]
    db.close()
    return findings, notes, reviews


def store_stats(findings, notes, key=None):
    """One store's build measures."""
    key = key or knowledge.source_key
    statuses = collections.Counter(STATUS[f["status"]] for f in findings)
    with_findings = {key(f["source_doi"], f["source_url"]) for f in findings} - {""}
    every = with_findings | ({key(n["doi"], n["url"]) for n in notes} - {""})
    q_with = {query_key(f["source_doi"], f["source_url"], key) for f in findings} - {""}
    q_every = q_with | ({query_key(n["doi"], n["url"], key) for n in notes} - {""})
    polymers = {f["subject"] for f in findings if f["subject"]}
    n = len(findings)
    fields = {name: share(sum(bool((f[col] or "").strip()) for f in findings), n) for name, col in FIELDS}
    return {"findings": n, "byStatus": {s: statuses.get(s, 0) for s in ORDER}, "notes": len(notes),
            "sources": len(every), "sourcesWithFindings": len(with_findings),
            "sourcesKeepingQuery": len(q_every), "sourcesWithFindingsKeepingQuery": len(q_with),
            "polymers": len(polymers), "withoutPolymerId": n - sum(bool(f["subject"]) for f in findings),
            "withoutPolymerIdShare": share(n - sum(bool(f["subject"]) for f in findings), n), "fields": fields,
            "polymerIds": sorted(polymers)}


def review_outcomes(findings):
    """Spot checks of sampled Added findings and the outcomes of findings flagged at save, by the status they ended
    with; every Rejected and Needs-checking finding with its reason."""
    spot = collections.Counter(f["detail"]["spotCheck"] for f in findings if "spotCheck" in f["detail"])
    flagged = collections.defaultdict(collections.Counter)
    for f in findings:
        kind = flag_kind(f["detail"].get("reviewFlag"))
        if kind:
            flagged[kind][STATUS[f["status"]]] += 1

    def route(f):
        return ("spot check" if "spotCheck" in f["detail"] else
                ("flagged: " + flag_kind(f["detail"]["reviewFlag"])) if f["detail"].get("reviewFlag") else "other")
    rejected = [{"finding": f["id"], "questionId": f["question_id"], "route": route(f), "kind": reason_kind(f["review_reason"]),
                 "reason": trim(f["review_reason"])} for f in findings if f["status"] == "unsupported"]
    uncertain = collections.Counter(route(f) for f in findings if STATUS[f["status"]] == "Needs checking")
    return {"spotChecks": {k: spot.get(k, 0) for k in ("supported", "uncertain", "unsupported", "not-assessed",
                                                      "failed", "pending")},
            "spotChecked": sum(spot.values()),
            "flagged": {k: dict(v) for k, v in sorted(flagged.items())}, "flaggedTotal": sum(sum(v.values()) for v in flagged.values()),
            "rejected": rejected, "needsChecking": dict(uncertain)}


# ----------------------------------------------------------------------------------------------- one restart

def git_revision(cwd):
    try:
        head = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "studies"], cwd=cwd, capture_output=True,
                               text=True, check=True).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def activity(base):
    """Tasks that ended failed (before being asked again or for good) and reviews that failed, from activity.jsonl."""
    tasks, reviews = [], []
    path = Path(base) / "activity.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        event = json.loads(line)
        if event.get("event") == "task-end" and event.get("status") == "failed":
            tasks.append({"task": event["task"], "reason": (event.get("error") or {}).get("reason"), "at": event["at"]})
        elif event.get("event") == "review-failed":
            reviews.append({"task": event["task"], "reason": event.get("reason"), "at": event["at"]})
    return tasks, reviews


def build_restart(n, base, mismatches):
    """Everything this analysis reports about restart n, from its folder `base`."""
    base = Path(base)
    name = "R%d" % n
    baseline = jread(base / "baseline.json")
    tasks = jread(base / "rounds.json")
    rounds = baseline["rounds"]
    by_id = {t["taskId"]: t for t in tasks}
    by_number = {t["number"]: t for t in tasks}
    qdir = base / "workspace/.oopc/loop/questions"
    states = {t["taskId"]: maybe(qdir / t["taskId"] / "question.json") or {} for t in tasks}
    done = {tid for tid, s in states.items() if s.get("status") == "completed"}
    m = {tid: metrics(jread(qdir / tid / "result.json")) for tid in done}
    recorded = jread(base / "snapshots.json")

    def note(what, expected, got):
        if expected != got:
            mismatches.append({"restart": name, "what": what, "expected": expected, "got": got})

    # snapshots S0..S<rounds>
    stores, snapshots = {}, {}
    for k in range(rounds + 1):
        path = database(base / "snapshots" / ("S%d" % k)) if k else None
        found = fingerprint(path)
        note("S%d fingerprint" % k, recorded.get("S%d" % k), found)
        findings, notes, reviews = load_store(path)
        stores[k] = (findings, notes, reviews)
        answered = sum(1 for t in tasks if t["round"] <= k and t["taskId"] in done)
        snapshots["S%d" % k] = dict(store_stats(findings, notes), tasksAnswered=answered, fingerprint=found,
                                    asTaken=recorded.get("S%d" % k) == found)
    note("workspace equals S%d" % rounds, fingerprint(path), fingerprint(database(base / "workspace")))
    final, final_notes, final_reviews = stores[rounds]
    status_now = {f["id"]: f["status"] for f in final}
    for k in range(1, rounds + 1):
        changed = sum(status_now.get(f["id"]) != f["status"] for f in stores[k][0])
        note("findings whose status changed between S%d and S%d" % (k, rounds), 0, changed)
    orphans = sum(f["question_id"] not in done for f in final)
    note("findings not saved by a completed task", 0, orphans)

    failed_events, review_failures = activity(base)
    rows = []
    for r in range(1, rounds + 1):
        rt = [t for t in tasks if t["round"] == r]
        ids = {t["taskId"] for t in rt}
        completed = [t for t in rt if t["taskId"] in done]
        failed = [{"task": t["number"], "reason": (states[t["taskId"]].get("error") or {}).get("reason"),
                   "attempts": len(states[t["taskId"]].get("attempts") or [])}
                  for t in rt if states[t["taskId"]].get("status") == "failed"]
        retried = collections.Counter(e["reason"] for e in failed_events
                                      if by_number[e["task"]]["round"] == r
                                      and e["task"] not in {f["task"] for f in failed})
        first = [t for t in completed if not t["revisit"]]
        revisits = []
        for t in completed:
            if not t["revisit"]:
                continue
            mine, parent = m[t["taskId"]], m.get(t["parent"]) or {}
            revisits.append({"task": t["number"], "kind": t["revisit"], "parentRound": by_id[t["parent"]]["round"],
                             "newTokens": mine["newTokens"], "webCalls": mine["webCalls"],
                             "parentTokens": parent.get("newTokens"), "parentWebCalls": parent.get("webCalls"),
                             "tokenRatio": round(mine["newTokens"] / parent["newTokens"], 4)
                             if mine["newTokens"] and parent.get("newTokens") else None,
                             "webRatio": round(mine["webCalls"] / parent["webCalls"], 4)
                             if parent.get("webCalls") else None})
        kinds = {}
        for kind in ("exact", "paraphrase", "sibling"):
            these = [v for v in revisits if v["kind"] == kind]
            kinds[kind] = {"n": len(these), "medianTokenRatio": median(v["tokenRatio"] for v in these),
                           "withoutWeb": sum(v["webCalls"] == 0 for v in these)}
        checks = []
        for t in [t for t in rt if t["checkSample"]]:
            c = maybe(base / "waves" / ("wave-%d" % r) / "checks" / ("check-%04d.json" % t["number"]))
            measured = check_measures(c)
            if c and measured and isinstance(c.get("measures"), dict):
                for k2 in ("contradicted", "complete", "resultGiven", "pass", "accessUncertain"):
                    note("check %d %s" % (t["number"], k2), c["measures"].get(k2), measured[k2])
            checks.append({"task": t["number"], "kind": t["kind"], "revisit": t["revisit"],
                           "verdict": (c or {}).get("verdict"), "error": ((c or {}).get("error") or {}).get("reason"),
                           "measures": measured,
                           "contradictedStatements": [
                               {k2: trim(s.get(k2), 400 if k2 == "statement" else 300)
                                for k2 in ("statement", "kind", "category", "reason")}
                               for s in (c or {}).get("statements") or []
                               if s.get("verdict") == "unsupported" and s.get("category") != "source-access"]})
        verdicts = collections.Counter(c["verdict"] for c in checks)
        mine = [f for f in final if f["question_id"] in ids]
        outcomes = review_outcomes(mine)
        for item in outcomes["rejected"]:
            item["task"] = by_id[item.pop("questionId")]["number"]
        reviews = collections.Counter(v["status"] for v in final_reviews if v["question_id"] in ids)
        before, after = snapshots["S%d" % (r - 1)], snapshots["S%d" % r]
        row = {
            "round": r,
            "promptVersion": version((base / "prompts" / ("P%d.txt" % (r - 1))).read_text()),
            "tasks": {"planned": len(rt), "completed": len(completed), "failed": failed,
                      "askedAgainAfterTransientFailure": dict(retried),
                      "nearParents": sum(bool(t.get("nearParentOf")) for t in completed),
                      "firstAsks": len(first), "revisits": len(revisits)},
            "firstAsks": {"medianTokens": median(m[t["taskId"]]["newTokens"] for t in first if m[t["taskId"]]["newTokens"]),
                          "medianWebCalls": median(m[t["taskId"]]["webCalls"] for t in first)},
            "answersCitingFindings": sum(m[t["taskId"]]["findingCitations"] > 0 for t in completed),
            "answersWithoutWeb": sum(m[t["taskId"]]["webCalls"] == 0 for t in completed),
            "revisitCost": {"n": len(revisits),
                            "medianTokenRatio": median(v["tokenRatio"] for v in revisits),
                            "cheaperThanParent": sum(bool(v["tokenRatio"] and v["tokenRatio"] < 1) for v in revisits),
                            "medianWebRatio": median(v["webRatio"] for v in revisits),
                            "withoutWeb": sum(v["webCalls"] == 0 for v in revisits),
                            "medianTokens": median(v["newTokens"] for v in revisits),
                            "byKind": kinds, "rows": revisits},
            "checks": {"n": len(checks), "verdicts": {v: verdicts.get(v, 0) for v in ("pass", "uncertain", "fail")},
                       "contradicted": sum((c["measures"] or {}).get("contradicted", 0) for c in checks),
                       "answersContradicted": sum(bool((c["measures"] or {}).get("contradicted")) for c in checks),
                       "complete": sum((c["measures"] or {}).get("complete") is True for c in checks),
                       "resultGiven": sum((c["measures"] or {}).get("resultGiven") is True for c in checks),
                       "accessUncertain": sum((c["measures"] or {}).get("accessUncertain", 0) for c in checks),
                       "rows": checks},
            "deposits": {"findingsSaved": len(mine), "byStatus": {s: sum(STATUS[f["status"]] == s for f in mine)
                                                                   for s in ORDER}},
            "reviews": dict(outcomes, reviewSessions={"completed": reviews.get("completed", 0),
                                                      "failed": reviews.get("failed", 0)},
                            failedReviewEvents=collections.Counter(e["reason"] for e in review_failures
                                                                   if by_number[e["task"]]["round"] == r)),
            "added": {k: after[k] - before[k] for k in ("findings", "notes", "sources", "sourcesKeepingQuery", "polymers")},
        }
        row["improver"], row["dev"] = edit_record(n, base, r, mismatches)
        # what the improver read about this round, against what is computed here
        records = maybe(base / "improver" / ("round-%d-records.json" % r))
        if records:
            s = records["summary"]
            ours = {"completed": len(completed), "answersCitingFindings": row["answersCitingFindings"],
                    "answersWithoutWeb": row["answersWithoutWeb"],
                    "medianTokensFirstAsks": round(row["firstAsks"]["medianTokens"], 3),
                    "medianWebCallsFirstAsks": round(row["firstAsks"]["medianWebCalls"], 3),
                    "revisitTokenRatio": round(median(v["tokenRatio"] for v in revisits if v["tokenRatio"]), 3),
                    "revisitWebRatio": round(median(v["webRatio"] for v in revisits if v["webRatio"] is not None), 3)
                    if any(v["webRatio"] is not None for v in revisits) else None,
                    "findingsSaved": len(mine), "flagged": outcomes["flaggedTotal"],
                    "rejectedFindings": len(outcomes["rejected"]), "checks": row["checks"]["verdicts"]}
            for k2, v in ours.items():
                note("round %d records %s" % (r, k2), s.get(k2), v)
        rows.append(row)

    # the growth curve: findings (status in S<rounds>), notes, sources and polymers by tasks answered, in finishing order
    order = sorted(done, key=lambda tid: (by_id[tid]["round"], states[tid].get("finishedAt") or ""))
    f_by_q, n_by_q = collections.defaultdict(list), collections.defaultdict(list)
    for f in final:
        f_by_q[f["question_id"]].append(f)
    for x in final_notes:
        n_by_q[x["question_id"]].append(x)
    curve = {"tasks": [0], "notes": [0], "sources": [0], "polymers": [0], **{s: [0] for s in ORDER}}
    counts, keys, polymers, notes_count = collections.Counter(), set(), set(), 0
    for i, tid in enumerate(order, 1):
        for f in f_by_q[tid]:
            counts[STATUS[f["status"]]] += 1
            keys.add(knowledge.source_key(f["source_doi"], f["source_url"]))
            if f["subject"]:
                polymers.add(f["subject"])
        for x in n_by_q[tid]:
            keys.add(knowledge.source_key(x["doi"], x["url"]))
        notes_count += len(n_by_q[tid])
        curve["tasks"].append(i)
        curve["notes"].append(notes_count)
        curve["sources"].append(len(keys - {""}))
        curve["polymers"].append(len(polymers))
        for s in ORDER:
            curve[s].append(counts[s])
    for k in range(rounds + 1):  # the curve meets every snapshot at its round end
        snap = snapshots["S%d" % k]
        x = snap["tasksAnswered"]
        note("curve at S%d" % k, {"findings": snap["findings"], "sources": snap["sources"], "polymers": snap["polymers"],
                                   "notes": snap["notes"]},
             {"findings": sum(curve[s][x] for s in ORDER), "sources": curve["sources"][x],
              "polymers": curve["polymers"][x], "notes": curve["notes"][x]})
    prompts = {"P%d" % k: version((base / "prompts" / ("P%d.txt" % k)).read_text()) for k in range(rounds + 1)}
    runs = [json.loads(line) for line in (base / "runs.jsonl").read_text().splitlines()] if (base / "runs.jsonl").exists() else []
    pins = {k: baseline[k] for k in ("tag", "revision", "promptVersion", "model", "improverModel", "release", "seed",
                                     "rounds", "editLimits", "minPairs", "tokenLimit", "harness")}
    pins.update(snapshots={k: v["fingerprint"] for k, v in snapshots.items()}, prompts=prompts,
                harnessCommitsRun=sorted({r["harness"][:12] for r in runs}), runs=len(runs),
                codeCommitsRun=sorted({r["code"][:12] for r in runs}),
                allRunsClean=all(r.get("codeClean") and r.get("harnessClean") for r in runs),
                settings=baseline["loop"]["settings"])
    for s in snapshots.values():
        s.pop("polymerIds")
    state = maybe(base / "state.json") or {}
    return {"restart": n, "pins": pins, "status": state.get("status"), "startedAt": state.get("startedAt"),
            "finishedAt": state.get("finishedAt"), "snapshots": snapshots, "rounds": rows, "curve": curve,
            "tasks": {"planned": len(tasks), "completed": len(done),
                      "failed": [f for row in rows for f in row["tasks"]["failed"]]},
            "reviewFailureEvents": collections.Counter(e["reason"] for e in review_failures),
            "transientTaskFailures": collections.Counter(e["reason"] for e in failed_events
                                                         if e["reason"] in TRANSIENT)}


def edit_record(n, base, r, mismatches):
    """Round r's improver proposal and dev decision."""
    imp = jread(base / "improver" / ("round-%d.json" % r))
    dec = jread(base / "eval" / ("round-%d" % r) / "dev" / "decision.json")
    current = (base / "prompts" / ("P%d.txt" % (r - 1))).read_text()
    adopted_text = (base / "prompts" / ("P%d.txt" % r)).read_text()
    proposal = imp.get("proposal") or {}
    candidate_path = base / "prompts" / ("P%d-candidate.txt" % r)
    candidate = candidate_path.read_text() if candidate_path.exists() else None
    known = EDITS.get((n, r))
    if proposal and (not known or known[0] != imp.get("candidateVersion")):
        raise SystemExit("R%d round %d: the edit's summary is for %s, the record's candidate is %s; read the new "
                         "proposal and update EDITS." % (n, r, known and known[0], imp.get("candidateVersion")))
    checks = {"candidate version": (imp.get("candidateVersion"), candidate and version(candidate)),
              "adopted prompt": (dec.get("adoptedVersion"), version(adopted_text)),
              "current prompt": (dec.get("currentVersion"), version(current)),
              "adopted means candidate": (dec.get("adopted"), dec.get("adoptedVersion") == imp.get("candidateVersion")),
              "candidate is current with the edit": (candidate, current.replace(proposal.get("old", ""), proposal.get("new", ""), 1)
                                                     if proposal else None)}
    for what, (expected, got) in checks.items():
        if expected != got:
            mismatches.append({"restart": "R%d" % n, "what": "round %d %s" % (r, what), "expected": trim(str(expected), 80),
                               "got": trim(str(got), 80)})
    attempts = imp.get("attempts") or []
    improver = {"candidateVersion": imp.get("candidateVersion"), "oldLength": len(proposal.get("old", "")),
                "newLength": len(proposal.get("new", "")), "promptLength": len(current),
                "candidateLength": len(candidate) if candidate else None,
                "attempts": len(attempts),
                "attemptProblems": [a.get("problem") or (a.get("error") or {}).get("reason") for a in attempts
                                    if a.get("problem") or a.get("error")],
                "evidenceTasks": len(proposal.get("evidence") or []),
                "family": known[1] if known else None, "change": known[2] if known else None,
                "diagnosis": known[3] if known else None, "expectedEffect": known[4] if known else None,
                "old": proposal.get("old"), "new": proposal.get("new")}
    failing = [k for k, v in (dec.get("rules") or {}).items() if not v]
    dev = {"adopted": bool(dec.get("adopted")), "failedRules": failing,
           "rejectedBy": [RULES[k] for k in failing], "pairs": dec.get("pairs"), "tokenRatio": dec.get("tokenRatio"),
           "measures": dec.get("measures"), "currentVersion": dec.get("currentVersion"),
           "adoptedVersion": dec.get("adoptedVersion"), "decidedAt": dec.get("at")}
    return improver, dev


# ----------------------------------------------------------------------------------------------- across restarts

PREDICTION_ONE = ("three checks, chosen by the analyst because the plan gives no thresholds (after the snapshots' "
                  "findings counts had been seen, before polymers were counted): steady growth, every round adds findings and the smallest round adds at least half as "
                  "many as the largest; polymers level off, the last round adds at most a tenth of the polymers the "
                  "store had before it; the final stores within a fifth, (largest - smallest) / smallest < 0.2 in "
                  "findings. Met if all three hold in every restart, not met if none does, partly otherwise.")


def prediction_one(restarts):
    """Prediction 1 (every restart builds a usable store), judged by PREDICTION_ONE."""
    rows, sizes = {}, {}
    for name, r in restarts.items():
        snaps = [r["snapshots"]["S%d" % k] for k in range(len(r["snapshots"]))]
        added = [b["findings"] - a["findings"] for a, b in zip(snaps, snaps[1:])]
        new_polymers = [b["polymers"] - a["polymers"] for a, b in zip(snaps, snaps[1:])]
        steady = all(a > 0 for a in added) and min(added) >= 0.5 * max(added)
        level = new_polymers[-1] <= 0.1 * snaps[-2]["polymers"]
        rows[name] = {"findingsAdded": added, "smallestOverLargest": round(min(added) / max(added), 3),
                      "steady": steady, "polymersAdded": new_polymers, "polymers": [s["polymers"] for s in snaps],
                      "lastRoundShareOfPrior": round(new_polymers[-1] / snaps[-2]["polymers"], 3), "levelsOff": level}
        sizes[name] = snaps[-1]["findings"]
    small, large = min(sizes.values()), max(sizes.values())
    spread = round((large - small) / small, 4)
    within = spread < 0.2
    parts = {"steady": all(v["steady"] for v in rows.values()), "levelsOff": all(v["levelsOff"] for v in rows.values()),
             "withinAFifth": within}
    held = sum(parts.values())
    verdict = "met" if held == 3 else "not met" if held == 0 else "partly"
    return {"verdict": verdict, "parts": parts, "restarts": rows, "finalFindings": sizes,
            "spreadOverSmallest": spread, "spreadOverLargest": round((large - small) / large, 4),
            "rule": PREDICTION_ONE}


def prediction_four_build(restarts):
    """The build half of prediction 4: each restart adopts between zero and three edits. The other half (no adopted
    edit raises contradicted statements on the held-out questions) waits for the final evaluation."""
    adopted = {name: sum(row["dev"]["adopted"] for row in r["rounds"]) for name, r in restarts.items()}
    rounds = {name: [row["round"] for row in r["rounds"] if row["dev"]["adopted"]] for name, r in restarts.items()}
    met = all(0 <= v <= 3 for v in adopted.values())
    return {"verdict": "met" if met else "not met", "adopted": adopted, "adoptedRounds": rounds,
            "total": sum(adopted.values()), "proposed": sum(len(r["rounds"]) for r in restarts.values()),
            "heldOutHalf": "waits for the final evaluation (restart-study-plan.md, Evaluation), running at the time of "
                           "this build"}


def convergence(restarts):
    """Which kinds of change were proposed and adopted, in how many restarts."""
    families = {}
    for key, label in FAMILIES.items():
        proposed = [(name, row["round"]) for name, r in restarts.items() for row in r["rounds"]
                    if row["improver"]["family"] == key]
        adopted = [(name, rd) for name, rd in proposed
                   if restarts[name]["rounds"][rd - 1]["dev"]["adopted"]]
        rejected_by = collections.Counter(rule for name, rd in proposed for rule in restarts[name]["rounds"][rd - 1]["dev"]["rejectedBy"])
        families[key] = {"label": label, "proposed": len(proposed), "adopted": len(adopted),
                         "restartsProposing": len({x for x, _ in proposed}), "restartsAdopting": len({x for x, _ in adopted}),
                         "proposedIn": ["%s r%d" % p for p in proposed], "adoptedIn": ["%s r%d" % a for a in adopted],
                         "rejectedBy": dict(rejected_by)}
    rules = collections.Counter(rule for r in restarts.values() for row in r["rounds"] for rule in row["dev"]["rejectedBy"])
    alone = collections.Counter(row["dev"]["rejectedBy"][0] for r in restarts.values() for row in r["rounds"]
                                if len(row["dev"]["rejectedBy"]) == 1)
    margins = []
    for name, r in restarts.items():
        for row in r["rounds"]:
            if row["dev"]["adopted"]:
                continue
            cur, can = row["dev"]["measures"]["current"], row["dev"]["measures"]["candidate"]
            margins.append({"edit": "%s r%d" % (name, row["round"]),
                            "complete": can["complete"] - cur["complete"], "sourced": can["sourced"] - cur["sourced"],
                            "contradicted": can["contradicted"] - cur["contradicted"],
                            "tokenRatio": (row["dev"]["tokenRatio"] or {}).get("median")})
    return {"families": families, "rejectionsByRule": dict(rules), "rejectedByOneRuleAlone": dict(alone),
            "rejectionMargins": margins,
            "repeatedAcrossRestarts": sorted(k for k, v in families.items() if v["restartsAdopting"] >= 2)}


def record_notes(restarts):
    """What in the records a reader of the results should know, computed: improver proposals that needed their retry,
    the harness commits the runs used, how often dev answers cited a saved finding, how flagged conversions and
    spot-checked findings fared in review, and how many contradicted statements are completeness statements."""
    retries = [{"edit": "%s r%d" % (name, row["round"]), "problems": row["improver"]["attemptProblems"]}
               for name, r in restarts.items() for row in r["rounds"] if row["improver"]["attempts"] > 1]
    citing = [(row["dev"]["measures"][arm]["citingFindings"], row["dev"]["measures"][arm]["answered"])
              for r in restarts.values() for row in r["rounds"] for arm in ("current", "candidate")]
    converted = collections.Counter()
    for r in restarts.values():
        for row in r["rounds"]:
            converted.update(row["reviews"]["flagged"].get("converted", {}))
    kinds = collections.Counter(f["kind"] for r in restarts.values() for row in r["rounds"] for f in row["reviews"]["rejected"])
    routes = collections.Counter(f["route"] for r in restarts.values() for row in r["rounds"] for f in row["reviews"]["rejected"])
    statements = [s for r in restarts.values() for row in r["rounds"] for c in row["checks"]["rows"]
                  for s in c["contradictedStatements"]]
    spot = collections.Counter()
    for r in restarts.values():
        for row in r["rounds"]:
            spot.update(row["reviews"]["spotChecks"])
    return {"improverRetries": retries,
            "harnessCommitsRun": sorted({c for r in restarts.values() for c in r["pins"]["harnessCommitsRun"]}),
            "harnessAtPrepare": sorted({r["pins"]["harness"][:12] for r in restarts.values()}),
            "devAnswersCitingFindings": {"min": min(c for c, _ in citing), "max": max(c for c, _ in citing),
                                         "of": sorted({n for _, n in citing})},
            "convertedFlagged": dict(converted), "rejectedByKind": dict(kinds), "rejectedByRoute": dict(routes),
            "spotChecks": dict(spot), "spotRejectedShare": share(spot["unsupported"], sum(spot.values())),
            "contradictedStatements": len(statements),
            "contradictedByKind": dict(collections.Counter(s["kind"] for s in statements))}


def build(base=None):
    base = Path(base or BASE)
    mismatches = []
    restarts = {"R%d" % n: build_restart(n, base / ("R%d" % n), mismatches) for n in range(1, COUNT + 1)}
    edits = []
    for name, r in restarts.items():
        for row in r["rounds"]:
            imp, dev = row["improver"], row["dev"]
            edits.append({"restart": name, "round": row["round"], "adopted": dev["adopted"],
                          "rejectedBy": dev["rejectedBy"], "family": imp["family"], "change": imp["change"],
                          "oldLength": imp["oldLength"], "newLength": imp["newLength"],
                          "promptLength": imp["promptLength"], "attempts": imp["attempts"],
                          "diagnosis": imp["diagnosis"], "expectedEffect": imp["expectedEffect"],
                          "tokenRatio": dev["tokenRatio"], "pairs": dev["pairs"],
                          "current": {k: dev["measures"]["current"][k] for k in ("contradicted", "complete", "sourced", "pass",
                                                                               "medianTokens", "medianWebCalls", "citingFindings")},
                          "candidate": {k: dev["measures"]["candidate"][k] for k in ("contradicted", "complete", "sourced",
                                                                                   "pass", "medianTokens", "medianWebCalls",
                                                                                   "citingFindings")},
                          "candidateVersion": imp["candidateVersion"]})
    code = Path(knowledge.__file__).resolve()
    meta = {"builder": "studies/macromolecules/recursive/build_results.py", "analysisRevision": git_revision(HERE.parent),
            "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "records": ".oopc/loop/harness/2026-10-restarts/R1..R5 (read only; final/ not read)",
            "codeImported": "freeze-2 (tag study-freeze-2)" if code.is_relative_to(FREEZE2) else "not freeze-2",
            "pins": {name: r["pins"] for name, r in restarts.items()},
            "about": "Part B's build from the restarts' records (restart-study-plan.md, Measures). Sources: distinct "
                     "documents by freeze-2's knowledge.source_key, which drops a URL's query string (CL-23); "
                     "sourcesKeepingQuery keeps it. Polymers: distinct polymer ids of findings of any status. Review "
                     "outcomes: each round's findings in the final snapshot, by the round of the task that saved them."}
    return {"meta": meta, "restarts": restarts, "edits": edits,
            "predictions": {"1": prediction_one(restarts), "4-build": prediction_four_build(restarts)},
            "convergence": convergence(restarts), "notes": record_notes(restarts),
            "crossChecks": {"mismatches": mismatches, "count": len(mismatches)}}


# ----------------------------------------------------------------------------------------------- report

def fmt(v):
    return "{:,}".format(v) if isinstance(v, int) else ("%.2f" % v if isinstance(v, float) else str(v))


def dots(values, f=fmt):
    return "·".join(f(v) for v in values)


def ratio(v):
    return "–" if v is None else "%.2f" % v


def markdown(data):
    R = data["restarts"]
    names = list(R)
    out = []
    w = out.append
    w("# Part B build: the five restarts from their records")
    w("")
    w("Built %s by `%s` at `%s`, from `.oopc/loop/harness/2026-10-restarts/R1`–`R5` only (no engine, no network; the "
      "final evaluation's folder is not read). Code that wrote the records: tag `study-freeze-2` (`%s`), prompt P0 "
      "`%s`, Codex `%s`, improver `%s`, graph release `%s`. Every snapshot's fingerprint matches the one recorded when "
      "it was taken: %s. Cross-check mismatches: %d." % (
          data["meta"]["builtAt"], data["meta"]["builder"], data["meta"]["analysisRevision"],
          R["R1"]["pins"]["revision"][:7], R["R1"]["pins"]["promptVersion"], R["R1"]["pins"]["model"],
          R["R1"]["pins"]["improverModel"], R["R1"]["pins"]["release"],
          "yes" if all(s["asTaken"] for r in R.values() for s in r["snapshots"].values()) else "NO",
          data["crossChecks"]["count"]))
    w("")
    w("## The stores, S0 to S5")
    w("")
    w("| Restart | Tasks answered | Findings S1·S2·S3·S4·S5 | Reviewed · Added · Needs checking · Rejected (S5) | Notes (S5) | "
      "Sources S1…S5 | Sources, query kept (S5) | Polymers S1…S5 | Without polymer id (S5) | Excerpt (S5) |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in names:
        s = [R[name]["snapshots"]["S%d" % k] for k in range(1, 6)]
        last = s[-1]
        w("| %s | %d | %s | %s | %s | %s | %s | %s | %s (%.1f%%) | %.1f%% |" % (
            name, last["tasksAnswered"], dots([x["findings"] for x in s]), dots([last["byStatus"][k] for k in ORDER]),
            fmt(last["notes"]), dots([x["sources"] for x in s]), fmt(last["sourcesKeepingQuery"]),
            dots([x["polymers"] for x in s]), fmt(last["withoutPolymerId"]), 100 * last["withoutPolymerIdShare"],
            100 * last["fields"]["excerpt"]))
    w("")
    w("S0 is the empty store (0 findings, 0 notes) in every restart. Sources are distinct documents by the store's own "
      "key, which drops a URL's query string (CL-23); the count with it kept is beside. Polymers: distinct polymer ids "
      "of findings of any status. Field completeness at S5 (locator, conditions, unit): %s." % "; ".join(
          "%s %s" % (name, ", ".join("%.1f%%" % (100 * R[name]["snapshots"]["S5"]["fields"][k])
                                     for k in ("locator", "conditions", "unit"))) for name in names))
    w("")
    w("## Each round's tasks")
    w("")
    w("Per round 1–5 (`a·b·c·d·e`). Citing: answers citing at least one saved finding; no web: answers with no web call; "
      "revisit ratio: median new tokens of a revisit over its parent's; checks: pass/uncertain/fail of the 12 "
      "whole-answer checks; contradicted: statements unsupported for a reason other than source access.")
    w("")
    w("| Restart | Completed | Failed | Citing findings | No web | First-ask median tokens (k) | Revisit token ratio | "
      "Revisits without web | Checks pass/unc/fail | Contradicted (answers) |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in names:
        rows = R[name]["rounds"]
        w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name, dots([x["tasks"]["completed"] for x in rows]),
            ", ".join("r%d %s (%s)" % (x["round"], len(x["tasks"]["failed"]), ", ".join(f["reason"] for f in x["tasks"]["failed"]))
                      for x in rows if x["tasks"]["failed"]) or "0",
            dots([x["answersCitingFindings"] for x in rows]), dots([x["answersWithoutWeb"] for x in rows]),
            dots([x["firstAsks"]["medianTokens"] / 1000 for x in rows], lambda v: "%.1f" % v),
            dots([x["revisitCost"]["medianTokenRatio"] for x in rows], ratio),
            dots(["%d/%d" % (x["revisitCost"]["withoutWeb"], x["revisitCost"]["n"]) for x in rows], str),
            dots(["%d/%d/%d" % tuple(x["checks"]["verdicts"][v] for v in ("pass", "uncertain", "fail")) for x in rows], str),
            dots(["%d (%d)" % (x["checks"]["contradicted"], x["checks"]["answersContradicted"]) for x in rows], str)))
    w("")
    pooled = collections.defaultdict(list)
    for name in names:
        for x in R[name]["rounds"]:
            for v in x["revisitCost"]["rows"]:
                pooled[v["kind"]].append(v)
    w("Revisits pooled over restarts and rounds: %s." % "; ".join(
        "%s %d, median token ratio %.2f, %d without web" % (k, len(v), median(y["tokenRatio"] for y in v),
                                                             sum(y["webCalls"] == 0 for y in v))
        for k, v in sorted(pooled.items())))
    asked_again = collections.Counter()
    for name in names:
        for x in R[name]["rounds"]:
            asked_again.update(x["tasks"]["askedAgainAfterTransientFailure"])
    w("Tasks that failed for a transient reason and were asked again (then completed): %s." % (
        ", ".join("%d %s" % (v, k) for k, v in sorted(asked_again.items())) or "none"))
    w("")
    w("## Review outcomes")
    w("")
    w("Findings saved in each round, in the final snapshot, by the round of the task that saved them (totals over "
      "rounds 1–5).")
    w("")
    w("| Restart | Spot-checked (Added sampled) | Supported · uncertain · rejected · other | Flagged at save (why) | "
      "Flagged ended Reviewed · Needs checking · Rejected | Rejected findings by round | Review sessions failed |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for name in names:
        rows = R[name]["rounds"]
        spot = collections.Counter()
        flagged_why, flagged_end = collections.Counter(), collections.Counter()
        for x in rows:
            spot.update(x["reviews"]["spotChecks"])
            for why, ends in x["reviews"]["flagged"].items():
                flagged_why[why] += sum(ends.values())
                flagged_end.update(ends)
        w("| %s | %d | %d · %d · %d · %d | %d (%s) | %d · %d · %d | %s | %d |" % (
            name, sum(spot.values()), spot["supported"], spot["uncertain"], spot["unsupported"],
            spot["not-assessed"] + spot["failed"] + spot["pending"], sum(flagged_why.values()),
            ", ".join("%s %d" % kv for kv in sorted(flagged_why.items())), flagged_end["Reviewed"],
            flagged_end["Needs checking"], flagged_end["Rejected"],
            dots([len(x["reviews"]["rejected"]) for x in rows]), sum(x["reviews"]["reviewSessions"]["failed"] for x in rows)))
    w("")
    notes = data["notes"]
    w("Rejected findings by the kind of reason (keyword reading, every reason listed below): %s; by route: %s." % (
        ", ".join("%s %d" % kv for kv in sorted(notes["rejectedByKind"].items(), key=lambda kv: -kv[1])),
        ", ".join("%s %d" % kv for kv in sorted(notes["rejectedByRoute"].items(), key=lambda kv: -kv[1]))))
    w("")
    w("Rejected findings, with the reviewer's reason (task number, how it reached review, kind of reason):")
    w("")
    for name in names:
        for x in R[name]["rounds"]:
            for f in x["reviews"]["rejected"]:
                w("- %s r%d task %d (%s; %s): %s" % (name, x["round"], f["task"], f["route"], f["kind"], f["reason"]))
    w("")
    w("Contradicted statements in the whole-answer checks:")
    w("")
    for name in names:
        for x in R[name]["rounds"]:
            for c in x["checks"]["rows"]:
                for s in c["contradictedStatements"]:
                    w("- %s r%d task %d (%s, %s): \"%s\" — %s" % (name, x["round"], c["task"], c["kind"], s["kind"],
                                                                 s["statement"], s["reason"]))
    w("")
    w("## The edits")
    w("")
    w("One per restart and round. Lengths: characters of `old` → `new`. Dev: 30 questions, current → candidate, on "
      "the round's snapshot; token ratio: median paired candidate/current with its bootstrap interval. The change, "
      "diagnosis and expected effect are the analyst's one-line summaries of the improver's text.")
    w("")
    w("| Edit | Change (kind) | Diagnosis | Expected effect | Old → new | Contradicted | Complete | Sourced | "
      "Passes | Token ratio | Decision |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for e in data["edits"]:
        t = e["tokenRatio"] or {}
        w("| %s r%d | %s (%s) | %s | %s | %d → %d%s | %d → %d | %d → %d | %d → %d | %d → %d | %s (%s–%s) | %s |" % (
            e["restart"], e["round"], e["change"], e["family"], e["diagnosis"], e["expectedEffect"], e["oldLength"],
            e["newLength"], " (2nd try)" if e["attempts"] > 1 else "",
            e["current"]["contradicted"], e["candidate"]["contradicted"], e["current"]["complete"],
            e["candidate"]["complete"], e["current"]["sourced"], e["candidate"]["sourced"], e["current"]["pass"],
            e["candidate"]["pass"], ratio(t.get("median")), ratio(t.get("low")), ratio(t.get("high")),
            "**adopted**" if e["adopted"] else "rejected: " + ", ".join(e["rejectedBy"])))
    w("")
    conv = data["convergence"]
    w("### Do the restarts converge on the same kinds of change?")
    w("")
    w("| Kind of change | Proposed (restarts) | Adopted (restarts) | Adopted in | Rejected by |")
    w("| --- | --- | --- | --- | --- |")
    for key, f in sorted(conv["families"].items(), key=lambda kv: (-kv[1]["proposed"], kv[0])):
        w("| %s | %d (%d) | %d (%d) | %s | %s |" % (f["label"], f["proposed"], f["restartsProposing"], f["adopted"],
                                                f["restartsAdopting"], ", ".join(f["adoptedIn"]) or "–",
                                                ", ".join("%s %d" % kv for kv in sorted(f["rejectedBy"].items())) or "–"))
    w("")
    margins = conv["rejectionMargins"]
    by_one = [m["edit"] for m in margins if -1 in (m["complete"], m["sourced"])]
    by_more = ["%s (%s)" % (m["edit"], ", ".join("%+d %s" % (m[k], k) for k in ("complete", "sourced") if m[k] < -1))
               for m in margins if min(m["complete"], m["sourced"]) < -1]
    w("Rejections by rule (an edit can fail several): %s; rejected by one rule alone: %s. Of the %d edits rejected "
      "for fewer complete answers or fewer sourced results, %d turned on a single answer of 30%s." % (
          ", ".join("%s %d" % kv for kv in sorted(conv["rejectionsByRule"].items())),
          ", ".join("%s %d" % kv for kv in sorted(conv["rejectedByOneRuleAlone"].items())),
          sum(1 for m in margins if min(m["complete"], m["sourced"]) < 0), len(by_one),
          "; " + ", ".join(by_more) + " by more" if by_more else ""))
    w("")
    w("### Notes on the records")
    w("")
    problems = collections.defaultdict(list)
    for x in notes["improverRetries"]:
        problems["; ".join(x["problems"])].append(x["edit"])
    w("- %d of %d proposals needed the improver's one retry, every one applied at the second try: %s." % (
        len(notes["improverRetries"]), len(data["edits"]),
        "; ".join("%s (%s)" % (p, ", ".join(e)) for p, e in problems.items())))
    w("- Runs used harness commits %s (prepared at %s); the restart, round, review and dev code is the same in all of "
      "them (`git log` of `studies/macromolecules/{recursive,driver.py,common.py,campaign}`), only the supervisor "
      "changed." % (", ".join("`%s`" % c[:7] for c in notes["harnessCommitsRun"]),
                    ", ".join("`%s`" % c[:7] for c in notes["harnessAtPrepare"])))
    w("- Dev answers citing a saved finding: %d to %d of %s per arm. Edits about reuse were judged on questions their "
      "store barely covers." % (notes["devAnswersCitingFindings"]["min"], notes["devAnswersCitingFindings"]["max"],
                                 "/".join(map(str, notes["devAnswersCitingFindings"]["of"]))))
    conv_f = notes["convertedFlagged"]
    w("- Findings flagged at save as converted or calculated: %d, of which %d ended Rejected (the reviewer's reason: "
      "the source does not state the converted value) and %d Reviewed." % (
          sum(conv_f.values()), conv_f.get("Rejected", 0), conv_f.get("Reviewed", 0)))
    w("- Spot checks of sampled Added findings: %s, of which %d rejected (%.1f%%)." % (
        fmt(sum(notes["spotChecks"].values())), notes["spotChecks"].get("unsupported", 0), 100 * notes["spotRejectedShare"]))
    w("- Contradicted statements in the whole-answer checks: %d, by kind %s; freeze-2's measure counts an unsupported "
      "completeness statement as contradicted." % (
          notes["contradictedStatements"], ", ".join("%s %d" % kv for kv in sorted(notes["contradictedByKind"].items()))))
    w("")
    p1, p4 = data["predictions"]["1"], data["predictions"]["4-build"]
    w("## Against the predictions")
    w("")
    w("**Prediction 1, %s.** Rule: %s" % (p1["verdict"], p1["rule"]))
    w("")
    for name, v in p1["restarts"].items():
        w("- %s: findings added per round %s (smallest/largest %.2f, %s); polymers S0–S5 %s, added %s, the last round "
          "%.1f%% of the store's polymers before it (%s)." % (
              name, dots(v["findingsAdded"]), v["smallestOverLargest"], "steady" if v["steady"] else "not steady",
              dots(v["polymers"]), dots(v["polymersAdded"]), 100 * v["lastRoundShareOfPrior"],
              "levels off" if v["levelsOff"] else "does not level off"))
    w("- Final stores: %s findings; (largest − smallest)/smallest = %.1f%% (%.1f%% of the largest): %s." % (
        ", ".join("%s %s" % (k, fmt(v)) for k, v in p1["finalFindings"].items()), 100 * p1["spreadOverSmallest"],
        100 * p1["spreadOverLargest"], "within a fifth" if p1["parts"]["withinAFifth"] else "not within a fifth"))
    w("")
    w("**Prediction 4, build half, %s.** Edits adopted: %s (%d of %d). The held-out half (no adopted edit raises "
      "contradicted statements on test 1's held-out questions) %s." % (
          p4["verdict"], ", ".join("%s %d (rounds %s)" % (k, v, ", ".join(map(str, p4["adoptedRounds"][k])))
                                   for k, v in p4["adopted"].items()), p4["total"], p4["proposed"], p4["heldOutHalf"]))
    w("")
    w("## Cross-checks")
    w("")
    if data["crossChecks"]["mismatches"]:
        for x in data["crossChecks"]["mismatches"]:
            w("- %s, %s: expected %s, got %s" % (x["restart"], x["what"], x["expected"], x["got"]))
    else:
        w("None: every snapshot is as taken and equals the growth curve at its round end; statuses of each round's "
          "findings are unchanged from their snapshot to S5; every measure the improver read agrees with this build; "
          "each check's stored measures equal those recomputed from its statements; each adopted prompt is its "
          "candidate, and each candidate is the current prompt with the edit applied.")
    w("")
    return "\n".join(out) + "\n"


def write(data, out=None):
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(data, ensure_ascii=False, indent=1, default=dict)
    report = markdown(json.loads(text))
    for name, body in (("results.json", text + "\n"), ("results.md", report)):
        if LOCAL_PATH.search(body):
            raise SystemExit("%s would contain a local path; nothing written" % name)
    (out / "results.json").write_text(text + "\n", encoding="utf-8")
    (out / "results.md").write_text(report, encoding="utf-8")
    return out


def main():
    parser = argparse.ArgumentParser(description="Part B's build from the five restarts' records.")
    parser.add_argument("--base", type=Path, help="the restarts' folder (default .oopc/loop/harness/2026-10-restarts)")
    parser.add_argument("--out", type=Path, help="write here instead of .oopc/study/analysis/restarts-build")
    args = parser.parse_args()
    if not Path(knowledge.__file__).resolve().is_relative_to(FREEZE2):
        raise SystemExit("The records were written by tag study-freeze-2; run with its code (%s)." % FREEZE2)
    data = build(args.base)
    out = write(data, args.out)
    p1, p4 = data["predictions"]["1"], data["predictions"]["4-build"]
    print("prediction 1:", p1["verdict"], p1["parts"], "| prediction 4 (build):", p4["verdict"], p4["adopted"])
    print("cross-check mismatches:", data["crossChecks"]["count"])
    print("wrote", out / "results.json", out / "results.md")


if __name__ == "__main__":
    main()
