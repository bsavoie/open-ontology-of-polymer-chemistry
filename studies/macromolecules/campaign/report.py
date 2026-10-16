"""The campaign's numbers, read from its records only (no engine calls): per wave and for the campaign so far.

    python report.py              # every wave run so far
    python report.py --wave 1

Writes `report.json` and `report.txt` beside this file. Revisits are compared with their first ask (an earlier
wave, or the 200-task run, whose records the workspace carries).

Ran in `.oopc/loop/harness/2026-10-campaign/` and still reads and writes there, not beside this file; moved to the
repository on 2026-10-13 unchanged except imports and paths.
"""
import argparse, collections, json, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-campaign")
WORK = BASE / "workspace"
from oopc import ask, calls, knowledge  # noqa: E402
from oopc.task_progress import effort, read_progress  # noqa: E402
from oopc.util import read_json  # noqa: E402


def median(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(values), 3) if values else None


def p90(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    return values[int(0.9 * (len(values) - 1))] if values else None


def seconds(start, end):
    import datetime as dt
    return (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds() if start and end else None


def task_record(task_id, ledger):
    """What one question cost and produced, from its saved records."""
    folder = ask.folder(WORK) / task_id
    if not (folder / "question.json").exists():
        return {"status": "unattempted"}
    item = read_json(folder / "question.json")
    row = {"status": item["status"], "engine": item.get("engine"), "error": (item.get("error") or {}).get("reason"),
           "seconds": seconds(item.get("startedAt"), item.get("finishedAt")),
           "deposit": knowledge.deposit_summary(WORK, task_id)}
    if (folder / "result.json").exists():
        result = read_json(folder / "result.json")
        answer = result.get("answer") or {}
        work = effort(result, read_progress(folder / "progress.json"))
        cited = [c for c in answer.get("citations") or [] if isinstance(c, str)]
        row.update(model=result.get("model"), newTokens=calls.new_tokens(result.get("usage")),
                   webCalls=sum(work.get(k) or 0 for k in ("webSearches", "pagesRead", "unclassifiedWebCalls")),
                   knowledgeLookups=work.get("knowledgeLookups"), citations=len(cited),
                   findingCitations=sum(c.startswith("finding:") for c in cited),
                   reuse=ask.reused_findings(WORK, cited), answerChars=len(answer.get("answer") or ""),
                   deferral=any(w in (answer.get("answer") or "").lower() for w in ("recorded below", "detailed below",
                                                                                   "listed below", "summarized below")))
    own = [c for c in ledger.get(task_id, [])]
    row["reviewTokens"] = sum(c.get("newTokens") or 0 for c in own if c["phase"] == "review")
    row["checkTokens"] = sum(c.get("newTokens") or 0 for c in own if c["phase"] == "answer-check")
    row["failedCalls"] = collections.Counter(c.get("reason") for c in own if c["outcome"] == "failed")
    return row


def summarize(rows, ledger_rows, checks):
    done = [r for r in rows if r["status"] == "completed"]
    first = [r for r in done if not r["revisit"]]
    revisits = [r for r in done if r["revisit"]]
    deposits = [r["deposit"] for r in done if r.get("deposit")]
    statuses = collections.Counter()
    for d in deposits:
        statuses.update(d.get("counts") or {})
    ids = {r["taskId"] for r in rows}
    with knowledge.connect(WORK) as db:
        marks = ",".join("?" * len(ids)) or "''"
        details = [(status, json.loads(d or "{}")) for status, d in db.execute(
            "SELECT status, detail FROM findings WHERE question_id IN (%s)" % marks, list(ids))]
        spot = collections.Counter(d.get("spotCheck") for _, d in details)
        spot.pop(None, None)
        flagged = collections.Counter(status for status, d in details if d.get("needsReview"))
        reviews = db.execute("SELECT r.engine, r.status, d.engine FROM reviews r JOIN deposits d ON "
                             "r.question_id=d.question_id WHERE r.question_id IN (%s)" % marks, list(ids)).fetchall()
        no_subject = db.execute("SELECT COUNT(*) FROM findings WHERE COALESCE(subject,'')='' AND question_id IN (%s)"
                                % marks, list(ids)).fetchone()[0]
        excerpt_flags = db.execute("SELECT COUNT(*) FROM findings WHERE json_extract(detail,'$.reviewFlag')="
                                   "'The excerpt does not show the reported value' AND question_id IN (%s)" % marks,
                                   list(ids)).fetchone()[0]
    completed_reviews = [r for r in reviews if r[1] == "completed"]
    phases = collections.defaultdict(lambda: {"calls": 0, "newTokens": 0, "missingUsage": 0, "failed": 0})
    for c in ledger_rows:
        bucket = phases[c["phase"]]
        bucket["calls"] += 1
        bucket["newTokens"] += c.get("newTokens") or 0
        bucket["missingUsage"] += c.get("newTokens") is None
        bucket["failed"] += c["outcome"] == "failed"
    statements = [s for c in checks.values() for s in c.get("statements", [])]
    pairs = []
    for r in revisits:
        parent = r.get("parentRecord") or {}
        if parent.get("status") == "completed":
            pairs.append(dict(number=r["number"], type=r["revisit"], parentWave=r.get("parentWave"),
                              sameEngine=parent.get("engine") == r.get("engine"),
                              tokenRatio=r["newTokens"] / parent["newTokens"] if parent.get("newTokens") and r.get("newTokens") is not None else None,
                              webRatio=r["webCalls"] / parent["webCalls"] if parent.get("webCalls") and r.get("webCalls") is not None else None,
                              web=[parent.get("webCalls"), r.get("webCalls")], tokens=[parent.get("newTokens"), r.get("newTokens")],
                              citedFindings=r.get("findingCitations")))
    by_type = {}
    for kind in ("exact", "paraphrase", "sibling"):
        group = [p for p in pairs if p["type"] == kind and p["sameEngine"]]
        by_type[kind] = dict(pairs=len(group), medianTokenRatio=median(p["tokenRatio"] for p in group),
                             medianWebRatio=median(p["webRatio"] for p in group),
                             noWeb=sum(p["web"][1] == 0 for p in group),
                             citingFindings=sum((p["citedFindings"] or 0) > 0 for p in group))
    return dict(
        tasks=dict(planned=len(rows), counts=dict(collections.Counter(r["status"] for r in rows)),
                   failures=dict(collections.Counter(r.get("error") for r in rows if r["status"] == "failed")),
                   engines=dict(collections.Counter(r.get("engine") for r in done)),
                   models=dict(collections.Counter(r.get("model") for r in done))),
        speed=dict(medianSeconds=median(r.get("seconds") for r in done), p90Seconds=p90([r.get("seconds") for r in done])),
        cost=dict(medianResearchTokens=median(r.get("newTokens") for r in done),
                  medianResearchTokensFirst=median(r.get("newTokens") for r in first),
                  medianResearchTokensRevisit=median(r.get("newTokens") for r in revisits),
                  phases={k: dict(v) for k, v in phases.items()},
                  reviewShareOfResearch=round(phases["review"]["newTokens"] / phases["research"]["newTokens"], 3)
                  if phases["research"]["newTokens"] else None),
        memory=dict(medianWebCalls=median(r.get("webCalls") for r in done),
                    medianWebCallsFirst=median(r.get("webCalls") for r in first),
                    medianWebCallsRevisit=median(r.get("webCalls") for r in revisits),
                    answersCitingFindings=sum((r.get("findingCitations") or 0) > 0 for r in done),
                    findingShareOfCitations=round(sum(r.get("findingCitations") or 0 for r in done) /
                                                  max(1, sum(r.get("citations") or 0 for r in done)), 3),
                    answersWithoutWeb=sum(r.get("webCalls") == 0 for r in done),
                    revisitsByType=by_type, revisitPairs=pairs),
        answers=dict(deferrals=sum(bool(r.get("deferral")) for r in done),
                     medianAnswerChars=median(r.get("answerChars") for r in done)),
        knowledge=dict(newFindings=sum(d.get("findings") or 0 for d in deposits), statuses=dict(statuses),
                       notes=sum(d.get("notes") or 0 for d in deposits), duplicates=sum(d.get("duplicates") or 0 for d in deposits),
                       dropped=sum(d.get("dropped") or 0 for d in deposits), withoutPolymerId=no_subject,
                       sentToReviewForExcerpt=excerpt_flags,
                       medianFindingsPerAnswer=median(d.get("findings") for d in deposits)),
        trust=dict(spotChecks=dict(spot), flaggedOutcomes=dict(flagged), reviewsCompleted=len(completed_reviews),
                   reviewsFailed=sum(r[1] == "failed" for r in reviews),
                   sameEngineReviewShare=round(sum(r[0] == r[2] for r in completed_reviews) / len(completed_reviews), 3)
                   if completed_reviews else None,
                   givenUp=sum((r.get("deposit") or {}).get("reviewStatus") == "failed" and
                               (r.get("deposit") or {}).get("reviewAttempts", 0) >= knowledge.MAX_REVIEW_ATTEMPTS for r in done)),
        quality=dict(checked=len(checks), verdicts=dict(collections.Counter(c.get("verdict") for c in checks.values())),
                     statements=len(statements), supported=sum(s.get("verdict") == "supported" for s in statements),
                     nonSupported=dict(collections.Counter(s.get("category") for s in statements if s.get("verdict") != "supported")),
                     completeness=dict(collections.Counter(s.get("verdict") for s in statements if s.get("kind") == "completeness"))),
    )


def curve(rows, size=25):
    """The memory curve: tasks in campaign order, in blocks."""
    done = [r for r in rows if r["status"] == "completed"]
    blocks = []
    for start in range(0, len(done), size):
        block = done[start:start + size]
        blocks.append(dict(tasks="%d-%d" % (block[0]["number"], block[-1]["number"]), n=len(block),
                           medianTokens=median(r.get("newTokens") for r in block),
                           medianWebCalls=median(r.get("webCalls") for r in block),
                           citingFindings=round(sum((r.get("findingCitations") or 0) > 0 for r in block) / len(block), 2),
                           medianFindingCitations=median(r.get("findingCitations") for r in block)))
    return blocks


def build(waves=None):
    tasks = json.loads((BASE / "questions.json").read_text())
    ledger_rows = calls.records(WORK)
    ledger = collections.defaultdict(list)
    for c in ledger_rows:
        ledger[c.get("owner")].append(c)
    parents = {}
    rows = []
    for task in tasks:
        if waves and task["wave"] not in waves:
            continue
        row = dict(task, **task_record(task["taskId"], ledger))
        if task.get("parent"):
            parents.setdefault(task["parent"], task_record(task["parent"], ledger))
            row["parentRecord"] = parents[task["parent"]]
        rows.append(row)
    attempted = [r for r in rows if r["status"] != "unattempted"]
    owners = {r["taskId"] for r in attempted}
    checks = {}
    for path in sorted((BASE / "waves").glob("wave-*/checks/check-0*.json")):
        value = read_json(path)
        number = int(path.stem.split("-")[1])
        if "verdict" in value and any(r["number"] == number for r in attempted):
            checks[number] = value
    value = dict(summary=summarize(attempted, [c for c in ledger_rows if c.get("owner") in owners], checks),
                 byWave={w: summarize([r for r in attempted if r["wave"] == w],
                                      [c for c in ledger_rows if c.get("owner") in {r["taskId"] for r in attempted if r["wave"] == w}],
                                      {n: c for n, c in checks.items() if any(r["number"] == n and r["wave"] == w for r in attempted)})
                         for w in sorted({r["wave"] for r in attempted})},
                 curve=curve(attempted), knowledgeNow=knowledge.summary(WORK),
                 byModel={m: summarize([r for r in attempted if r.get("model") == m],
                                       [c for c in ledger_rows if c.get("owner") in {r["taskId"] for r in attempted if r.get("model") == m}], {})
                          for m in sorted({r.get("model") for r in attempted if r.get("model")})},
                 rows=[{k: v for k, v in r.items() if k not in ("question",)} for r in attempted])
    return value


def text(value):
    s, lines = value["summary"], []
    lines.append("Campaign so far: %s" % s["tasks"])
    lines.append("Speed: %s" % s["speed"])
    lines.append("Cost: median research tokens %s (first asks %s, revisits %s); review/research %s" % (
        s["cost"]["medianResearchTokens"], s["cost"]["medianResearchTokensFirst"], s["cost"]["medianResearchTokensRevisit"],
        s["cost"]["reviewShareOfResearch"]))
    lines.append("By phase: %s" % s["cost"]["phases"])
    m = s["memory"]
    lines.append("Memory: median web calls %s (first %s, revisit %s); answers citing findings %s; finding share of citations %s; without web %s" % (
        m["medianWebCalls"], m["medianWebCallsFirst"], m["medianWebCallsRevisit"], m["answersCitingFindings"],
        m["findingShareOfCitations"], m["answersWithoutWeb"]))
    lines.append("Revisits (same engine): %s" % m["revisitsByType"])
    lines.append("Answers: %s" % s["answers"])
    lines.append("Knowledge: %s" % s["knowledge"])
    lines.append("Trust: %s" % s["trust"])
    lines.append("Quality (sampled checks): %s" % s["quality"])
    lines.append("Knowledge store now: %s" % value["knowledgeNow"])
    lines.append("Memory curve (blocks of 25 completed tasks):")
    lines += ["  %(tasks)s n=%(n)d tokens %(medianTokens)s web %(medianWebCalls)s citing %(citingFindings)s" % b for b in value["curve"]]
    for wave, w in value["byWave"].items():
        lines.append("Wave %s: tasks %s; tokens %s; web %s; revisits %s; checks %s" % (
            wave, w["tasks"]["counts"], w["cost"]["medianResearchTokens"], w["memory"]["medianWebCalls"],
            w["memory"]["revisitsByType"], w["quality"]["verdicts"]))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave", type=int, action="append")
    args = parser.parse_args()
    value = build(set(args.wave) if args.wave else None)
    for name, content in (("report.json", json.dumps(value, indent=1, default=str)), ("report.txt", text(value))):
        (BASE / name).write_text(content)
        (BASE / name).chmod(0o600)
    print(text(value))
