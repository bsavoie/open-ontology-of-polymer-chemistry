"""Deterministic, immutable release assembly with atomically published directories."""
import hashlib
import copy
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from .validation import validate_records, _private_values
from .vocabulary import BASE, expand_iri, get_context, get_shapes
from .units import PROFILE_VERSION

FORMAT_VERSION = 1
INDEX_VERSION = "sqlite-fts5-v1"
OWNER = "open-ontology-of-polymer-chemistry"
MANAGED_METADATA = {"owner", "release_id", "index_version", "counts", "record_count", "files"}


def _metadata(value):
    return {k: v for k, v in value.items() if k not in MANAGED_METADATA}


def _release_id(records, ontology, metadata):
    identity = hashlib.sha256()
    for record in records:
        identity.update((canonical_json(record) + "\n").encode("utf-8"))
    identity.update(canonical_json(ontology).encode("utf-8"))
    identity.update(canonical_json(_metadata(metadata)).encode("utf-8"))
    return "oopc-" + identity.hexdigest()[:24]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_text(path, text):
    # Explicit LF preserves the same projection bytes on Windows and POSIX.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _write_json(path, value):
    _write_text(path, canonical_json(value) + "\n")


def _iri(value, vocab=False):
    return expand_iri(value, vocab=vocab)


def _literal(value):
    # JSON escaping is also valid for N-Triples string literals.
    return json.dumps(value, ensure_ascii=False)


def _projection_context(records):
    context = get_context()
    for record in records:
        for key, value in record.items():
            definition = context["@context"].get(key)
            if isinstance(definition, dict) and definition.get("@type") in {"@id", "@vocab"}:
                continue
            if isinstance(value, (dict, list)):
                context["@context"][key] = {"@id": BASE + "vocab/" + key, "@type": "@json"}
    return context


def _ontology_nodes(ontology):
    """The same vocabulary declarations accompany both RDF serializations."""
    for term in ontology.get("terms", []):
        node = {"@id": _iri(term["id"], vocab=True),
                "@type": "rdfs:Class" if term["kind"] == "class" else "rdf:Property",
                "label": term["label"], "definition": term["definition"]}
        mappings = [mapping["target"] for mapping in term.get("mappings", [])
                    if isinstance(mapping, dict) and mapping.get("relation") == "rdfs:subClassOf"]
        if mappings:
            node["subClassOf"] = mappings
        yield node


def _rdf(records, ontology, path, context=None):
    """Serialize the bundled flat JSON-LD profile without a runtime RDF library.

    All typed fields use the same context as graph.jsonld. Scientific Claim
    records stay reified; exporting a candidate never asserts its bare edge.
    """
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    context = (context or _projection_context(records))["@context"]
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in [*_ontology_nodes(ontology), *records]:
            subject = "<" + _iri(record["@id"]) + ">"
            stream.write("%s <%stype> <%s> .\n" % (subject, rdf, _iri(record["@type"], vocab=True)))
            for key, value in sorted(record.items()):
                if key.startswith("@") or value is None:
                    continue
                definition = context.get(key, key)
                predicate = _iri(definition.get("@id", key) if isinstance(definition, dict) else definition, vocab=True)
                value_type = definition.get("@type") if isinstance(definition, dict) else None
                if value_type in {"@id", "@vocab"}:
                    values = value if isinstance(value, list) else [value]
                    objects = ["<" + _iri(item, vocab=value_type == "@vocab") + ">" for item in values if item is not None]
                elif value_type == "@json":
                    objects = [_literal(canonical_json(value)) + "^^<" + rdf + "JSON>"]
                elif value_type:
                    objects = [_literal(str(value)) + "^^<" + _iri(value_type, vocab=True) + ">"]
                elif isinstance(value, bool):
                    objects = [('"true"' if value else '"false"') + "^^<http://www.w3.org/2001/XMLSchema#boolean>"]
                elif isinstance(value, (int, float)):
                    objects = [_literal(str(value)) + "^^<http://www.w3.org/2001/XMLSchema#" + ("integer" if isinstance(value, int) else "double") + ">"]
                else:
                    objects = [_literal(str(value))]
                for obj in objects:
                    stream.write("%s <%s> %s .\n" % (subject, predicate, obj))


def _search_text(record):
    fields = ("label", "alternateNames", "abbreviations", "canonicalSlug", "taxonomy", "text", "citation", "locator", "route", "context", "definition", "taskScope")
    return " ".join(canonical_json(record[k]) if not isinstance(record[k], str) else record[k] for k in fields if k in record)


def build_sqlite(path, records):
    """Rebuild the documented read projection; insertion order is deterministic."""
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript('''
            PRAGMA journal_mode=DELETE;
            PRAGMA page_size=4096;
            CREATE TABLE records (id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, status TEXT, layer TEXT, json TEXT NOT NULL);
            CREATE TABLE edges (id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, status TEXT, layer TEXT, json TEXT NOT NULL);
            CREATE INDEX records_type ON records(type);
            CREATE INDEX records_status_layer ON records(status,layer);
            CREATE INDEX edges_subject ON edges(subject,predicate);
            CREATE INDEX edges_object ON edges(object,predicate);
            CREATE INDEX edges_predicate ON edges(predicate,status,layer);
            CREATE VIRTUAL TABLE records_fts USING fts5(id UNINDEXED,label,text, tokenize='unicode61 remove_diacritics 2');
        ''')
        for record in records:
            body = canonical_json(record)
            connection.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (record["@id"], record["@type"], record["label"], record.get("status"), record.get("layer"), body))
            connection.execute("INSERT INTO records_fts VALUES (?,?,?)", (record["@id"], record["label"], _search_text(record)))
            if record["@type"] == "Claim":
                connection.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", (record["@id"], record["subject"], record["predicate"], record["object"], record.get("status"), record.get("layer"), body))
        connection.execute("INSERT INTO records_fts(records_fts) VALUES ('optimize')")
        connection.commit()
        connection.execute("VACUUM")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite projection failed integrity check")
    finally:
        connection.close()


def _markdown(root, records, ontology):
    root.mkdir()
    by_id = {record["@id"]: record for record in records}
    overview = ["# Open Ontology of Polymer Chemistry", "", "Seed assertions retain the wiki's draft maturity. Their source declarations have not been newly verified.", "", "## Polymer identities", ""]
    for polymer in records:
        if polymer["@type"] != "PolymerConcept":
            continue
        overview.append("- [%s](%s.md)" % (polymer["label"].replace("[", "\\[").replace("]", "\\]"), polymer["@id"]))
        lines = ["# " + polymer["label"], "", "Stable ID: `" + polymer["@id"] + "` · Status: seed", "", "Imported from Wiki of Open Polymer Data. Original prose: CC BY 4.0; structured data: CC0. Linked publications retain their rights.", ""]
        for sid in polymer.get("sectionIds", []):
            section = by_id[sid]
            lines.extend(["## " + section["sectionKey"], "", section["text"] or "*Evidence gap: empty source section.*", "", "Evidence:", ""])
            for eid in section["evidence"]:
                evidence = by_id[eid]
                lines.append("- [%s](%s) — %s" % (evidence["label"].replace("[", "\\[").replace("]", "\\]"), evidence.get("contentUrl") or evidence["url"], evidence["locator"]))
            lines.append("")
        _write_text(root / (polymer["@id"] + ".md"), "\n".join(lines) + "\n")
    _write_text(root / "index.md", "\n".join(overview) + "\n")
    lines = ["# Ontology definitions", ""]
    for term in ontology.get("terms", []):
        lines += ["## " + term["label"], "", term["definition"], "", "Status: " + term["status"], ""]
        if term.get("requiredContext"):
            lines += ["Required context: " + ", ".join(term["requiredContext"]), ""]
    _write_text(root / "ontology.md", "\n".join(lines))


def build_release(destination, records, ontology, metadata):
    """Validate/build in staging, then publish an immutable directory by rename.

    Existing releases are never replaced. Rebuilding identical content is a no-op;
    use a new destination for changed content. No source paths enter the manifest.
    """
    records = sorted(records, key=lambda r: r.get("@id", ""))
    metadata = _metadata(metadata)
    metadata.setdefault("format_version", FORMAT_VERSION)
    schema_source = Path(__file__).parent / "schema"
    metadata["build_profile"] = {"export_version": "2", "index_version": INDEX_VERSION, "units_profile": PROFILE_VERSION,
        "context_sha256": hashlib.sha256(canonical_json(get_context()).encode("utf-8")).hexdigest(),
        "shapes_sha256": hashlib.sha256(get_shapes().encode("utf-8")).hexdigest(),
        "schema_sha256": {p.name: sha256_file(p) for p in sorted(schema_source.glob("*.json"))}}
    errors = validate_records(records, ontology)
    errors += _private_values(metadata, "metadata")
    if errors:
        raise ValueError("Release validation failed:\n" + "\n".join(errors[:100]))
    destination = Path(destination).absolute()
    release_id = _release_id(records, ontology, metadata)
    if destination.exists():
        manifest = verify_release(destination)
        if manifest.get("release_id") == release_id:
            return destination
        raise FileExistsError("Immutable release exists; choose a new destination: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".oopc-release-", dir=str(destination.parent)))
    try:
        with (staging / "records.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(canonical_json(record) + "\n")
        _write_json(staging / "ontology.json", ontology)
        context = _projection_context(records)
        _write_json(staging / "context.json", context)
        _write_text(staging / "shapes.ttl", get_shapes())
        schema_source = Path(__file__).parent / "schema"
        if schema_source.is_dir():
            shutil.copytree(schema_source, staging / "schemas")
        _rdf(records, ontology, staging / "graph.nt", context)
        build_sqlite(staging / "graph.sqlite", records)
        _markdown(staging / "markdown", records, ontology)
        # JSON-LD streams are valid when interpreted with the supplied context.
        # An ordinary JSON-LD document is provided for standard RDF tooling too.
        with (staging / "graph.jsonld").open("w", encoding="utf-8", newline="\n") as stream:
            stream.write('{"@context":' + canonical_json(context["@context"]) + ',"@graph":[')
            for index, record in enumerate([*_ontology_nodes(ontology), *records]):
                stream.write(("," if index else "") + canonical_json(record))
            stream.write("]}\n")
        files = {p.relative_to(staging).as_posix(): {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                 for p in sorted(staging.rglob("*")) if p.is_file()}
        manifest = {**metadata, "owner": OWNER, "format_version": FORMAT_VERSION, "release_id": release_id,
                    "index_version": INDEX_VERSION, "counts": dict(sorted(Counter(r["@type"] for r in records).items())),
                    "record_count": len(records), "files": files}
        _write_json(staging / "manifest.json", manifest)
        verify_release(staging)
        # flush files before publishing; directory rename is the commit point.
        for path in staging.rglob("*"):
            if path.is_file():
                # Windows requires a writable descriptor for fsync.
                with path.open("r+b") as stream:
                    os.fsync(stream.fileno())
        staging.rename(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _verify_release_data(path):
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Not an owned OOPC release: missing manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("owner") != OWNER or manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unknown release owner or unsupported format version")
    required = {"records.jsonl", "ontology.json", "context.json", "shapes.ttl", "graph.sqlite", "graph.nt", "graph.jsonld"}
    files = manifest.get("files", {})
    if not required.issubset(files):
        raise ValueError("Incomplete release manifest")
    for name, info in files.items():
        file = path / name
        if Path(name).is_absolute() or ".." in Path(name).parts or file.is_symlink() or not file.is_file() or path.resolve() not in file.resolve().parents:
            raise ValueError("Unsafe or missing release file: " + name)
        if file.stat().st_size != info.get("bytes") or sha256_file(file) != info.get("sha256"):
            raise ValueError("Release checksum mismatch: " + name)
    with (path / "records.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    ontology = json.loads((path / "ontology.json").read_text(encoding="utf-8"))
    if _release_id(records, ontology, manifest) != manifest.get("release_id"):
        raise ValueError("Release identity does not match canonical content and metadata")
    if len(records) != manifest.get("record_count"):
        raise ValueError("Release record count mismatch")
    return records, ontology, manifest


def verify_release(path):
    from .release_verification import _verified_snapshot
    snapshot = _verified_snapshot(path, _verify_release_data)
    if snapshot is not None:
        return copy.deepcopy(snapshot.manifest)
    return _verify_release_data(path)[2]


def load_release(path):
    from .release_verification import _verified_snapshot
    snapshot = _verified_snapshot(path, _verify_release_data)
    if snapshot is not None:
        return copy.deepcopy((snapshot.records, snapshot.ontology, snapshot.manifest))
    return _verify_release_data(path)
