"""Lossless, read-only import of WOP v2. No article text is promoted to a fact."""
import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .vocabulary import get_ontology

SEED_URL = "https://github.com/bsavoie/wiki-of-open-polymer-data/blob/main/public-data/wop-publication-snapshot-v2/snapshot.json"
SEED_ATTRIBUTION = "Wiki of Open Polymer Data contributors"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_doi(doi):
    value = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return value


def normalize_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def evidence_id(wop_id, source_id):
    return "evidence:%s:%s" % (wop_id, source_id)


def import_seed(snapshot_path, expected_sha256=None):
    """Return (records, ontology, metadata), preserving original strings and IDs.

    Reading bytes is intentional: the seed is pinned to the source file checksum,
    not a reformatted equivalent. The input is never modified.
    """
    raw = Path(snapshot_path).read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("schema") != "wop-publication-snapshot-v2":
        raise ValueError("Expected authoritative wop-publication-snapshot-v2 snapshot")
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError("Seed checksum does not match the pinned source snapshot")
    provenance = {"source": "Wiki of Open Polymer Data v2", "sourceUrl": SEED_URL,
                  "snapshotSha256": sha, "verification": "Imported without new scientific verification"}
    rights_data = {"license": "CC0-1.0", "attribution": SEED_ATTRIBUTION, "sourceUrl": SEED_URL,
                   "thirdPartyRights": "Linked publications retain their own rights."}
    rights_prose = {"license": "CC-BY-4.0", "attribution": SEED_ATTRIBUTION, "sourceUrl": SEED_URL,
                    "adaptation": "Verbatim imported wiki prose; no scientific reinterpretation."}
    records = []
    ids = set()

    def add(record):
        if record["@id"] in ids:
            raise ValueError("Duplicate imported identifier: " + record["@id"])
        record.setdefault("status", "seed")
        record.setdefault("provenance", deepcopy(provenance))
        record.setdefault("history", [{"action": "seed-import", "snapshotSha256": sha}])
        record.setdefault("rights", deepcopy(rights_data))
        ids.add(record["@id"])
        records.append(record)
        return record

    def claim(subject, predicate, object_, context=None, evidence=None, layer="science", key=None):
        context = context or {}
        identity = _json([subject, predicate, object_, context, key])
        return add({"@id": "claim:" + _digest(identity)[:32], "@type": "Claim",
                    "label": "%s → %s → %s" % (subject, predicate, object_),
                    "subject": subject, "predicate": predicate, "object": object_,
                    "status": "seed", "layer": layer, "context": deepcopy(context),
                    "evidence": list(evidence or []), "verified": False})

    polymers = snapshot["polymers"]
    polymer_ids = [p["wopId"] for p in polymers]
    if len(polymer_ids) != len(set(polymer_ids)):
        raise ValueError("Duplicate WOP identifiers")
    sources = [(p["wopId"], s) for p in polymers for s in p.get("sources", [])]
    sources += [("methodology", s) for s in snapshot.get("methodology", {}).get("sources", [])]
    url_dois = defaultdict(set)
    for _, source in sources:
        doi = normalize_doi(source.get("doi"))
        if doi:
            for field in ("url", "contentUrl"):
                if source.get(field):
                    url_dois[normalize_url(source[field])].add(doi)
    documents = {}
    evidence_by_owner = defaultdict(list)
    for owner, source in sources:
        doi = normalize_doi(source.get("doi"))
        canonical = normalize_url(source.get("url") or source.get("contentUrl") or "")
        if not canonical:
            raise ValueError("Seed evidence is missing its source URL")
        mapped_dois = url_dois.get(canonical, set())
        if not doi and len(mapped_dois) == 1:
            doi = next(iter(mapped_dois))
        key = "doi:" + doi if doi else "url:" + canonical
        doc_id = "document:" + _digest(key)[:32]
        if doc_id not in documents:
            documents[doc_id] = {"@id": doc_id, "@type": "Document", "label": source["citation"],
                                 "identityKey": key, "doi": doi or None, "urls": [], "citations": [],
                                 "lineageIds": [], "sourceTypes": [], "layer": "provenance"}
        document = documents[doc_id]
        for field, values in (("urls", [source.get("url"), source.get("contentUrl")]),
                              ("citations", [source.get("citation")]), ("lineageIds", [source.get("lineageId")]),
                              ("sourceTypes", [source.get("sourceType")])):
            document[field] = sorted(set(document[field]) | {v for v in values if v})
        occurrence = {**deepcopy(source), "@id": evidence_id(owner, source["sourceId"]),
                      "@type": "Evidence", "label": source["citation"], "wopId": owner,
                      "document": doc_id, "source": deepcopy(source), "verified": False,
                      "layer": "provenance", "rights": {**rights_data, "evidenceReuseStatus": source.get("reuseStatus"),
                                                             "permissionBasis": source.get("permissionBasis")}}
        add(occurrence)
        evidence_by_owner[owner].append(occurrence)
        claim(occurrence["@id"], "evidenceFrom", doc_id, layer="provenance")
    for document in documents.values():
        add(document)

    for structure in snapshot.get("chemicalStructures", []):
        add({**deepcopy(structure), "@id": "structure:" + structure["structureId"], "@type": "Structure",
             "label": structure["structureId"], "layer": "science",
             "molfileSha256": _digest(structure["molfileV3000"]),
             "representationPolicy": "Usage fidelity and scope are attached to hasStructure claims; no chemistry was inferred."})

    for polymer in polymers:
        wid = polymer["wopId"]
        attrs = {k: deepcopy(v) for k, v in polymer.items() if k not in ("type", "sources", "sections", "relationships")}
        add({**attrs, "@id": wid, "@type": "PolymerConcept", "label": polymer["canonicalName"],
             "layer": "science", "sectionIds": ["section:%s:%s" % (wid, k) for k in polymer.get("sections", {})],
             "evidence": [e["@id"] for e in evidence_by_owner[wid]],
             "seedRelationships": deepcopy(polymer.get("relationships", [])),
             "rights": {**rights_data, "embeddedProseLicense": "CC-BY-4.0"}})
        for relationship in polymer.get("relationships", []):
            claim(wid, relationship["kind"], relationship["wopId"], context={"basis": "wiki-authored relationship; not independently verified"})
        for axis, values in polymer.get("taxonomy", {}).items():
            for value in values if isinstance(values, list) else [values]:
                fid = "facet:%s:%s" % (axis, value)
                if fid not in ids:
                    add({"@id": fid, "@type": "Facet", "label": value.replace("_", " "),
                         "axis": axis, "value": value, "layer": "taxonomy"})
                claim(wid, "hasFacet", fid, context={"axis": axis, "browsingOnly": axis == "primaryClass"}, layer="taxonomy")
        for section_key, body in polymer.get("sections", {}).items():
            sid = "section:%s:%s" % (wid, section_key)
            evidence = [e["@id"] for e in evidence_by_owner[wid] if section_key in e.get("supports", [])]
            add({"@id": sid, "@type": "Section", "label": polymer["canonicalName"] + " — " + section_key,
                 "wopId": wid, "sectionKey": section_key, "text": body, "empty": not bool(body),
                 "evidence": evidence, "maturity": deepcopy(polymer.get("maturity", {})),
                 "layer": "provenance", "rights": deepcopy(rights_prose)})
            claim(wid, "hasSection", sid, context={"sectionKey": section_key}, layer="provenance")
            for eid in evidence:
                claim(sid, "supportedBy", eid, layer="provenance")
        groups = [("structuralDepictions", polymer.get("structuralDepictions", {}))]
        groups.extend(("contextualStructures." + name, group) for name, group in polymer.get("contextualStructures", {}).items())
        for placement, group in groups:
            for index, item in enumerate(group.get("items", [])):
                context = {**deepcopy(item), "placement": placement,
                           "scopeNote": group.get("scopeNote", ""), "reviewStatus": group.get("reviewStatus"),
                           "representationType": group.get("representationType", "contextual")}
                claim(wid, "hasStructure", "structure:" + item["structureId"], context=context,
                      evidence=[evidence_id(wid, s) for s in group.get("sourceIds", [])], key=index)
        for route in polymer.get("synthesisRoutes", []):
            rid = "process:%s:%s" % (wid, route["routeId"])
            evidence = [evidence_id(wid, sid) for sid in route.get("sourceIds", [])]
            add({"@id": rid, "@type": "Process", "label": route["title"], "wopId": wid,
                 "route": deepcopy(route), "scopeNote": route.get("scopeNote", ""), "evidence": evidence,
                 "layer": "science", "rights": {**rights_data, "embeddedProseLicense": "CC-BY-4.0"}})
            claim(wid, "hasProcess", rid, context={"scopeNote": route.get("scopeNote", ""), "basis": route.get("basis")}, evidence=evidence)
            for key_, predicate in (("inputs", "routeInput"), ("products", "routeProduct")):
                for index, item in enumerate(route.get(key_, [])):
                    if item.get("structureId"):
                        claim(rid, predicate, "structure:" + item["structureId"],
                              context={"scopeNote": route.get("scopeNote", ""), "productMode": route.get("productMode", "unknown"),
                                       "productNote": route.get("productNote", ""), "label": item.get("label", "")},
                              evidence=evidence, key=index)
    records.sort(key=lambda r: r["@id"])
    metadata = {"format_version": 1, "seed_schema": snapshot["schema"],
                "seed_source": {"url": SEED_URL, "sha256": sha}, "seed_snapshot_sha256": sha,
                "seed_counts": {"polymers": len(polymers), "structures": len(snapshot.get("chemicalStructures", [])),
                                "article_evidence": sum(len(p.get("sources", [])) for p in polymers),
                                "relationships": sum(len(p.get("relationships", [])) for p in polymers)},
                "aliases": deepcopy(snapshot.get("aliases", [])), "searchTerms": deepcopy(snapshot.get("searchTerms", [])),
                "methodology": deepcopy(snapshot.get("methodology", {})),
                "rights": {"structuredData": rights_data, "originalProse": rights_prose},
                "importPolicy": "Read-only, lossless seed import; source declarations are retained without a new source access or claim verification pass."}
    return records, get_ontology(), metadata
