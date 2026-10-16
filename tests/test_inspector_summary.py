"""Execution, evaluation, and observed retrieval cannot substitute for each other."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from oopc.inspector_summary import read_run_summary, summarize_run
from oopc.release import build_release
from oopc.trace import TraceStore
from oopc.vocabulary import get_ontology


class InspectorSummaryTests(unittest.TestCase):
    def review(self, evaluation):
        events = [{"event_id": "review", "sequence": 1, "kind": "review"}]
        artifacts = [{"event_id": "review", "evaluation": evaluation,
                      "findings": [{"claimId": "supported", "verdict": "pass"}]}]
        return summarize_run({"status": "completed"}, events, artifacts, [])

    def test_qualified_overall_failure_retains_separate_passing_claim(self):
        summary = self.review({"independentlySourceChecked": True, "reviewVerdict": "fail",
                               "reviewerReportedVerdict": "pass", "status": "agent-source-checked"})
        self.assertEqual(summary["evaluation"]["verdict"], "fail")
        self.assertEqual(summary["evaluation"]["qualification"], "source-checked")
        self.assertEqual(summary["claimFindings"]["pass"], 1)

    def test_unscorable_reported_pass_is_not_a_task_pass(self):
        summary = self.review({"independentlySourceChecked": False, "reviewVerdict": "pass",
                               "status": "source-verification-incomplete"})
        self.assertEqual(summary["evaluation"]["qualification"], "unscorable")
        self.assertIsNone(summary["evaluation"]["verdict"])
        self.assertEqual(summary["evaluation"]["reportedVerdict"], "pass")

    def test_partial_failure_keeps_continuous_scores_and_coverage_counts(self):
        evaluation = {"independentlySourceChecked": True, "reviewVerdict": "fail",
            "supportedCorrectness": 1, "qualificationScore": 1, "citationEntailment": 1,
            "abstentionScore": 1, "taskCompletionScore": 2/3, "fullResearchCoverage": 1/3,
            "taskCoverageChecks": {"a": {"outcome": "supported-answer", "rationale": "PRIVATE"},
                                   "b": {"outcome": "correctly-scoped-abstention"},
                                   "c": {"outcome": "missed-available-evidence"}}}
        summary = self.review(evaluation)["evaluation"]
        self.assertEqual(summary["scores"]["supportedCorrectness"], 1)
        self.assertEqual(summary["scores"]["taskCompletionScore"], 2/3)
        self.assertEqual(summary["coverageOutcomes"]["correctly-scoped-abstention"], 1)
        self.assertEqual(summary["verdict"], "fail")
        self.assertNotIn("PRIVATE", json.dumps(summary))

    def test_unscorable_and_invalid_numbers_cannot_be_graded(self):
        for value in (True, float('nan'), float('inf'), -.01, 1.1, '0.8'):
            summary = self.review({"independentlySourceChecked": True,
                                  "supportedCorrectness": value})["evaluation"]
            self.assertNotIn("supportedCorrectness", summary["scores"])
        summary = self.review({"independentlySourceChecked": False, "supportedCorrectness": 1,
                              "taskCoverageChecks": {"x": {"outcome": "supported-answer"}}})["evaluation"]
        self.assertEqual(summary["scores"], {})
        self.assertEqual(summary["coverageOutcomes"], {})

    def test_no_scientific_assertions_keeps_original_scores_but_counts_zero(self):
        evaluation = {"independentlySourceChecked": True, "completeAnswerCoverage": True,
            "reviewVerdict": "fail", "supportedCorrectness": 1, "citationEntailment": 1,
            "supportLinks": 0, "answerClaimAssessments": [
                {"claimId": "gap", "kind": "abstention", "verdict": "pass", "text": "PRIVATE", "citations": []},
                {"claimId": "context", "kind": "corpus-attribution", "verdict": "pass", "citations": [
                    {"evidenceId": "source", "role": "corpus-attribution"}]}]}
        original = copy.deepcopy(evaluation)
        result = self.review(evaluation)["evaluation"]
        self.assertEqual(result["assessmentCounts"], {"scientificClaims": 0, "scientificSupportLinks": 0})
        self.assertEqual(result["scores"]["supportedCorrectness"], 1)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(evaluation, original)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_assessed_denominators_count_links_per_claim_not_unique_sources(self):
        evaluation = {"independentlySourceChecked": True, "completeAnswerCoverage": True,
            "supportLinks": 2, "answerClaimAssessments": [
                {"claimId": "one", "kind": "scientific-claim", "verdict": "pass", "citations": [
                    {"evidenceId": "source", "role": "support"}]},
                {"claimId": "two", "kind": "scientific-claim", "verdict": "uncertain", "citations": [
                    {"evidenceId": "source", "role": "support"}]}]}
        result = self.review(evaluation)["evaluation"]
        self.assertEqual(result["assessmentCounts"], {"scientificClaims": 2, "scientificSupportLinks": 2})
        evaluation["supportLinks"] = 0
        self.assertEqual(self.review(evaluation)["evaluation"]["assessmentCounts"],
                         {"scientificClaims": 2, "scientificSupportLinks": None})

    def test_absent_incomplete_or_malformed_assessments_never_imply_zero(self):
        claim = {"claimId": "one", "kind": "abstention", "verdict": "pass", "citations": []}
        for fields in ({}, {"answerClaimAssessments": []}, {"answerClaimAssessments": [claim, claim]},
                       {"answerClaimAssessments": [dict(claim, kind="unknown")]},
                       {"answerClaimAssessments": [claim], "completeAnswerCoverage": False}):
            evaluation = {"independentlySourceChecked": True, "completeAnswerCoverage": True, **fields}
            self.assertEqual(self.review(evaluation)["evaluation"]["assessmentCounts"],
                             {"scientificClaims": None, "scientificSupportLinks": None})
        evaluation = {"independentlySourceChecked": False, "completeAnswerCoverage": True,
                      "answerClaimAssessments": [claim]}
        self.assertEqual(self.review(evaluation)["evaluation"]["assessmentCounts"],
                         {"scientificClaims": None, "scientificSupportLinks": None})

    def test_empty_and_unlinked_reviews_cannot_invent_results(self):
        summary = summarize_run({"status": "completed"}, [], [{"verdict": "pass"}], [])
        self.assertEqual(summary["evaluation"]["qualification"], "not-recorded")
        self.assertIsNone(summary["evaluation"]["verdict"])
        self.assertEqual(sum(summary["claimFindings"].values()), 0)
        self.assertEqual(summary["condition"]["cohortStatus"], "not-recorded")

    def test_graph_memory_without_returned_recipes_is_zero_use_evidence(self):
        events = [{"event_id": "lookup", "kind": "access", "operation": "get_recipes", "status": "ok", "result_ids": []}]
        summary = summarize_run({"task": {"mode": "graph-memory"}}, events, [], [])
        self.assertEqual(summary["retrieval"]["recipeLookupCalls"], 1)
        self.assertEqual(summary["retrieval"]["returnedRecipes"], 0)
        self.assertEqual(summary["retrieval"]["deliveredRecipes"], 0)

    def test_returned_edges_and_recipes_are_not_implicit_traversal_or_delivery(self):
        records = [{"@id": "recipe", "@type": "Recipe"}, {"@id": "edge", "@type": "Claim"},
                   {"@id": "fragment", "@type": "RecordFragment", "sourceRecordId": "missing-edge"}]
        events = [{"kind": "access", "operation": "search", "status": "ok", "result_ids": ["recipe", "edge", "fragment"]},
                  {"kind": "access", "operation": "traverse", "status": "error", "traversed_edges": ["edge"]}]
        summary = summarize_run({}, events, [], records)["retrieval"]
        self.assertEqual(summary["returnedRelationships"], 1)
        self.assertEqual(summary["returnedProjections"], 1)
        self.assertEqual(summary["traversedRelationships"], 0)
        self.assertEqual(summary["returnedRecipes"], 1)
        self.assertEqual(summary["deliveredRecipes"], 0)
        self.assertEqual(summary["citedRecipes"], 0)

    def test_latest_attached_review_controls_current_verdict(self):
        events = [{"event_id": "old", "kind": "review", "sequence": 1}, {"event_id": "new", "kind": "review", "sequence": 2}]
        artifacts = [{"event_id": "new", "evaluation": {"independentlySourceChecked": False, "reviewVerdict": "pass"}},
                     {"event_id": "old", "evaluation": {"independentlySourceChecked": True, "reviewVerdict": "pass"}}]
        summary = summarize_run({}, events, artifacts, [])
        self.assertEqual(summary["evaluation"]["eventId"], "new")
        self.assertEqual(summary["evaluation"]["qualification"], "unscorable")

    def test_source_attachments_are_capture_gaps_not_access_receipts(self):
        artifacts = [{"type": "external_evidence", "records": [{"@id": "source"}],
                      "source_checks": [{"anonymousFullContent": True}], "content": {"source": {"status": "excluded"}}}]
        summary = summarize_run({}, [], artifacts, [])
        self.assertIsNone(summary["capture"]["external_source_access"])
        self.assertEqual(summary["capture"]["missingSourceContentCount"], 1)
        self.assertEqual(summary["retrieval"]["accessCalls"], 0)

    def test_recorded_condition_is_versioned_without_inferred_current_membership(self):
        summary = summarize_run({"task": {"experimentCondition": {"adapterVersion": "0.6.7",
            "retrievalCondition": {"protocol": "oopc-budgeted-retrieval-v2"}, "privateField": "PRIVATE"}}}, [], [], [])
        self.assertTrue(summary["condition"]["recorded"])
        self.assertEqual(summary["condition"]["retrievalProtocol"], "oopc-budgeted-retrieval-v2")
        self.assertEqual(summary["condition"]["cohortStatus"], "not-recorded")
        self.assertNotIn("PRIVATE", json.dumps(summary))

    def test_read_only_summary_uses_exact_run_and_omits_private_review_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = build_release(root/"releases/fixture", [{"@id": "p", "@type": "PolymerConcept", "label": "Fixture", "status": "seed", "layer": "science"}], get_ontology(), {})
            run = TraceStore(root).create(release)
            run.artifact({"evaluation": {"independentlySourceChecked": True, "reviewVerdict": "fail",
                          "referenceConclusionChecks": {"PRIVATE_REFERENCE": "PRIVATE_TEXT"}, "reviewerSessionId": "PRIVATE_SESSION"},
                          "findings": [{"verdict": "pass"}]}, kind="review")
            before = {name: (run.path/name).read_bytes() for name in ("run.json", "events.jsonl")}
            events = run.events()
            summary = read_run_summary(run, run.meta())
            self.assertEqual(summary["evaluation"]["verdict"], "fail")
            self.assertNotIn("PRIVATE", json.dumps(summary))
            self.assertEqual(run.events(), events)
            for name, content in before.items():
                self.assertEqual((run.path/name).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
