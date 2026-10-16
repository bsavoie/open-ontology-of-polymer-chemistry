"""Read-only, instrumented access to an immutable evidence-graph release."""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from .util import read_json

DEFAULT_EXCLUDED = ("candidate", "disputed", "experimental", "rejected", "superseded")


# CorpusMCP preserves legacy v1/v2 behavior independently of regular Graph access.
# Prospective benchmark callers opt into changed semantics with an exact pin.
LEGACY_RETRIEVAL_PROTOCOL = "oopc-retrieval-v1"
BUDGETED_RETRIEVAL_PROTOCOL = "oopc-budgeted-retrieval-v2"
VALIDATED_RETRIEVAL_PROTOCOL = "oopc-budgeted-retrieval-v3"
BUDGETED_RETRIEVAL_PROTOCOLS = (BUDGETED_RETRIEVAL_PROTOCOL, VALIDATED_RETRIEVAL_PROTOCOL)
RETRIEVAL_PROTOCOLS = (LEGACY_RETRIEVAL_PROTOCOL, *BUDGETED_RETRIEVAL_PROTOCOLS)
PROJECTION_NOTICE = ("RecordFragment items contain partial canonical JSON, not complete scientific "
                     "claims. Qualifications may be outside the fragment. Retrieve all fragments "
                     "before interpreting or citing the record; cite sourceRecordId.")


def validate_predicate(ontology, predicate, *, allow_all=False):
    """An exact declared relation, not an inferred name or an observed edge.

    Empty filters remain unspecified. Budgeted protocols additionally expose
    their existing explicit ``all`` wildcard. A known relation may have no
    visible instances; that is an ordinary empty result, not a vocabulary error.
    """
    if predicate is None or predicate == "" or (allow_all and predicate == "all"):
        return
    terms = ontology.get("predicates", [])
    if not terms:
        terms = [term for term in ontology.get("terms", []) if term.get("kind") == "relation"]
    identifiers = {term.get("id", term.get("@id")) for term in terms}
    if not isinstance(predicate, str) or predicate not in identifiers:
        displayed = repr(predicate)
        if len(displayed) > 160:
            displayed = displayed[:157] + "..."
        raise ValueError("Unknown relationship predicate " + displayed
                         + ". Use describe_vocabulary to select an exact relation ID from the pinned ontology.")


def serialized_chars(payload):
    """Use the same Unicode character envelope as the MCP tool return."""
    return len(json.dumps(payload, ensure_ascii=False))


def response_fits(payload, maximum, access_run_id=None):
    # Run.record appends this exact-size receipt to the returned payload. Reserve
    # it BEFORE packing; the actual receipt is created only for the packed result.
    if access_run_id is not None:
        payload = dict(payload, _access={"run_id": access_run_id, "event_id": "evt-" + "0" * 32})
    return serialized_chars(payload) <= maximum


def fragment_record(record, offset, length, retrieval_tool="get_record", id_key="id", next_length=24000):
    """Lossless, explicitly incomplete JSON slice with its own immutable identity."""
    source = json.dumps(record, ensure_ascii=False, sort_keys=True)
    identifier = record.get("@id", record.get("id"))
    if not isinstance(identifier, str):
        raise ValueError("Fragment source requires a canonical identifier")
    if offset < 0 or offset > len(source):
        raise ValueError("char_offset is outside this record")
    end = min(len(source), offset + length)
    fragment = {"@type": "RecordFragment", "sourceRecordId": identifier,
                "sourceRecordType": record.get("@type", "VocabularyTerm"),
                "sourceSha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "serialization": "json-ensure-ascii-false-sort-keys-v1",
                "char_offset": offset, "char_end": end, "total_chars": len(source),
                "contentComplete": offset == 0 and end == len(source),
                "text": source[offset:end],
                "next": {"tool": retrieval_tool, "arguments": {id_key: identifier,
                         "char_offset": end, "char_limit": next_length}} if end < len(source) else None}
    identity = hashlib.sha256(json.dumps(fragment, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"@id": "fragment:" + identity, **fragment}


def fit_fragment(record, make_payload, maximum, access_run_id=None, offset=0, length=2048,
                 retrieval_tool="get_record", id_key="id", next_length=24000):
    """Choose the largest exact slice that fits INCLUDING its response metadata."""
    source_length = len(json.dumps(record, ensure_ascii=False, sort_keys=True))
    if offset < 0 or offset > source_length:
        raise ValueError("char_offset is outside this record")
    low, high, selected = 1, min(length, max(1, source_length - offset)), None
    # At the final slice, removing continuation metadata can make the complete
    # slice fit even when a slightly shorter slice would not. Test that boundary
    # first; the remaining search then has monotonically increasing size.
    complete_candidate = make_payload(fragment_record(record, offset, high, retrieval_tool, id_key, next_length))
    if response_fits(complete_candidate, maximum, access_run_id):
        return complete_candidate
    while low <= high:
        middle = (low + high) // 2
        fragment = fragment_record(record, offset, middle, retrieval_tool, id_key, next_length)
        payload = make_payload(fragment)
        if response_fits(payload, maximum, access_run_id):
            selected = payload
            low = middle + 1
        else:
            high = middle - 1
    if selected is None:
        raise ValueError("Response cap cannot fit one identified fragment and continuation metadata")
    return selected


def pack_record_page(records, *, offset=0, limit=20, maximum=24000, access_run_id=None,
                     transform=None, key="records", retrieval_tool="get_record", id_key="id",
                     retrieval_protocol=BUDGETED_RETRIEVAL_PROTOCOL):
    """Stable whole-record prefix, or an honest fragment when its first item is large."""
    if retrieval_protocol not in BUDGETED_RETRIEVAL_PROTOCOLS:
        raise ValueError("Unsupported budgeted retrieval protocol")
    total = len(records)
    def envelope(items, next_index, partial=False):
        result = {key: items, "total": total, "offset": offset, "limit": limit,
                  "truncated": next_index < total or partial,
                  "next_offset": next_index if next_index < total else None,
                  "retrievalProtocol": retrieval_protocol}
        if partial:
            result["notice"] = PROJECTION_NOTICE
        return result
    selected = []
    for index in range(offset, min(total, offset + limit)):
        record = records[index]
        displayed = transform(record) if transform else record
        payload = envelope(selected + [displayed], index + 1)
        if response_fits(payload, maximum, access_run_id):
            selected.append(displayed)
        elif selected:
            break
        else:
            return fit_fragment(record, lambda fragment: envelope([fragment], index + 1, True),
                                maximum, access_run_id, length=2048,
                                retrieval_tool=retrieval_tool, id_key=id_key)
    payload = envelope(selected, min(total, offset + len(selected)))
    if not response_fits(payload, maximum, access_run_id):
        raise ValueError("Response cap cannot fit pagination metadata")
    return payload


class Graph:
    def __init__(self, release, trace=None, agent_id="agent", verify=True):
        self.path = Path(release).resolve()
        if verify:
            from .release import verify_release
            self.manifest = verify_release(self.path)
        else:
            self.manifest = read_json(self.path / "manifest.json")
        self.release_id = self.manifest["release_id"]
        self.ontology = read_json(self.path / "ontology.json")
        self.trace = trace
        self.agent_id = agent_id
        if trace and trace.meta()["release_id"] != self.release_id:
            raise ValueError("A run cannot change its pinned graph release")

    @contextmanager
    def db(self):
        db = sqlite3.connect((self.path / "graph.sqlite").as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def _execute(self, operation, request, fn, parent_event_id=None):
        started = time.monotonic()
        try:
            if "predicate" in request:
                validate_predicate(self.ontology, request["predicate"])
            result = fn()
        except Exception as error:
            if self.trace:
                self.trace.record(operation, request, {"error": str(error)}, agent_id=self.agent_id,
                                  status="error", duration_ms=(time.monotonic()-started)*1000,
                                  parent_event_id=parent_event_id)
            raise
        if isinstance(result, dict):
            result.setdefault("release_id", self.release_id)
        if self.trace:
            paths = result.get("paths", []) if operation == "traverse" else []
            traversed = list(dict.fromkeys(edge for path in paths for edge in path["edge_ids"]))
            self.trace.record(operation, request, result, agent_id=self.agent_id,
                              traversed_edges=traversed, paths=paths,
                              duration_ms=(time.monotonic()-started)*1000,
                              parent_event_id=parent_event_id)
        return result

    @staticmethod
    def _filters(filters, alias=""):
        prefix = alias + "." if alias else ""
        sql, args = [], []
        for key in ("type", "layer", "status"):
            value = filters.get(key)
            if value and value != "all":
                sql.append(prefix + key + " = ?")
                args.append(value)
        if not filters.get("status"):
            sql.append(prefix + "status NOT IN (" + ",".join("?" for _ in DEFAULT_EXCLUDED) + ")")
            args.extend(DEFAULT_EXCLUDED)
        return sql, args

    @staticmethod
    def _facet_matches(record, filters):
        # Each facet searches its own dimension. Shared words never establish
        # environmental, test, or application compatibility across dimensions.
        if record.get("@type") == "Recipe" and not filters.get("include_unavailable"):
            availability = record.get("sourceAvailability", {})
            if record.get("availability") == "suspended" or isinstance(availability, dict) and availability.get("status") in {"unavailable", "needs-reevaluation"}:
                return False
        context = record.get("context", {})
        context = context if isinstance(context, dict) else {}
        taxonomy = record.get("taxonomy", {})
        scope = {key: [record.get(key), context.get(key)] for key in
                 ("property", "process", "application", "environment")}
        scope["property"].extend([context.get("propertyType"), context.get("measuredProperty")])
        scope["process"].extend([context.get("processing"), context.get("processType")])
        scope["source"] = [record.get("evidence"), record.get("sources"), record.get("document"), record.get("url"), record.get("citation")]
        scope["facet"] = [taxonomy, context.get("axis"), context.get("value"), record.get("facet")]
        for key in ("property", "process", "application", "environment", "source", "facet"):
            value = filters.get(key)
            if value and value.casefold() not in json.dumps(scope[key], ensure_ascii=False).casefold():
                return False
        return True

    def get(self, record_id, parent_event_id=None):
        def work():
            with self.db() as db:
                row = db.execute("SELECT json FROM records WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise KeyError("Record not found: " + record_id)
            return json.loads(row[0])
        return self._execute("get", {"id": record_id}, work, parent_event_id)

    def search(self, q="", limit=50, offset=0, parent_event_id=None, **filters):
        def work():
            page_limit, page_offset = min(max(int(limit), 1), 500), max(int(offset), 0)
            where, args = self._filters(filters, "r")
            # Literal AND matching avoids exposing FTS syntax as executable query language.
            tokens = re.findall(r"[\w-]+", q, flags=re.UNICODE)
            use_fts = bool(tokens)
            if use_fts:
                phrase = " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens[:20])
                aliases = [a["wopId"] for a in self.manifest.get("aliases",[]) if a.get("slug","").casefold()==q.casefold()]
                aliases += [rid for term in self.manifest.get("searchTerms",[]) if term.get("term","").casefold()==q.casefold() for rid in term.get("wopIds",[])]
                aliases = list(dict.fromkeys([q]+aliases))
                where.append("(r.id IN (SELECT id FROM records_fts WHERE records_fts MATCH ?) OR r.id IN ("+",".join("?" for _ in aliases)+"))")
                args.append(phrase)
                args.extend(aliases)
            if filters.get("predicate"):
                where.append("r.id IN (SELECT id FROM edges WHERE predicate=?)")
                args.append(filters["predicate"])
            sql = "SELECT r.json FROM records r" + (" WHERE " + " AND ".join(where) if where else "")
            sql += " ORDER BY CASE r.type WHEN 'PolymerConcept' THEN 0 WHEN 'Material' THEN 1 WHEN 'Section' THEN 2 ELSE 3 END,r.label,r.id"
            with self.db() as db:
                rows = [json.loads(row[0]) for row in db.execute(sql, args)]
            rows = [r for r in rows if self._facet_matches(r, filters)]
            # Exact labels and IDs precede broad family/prose matches.
            needle = q.strip().casefold()
            if needle:
                rows.sort(key=lambda r: (r.get("label", "").casefold() != needle and r["@id"].casefold() != needle,
                                         not r.get("label", "").casefold().startswith(needle)))
            return {"records": rows[page_offset:page_offset+page_limit], "total": len(rows), "offset": page_offset,
                    "limit": page_limit, "truncated": len(rows) > page_offset+page_limit}
        return self._execute("search", {"q": q, "limit": limit, "offset": offset, **filters}, work, parent_event_id)

    def claims(self, subject=None, predicate=None, object=None, limit=100, offset=0, parent_event_id=None, **filters):
        def work():
            page_limit, page_offset = min(max(int(limit), 1), 500), max(int(offset), 0)
            where, args = self._filters({k:v for k,v in filters.items() if k != "type"})
            for key, value in (("subject", subject), ("predicate", predicate), ("object", object)):
                if value:
                    where.append(key + "=?")
                    args.append(value)
            sql = "SELECT json FROM edges" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
            with self.db() as db:
                rows = [json.loads(row[0]) for row in db.execute(sql, args)]
            rows = [r for r in rows if self._facet_matches(r, filters)]
            return {"records": rows[page_offset:page_offset+page_limit], "total": len(rows), "offset": page_offset,
                    "limit": page_limit, "truncated": len(rows) > page_offset+page_limit}
        return self._execute("claims", {"subject": subject, "predicate": predicate, "object": object,
                                      "limit": limit, "offset": offset, **filters}, work, parent_event_id)

    def describe(self, term=None, parent_event_id=None):
        def work():
            terms = self.ontology.get("terms", self.ontology.get("classes", []) + self.ontology.get("predicates", []))
            return {"terms": [t for t in terms if not term or t.get("id", t.get("@id")) == term]}
        return self._execute("describe", {"term": term}, work, parent_event_id)

    def evidence(self, record_id, parent_event_id=None):
        def work():
            with self.db() as db:
                row = db.execute("SELECT json FROM records WHERE id=?", (record_id,)).fetchone()
                if not row:
                    raise KeyError(record_id)
                rec = json.loads(row[0])
                if rec["@type"] == "Evidence":
                    return {"records": [rec], "total": 1, "truncated": False}
                ids = rec.get("evidence", [])
                if not ids:
                    edges = db.execute("SELECT object FROM edges WHERE subject=? AND predicate='supportedBy'", (record_id,)).fetchall()
                    ids = [e[0] for e in edges]
                records = []
                for eid in ids:
                    eid = eid.get("@id") if isinstance(eid, dict) else eid
                    row = db.execute("SELECT json FROM records WHERE id=?", (eid,)).fetchone()
                    if row:
                        records.append(json.loads(row[0]))
            return {"records": records, "total": len(records), "truncated": False}
        return self._execute("evidence", {"id": record_id}, work, parent_event_id)

    def recipes(self, q="", include_experimental=False, parent_event_id=None, include_unavailable=False, limit=50, offset=0):
        # Search is separately identified to keep memory access visible in traces.
        def work():
            return Graph(self.path, verify=False).search(q, type="Recipe", status="all" if include_experimental else "reuse-tested", include_unavailable=include_unavailable, limit=limit, offset=offset)
        return self._execute("recipes", {"q": q, "include_experimental": include_experimental, "include_unavailable": include_unavailable, "limit":limit, "offset":offset}, work, parent_event_id)

    def traverse(self, start, depth=1, direction="both", limit=150, parent_event_id=None, **filters):
        def work():
            levels, edge_limit = min(max(int(depth), 1), 4), min(max(int(limit), 1), 500)
            if direction not in ("out", "in", "both"):
                raise ValueError("direction must be out, in, or both")
            nodes, edges, paths = {}, {}, []
            truncated = False
            with self.db() as db:
                row = db.execute("SELECT json FROM records WHERE id=?", (start,)).fetchone()
                if not row:
                    raise KeyError(start)
                nodes[start] = json.loads(row[0])
                frontier = [(start, [], [start])]
                for _ in range(levels):
                    following = []
                    for current, history, node_path in frontier:
                        where, args = self._filters({k:v for k,v in filters.items() if k != "type"})
                        endpoint = "(subject=? OR object=?)" if direction == "both" else ("subject=?" if direction == "out" else "object=?")
                        where.append(endpoint)
                        args.extend([current, current] if direction == "both" else [current])
                        if filters.get("predicate"):
                            where.append("predicate=?")
                            args.append(filters["predicate"])
                        rows = db.execute("SELECT json FROM edges WHERE " + " AND ".join(where) + " ORDER BY id", args)
                        for erow in rows:
                            edge = json.loads(erow[0])
                            if edge["@id"] in edges or not self._facet_matches(edge, filters):
                                continue
                            if len(edges) >= edge_limit:
                                truncated = True
                                break
                            target = edge["object"] if edge["subject"] == current else edge["subject"]
                            targetrow = db.execute("SELECT json FROM records WHERE id=?", (target,)).fetchone()
                            if not targetrow:
                                continue
                            edges[edge["@id"]] = edge
                            is_new = target not in nodes
                            nodes[target] = json.loads(targetrow[0])
                            path_ids = history + [edge["@id"]]
                            path_nodes = node_path + [target]
                            paths.append({"edge_ids": path_ids, "node_ids": path_nodes,
                                          "directions": ["forward" if edges[eid]["subject"] == path_nodes[i] else "reverse" for i,eid in enumerate(path_ids)]})
                            if is_new:
                                following.append((target, path_ids, path_nodes))
                        if truncated:
                            break
                    frontier = following
                    if truncated or not frontier:
                        break
            return {"nodes": list(nodes.values()), "edges": list(edges.values()), "paths": paths,
                    "truncated": truncated, "limit": edge_limit, "depth": levels}
        return self._execute("traverse", {"start": start, "depth": depth, "direction": direction,
                                        "limit": limit, **filters}, work, parent_event_id)

    def neighborhood(self, start, depth=1, direction="both", limit=150, offset=None, **filters):
        """Inspector-only access: a separate uninstrumented reader avoids trace pollution."""
        validate_predicate(self.ontology, filters.get("predicate"))
        if offset is None:
            return Graph(self.path, verify=False).traverse(start, depth=depth, direction=direction, limit=limit, **filters)
        if int(depth) != 1:
            raise ValueError("Paged neighborhoods require depth=1; expand each adjacent node separately")
        if direction not in ("out", "in", "both"):
            raise ValueError("direction must be out, in, or both")
        page_limit, page_offset = min(max(int(limit), 1), 500), max(int(offset), 0)
        where, args = self._filters({k:v for k,v in filters.items() if k != "type"}, "e")
        where.append("(e.subject=? OR e.object=?)" if direction == "both" else "e." + ("subject" if direction == "out" else "object") + "=?")
        args.extend([start, start] if direction == "both" else [start])
        if filters.get("predicate"):
            where.append("e.predicate=?")
            args.append(filters["predicate"])
        nodes, edges, paths, total = {}, [], [], 0
        with self.db() as db:
            row = db.execute("SELECT json FROM records WHERE id=?", (start,)).fetchone()
            if row is None:
                raise KeyError(start)
            nodes[start] = json.loads(row[0])
            # The release is immutable. Stable assertion ordering makes offsets
            # repeatable while keeping parallel assertions and their scopes intact.
            rows = db.execute("SELECT e.json FROM edges e WHERE " + " AND ".join(where) + " ORDER BY e.id", args)
            for row in rows:
                edge = json.loads(row[0])
                if not self._facet_matches(edge, filters):
                    continue
                target = edge["object"] if edge["subject"] == start else edge["subject"]
                targetrow = db.execute("SELECT json FROM records WHERE id=?", (target,)).fetchone()
                if targetrow is None:
                    continue
                if page_offset <= total < page_offset + page_limit:
                    nodes[target] = json.loads(targetrow[0])
                    edges.append(edge)
                    paths.append({"edge_ids": [edge["@id"]], "node_ids": [start, target],
                                  "directions": ["forward" if edge["subject"] == start else "reverse"]})
                total += 1
        truncated = page_offset + page_limit < total
        return {"nodes": list(nodes.values()), "edges": edges, "paths": paths,
                "total": total, "offset": page_offset, "limit": page_limit, "depth": 1,
                "truncated": truncated, "next_offset": page_offset + page_limit if truncated else None,
                "release_id": self.release_id}

    def metadata(self):
        with self.db() as db:
            filters = {key: [r[0] for r in db.execute("SELECT DISTINCT " + key + " FROM records ORDER BY " + key)]
                       for key in ("type", "status", "layer")}
        return {"release": self.manifest, "ontology": self.ontology, "types": filters["type"],
                "statuses": filters["status"], "layers": filters["layer"]}


def release_diff(before, after):
    def records(path):
        with open(Path(path) / "records.jsonl", encoding="utf-8") as handle:
            return {r["@id"]:r for r in (json.loads(line) for line in handle if line.strip())}
    old, new = records(before), records(after)
    return {"added": [new[k] for k in sorted(new.keys()-old.keys())],
            "removed": [old[k] for k in sorted(old.keys()-new.keys())],
            "changed": [{"id": k, "before": old[k], "after": new[k]} for k in sorted(old.keys() & new.keys()) if old[k] != new[k]]}
