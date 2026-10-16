"""Deterministic structural and admission checks; does not certify scientific truth."""
import hashlib
from copy import deepcopy
import math
import re
from urllib.parse import urlsplit

from .vocabulary import get_ontology
from .units import quantity_errors, is_number

STATUSES = {"seed", "candidate", "agent-validated", "experimental", "disputed", "superseded", "reuse-tested"}
REUSE = {"open_licensed", "public_domain", "publicly_accessible_citation_only"}
QUANTITATIVE_KEYS = ("material", "specimen", "method", "conditions", "units", "uncertainty", "limitations")


def _public_url(value):
    if not isinstance(value, str):
        return False
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    return (url.scheme in ("http", "https") and bool(host) and not url.username and not url.password
            and host not in ("localhost", "127.0.0.1", "::1") and not host.endswith((".local", ".internal")))


def _private_values(value, path=""):
    errors = []
    if isinstance(value, dict):
        for key, sub in value.items():
            if key.lower().replace("_", "") in {"apikey", "authorization", "accesstoken", "refreshtoken", "password", "systemprompt", "conversationhistory"}:
                errors.append(path + "." + key + ": private field forbidden in a public record")
            errors.extend(_private_values(sub, path + "." + key))
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            errors.extend(_private_values(sub, "%s[%s]" % (path, i)))
    elif isinstance(value, str) and re.search(r"(?:file://|/Users/|/home/|/private/(?:tmp|var)/|[A-Za-z]:\\Users\\)", value):
        errors.append(path + ": private filesystem path forbidden in a public record")
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(path + ": non-finite number")
    return errors


def stage_experimental_relation(ontology, record):
    """Return a private staging ontology; this does not grant publication authority.

    The assembler must also validate the independently reviewed instance claims
    and call experimental_instance_errors before committing the complete group.
    """
    rid = record.get("@id", record.get("id"))
    if not isinstance(rid, str) or not re.fullmatch(r"experimental:[A-Za-z][A-Za-z0-9_.-]*", rid):
        raise ValueError("Experimental relation requires a safe experimental: identifier")
    existing = ontology.get("terms", []) + ontology.get("predicates", []) + ontology.get("classes", [])
    if any(term.get("id", term.get("@id")) == rid for term in existing):
        raise ValueError("Vocabulary definitions are append-only; an existing term cannot be replaced")
    forbidden = {"equivalentClass", "equivalentProperty", "subClassOf", "subPropertyOf", "transitive", "inferenceRule", "inverseOf", "sameAs"}
    if forbidden.intersection(record) or record.get("mappings"):
        raise ValueError("Experimental bootstrap cannot introduce inference or equivalence mappings")
    for key in ("definition", "example", "counterexample", "existingTermsInsufficient"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError("Experimental relation requires " + key)
    classes = {term.get("id", term.get("@id")) for term in ontology.get("classes", [])}
    for key in ("domain", "range", "requiredContext"):
        values = record.get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("Experimental relation requires a unique string list for " + key)
        if key in ("domain", "range") and (not values or not set(values).issubset(classes)):
            raise ValueError("Experimental relation " + key + " must name existing classes")
    if record.get("kind") not in (None, "relation") or record.get("status") not in (None, "candidate", "experimental"):
        raise ValueError("Automatic vocabulary may stage experimental relations only")
    if _private_values(record, rid):
        raise ValueError("Experimental definition contains private data")
    term = {"id": rid, "@id": rid, "label": record.get("label") or rid, "kind": "relation", "status": "experimental",
            "definition": record["definition"], "domain": deepcopy(record["domain"]), "range": deepcopy(record["range"]),
            "requiredContext": deepcopy(record["requiredContext"]), "examples": [record["example"]], "counterexamples": [record["counterexample"]],
            "mappings": [], "existingTermsInsufficient": record["existingTermsInsufficient"],
            "validatedInstances": deepcopy(record.get("validatedInstances", [])), "review": deepcopy(record.get("review", {})),
            "history": deepcopy(record.get("history", []))}
    if not isinstance(term["label"], str) or not term["label"].strip():
        raise ValueError("Experimental relation label must be a non-empty string")
    staged = deepcopy(ontology)
    staged.setdefault("predicates", []).append(term)
    staged.setdefault("terms", []).append(deepcopy(term))
    return staged


def experimental_instance_errors(term, records_by_id):
    """Check real reviewed graph instances, never worker-declared status fields."""
    errors, claims, documents, lineages = [], set(), set(), set()
    tid = term.get("id", term.get("@id"))
    instances = term.get("validatedInstances", [])
    if not isinstance(instances, list):
        return ["Experimental relation instances must be an array"]
    for instance in instances:
        if not isinstance(instance, dict):
            errors.append("Invalid experimental relation instance")
            continue
        cid, eid = instance.get("claimId"), instance.get("evidenceId")
        claim, evidence = records_by_id.get(cid, {}), records_by_id.get(eid, {})
        checked = claim.get("status") == "agent-validated" or claim.get("validationStatus") == "agent-validated"
        if claim.get("@type") != "Claim" or not checked or claim.get("predicate") != tid or eid not in claim.get("evidence", []):
            errors.append("Required source-reviewed vocabulary instance was not assembled: " + str(cid))
            continue
        if evidence.get("@type") != "Evidence" or not evidence.get("document") or not evidence.get("lineageId"):
            errors.append("Vocabulary instance has unresolved source identity: " + str(eid))
            continue
        claims.add(cid)
        documents.add(evidence["document"])
        lineages.add(evidence["lineageId"])
    if len(claims) < 2 or len(documents) < 2 or len(lineages) < 2:
        errors.append("Experimental relation requires two assembled source-reviewed claims from two documents and source lineages")
    return errors


def validate_records(records, ontology=None):
    """Return errors. Candidate incompleteness is allowed; accepted facts are gated."""
    ontology = ontology or get_ontology()
    classes = {r.get("id", r.get("@id")) for r in ontology.get("classes", [])}
    predicates = {r.get("id", r.get("@id")): r for r in ontology.get("predicates", [])}
    if not classes:
        classes = {r.get("id", r.get("@id")) for r in ontology.get("terms", []) if r.get("kind") == "class"}
    if not predicates:
        predicates = {r.get("id", r.get("@id")): r for r in ontology.get("terms", []) if r.get("kind") == "relation"}
    errors = []
    by_id = {}
    for record in records:
        if not isinstance(record, dict):
            errors.append("Every record must be an object")
            continue
        rid = record.get("@id")
        if not isinstance(rid, str) or not rid or any(c.isspace() or c in '<>"{}|^`\\' for c in rid):
            errors.append("Missing or invalid record @id")
            continue
        if rid in by_id:
            errors.append(rid + ": duplicate identifier")
        if any(key.startswith("@") and key not in {"@id", "@type"} for key in record):
            errors.append(rid + ": record-level JSON-LD directives cannot override the release context")
        by_id[rid] = record
        if record.get("@type") not in classes:
            errors.append(rid + ": unknown record type " + str(record.get("@type")))
        if not isinstance(record.get("label"), str) or not record["label"].strip():
            errors.append(rid + ": non-empty label required")
        if record.get("status") not in STATUSES:
            errors.append(rid + ": invalid or missing status")
        errors.extend(_private_values(record, rid))
    for rid, record in by_id.items():
        kind = record.get("@type")
        source_validated = record.get("status") == "agent-validated" or record.get("validationStatus") == "agent-validated"
        evidence = record.get("evidence", [])
        # A proposal may be incomplete, but an explicit conversion must never
        # claim deterministic validity merely because it has not been reviewed.
        errors.extend(rid + ": " + error for error in quantity_errors(record))
        if not isinstance(evidence, list):
            errors.append(rid + ": evidence must be an array")
            evidence = []
        for eid in evidence:
            if not isinstance(eid, str) or by_id.get(eid, {}).get("@type") != "Evidence":
                errors.append(rid + ": unresolved evidence " + str(eid))
        if kind == "Evidence":
            if by_id.get(record.get("document"), {}).get("@type") != "Document":
                errors.append(rid + ": unresolved document")
            for key in ("locator", "lineageId", "accessedDate", "permissionBasis"):
                if not record.get(key):
                    errors.append(rid + ": evidence requires " + key)
            if record.get("accessStatus") != "anonymous_full_content":
                errors.append(rid + ": evidence requires anonymous full content declaration")
            if record.get("reuseStatus") not in REUSE:
                errors.append(rid + ": missing or unsupported reuse status")
            if not _public_url(record.get("contentUrl") or record.get("url")):
                errors.append(rid + ": evidence requires a public HTTP(S) URL")
        if kind == "Section":
            if not isinstance(record.get("text"), str):
                errors.append(rid + ": section text must be a string")
            elif record["text"].strip() and not evidence:
                errors.append(rid + ": non-empty section requires evidence")
            for eid in evidence:
                if record.get("sectionKey") not in by_id.get(eid, {}).get("supports", []):
                    errors.append(rid + ": evidence does not support this section")
        if kind == "Structure":
            mol = record.get("molfileV3000", "")
            if not isinstance(mol, str) or "V3000" not in mol or "M  END" not in mol:
                errors.append(rid + ": canonical MDL V3000 is required")
            elif record.get("molfileSha256") != hashlib.sha256(mol.encode("utf-8")).hexdigest():
                errors.append(rid + ": V3000 checksum mismatch")
        if kind == "Claim":
            for endpoint in ("subject", "object"):
                value = record.get(endpoint)
                if not isinstance(value, str) or value not in by_id:
                    errors.append(rid + ": unresolved " + endpoint)
            predicate = predicates.get(record.get("predicate"))
            if not predicate:
                errors.append(rid + ": unknown predicate")
            else:
                if predicate.get("status") == "experimental" and record.get("status") not in ("experimental", "candidate", "disputed", "superseded"):
                    errors.append(rid + ": experimental predicate instances must remain opt-in")
                for endpoint, type_key in (("subject", "domain"), ("object", "range")):
                    allowed = predicate.get(type_key, [])
                    endpoint_type = by_id.get(record.get(endpoint), {}).get("@type")
                    if allowed and endpoint_type and endpoint_type not in allowed:
                        errors.append(rid + ": " + endpoint + " violates predicate " + type_key)
                context = record.get("context")
                if not isinstance(context, dict):
                    errors.append(rid + ": context must be an object")
                elif source_validated or record.get("status") not in ("candidate", "experimental"):
                    for key in predicate.get("requiredContext", []):
                        if key not in context or context[key] in (None, "", []):
                            errors.append(rid + ": missing predicate context " + key)
                    if record.get("predicate") == "comparableFor" and source_validated:
                        compat = context.get("compatibleConditions")
                        if compat in ("unknown", "unreported", False) or isinstance(compat, dict) and compat.get("status") in ("unknown", "unreported"):
                            errors.append(rid + ": unreported conditions do not establish comparability")
        if kind == "Observation":
            subject = record.get("subject")
            if not isinstance(subject, str) or subject not in by_id:
                errors.append(rid + ": unresolved observation subject")
            elif by_id[subject].get("@type") not in {"Material", "Specimen"}:
                errors.append(rid + ": observation subject must identify a material or specimen, not a polymer family")
            if not isinstance(record.get("property"), str) or not record["property"].strip():
                errors.append(rid + ": observation requires an identified property")
        if kind == "Recipe" and record.get("status") in {"experimental", "reuse-tested"}:
            if record.get("layer") != "memory":
                errors.append(rid + ": experimental recipe belongs to the memory layer")
            supporting = record.get("supportingClaims", [])
            if not isinstance(supporting, list) or not supporting:
                errors.append(rid + ": experimental recipe requires supporting assertions")
                supporting = []
            for cid in supporting:
                claim = by_id.get(cid, {})
                if claim.get("@type") not in {"Claim", "Observation"}:
                    errors.append(rid + ": unresolved supporting assertion " + str(cid))
                elif "agent-validated" not in {claim.get("status"), claim.get("validationStatus")}:
                    errors.append(rid + ": experimental recipe requires source-validated support")
        if source_validated and kind in ("Claim", "Observation"):
            if not evidence:
                errors.append(rid + ": accepted scientific assertion requires evidence")
            context = record.get("context", {})
            if not isinstance(context, dict):
                context = {}
            for key in ("materialScope", "claimType"):
                if not context.get(key):
                    errors.append(rid + ": accepted assertion requires " + key)
            if context.get("claimType") not in ("reported", "derived", "synthesis"):
                errors.append(rid + ": claimType must be reported, derived, or synthesis")
            quantitative = (kind == "Observation" or record.get("quantitative") or context.get("quantitative")
                            or any(k in context for k in ("value", "range", "normalizedValue", "normalizedRange")))
            if context.get("claimType") == "derived" and not context.get("derivation"):
                errors.append(rid + ": derived assertions require reproducible derivation")
            if quantitative:
                for key in QUANTITATIVE_KEYS:
                    if key not in context or context[key] in (None, ""):
                        errors.append(rid + ": quantitative assertion requires explicit " + key)
                value, range_ = context.get("value"), context.get("range")
                if kind == "Observation":
                    valid_range = isinstance(range_, list) and len(range_) == 2 and all(is_number(x) for x in range_) and range_[0] <= range_[1]
                    if not is_number(value) and not valid_range:
                        errors.append(rid + ": observation requires numeric context.value or ordered context.range")
            if context.get("claimType") == "synthesis" and (context.get("scopeLevel") == "family" or context.get("materialScope") == "family"):
                docs = {by_id[e]["document"] for e in evidence if e in by_id and "document" in by_id[e]}
                lineages = {by_id[e].get("lineageId") for e in evidence if e in by_id and by_id[e].get("lineageId")}
                if len(docs) < 2 or len(lineages) < 2:
                    errors.append(rid + ": family synthesis requires two documents and source lineages")
            review = record.get("review", {})
            if not isinstance(review, dict):
                review = {}
            if review.get("decision") != "pass" or review.get("independent") is not True:
                errors.append(rid + ": accepted assertion requires independent passing review")
            producer, reviewer = review.get("producerRunId"), review.get("reviewerRunId")
            if not producer or not reviewer or producer == reviewer:
                errors.append(rid + ": producer and reviewer runs must be distinct")
            checks = {c.get("evidenceId"): c for c in review.get("sourceChecks", []) if isinstance(c, dict)}
            for eid in evidence:
                check = checks.get(eid, {})
                if not all(check.get(k) is True for k in ("anonymousFullContent", "locatorSupported", "rightsRecorded")) or not check.get("checkedAt"):
                    errors.append(rid + ": accepted assertion requires fresh source check for " + str(eid))
    return errors
