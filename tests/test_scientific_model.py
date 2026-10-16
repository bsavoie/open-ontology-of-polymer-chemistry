import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from oopc.graph import Graph
from oopc.release import build_release
from oopc.units import canonical_unit_iri, convert_value, quantity_errors
from oopc.validation import validate_records, stage_experimental_relation
from oopc.vocabulary import BASE, get_ontology
from fixtures.validation import accepted_fixture

try:
    import rdflib
    from rdflib.compare import isomorphic
except ImportError:
    rdflib = None


def scientific_fixture():
    """Synthetic topology only. No fixture is published as scientific evidence."""
    def entity(rid, kind, **fields):
        return {"@id": rid, "@type": kind, "label": rid, "status": "candidate", "layer": "science", **fields}

    def edge(rid, subject, predicate, object_, context):
        return entity(rid, "Claim", subject=subject, predicate=predicate, object=object_, context=context, evidence=[])

    records = [entity("wop-000001", "PolymerConcept"), entity("material:grade", "Material"),
               entity("specimen:A", "Specimen"), entity("process:moulding", "Process"),
               entity("dataset:table2", "Dataset")]
    for suffix, value in (("A", 10.0), ("B", 12.0)):
        records.append(entity("observation:" + suffix, "Observation", subject="specimen:A", property="tensile strength",
                              context={"value": value, "units": "MPa", "limitations": "Synthetic test fixture"}))
    records += [
        edge("claim:material", "material:grade", "materialOf", "wop-000001", {"materialScope": "Named test grade only"}),
        edge("claim:specimen", "specimen:A", "specimenOf", "material:grade", {"preparation": "moulded", "conditioning": "unreported"}),
        edge("claim:process", "specimen:A", "hasProcess", "process:moulding", {"scopeNote": "This specimen only"}),
        edge("claim:measurement", "specimen:A", "measuredProperty", "observation:A", {"material": "material:grade", "specimen": "specimen:A", "method": "test fixture", "conditions": "unreported"}),
        edge("claim:contains", "dataset:table2", "containsObservation", "observation:A", {"materialScope": "Named test grade only"}),
        edge("claim:conflicting", "specimen:A", "measuredProperty", "observation:B", {"material": "material:grade", "specimen": "specimen:A", "method": "test fixture", "conditions": "unreported"}),
    ]
    return records


class ScientificTopologyTests(unittest.TestCase):
    def test_polymer_grade_specimen_measurement_dataset_and_process_are_connected(self):
        records = scientific_fixture()
        self.assertEqual(validate_records(records), [])
        with tempfile.TemporaryDirectory() as directory:
            release = build_release(Path(directory) / "release", records, get_ontology(), {})
            result = Graph(release).traverse("wop-000001", depth=4, status="candidate")
        self.assertEqual({node["@id"] for node in result["nodes"]},
                         {record["@id"] for record in records if record["@type"] != "Claim"})
        dataset_path = next(path for path in result["paths"] if path["node_ids"][-1] == "dataset:table2")
        self.assertEqual(dataset_path["node_ids"], ["wop-000001", "material:grade", "specimen:A", "observation:A", "dataset:table2"])
        self.assertEqual(dataset_path["directions"], ["reverse", "reverse", "forward", "reverse"])
        # Conflicting observations remain distinct objects and distinct edges.
        self.assertEqual(len([node for node in result["nodes"] if node["@type"] == "Observation"]), 2)

    def test_new_relations_enforce_types_and_scope(self):
        records = scientific_fixture()
        edge = next(record for record in records if record["@id"] == "claim:specimen")
        edge["status"] = "seed"
        edge["context"].pop("conditioning")
        self.assertTrue(any("missing predicate context conditioning" in error for error in validate_records(records)))
        edge["context"]["conditioning"] = "unreported"
        edge["object"] = "wop-000001"
        self.assertTrue(any("violates predicate range" in error for error in validate_records(records)))


class UnitAdmissionTests(unittest.TestCase):
    def test_pressure_conversion_retains_original(self):
        records = accepted_fixture()
        records[-1]["context"].update(normalizedValue=10000000, normalizedUnits="Pa")
        before = deepcopy(records)
        self.assertEqual(validate_records(records), [])
        self.assertEqual(records, before)
        self.assertEqual(canonical_unit_iri("MPa"), "http://qudt.org/vocab/unit/MegaPA")

    def test_wrong_dimension_arithmetic_and_original_property_are_rejected(self):
        for target, value, message in (("K", 99999, "incompatible dimensions"), ("Pa", 99999, "does not match")):
            with self.subTest(target=target):
                records = accepted_fixture()
                records[-1]["context"].update(normalizedValue=value, normalizedUnits=target)
                self.assertTrue(any(message in error for error in validate_records(records)))
        records = accepted_fixture()
        records[-1]["context"]["units"] = "K"
        self.assertTrue(any("property and original units" in error for error in validate_records(records)))

    def test_unknown_original_unit_survives_but_unchecked_conversion_does_not(self):
        records = accepted_fixture()
        records[-1]["context"]["units"] = "author-specific units"
        self.assertEqual(validate_records(records), [])
        records[-1]["context"].update(normalizedValue=1, normalizedUnits="Pa")
        self.assertTrue(any("registered" in error for error in validate_records(records)))

    def test_temperature_offsets_intervals_and_dimensionless_percent(self):
        self.assertAlmostEqual(convert_value(25, "°C", "K"), 298.15)
        self.assertEqual(convert_value(25, "°C", "K", "temperature_difference"), 25)
        self.assertEqual(convert_value(125, "%", "1"), 1.25)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            convert_value(25, "°C", "MPa")

    def test_range_normalization_cannot_invent_a_scalar(self):
        record = {"context": {"range": [1, 2], "units": "GPa", "normalizedRange": [1000, 2000], "normalizedUnits": "MPa"}}
        self.assertEqual(quantity_errors(record), [])
        record["context"].update(normalizedValue=1500)
        self.assertTrue(any("range cannot become a scalar" in error for error in quantity_errors(record)))
        record["context"].pop("normalizedValue")
        record["context"]["normalizedRange"] = [1000, 2100]
        self.assertTrue(any("does not match" in error for error in quantity_errors(record)))

    def test_canonical_qudt_fields_must_match_retained_quantity(self):
        records = accepted_fixture()
        observation = records[-1]
        observation.update(unit="http://qudt.org/vocab/unit/PA", numericValue=10000000)
        self.assertEqual(validate_records(records), [])
        observation["numericValue"] = 10
        self.assertTrue(any("does not agree" in error for error in validate_records(records)))
        observation["unit"] = "MPa"
        self.assertTrue(any("canonical QUDT" in error for error in validate_records(records)))

    def test_candidate_is_not_a_bypass_for_explicit_invalid_normalization(self):
        record = {"@id": "material:bad", "@type": "Material", "label": "Proposed", "status": "candidate",
                  "context": {"value": 10, "units": "MPa", "normalizedValue": 99999, "normalizedUnits": "K"}}
        self.assertTrue(any("incompatible dimensions" in error for error in validate_records([record])))

    def test_non_finite_and_unrepresentable_numbers_are_rejected(self):
        for value in (float("inf"), float("nan"), 10 ** 1000, True):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "finite original"):
                    convert_value(value, "MPa", "Pa")


class ProjectionEquivalenceTests(unittest.TestCase):
    def test_records_cannot_override_the_shared_projection_context(self):
        records = accepted_fixture()
        records[0]["@context"] = {"label": "http://example.org/different"}
        self.assertTrue(any("cannot override" in error for error in validate_records(records)))

    def build(self, root):
        records = accepted_fixture()
        records[-1].update(unit="http://qudt.org/vocab/unit/MegaPA", numericValue=10.0,
                           wasDerivedFrom=["evidence:paper"], wasGeneratedBy="episode:test",
                           generatedAtTime="2026-09-11T00:00:00Z")
        # One globally JSON-typed field is a string here and an object elsewhere.
        records[0]["originalMetadata"] = "unknown"
        records[1]["originalMetadata"] = {"source": "fixture"}
        ontology = stage_experimental_relation(get_ontology(), {
            "@id": "experimental:scopedComparison", "definition": "Test-only scoped comparison.",
            "example": "A test observation pair", "counterexample": "Unqualified equivalence",
            "existingTermsInsufficient": "Fixture exercises compact IRI identity.",
            "domain": ["Observation"], "range": ["Observation"], "requiredContext": ["scope"]})
        records.append({"@id": "claim:experimental", "@type": "Claim", "label": "Test claim", "status": "candidate",
                        "subject": records[-1]["@id"], "object": records[-1]["@id"], "predicate": "experimental:scopedComparison",
                        "context": {"scope": "fixture"}, "evidence": []})
        return build_release(root / "release", records, ontology, {})

    def test_units_are_iris_and_experimental_identifiers_share_one_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            release = self.build(Path(directory))
            rdf = (release / "graph.nt").read_text()
            graph = json.loads((release / "graph.jsonld").read_text())
        self.assertIn('<http://qudt.org/schema/qudt/unit> <http://qudt.org/vocab/unit/MegaPA>', rdf)
        self.assertIn('<' + BASE + 'vocab/experimental/scopedComparison>', rdf)
        self.assertNotIn('experimental%3A', rdf)
        self.assertEqual(graph["@context"]["experimental"], BASE + "vocab/experimental/")
        self.assertTrue(any(node.get("subClassOf") == ["prov:Entity"] for node in graph["@graph"]))

    @unittest.skipUnless(rdflib, "Install the optional validation dependencies for cross-serialization RDF checks")
    def test_complete_rdf_and_jsonld_graphs_are_equivalent(self):
        with tempfile.TemporaryDirectory() as directory:
            release = self.build(Path(directory))
            rdf = rdflib.Graph().parse(release / "graph.nt", format="nt")
            jsonld = rdflib.Graph().parse(release / "graph.jsonld", format="json-ld")
            self.assertTrue(isomorphic(rdf, jsonld), (list(rdf - jsonld)[:5], list(jsonld - rdf)[:5]))


if __name__ == "__main__":
    unittest.main()
