"""One-off upkeep of the knowledge store before a study freeze. Nothing here runs in the loop.

The store holds the defects of the waves that wrote it before each fix landed. Each action reports what it would
change and changes the store only with `apply`, after copying the store to `.oopc/loop/backups/`:

- `audit`: the counts the pre-publication targets are judged by.
- `requeue`: findings left Needs checking because their reviewer could not open the source go back to review; a
  sampled Added finding goes back to Added with its spot check pending (P0-6).
- `excerpts`: Added and Reviewed findings with no excerpt, or one that shows no label, go to review, whose reviewer
  quotes the span: an Added one at its spot check, a Reviewed one checked again (P0-7). Excerpts this pass once picked
  from captured text by itself are withdrawn and reviewed the same way (a quarter of a sample quoted the wrong
  measurement).
- `titles`: every finding and note under its DOI's Crossref title (P0-8).
- `polymers`: findings with no polymer id get the one their own text, their question or their source's other
  findings agree on (P0-9); a polymer id a person approved, a blank included, is never changed.
- `duplicates`: findings the current duplicate rule would merge are merged into the best-reviewed one; the others'
  rows are kept in `merged`, and their ids still resolve (P0-10).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import knowledge, sources
from .util import now, read_json

# A reviewer's reason that says it could not read the source, not that the source was ambiguous. Read against all 429
# Needs-checking reasons in the store on 2026-10-14: 425 matched, no false positive, and none of the rejected ones.
ACCESS = re.compile(r"""(?ix)
    \b(?:HTTP\s*)?40[134]\b | \bforbidden\b
  | \b(?:could\s*not|couldn[’']t|cannot|can[’']t|wouldn[’']t|unable\s+to|failed\s+to|did\s+not)\s+
        (?:be\s+)?(?:open|read|access|extract|pars|fetch|retriev|load|download|inspect)\w*
  | \b(?:not|never)\s+(?:be\s+)?(?:opened|accessed|extracted|parsed|fetched|retrieved|loaded)\b
  | paywall | \blogin\b | \bsign[- ]in\b | subscription
  | \babstract[- ]only\b | \bonly\s+(?:the\s+|an?\s+)?(?:abstract|metadata)\b | \bhas\s+only\s+(?:the\s+)?abstract
  | \bcompressed\b | \bbinary\b | \bscanned\b | text\s+layer | image[- ]only | \bno\s+(?:readable|extractable)\s+text
  | \bunreadable\b | \bunparseable\b | \bgarbled\b
  | (?:browser|client|javascript|bot)[- ](?:challenge|check|verification) | browser\s+verification | captcha
  | redirect\s+loop | \bfirewall\b | \bblocked\b | blocking
  | timed\s+out | time-?out | too\s+large | size\s+limit
  | access\s+(?:errors?|failures?|blocking|was\s+blocked) | retrieval\s+(?:returned\s+errors|failures?)
  | \binaccessible\b | no\s+accessible\s+copy | not\s+accessible
  | returned\s+only\s+(?:the\s+)?(?:site\s+header|metadata|abstract) | no\s+preview\s+text
""")


def backup(root, label):
    """A consistent copy of the store before an upkeep change; returns its path."""
    target = knowledge.folder(root) / "backups" / ("%s-before-%s" % (now()[:19].replace(":", ""), label))
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    source, copy = sqlite3.connect(str(knowledge.database(root))), sqlite3.connect(str(target / "knowledge.sqlite"))
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    return target


def _queue(db, question_id):
    """Put a question's waiting findings in the review queue again; imported findings have no deposit, so one is made."""
    if not db.execute("UPDATE deposits SET review_status='pending', review_attempts=0, review_error=NULL "
                      "WHERE question_id=?", (question_id,)).rowcount:
        db.execute("INSERT INTO deposits (question_id, origin, engine, deposited_at, findings, notes, dropped, "
                   "review_status, review_attempts) VALUES (?, 'upkeep', '', ?, 0, 0, 0, 'pending', 0)",
                   (question_id, now()))


def _rows(root, where="1", args=()):
    with knowledge.connect(root) as db:
        return db.execute("SELECT * FROM findings WHERE " + where, args).fetchall()


def _detail(row):
    return json.loads(row["detail"]) if row["detail"] else {}


def access_uncertain(row):
    return row["status"] == knowledge.UNCERTAIN and bool(ACCESS.search(row["review_reason"] or ""))


# ---------------------------------------------------------------------------
# The audit

def audit(root):
    """The counts each store target is judged by."""
    rows = _rows(root)
    total = len(rows)
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    kept = [r for r in rows if r["status"] in (knowledge.ACCEPTED, knowledge.SUPPORTED)]
    missing = [r for r in kept if not (r["excerpt"] or "").strip()]
    no_label = [r for r in kept if (r["excerpt"] or "").strip() and knowledge.bare_excerpt(r["excerpt"], r["unit"])]
    with knowledge.connect(root) as db:
        merged = db.execute("SELECT COUNT(*) FROM merged").fetchone()[0]
    share = lambda n: round(n / total, 4) if total else None
    access = sum(access_uncertain(r) for r in rows)
    no_polymer = sum(not r["subject"] for r in rows)
    return {"findings": total, "byStatus": counts, "merged": merged,
            "accessUncertain": {"count": access, "share": share(access), "target": "under 2% of the store"},
            "excerpts": {"missing": len(missing), "bare": len(no_label),
                         "target": "every Added or Reviewed finding has an excerpt showing its value with its label"},
            "noPolymerId": {"count": no_polymer, "share": share(no_polymer), "target": "under 2%"},
            "duplicates": {"pairs": len(duplicate_groups(root, rows)[1]), "target": "no remaining pairs"}}


# ---------------------------------------------------------------------------
# P0-6: findings the reviewer could not read go back to review

def requeue(root, *, apply=False):
    rows = [r for r in _rows(root, "status=?", (knowledge.UNCERTAIN,)) if access_uncertain(r)]
    report = {"candidates": len(rows), "sampled": sum("spotCheck" in _detail(r) for r in rows),
              "questions": len({r["question_id"] for r in rows}), "applied": apply,
              "examples": [{"id": r["id"], "reason": (r["review_reason"] or "")[:200]} for r in rows[:10]]}
    if not apply or not rows:
        return report
    report["backup"] = str(backup(root, "requeue"))
    stamp = now()
    with knowledge.connect(root) as db:
        for row in rows:
            detail = _detail(row)
            previous = detail.setdefault("previousReviews", [])
            previous.append({"verdict": row["status"], "reason": row["review_reason"], "engine": row["reviewer_engine"],
                             "reviewedAt": row["reviewed_at"], "requeuedAt": stamp, "why": "source access"})
            # A sampled Added finding was Added before its spot check; it stays Added until it is checked again.
            status = knowledge.ACCEPTED if "spotCheck" in detail else knowledge.UNREVIEWED
            if status == knowledge.ACCEPTED:
                detail["spotCheck"] = "pending"
            db.execute("UPDATE findings SET status=?, detail=? WHERE id=?",
                       (status, json.dumps(detail, ensure_ascii=False), row["id"]))
        for question in {r["question_id"] for r in rows}:
            _queue(db, question)
    return report


# ---------------------------------------------------------------------------
# P0-7: excerpts that show the value with its label

def excerpts(root, *, apply=False):
    """Send findings whose excerpt is missing or shows no label to review, whose reviewer quotes the span from the
    source: an Added one at its spot check, a Reviewed one checked again (it keeps its review unless the second
    reviewer finds it unsupported). An excerpt this pass once picked from captured source text by itself is withdrawn
    (its former excerpt restored) and goes the same way: the independent review of 2026-10-14 found a quarter of a
    sample of them quoting another measurement (an Izod span for a Charpy value), so no excerpt is chosen without a
    reviewer."""
    picked = lambda row: "captured" in (_detail(row).get("excerptFrom") or {})
    rows = [r for r in _rows(root, "status IN (?, ?)", (knowledge.ACCEPTED, knowledge.SUPPORTED))
            if not (r["excerpt"] or "").strip() or knowledge.bare_excerpt(r["excerpt"], r["unit"]) or picked(r)]
    report = {"candidates": len(rows), "withdrawn": sum(map(picked, rows)),
              "sentToSpotCheck": sum(r["status"] == knowledge.ACCEPTED for r in rows),
              "sentToRecheck": sum(r["status"] == knowledge.SUPPORTED for r in rows), "applied": apply}
    if not apply or not rows:
        return report
    report["backup"] = str(backup(root, "excerpts"))
    stamp = now()
    with knowledge.connect(root) as db:
        for row in rows:
            changes = {"needsExcerpt": True, ("spotCheck" if row["status"] == knowledge.ACCEPTED else "recheck"): "pending"}
            if picked(row):
                filled = _detail(row)["excerptFrom"]
                changes.update(excerptFrom=None, excerptWithdrawn={"excerpt": row["excerpt"], "captured": filled["captured"],
                                                                   "filledAt": filled.get("at"), "at": stamp})
                db.execute("UPDATE findings SET excerpt=? WHERE id=?", (filled.get("was") or "", row["id"]))
            knowledge._set_detail(db, row["id"], **changes)
        for question in {r["question_id"] for r in rows}:
            _queue(db, question)
    return report


# ---------------------------------------------------------------------------
# P0-8: titles from DOI metadata

def import_metadata_cache(root, folder):
    """Copy Crossref responses another tool cached (one JSON file per DOI with `doi`, `status` and `message`)."""
    copied = 0
    for path in sorted(Path(folder).glob("*.json")):
        value = read_json(path)
        doi = sources.clean_doi(value.get("doi"))
        if doi and value.get("status") in (200, 404) and not sources._metadata_path(root, doi).exists():
            from .util import atomic_json
            atomic_json(sources._metadata_path(root, doi), value, private=True)
            copied += 1
    return copied


def titles(root, *, apply=False, cache=None, fetch=None):
    report = {"copiedFromCache": import_metadata_cache(root, cache) if cache else 0, "applied": apply}
    if not apply:
        rows = _rows(root)
        report["dois"] = len({sources.clean_doi(r["source_doi"]) or sources.doi_of(r["source_url"]) for r in rows} - {""})
        report["cached"] = sum(sources._metadata_path(root, d).exists() for d in {
            sources.clean_doi(r["source_doi"]) or sources.doi_of(r["source_url"]) for r in rows} - {""})
        return report
    report["backup"] = str(backup(root, "titles"))
    report.update(knowledge.apply_titles(root, fetch=fetch))
    return report


# ---------------------------------------------------------------------------
# P0-9: polymer ids

def _question_text(root, question_id):
    path = knowledge.folder(root) / "questions" / (question_id or "") / "question.json"
    try:
        return read_json(path).get("question", "") if path.exists() else ""
    except (OSError, ValueError):
        return ""


def file_under(root, row, question, peers):
    """`knowledge.file_subject`, and for a finding that names no polymer and whose question settles nothing, the one
    polymer every other finding from its source is filed under (`peers`)."""
    subject, rule = knowledge.file_subject(root, {"material": row["material"], "statement": row["statement"]}, question)
    if not subject and rule == "no polymer named" and len(peers) == 1:
        return next(iter(peers)), "same source"
    return subject, rule


def _approved(row):
    """A finding whose polymer id a person approved (`corrections`), an approved blank included: no automatic pass
    changes it again (independent review, 2026-10-14: a later pass re-filed six approved blanks)."""
    return (_detail(row).get("polymerFrom") or {}).get("rule") == "approved correction"


def polymers(root, *, apply=False):
    """File findings without a polymer id by `file_under`, and move a finding filed under a family to the member of it
    its own text names (polyethylene family to HDPE). A finding today's rules would file under an unrelated polymer is
    only listed (`toCheck`): a sample code ("PA-0" in a TPV paper) and a polymer's own coded samples ("TPU-25") read
    alike, so moving it is a person's call. An approved polymer id is never changed."""
    rows = [row for row in _rows(root) if not _approved(row)]
    by_source = {}
    for row in rows:
        if row["subject"]:
            by_source.setdefault(knowledge.source_key(row["source_doi"], row["source_url"]), set()).add(row["subject"])
    questions, changes, why, left, check = {}, {}, {}, {}, []
    for row in rows:
        if row["question_id"] not in questions:
            questions[row["question_id"]] = _question_text(root, row["question_id"])
        peers = by_source.get(knowledge.source_key(row["source_doi"], row["source_url"]), set()) \
            if not row["subject"] else set()
        subject, rule = file_under(root, row, questions[row["question_id"]], peers)
        if not row["subject"] and not subject:
            left[rule] = left.get(rule, 0) + 1
            continue
        if not subject or subject == row["subject"]:
            continue
        if row["subject"] and row["subject"] not in knowledge._ancestors(root, subject):
            check.append({"id": row["id"], "from": row["subject"], "to": subject, "rule": rule,
                          "material": row["material"]})
            continue
        kind = ("filed by " if not row["subject"] else "narrowed by ") + rule
        changes[row["id"]] = (subject, row["subject"], kind)
        why[kind] = why.get(kind, 0) + 1
    report = {"withoutId": sum(not r["subject"] for r in rows), "changes": len(changes), "byRule": why,
              "leftWithoutId": left, "applied": apply, "toCheck": check,
              "examples": [{"id": i, "from": old, "to": new, "rule": rule} for i, (new, old, rule) in changes.items()][:25]}
    if apply and changes:
        report["backup"] = str(backup(root, "polymers"))
        with knowledge.connect(root) as db:
            for identifier, (subject, old, rule) in changes.items():
                db.execute("UPDATE findings SET subject=? WHERE id=?", (subject, identifier))
                knowledge._set_detail(db, identifier, polymerFrom={"rule": rule, "was": old, "at": now()[:10]})
    return report


def disambiguate(root, *, apply=False, capture=False, fetch=None):
    """Findings whose material or statement uses a name the graph gives to unrelated polymers (PEI, PFA), settled from
    their question, their source's title and notes and its captured text, and written out (`knowledge.settle_names`).
    The rest go to review, whose reviewer writes the material out from the source: an Added finding waits for it, and a
    Reviewed one is checked again and keeps its review meanwhile."""
    rows = [r for r in _rows(root, "status != ?", (knowledge.UNSUPPORTED,))
            if knowledge.may_misread(root, (r["material"] or "") + "; " + (r["statement"] or ""))]
    with knowledge.connect(root) as db:
        notes = db.execute("SELECT doi, url, title, supports, conditions, excerpts FROM notes").fetchall()
    said = {}
    for note in notes:
        said.setdefault(knowledge.source_key(note["doi"], note["url"]), []).append(" ".join(
            [note["title"] or "", note["supports"] or "", note["conditions"] or "", *json.loads(note["excerpts"] or "[]")]))
    settled, unsettled = {}, {}
    for row in rows:
        source = {"title": row["source_title"], "url": row["source_url"], "doi": row["source_doi"]}
        kept = sources.captured(root, source) or (sources.capture(root, source, fetch=fetch) if capture else None)
        context = " ".join([_question_text(root, row["question_id"]), row["source_title"] or "",
                            *said.get(knowledge.source_key(row["source_doi"], row["source_url"]), []),
                            (kept or {}).get("text") or ""])
        finding, names = knowledge.settle_names(root, {"material": row["material"], "statement": row["statement"]}, context)
        if names:
            unsettled[row["id"]] = names
        elif finding.get("asWritten"):
            settled[row["id"]] = finding
    report = {"ambiguous": len(rows), "settled": len(settled), "toReview": len(unsettled), "applied": apply,
              "examples": [{"id": i, "material": f["material"]} for i, f in list(settled.items())[:10]]}
    if not apply or not rows:
        return report
    report["backup"] = str(backup(root, "disambiguate"))
    stamp = now()
    with knowledge.connect(root) as db:
        for identifier, finding in settled.items():
            row = db.execute("SELECT * FROM findings WHERE id=?", (identifier,)).fetchone()
            subject = row["subject"] if _approved(row) else knowledge.file_subject(root, finding)[0] or row["subject"]
            knowledge._set_detail(db, identifier, asWritten=finding.get("asWritten"), settledAt=stamp)
            db.execute("UPDATE findings SET material=?, statement=?, subject=? WHERE id=?",
                       (finding["material"], finding["statement"], subject, identifier))
            knowledge._reindex(db, identifier)
        for identifier, names in unsettled.items():
            row = db.execute("SELECT status, question_id FROM findings WHERE id=?", (identifier,)).fetchone()
            changes = {"ambiguous": [n["name"] for n in names], "reviewFlag": knowledge.ambiguity_flag(names)}
            if row["status"] == knowledge.ACCEPTED:  # Not used as Added while its name can be misread.
                db.execute("UPDATE findings SET status=? WHERE id=?", (knowledge.UNREVIEWED, identifier))
                changes["previousStatus"] = knowledge.ACCEPTED
            elif row["status"] in (knowledge.SUPPORTED, knowledge.UNCERTAIN):
                changes["recheck"] = "pending"
            knowledge._set_detail(db, identifier, **changes)
            _queue(db, row["question_id"])
    return report


def corrections(root, path, *, apply=False):
    """Approved corrections (P1-7): a JSON object of finding id to a graph polymer id ("" to leave it unfiled), or to
    {"polymer": id, "material": text, "by": who approved it} when the material label is rewritten too."""
    wanted = {i: v if isinstance(v, dict) else {"polymer": v} for i, v in read_json(path).items()}
    rows = {r["id"]: r for r in _rows(root)}
    known = set(knowledge._graph_families(root)[2])
    unknown = sorted(i for i in wanted if i not in rows)
    bad = sorted({v.get("polymer") for v in wanted.values()} - known - {"", None})
    if unknown or bad:
        raise ValueError("Not in the store: %s; not graph polymers: %s" % (", ".join(unknown) or "none", ", ".join(bad) or "none"))
    changes = {i: v for i, v in wanted.items()
               if rows[i]["subject"] != v.get("polymer", "") or (v.get("material") and v["material"] != rows[i]["material"])}
    report = {"corrections": len(wanted), "changes": len(changes), "applied": apply}
    if apply and changes:
        report["backup"] = str(backup(root, "polymer-corrections"))
        with knowledge.connect(root) as db:
            for identifier, value in changes.items():
                row = rows[identifier]
                material = " ".join((value.get("material") or row["material"] or "").split())[:knowledge.LIMITS["material"]]
                db.execute("UPDATE findings SET subject=?, material=? WHERE id=?",
                           (value.get("polymer", ""), material, identifier))
                written = dict(json.loads(row["detail"] or "{}").get("asWritten") or {})
                if material != row["material"]:
                    written.setdefault("material", row["material"])
                knowledge._set_detail(db, identifier, asWritten=written or None, polymerFrom={
                    "rule": "approved correction", "by": value.get("by", ""), "was": row["subject"], "at": now()[:10]})
                knowledge._reindex(db, identifier)
    return report


# ---------------------------------------------------------------------------
# P0-10: duplicates

RANK = {knowledge.SUPPORTED: 0, knowledge.ACCEPTED: 1, knowledge.UNCERTAIN: 2, knowledge.UNREVIEWED: 2}


def duplicate_groups(root, rows=None):
    """Groups of findings the current duplicate rule would have merged (same source, same fact), and the pairs found.
    Rejected findings are left out: one fact both supported and rejected is a disagreement to resolve, not a duplicate."""
    rows = [r for r in (rows if rows is not None else _rows(root)) if r["status"] != knowledge.UNSUPPORTED]
    by_source = {}
    for row in rows:
        key = knowledge.source_key(row["source_doi"], row["source_url"])
        if key:
            by_source.setdefault(key, []).append(row)
    parent, pairs = {}, []

    def top(i):
        while parent.get(i, i) != i:
            i = parent[i]
        return i
    for group in by_source.values():
        facts = [(row, knowledge._row_fact(row)) for row in group]
        for n, (a, fa) in enumerate(facts):
            for b, fb in facts[n + 1:]:
                if knowledge.same_fact(fa, fb):
                    pairs.append((a["id"], b["id"]))
                    parent[top(b["id"])] = top(a["id"])
    groups = {}
    by_id = {row["id"]: row for row in rows}
    for a, b in pairs:
        for i in (a, b):
            groups.setdefault(top(i), set()).add(i)
    # The one kept: the best reviewed, then one whose statement gives its value, then the oldest.
    says_value = lambda r: knowledge._numbers(r["value"]) <= knowledge._numbers(r["statement"])
    return [sorted((by_id[i] for i in g), key=lambda r: (RANK.get(r["status"], 3), not says_value(r),
                                                         r["created_at"] or "", r["id"]))
            for g in groups.values()], pairs


def duplicates(root, *, apply=False):
    groups, pairs = duplicate_groups(root)
    report = {"pairs": len(pairs), "groups": len(groups), "toMerge": sum(len(g) - 1 for g in groups), "applied": apply,
              "examples": [[{"id": r["id"], "status": r["status"], "statement": r["statement"][:160]} for r in g]
                           for g in groups[:8]]}
    if not apply or not groups:
        return report
    report["backup"] = str(backup(root, "duplicates"))
    stamp = now()
    with knowledge.connect(root) as db:
        for group in groups:
            keeper, others = group[0], group[1:]
            detail = _detail(keeper)
            detail.setdefault("mergedFrom", []).extend(
                {"id": r["id"], "questionId": r["question_id"], "status": r["status"], "producer": r["producer_engine"],
                 "reviewer": r["reviewer_engine"], "reason": r["review_reason"], "at": stamp} for r in others)
            if not (keeper["excerpt"] or "").strip():
                better = next((r["excerpt"] for r in others if (r["excerpt"] or "").strip()), "")
                if better:
                    db.execute("UPDATE findings SET excerpt=? WHERE id=?", (better, keeper["id"]))
            db.execute("UPDATE findings SET detail=? WHERE id=?", (json.dumps(detail, ensure_ascii=False), keeper["id"]))
            for row in others:
                db.execute("INSERT OR REPLACE INTO merged VALUES (?,?,?,?)",
                           (row["id"], keeper["id"], stamp, json.dumps(dict(row), ensure_ascii=False)))
                db.execute("DELETE FROM findings WHERE id=?", (row["id"],))
                db.execute("DELETE FROM findings_fts WHERE id=?", (row["id"],))
    return report


ACTIONS = {"audit": None, "requeue": requeue, "excerpts": excerpts, "titles": titles, "polymers": polymers,
           "disambiguate": disambiguate,
           "duplicates": duplicates}
