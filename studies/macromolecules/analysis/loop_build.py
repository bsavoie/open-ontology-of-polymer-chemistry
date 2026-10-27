#!/usr/bin/env python3
"""Records-only data behind Fig. 4b, 4d and 4e of the Macromolecules study (E2: reuse, revisits, scaffold trajectory,
memory curve).

    python3 -B build.py

Reads, read-only: the question records (`.oopc/loop/questions`), the traces with their tool-return payloads
(`.oopc/runs`), the frozen K3 store (opened with `mode=ro`), the campaign records (questions, report, wave states,
checks, call ledger) and the 200-task run's records. Writes `reuse.json`, `revisits.json`, `trajectory.json` and
`curve.json` beside this file and nothing anywhere else. No engine calls, no network, standard library only; the only
project code used is two pure counting functions from the frozen worktree (`task_progress.effort`,
`calls.new_tokens`), so web calls and new tokens are counted exactly as the campaign report counts them.

Outputs carry ids, counts, ratios, timestamps and prompt versions only: never question text, excerpt text, source
text or local paths. Text fields (excerpts, flag reasons, note `supports`) are read in memory to classify them.

Ran as `.oopc/study/analysis/loop/build.py`; moved to the repository on 2026-10-13 unchanged except imports and paths.
It still writes to `.oopc/study/analysis/loop/`, not beside this file; the frozen worktree is now common.CODE.

    python3 -B build.py --kf [--out DIR]   # experiment A1: the same build on KF, into loop-kf

`--kf` (2026-10-18) reads the frozen copy of KF (`kf.store()`) instead of K3, writes to `.oopc/study/analysis/loop-kf/`
(or `--out`) and puts KF's pins (`kf.meta`) in every output. The trajectory's excerpt measures read each excerpt as the
researcher saved it (`kf.as_written`): the 2026-10-14/16 cleanup filled or replaced 3,888 excerpts, which says nothing
about what a prompt version produced. On K3 this is the stored excerpt, so the K3 build is unchanged.
"""
import argparse
import bisect
import collections
import datetime as dt
import hashlib
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the frozen worktree
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, ROOT, analysis_dir  # noqa: E402  (common puts CODE first on sys.path)
from analysis import kf  # noqa: E402  (KF's pins, frozen copy and as-written excerpts)


def arguments():
    parser = argparse.ArgumentParser(description="Records-only data behind Fig. 4b, 4d and 4e.")
    parser.add_argument("--kf", action="store_true", help="read KF's frozen copy and write to loop-kf")
    parser.add_argument("--out", type=Path, help="write the outputs here instead")
    return parser.parse_args()


ARGS = arguments() if __name__ == "__main__" else argparse.Namespace(kf=False, out=None)
OUT = ARGS.out or analysis_dir("loop-kf" if ARGS.kf else "loop")  # the private folder it ran in and writes to
OOPC = ROOT / ".oopc"
FREEZE = CODE
from oopc.calls import new_tokens  # noqa: E402  (pure)
from oopc.task_progress import effort, read_progress  # noqa: E402  (pure)

QUESTIONS = OOPC / "loop" / "questions"
RUNS = OOPC / "runs"
HARNESS = OOPC / "loop" / "harness"
K3 = HARNESS / "2026-10-ablation" / "workspaces" / "K3" / ".oopc" / "loop" / "knowledge.sqlite"
STORE_NAME = "KF" if ARGS.kf else "K3"
STORE = kf.store() if ARGS.kf else K3
CAMPAIGN = HARNESS / "2026-10-campaign"
RUN200 = HARNESS / "2026-10-03-200"
LEDGER = CAMPAIGN / "workspace" / ".oopc" / "loop" / "calls"

STATUS_LABEL = {"supported": "Reviewed", "accepted": "Added", "uncertain": "Needs checking",
                "unsupported": "Rejected", "unreviewed": "Needs checking"}
AUTO_FLAG = "The excerpt does not show the reported value"
STAGES = ["run200", "wave1", "wave2", "wave3"]
STAGE_INFO = {"run200": "200-task run (2026-10-03/04)", "wave1": "campaign wave 1", "wave2": "campaign wave 2",
              "wave3": "campaign wave 3"}
BLOCK = 25


# ---------------------------------------------------------------- helpers

def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ro(path):
    return sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)


def when(value):
    if not value:
        return None
    value = value + "T00:00:00+00:00" if len(value) == 10 else value
    t = dt.datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def hours(start, end):
    return round((when(end) - when(start)).total_seconds() / 3600, 3)


def med(values, digits=3):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(values), digits) if values else None


def quantiles(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    pick = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]  # noqa: E731
    return dict(n=len(values), min=values[0], p25=pick(0.25), median=round(statistics.median(values), 3),
                p75=pick(0.75), p90=pick(0.9), max=values[-1], mean=round(sum(values) / len(values), 3))


def share(part, whole, digits=4):
    return round(part / whole, digits) if whole else None


def div(a, b):
    return a / b if (a is not None and b) else None


def bin_label(n):
    return "0" if n == 0 else "1" if n == 1 else "2-3" if n <= 3 else "4-6" if n <= 6 else "7+"


DOSE_BINS = ["0", "1", "2-3", "4-6", "7+"]


def write(name, value):
    path = OUT / name
    text = json.dumps(value, indent=1, ensure_ascii=False, default=str)
    if "/Users/" in text or "\\Users\\" in text:
        raise SystemExit("refusing to write a local path into " + name)
    path.write_text(text + "\n", encoding="utf-8")
    path.chmod(0o600)


def freeze_revision():
    try:
        pointer = (FREEZE / ".git").read_text().split("gitdir:", 1)[1].strip()
        return (Path(pointer) / "HEAD").read_text().strip()[:12]
    except (OSError, IndexError):
        return None


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:24]


def check(expected, computed, tolerance):
    """Expected value from the campaign plan against the recomputed one."""
    ok = None if computed is None else abs(computed - expected) <= tolerance
    return dict(plan=expected, records=computed, reproduced=ok)


# ---------------------------------------------------------------- inputs

camp_tasks = sorted(jread(CAMPAIGN / "questions.json"), key=lambda t: t["number"])
camp_by_id = {t["taskId"]: t for t in camp_tasks}
run200_tasks = sorted(jread(RUN200 / "questions.json"), key=lambda t: t["number"])
run200_by_id = {t["taskId"]: t for t in run200_tasks}
report = jread(CAMPAIGN / "report.json")
report_rows = {r["taskId"]: r for r in report["rows"]}


def stage_of(qid, origin):
    if qid in run200_by_id:
        return "run200"
    if qid in camp_by_id:
        return "wave%d" % camp_by_id[qid]["wave"]
    return "pre-" + (origin or "unknown")


answers = {}
for folder in sorted(QUESTIONS.iterdir()):
    if not (folder / "question.json").exists():
        continue
    q = jread(folder / "question.json")
    rec = dict(id=folder.name, status=q.get("status"), origin=q.get("origin"), engine=q.get("engine"),
               submittedAt=q.get("submittedAt"), finishedAt=q.get("finishedAt"), runId=q.get("runId"),
               stage=stage_of(folder.name, q.get("origin")))
    if (folder / "result.json").exists():
        result = jread(folder / "result.json")
        body = result.get("answer") or {}
        work = effort(result, read_progress(folder / "progress.json"))
        cited = [c for c in body.get("citations") or [] if isinstance(c, str)]
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        total = (usage["input_tokens"] + usage["output_tokens"]) if all(
            type(usage.get(k)) is int for k in ("input_tokens", "output_tokens")) else None
        rec.update(model=result.get("model"), promptVersion=result.get("promptVersion"),
                   newTokens=new_tokens(result.get("usage")), totalTokens=total,
                   webCalls=sum(work.get(k) or 0 for k in ("webSearches", "pagesRead", "unclassifiedWebCalls")),
                   knowledgeLookups=work.get("knowledgeLookups"), citations=len(cited),
                   findingCited=[c for c in cited if c.startswith("finding:")])
        rec["_body"] = body  # in memory only; never written
    answers[folder.name] = rec

history = sorted((a for a in answers.values() if a["status"] == "completed"),
                 key=lambda a: (a["submittedAt"], a["finishedAt"] or ""))
for rank, a in enumerate(history, 1):
    a["rank"] = rank
N = len(history)
submitted_times = [when(a["submittedAt"]) for a in history]

# Traces: every search_knowledge call with what its payload actually returned.
searches = {}
trace_problems = collections.Counter()
for a in history:
    if not a.get("runId"):
        continue
    events_path = RUNS / a["runId"] / "events.jsonl"
    if not events_path.exists():
        trace_problems["missingTrace"] += 1
        continue
    found = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("operation") != "knowledge.search_knowledge":
            continue
        if event.get("status") != "ok":
            trace_problems["searchNotOk"] += 1
        payload_path = RUNS / a["runId"] / "payloads" / ("%s.json" % event.get("payload_hash"))
        if not event.get("payload_hash") or not payload_path.exists():
            trace_problems["missingPayload"] += 1
            continue
        result = jread(payload_path).get("result") or {}
        found.append(dict(at=event["timestamp"], limit=(event.get("request") or {}).get("arguments", {}).get("limit"),
                          groups={g: [x["id"] for x in result.get(g) or [] if isinstance(x, dict) and x.get("id")]
                                  for g in ("reviewed", "added", "unreviewed")},
                          notes=len(result.get("notes") or [])))
    searches[a["id"]] = found
    if a.get("knowledgeLookups") is not None and a["knowledgeLookups"] != len(found):
        trace_problems["lookupsDifferFromTrace"] += 1

db = ro(STORE)
findings = {}
for row in db.execute("SELECT id, question_id, status, subject, created_at, excerpt, value, unit, source_url, "
                      "source_doi, detail FROM findings"):
    fid, qid, status, subject, created, excerpt, value, unit, url, doi, detail = row
    detail = json.loads(detail or "{}")
    findings[fid] = dict(question=qid, status=status, subject=subject or "", created=created,
                         excerpt=kf.as_written(excerpt or "", detail), value=value or "", unit=unit or "",
                         url=url or "", doi=doi or "", detail=detail)
notes = [dict(id=r[0], question=r[1], supports=r[2] or "", url=r[3] or "", doi=r[4] or "", readUrl=r[5] or "")
         for r in db.execute("SELECT id, question_id, supports, url, doi, read_url FROM notes")]
deposit_counts = dict(db.execute("SELECT question_id, findings FROM deposits"))
db.close()

COUNTS = dict(answers=N, answersByStage=dict(collections.Counter(a["stage"] for a in history)))
META = dict(kf.meta("loop_build.py (records only; no engine calls)"), **COUNTS) if ARGS.kf else dict(
    generatedBy="build.py (records only; no engine calls)",
    generatedAt=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    freezeRevision=freeze_revision(), k3Sha256Prefix=file_hash(K3),
    k3Snapshot="oopc-knowledge-0f0a0104a3f9e15a08b94bf7 (id given in the study plan)",
    k3Findings=len(findings), k3Notes=len(notes), **COUNTS)


def deposit_rank(created):
    """How many answers had been submitted when a finding was saved."""
    return bisect.bisect_right(submitted_times, when(created))


# ---------------------------------------------------------------- reuse.json

def build_reuse():
    returned_by = collections.defaultdict(list)  # fid -> [(rank, at, group)] in history order
    for a in history:
        for s in searches.get(a["id"], []):
            for group, ids in s["groups"].items():
                for fid in ids:
                    returned_by[fid].append((a["rank"], s["at"], group, a["id"]))
    cited_by = collections.defaultdict(list)
    for a in history:
        for fid in a.get("findingCited") or []:
            cited_by[fid].append((a["rank"], a["finishedAt"], a["id"]))

    rows, problems = [], collections.Counter()
    for fid, f in findings.items():
        d_rank = deposit_rank(f["created"])
        ret = returned_by.get(fid, [])
        sessions = sorted({r[3] for r in ret})
        if any(q == f["question"] for q in sessions):
            problems["returnedToItsOwnSession"] += 1
        if any(r[0] <= d_rank for r in ret):
            problems["returnedBeforeDeposit"] += 1
        cit = cited_by.get(fid, [])
        if any(c[0] <= d_rank for c in cit):
            problems["citedBeforeDeposit"] += 1
        first_ret = min(ret, key=lambda r: (r[0], r[1])) if ret else None
        first_cit = min(cit) if cit else None
        shown = collections.Counter(r[2] for r in ret)
        rows.append(dict(
            id=fid, status=f["status"], statusLabel=STATUS_LABEL.get(f["status"], f["status"]),
            depositStage=answers[f["question"]]["stage"] if f["question"] in answers else "import",
            questionId=f["question"], subject=f["subject"] or None, createdAt=f["created"],
            depositRank=d_rank, laterAnswers=N - d_rank,
            returnedSessions=len(sessions), returnEvents=len(ret),
            returnedShownAs={k: shown[k] for k in ("reviewed", "added", "unreviewed") if shown[k]},
            citedAnswers=len({c[2] for c in cit}),
            firstReturn=dict(questionId=first_ret[3], lagAnswers=first_ret[0] - d_rank,
                             lagHours=hours(f["created"], first_ret[1])) if first_ret else None,
            firstCitation=dict(questionId=first_cit[2], lagAnswers=first_cit[0] - d_rank,
                               lagHours=hours(f["created"], first_cit[1])) if first_cit else None))
    rows.sort(key=lambda r: (r["depositRank"], r["id"]))
    total = len(rows)

    def ccdf(key):
        values = [r[key] for r in rows]
        top = max(values)
        return dict(note="share of all %d findings with at least k" % total,
                    points=[dict(k=k, findings=sum(v >= k for v in values), share=share(sum(v >= k for v in values), total))
                            for k in range(0, top + 1)])

    def reuse_summary(group):
        n = len(group)
        return dict(findings=n, everReturned=sum(r["returnedSessions"] > 0 for r in group),
                    everReturnedShare=share(sum(r["returnedSessions"] > 0 for r in group), n),
                    everCited=sum(r["citedAnswers"] > 0 for r in group),
                    everCitedShare=share(sum(r["citedAnswers"] > 0 for r in group), n),
                    meanReturnedSessions=round(sum(r["returnedSessions"] for r in group) / n, 3) if n else None,
                    meanCitedAnswers=round(sum(r["citedAnswers"] for r in group) / n, 3) if n else None,
                    citedShareOfReturned=share(sum(r["citedAnswers"] > 0 for r in group),
                                               sum(r["returnedSessions"] > 0 for r in group)))

    by_status = {label: reuse_summary([r for r in rows if r["statusLabel"] == label])
                 for label in ("Reviewed", "Added", "Needs checking", "Rejected")}
    stage_order = ["import", "pre-legacy", "pre-ask", "pre-research", "run200", "wave1", "wave2", "wave3"]
    by_stage = {s: reuse_summary([r for r in rows if r["depositStage"] == s]) for s in stage_order
                if any(r["depositStage"] == s for r in rows)}
    by_exposure = {}
    for lo, hi in ((0, 24), (25, 99), (100, 399), (400, 799), (800, 10 ** 6)):
        group = [r for r in rows if lo <= r["laterAnswers"] <= hi]
        if group:
            by_exposure["%d-%s" % (lo, hi if hi < 10 ** 6 else "")] = reuse_summary(group)
    shown_events = collections.Counter()
    shown_findings = collections.Counter()
    for r in rows:
        for k, v in r["returnedShownAs"].items():
            shown_events[k] += v
            shown_findings[k] += 1

    def lag_summary(key):
        got = [r[key] for r in rows if r[key]]
        answers_lag = [g["lagAnswers"] for g in got]
        bins = collections.Counter()
        for v in answers_lag:
            bins["1" if v <= 1 else "2-5" if v <= 5 else "6-25" if v <= 25 else "26-100" if v <= 100
                 else "101-400" if v <= 400 else "401+"] += 1
        return dict(findings=len(got), answers=quantiles(answers_lag), hours=quantiles([g["lagHours"] for g in got]),
                    answersHistogram={k: bins[k] for k in ("1", "2-5", "6-25", "26-100", "101-400", "401+")})

    # Finding share of all citations, in blocks of 25 answers over the whole history and over the campaign.
    def citation_blocks(seq):
        out = []
        for start in range(0, len(seq), BLOCK):
            block = seq[start:start + BLOCK]
            cits = sum(a.get("citations") or 0 for a in block)
            fcits = sum(len(a.get("findingCited") or []) for a in block)
            out.append(dict(ranks="%d-%d" % (block[0]["rank"], block[-1]["rank"]), n=len(block),
                            stages=dict(collections.Counter(a["stage"] for a in block)),
                            citations=cits, findingCitations=fcits, findingShare=share(fcits, cits, 3),
                            answersCitingFindings=sum(bool(a.get("findingCited")) for a in block)))
        return out

    campaign = [a for a in history if a["stage"].startswith("wave")]
    camp_share = share(sum(len(a["findingCited"]) for a in campaign), sum(a["citations"] for a in campaign), 3)
    all_share = share(sum(len(a.get("findingCited") or []) for a in history), sum(a.get("citations") or 0 for a in history), 3)

    # Dose response: first asks of the campaign by how many earlier campaign tasks named their polymer.
    def dose(counter, label, definition, include_200=False):
        mats200 = collections.Counter(t["material"] for t in run200_tasks)
        bins = {b: [] for b in DOSE_BINS}
        for i, t in enumerate(camp_tasks):
            if t.get("revisit"):
                continue
            earlier = camp_tasks[:i]
            n = counter(t, earlier) + (min(mats200.get(m, 0) for m in t["materials"]) if include_200 else 0)
            bins[bin_label(n)].append(answers[t["taskId"]])
        return dict(label=label, definition=definition,
                    bins=[dict(bin=b, firstAsks=len(v), citingFinding=sum(bool(a["findingCited"]) for a in v),
                               share=share(sum(bool(a["findingCited"]) for a in v), len(v), 3),
                               medianNewTokens=med([a["newTokens"] for a in v], 1),
                               medianWebCalls=med([a["webCalls"] for a in v], 1)) for b, v in bins.items()])

    per_material = lambda t, earlier, m: sum(m in u["materials"] for u in earlier)  # noqa: E731
    primary = dose(lambda t, e: min(per_material(t, e, m) for m in t["materials"]), "primary",
                   "For each of the 655 campaign first asks (non-revisits): for each polymer it names (the campaign's "
                   "material string), the number of earlier campaign tasks of any kind (revisits included) naming that "
                   "polymer; a comparison takes its least-asked polymer (minimum). Citing = the answer cites at least "
                   "one finding id.")
    variants = [
        dose(lambda t, e: max(per_material(t, e, m) for m in t["materials"]), "maxOverPolymers",
             "As primary, but a comparison takes its most-asked polymer (maximum)."),
        dose(lambda t, e: sum(bool(set(u["materials"]) & set(t["materials"])) for u in e), "anySharedPolymer",
             "Earlier campaign tasks sharing any polymer with the question."),
        dose(lambda t, e: min(per_material(t, e, m) for m in t["materials"]), "with200TaskRun",
             "As primary, plus the 200-task run's questions on the same polymer (by material string).", include_200=True),
        dose(lambda t, e: min(sum(m in u["materials"] for u in e if not u.get("revisit")) for m in t["materials"]),
             "firstAsksOnly", "As primary, counting earlier first asks only (no revisits)."),
    ]
    plan = [0.13, 0.18, 0.28, 0.37, 0.44]
    primary["plan"] = dict(zip(DOSE_BINS, plan))
    primary["reproduced"] = all(abs(b["share"] - p) <= 0.005 for b, p in zip(primary["bins"], plan))

    return dict(
        meta=dict(META, definitions=dict(
            returned="A finding is returned to a session when one of that session's search_knowledge tool-return "
                     "payloads lists its id in the reviewed, added or unreviewed group (the same-source extras are "
                     "inside these groups). Only payloads are counted; nothing is inferred between searches. "
                     "knowledge.get_finding (3 calls in all traces) is not a search and is not counted.",
            cited="An answer cites a finding when its citations list holds the id (the list equals the finding ids in "
                  "the answer text in all 1,092 answers).",
            later="Answers are ordered by submittedAt over the whole linear history (main store -> 200-task "
                  "workspace -> campaign workspace, each seeded from the one before). A finding's depositRank is the "
                  "number of answers submitted before its created_at; lagAnswers = rank of the reusing answer - "
                  "depositRank (1 = the next answer); lagHours runs from created_at to the search event (returns) or "
                  "to the citing answer's finishedAt (citations). Legacy imports carry a date-only created_at.",
            status="Status is the finding's status in the frozen %s store; returnedShownAs is the group it was shown "
                   "in at each return (its status at that time)." % STORE_NAME)),
        integrity=dict(traceProblems=dict(trace_problems), orderingProblems=dict(problems),
                       searchesInTraces=sum(len(v) for v in searches.values()),
                       sessionsWithSearches=sum(bool(v) for v in searches.values())),
        totals=dict(findings=total, **{k: v for k, v in reuse_summary(rows).items() if k != "findings"},
                    returnEvents=sum(r["returnEvents"] for r in rows),
                    citationsOfFindings=sum(r["citedAnswers"] for r in rows)),
        ccdfReturnedSessions=ccdf("returnedSessions"), ccdfCitedAnswers=ccdf("citedAnswers"),
        byStatus=by_status, byDepositStage=by_stage, byLaterAnswers=by_exposure,
        shownAtReturn=dict(events=dict(shown_events), distinctFindings=dict(shown_findings)),
        firstReturnLag=lag_summary("firstReturn"), firstCitationLag=lag_summary("firstCitation"),
        findingShareOfCitations=dict(
            campaign=check(0.632, camp_share, 0.0005), wholeHistory=all_share,
            historyBlocks=citation_blocks(history), campaignBlocks=citation_blocks(campaign)),
        doseResponse=dict(primary=primary, variants=variants),
        findings=rows)


# ---------------------------------------------------------------- revisits.json

def returned_ids(qid):
    return {fid for s in searches.get(qid, []) for ids in s["groups"].values() for fid in ids}


def pair_record(run, task, parent_id, kind):
    r, p = answers[task["taskId"]], answers[parent_id]
    parent_findings = {fid for fid, f in findings.items() if f["question"] == parent_id
                       and when(f["created"]) < when(r["submittedAt"])}
    got = returned_ids(task["taskId"]) & parent_findings
    cited = set(r["findingCited"])
    return dict(run=run, wave=task.get("wave", 0), number=task["number"], type=kind, taskId=task["taskId"],
                parentId=parent_id, parentStage=p["stage"], parentNumber=task.get("parentNumber"),
                tokens=[p["newTokens"], r["newTokens"]], tokenRatio=div(r["newTokens"], p["newTokens"]),
                totalTokens=[p["totalTokens"], r["totalTokens"]], totalTokenRatio=div(r["totalTokens"], p["totalTokens"]),
                web=[p["webCalls"], r["webCalls"]], webRatio=div(r["webCalls"], p["webCalls"]), noWeb=r["webCalls"] == 0,
                searches=len(searches.get(task["taskId"], [])), citedFindings=len(cited), citesFindings=bool(cited),
                parentFindings=len(parent_findings), parentFindingsReturned=len(got),
                parentFindingsReturnedShare=share(len(got), len(parent_findings), 3),
                citedParentFindings=len(cited & parent_findings),
                prompt=[p.get("promptVersion"), r.get("promptVersion")], model=[p.get("model"), r.get("model")],
                engine=[p.get("engine"), r.get("engine")], sameEngine=p.get("engine") == r.get("engine"))


def summarize_pairs(group):
    with_findings = [g for g in group if g["parentFindings"]]
    return dict(pairs=len(group), medianTokenRatio=med(g["tokenRatio"] for g in group),
                medianWebRatio=med(g["webRatio"] for g in group),
                medianTotalTokenRatio=med(g["totalTokenRatio"] for g in group),
                noWeb=sum(g["noWeb"] for g in group), citingFindings=sum(g["citesFindings"] for g in group),
                citingParentFindings=sum(g["citedParentFindings"] > 0 for g in group),
                parentsWithFindings=len(with_findings),
                parentFindingsReturnedAny=sum(g["parentFindingsReturned"] > 0 for g in with_findings),
                parentFindingsReturnedAll=sum(g["parentFindingsReturned"] == g["parentFindings"] for g in with_findings),
                medianParentFindingsReturnedShare=med(g["parentFindingsReturnedShare"] for g in with_findings),
                ratioAbove0p8=sum((g["tokenRatio"] or 0) >= 0.8 for g in group),
                totalsTokenRatio=round(div(sum(g["tokens"][1] or 0 for g in group), sum(g["tokens"][0] or 0 for g in group)) or 0, 3),
                totalsWebRatio=round(div(sum(g["web"][1] or 0 for g in group), sum(g["web"][0] or 0 for g in group)) or 0, 3))


def build_revisits():
    pairs = [pair_record("campaign", t, t["parent"], t["revisit"]) for t in camp_tasks if t.get("revisit")]
    run200_numbers = {t["number"]: t["taskId"] for t in run200_tasks}  # the 200-task run names its parent by number
    pairs += [dict(pair_record("run200", t, run200_numbers[t["parent"]], "exact"), parentNumber=t["parent"])
              for t in run200_tasks if t.get("parent")]
    camp = [p for p in pairs if p["run"] == "campaign"]
    by_type = {k: summarize_pairs([p for p in camp if p["type"] == k]) for k in ("exact", "paraphrase", "sibling")}
    by_wave = {"wave%d" % w: {k: summarize_pairs([p for p in camp if p["wave"] == w and p["type"] == k])
                              for k in ("exact", "paraphrase", "sibling")} | {
        "all": summarize_pairs([p for p in camp if p["wave"] == w])} for w in (1, 2, 3)}
    by_parent = {}
    for w in (1, 2, 3):
        for ps in sorted({p["parentStage"] for p in camp if p["wave"] == w}):
            by_parent["wave%d<-%s" % (w, ps)] = summarize_pairs([p for p in camp if p["wave"] == w and p["parentStage"] == ps])
    run200 = summarize_pairs([p for p in pairs if p["run"] == "run200"])
    expected = report["summary"]["memory"]["revisitsByType"]
    plan = dict(exact=(0.63, 0.27), paraphrase=(0.77, 0.55), sibling=(0.59, 0.18))
    checks = {k: dict(tokens=check(plan[k][0], by_type[k]["medianTokenRatio"], 0.005),
                      web=check(plan[k][1], by_type[k]["medianWebRatio"], 0.005),
                      reportJson=dict(tokens=expected[k]["medianTokenRatio"], web=expected[k]["medianWebRatio"],
                                      noWeb=expected[k]["noWeb"], citingFindings=expected[k]["citingFindings"]))
              for k in plan}
    checks["run200"] = dict(tokens=check(0.79, run200["medianTokenRatio"], 0.005),
                            web=check(0.84, run200["medianWebRatio"], 0.005),
                            webTotalsRatio=check(0.84, run200["totalsWebRatio"], 0.005), noWeb=check(0, run200["noWeb"], 0),
                            note="the plan's 0.84 is the ratio of summed web calls (repeats/first asks); the median "
                                 "of per-pair web ratios is 0.92")
    checks["campaignNoWeb"] = check(54, sum(p["noWeb"] for p in camp), 0)
    w2_from_w1 = summarize_pairs([p for p in camp if p["wave"] == 2 and p["parentStage"] == "wave1"])
    checks["wave2RevisitsOfWave1"] = dict(
        pairs=check(26, w2_from_w1["pairs"], 0), parentsWithFindings=check(21, w2_from_w1["parentsWithFindings"], 0),
        returnedAny=check(19, w2_from_w1["parentFindingsReturnedAny"], 0), noWeb=check(13, w2_from_w1["noWeb"], 0),
        medianTokens=check(0.56, w2_from_w1["medianTokenRatio"], 0.005))
    w3 = by_wave["wave3"]
    checks["wave3"] = dict(
        tokens={k: check(v, w3[k]["medianTokenRatio"], 0.005) for k, v in (("exact", 0.63), ("paraphrase", 0.77), ("sibling", 0.63))},
        web={k: check(v, w3[k]["medianWebRatio"], 0.005) for k, v in (("exact", 0.22), ("paraphrase", 0.56), ("sibling", 0.0))},
        totalTokens={k: check(v, w3[k]["medianTotalTokenRatio"], 0.005) for k, v in (("exact", 0.34), ("paraphrase", 0.54), ("sibling", 0.40))},
        noWeb=check(35, w3["all"]["noWeb"], 0))
    return dict(meta=dict(META, definitions=dict(
        tokens="new tokens = uncached input + output (calls.new_tokens) of the answer's research call; totalTokens "
               "count cached input too.",
        web="web calls = web searches + pages read + unclassified web calls (task_progress.effort with the "
            "answer's progress record), as report.py counts them.",
        parentFindings="findings in %s deposited by the parent answer before the revisit was submitted; "
                       "parentFindingsReturned = those whose ids appear in the revisit's search payloads." % STORE_NAME,
        medians="medians of per-pair ratios; pairs with a zero-web parent have no web ratio.")),
        summary=dict(campaignByType=by_type, campaignAll=summarize_pairs(camp), campaignByWave=by_wave,
                     campaignByWaveAndParent=by_parent, run200Repeats=run200),
        checks=checks, pairs=pairs)


# ---------------------------------------------------------------- trajectory.json

FLAG_CATEGORIES = [
    ("excerpt or quotation", r"excerpt|quotation|quote|verbatim"),
    ("read from a figure", r"figure|\bfig\b|\bfig\.|plot|graph|curve|chart|digiti[sz]|image|visual"),
    ("converted or calculated", r"conver|calculat|comput|derived|deriv|combin|infer|estimat|averag|normali[sz]"),
    ("conflicting reports", r"conflict|disagree|inconsisten|discrepan|contradict|differ|whereas|instead|mismatch|versus|"
                            r"elsewhere|also reports?|separately reports?|\bgives\b|nominal|not clearly distinguish"),
    ("unit or value doubt", r"unit|implausib|typo|mislabel|ambigu|unclear|doubt|error|notation|suspicious|uncertain|"
                            r"unusual|questionable|presumabl|exceptional|cannot be excluded|verify|check|confirm|label"),
    ("source access or transcription", r"relayed|fetch|extract|transcri|ocr|translat|snippet|abstract|secondary|access|"
                                       r"render|garbl|corrupt|pdf"),
]
FLAG_CATEGORIES = [(name, re.compile(p, re.I)) for name, p in FLAG_CATEGORIES]
QUOTE_LIMIT = re.compile(r"quotation limit", re.I)
UNOPENED = re.compile(
    r"(could not|couldn't|cannot|can't|unable to|did not|didn't|failed to|would not|wouldn't|not be) (be )?"
    r"(opened|open|accessed|access|loaded|load|retrieved|retrieve|read|fetched|fetch|reached|reach)"
    r"|\b(opening|access|retrieval|download|fetch|fetching|loading|publisher|PDF|HTML|page|link)( attempts?)? "
    r"(failed|was blocked|returned (an? )?(error|403|404|429|browser|bot|captcha|verification|javascript))"
    r"|\b(403|429|forbidden|access denied|paywall(ed)?|captcha|inaccessible|not accessible|browser (challenge|check|"
    r"verification)|bot (check|challenge|verification)|verification page|cloudflare|timed out|time-?out)\b", re.I)


def flag_category(text):
    if text == AUTO_FLAG:
        return "automatic: excerpt does not show value"
    for name, pattern in FLAG_CATEGORIES:
        if pattern.search(text):
            return name
    return "other"


def norm(text):
    text = unicodedata.normalize("NFKC", text or "").lower().replace("−", "-").replace("–", "-")
    return re.sub(r"[\s,;:.()\[\]\"'`]+", "", text)


def source_key(url, doi):
    d = (doi or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    if d:
        return "doi:" + d
    u = (url or "").strip().lower()
    m = re.match(r"^https?://(dx\.)?doi\.org/(.+)$", u)
    return "doi:" + m.group(2) if m else "url:" + u.rstrip("/")


def ledger_tokens():
    """Review and research new tokens per owner, from the campaign's call ledger and the 200-task run's call list."""
    owners = collections.defaultdict(lambda: collections.Counter())
    for path in LEDGER.glob("*.json"):
        c = jread(path)
        owners[c.get("owner")][c.get("phase")] += c.get("newTokens") or 0
    run200 = collections.Counter()
    by_number = {t["number"]: t["taskId"] for t in run200_tasks}
    for c in jread(RUN200 / "calls.json"):
        run200[c.get("phase")] += new_tokens(c.get("usage")) or 0
    return owners, run200, by_number


SCIENTIFIC = ("source-fact", "inference")  # the plan's "scientific statements" (388/429 in the 200-task run)


def checks_for(stage):
    """Whole-answer check verdicts: the first check and, in the campaign, the final verdict after the Codex recheck."""
    first, final, statements, supported = collections.Counter(), collections.Counter(), 0, 0
    scientific = scientific_ok = 0
    if stage == "run200":
        files = sorted(RUN200.glob("check-[0-9]*.json"))
        for path in files:
            c = jread(path)
            if "verdict" not in c:
                continue
            first[c["verdict"]] += 1
            final[c["verdict"]] += 1
            statements += len(c.get("statements") or [])
            supported += sum(s.get("verdict") == "supported" for s in c.get("statements") or [])
            scientific += sum(s.get("kind") in SCIENTIFIC for s in c.get("statements") or [])
            scientific_ok += sum(s.get("kind") in SCIENTIFIC and s.get("verdict") == "supported" for s in c.get("statements") or [])
    else:
        folder = CAMPAIGN / "waves" / ("wave-%s" % stage[-1]) / "checks"
        for path in sorted(folder.glob("check-0*.json")):
            if path.stem.endswith("-codex"):
                continue
            c = jread(path)
            if "verdict" not in c:
                continue
            first[c["verdict"]] += 1
            statements += len(c.get("statements") or [])
            supported += sum(s.get("verdict") == "supported" for s in c.get("statements") or [])
            scientific += sum(s.get("kind") in SCIENTIFIC for s in c.get("statements") or [])
            scientific_ok += sum(s.get("kind") in SCIENTIFIC and s.get("verdict") == "supported" for s in c.get("statements") or [])
            again = path.with_name(path.stem + "-codex.json")
            later = jread(again) if again.exists() else {}
            final[later.get("verdict") or c["verdict"]] += 1
    return dict(firstCheck=dict(first), finalAfterRecheck=dict(final), statements=statements,
                statementsSupported=supported, scientificStatements=scientific, scientificSupported=scientific_ok)


def build_trajectory(revisits):
    owners, run200_phase, _ = ledger_tokens()
    found_sources = collections.defaultdict(set)
    for f in findings.values():
        found_sources[f["question"]].add(source_key(f["url"], f["doi"]))
    pairs = revisits["pairs"]
    states = {w: jread(CAMPAIGN / "waves" / ("wave-%d" % w) / "state.json") for w in (1, 2, 3)}
    base200 = jread(RUN200 / "baseline.json")
    out = {}
    for stage in STAGES:
        done = [a for a in history if a["stage"] == stage]
        ids = {a["id"] for a in done}
        if stage == "run200":
            first = [a for a in done if not run200_by_id[a["id"]].get("parent")]
        else:
            first = [a for a in done if not camp_by_id[a["id"]].get("revisit")]
        fs = [f for f in findings.values() if f["question"] in ids]
        n = len(fs)
        researcher_flags = [f for f in fs if f["detail"].get("needsReview") and f["detail"].get("reviewFlag") != AUTO_FLAG]
        auto_flags = [f for f in fs if f["detail"].get("needsReview") and f["detail"].get("reviewFlag") == AUTO_FLAG]
        reasons = collections.Counter(flag_category((f["detail"].get("reviewFlag") or "").strip()) for f in researcher_flags)
        nonempty = [f for f in fs if f["excerpt"].strip()]
        exact = sum(f["excerpt"].strip() == f["value"].strip() for f in nonempty)
        value_unit = sum(norm(f["excerpt"]) in {norm(f["value"]), norm(f["value"] + f["unit"])} for f in nonempty)
        no_words = sum(not re.search(r"[A-Za-z]{2,}", f["excerpt"]) for f in nonempty)
        quote = collections.Counter()
        for a in done:
            body = a["_body"]
            parts = dict(answerText=body.get("answer") or "", limitations=json.dumps(body.get("limitations"), ensure_ascii=False),
                         findings=json.dumps(body.get("findings"), ensure_ascii=False),
                         sources=json.dumps(body.get("sources"), ensure_ascii=False))
            hit = {k: bool(QUOTE_LIMIT.search(v)) for k, v in parts.items()}
            for k, v in hit.items():
                quote[k] += v
            quote["anywhere"] += any(hit.values())
        empty_tasks = len({f["question"] for f in fs if not f["excerpt"].strip()})
        stage_notes = [x for x in notes if x["question"] in ids]
        fail_language = [x for x in stage_notes if UNOPENED.search(x["supports"])]
        unopened = [x for x in fail_language if source_key(x["url"], x["doi"]) not in found_sources[x["question"]]]
        rg = sum("researchgate" in x["readUrl"].lower() for x in stage_notes)
        if stage == "run200":
            research, review = run200_phase["research"], run200_phase["review"]
        else:
            research = sum(owners[i]["research"] for i in ids)
            review = sum(owners[i]["review"] for i in ids)
        cits = sum(a["citations"] for a in done)
        fcits = sum(len(a["findingCited"]) for a in done)
        stage_pairs = [p for p in pairs if (p["run"] == "run200") == (stage == "run200") and
                       (stage == "run200" or p["wave"] == int(stage[-1]))]
        exact_pairs = [p for p in stage_pairs if p["type"] == "exact"]
        per_answer = [deposit_counts.get(a["id"], 0) for a in done]
        out[stage] = dict(
            label=STAGE_INFO[stage],
            promptVersions=dict(collections.Counter(a.get("promptVersion") for a in done)),
            models=dict(collections.Counter(a.get("model") for a in done)),
            engines=dict(collections.Counter(a.get("engine") for a in done)),
            revision=(base200.get("revision") if stage == "run200" else states[int(stage[-1])].get("revision") or "")[:12],
            answers=len(done), firstAsks=len(first), revisits=len(done) - len(first),
            findings=n, findingsPerAnswerMedian=med(per_answer, 1), findingsPerAnswerMean=round(sum(per_answer) / len(per_answer), 2),
            flagged=dict(researcherFlagged=len(researcher_flags), researcherFlaggedShare=share(len(researcher_flags), n),
                         automaticExcerptFlag=len(auto_flags),
                         anyFlagShare=share(len(researcher_flags) + len(auto_flags), n),
                         researcherFlagReasons=dict(reasons.most_common()),
                         quotationFlags=sum(bool(re.search(r"quot", f["detail"].get("reviewFlag") or "", re.I))
                                            for f in researcher_flags)),
            excerpts=dict(empty=n - len(nonempty), emptyShare=share(n - len(nonempty), n),
                          answersWithAnEmptyExcerpt=empty_tasks,
                          bareExact=exact, bareExactShare=share(exact, n),
                          bareValueOrValueUnit=value_unit, bareValueOrValueUnitShare=share(value_unit, n),
                          bareValueOrValueUnitShareOfNonEmpty=share(value_unit, len(nonempty)),
                          noWordExcerpt=no_words, noWordExcerptShare=share(no_words, n)),
            quotationLimitAnswers=dict(quote),
            notes=dict(total=len(stage_notes), failureLanguage=len(fail_language),
                       unopenedSources=len(unopened), researchGateCopies=rg,
                       researchGateShare=share(rg, len(stage_notes))),
            reviewTokens=review, researchTokens=research, reviewPerResearchToken=round(review / research, 3) if research else None,
            answersWithoutWeb=sum(a["webCalls"] == 0 for a in done),
            answersCitingFindings=sum(bool(a["findingCited"]) for a in done),
            answersCitingFindingsShare=share(sum(bool(a["findingCited"]) for a in done), len(done), 3),
            findingShareOfCitations=share(fcits, cits, 3),
            answersSayingNotInSavedFindings=sum("not in the saved findings" in (a["_body"].get("answer") or "").lower() for a in done),
            medianFirstAskNewTokens=med([a["newTokens"] for a in first], 1),
            medianFirstAskWebCalls=med([a["webCalls"] for a in first], 1),
            medianNewTokens=med([a["newTokens"] for a in done], 1), medianWebCalls=med([a["webCalls"] for a in done], 1),
            revisitMedianTokenRatio=dict(exact=med(p["tokenRatio"] for p in exact_pairs),
                                         allTypes=med(p["tokenRatio"] for p in stage_pairs), pairs=len(stage_pairs)),
            wholeAnswerChecks=checks_for(stage))

    w1, w2, w3, r2 = out["wave1"], out["wave2"], out["wave3"], out["run200"]
    plan = dict(
        wave1=dict(
            researcherFlaggedShare=check(0.54, w1["flagged"]["researcherFlaggedShare"], 0.005),
            excerptFlagReasons=check(761, w1["flagged"]["researcherFlagReasons"].get("excerpt or quotation"), 0),
            flaggedForExcerptInclAutomatic=check(763, w1["flagged"]["researcherFlagReasons"].get("excerpt or quotation", 0)
                                                 + w1["flagged"]["automaticExcerptFlag"], 0),
            flaggedAll=check(905, w1["flagged"]["researcherFlagged"] + w1["flagged"]["automaticExcerptFlag"], 0),
            emptyExcerptShare=check(0.24, w1["excerpts"]["emptyShare"], 0.005),
            emptyExcerpts=check(401, w1["excerpts"]["empty"], 0),
            quotationLimitAnswers=check(81, w1["quotationLimitAnswers"]["anywhere"], 0),
            unopenedSourceNotes=check(10, w1["notes"]["unopenedSources"], 0),
            reviewPerResearchToken=check(0.35, w1["reviewPerResearchToken"], 0.005),
            answersWithoutWeb=check(7, w1["answersWithoutWeb"], 0),
            answersCitingFindings=check(35, w1["answersCitingFindings"], 0),
            medianFirstAskNewTokens=check(67700, w1["medianFirstAskNewTokens"], 50),
            medianWebCalls=check(7, w1["medianWebCalls"], 0),
            findings=check(1638, w1["findings"], 0), findingsPerAnswerMedian=check(10, w1["findingsPerAnswerMedian"], 0),
            checksFirst=dict(plan="6 pass, 6 uncertain, 0 fail", records=w1["wholeAnswerChecks"]["firstCheck"]),
            researchGateShare=check(0.14, w1["notes"]["researchGateShare"], 0.005),
            notInSavedFindings=check(0, w1["answersSayingNotInSavedFindings"], 0)),
        wave2=dict(
            researcherFlaggedShare=check(0.079, w2["flagged"]["researcherFlaggedShare"], 0.0005),
            excerptFlagReasons=check(44, w2["flagged"]["researcherFlagReasons"].get("excerpt or quotation"), 0),
            emptyExcerptShare=check(0.005, w2["excerpts"]["emptyShare"], 0.001),
            bareValueShare=check(0.64, w2["excerpts"]["bareValueOrValueUnitShare"], 0.005),
            bareValueShareAsGivenForWave3Comparison=check(0.69, w2["excerpts"]["bareValueOrValueUnitShare"], 0.005),
            quotationLimitAnswers=check(0, w2["quotationLimitAnswers"]["anywhere"], 0),
            unopenedSourceNotes=check(175, w2["notes"]["unopenedSources"], 0),
            reviewPerResearchToken=check(0.13, w2["reviewPerResearchToken"], 0.005),
            answersWithoutWeb=check(28, w2["answersWithoutWeb"], 0),
            answersCitingFindings=check(91, w2["answersCitingFindings"], 0),
            medianFirstAskNewTokens=check(60700, w2["medianFirstAskNewTokens"], 50),
            medianWebCalls=check(6, w2["medianWebCalls"], 0),
            findings=check(2922, w2["findings"], 0),
            checksFirst=dict(plan="11 pass, 9 uncertain, 0 fail", records=w2["wholeAnswerChecks"]["firstCheck"]),
            researchGateShare=check(0.06, w2["notes"]["researchGateShare"], 0.005),
            notInSavedFindings=check(43, w2["answersSayingNotInSavedFindings"], 0)),
        wave3=dict(
            bareValueShare=check(0.16, w3["excerpts"]["bareValueOrValueUnitShare"], 0.005),
            bareNoWordShare=check(0.16, w3["excerpts"]["noWordExcerptShare"], 0.005),
            emptyExcerpts=check(228, w3["excerpts"]["empty"], 0),
            answersWithAnEmptyExcerpt=check(27, w3["excerpts"]["answersWithAnEmptyExcerpt"], 0),
            quotationFlags=check(219, w3["flagged"]["quotationFlags"], 0),
            quotationLimitAnswers=check(27, w3["quotationLimitAnswers"]["anywhere"], 0),
            reviewPerResearchToken=check(0.32, w3["reviewPerResearchToken"], 0.005),
            answersWithoutWeb=check(64, w3["answersWithoutWeb"], 0),
            answersCitingFindings=check(190, w3["answersCitingFindings"], 0),
            medianFirstAskNewTokens=check(66200, w3["medianFirstAskNewTokens"], 50),
            medianWebCalls=check(6, w3["medianWebCalls"], 0),
            findings=check(3813, w3["findings"], 0)),
        run200=dict(
            revisitMedianTokenRatio=check(0.79, r2["revisitMedianTokenRatio"]["exact"], 0.005),
            medianNewTokens=check(43150, r2["medianNewTokens"], 50),
            findingsPerAnswerMedian=check(2, r2["findingsPerAnswerMedian"], 0),
            scientificStatements=check(429, r2["wholeAnswerChecks"]["scientificStatements"], 0),
            scientificSupported=check(388, r2["wholeAnswerChecks"]["scientificSupported"], 0),
            checks=dict(plan="19 pass, 17 uncertain, 4 fail; 388/429 statements supported",
                        records=r2["wholeAnswerChecks"])),
        campaign=dict(
            finalChecks=dict(plan="53 pass, 11 uncertain, 0 fail",
                             records=dict(sum((collections.Counter(out[s]["wholeAnswerChecks"]["finalAfterRecheck"])
                                               for s in ("wave1", "wave2", "wave3")), collections.Counter()))),
            reviewPerResearchToken=check(0.27, round(sum(out[s]["reviewTokens"] for s in ("wave1", "wave2", "wave3")) /
                                                     sum(out[s]["researchTokens"] for s in ("wave1", "wave2", "wave3")), 3), 0.005)))
    return dict(meta=dict(META, definitions=dict(
        researcherFlagged="findings the researcher itself set needsReview on (the automatic flag 'The excerpt does not "
                          "show the reported value', applied by the store to an unflagged finding, is counted "
                          "separately); shares are of the stage's findings in %s." % STORE_NAME,
        flagReasons="the researcher's reviewFlag text, first matching category in the order excerpt or quotation, "
                    "figure, conversion or calculation, conflicting reports, unit or value doubt, source access or "
                    "transcription, other (keyword rules in build.py; approximate).",
        bareExcerpt="bareExact: the excerpt equals the value string; bareValueOrValueUnit: after removing case, "
                    "spaces and punctuation the excerpt equals the value or the value with its unit; noWordExcerpt: "
                    "the excerpt holds no word of two or more letters. No excerpt text is written. Excerpts as the "
                    "researcher saved them (an excerpt the 2026-10-14/16 cleanup filled or replaced counts as it was).",
        quotationLimitAnswers="answers whose answer text, limitations, findings or sources contain 'quotation limit' "
                              "(case-insensitive); anywhere = any of these.",
        unopenedSources="source notes whose supports text says the source could not be opened or loaded (failure "
                        "language: could not open/access/load, 403/429, paywall, browser challenge, ...) and from "
                        "whose source the same answer saved no finding; failureLanguage counts all notes with such "
                        "language, including partly opened sources.",
        researchGate="notes whose readUrl (the URL actually read) is a ResearchGate copy, over all of the stage's notes.",
        quotationFlags="researcher flags whose reason mentions quotation (withheld or shortened excerpts).",
        reviewPerResearchToken="review new tokens / research new tokens of the stage's tasks, from the call ledger "
                               "(campaign) or the run's call list (200-task run), failed calls included.",
        checks="first whole-answer check (Claude for 63 of 64 in the campaign; Codex 31, Claude 9 in the 200-task run) and, in the "
               "campaign, the final verdict after the Codex recheck of every non-pass.")),
        stages=out, planChecks=plan)


# ---------------------------------------------------------------- curve.json

def build_curve():
    created = sorted(when(f["created"]) for f in findings.values())

    def size_at(moment):
        return bisect.bisect_left(created, when(moment))

    camp = [a for a in history if a["stage"].startswith("wave")]
    camp.sort(key=lambda a: camp_by_id[a["id"]]["number"])
    blocks = []
    for start in range(0, len(camp), BLOCK):
        block = camp[start:start + BLOCK]
        numbers = [camp_by_id[a["id"]]["number"] for a in block]
        blocks.append(dict(tasks="%d-%d" % (numbers[0], numbers[-1]), n=len(block),
                           waves=sorted({camp_by_id[a["id"]]["wave"] for a in block}),
                           medianTokens=med([a["newTokens"] for a in block]),
                           medianWebCalls=med([a["webCalls"] for a in block]),
                           citingFindings=round(sum(bool(a["findingCited"]) for a in block) / len(block), 2),
                           medianFindingCitations=med([len(a["findingCited"]) for a in block]),
                           revisits=sum(bool(camp_by_id[a["id"]].get("revisit")) for a in block),
                           answersWithoutWeb=sum(a["webCalls"] == 0 for a in block),
                           findingsInStoreAtStart=size_at(block[0]["submittedAt"])))
    reference = report["curve"]
    keys = ("tasks", "n", "medianTokens", "medianWebCalls", "citingFindings", "medianFindingCitations")
    mismatches = [i for i, (b, r) in enumerate(zip(blocks, reference)) if any(b[k] != r[k] for k in keys)]
    hist = []
    for start in range(0, N, BLOCK):
        block = history[start:start + BLOCK]
        hist.append(dict(ranks="%d-%d" % (block[0]["rank"], block[-1]["rank"]), n=len(block),
                         stages=dict(collections.Counter(a["stage"] for a in block)),
                         firstSubmittedAt=block[0]["submittedAt"],
                         withTokens=sum(a.get("newTokens") is not None for a in block),
                         medianTokens=med([a.get("newTokens") for a in block]),
                         medianWebCalls=med([a.get("webCalls") for a in block]),
                         citingFindings=round(sum(bool(a.get("findingCited")) for a in block) / len(block), 2),
                         answersWithoutWeb=sum(a.get("webCalls") == 0 for a in block),
                         findingsInStoreAtStart=size_at(block[0]["submittedAt"])))
    return dict(meta=dict(META, definitions=dict(
        campaign="campaign tasks in campaign order (task number), blocks of 25, as report.py's curve; medians of new "
                 "tokens and web calls; citingFindings = share of the block's answers citing at least one finding.",
        history="all 1,092 completed answers ordered by submittedAt, blocks of 25 (the last holds 17). Stages: pre-* "
                "= the main store before 2026-10-03 (legacy = imported 0.11 records, ask = asked in the app, "
                "research = research queue), run200 = the 200-task run, wave1-3 = the campaign. Legacy answers come "
                "from the retired 0.11 scaffold and have no search traces.",
        findingsInStoreAtStart="findings of the frozen %s store created before the block's first answer was "
                               "submitted (it keeps rejected findings; duplicates were never saved)." % STORE_NAME)),
        campaign=dict(blocks=blocks, matchesReportJson=not mismatches and len(blocks) == len(reference),
                      mismatchedBlocks=mismatches),
        history=dict(blocks=hist))


# ---------------------------------------------------------------- main

def main():
    reuse = build_reuse()
    revisits = build_revisits()
    trajectory = build_trajectory(revisits)
    curve = build_curve()
    OUT.mkdir(parents=True, exist_ok=True)
    write("reuse.json", reuse)
    write("revisits.json", revisits)
    write("trajectory.json", trajectory)
    write("curve.json", curve)
    t = reuse["totals"]
    print("findings %d; ever returned %.3f; ever cited %.3f" % (t["findings"], t["everReturnedShare"], t["everCitedShare"]))
    print("dose response primary:", [b["share"] for b in reuse["doseResponse"]["primary"]["bins"]],
          "reproduced" if reuse["doseResponse"]["primary"]["reproduced"] else "NOT reproduced")
    print("revisits:", {k: (v["medianTokenRatio"], v["medianWebRatio"]) for k, v in revisits["summary"]["campaignByType"].items()},
          "run200", revisits["summary"]["run200Repeats"]["medianTokenRatio"])
    print("curve matches report.json:", curve["campaign"]["matchesReportJson"])


if __name__ == "__main__":
    main()
