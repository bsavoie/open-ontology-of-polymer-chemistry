"""Shared fixtures moved from tests/test_validation.py (TD-17)."""
import unittest
from copy import deepcopy
from oopc.validation import validate_records


def accepted_fixture():
    records = [
        {"@id": "material:grade", "@type": "Material", "label": "Explicit grade", "status": "candidate"},
        {"@id": "document:paper", "@type": "Document", "label": "Source", "status": "candidate"},
        {"@id": "evidence:paper", "@type": "Evidence", "label": "Observation source", "status": "candidate",
         "document": "document:paper", "locator": "Table 2, row A", "lineageId": "lab-a", "accessedDate": "2026-09-10",
         "url": "https://example.org/full-paper", "accessStatus": "anonymous_full_content", "reuseStatus": "publicly_accessible_citation_only", "permissionBasis": "Citation and paraphrase"},
        {"@id": "observation:strength", "@type": "Observation", "label": "Qualified strength", "status": "agent-validated", "layer": "science",
         "subject": "material:grade", "property": "tensile strength", "evidence": ["evidence:paper"], "context": {"materialScope": "Named grade only", "claimType": "reported", "material": "material:grade",
             "specimen": "Source specimen A", "method": "Source test method", "conditions": {"temperature": "reported in source"},
             "value": 10.0, "units": "MPa", "uncertainty": "unreported", "limitations": "Not a family-wide value"},
         "review": {"decision": "pass", "independent": True, "producerRunId": "run-a", "reviewerRunId": "run-b",
                    "sourceChecks": [{"evidenceId": "evidence:paper", "anonymousFullContent": True, "locatorSupported": True, "rightsRecorded": True, "checkedAt": "2026-09-10T00:00:00Z"}]}}
    ]
    return records
