"""Small, locally bundled ontology profile; definitions are not scientific assertions."""
from copy import deepcopy
from urllib.parse import urljoin

BASE = "https://bsavoie.github.io/open-ontology-of-polymer-chemistry/"
VERSION = "0.2.0"
PREFIXES = {"prov": "http://www.w3.org/ns/prov#", "qudt": "http://qudt.org/schema/qudt/",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "experimental": BASE + "vocab/experimental/"}


def expand_iri(value, vocab=False):
    """Expand precisely the compact-IRI profile shared by JSON-LD and RDF.

    Scoped record IDs such as evidence:... remain opaque absolute IRIs. The
    explicitly declared experimental: prefix resolves identically everywhere.
    """
    if ":" in value:
        prefix, suffix = value.split(":", 1)
        return PREFIXES[prefix] + suffix if prefix in PREFIXES else value
    return BASE + "vocab/" + value if vocab else urljoin(BASE + "record/", value)

_CLASS_DEFINITIONS = {
    "PolymerConcept": "A polymer identity or family boundary; not a particular manufactured grade or specimen.",
    "Material": "An identified material, grade, formulation, blend, or network with explicit composition scope.",
    "Specimen": "A particular sample or specimen with preparation and conditioning history.",
    "Process": "A source-qualified synthesis, processing, treatment, degradation, or measurement procedure.",
    "Observation": "A reported or derived measurement with material, specimen, method, conditions, units, and limitations.",
    "Document": "A bibliographic work identified separately from article-specific evidence occurrences.",
    "Dataset": "An identifiable dataset with provenance, material scope, and measurement context.",
    "Evidence": "An occurrence of supporting evidence with document, locator, access, reuse, and lineage information.",
    "Structure": "A canonical authored MDL V3000 connection table. Representation scope belongs to its qualified usage.",
    "Section": "Attributed source-wiki section text, retained as a draft synthesis rather than automatically extracted facts.",
    "Claim": "An identified, qualified assertion with independently addressable evidence and review history.",
    "Recipe": "A task-specific research strategy; usefulness is distinct from scientific truth.",
    "ResearchEpisode": "A task, deliverable, access trajectory, and review results pinned to a graph release.",
    "Facet": "A value on a non-exclusive taxonomy axis; primaryClass denotes browsing placement only.",
}
# predicate, definition, subject types, object types, required context, example, counterexample
_RELATIONS = [
    ("broader", "The object concept has a broader scope than the subject concept.", ["PolymerConcept"], ["PolymerConcept"], [], "A particular polyethylene scope points to the polyethylene family.", "A supplier grade and a specimen are not interchangeable concept families."),
    ("narrower", "The object concept has a narrower scope than the subject concept.", ["PolymerConcept"], ["PolymerConcept"], [], "A polymer family links to a narrower material concept.", "Shared application alone does not establish narrower scope."),
    ("related", "Source-attributed related concepts without an implied equivalence or inheritance rule.", ["PolymerConcept"], ["PolymerConcept"], [], "A wiki-authored related-material association.", "Related does not imply identical properties or interchangeable grades."),
    ("materialOf", "An identified grade or formulation falls within a stated polymer concept scope; the material retains its particular composition and identity.", ["Material"], ["PolymerConcept"], ["materialScope"], "A named PLA grade links to the PLA concept with its stereochemical and formulation limits.", "This link does not promote grade-specific measurements into family constants."),
    ("specimenOf", "A specific specimen is made from the identified material, retaining its preparation and conditioning history, including explicit unknowns.", ["Specimen"], ["Material"], ["preparation", "conditioning"], "An injection-moulded tensile specimen links to its reported resin grade.", "Two specimens of the same grade need not have the same morphology or test results."),
    ("containsObservation", "A source-defined dataset contains an individually qualified observation; membership alone does not establish comparability.", ["Dataset"], ["Observation"], ["materialScope"], "A tensile-test table links to a specific row's observation and material scope.", "Two values in one dataset may use incompatible specimens or test conditions."),
    ("hasFacet", "An attributed classification on one explicit, overlapping taxonomy axis.", ["PolymerConcept", "Material"], ["Facet"], ["axis"], "A concept has materialBehaviors value thermoplastic.", "A primary browsing class does not prove every member has a property."),
    ("hasSection", "An identity is described by an attributed wiki section.", ["PolymerConcept"], ["Section"], ["sectionKey"], "A concept links to its processing section.", "A section is not a normalized quantitative observation."),
    ("supportedBy", "An assertion or synthesis names an evidence occurrence; the assertion's review status qualifies support.", ["Section", "Claim", "Process", "Observation", "Recipe"], ["Evidence"], [], "A section cites a specific article-local evidence locator.", "A citation alone does not demonstrate claim-level entailment."),
    ("evidenceFrom", "An evidence occurrence refers to a bibliographic document.", ["Evidence"], ["Document"], [], "Two article-specific locators refer to the same DOI.", "Two occurrences are not merged merely because their document matches."),
    ("hasStructure", "A material concept uses a canonical structure with explicit representation and fidelity limits.", ["PolymerConcept", "Material"], ["Structure"], ["scopeNote", "fidelity", "placement"], "A family uses a representative motif with its scope note.", "A representative motif does not define every family member."),
    ("hasProcess", "A concept is associated with a source-qualified process outline.", ["PolymerConcept", "Material", "Specimen"], ["Process"], ["scopeNote"], "A concept links to an attributed representative synthesis route.", "A route outline is not a universal manufacturing recipe."),
    ("routeInput", "A process uses a depicted input within the route's stated scope.", ["Process"], ["Structure", "Material"], ["scopeNote"], "A route points to an explicitly identified feedstock structure.", "An unlabeled family member must not be inferred from a process title."),
    ("routeProduct", "A process points to an explicitly qualified product or structural reference.", ["Process"], ["Structure", "Material"], ["scopeNote", "productMode"], "A route links to a structural reference rather than implying simultaneous products.", "Alternative motifs do not prove that all are products of one experiment."),
    ("measuredProperty", "An identified specimen or material has a qualified observation.", ["Material", "Specimen"], ["Observation"], ["material", "specimen", "method", "conditions"], "A conditioned specimen links to its reported tensile measurement.", "A grade datasheet value is not a family-wide constant."),
    ("comparableFor", "Datasets or observations are comparable for a specified property and compatible measurement scope.", ["Dataset", "Observation"], ["Dataset", "Observation"], ["property", "materialScope", "compatibleConditions", "comparisonMethod"], "Two datasets can be compared for a property under documented compatible conditions.", "Mechanical comparability does not establish environmental comparability."),
    ("usesEvidence", "A research strategy or episode uses an evidence bundle; usefulness requires a separate reuse evaluation.", ["Recipe", "ResearchEpisode"], ["Evidence", "Claim", "Dataset"], ["taskScope"], "A strategy records evidence useful for a specific comparison task.", "Frequently accessed evidence is not necessarily true or useful."),
]


def get_ontology():
    classes = []
    for name, definition in _CLASS_DEFINITIONS.items():
        mappings = ([{"relation": "rdfs:subClassOf", "target": "prov:Entity", "url": PREFIXES["prov"] + "Entity"}]
                    if name in {"Document", "Evidence", "Claim", "Observation", "Dataset", "Recipe", "Section", "Structure"}
                    else [{"relation": "rdfs:subClassOf", "target": "prov:Activity", "url": PREFIXES["prov"] + "Activity"}]
                    if name == "ResearchEpisode" else [])
        classes.append({"id": name, "@id": name, "label": name, "kind": "class", "definition": definition,
                        "domain": [], "range": [], "requiredContext": [], "examples": [],
                        "counterexamples": [], "mappings": mappings, "status": "stable", "history": [{"version": "0.1.0", "change": "Initial profile definition."}] +
                        ([{"version": VERSION, "change": "Mapped information entities and research activities to PROV-O without domain equivalence claims."}] if mappings else [])})
    predicates = []
    for name, definition, domain, range_, context, example, counterexample in _RELATIONS:
        predicates.append({"id": name, "@id": name, "label": name, "kind": "relation", "definition": definition,
                           "domain": domain, "range": range_, "requiredContext": context, "examples": [example],
                           "counterexamples": [counterexample], "mappings": [], "status": "stable",
                           "history": [{"version": VERSION if name in {"materialOf", "specimenOf", "containsObservation"} else "0.1.0", "change": "Initial profile definition."}]})
    return {"version": VERSION, "namespace": BASE, "classes": classes, "predicates": predicates,
            "terms": deepcopy(classes + predicates),
            "references": [{"url": "https://www.criptapp.org/resources/api-user-guide/", "relation": "designReference"},
                           {"url": "https://github.com/emmo-repo/hyperdimensional-polymer-ontology", "relation": "mappingCandidate"}],
            "mappingPolicy": "References are design inputs; no unverified equivalence or inheritance mapping is asserted."}


def get_context():
    context = {"@version": 1.1, "@base": BASE + "record/", "@vocab": BASE + "vocab/",
               **PREFIXES, "label": "rdfs:label", "definition": "rdfs:comment",
               "subClassOf": {"@id": "rdfs:subClassOf", "@type": "@vocab", "@container": "@set"},
               "subject": {"@id": BASE + "vocab/subject", "@type": "@id"},
               "predicate": {"@id": BASE + "vocab/predicate", "@type": "@vocab"},
               "object": {"@id": BASE + "vocab/object", "@type": "@id"},
               "document": {"@id": BASE + "vocab/document", "@type": "@id"},
               "evidence": {"@id": BASE + "vocab/evidence", "@type": "@id", "@container": "@set"},
               "provenance": {"@id": BASE + "vocab/provenance", "@type": "@json"},
               "context": {"@id": BASE + "vocab/context", "@type": "@json"},
               "unit": {"@id": "qudt:unit", "@type": "@id"},
               "numericValue": "qudt:numericValue",
               "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id", "@container": "@set"},
               "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
               "generatedAtTime": {"@id": "prov:generatedAtTime", "@type": "xsd:dateTime"}}
    # Embedded evidence and authored metadata are lossless JSON, not accidental RDF nodes.
    for key in ["source", "taxonomy", "maturity", "structuralDepictions", "contextualStructures", "synthesisRoutes", "route", "history", "review", "rights", "alternateNames", "abbreviations", "sectionIds", "seedRelationships", "urls", "citations", "lineageIds", "sourceTypes", "supports"]:
        context[key] = {"@id": BASE + "vocab/" + key, "@type": "@json"}
    return {"@context": context}


def get_shapes():
    return '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix oopc: <https://bsavoie.github.io/open-ontology-of-polymer-chemistry/vocab/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

oopc:RecordShape a sh:NodeShape ;
  sh:targetSubjectsOf rdfs:label ;
  sh:property [ sh:path rdfs:label ; sh:minCount 1 ; sh:datatype xsd:string ] .
oopc:ClaimShape a sh:NodeShape ;
  sh:targetClass oopc:Claim ;
  sh:property [ sh:path oopc:subject ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path oopc:predicate ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path oopc:object ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path oopc:status ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ( "seed" "candidate" "agent-validated" "experimental" "disputed" "superseded" ) ] .
oopc:EvidenceShape a sh:NodeShape ;
  sh:targetClass oopc:Evidence ;
  sh:property [ sh:path oopc:document ; sh:minCount 1 ; sh:class oopc:Document ] ;
  sh:property [ sh:path oopc:locator ; sh:minCount 1 ; sh:minLength 1 ] ;
  sh:property [ sh:path oopc:accessStatus ; sh:minCount 1 ; sh:hasValue "anonymous_full_content" ] .
# Context, scope, review independence, and evidence eligibility are checked by
# oopc.validation in addition to these portable structural SHACL constraints.
'''
