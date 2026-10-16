"""Durable, model-neutral evidence-access events and offline replay."""
import copy
from contextlib import contextmanager
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from .util import (atomic_bytes, atomic_json, canonical, digest, locked, now, private_sqlite, read_json, safe_name,
                   sqlite_close, sqlite_open, walk_records)

# Run-lock holders do bounded work (SQLite waits are capped at 30 s), so a wait
# this long is a stuck holder; fail with a named lock rather than hang.
RUN_LOCK_TIMEOUT = 300


def _citation_id(value):
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        for key in ("record_id", "source_id", "claim_id", "@id"):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
    raise ValueError("Citation requires a record identifier")


def _validate_source_attachment(payload):
    records, content = payload.get("records"), payload.get("content")
    if not isinstance(records, list) or not all(isinstance(r, dict) and isinstance(r.get("@id"), str) and
            r.get("@type") in ("Evidence", "Document") for r in records):
        raise ValueError("Invalid external evidence records")
    ids = [r["@id"] for r in records]
    if len(set(ids)) != len(ids) or not isinstance(content, dict) or set(content) != set(ids):
        raise ValueError("Every attached source needs explicit content availability")
    checks = payload.get("source_checks")
    if not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks):
        raise ValueError("Invalid source inspection receipts")
    if payload.get("citations") or payload.get("claims") or not isinstance(payload.get("capture_note"), str):
        raise ValueError("Source attachment must remain separate from answer claims and citations")
    for item in content.values():
        if not isinstance(item, dict):
            raise ValueError("Invalid source content record")
        if item.get("status") == "included":
            if not isinstance(item.get("text"), str) or not item.get("permission_basis") or digest(item["text"].encode("utf-8")) != item.get("sha256"):
                raise ValueError("Invalid attached source content checksum or permission basis")
        elif item.get("status") not in ("excluded", "unavailable") or not item.get("reason") or "text" in item:
            raise ValueError("Invalid external source content gap")


class TraceStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / ".oopc" / "runs"

    def create(self, release, title="Polymer research task", capabilities=None, task=None):
        manifest = read_json(Path(release) / "manifest.json")
        run_id = "run-" + uuid.uuid4().hex
        directory = self.path / run_id
        directory.mkdir(parents=True, mode=0o700)
        (directory / "payloads").mkdir(mode=0o700)
        caps = {"graph_access": True, "explicit_traversal": True,
                "context_delivery": False, "full_context": False, "citations": True,
                "external_source_access": False, "direct_file_access": False}
        caps.update(capabilities or {})
        atomic_json(directory / "run.json", {
            "trace_version": "oopc-trace-v1", "run_id": run_id, "title": title,
            "task": task or {}, "status": "running", "created_at": now(),
            "release_id": manifest["release_id"], "retrieval_index_version": manifest.get("index_version", "unreported"), "release_checksum": digest((Path(release)/"manifest.json").read_bytes()),
            "release_path": str(Path(release).resolve()), "capabilities": caps,
            "agents": [], "last_sequence": 0, "private": True,
        }, private=True)
        atomic_json(directory / "ontology.json", read_json(Path(release)/"ontology.json"), private=True)
        run = self.run(run_id)
        with run.db() as db:
            db.executescript("""
                CREATE TABLE events(sequence INTEGER PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,json TEXT NOT NULL);
                CREATE TABLE records(id TEXT PRIMARY KEY,json TEXT NOT NULL);
                CREATE TABLE artifacts(id TEXT PRIMARY KEY,json TEXT NOT NULL);
            """)
        return run

    def run(self, run_id):
        path = self.path / safe_name(run_id)
        if not (path / "run.json").exists():
            raise KeyError("Run not found")
        return Run(path)

    def list(self):
        result = []
        for path in self.path.glob("*/run.json"):
            meta = Run(path.parent).meta()
            meta.pop("release_path", None)
            result.append(meta)
        return sorted(result, key=lambda r: r["created_at"], reverse=True)


class Run:
    def __init__(self, path):
        self.path = Path(path)

    def meta(self):
        meta = read_json(self.path / "run.json")
        # The committed event index is authoritative. A process may exit after
        # its transaction commits and before the separate metadata write. Repair
        # this derived view in memory; reading a trace never rewrites its events.
        with self.db() as db:
            db.execute("BEGIN")
            last = db.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0]
            if meta.get("last_sequence") != last:
                events = [json.loads(row[0]) for row in db.execute("SELECT json FROM events ORDER BY sequence")]
                meta["last_sequence"] = last
                meta["agents"] = list(dict.fromkeys(event["agent_id"] for event in events))
                if events:
                    meta["updated_at"] = events[-1]["timestamp"]
                if any(event["kind"] == "delivery" for event in events):
                    meta.setdefault("capabilities", {})["context_delivery"] = True
        return meta

    @contextmanager
    def db(self):
        db = sqlite_open(private_sqlite(self.path / "trace.sqlite"), timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            sqlite_close(db)

    def _repair_journal(self, db):
        journal = self.path / "events.jsonl"
        rows = db.execute("SELECT json FROM events ORDER BY sequence").fetchall()
        expected = b"".join(row[0].encode("utf-8") + b"\n" for row in rows)
        if not journal.exists() or journal.read_bytes() != expected:
            atomic_bytes(journal, expected, private=True)

    def record(self, operation, request, payload, agent_id="agent", status="ok", kind="access",
               traversed_edges=None, paths=None, duration_ms=0, parent_event_id=None, result_ids=None):
        if kind not in ("access", "delivery", "artifact", "review", "reuse", "candidate", "lifecycle"):
            raise ValueError("Unknown trace event kind")
        if kind == "access" and result_ids is not None:
            returned_ids = {record["@id"] for record in walk_records(payload)}
            if set(result_ids) != returned_ids:
                raise ValueError("Access result IDs must identify exactly the returned records")
        event_id = "evt-" + uuid.uuid4().hex
        if isinstance(payload, dict):
            payload["_access" if kind == "access" else "_recording"] = {"run_id": self.path.name, "event_id": event_id}
        content = canonical(payload)
        payload_hash = digest(content)
        records = list(walk_records(payload))
        ids = list(dict.fromkeys(result_ids if result_ids is not None else [r["@id"] for r in records]))
        with locked(self.path / ".lock", timeout=RUN_LOCK_TIMEOUT):
            meta = self.meta()
            if meta.get("imported"):
                raise ValueError("Imported replay is immutable")
            if meta["status"] != "running" and kind == "access":
                raise ValueError("Cannot append access to a finished run")
            with self.db() as db:
                self._repair_journal(db)
                if parent_event_id and not db.execute("SELECT 1 FROM events WHERE event_id=?", (parent_event_id,)).fetchone():
                    raise ValueError("Causal parent must belong to the same run")
                sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events").fetchone()[0]
                event = {"trace_version": "oopc-trace-v1", "run_id": meta["run_id"],
                         "trace_id":digest(meta["run_id"])[:32], "operation_id":"op-"+uuid.uuid4().hex,
                         "event_id": event_id, "sequence": sequence, "timestamp": now(),
                         "agent_id": agent_id, "span_id": uuid.uuid4().hex[:16],
                         "parent_event_id": parent_event_id, "release_id": meta["release_id"],
                         "retrieval_index_version": meta.get("retrieval_index_version", "unreported"), "operation": operation,
                         "kind": kind, "status": status, "request": copy.deepcopy(request),
                         "result_ids": ids, "traversed_edges": traversed_edges or [], "paths": paths or [],
                         "payload_hash": payload_hash, "duration_ms": round(duration_ms, 3),
                         "truncated": bool(payload.get("truncated", False)) if isinstance(payload, dict) else False}
                if isinstance(payload,dict):
                    event["pagination"] = {key:payload[key] for key in ("limit","offset","total","truncated") if key in payload}
                    if kind == "artifact" and payload.get("type") == "external_evidence":
                        event["artifact_type"] = "external_evidence"
                if operation != "traverse" and (traversed_edges or paths):
                    raise ValueError("Only explicit traversal operations can record traversed edges")
                if kind in ("artifact", "review", "reuse", "candidate") and isinstance(payload, dict) and payload.get("id"):
                    if db.execute("SELECT 1 FROM artifacts WHERE id=?", (payload["id"],)).fetchone():
                        raise ValueError("Artifact identifier already exists")
                atomic_bytes(self.path / "payloads" / (payload_hash + ".json"), content, private=True)
                for rec in records if kind == "access" else []:
                    snapshot = copy.deepcopy(rec)
                    snapshot.pop("_access", None)
                    snapshot.pop("release_id", None)
                    old = db.execute("SELECT json FROM records WHERE id=?", (snapshot["@id"],)).fetchone()
                    serialized = canonical(snapshot).decode()
                    if old and old[0] != serialized:
                        raise ValueError("Record changed within pinned run: " + snapshot["@id"])
                    db.execute("INSERT OR IGNORE INTO records VALUES (?,?)", (snapshot["@id"], serialized))
                if kind in ("artifact", "review", "reuse", "candidate") and isinstance(payload, dict) and payload.get("id"):
                    artifact = copy.deepcopy(payload)
                    artifact["event_id"] = event_id
                    db.execute("INSERT INTO artifacts VALUES (?,?)", (artifact["id"], canonical(artifact).decode()))
                serialized = canonical(event).decode()
                db.execute("INSERT INTO events VALUES (?,?,?)", (sequence, event_id, serialized))
                db.commit()
                with open(self.path / "events.jsonl", "ab") as handle:
                    handle.write(serialized.encode("utf-8") + b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            if kind == "delivery":
                meta["capabilities"]["context_delivery"] = True
            meta["last_sequence"] = sequence
            meta["updated_at"] = event["timestamp"]
            if agent_id not in meta["agents"]:
                meta["agents"].append(agent_id)
            atomic_json(self.path / "run.json", meta, private=True)
        return event

    def events(self, after=0):
        with self.db() as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT json FROM events WHERE sequence>? ORDER BY sequence", (max(0,int(after)),)).fetchall()
            last = db.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0]
        return {"events": [json.loads(r[0]) for r in rows], "last_sequence": last}

    def payload(self, value):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Invalid payload checksum")
        content = (self.path / "payloads" / (value + ".json")).read_bytes()
        if digest(content) != value:
            raise ValueError("Payload checksum mismatch")
        return json.loads(content)

    def delivery(self, event_id, record_ids, model_call_id, representation="content", agent_id="agent"):
        if not isinstance(model_call_id, str) or not model_call_id.strip():
            raise ValueError("Context delivery requires a model call identifier")
        if representation not in ("content", "reference", "summary"):
            raise ValueError("Invalid representation")
        source = next((e for e in self.events()["events"] if e["event_id"] == event_id), None)
        if not source or source["kind"] != "access":
            raise ValueError("Delivery must reference an access event")
        if not set(record_ids).issubset(source["result_ids"]):
            raise ValueError("Delivery cannot claim records absent from the returned payload")
        event = self.record("context_delivery", {"source_event_id": event_id, "model_call_id": model_call_id,
                            "representation": representation}, {"record_ids": record_ids}, kind="delivery",
                            result_ids=record_ids, agent_id=agent_id, parent_event_id=event_id)
        return event

    def artifact(self, artifact, agent_id="agent", kind="artifact"):
        if kind not in ("artifact", "review", "reuse", "candidate"):
            raise ValueError("Invalid artifact kind")
        artifact = copy.deepcopy(artifact)
        if artifact.get("type") == "external_evidence":
            if kind != "artifact":
                raise ValueError("External source attachments are neither reviews nor graph accesses")
            _validate_source_attachment(artifact)
        artifact.setdefault("id", "artifact-" + uuid.uuid4().hex)
        citations = list(artifact.get("citations", []))
        for claim in artifact.get("claims", []):
            citations.extend(claim.get("citations", []))
        ids = list(dict.fromkeys(_citation_id(c) for c in citations))
        if kind == "review":
            ids = list(dict.fromkeys(_citation_id(c) for finding in artifact.get("findings", [])
                                    if finding.get("verdict") == "pass" for c in finding.get("citations", [])))
        elif kind == "reuse":
            ids = list(artifact.get("supported_ids", [])) if artifact.get("passed") is True else []
        elif kind == "candidate":
            ids = [r["@id"] for r in artifact.get("records", [])]
        with self.db() as db:
            observed = {r[0] for r in db.execute("SELECT id FROM records")}
            artifact["unobserved_citations"] = [i for i in ids if i not in observed]
        event = self.record("attach_" + kind, {}, artifact, kind=kind, agent_id=agent_id, result_ids=ids)
        artifact["event_id"] = event["event_id"]
        return artifact

    def external_evidence(self, records, source_checks=None, agent_id="coordinator",
                          title="External source evidence", content=None):
        """Attach source metadata/receipts without asserting an observed retrieval.

        ``content`` optionally maps evidence IDs to an included UTF-8 text payload
        (with permission_basis), or an excluded/unavailable gap (with reason).
        Metadata, receipts and permitted content survive export unchanged. They
        never enter the pinned graph's returned-record index. Source checks are
        coordinator/worker attestations, not trace evidence of a browser access.
        """
        if not isinstance(records, list) or not all(isinstance(r, dict) and r.get("@id") and
                r.get("@type") in ("Evidence", "Document") for r in records):
            raise ValueError("External evidence requires identified Evidence or Document records")
        if len({r["@id"] for r in records}) != len(records):
            raise ValueError("Duplicate external evidence identity")
        checks = source_checks if source_checks is not None else []
        if not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks):
            raise ValueError("Source checks must be an array of recorded inspection receipts")
        content = copy.deepcopy(content or {})
        if not isinstance(content, dict) or set(content)-{r["@id"] for r in records}:
            raise ValueError("Captured source content must refer to an attached record")
        for record in records:
            item = content.setdefault(record["@id"], {"status":"unavailable",
                "reason":"Source content was not captured by the trace adapter; only metadata and any inspection receipts are attached."})
            if not isinstance(item, dict) or item.get("status") not in ("included", "excluded", "unavailable"):
                raise ValueError("Source content needs an explicit availability status")
            if item["status"] == "included":
                if not isinstance(item.get("text"), str) or not item.get("permission_basis"):
                    raise ValueError("Included source text requires text and a redistribution permission basis")
                checksum = digest(item["text"].encode("utf-8"))
                if item.get("sha256", checksum) != checksum:
                    raise ValueError("Captured source content checksum mismatch")
                item.update(sha256=checksum, media_type=item.get("media_type", "text/plain; charset=utf-8"))
            elif not item.get("reason") or "text" in item:
                raise ValueError("Excluded or unavailable content needs a reason and cannot contain text")
        return self.artifact({"title":title, "type":"external_evidence", "records":records,
                              "source_checks":checks, "content":content,
                              "capture_note":"Attached metadata and inspection attestations. The adapter did not observe the external source access or delivery into a model request."},
                             agent_id=agent_id)

    def citation(self, record_id, event_id=None, sequence=None, agent_id=None):
        """Resolve a citation to observed access and separately attached evidence.

        A citation/review/candidate event is never an access event. Resolution
        stops at the citing event, so a later retrieval cannot repair a historical
        capture gap. Repeated accesses remain distinct in ``access_events``.
        """
        events = self.events()["events"]
        bound = int(sequence) if sequence is not None else len(events)
        requested = next((e for e in events if e["event_id"] == event_id), None)
        if event_id and requested is None:
            raise KeyError("Citation event does not belong to this run")
        if requested:
            bound = min(bound, requested["sequence"])
        visible = [e for e in events if e["sequence"] <= bound and (not agent_id or e["agent_id"] == agent_id)]
        accesses = [e for e in visible if e["kind"] == "access" and e["status"] == "ok" and record_id in e["result_ids"]]
        access = next((e for e in accesses if e["event_id"] == event_id), None) or (accesses[-1] if accesses else None)
        record = next((r for r in walk_records(self.payload(access["payload_hash"])) if r["@id"] == record_id), None) if access else None
        attachments, findings = [], []
        for event in visible:
            if event["kind"] not in ("artifact", "review"):
                continue
            payload = self.payload(event["payload_hash"])
            if payload.get("type") == "external_evidence":
                for attached in payload.get("records", []):
                    if attached["@id"] == record_id:
                        checks = [c for c in payload.get("source_checks", []) if
                            record_id in (c.get("evidenceId"), c.get("evidence_id"), c.get("record_id"), c.get("@id")) or
                            any(c.get(k) and c.get(k) in (attached.get("url"), attached.get("contentUrl")) for k in ("url", "contentUrl", "accessUrl"))]
                        attachments.append({"event_id":event["event_id"], "sequence":event["sequence"],
                            "agent_id":event["agent_id"], "payload_hash":event["payload_hash"], "record":attached,
                            "source_checks":checks, "content":payload["content"][record_id], "capture_note":payload["capture_note"]})
            if event["kind"] == "review":
                findings.extend(dict(f, event_id=event["event_id"]) for f in payload.get("findings", []) if record_id in [_citation_id(c) for c in f.get("citations", [])])
        return {"record_id":record_id, "record":record, "access_event":access, "access_events":accesses,
                "attachments":attachments, "findings":findings,
                "capture_gap":None if access else "No successful instrumented access returned this record before the cited event. Source attachments and reviewer receipts do not establish an observed retrieval.",
                "sequence":bound, "release_id":self.meta()["release_id"]}

    def artifacts(self):
        with self.db() as db:
            return {"artifacts": [json.loads(row[0]) for row in db.execute("SELECT json FROM artifacts ORDER BY rowid")]}

    def finish(self, status="completed"):
        if status not in ("completed", "failed", "cancelled", "paused"):
            raise ValueError("Invalid run status")
        with locked(self.path / ".lock", timeout=RUN_LOCK_TIMEOUT):
            meta = self.meta()
            if meta.get("imported"):
                raise ValueError("Imported replay is immutable")
            meta["status"] = status
            meta["finished_at"] = now()
            atomic_json(self.path / "run.json", meta, private=True)
        return meta

    def graph(self, sequence=None, cumulative=True, agent_id=None):
        events = self.events()["events"]
        if sequence is None:
            sequence = events[-1]["sequence"] if events else 0
        selected = [e for e in events if (e["sequence"] <= int(sequence) if cumulative else e["sequence"] == int(sequence))
                    and (not agent_id or e["agent_id"] == agent_id)]
        highlights = {key: [] for key in ("returned", "traversed", "cited", "reviewer_supported", "reuse_tested", "candidates", "delivered")}
        included = set()
        candidate_snapshot = {}
        for event in selected:
            kind = event["kind"]
            if kind == "candidate":
                proposals = list(walk_records(self.payload(event["payload_hash"])))
                overlay_ids = {r["@id"]: "candidate:" + event["event_id"] + ":" + r["@id"] for r in proposals}
                for record in proposals:
                    overlay = copy.deepcopy(record)
                    overlay["original_record_id"] = record["@id"]
                    overlay["@id"] = overlay_ids[record["@id"]]
                    overlay["status"] = "candidate"
                    overlay["candidate_event_id"] = event["event_id"]
                    if overlay["@type"] == "Claim":
                        for endpoint in ("subject", "object"):
                            overlay[endpoint] = overlay_ids.get(overlay[endpoint], overlay[endpoint])
                    candidate_snapshot[overlay["@id"]] = overlay
                    included.add(overlay["@id"])
                    highlights["candidates"].append(overlay["@id"])
                continue
            included.update(event["result_ids"])
            included.update(event["traversed_edges"])
            if kind == "access":
                highlights["returned"].extend(event["result_ids"])
                highlights["traversed"].extend(event["traversed_edges"])
            elif kind == "delivery":
                highlights["delivered"].extend(event["result_ids"])
            elif kind == "artifact":
                highlights["cited"].extend(event["result_ids"])
            elif kind in ("review", "reuse"):
                key = {"review":"reviewer_supported", "reuse":"reuse_tested"}[kind]
                highlights[key].extend(event["result_ids"])
        # Reconstruct only actually accessed records in this time/agent scope.
        # Proposal payloads are isolated overlays and never revise the pinned data.
        snapshot = {}
        for event in events:
            if event["kind"] == "access" and event["sequence"] <= int(sequence) and (not agent_id or event["agent_id"] == agent_id):
                for rec in walk_records(self.payload(event["payload_hash"])):
                    snapshot[rec["@id"]] = rec
        # An explicit adapter-confirmed handoff may deliver another agent's
        # evidence. Reveal only those IDs, never the rest of that agent's context.
        by_event = {event["event_id"]: event for event in events}
        for event in selected:
            if event["kind"] == "delivery":
                source = by_event.get(event.get("request", {}).get("source_event_id"))
                if source:
                    for record in walk_records(self.payload(source["payload_hash"])):
                        if record["@id"] in event["result_ids"]:
                            snapshot[record["@id"]] = record
        snapshot.update(candidate_snapshot)
        # Include only returned assertion edges, never all edges induced by returned nodes.
        edges = [snapshot[i] for i in sorted(included) if i in snapshot and snapshot[i]["@type"] == "Claim"]
        endpoint_ids = set()
        for edge in edges:
            endpoint_ids.update((edge["subject"], edge["object"]))
        included.update(endpoint_ids)
        nodes = []
        for rid in sorted(included):
            # Assertions are themselves addressable entities. A supportedBy or
            # usesEvidence edge can point to one, so expose its actual payload
            # as a node as well as its edge when that endpoint is needed. The
            # viewer separates display IDs; canonical record IDs stay intact.
            # No synthetic scientific link joins the two representations.
            if rid in snapshot and snapshot[rid]["@type"] == "Claim" and rid not in endpoint_ids:
                continue
            nodes.append(snapshot.get(rid, {"@id": rid, "@type": "Unobserved", "label": rid,
                                           "status": "unobserved", "capture_note": "Referenced endpoint; record payload was not returned."}))
        return {"nodes": nodes, "edges": edges, "highlights": {k: list(dict.fromkeys(v)) for k,v in highlights.items()},
                "sequence": sequence, "release_id": self.meta()["release_id"], "truncated": False}

    def export(self, output):
        """Explicit private replay export. It is never included by the release builder."""
        output = Path(output)
        if output.exists():
            raise FileExistsError(output)
        with locked(self.path / ".lock", timeout=RUN_LOCK_TIMEOUT):
            event_snapshot = self.events()["events"]
            meta = self.meta()
            meta.pop("release_path", None)
            meta["export_notice"] = "Private task bundle. Review task text and evidence rights before sharing. No source documents are fetched or added."
            files = {"run.json": canonical(meta), "ontology.json": (self.path/"ontology.json").read_bytes(),
                     "events.jsonl": b"".join(canonical(e)+b"\n" for e in event_snapshot),
                     "artifacts.json": canonical(self.artifacts())}
            with self.db() as db:
                files["records.jsonl"] = b"".join(row[0].encode()+b"\n" for row in db.execute("SELECT json FROM records ORDER BY id"))
            for event in event_snapshot:
                name = "payloads/" + event["payload_hash"] + ".json"
                self.payload(event["payload_hash"])
                files[name] = (self.path/name).read_bytes()
        files["manifest.json"] = canonical({"format":"oopc-replay-v1", "private":True,
            "release_id":meta["release_id"], "files":{name:digest(data) for name,data in files.items()}})
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name("."+output.name+".tmp-"+uuid.uuid4().hex)
        try:
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items():
                    archive.writestr(name, data)
            os.chmod(temp, 0o600)
            os.replace(temp, output)
        finally:
            if temp.exists():
                temp.unlink()
        return {"path":str(output), "run_id":meta["run_id"], "private":True, "files":len(files)}


def import_replay(bundle, store):
    """Check hashes and replay semantics before atomically creating a local replay."""
    with zipfile.ZipFile(bundle) as archive:
        if sum(i.file_size for i in archive.infolist()) > 200_000_000:
            raise ValueError("Replay exceeds the 200 MB import limit")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate replay member")
        files = {name: archive.read(name) for name in names}
    required = {"run.json", "ontology.json", "events.jsonl", "artifacts.json", "records.jsonl", "manifest.json"}
    if not required.issubset(files):
        raise ValueError("Incomplete replay archive")
    manifest = json.loads(files["manifest.json"])
    if manifest.get("format") != "oopc-replay-v1" or set(manifest.get("files", {})) != set(files)-{"manifest.json"}:
        raise ValueError("Invalid replay manifest")
    for name, checksum in manifest["files"].items():
        if name not in required and not re.fullmatch(r"payloads/[0-9a-f]{64}\.json", name):
            raise ValueError("Unexpected replay file")
        if digest(files[name]) != checksum:
            raise ValueError("Invalid replay member checksum")
    meta = json.loads(files["run.json"])
    if not isinstance(meta, dict) or meta.get("trace_version") != "oopc-trace-v1" or not meta.get("run_id"):
        raise ValueError("Unsupported replay metadata")
    if manifest.get("release_id") != meta.get("release_id"):
        raise ValueError("Replay manifest release mismatch")
    # Import is a storage operation, never evidence of task completion. Older
    # importers overwrote every outcome with "completed"; re-exported legacy
    # replays therefore cannot establish their original task status. Preserve
    # that gap rather than guessing from the available events or artifacts.
    recorded_status = meta.get("recorded_status", "unknown") if meta.get("imported") else meta.get("status", "unknown")
    if recorded_status not in ("running", "completed", "failed", "cancelled", "paused", "unknown"):
        raise ValueError("Unsupported recorded replay status")
    original = meta.get("original_run_id", meta["run_id"])
    ontology = json.loads(files["ontology.json"])
    if not isinstance(ontology, dict):
        raise ValueError("Invalid replay ontology")
    events = [json.loads(line) for line in files["events.jsonl"].splitlines() if line]
    seen_events, observed, event_payloads, seen_by_id = set(), {}, {}, {}
    for index, event in enumerate(events, 1):
        if event.get("kind") not in ("access", "delivery", "artifact", "review", "reuse", "candidate", "lifecycle"):
            raise ValueError("Unknown replay event kind")
        if event.get("sequence") != index or event.get("release_id") != meta["release_id"] or event.get("run_id") != original:
            raise ValueError("Invalid replay sequence, run, or release")
        event_id = event.get("event_id")
        if not event_id or event_id in seen_events:
            raise ValueError("Duplicate or missing replay event identifier")
        parent = event.get("parent_event_id")
        if parent and parent not in seen_events:
            raise ValueError("Causal parent must precede the replay event")
        if event.get("kind") == "delivery":
            request = event.get("request", {})
            source = seen_by_id.get(request.get("source_event_id"), {})
            if source.get("kind") != "access" or parent != source.get("event_id") or not set(event.get("result_ids", [])).issubset(source.get("result_ids", [])):
                raise ValueError("Replay delivery lacks its supporting access event")
            if request.get("representation") not in ("content", "reference", "summary") or not request.get("model_call_id"):
                raise ValueError("Invalid replay delivery representation or model call")
        seen_events.add(event_id)
        seen_by_id[event_id] = event
        payload_hash = event.get("payload_hash", "")
        if not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
            raise ValueError("Invalid event payload checksum")
        raw = files.get("payloads/" + payload_hash + ".json")
        if raw is None or digest(raw) != payload_hash:
            raise ValueError("Missing or invalid event payload")
        payload = json.loads(raw)
        if isinstance(payload, dict) and payload.get("type") == "external_evidence":
            if event["kind"] != "artifact" or event.get("result_ids"):
                raise ValueError("Attached source evidence cannot imply observed access or citations")
            _validate_source_attachment(payload)
        event_payloads[event_id] = payload
        ids = event.get("result_ids")
        if not isinstance(ids, list) or not all(isinstance(rid, str) for rid in ids):
            raise ValueError("Invalid replay result identifiers")
        traversed, paths = event.get("traversed_edges", []), event.get("paths", [])
        if event.get("operation") != "traverse" and (traversed or paths):
            raise ValueError("Only explicit traversal may contain followed paths")
        if event.get("kind") == "access":
            returned = list(walk_records(payload))
            if len(ids) != len(set(ids)) or set(ids) != {record["@id"] for record in returned}:
                raise ValueError("Replay result identifiers differ from returned records")
            for record in returned:
                snapshot = copy.deepcopy(record)
                snapshot.pop("_access", None)
                snapshot.pop("release_id", None)
                rid = snapshot["@id"]
                if rid in observed and canonical(observed[rid]) != canonical(snapshot):
                    raise ValueError("Record changed within pinned replay")
                observed[rid] = snapshot
            if event.get("operation") == "traverse":
                if not isinstance(payload, dict) or paths != payload.get("paths", []):
                    raise ValueError("Traversal event and payload paths disagree")
                expected = list(dict.fromkeys(edge for path in paths for edge in path.get("edge_ids", [])))
                if traversed != expected:
                    raise ValueError("Traversal edge identifiers disagree with paths")
                returned_index = {record["@id"]: record for record in returned}
                for path in paths:
                    edge_ids, node_ids, directions = path.get("edge_ids", []), path.get("node_ids", []), path.get("directions", [])
                    if len(node_ids) != len(edge_ids)+1 or len(directions) != len(edge_ids):
                        raise ValueError("Invalid traversal path dimensions")
                    for i, eid in enumerate(edge_ids):
                        edge = returned_index.get(eid, {})
                        source, target = node_ids[i:i+2]
                        expected_pair = (source, target) if directions[i] == "forward" else (target, source)
                        if directions[i] not in ("forward", "reverse") or edge.get("@type") != "Claim" or (edge.get("subject"), edge.get("object")) != expected_pair:
                            raise ValueError("Traversal path is not supported by returned edges")
    if meta.get("last_sequence") != len(events):
        raise ValueError("Replay metadata and event sequence disagree")
    records = [json.loads(line) for line in files["records.jsonl"].splitlines() if line]
    indexed = {}
    for record in records:
        if not isinstance(record, dict) or not record.get("@id") or record["@id"] in indexed:
            raise ValueError("Duplicate or invalid replay record")
        indexed[record["@id"]] = record
    if canonical(indexed) != canonical(observed):
        raise ValueError("Replay record index differs from observed access payloads")
    artifacts = json.loads(files["artifacts.json"]).get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Invalid replay artifacts")
    artifact_ids = set()
    for artifact in artifacts:
        aid, eid = artifact.get("id"), artifact.get("event_id")
        if not aid or aid in artifact_ids or eid not in event_payloads:
            raise ValueError("Duplicate or unlinked replay artifact")
        artifact_ids.add(aid)
        expected = copy.deepcopy(event_payloads[eid])
        expected["event_id"] = eid
        if canonical(artifact) != canonical(expected):
            raise ValueError("Replay artifact differs from its recorded payload")
    run_id = "replay-" + uuid.uuid4().hex
    store.path.mkdir(parents=True, exist_ok=True)
    final_path = store.path / run_id
    staging = Path(tempfile.mkdtemp(prefix=".replay-import-", dir=str(store.path)))
    try:
        meta.pop("release_path", None)
        meta.update(run_id=run_id, original_run_id=original, imported=True,
                    immutable_replay=True, recorded_status=recorded_status,
                    status="checkpoint" if recorded_status in ("running", "unknown") else recorded_status,
                    private=True)
        meta["replay_status_note"] = (
            "Immutable replay checkpoint. The task was running when captured; no live worker is attached."
            if recorded_status == "running" else
            "Immutable replay checkpoint. The original task status was not preserved; completion is unknown."
            if recorded_status == "unknown" else
            "Immutable replay. The recorded task status is preserved; no live worker is attached.")
        for name, data in files.items():
            if name not in ("manifest.json", "run.json"):
                atomic_bytes(staging/name, data, private=True)
        atomic_json(staging/"run.json", meta, private=True)
        run = Run(staging)
        with run.db() as db:
            db.executescript("CREATE TABLE events(sequence INTEGER PRIMARY KEY,event_id TEXT UNIQUE,json TEXT); CREATE TABLE records(id TEXT PRIMARY KEY,json TEXT); CREATE TABLE artifacts(id TEXT PRIMARY KEY,json TEXT);")
            for event in events:
                db.execute("INSERT INTO events VALUES (?,?,?)", (event["sequence"],event["event_id"],canonical(event).decode()))
            for record in records:
                db.execute("INSERT INTO records VALUES (?,?)", (record["@id"],canonical(record).decode()))
            for artifact in artifacts:
                db.execute("INSERT INTO artifacts VALUES (?,?)", (artifact["id"],canonical(artifact).decode()))
        # Close WAL state before the directory's atomic publication.
        with run.db() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        staging.rename(final_path)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return meta
