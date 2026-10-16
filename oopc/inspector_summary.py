"""Read-only, allowlisted interpretation of a run's own captured evidence.

No report discovery, source access, cohort lookup, or trace writes occur here.
Execution, qualified evaluation, and claim findings are deliberately separate.
"""
import json
import math

from .util import sqlite_close, sqlite_open


VERDICTS = {"pass", "fail", "uncertain"}
SCORE_FIELDS = ("supportedCorrectness", "qualificationScore", "citationEntailment",
                "abstentionScore", "taskCompletionScore", "fullResearchCoverage")


def _is_verdict(value):
    # Historical structured values remain unclassified; this is not admission normalization.
    return isinstance(value, str) and value in VERDICTS


def evaluation_denominators(evaluation):
    """Count complete recorded assessments; absent or inconsistent data is unknown."""
    result = {"scientificClaims": None, "scientificSupportLinks": None}
    claims = evaluation.get("answerClaimAssessments")
    if (evaluation.get("independentlySourceChecked") is not True
            or evaluation.get("completeAnswerCoverage") is not True
            or not isinstance(claims, list) or not claims):
        return result
    identifiers = []
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get("claimId"), str) or not claim["claimId"]
                or not isinstance(claim.get("kind"), str)
                or claim["kind"] not in {"scientific-claim", "corpus-attribution", "abstention"}
                or not _is_verdict(claim.get("verdict"))):
            return result
        identifiers.append(claim["claimId"])
    if len(identifiers) != len(set(identifiers)):
        return result
    result["scientificClaims"] = sum(claim["kind"] == "scientific-claim" for claim in claims)
    links = 0
    for claim in claims:
        if not isinstance(claim.get("citations"), list):
            return result
        local_ids = []
        for citation in claim["citations"]:
            if (not isinstance(citation, dict) or not isinstance(citation.get("evidenceId"), str)
                    or not citation["evidenceId"] or not isinstance(citation.get("role"), str)
                    or citation["role"] not in {"support", "access-gap", "corpus-attribution"}
                    or citation["role"] == "support" and claim["kind"] != "scientific-claim"):
                return result
            local_ids.append(citation["evidenceId"])
            links += citation["role"] == "support"
        if len(local_ids) != len(set(local_ids)):
            return result
    if "supportLinks" in evaluation and (type(evaluation["supportLinks"]) is not int or evaluation["supportLinks"] != links):
        return result
    result["scientificSupportLinks"] = links
    return result


def publication_inspection_summary(meta, events, artifacts):
    """Describe a recorded coordinator outcome, never rejudge its source work."""
    task = meta.get("task") if isinstance(meta.get("task"), dict) else {}
    job = task.get("specification") if isinstance(task.get("specification"), dict) else {}
    specification = job.get("specification") if isinstance(job.get("specification"), dict) else {}
    expected = isinstance(specification.get("publicationIngestion"), dict)
    result = {"status": "pending" if expected else "not-recorded", "disposition": None,
              "taskComplete": None, "eventId": None, "issues": [],
              "sourceIds": [], "acceptedClaimIds": []}
    attached = {event["event_id"]: event for event in events
                if event.get("kind") == "artifact" and event.get("agent_id") == "coordinator"}
    outcomes = sorted((item for item in artifacts if item.get("type") == "publication_inspection"
                       and item.get("event_id") in attached),
                      key=lambda item: attached[item["event_id"]]["sequence"])
    if not outcomes:
        return result
    artifact = outcomes[-1]
    result["eventId"] = artifact["event_id"]
    receipt = artifact.get("inspection")
    if not isinstance(receipt, dict):
        result["status"] = "invalid"
        return result
    disposition, complete = receipt.get("disposition"), receipt.get("taskComplete")
    issues, sources, claims = receipt.get("issues"), receipt.get("sourceRecordHashes"), receipt.get("assignedPaperAcceptedClaimIds")
    valid = (receipt.get("protocol") == "oopc-publication-inspection-receipt-v1"
             and disposition in ("completed", "inspected-no-additions", "unavailable-incomplete")
             and type(complete) is bool and complete == (disposition != "unavailable-incomplete")
             and isinstance(issues, list) and all(isinstance(item, str) for item in issues)
             and isinstance(sources, dict) and all(isinstance(key, str) for key in sources)
             and isinstance(claims, list) and all(isinstance(item, str) for item in claims)
             and (not complete or (not issues and bool(sources)))
             and (disposition != "completed" or bool(claims))
             and (disposition != "inspected-no-additions" or not claims))
    if not valid:
        result["status"] = "invalid"
        return result
    result.update(status="recorded", disposition=disposition, taskComplete=complete,
                  issues=list(issues), sourceIds=sorted(sources), acceptedClaimIds=list(claims))
    return result


def evaluation_summary(review):
    evaluation = review.get("evaluation")
    result = {"qualification": "not-recorded", "verdict": None,
              "reportedVerdict": None, "status": None, "policy": None, "scores": {},
              "coverageOutcomes": {}, "assessmentCounts": {"scientificClaims": None, "scientificSupportLinks": None}}
    if isinstance(evaluation, dict):
        qualified = evaluation.get("independentlySourceChecked") is True
        result.update(qualification="source-checked" if qualified else "unscorable",
                      status=evaluation.get("status"), policy=evaluation.get("evaluationPolicy"))
        if qualified and _is_verdict(evaluation.get("reviewVerdict")):
            result["verdict"] = evaluation["reviewVerdict"]
        if qualified:
            result["assessmentCounts"] = evaluation_denominators(evaluation)
            result["scores"] = {key: evaluation[key] for key in SCORE_FIELDS
                if type(evaluation.get(key)) in (int, float) and math.isfinite(evaluation[key])
                and 0 <= evaluation[key] <= 1}
            coverage = evaluation.get("taskCoverageChecks")
            if isinstance(coverage, dict):
                for item in coverage.values():
                    outcome = item.get("outcome") if isinstance(item, dict) else None
                    if isinstance(outcome, str) and outcome in {"supported-answer", "correctly-scoped-abstention",
                                   "missed-available-evidence", "unsupported-answer", "omitted"}:
                        counts = result["coverageOutcomes"]
                        counts[outcome] = counts.get(outcome, 0) + 1
        raw = evaluation.get("reviewerReportedVerdict", evaluation.get("reviewVerdict"))
        if _is_verdict(raw):
            result["reportedVerdict"] = raw
    elif _is_verdict(review.get("verdict")):
        # Older worker reviews lack the benchmark qualification contract.
        result.update(qualification="unqualified-review", reportedVerdict=review["verdict"])
    return result


def summarize_run(meta, events, artifacts, records):
    reviews = {event["event_id"]: event for event in events if event.get("kind") == "review"}
    attached_reviews = sorted((artifact for artifact in artifacts if artifact.get("event_id") in reviews),
                              key=lambda artifact: reviews[artifact["event_id"]]["sequence"])
    review = attached_reviews[-1] if attached_reviews else {}
    evaluation = evaluation_summary(review)
    evaluation["reviewCount"] = len(attached_reviews)
    evaluation["eventId"] = review.get("event_id")
    claims = {verdict: 0 for verdict in ("pass", "fail", "uncertain", "unclassified")}
    findings = review.get("findings", [])
    for finding in findings if isinstance(findings, list) else []:
        verdict = finding.get("verdict") if isinstance(finding, dict) else None
        claims[verdict if _is_verdict(verdict) else "unclassified"] += 1

    accesses = [event for event in events if event.get("kind") == "access" and event.get("status") == "ok"]
    returned = {rid for event in accesses for rid in event.get("result_ids", [])}
    index = {record["@id"]: record for record in records}
    recipes = {rid for rid in returned if index.get(rid, {}).get("@type") == "Recipe"}
    relationships = {rid for rid in returned if index.get(rid, {}).get("@type") == "Claim"}
    traversed = {rid for event in accesses for rid in event.get("traversed_edges", [])}
    deliveries = {rid for event in events if event.get("kind") == "delivery" for rid in event.get("result_ids", [])}
    citations = {rid for event in events if event.get("kind") == "artifact" for rid in event.get("result_ids", [])}
    attachments = [artifact for artifact in artifacts if artifact.get("type") == "external_evidence"]
    content = {}
    for attachment in attachments:
        for record in attachment.get("records", []):
            content[record["@id"]] = attachment.get("content", {}).get(record["@id"], {}).get("status", "unavailable")
    caps = meta.get("capabilities", {})
    if isinstance(caps, list):
        caps = {key: True for key in caps}
    capture = {key: caps.get(key) if type(caps.get(key)) is bool else None for key in
               ("graph_access", "explicit_traversal", "context_delivery", "full_context", "external_source_access", "direct_file_access")}
    capture.update(externalSourceCount=len(content), includedSourceCount=sum(value == "included" for value in content.values()),
                   missingSourceContentCount=sum(value != "included" for value in content.values()))
    task = meta.get("task") if isinstance(meta.get("task"), dict) else {}
    condition = task.get("experimentCondition") if isinstance(task.get("experimentCondition"), dict) else {}
    retrieval_condition = condition.get("retrievalCondition") if isinstance(condition.get("retrievalCondition"), dict) else {}
    return {"version": "inspector-summary-v1", "evaluation": evaluation, "claimFindings": claims,
            "publicationInspection": publication_inspection_summary(meta, events, artifacts),
            "retrieval": {"accessCalls": len(accesses), "returnedRecords": len(returned),
                          "returnedRelationships": len(relationships), "traversalCalls": sum(event.get("operation") == "traverse" for event in accesses),
                          "returnedProjections": sum(index.get(rid, {}).get("@type") in ("RecordFragment", "RecordProjection") for rid in returned),
                          "traversedRelationships": len(traversed),
                          "recipeLookupCalls": sum(event.get("operation") in ("get_recipes", "recipes") for event in accesses),
                          "returnedRecipes": len(recipes), "deliveredRecipes": len(recipes & deliveries), "citedRecipes": len(recipes & citations)},
            "capture": capture,
            # A mode name/date does not prove current-cohort membership.
            "condition": {"mode": task.get("mode"), "cohortStatus": "not-recorded",
                          "recorded": bool(condition), "adapterVersion": condition.get("adapterVersion"),
                          "retrievalProtocol": retrieval_condition.get("protocol"),
                          "evaluationPolicy": condition.get("evaluationPolicy"),
                          "releaseId": meta.get("release_id")}}


def read_run_summary(run, meta):
    """One consistent committed snapshot, opened without SQLite write access."""
    connection = sqlite_open((run.path / "trace.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        events = [json.loads(row[0]) for row in connection.execute("SELECT json FROM events ORDER BY sequence")]
        artifacts = [json.loads(row[0]) for row in connection.execute("SELECT json FROM artifacts ORDER BY rowid")]
        records = [json.loads(row[0]) for row in connection.execute("SELECT json FROM records")]
        return summarize_run(meta, events, artifacts, records)
    finally:
        sqlite_close(connection)
