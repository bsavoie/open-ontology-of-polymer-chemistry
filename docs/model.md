# Data model and release contract

The authoritative companion data are the versioned canonical records and ontology. SQLite, RDF, and Markdown are projections. The WOP importer reads the v2 snapshot without changing it; it does not perform new literature research, extract normalized measurements from prose, alter a V3000 structure, or upgrade scientific maturity.

## Canonical records

Every record has `@id`, `@type`, `label`, and `status`. Scientific assertions use `Claim` records with `subject`, `predicate`, `object`, `context`, `evidence`, and review/provenance history. A relationship is therefore independently addressable, including when several differently qualified assertions share endpoints. Missing relationships express no conclusion.

Identity types distinguish `PolymerConcept`, `Material`, `Specimen`, `Process`, `Observation`, `Dataset`, `Document`, `Evidence`, `Structure`, `Section`, `Claim`, `Recipe`, `ResearchEpisode`, and `Facet`. Grades and measured specimens must not be collapsed into family identities. The initial import creates no synthetic grades, specimens, datasets, or measurements from article text.

The scientific profile links these distinct identities explicitly:

| Relationship | Direction | Required scope |
|---|---|---|
| `materialOf` | Material → PolymerConcept | `materialScope` |
| `specimenOf` | Specimen → Material | `preparation`, `conditioning` |
| `hasProcess` | Concept, material, or specimen → Process | `scopeNote` |
| `measuredProperty` | Material or specimen → Observation | `material`, `specimen`, `method`, `conditions` |
| `containsObservation` | Dataset → Observation | `materialScope` |
| `comparableFor` | Dataset or observation → Dataset or observation | `property`, `materialScope`, `compatibleConditions`, `comparisonMethod` |

These are independently qualified Claim records. A dataset membership does not establish comparability, and a grade's family membership does not turn a grade measurement into a family constant. Unknown preparation or conditioning remains explicit. Conflicting observations remain separate records even when they describe the same specimen.

WOP identities stay `wop-NNNNNN`. Article evidence uses `evidence:wop-NNNNNN:sourceId`; methodology evidence uses `evidence:methodology:sourceId`. Document IDs separately hash a normalized DOI or canonical source URL. Distinct occurrences sharing a document retain their own locators, supported sections, access declarations, and reuse rights. DOI reconciliation removes standard DOI URL prefixes and lowercases the DOI; URL reconciliation lowercases scheme/host and strips fragments while retaining path and query. An evidence occurrence without DOI inherits a DOI for its exact canonical URL only if the source catalog has one unambiguous DOI there.

Sections preserve their strings, including empty gaps, verbatim under the wiki's CC BY 4.0 attribution. Original structured data retain CC0, and linked source material retains its own rights. All source fields are copied, with the exact source object retained. The importer never downloads or redistributes linked full text.

Canonical MDL V3000 strings retain their UTF-8 bytes and SHA-256 hashes. Shared structure identity is separate from each `hasStructure` claim's exact/representative/schematic fidelity, placement, scope note, caption, notation, and imported review status. Imported `reviewed` depiction metadata remains metadata of the source wiki; the new claim still has `status: seed` and `verified: false`.

Taxonomy uses one `Facet` for each `(axis,value)`, with `hasFacet` claims. Axes overlap. The `primaryClass` context has `browsingOnly: true`. Synthesis outlines are `Process` records with the full original route retained; route input/product edges refer only to explicit structure IDs. Unstructured names are not resolved into guessed entities.

## Status and admission

These statuses belong to the graph record format and its validator
(`oopc/validation.py`). Since the core loop, no workflow proposes or admits graph
records: the graph changes only by importing the wiki seed, and what research
finds is kept as findings in the knowledge store, with the statuses Reviewed,
Added, Needs checking and Rejected (see [the core loop](core-loop.md)).

`seed` retains source-wiki declarations without new verification. `candidate` and `experimental` preserve proposals that have not passed their admission gates. `agent-validated` scientific claims and observations require evidence, material scope, reported/derived/synthesis classification, distinct producer/reviewer runs, independent passing review, and fresh source-specific checks. Quantitative observations additionally require explicit material, specimen, method, conditions, units, uncertainty, and limitations. An explicit unknown is allowed in a measurement record but cannot establish compatible test conditions for a comparison.

New experimental relation definitions and their first instances are committed as one group. The coordinator may stage a structural definition privately to check its domain, range, and required context before publication. It then requires at least two independently source-reviewed claim instances from two distinct documents and source lineages. A missing or invalid required instance withholds the definition and all claims depending on it; staging alone grants no scientific or publication status.

Published instances of an experimental predicate carry `status: experimental` and `validationStatus: agent-validated`, alongside the actual independent review receipt. The first field keeps retrieval opt-in; the second records source review without asserting stable vocabulary. All scientific evidence, scope, and qualifier checks still apply. A worker-declared instance status never substitutes for an assembled, reviewed claim. Automatic vocabulary cannot alter core definitions or inference semantics.

Evidence metadata uses controlled values for admission:

| Field | Contract |
| --- | --- |
| `accessStatus` | `anonymous_full_content` only after inspecting substantive content without login. A successful request, abstract or challenge page is insufficient. |
| `reuseStatus` | `open_licensed`, `public_domain`, or `publicly_accessible_citation_only`, according to the inspected rights. Public access alone does not establish an open license. |
| `permissionBasis` | The license name and source statement, public-domain basis, or explanation that citation/paraphrase is used without established redistribution rights. |
| `contentUrl`, `locator`, `lineageId` | Direct content URL, precise supporting location and independent source lineage. |

Keep descriptive explanations in their descriptive fields. Do not silently
normalize an earlier rejected record or assert eligibility merely to pass a
schema. A corrected submission gets a new revision and independent source review.
Future researcher prompts include these exact values; benchmark and source-review
prompts retain their separate execution conditions.

Reviews use:

```json
{
  "decision": "pass",
  "independent": true,
  "producerRunId": "research-run",
  "reviewerRunId": "isolated-review-run",
  "sourceChecks": [{
    "evidenceId": "evidence:example",
    "anonymousFullContent": true,
    "locatorSupported": true,
    "rightsRecorded": true,
    "checkedAt": "2026-09-10T00:00:00Z"
  }]
}
```

This structural contract checks review provenance; it does not itself authenticate a reviewer or certify scientific truth. The proposal/admission workflow is responsible for creating and retaining the independent review artifact. Derived records must retain reproducible derivation. Family-level synthesis requires at least two documents and source lineages. Disputed and superseded observations remain addressable; conflict never silently deletes history.

## Quantities and unit conversion

`Observation.context` preserves the reported `value` or ordered `range`, original `units`, and material/test qualifications. Optional `normalizedValue` or `normalizedRange` must correspond to the same original scalar or range and name `normalizedUnits`. Normalization cannot replace a reported interval with its midpoint.

The dependency-free unit profile checks actual conversions and dimensions. It includes Pa/kPa/MPa/GPa, Kelvin/Celsius, percent/dimensionless values, common length units, and seconds/minutes/hours. Unknown original units remain valid source metadata, but unchecked normalization is rejected. Clearly named properties also receive dimensional checks; ambiguous property names are not guessed. Celsius temperature values use the scale offset; differences require explicit `quantityKind: temperature_difference`. Conversion tolerance covers numerical rounding, not experimental uncertainty.

Optional top-level `unit` and `numericValue` expose the same scalar to standard QUDT tools. `unit` must be a registered canonical QUDT IRI, and `numericValue` must convert correctly from the retained original quantity. For example, an original value of 10 MPa may have `unit: http://qudt.org/vocab/unit/PA` and `numericValue: 10000000`. These fields cannot introduce an unrelated quantity or discard the original measurement.

Registry additions require reviewed definitions and conversion tests. Research workers cannot expand the registry themselves. Unit correctness supplements source review; it does not establish that a reported number is scientifically correct.

## Ontology and RDF

`ontology.json` supplies both `classes`/`predicates` and a combined `terms` array for the inspector. Each term defines its domain/range, required contextual qualifiers, examples, counterexamples, mappings, status, and history. CRIPT and HPO are labeled design references/mapping candidates; no unsupported equivalence is asserted.

`context.json` and `graph.jsonld` provide a self-contained JSON-LD 1.1 profile. Structured metadata are RDF JSON literals so nested original data cannot accidentally become unqualified assertions. Scoped IDs such as `evidence:...` and `claim:...` are opaque absolute IRIs; WOP IDs resolve against the declared base. The explicit `experimental:` prefix resolves to `https://bsavoie.github.io/open-ontology-of-polymer-chemistry/vocab/experimental/` in both RDF and JSON-LD. The repository namespace is provisional; a permanent w3id resolver can be registered later without changing opaque record IDs. No network resolution is needed.

QUDT units are IRIs, not string literals. Information records such as Document, Evidence, Claim, Observation, Dataset, and Recipe map conservatively as subclasses of `prov:Entity`; ResearchEpisode maps to `prov:Activity`. Explicit `wasDerivedFrom`, `wasGeneratedBy`, and `generatedAtTime` fields map to their PROV-O properties. These mappings describe provenance, not scientific entailment or unverified CRIPT/HPO equivalences. Record-level JSON-LD directives cannot override the release's context.

The bundled SHACL shapes enforce structural constraints; the Python validator additionally enforces cross-record and review/qualifier constraints. RDF and JSON-LD use the same vocabulary declarations and field expansion; the optional validation test compares their parsed graphs for equivalence.

`graph.nt` contains record descriptions and reified Claim records. It deliberately does not emit a bare scientific triple for every claim, because doing so would discard status and qualifiers. `schemas/` includes the JSON schemas. These downloadable constraints are complements to the deterministic Python validator, not substitutes for source review.

## Python and SQLite interfaces

- `import_seed(snapshot_path, expected_sha256=None) -> (records, ontology, metadata)`
- `validate_records(records, ontology=None) -> list[str]`
- `build_release(destination, records, ontology, metadata) -> pathlib.Path`
- `verify_release(path) -> manifest` (raises on checksum/identity failure)
- `load_release(path) -> (records, ontology, manifest)`

`load_release`'s manifest can be passed as the next build's metadata; generated manifest fields are stripped before deriving the new identity. Canonical output sorts records by stable ID, JSON keys, and database insertion order. Source bytes, not reserialized JSON, determine the pinned seed checksum. Release identity hashes canonical records, ontology, and non-derived metadata. There are no wall-clock timestamps or private source paths in reproducible seed outputs.

SQLite schema:

```sql
records(id TEXT PRIMARY KEY, type TEXT, label TEXT, status TEXT, layer TEXT, json TEXT)
edges(id TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, status TEXT, layer TEXT, json TEXT)
records_fts USING fts5(id UNINDEXED, label, text)
```

Only Claim records populate `edges`; the complete record JSON remains available. Indexes support subject/object traversal, predicate/status/layer filtering, type filtering, and full-text search.

## Atomic publication

A build validates all records before touching an existing output, builds in an owned temporary directory beside the destination, verifies files and canonical identity, flushes file contents, then renames the complete directory. Destinations are immutable: rebuilding identical input is a verified no-op; different content requires a different destination. Unknown directories and the last good release are never overwritten. A failed import/build removes only its staging directory.

A release includes canonical JSONL, ontology/context, JSON-LD, N-Triples, SHACL/JSON schemas, SQLite, Markdown pages, and a file-checksum manifest. Checksums detect accidental changes; they are not publisher signatures. User trajectories and credentials are separate from canonical releases. Metadata with private filesystem paths or secret-bearing keys is rejected.

## Knowledge snapshots

A graph release carries the seed only. What the loop has found is published
separately as a knowledge snapshot (`oopc knowledge --export`; see
[the core loop](core-loop.md)): findings and source notes with their statuses and
review verdicts, named by a hash of their content and of the graph release they
were made against. `oopc knowledge --import` starts an empty workspace from one.

## Retired workflows

The 0.11 workflows that proposed and admitted research results into the graph
(experimental relations, private recipe evaluation, reviewer qualification)
were retired; their code and documentation remain at tag `v0.11.6`, and their
records stay on disk.
