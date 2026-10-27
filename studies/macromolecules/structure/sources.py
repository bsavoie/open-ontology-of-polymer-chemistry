#!/usr/bin/env python3
"""Structure strategy 1, source records, estimated offline from the records (`docs/exec-plans/active/
structure-estimates-plan.md`, estimate 1 and prediction 1). No engine is called, KF's store is read with sqlite's
`?mode=ro`, and nothing is written outside OUT (`ROOT/.oopc/study/analysis/structure/sources/`, private).

**The idea.** One record per source (its DOI or key, the copy that opened, the URLs that failed), shown in the
researcher's search result. Today a source is only text repeated on each finding and note.

**Records.**
- The derivation pool (Part C, `mine/answers.jsonl`, pinned by `mine/pool.json`): each answer's ordered steps, page
  opens with their outcomes among them. Times: a loop answer's `question.json` (`startedAt`, `finishedAt`); a Part A
  answer's driver item (`answer.at`, its end, less `metrics.seconds`). New tokens: the loop's `result.json` usage
  (`calls.new_tokens`), a driver item's `metrics.newTokens`. Web calls: web searches, opens, finds and other actions.
- The Part C screen (`screen/s1..s8/items`) and case studies (`cases/r1..r5/items`): each item's `answer.webActions` in
  order, its `metrics` (`newTokens`, `webCalls`, `seconds`) and `answer.at` (its end).
- KF's notes (`read_url`, `created_at`) and the DOIs of KF's notes and findings, read-only.

**Pages and sources.** A page's address is `knowledge.source_key("", url)` (no scheme, `www.`, query or fragment; a
doi.org URL is its DOI), keeping the query parameters that name the document (`scielo.php?pid=`, `?doi=`). A page's
source is identified by every key it carries: its address, a DOI in its URL (`mine.doi_in`), a PMC id, a ScienceDirect
PII, an arXiv id, a patent number, an MDPI article (`mdpi.com/<ISSN>/<volume>/<issue>/<n>` and the `mdpi-res.com` PDF
of the same article, for the journals whose ISSN the records pair with their DOIs), and the DOIs that any answer's
source notes and reported findings, or KF's notes and findings, give for that address (an address given three or more
DOIs is a listing, not a document, and is not mapped). Two pages are of one source when their keys meet.

**Avoidable failed opens.** A failed open is one whose outcome is `refused` (the `unrecorded` opens of older loop
records are neither failed nor opened). Each gets the first reason that holds, on evidence from before its answer
started (another answer that had ended, a KF note already created):
- `copy-opened-elsewhere`: another answer had opened the same source at another address;
- `copy-in-note`: a KF note of the source recorded a `read_url` at another address;
- `url-failed-before`: another answer's open of the same address had failed;
- `same-answer`: only the answer itself had already failed at that address, or opened the source: the session knew,
  so a record shown at search time adds nothing (reported, not credited);
- `none`.
The first three are credited to a source record. Variants: evidence only from answers to other questions (the screen
and cases ask each question on several arms and replicates, whose repeats would otherwise count); and a copy counted
only when the answer that opened it then used the source (cited it, reported a finding from it or listed it).

**Web calls saved.** Per answer and source (its failed opens grouped where their keys meet), credited failed opens are
skipped (`upper`). Net, conservatively: one open is added back for each such source the answer never opened (the
working copy, or for a warned-off address the researcher's next try, replaces the failed attempts). `gained` counts
the sources an answer never opened that the record offered a working copy of.

**Marginal cost of a web call.** Over the screen and cases, an answer's new tokens (and seconds) are regressed on its
web calls with question fixed effects (paired across arms and replicates), with a bootstrap over questions. Variants
add arm effects, and split web calls by kind (failed opens, opened pages, searches, finds and others). The share of an
origin's new tokens per answer is its net saving times the cost per web call over its mean new tokens. By kind: the
skipped failed opens at a failed open's cost, less the opens added back (a gained copy at an opened page's cost,
another try at a web call's).

**Not avoidable.** The rest, split by whether the session itself had already failed there or had the source, the
source never opened anywhere in the records (no answer at any time, no KF `read_url`), opened only later, or opened
before at the same address (an intermittent failure). Also: the hosts and URL patterns that fail, and the hosts a
failed source did open at (mirrors).

**Cheaper fixes**, on the same failed opens and counted the same way: a time-ordered known-blocked rule by host and by
URL pattern (skip an open whose host or pattern had, in answers that ended before, at least 10 opens of which 90% or
more failed), with the opened pages it would skip; and the record with the host rule.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main checkout>/.oopc/study/freeze-3 \\
        python -B studies/macromolecules/structure/sources.py [--out DIR] [--reps 2000]

Writes `results.json`, `results.md` and `failed-opens.jsonl` (each failed open with its reason and evidence).
"""
import argparse, collections, datetime as dt, json, random, re, sqlite3, sys, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
from refinement import mine, pins  # noqa: E402
from oopc import calls, knowledge  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, read_json  # noqa: E402

OUT = common.analysis_dir("structure") / "sources"
WEB = {"web-search": "search", "open": "open", "find": "other", "other": "other"}  # pool step type -> web call kind
REASONS = ("copy-opened-elsewhere", "copy-in-note", "url-failed-before", "same-answer", "none")
CREDITED = REASONS[:3]
COPIES = REASONS[:2]  # a working copy known
KINDS = ("failed", "opened", "search", "other")  # web calls by kind (an unrecorded open counts as opened)
REPS, SEED = 2000, 20261023
BLOCKED = {"min": 10, "share": 0.9}  # the known-blocked host rule
PREDICTION = {"avoidable": (0.20, 0.50), "callsSaved": (0.2, 0.6), "tokenShare": 0.05}
VARIANTS = {"main": {}, "otherQuestions": {"other_questions": True}, "usedCopies": {"used_only": True}}
GROUPS = ("all", "pool", "pool/loop", "pool/A4", "pool/A5", "screen", "screen/B0", "screen/B", "screen/Oplus", "cases",
          "cases/B0", "cases/O0", "cases/B", "cases/Oplus")

# MDPI journals by ISSN, as the records pair `mdpi.com/<ISSN>/...` pages with their DOIs and `mdpi-res.com` PDFs.
MDPI = {"2073-4360": "polymers", "1996-1944": "materials", "2076-3417": "applsci", "2077-0375": "membranes",
        "1420-3049": "molecules", "2079-4991": "nanomaterials", "1424-8220": "sensors", "1422-0067": "ijms",
        "2072-666X": "micromachines", "2079-6412": "coatings", "2304-8158": "foods", "2073-4352": "crystals",
        "2504-477X": "jcs", "2310-2861": "gels", "1999-4923": "pharmaceutics", "1996-1073": "energies",
        "2073-4409": "cells", "2504-4494": "jmmp", "2306-5354": "bioengineering", "2075-4442": "lubricants",
        "2071-1050": "sustainability"}
PMC = re.compile(r"\bPMC(\d{3,9})\b", re.I)
PII = re.compile(r"/pii/(S[0-9X()\-]{15,})", re.I)
ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
PATENT = re.compile(r"(?<![A-Za-z0-9])((?:US|EP|WO|CN|JP|KR|DE|GB|FR|CA)\d{6,}[A-Z]\d?)(?![A-Za-z0-9])", re.I)
MDPI_PAGE = re.compile(r"mdpi\.com/(\d{4}-\d{3}[\dX])/(\d+)/\d+/(\d+)", re.I)
MDPI_FILE = re.compile(r"mdpi(?:-res)?\.com/(?:d_attachment/)?([a-z]+)/\1-(\d+)-(\d+)", re.I)
SCRIPT = re.compile(r"\.(?:php|cfm|asp|aspx|jsp|do|cgi|pl)$", re.I)
NAMING = {"doi", "pid", "id", "pub_id", "file", "productid", "item_code", "article", "articleid", "docid", "accession",
          "p10_accession_num", "handle", "record", "paperid", "arnumber"}  # query parameters that name a document


# ----- pages and sources -----

def address(url):
    """A page's address: `knowledge.source_key("", url)`, with the query parameters that name the document (on a
    script page, all but tracking and language)."""
    url = (url or "").strip()
    key = knowledge.source_key("", url)
    if not key.startswith("url:"):
        return key
    parts = urllib.parse.urlsplit(url)
    script = bool(SCRIPT.search(parts.path))
    kept = sorted((k.lower(), v.lower()) for k, v in urllib.parse.parse_qsl(parts.query)
                  if k.lower() in NAMING or (script and not k.lower().startswith("utm_")
                                             and k.lower() not in ("lang", "tlng")))
    return key + ("?" + urllib.parse.urlencode(kept) if kept else "")


def host(url):
    return urllib.parse.urlsplit((url or "").strip()).netloc.lower().removeprefix("www.")


def pattern(url):
    """A URL's pattern: host and first two path segments, numbers as #, with ? for a query and [pdf] for a PDF."""
    parts = urllib.parse.urlsplit((url or "").strip())
    path = re.sub(r"\d+", "#", re.sub(r"PMC\d+", "PMC#", parts.path, flags=re.I))
    segments = [s for s in path.split("/") if s][:2]
    pdf = parts.path.lower().endswith(".pdf") or "/pdf" in parts.path.lower() or "pdf" in parts.query.lower()
    return host(url) + "/" + "/".join(segments) + ("?" if parts.query else "") + (" [pdf]" if pdf else "")


class Sources:
    """The keys a page's source is identified by, with the DOIs the records give for each address."""

    def __init__(self, pairs):
        given = collections.defaultdict(set)
        for url, doi in pairs:
            doi_key, page = knowledge.source_key(doi or "", "") if doi else "", address(url) if url else ""
            if doi_key.startswith("doi:") and page and page != doi_key:
                given[page].add(doi_key)
        self.dois = {page: dois for page, dois in given.items() if len(dois) < 3}
        self.listings = sorted(page for page, dois in given.items() if len(dois) >= 3)
        self._keys = {}

    def keys(self, url):
        url = (url or "").strip()
        if url not in self._keys:
            page, text = address(url), urllib.parse.unquote(url)
            found = {page}
            doi = mine.doi_in(url)
            if doi:
                found.add("doi:" + doi)
            found |= {"pmc:" + m.group(1) for m in PMC.finditer(text)}
            match = PII.search(text)
            if match:
                found.add("pii:" + re.sub(r"[()\-]", "", match.group(1).lower()))
            match = ARXIV.search(text)
            if match:
                found.add("arxiv:" + match.group(1))
            if "patent" in host(url):
                found |= {"patent:" + m.group(1).upper() for m in PATENT.finditer(urllib.parse.urlsplit(url).path)}
            match = MDPI_PAGE.search(text)
            if match and match.group(1).upper() in MDPI:
                found.add("mdpi:%s-%d-%d" % (MDPI[match.group(1).upper()], int(match.group(2)), int(match.group(3))))
            match = MDPI_FILE.search(text)
            if match:
                found.add("mdpi:%s-%d-%d" % (match.group(1).lower(), int(match.group(2)), int(match.group(3))))
            found |= self.dois.get(page, set())
            self._keys[url] = frozenset(k for k in found if k)
        return self._keys[url]

    def of(self, urls=(), dois=()):
        """The keys of the sources some URLs and DOIs name."""
        found = set()
        for url in urls:
            if url:
                found |= self.keys(url)
        for doi in dois:
            key = knowledge.source_key(doi, "") if doi else ""
            if key:
                found.add(key)
        return frozenset(found)


# ----- the records -----

def when(text):
    """An ISO time as an aware datetime (a bare date is its midnight UTC); None if absent."""
    if not text:
        return None
    value = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _norm(text):
    return " ".join((text or "").split()).casefold()


def _kind(action, outcome):
    if action != "open":
        return action
    return "failed" if outcome == "refused" else "opened"


def _answer(ident, group, question, *, arm, engine, start, end, tokens, seconds, calls_, sources, findings, cited):
    """One answer: its web calls in order (each open with its url and outcome, numbered among the web calls), times,
    costs, the sources it used (its source notes, reported findings and cited URLs) and the (url, doi) pairs they
    give."""
    opens = [{"n": n, "url": c["url"], "outcome": c["outcome"]} for n, c in enumerate(calls_) if c["action"] == "open"]
    kinds = collections.Counter(_kind(c["action"], c.get("outcome")) for c in calls_)
    sources = [s for s in sources or [] if isinstance(s, dict)]
    findings = [f for f in findings or [] if isinstance(f, dict)]
    pairs = [(s.get(k), s.get("doi")) for s in sources for k in ("url", "readUrl")]
    pairs += [(f.get("sourceUrl"), f.get("sourceDoi")) for f in findings]
    return {"id": ident, "group": group, "origin": group.split("/")[0], "question": _norm(question), "arm": arm,
            "engine": engine, "start": start, "end": end, "webCalls": len(calls_),
            "kinds": {k: kinds.get(k, 0) for k in KINDS}, "newTokens": tokens, "seconds": seconds, "opens": opens,
            "usedUrls": [u for u, _ in pairs if u] + [u for u in cited or [] if u],
            "usedDois": [d for _, d in pairs if d], "pairs": [(u, d) for u, d in pairs if u and d]}


def pool_answers(folder=None, root=None, harness=None):
    """The derivation pool's answers (`mine/answers.jsonl`), with times and new tokens from their records."""
    folder, root = Path(folder or pins.FOLDERS["mine"]), Path(root or common.ROOT)
    harness = Path(harness or root / ".oopc/loop/harness")
    pinned = set(read_json(folder / "pool.json")["answers"]) if (folder / "pool.json").exists() else None
    for line in (folder / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if pinned is not None and record["id"] not in pinned:
            continue
        calls_ = [{"action": WEB[s["type"]], "url": s.get("url") or "", "outcome": s.get("outcome") or "unrecorded"}
                  for s in record["steps"] if s["type"] in WEB]
        detail = record.get("detail") or {}
        if record["origin"] == "loop":
            base = root / ".oopc/loop/questions" / record["questionId"]
            question = read_json(base / "question.json") if (base / "question.json").exists() else {}
            result = read_json(base / "result.json") if (base / "result.json").exists() else {}
            start, end = when(question.get("startedAt") or record.get("startedAt")), when(question.get("finishedAt"))
            answer = result.get("answer") if isinstance(result.get("answer"), dict) else {}
            if end is None and start is not None and isinstance(result.get("agentSeconds"), (int, float)):
                end = start + dt.timedelta(seconds=result["agentSeconds"])
            tokens = calls.new_tokens(answer.get("usage") or result.get("usage"))
            seconds = (end - start).total_seconds() if start and end else None
            engine = detail.get("engine")
        else:
            item = read_json(harness / detail["folder"] / "items" / (detail["item"] + ".json"))["answer"]
            metrics = item.get("metrics") or {}
            seconds, end = metrics.get("seconds"), when(item.get("at"))
            start = end - dt.timedelta(seconds=seconds or 0) if end else None
            tokens, engine = metrics.get("newTokens"), item.get("engine")
        yield _answer(record["id"], "pool/" + record["origin"], record["question"], arm=detail.get("arm"),
                      engine=engine, start=start, end=end, tokens=tokens, seconds=seconds, calls_=calls_,
                      sources=record.get("sources"), findings=record.get("reported"),
                      cited=(record.get("cited") or {}).get("urls"))


def driver_answers(kind, folder=None, skipped=None):
    """A Part C driver run's answers (`screen` or `cases`): every item of its folders, in their order."""
    folder = Path(folder or pins.FOLDERS[kind])
    skipped = skipped if skipped is not None else []
    for run in sorted(p for p in folder.iterdir() if (p / "items").is_dir()):
        plan = read_json(run / "plan.json") if (run / "plan.json").exists() else {}
        texts = {q["id"]: q.get("question") or q["id"] for q in plan.get("questions") or []}
        for path in sorted((run / "items").glob("*.json")):
            item = read_json(path)
            answered = item.get("answer") if isinstance(item.get("answer"), dict) else {}
            content = answered.get("answer") if isinstance(answered.get("answer"), dict) else None
            if content is None or "error" in answered or not answered.get("at"):
                skipped.append("%s/%s/%s" % (kind, run.name, path.stem))
                continue
            metrics = answered.get("metrics") or {}
            end, seconds = when(answered["at"]), metrics.get("seconds")
            calls_ = [{"action": {"search": "search", "open": "open"}.get(a.get("action"), "other"),
                       "url": a.get("url") or "", "outcome": a.get("outcome") or "unrecorded"}
                      for a in answered.get("webActions") or [] if isinstance(a, dict)]
            yield _answer("%s/%s/%s" % (kind, run.name, path.stem), "%s/%s" % (kind, item.get("arm")),
                          texts.get(item.get("question"), item.get("question")), arm=item.get("arm"),
                          engine=answered.get("engine"), start=end - dt.timedelta(seconds=seconds or 0), end=end,
                          tokens=metrics.get("newTokens"), seconds=seconds, calls_=calls_,
                          sources=content.get("sources"), findings=content.get("findings"),
                          cited=mine.cited(content)["urls"])


def kf_store(path=None):
    """KF's notes (url, doi, read_url, created_at, question) and its findings' sources, read-only."""
    path = Path(path or knowledge.database(pins.KF))
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        notes = [dict(r) for r in db.execute("SELECT id, question_id, url, doi, read_url, created_at FROM notes")]
        findings = [dict(r) for r in db.execute("SELECT source_url, source_doi FROM findings")]
    finally:
        db.close()
    return notes, findings


def loop_questions(root=None):
    """Loop question texts by id (the questions KF's notes came from)."""
    folder = Path(root or common.ROOT) / ".oopc/loop/questions"
    found = {}
    for path in folder.glob("*/question.json") if folder.is_dir() else []:
        try:
            found[path.parent.name] = _norm(read_json(path).get("question"))
        except (OSError, ValueError):
            continue
    return found


def doi_pairs(answers, notes, findings):
    """(url, doi) pairs the records give: KF's notes and findings, and every answer's sources and findings."""
    for note in notes:
        yield note.get("url"), note.get("doi")
        yield note.get("read_url"), note.get("doi")
    for finding in findings:
        yield finding.get("source_url"), finding.get("source_doi")
    for a in answers:
        yield from a["pairs"]


# ----- failed opens, classed in time order -----

def classify(answers, notes, sources, *, other_questions=False, used_only=False, note_questions=None):
    """Each failed open with its reason and evidence (module docstring). `answers` need `start` and `end`."""
    note_questions = note_questions or {}
    opened, failed, by_address, copies = (collections.defaultdict(list) for _ in range(4))
    for i, a in enumerate(answers):
        used = sources.of(a["usedUrls"], a["usedDois"])
        for o in a["opens"]:
            keys, page = sources.keys(o["url"]), address(o["url"])
            if o["outcome"] == "opened":
                entry = (a["end"], page, i, bool(keys & used), a["question"])
                for key in keys:
                    opened[key].append(entry)
                by_address[page].append(entry)
            elif o["outcome"] == "refused":
                failed[page].append((a["end"], i, a["question"]))
    for note in notes:
        if note.get("read_url"):
            entry = (when(note.get("created_at")), address(note["read_url"]),
                     note_questions.get(note.get("question_id"), ""))
            for key in sources.of([note.get("url")], [note.get("doi")]):
                copies[key].append(entry)
    rows = []
    for i, a in enumerate(answers):
        start, q = a["start"], a["question"]
        for j, o in enumerate(a["opens"]):
            if o["outcome"] != "refused":
                continue
            keys, page = sources.keys(o["url"]), address(o["url"])
            ok = lambda end, other, question: (end <= start and other != i and not (other_questions and question == q))
            copy = sorted({(e[0].isoformat(), e[1]) for k in keys for e in opened[k]
                           if ok(e[0], e[2], e[4]) and e[1] != page and (e[3] or not used_only)})
            note = sorted({(e[0].isoformat(), e[1]) for k in keys for e in copies[k]
                           if e[0] and e[0] <= start and e[1] != page and not (other_questions and e[2] == q)})
            before = sorted({e[0].isoformat() for e in failed[page] if ok(*e)})
            earlier = a["opens"][:j]
            retried = [p["n"] for p in earlier if address(p["url"]) == page]
            had = [p["n"] for p in earlier if p["outcome"] == "opened" and sources.keys(p["url"]) & keys]
            flags = {"copy-opened-elsewhere": bool(copy), "copy-in-note": bool(note),
                     "url-failed-before": bool(before), "same-answer": bool(retried or had)}
            reason = next((r for r in REASONS[:-1] if flags[r]), "none")
            anywhere = any(opened[k] or copies[k] for k in keys)  # by any answer at any time, or a KF read_url
            if reason in CREDITED:
                rest = None
            elif reason == "same-answer":
                rest = "same-answer-retry" if retried else "same-answer-had-source"
            elif any(e[0] <= start and e[2] != i for e in by_address[page]):
                rest = "opened-before-at-this-address"
            elif anywhere:
                rest = "opened-only-later"
            else:
                rest = "never-opened"
            rows.append({"answer": i, "id": a["id"], "group": a["group"], "n": o["n"], "url": o["url"],
                         "address": page, "keys": sorted(keys), "reason": reason, "flags": flags, "rest": rest,
                         "evidence": {"copy": copy[:3], "note": note[:3], "failedBefore": before[:3],
                                      "sameAnswer": sorted(set(retried + had))}})
    return rows


def credited(row):
    return row["reason"] in CREDITED


def savings(answers, rows, sources, credit=credited, copies=True):
    """Per answer: the failed opens `credit` skips (`upper`), and net of one open added back for each source the
    answer never opened (`net`); `added` counts those sources, and `gained` those of them the record offered a working
    copy of (with `copies`; a rule that only skips offers none)."""
    by_answer = collections.defaultdict(list)
    for row in rows:
        by_answer[row["answer"]].append(row)
    found = {}
    for i, a in enumerate(answers):
        mine_ = by_answer.get(i, [])
        groups = []  # failed opens of one source, joined where their keys meet
        for row in mine_:
            keys = set(row["keys"])
            joined = [g for g in groups if g["keys"] & keys]
            merged = {"keys": keys.union(*(g["keys"] for g in joined)),
                      "rows": [row] + [r for g in joined for r in g["rows"]]}
            groups = [g for g in groups if g not in joined] + [merged]
        upper = net = gained = 0
        for g in groups:
            skipped = sum(bool(credit(r)) for r in g["rows"])
            if not skipped:
                continue
            got = any(o["outcome"] == "opened" and sources.keys(o["url"]) & g["keys"] for o in a["opens"])
            upper += skipped
            net += max(0, skipped - (0 if got else 1))
            gained += bool(copies and not got and any(r["reason"] in COPIES for r in g["rows"]))
        found[i] = {"failed": len(mine_), "credited": sum(bool(credit(r)) for r in mine_), "upper": upper,
                    "net": net, "added": upper - net, "gained": gained,
                    "reasons": collections.Counter(r["reason"] for r in mine_)}
    return found


# ----- the marginal cost of a web call -----

def _solve(matrix, vector):
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(vector)
    a = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-9:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                factor = a[r][col] / a[col][col]
                a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
    return [a[i][n] / a[i][i] for i in range(n)]


def within(rows, columns, outcome, cluster="question"):
    """Per cluster, the cross products of its rows' columns and outcome, each demeaned within the cluster."""
    by = collections.defaultdict(list)
    for row in rows:
        if row.get(outcome) is not None:
            by[row[cluster]].append(row)
    found = {}
    for c, members in by.items():
        x = [[float(r[col]) for col in columns] for r in members]
        y = [float(r[outcome]) for r in members]
        mx = [sum(col) / len(members) for col in zip(*x)]
        my = sum(y) / len(y)
        dx = [[v - m for v, m in zip(row, mx)] for row in x]
        dy = [v - my for v in y]
        k = len(columns)
        found[c] = ([[sum(r[p] * r[q] for r in dx) for q in range(k)] for p in range(k)],
                    [sum(r[p] * v for r, v in zip(dx, dy)) for p in range(k)])
    return found


def fit(cross, weights=None):
    """The fixed-effects coefficients from per-cluster cross products, clusters weighted (a bootstrap draw)."""
    if not cross:
        return None
    clusters = list(weights.items()) if weights is not None else [(c, 1) for c in cross]
    k = len(next(iter(cross.values()))[1])
    xx, xy = [[0.0] * k for _ in range(k)], [0.0] * k
    for c, w in clusters:
        if c not in cross:
            continue
        m, v = cross[c]
        for p in range(k):
            xy[p] += w * v[p]
            for q in range(k):
                xx[p][q] += w * m[p][q]
    return _solve(xx, xy)


def draws(clusters, reps, seed):
    rng, ids = random.Random(seed), sorted(clusters)
    return [collections.Counter(rng.choice(ids) for _ in ids) for _ in range(reps)]


def interval(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pick = lambda p: values[min(len(values) - 1, max(0, int(round(p * (len(values) - 1)))))]
    return [pick(0.025), pick(0.975)]


def regression_rows(answers):
    arms = sorted({a["arm"] for a in answers if a["arm"]} - {"B0"})
    rows = []
    for a in answers:
        row = {"question": a["question"], "newTokens": a["newTokens"], "seconds": a["seconds"], "web": a["webCalls"]}
        row.update({k: a["kinds"][k] for k in KINDS})
        row.update({"arm:" + arm: int(a["arm"] == arm) for arm in arms})
        rows.append(row)
    return rows, ["arm:" + arm for arm in arms]


def marginal_cost(answers, reps=REPS, seed=SEED):
    """New tokens and seconds per web call (question fixed effects), with variants and a bootstrap over questions."""
    rows, arm_columns = regression_rows(answers)
    models = {"web": ["web"], "web+arm": ["web"] + arm_columns, "kinds+arm": list(KINDS) + arm_columns}
    clusters = {r["question"] for r in rows}
    samples = draws(clusters, reps, seed)
    found = {"answers": len(rows), "questions": len(clusters), "reps": reps, "models": {}}
    for outcome in ("newTokens", "seconds"):
        for name, columns in models.items():
            cross = within(rows, columns, outcome)
            point = fit(cross)
            boot = [fit(cross, w) for w in samples]
            found["models"]["%s|%s" % (outcome, name)] = {
                "columns": columns,
                "coefficients": {c: round(point[p], 3) if point else None for p, c in enumerate(columns)},
                "intervals": {c: interval([b[p] for b in boot if b]) for p, c in enumerate(columns)
                              if not c.startswith("arm:")},
                "draws": {c: [b[p] if b else None for b in boot] for p, c in enumerate(columns)
                          if not c.startswith("arm:")}}
    means = collections.defaultdict(list)
    for r in rows:
        for k in ("newTokens", "seconds", "web"):
            if r[k] is not None:
                means[k].append(r[k])
    found["means"] = {k: sum(v) / len(v) for k, v in means.items()}
    return found


# ----- summaries -----

def _members(answers, group):
    if group == "all":
        return [i for i, _ in enumerate(answers)]
    return [i for i, a in enumerate(answers) if a["group"] == group or a["origin"] == group]


FIELDS = ("answers", "web", "failed", "credited", "upper", "net", "added", "gained", "reason:same-answer", "newTokens",
          "newTokensAnswers", "seconds", "secondsAnswers")
BOOTED = ("avoidable", "netPerAnswer", "upperPerAnswer", "gainedPerAnswer", "tokenShare", "secondsShare",
          "skipShareByKind", "readShareByKind", "tokenShareByKind")


def _aggregate(answers, members, saved):
    per = collections.defaultdict(collections.Counter)
    for i in members:
        a, s = answers[i], saved[i]
        c = per[a["question"]]
        c["answers"] += 1
        c["web"] += a["webCalls"]
        for k in ("failed", "credited", "upper", "net", "added", "gained"):
            c[k] += s[k]
        for reason, n in s["reasons"].items():
            c["reason:" + reason] += n
        for k in ("newTokens", "seconds"):
            if a[k] is not None:
                c[k] += a[k]
                c[k + "Answers"] += 1
    return per


def _ratios(total, cost, cost_seconds, cost_failed=None, cost_opened=None):
    """Shares and per-answer rates from summed counts. Tokens and time: the net web calls saved at a web call's
    marginal cost; and by kind, the skipped failed opens at a failed open's cost (`skip`) less the opens added back
    (`read`: a working copy at an opened page's cost, another try at a web call's)."""
    ratio = lambda a, b: total[a] / total[b] if total[b] else None
    value = {"avoidable": ratio("credited", "failed"), "upperPerAnswer": ratio("upper", "answers"),
             "netPerAnswer": ratio("net", "answers"), "addedPerAnswer": ratio("added", "answers"),
             "gainedPerAnswer": ratio("gained", "answers"), "webPerAnswer": ratio("web", "answers"),
             "failedPerAnswer": ratio("failed", "answers"),
             "avoidableWithSameAnswer": (total["credited"] + total["reason:same-answer"]) / total["failed"]
             if total["failed"] else None}
    tokens, seconds = ratio("newTokens", "newTokensAnswers"), ratio("seconds", "secondsAnswers")
    value["tokensPerAnswer"], value["secondsPerAnswer"] = tokens, seconds
    net, upper, added, gained = (value[k] for k in ("netPerAnswer", "upperPerAnswer", "addedPerAnswer",
                                                    "gainedPerAnswer"))
    value["tokenShare"] = net * cost / tokens if None not in (net, cost) and tokens else None
    value["secondsShare"] = net * cost_seconds / seconds if None not in (net, cost_seconds) and seconds else None
    if None not in (cost, cost_failed, cost_opened, upper) and tokens:
        value["skipShareByKind"] = upper * cost_failed / tokens
        value["readShareByKind"] = (gained * cost_opened + (added - gained) * cost) / tokens
        value["tokenShareByKind"] = value["skipShareByKind"] - value["readShareByKind"]
    return value


def summarize(answers, saved, cost, reps=REPS, seed=SEED, groups=GROUPS):
    """Per group: failed opens by reason, the avoidable share, web calls saved and their share of tokens and time,
    with intervals from a bootstrap over the group's questions, each draw paired with a draw of the cost's bootstrap."""
    models = cost["models"]
    point = (models["newTokens|web"]["coefficients"]["web"], models["seconds|web"]["coefficients"]["web"],
             models["newTokens|kinds+arm"]["coefficients"]["failed"],
             models["newTokens|kinds+arm"]["coefficients"]["opened"])
    paired = list(zip(models["newTokens|web"]["draws"]["web"], models["seconds|web"]["draws"]["web"],
                      models["newTokens|kinds+arm"]["draws"]["failed"],
                      models["newTokens|kinds+arm"]["draws"]["opened"]))
    found = {}
    for g, group in enumerate(GROUPS):
        members = _members(answers, group)
        if group not in groups or not members:
            continue
        per = _aggregate(answers, members, saved)
        total = sum(per.values(), collections.Counter())
        value = _ratios(total, *point)
        value.update({"answers": total["answers"], "questions": len(per), "failedOpens": total["failed"],
                      "credited": total["credited"], "webCalls": total["web"],
                      "reasons": {r: total["reason:" + r] for r in REASONS}})
        vectors = {c: [counts[f] for f in FIELDS] for c, counts in per.items()}
        boot = collections.defaultdict(list)
        for r, weights in enumerate(draws(per, reps, seed + g + 1)):
            sample = [0.0] * len(FIELDS)
            for c, w in weights.items():
                for p, v in enumerate(vectors[c]):
                    sample[p] += w * v
            ratios = _ratios(collections.Counter(dict(zip(FIELDS, sample))), *paired[r])
            for k in BOOTED:
                boot[k].append(ratios.get(k))
        value["intervals"] = {k: interval(v) for k, v in boot.items()}
        found[group] = value
    return found


def verdicts(groups):
    low, high = PREDICTION["avoidable"]
    calls_low, calls_high = PREDICTION["callsSaved"]
    found = {}
    for group in ("all", "pool", "screen", "cases", "screen/B"):
        if group not in groups:
            continue
        v = groups[group]
        place = lambda x, a, b: None if x is None else "met" if a <= x <= b else "below" if x < a else "above"
        found[group] = {"avoidable": place(v["avoidable"], low, high),
                        "callsSaved": place(v["netPerAnswer"], calls_low, calls_high),
                        "tokenShare": None if v["tokenShare"] is None else
                        ("met" if v["tokenShare"] <= PREDICTION["tokenShare"] else "above")}
    return found


def rest_of(rows):
    """The failed opens not credited, by why, with the hosts of those whose source never opened anywhere."""
    rest = [r for r in rows if r["reason"] not in CREDITED]
    return {"notCredited": len(rest), "byWhy": dict(collections.Counter(r["rest"] for r in rest)),
            "neverOpenedHosts": collections.Counter(host(r["url"]) for r in rest
                                                    if r["rest"] == "never-opened").most_common(10)}


def hosts(answers, rows, sources, top=15):
    """Failing hosts and URL patterns, and the hosts at which a failed source did open (mirrors)."""
    by_host, by_pattern = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    opened_hosts = collections.defaultdict(set)
    for a in answers:
        for o in a["opens"]:
            outcome = {"refused": "failed", "opened": "opened"}.get(o["outcome"], "unrecorded")
            by_host[host(o["url"])][outcome] += 1
            by_pattern[pattern(o["url"])][outcome] += 1
            if o["outcome"] == "opened":
                for key in sources.keys(o["url"]):
                    opened_hosts[key].add(host(o["url"]))
    table = lambda counts: [{"name": name, "failed": c["failed"], "opened": c["opened"],
                             "failRate": round(c["failed"] / (c["failed"] + c["opened"]), 3)
                             if c["failed"] + c["opened"] else None}
                            for name, c in sorted(counts.items(), key=lambda kv: (-kv[1]["failed"], kv[0]))[:top]]
    mirrors = collections.Counter()
    for r in rows:
        for elsewhere in set().union(*(opened_hosts.get(k, set()) for k in r["keys"])) - {host(r["url"])}:
            mirrors[(host(r["url"]), elsewhere)] += 1
    return {"hosts": table(by_host), "patterns": table(by_pattern),
            "mirrors": [{"failedAt": a, "openedAt": b, "failedOpens": n}
                        for (a, b), n in sorted(mirrors.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]}


def blocked(answers, by=host, rule=BLOCKED):
    """The known-blocked rule, in time order: skip an open whose host (or pattern) had, in answers that ended before
    this one started, at least `min` opens of which a `share` or more failed. Returns the failed opens it skips, as
    (answer, n), and its counts: failed opens skipped and opened pages it would have skipped too."""
    ended = sorted((a["end"], by(o["url"]), o["outcome"] == "refused") for a in answers for o in a["opens"]
                   if o["outcome"] in ("refused", "opened"))
    seen, pointer, skipped, counts, names = collections.defaultdict(lambda: [0, 0]), 0, set(), collections.Counter(), \
        collections.Counter()
    for i in sorted(range(len(answers)), key=lambda i: answers[i]["start"]):
        while pointer < len(ended) and ended[pointer][0] <= answers[i]["start"]:
            seen[ended[pointer][1]][0] += 1
            seen[ended[pointer][1]][1] += ended[pointer][2]
            pointer += 1
        for o in answers[i]["opens"]:
            total, failed = seen[by(o["url"])]
            if o["outcome"] not in ("refused", "opened") or total < rule["min"] or failed / total < rule["share"]:
                continue
            if o["outcome"] == "refused":
                skipped.add((i, o["n"]))
                names[by(o["url"])] += 1
            counts["failedSkipped" if o["outcome"] == "refused" else "openedSkipped"] += 1
    return skipped, dict(rule, **counts, top=names.most_common(10))


# ----- the run -----

def load(*, pool_folder=None, screen=None, cases=None, kf=None, root=None, harness=None):
    """Every answer (pool, screen, cases) with times, KF's notes, and the sources the records identify."""
    skipped = []
    answers = list(pool_answers(pool_folder, root, harness))
    answers += list(driver_answers("screen", screen, skipped)) + list(driver_answers("cases", cases, skipped))
    untimed = [a["id"] for a in answers if a["start"] is None or a["end"] is None]
    answers = [a for a in answers if a["start"] is not None and a["end"] is not None]
    notes, findings = kf_store(kf)
    sources = Sources(doi_pairs(answers, notes, findings))
    return answers, notes, sources, {"skipped": skipped, "untimed": untimed, "kfNotes": len(notes),
                                     "kfReadUrls": sum(bool(n.get("read_url")) for n in notes),
                                     "listings": len(sources.listings)}


def build(*, reps=REPS, root=None, **paths):
    """Everything in `results.json`, and the main variant's failed opens."""
    answers, notes, sources, info = load(root=root, **paths)
    note_questions = loop_questions(root)
    cost = marginal_cost([a for a in answers if a["origin"] in ("screen", "cases")], reps)
    variants, rows = {}, None
    for name, options in VARIANTS.items():
        classified = classify(answers, notes, sources, note_questions=note_questions, **options)
        groups = summarize(answers, savings(answers, classified, sources), cost, reps)
        variants[name] = {"groups": groups, "verdicts": verdicts(groups)}
        rows = rows or classified
    # cheaper fixes beside the record, on the main variant's failed opens: a known-blocked host or URL pattern rule,
    # and the record with the host rule
    by_host, host_counts = blocked(answers, host)
    by_pattern, pattern_counts = blocked(answers, pattern)
    rules = {"hostRule": (lambda r: (r["answer"], r["n"]) in by_host, host_counts, False),
             "patternRule": (lambda r: (r["answer"], r["n"]) in by_pattern, pattern_counts, False),
             "record+hostRule": (lambda r: credited(r) or (r["answer"], r["n"]) in by_host, None, True)}
    alternatives = {}
    for name, (credit, counts, copies) in rules.items():
        groups = summarize(answers, savings(answers, rows, sources, credit, copies), cost, reps,
                           groups=("all", "pool", "screen", "cases", "screen/B"))
        alternatives[name] = {"groups": groups, "rule": counts,
                              "notCreditedByRecord": sum(bool(credit(r)) and not credited(r) for r in rows)}
    opens = collections.Counter(o["outcome"] for a in answers for o in a["opens"])
    models = {name: {k: v for k, v in model.items() if k != "draws"} for name, model in cost["models"].items()}
    result = {"format": "oopc-structure-sources-v1",
              "inputs": dict(info, answers=len(answers), opens=dict(opens),
                             pool=_pool_digest(paths.get("pool_folder"))),
              "prediction": PREDICTION, "variants": variants, "alternatives": alternatives,
              "cost": dict(cost, models=models),
              "notCredited": {group: rest_of([r for r in rows if group == "all" or r["group"] == group
                                              or r["group"].split("/")[0] == group])
                              for group in ("all", "pool", "screen", "cases")},
              "hosts": hosts(answers, rows, sources)}
    return result, rows


def _pool_digest(folder=None):
    path = Path(folder or pins.FOLDERS["mine"]) / "pool.json"
    return read_json(path).get("digest") if path.exists() else None


def _pct(x, digits=0):
    return "–" if x is None else "%.*f%%" % (digits, 100 * x)


def _num(x, digits=2):
    return "–" if x is None else "%.*f" % (digits, x)


def _ci(pair, pct=True, digits=0):
    if not pair:
        return ""
    show = (lambda x: _pct(x, digits)) if pct else (lambda x: _num(x, digits))
    return " [%s, %s]" % (show(pair[0]), show(pair[1]))


def _row(name, group, g):
    ci = g["intervals"]
    return "| %s | %s | %s%s | %s%s | %s | %s%s | %s%s | %s%s |" % (
        name, group, _pct(g["avoidable"]), _ci(ci["avoidable"]), _num(g["netPerAnswer"]),
        _ci(ci["netPerAnswer"], False, 2), _num(g["gainedPerAnswer"]), _pct(g["tokenShare"], 1),
        _ci(ci["tokenShare"], True, 1), _pct(g.get("tokenShareByKind"), 1), _ci(ci.get("tokenShareByKind"), True, 1),
        _pct(g["secondsShare"], 1), _ci(ci["secondsShare"], True, 1))


def render(result):
    """The results as Markdown."""
    main_ = result["variants"]["main"]["groups"]
    lines = ["# Source records: what they could gain (offline estimate)", "",
             "Structure strategy 1 (`docs/exec-plans/active/structure-estimates-plan.md`). From the records only; "
             "intervals are 95% bootstrap intervals over questions.", "",
             "Inputs: %(answers)d answers, opens %(opens)s, KF notes %(kfNotes)d (%(kfReadUrls)d with a read_url)."
             % result["inputs"], ""]
    lines += ["## Prediction 1 (main variant)", "",
              "| Group | Avoidable 20–50% | Calls saved 0.2–0.6 | Tokens ≤5% |", "|---|---|---|---|"]
    for group, v in result["variants"]["main"]["verdicts"].items():
        g = main_[group]
        lines.append("| %s | %s (%s) | %s (%s) | %s (%s) |" % (
            group, v["avoidable"], _pct(g["avoidable"], 1), v["callsSaved"], _num(g["netPerAnswer"]), v["tokenShare"],
            _pct(g["tokenShare"], 1)))
    lines += ["", "## Failed opens and what a source record avoids (main)", "",
              "| Group | Answers | Web calls/answer | Failed opens | Copy elsewhere | Copy in note | URL failed before "
              "| Same answer | None | Avoidable | With same answer | Calls saved/answer (net) | Upper "
              "| Copies gained/answer |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for group, g in main_.items():
        r, ci = g["reasons"], g["intervals"]
        lines.append("| %s | %d | %.1f | %d | %d | %d | %d | %d | %d | %s%s | %s | %s%s | %s | %s |" % (
            group, g["answers"], g["webPerAnswer"], g["failedOpens"], r["copy-opened-elsewhere"], r["copy-in-note"],
            r["url-failed-before"], r["same-answer"], r["none"], _pct(g["avoidable"]), _ci(ci["avoidable"]),
            _pct(g["avoidableWithSameAnswer"]), _num(g["netPerAnswer"]), _ci(ci["netPerAnswer"], False, 2),
            _num(g["upperPerAnswer"]), _num(g["gainedPerAnswer"])))
    header = ["| Variant | Group | Avoidable | Calls saved/answer (net) | Copies gained/answer "
              "| Tokens (web-call cost) | Tokens (by kind) | Time |", "|---|---|---|---|---|---|---|---|"]
    lines += ["", "## Tokens and time saved, and variants", ""] + header
    for name, variant in result["variants"].items():
        lines += [_row(name, group, variant["groups"][group]) for group in GROUPS if group in variant["groups"]
                  and (name == "main" or group in ("all", "pool", "screen", "cases", "screen/B"))]
    lines += ["", "## Cheaper fixes beside the record (same failed opens)", ""] + header
    for name, alternative in result["alternatives"].items():
        lines += [_row(name, group, g) for group, g in alternative["groups"].items()]
    for name, alternative in result["alternatives"].items():
        rule = alternative["rule"]
        if rule:
            lines += ["", "- %s: skips %d failed opens (%d not credited to the record) and %d opened pages; "
                      "top: %s." % (
                name, rule.get("failedSkipped", 0), alternative["notCreditedByRecord"], rule.get("openedSkipped", 0),
                ", ".join("%s %d" % (x, n) for x, n in rule["top"]))]
    cost = result["cost"]
    lines += ["", "## Marginal cost of a web call (screen and cases, question fixed effects)", "",
              "%d answers on %d questions; mean %.0f new tokens, %.0f s and %.1f web calls per answer." % (
                  cost["answers"], cost["questions"], cost["means"]["newTokens"], cost["means"]["seconds"],
                  cost["means"]["web"]), "", "| Outcome | Model | Coefficient [95%] |", "|---|---|---|"]
    for name, model in cost["models"].items():
        outcome, label = name.split("|")
        for column, pair in model["intervals"].items():
            lines.append("| %s | %s | %s: %s%s |" % (outcome, label, column, _num(model["coefficients"][column], 0),
                                                       _ci(pair, False, 0)))
    lines += ["", "## Failed opens not credited", ""]
    for group, rest in result["notCredited"].items():
        lines.append("- %s: %d not credited; %s; never-opened hosts: %s" % (
            group, rest["notCredited"], ", ".join("%s %d" % kv for kv in sorted(rest["byWhy"].items())),
            ", ".join("%s %d" % (h, n) for h, n in rest["neverOpenedHosts"])))
    found = result["hosts"]
    for title, key in (("Failing hosts", "hosts"), ("Failing URL patterns", "patterns")):
        lines += ["", "## " + title, "", "| Name | Failed | Opened | Fail rate |", "|---|---|---|---|"]
        lines += ["| %s | %d | %d | %s |" % (x["name"], x["failed"], x["opened"], _pct(x["failRate"]))
                  for x in found[key]]
    lines += ["", "## Where a failed source did open (mirrors)", "", "| Failed at | Opened at | Failed opens |",
              "|---|---|---|"]
    lines += ["| %s | %s | %d |" % (x["failedAt"], x["openedAt"], x["failedOpens"]) for x in found["mirrors"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--reps", type=int, default=REPS)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    result, rows = build(reps=args.reps)
    atomic_json(out / "results.json", result, private=True)
    atomic_bytes(out / "results.md", render(result).encode("utf-8"), private=True)
    atomic_bytes(out / "failed-opens.jsonl", "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                                     for r in rows).encode("utf-8"), private=True)
    print(render(result))


if __name__ == "__main__":
    main()
