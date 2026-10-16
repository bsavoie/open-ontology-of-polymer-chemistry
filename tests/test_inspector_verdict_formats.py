"""Malformed historical verdicts remain readable without retrospective approval."""
import copy
import tempfile
import unittest
from pathlib import Path

from oopc.inspector_summary import evaluation_denominators, evaluation_summary, read_run_summary, summarize_run
from oopc.release import build_release
from oopc.trace import TraceStore
from oopc.vocabulary import get_ontology


class InspectorVerdictFormatTests(unittest.TestCase):
    def summary(self, review):
        return summarize_run({}, [{"kind": "review", "event_id": "review", "sequence": 1}],
                             [dict(review, event_id="review")], [])

    def test_nested_historical_passes_are_unclassified_not_new_grades(self):
        review = {"verdict": "fail", "findings": [
            {"claimId": "claim:one", "verdict": {"verdict": "pass", "rationale": "Recorded source judgment"}},
            {"claimId": "claim:two", "verdict": "pass"}]}
        original = copy.deepcopy(review)
        result = self.summary(review)
        self.assertEqual(result["claimFindings"], {"pass": 1, "fail": 0, "uncertain": 0, "unclassified": 1})
        self.assertEqual(result["evaluation"]["reportedVerdict"], "fail")
        self.assertEqual(result["evaluation"]["qualification"], "unqualified-review")
        self.assertEqual(result["evaluation"]["scores"], {})
        self.assertEqual(review, original)

    def test_non_string_finding_verdicts_never_crash_or_count_as_pass(self):
        invalid = [{"verdict": "pass"}, ["pass"], None, True, 1, "PASS", "", "unknown"]
        result = self.summary({"findings": [{"verdict": verdict} for verdict in invalid]})
        self.assertEqual(result["claimFindings"]["unclassified"], len(invalid))
        self.assertEqual(result["claimFindings"]["pass"], 0)
        self.assertEqual(result["evaluation"]["scores"], {})

    def test_non_mapping_findings_and_malformed_collection_have_no_support_credit(self):
        result = self.summary({"findings": [None, "pass", ["pass"]]})
        self.assertEqual(result["claimFindings"]["unclassified"], 3)
        for findings in (None, {"verdict": "pass"}, "pass"):
            with self.subTest(findings=findings):
                result = self.summary({"findings": findings})
                self.assertEqual(result["claimFindings"]["pass"], 0)
                self.assertEqual(result["evaluation"]["scores"], {})

    def test_unhashable_overall_and_reported_verdicts_remain_unclassified(self):
        for verdict in ({"verdict": "pass"}, ["pass"]):
            with self.subTest(verdict=verdict):
                ordinary = evaluation_summary({"verdict": verdict})
                self.assertEqual(ordinary["qualification"], "not-recorded")
                self.assertIsNone(ordinary["reportedVerdict"])
                for qualified in (True, False):
                    result = evaluation_summary({"evaluation": {
                        "independentlySourceChecked": qualified, "reviewVerdict": verdict,
                        "reviewerReportedVerdict": verdict}})
                    self.assertIsNone(result["verdict"])
                    self.assertIsNone(result["reportedVerdict"])
                    self.assertEqual(result["scores"], {})

    def test_malformed_assessment_verdict_or_kind_does_not_invent_zero_denominators(self):
        for field in ("verdict", "kind"):
            for value in ({"verdict": "pass"}, ["pass"]):
                claim = {"claimId": "c", "kind": "scientific-claim", "verdict": "pass", "citations": []}
                claim[field] = value
                evaluation = {"independentlySourceChecked": True, "completeAnswerCoverage": True,
                              "answerClaimAssessments": [claim]}
                self.assertEqual(evaluation_denominators(evaluation),
                                 {"scientificClaims": None, "scientificSupportLinks": None})

    def test_malformed_citation_role_and_coverage_outcome_do_not_crash(self):
        evaluation = {"independentlySourceChecked": True, "completeAnswerCoverage": True,
            "answerClaimAssessments": [{"claimId": "c", "kind": "scientific-claim", "verdict": "pass",
                "citations": [{"evidenceId": "e", "role": {"role": "support"}}]}],
            "taskCoverageChecks": {"bad": {"outcome": ["supported-answer"]},
                                   "valid": {"outcome": "correctly-scoped-abstention"}}}
        result = evaluation_summary({"evaluation": evaluation})
        self.assertEqual(result["assessmentCounts"], {"scientificClaims": 1, "scientificSupportLinks": None})
        self.assertEqual(result["coverageOutcomes"], {"correctly-scoped-abstention": 1})

    def test_reading_real_trace_shape_preserves_all_saved_review_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            release = build_release(root / "releases/fixture", [{"@id": "p", "@type": "PolymerConcept",
                "label": "Fixture", "status": "seed", "layer": "science"}], get_ontology(), {})
            run = TraceStore(root).create(release)
            run.artifact({"verdict": "fail", "findings": [{"claimId": "claim:one",
                "verdict": {"verdict": "pass", "rationale": "Historical raw review"}}]}, kind="review")
            paths = [run.path / name for name in ("run.json", "events.jsonl")] + list((run.path / "payloads").glob("*.json"))
            before = {path: path.read_bytes() for path in paths}
            events = run.events()
            result = read_run_summary(run, run.meta())
            self.assertEqual(result["claimFindings"]["unclassified"], 1)
            self.assertEqual(result["claimFindings"]["pass"], 0)
            self.assertEqual(result["evaluation"]["reportedVerdict"], "fail")
            self.assertEqual(result["evaluation"]["scores"], {})
            self.assertEqual(run.events(), events)
            self.assertEqual({path: path.read_bytes() for path in paths}, before)
