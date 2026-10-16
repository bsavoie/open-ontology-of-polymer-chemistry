"""One-time import of useful knowledge from the retired 0.11 workflow.

It only reads the legacy files under `.oopc/` and writes the new store under
`.oopc/loop/`. Nothing legacy is changed or deleted. What it brings over:

- **Reviewed findings**: proposals the 0.11 independent review admitted
  (`.oopc/admissions`, accepted), converted to simple findings with their source,
  locator and the reviewer's source-check note. Admissions without an openable
  source are skipped and listed.
- **Sources**: the Evidence records those answers cited, kept under their
  original ids so old answers still resolve their citations.
- **Source notes** from everyday questions that the old review did not reject.
- **Question history**: the question, answer, citations and limitations of each
  earlier Ask question, shown read-only in History.

Rejected proposals, retrieval recipes, evaluation panels, cohorts, traces and
campaign ledgers are not imported. Running it again adds nothing new.

Many 0.11 records kept the fact in structured context and linked Process or
Material entities, with only a label as text ("Reported P5-15 preparation").
`rewrite_statements` turns such labels into one plain sentence each: one engine
writes them from the original record only, any sentence with a number the record
does not contain is refused, and the other engine confirms each sentence says
nothing the record does not. The original label and both engines are kept in
the finding's detail; a refused sentence leaves the label unchanged.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import engines, knowledge
from .util import atomic_json, now, read_json

DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>)\]]+", re.I)
WOP = re.compile(r"wop-\d{6}")


def _legacy(root):
    return Path(root).resolve() / ".oopc"


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _flat(value, limit=1500):
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, "", "unknown", [], {}):
                continue
            parts.append("%s: %s" % (key, _flat(item, 300)))
        return "; ".join(parts)[:limit]
    if isinstance(value, list):
        return ", ".join(_flat(item, 200) for item in value)[:limit]
    return str(value)[:limit] if value is not None else ""


def _evidence_index(base):
    """Every Evidence record found in legacy results and deposit drafts, by id."""
    index = {}
    for path in base.glob("campaigns/*/*/result.json"):
        _collect(_load(path), index)
    for path in base.glob("campaigns/*/*/revisions/*/result.json"):
        _collect(_load(path), index)
    db_path = base / "knowledge" / "knowledge.sqlite"
    if db_path.exists():
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            for (text,) in db.execute("SELECT json FROM drafts WHERE type='Evidence'"):
                record = json.loads(text)
                index.setdefault(record["@id"], record)
        finally:
            db.close()
    return index


def _collect(result, index):
    if not isinstance(result, dict):
        return
    for record in result.get("evidenceRecords") or []:
        if isinstance(record, dict) and isinstance(record.get("@id"), str) and record.get("@type") == "Evidence":
            index.setdefault(record["@id"], record)


def _source(evidence):
    url = evidence.get("contentUrl") or evidence.get("url") or ""
    citation = str(evidence.get("citation") or evidence.get("title") or "")
    doi = DOI.search(str(evidence.get("doi") or "")) or DOI.search(citation) or DOI.search(url)
    return {"sourceTitle": citation[:500], "sourceUrl": str(url)[:1000], "sourceDoi": doi.group(0).rstrip(".,;") if doi else "",
            "locator": _flat(evidence.get("locator"), 500)}


def _task_of_records(base):
    """Record id -> the everyday question that deposited it."""
    mapping = {}
    db_path = base / "knowledge" / "knowledge.sqlite"
    if db_path.exists():
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            mapping = dict(db.execute("SELECT id, task_id FROM drafts"))
        finally:
            db.close()
    return mapping


def _graph_evidence(root, identifiers, index):
    """Seed-graph Evidence cited by legacy records, from the current release."""
    missing = [i for i in identifiers if isinstance(i, str) and i not in index]
    if not missing:
        return
    try:
        from .graph import Graph
        from .util import resolve_release
        graph = Graph(resolve_release(root), verify=False)
    except (ValueError, FileNotFoundError, KeyError):
        return
    for identifier in missing:
        try:
            record = graph.get(identifier)
        except KeyError:
            continue
        if record.get("@type") == "Evidence":
            index[identifier] = record


def admitted_findings(root):
    """(findings, skipped) converted from accepted 0.11 admissions."""
    base = _legacy(root)
    evidence = _evidence_index(base)
    tasks = _task_of_records(base)
    findings, skipped, seen = [], [], set()
    for path in sorted(base.glob("admissions/*.json")):
        admission = _load(path)
        if not isinstance(admission, dict) or admission.get("accepted") is not True:
            continue
        proposal_id = path.stem
        proposal = _load(base / "proposals" / (proposal_id + ".json")) or {}
        record = proposal.get("record") if isinstance(proposal.get("record"), dict) else {}
        if proposal.get("kind", "claim") != "claim" or record.get("@type") not in {"Claim", "Observation"}:
            continue  # Retrieval recipes and vocabulary were never scientific findings.
        record_id = record.get("@id")
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        receipt = _load(base / "reviews" / (proposal_id + ".json")) or {}
        context = record.get("context") if isinstance(record.get("context"), dict) else {}
        cited = [e.get("@id") if isinstance(e, dict) else e for e in record.get("evidence") or []]
        _graph_evidence(root, cited, evidence)
        sources = [evidence[e] for e in cited if isinstance(e, str) and e in evidence]
        source = next((_source(e) for e in sources if _source(e)["sourceUrl"] or _source(e)["sourceDoi"]), None)
        statement = record.get("claim") or record.get("text") or record.get("statement") or record.get("label") or ""
        if not source or not statement:
            skipped.append({"recordId": record_id, "reason": "no openable source" if statement else "no statement"})
            continue
        material = context.get("material") if isinstance(context.get("material"), str) else ""
        if not material or material.startswith(("material:", "wop-")):
            material = context.get("materialScope") or material
        checks = [c for c in receipt.get("sourceChecks") or [] if isinstance(c, dict) and c.get("evidenceId") in cited]
        reason = next((str(c.get("notes")) for c in checks if c.get("notes")), "")
        subjects = WOP.findall(json.dumps([record.get("subject"), record.get("object"), context.get("materialScope")]))
        value = context.get("originalValue") if context.get("originalValue") not in (None, "") else context.get("value")
        conditions = _flat(context.get("conditions"))
        if context.get("method"):
            conditions = (conditions + "; method: " if conditions else "method: ") + _flat(context["method"], 500)
        finding = knowledge.clean_finding({
            "statement": statement, "material": _flat(material, 500),
            "property": _flat(context.get("property") or context.get("measuredProperty") or record.get("property") or "", 300),
            "value": _flat(value, 200), "unit": _flat(context.get("units"), 100), "conditions": conditions,
            "subject": subjects[0] if subjects else "", "excerpt": _flat(record.get("excerpt") or "", 1200), **source})
        if finding is None:
            skipped.append({"recordId": record_id, "reason": "incomplete after conversion"})
            continue
        findings.append({"id": "finding:legacy-" + proposal_id[:16], "questionId": tasks.get(record_id) or "legacy",
                         "finding": finding,
                         "reason": ("Admitted by the 0.11 independent source review. " + reason)[:600],
                         "detail": {"legacyRecordId": record_id, "proposalId": proposal_id,
                                    "reviewId": admission.get("reviewId"), "evidence": cited}})
    return findings, skipped, evidence


def legacy_notes(root):
    base = _legacy(root)
    db_path = base / "knowledge" / "knowledge.sqlite"
    if not db_path.exists():
        return []
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT id, task_id, json FROM notes WHERE status != 'rejected'").fetchall()
    finally:
        db.close()
    notes = []
    for identifier, task_id, text in rows:
        value = json.loads(text)
        source = value.get("source") or {}
        note = knowledge.clean_note({"title": source.get("title"), "url": source.get("url"),
                                     "doi": source.get("doi"), "locator": value.get("locator"),
                                     "excerpts": value.get("excerpts"), "supports": value.get("supports"),
                                     "conditions": value.get("conditions")})
        if note:
            notes.append({"id": "note:legacy-" + identifier.split(":", 1)[-1], "questionId": task_id, "note": note})
    return notes


def legacy_questions(root):
    """Earlier Ask questions with their answers, read-only."""
    base = _legacy(root)
    questions = []
    for state_path in sorted(base.glob("campaigns/*/state.json")):
        state = _load(state_path) or {}
        for job in state.get("jobs", []):
            task = job.get("interactiveTask")
            if not isinstance(task, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(task.get("taskId", ""))):
                continue
            result = _load(state_path.parent / job["jobId"] / "result.json")
            answered = isinstance(result, dict) and isinstance(result.get("answer"), str)
            questions.append({"id": task["taskId"], "question": job.get("question", ""), "origin": "legacy",
                              "engine": task.get("runtime") or "codex", "budgetSeconds": task.get("budgetSeconds"),
                              "status": "completed" if answered else "failed", "submittedAt": task.get("submittedAt"),
                              "finishedAt": task.get("submittedAt"), "attempts": [],
                              "error": None if answered else {"reason": "crashed", "message": "Did not finish in 0.11"},
                              "legacy": {"campaignId": state.get("campaignId"), "protocol": task.get("protocol")},
                              "result": {"engine": task.get("runtime") or "codex", "usage": result.get("usage"),
                                         "observedTools": result.get("observedTools"),
                                         "agentSeconds": result.get("agentSeconds"),
                                         "answer": {"answer": result["answer"], "citations": result.get("citations") or [],
                                                    "limitations": result.get("limitations") or [],
                                                    "openQuestions": []}} if answered else None})
    return questions


def run(root, *, apply=False):
    findings, skipped, evidence = admitted_findings(root)
    notes = legacy_notes(root)
    questions = legacy_questions(root)
    cited = {c for q in questions if q.get("result") for c in q["result"]["answer"]["citations"]}
    cited |= {e for f in findings for e in f["detail"]["evidence"] if isinstance(e, str)}
    sources = []
    for identifier in sorted(cited):
        record = evidence.get(identifier)
        if record:
            source = _source(record)
            note = knowledge.clean_note({"title": source["sourceTitle"], "url": source["sourceUrl"],
                                         "doi": source["sourceDoi"], "locator": source["locator"],
                                         "supports": "Source cited by an earlier answer.", "excerpts": []})
            if note:
                sources.append({"id": identifier, "note": note})
    report = {"reviewedFindings": len(findings), "skippedAdmissions": skipped, "sourceNotes": len(notes),
              "citedSources": len(sources), "questions": len(questions),
              "answeredQuestions": sum(1 for q in questions if q["status"] == "completed"), "applied": apply}
    if not apply:
        return report
    root = Path(root).resolve()
    with knowledge.connect(root) as db:
        for item in findings:
            knowledge._insert_finding(db, item["id"], item["questionId"], "import", item["finding"],
                                      status=knowledge.SUPPORTED, producer_engine="legacy", created_at="2026-09-27",
                                      review_reason=item["reason"], reviewer_engine="legacy-review",
                                      reviewed_at="2026-09-27", detail=item["detail"])
        for item in notes + sources:
            knowledge._insert_note(db, item["id"], item.get("questionId") or "legacy", "import", item["note"],
                                   created_at="2026-09-27")
    from .ask import folder as questions_folder
    for question in questions:
        target = questions_folder(root) / question["id"]
        if (target / "question.json").exists():
            continue
        result = question.pop("result")
        atomic_json(target / "question.json", question, private=True)
        if result:
            atomic_json(target / "result.json", result, private=True)
    return report


# ----- readable statements for imported findings -----

REWRITE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["rewrites"], "properties": {
    "rewrites": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["id", "statement"],
                 "properties": {"id": {"type": "string"}, "statement": {"type": "string"}}}}}}
FAITHFUL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdicts"], "properties": {
    "verdicts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["id", "faithful", "reason"],
                 "properties": {"id": {"type": "string"}, "faithful": {"type": "boolean"}, "reason": {"type": "string"}}}}}}
REWRITE = """Each item below is a finding imported from an earlier version of a polymer knowledge base. Its
statement is only a label; the facts are in the original record (the claim, its linked Process and
Material entities, and the notes of the reviewer who checked it against the source).

Write one plain sentence per item that states the finding itself: the material, what was reported or
measured, the values and the key conditions, as a polymer scientist would read it. Use only facts
present in the item; do not add, round, convert or infer anything, and keep stated limits (for
example "unknown" temperature, or "in this article only") when they matter to the meaning. Name the
authors if the record does. At most about 60 words. Return one rewrite per id.

Items:
"""
FAITHFUL = """Each item below gives an original record and a proposed one-sentence statement of it. Judge only
whether the statement is faithful to the record: every fact in it (material, values, units,
conditions, direction of an effect, scope) must be present in the record, and it must not overstate
the record's scope. Missing detail is acceptable; anything added, changed or generalised is not.
Return one verdict per id with a short reason.

Items:
"""
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def label_like(statement, value=""):
    """A statement that names a finding rather than stating it: no closing full stop, or it leaves out the finding's
    value ("CA2 fitted Langmuir capacity."), or, with no value given, it has no number but years and section, table or
    figure references."""
    if not statement.rstrip().endswith((".", "!", "?")):
        return True
    if _numbers(value or ""):
        return not _numbers(value) & _numbers(statement)
    text = re.sub(r"\b(?:section|sect|table|fig|figure|eq|page|p)\.?\s*[\dS][\d.]*", " ", statement, flags=re.I)
    return not re.search(r"\d", re.sub(r"\b(?:19|20)\d\d\b", " ", text))


def _original(root, detail):
    base = _legacy(root)
    proposal = _load(base / "proposals" / (detail.get("proposalId", "") + ".json")) or {}
    receipt = _load(base / "reviews" / (detail.get("proposalId", "") + ".json")) or {}
    return {"claim": proposal.get("record"), "entities": proposal.get("entities") or [],
            "reviewerNotes": [c.get("notes") for c in receipt.get("sourceChecks") or []
                              if isinstance(c, dict) and c.get("notes")]}


def _numbers(text):
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n
            for n in NUMBER.findall(text)}


def rewrite_statements(root, *, writer="claude-code", checker="codex", runner=None, apply=False, timeout=900):
    """Rewrite label-like statements of imported findings. Returns what changed and what was refused."""
    run = runner or engines.run_session
    root = Path(root).resolve()
    with knowledge.connect(root) as db:
        rows = db.execute("SELECT id, statement, value, source_title, detail FROM findings WHERE origin='import'").fetchall()
    items = []
    for identifier, statement, value, title, detail in rows:
        detail = json.loads(detail or "{}")
        if label_like(statement, value) and "originalStatement" not in detail:
            items.append({"id": identifier, "label": statement, "source": title, **_original(root, detail)})
    report = {"candidates": len(items), "rewritten": [], "refused": [], "applied": apply}
    if not items:
        return report
    written = run(writer, REWRITE + json.dumps(items, ensure_ascii=False, indent=1), REWRITE_SCHEMA,
                  tools=None, web=False, timeout=timeout)
    proposed = {r["id"]: r["statement"].strip() for r in written["answer"].get("rewrites") or []
                if isinstance(r, dict) and isinstance(r.get("statement"), str) and r["statement"].strip()}
    by_id = {item["id"]: item for item in items}
    checkable = []
    for identifier, statement in proposed.items():
        item = by_id.get(identifier)
        if item is None:
            continue
        extra = _numbers(statement) - _numbers(json.dumps(item, ensure_ascii=False))
        if extra:
            report["refused"].append({"id": identifier, "statement": statement,
                                      "reason": "numbers not in the record: " + ", ".join(sorted(extra))})
        else:
            checkable.append({"id": identifier, "record": item, "statement": statement})
    report["refused"] += [{"id": i, "reason": "no rewrite returned"} for i in by_id if i not in proposed]
    verdicts = {}
    if checkable:
        checked = run(checker, FAITHFUL + json.dumps(checkable, ensure_ascii=False, indent=1), FAITHFUL_SCHEMA,
                      tools=None, web=False, timeout=timeout)
        verdicts = {v["id"]: v for v in checked["answer"].get("verdicts") or [] if isinstance(v, dict)}
    for item in checkable:
        verdict = verdicts.get(item["id"])
        if not verdict or verdict.get("faithful") is not True:
            report["refused"].append({"id": item["id"], "statement": item["statement"],
                                      "reason": (verdict or {}).get("reason") or "not confirmed faithful"})
            continue
        report["rewritten"].append({"id": item["id"], "from": item["record"]["label"], "to": item["statement"],
                                    "check": verdict.get("reason", "")})
    if apply and report["rewritten"]:
        stamp = now()
        with knowledge.connect(root) as db:
            for change in report["rewritten"]:
                row = db.execute("SELECT * FROM findings WHERE id=?", (change["id"],)).fetchone()
                detail = dict(json.loads(row["detail"] or "{}"), originalStatement=change["from"], statementRewrite={
                    "at": stamp, "writer": written["engine"], "checker": checked["engine"], "check": change["check"]})
                db.execute("UPDATE findings SET statement=?, detail=? WHERE id=?",
                           (change["to"], json.dumps(detail, ensure_ascii=False), change["id"]))
                db.execute("DELETE FROM findings_fts WHERE id=?", (change["id"],))
                text = dict(row, statement=change["to"], sourceTitle=row["source_title"])
                db.execute("INSERT INTO findings_fts VALUES (?,?)", (change["id"], knowledge._finding_text(text)))
    return report
