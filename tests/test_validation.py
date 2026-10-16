import unittest
from copy import deepcopy

from oopc.validation import validate_records
from fixtures.validation import accepted_fixture


class ValidationTests(unittest.TestCase):
    def test_qualified_independently_reviewed_measurement_passes(self):
        self.assertEqual(validate_records(accepted_fixture()), [])

    def test_self_approval_and_unsupported_claim_fail(self):
        records = accepted_fixture()
        records[-1]["review"]["reviewerRunId"] = "run-a"
        records[-1]["evidence"] = []
        errors = validate_records(records)
        self.assertTrue(any("distinct" in e for e in errors))
        self.assertTrue(any("requires evidence" in e for e in errors))

    def test_missing_qualifiers_fail_but_explicit_unknown_is_preserved(self):
        records = accepted_fixture()
        records[-1]["context"].pop("specimen")
        errors = validate_records(records)
        self.assertTrue(any("explicit specimen" in e for e in errors))
        records[-1]["context"]["specimen"] = "unreported"
        self.assertEqual(validate_records(records), [])

    def test_abstract_or_unchecked_source_cannot_be_accepted(self):
        records = accepted_fixture()
        records[2]["accessStatus"] = "abstract_only"
        records[-1]["review"]["sourceChecks"][0]["locatorSupported"] = False
        errors = validate_records(records)
        self.assertTrue(any("full content" in e for e in errors))
        self.assertTrue(any("fresh source check" in e for e in errors))

    def test_family_synthesis_requires_independent_breadth(self):
        records = accepted_fixture()
        records[-1]["context"].update({"claimType": "synthesis", "scopeLevel": "family"})
        self.assertTrue(any("two documents" in e for e in validate_records(records)))

    def test_observation_cannot_replace_original_with_normalized_or_non_numeric_value(self):
        records = accepted_fixture()
        records[-1]["context"]["value"] = "unknown"
        self.assertTrue(any("requires numeric" in e for e in validate_records(records)))
        records[-1]["context"].pop("value")
        records[-1]["context"].update({"normalizedValue": 10000000, "normalizedUnits": "Pa"})
        self.assertTrue(any("retain the original" in e for e in validate_records(records)))

    def test_duplicate_identity_bad_relation_and_private_paths_fail(self):
        records = accepted_fixture()
        records.append(deepcopy(records[0]))
        records[0]["privateNote"] = "/Users/researcher/private.pdf"
        records.append({"@id": "claim:bad", "@type": "Claim", "label": "Bad edge", "status": "seed", "layer": "science",
                        "subject": "material:grade", "predicate": "broader", "object": "document:paper", "context": {}, "evidence": []})
        errors = validate_records(records)
        self.assertTrue(any("duplicate" in e for e in errors))
        self.assertTrue(any("private filesystem" in e for e in errors))
        self.assertTrue(any("violates predicate" in e for e in errors))

    def test_unknown_compatibility_does_not_support_comparability(self):
        records = accepted_fixture()
        observation = records[-1]
        claim = {"@id": "claim:comparison", "@type": "Claim", "label": "Unsupported comparison", "status": "agent-validated", "layer": "science",
                 "subject": observation["@id"], "object": observation["@id"], "predicate": "comparableFor", "evidence": observation["evidence"],
                 "context": {"materialScope": "grade only", "claimType": "derived", "property": "tensile strength", "comparisonMethod": "unit conversion", "compatibleConditions": "unknown"},
                 "review": deepcopy(observation["review"])}
        records.append(claim)
        self.assertTrue(any("do not establish comparability" in e for e in validate_records(records)))


if __name__ == "__main__":
    unittest.main()
