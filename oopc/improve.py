"""Measure: a weekly summary of the loop, and a like-for-like comparison of two parity runs.

- `summary` reads the recorded answers: how many reused saved findings, how many
  needed no web at all, tokens, failures by reason, the spot-check error rate,
  review backlog and the latest parity guardrail.
- `compare` puts two parity runs side by side over the questions checked in both,
  for example the runs before and after a change to the researcher's
  instructions. Those instructions live in code (`oopc.ask.RESEARCHER`); a change
  is a reviewed commit, judged by such a comparison.

Research workers never edit their own prompt, the review policy or code.
"""
from __future__ import annotations

import datetime as dt
import statistics

from . import calls, knowledge
from .util import read_json

MIN_PARITY_QUESTIONS = 6
TOTAL_TOKEN_ALLOWANCE = 1.1  # A change may use at most 10% more new tokens in total than the run it is compared with.


def summary(root, days=7, moment=None):
    from .ask import folder as questions_folder, reused_findings
    from .task_progress import effort, read_progress
    moment = moment or dt.datetime.now(dt.timezone.utc)
    since = (moment - dt.timedelta(days=days)).isoformat()
    base = questions_folder(root)
    answered, failed, web, tokens, reuse = 0, {}, [], [], 0
    zero_web = 0
    for path in sorted(base.glob("*/question.json")) if base.exists() else []:
        item = read_json(path)
        if item.get("origin") == "legacy" or (item.get("submittedAt") or "") < since:
            continue
        if item["status"] == "failed":
            reason = (item.get("error") or {}).get("reason", "unknown")
            failed[reason] = failed.get(reason, 0) + 1
        if item["status"] != "completed" or not (path.parent / "result.json").exists():
            continue
        result = read_json(path.parent / "result.json")
        value = effort(result, read_progress(path.parent / "progress.json"))
        answered += 1
        web_calls = (value.get("webSearches") or 0) + (value.get("pagesRead") or 0) + (value.get("unclassifiedWebCalls") or 0)
        web.append(web_calls)
        zero_web += web_calls == 0
        measured_tokens = calls.new_tokens(result.get("usage") or {})
        if measured_tokens is not None:
            tokens.append(measured_tokens)
        cited = reused_findings(root, (result.get("answer") or {}).get("citations"))
        reuse += cited["supported"] + cited["added"] > 0
    from .parity import report as parity_report
    latest = parity_report(root)
    return {"days": days, "answered": answered, "failed": failed, "reusedSavedFindings": reuse,
            "answeredWithoutWeb": zero_web, "medianWebCalls": statistics.median(web) if web else None,
            "medianNewTokens": statistics.median(tokens) if tokens else None,
            "knowledge": knowledge.summary(root), "spotChecks": knowledge.spot_check_stats(root),
            "reviews": review_diagnostics(root, since),
            "parity": {"run": latest["run"], "guardrail": latest["guardrail"]} if latest else None,
            "loopCosts": calls.summary(root, since)}


def review_diagnostics(root, since=""):
    with knowledge.connect(root) as db:
        rows = db.execute("SELECT r.engine, d.engine AS producer FROM reviews r JOIN deposits d ON r.question_id=d.question_id "
                          "WHERE r.started_at>=? AND r.status='completed'", (since,)).fetchall()
        given_up = db.execute("SELECT COUNT(*) FROM deposits WHERE review_status='failed' AND review_attempts>=?",
                              (knowledge.MAX_REVIEW_ATTEMPTS,)).fetchone()[0]
    same = sum(r["engine"] == r["producer"] for r in rows)
    return {"completed": len(rows), "sameEngine": same, "sameEngineFraction": same / len(rows) if rows else None,
            "waiting": len(knowledge.review_queue(root)), "givenUp": given_up}


def compare(baseline, trial):
    """Like for like: only questions whose ontology answer was checked in both runs. A trial is *recommended*
    (not worse on this set) when it has no more contradicted statements, no fewer complete answers or sourced
    results, keeps citations, and uses no more median new tokens and at most 10% more in total. Passes are shown
    beside these; they move with whether a source opened during the check."""
    from . import reviewer

    def checked(report):
        return {row["id"]: row["arms"]["ontology"] for row in report["rows"]
                if (row["arms"].get("ontology") or {}).get("verdict")}
    before, after = checked(baseline), checked(trial)
    common = sorted(set(before) & set(after))
    median = lambda values: statistics.median(values) if values else None

    def stats(arms):
        new = [(arms[q].get("metrics") or {}).get("newTokens") for q in common]
        cited = [arms[q].get("citedFraction") for q in common]
        # Older reports kept the statements but not the measures.
        measured = [arms[q].get("measures") or reviewer.measures({"verdict": arms[q]["verdict"],
                                                                  "resultGiven": arms[q].get("resultGiven"),
                                                                  "statements": arms[q].get("statements")})
                    for q in common]
        return {"contradicted": sum(m["contradicted"] for m in measured),
                "complete": sum(m["complete"] is True for m in measured),
                # None for checks made before the measure existed, not zero answers that gave the result.
                "resultsGiven": sum(m["resultGiven"] is True for m in measured)
                if any(isinstance(m["resultGiven"], bool) for m in measured) else None,
                "passes": sum(arms[q]["verdict"] == "pass" for q in common),
                "medianNewTokens": median([n for n in new if n is not None]),
                "medianCited": median([c for c in cited if c is not None]),
                "totalNewTokens": sum(new) if new and None not in new else None}
    first, second = stats(before), stats(after)
    pair = {key: (first[key], second[key]) for key in first}
    tokens, totals, cited = pair["medianNewTokens"], pair["totalNewTokens"], pair["medianCited"]
    enough = len(common) >= MIN_PARITY_QUESTIONS
    recommended = (enough and second["contradicted"] <= first["contradicted"] and second["complete"] >= first["complete"]
                   and (None in pair["resultsGiven"] or second["resultsGiven"] >= first["resultsGiven"])
                   and None not in tokens and tokens[1] <= tokens[0]
                   and None not in totals and totals[1] <= totals[0] * TOTAL_TOKEN_ALLOWANCE
                   and (cited[1] or 0) >= (cited[0] or 0) - 0.05)
    return {"baseline": baseline.get("run"), "trial": trial.get("run"), **pair, "compared": len(common),
            "checked": (len(before), len(after)), "recommended": bool(recommended),
            "notice": "Eight questions: 'recommended' means 'not worse on this set', not a proven improvement; "
                      "a difference of one or two statements, answers or passes is within noise."}
