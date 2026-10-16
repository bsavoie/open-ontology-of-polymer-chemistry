"""Authentic isolated read journals with synthetic source/model/bridge seams.

This helper never reads a real panel, contacts a service, or launches inference.
The ordinary archive reader, MCP recorder, qualification journals, reservation
accounting, production parser and independent-review arithmetic remain real.
"""
import contextlib
import copy
import json
from pathlib import Path
from unittest.mock import patch

from oopc import commissioning_captured_sources as capture
from oopc import reviewer_qualification as qualification
from oopc import reviewer_sources
from oopc.admission import canonical_hash
from oopc.answer_unit_review import condition
from oopc.critical_review import review_instructions
from oopc.evolution import read_private
from oopc.recovery import clear_reservation, register_guarded_worker
from oopc.util import atomic_json, now
import fixtures.commissioning_captured_sources as captured_fixture
import fixtures.reviewer_qualification as panel_fixture
from fixtures.benchmark_fairness import freeze as freeze_availability, witness


class RecoveryBackend(panel_fixture.ScriptedBackend):
    """Native seam: real capability reads, synthetic scientific statements."""
    def __init__(self, fixture):
        super().__init__()
        self.fixture = fixture
        self.legacy = False
        self.extra_metadata = [{"authorOnlyDiagnostic": "never-scientific-authority"}]
        self.author_mutator = None
        self.answers_encoder = json.dumps
        self.source_checks_mutator = None

    def _confinement(self):
        return None  # There is no external process in this isolated backend.

    def _call(self, role, payload, schema, context):
        worker = register_guarded_worker(purpose="model-inference")
        if worker is None:
            raise AssertionError("Synthetic native dispatch needs an actual owned reservation")
        self.fixture.worker_folders.append(Path(worker))
        response = super()._call(role, payload, schema, context)
        response.pop("capturedSourceAccess", None)
        response = json.loads(json.dumps(response).replace("source:one", self.fixture.evidence_id))
        checks = []
        for source in self.service.call("list_captured_sources", {})["sources"]:
            cursor = {"evidenceId": source["evidenceId"]}
            while cursor:
                chunk = self.service.call("read_captured_source", cursor)
                cursor = dict(chunk["next"], evidenceId=source["evidenceId"]) if chunk.get("next") else None
            checks.append({"evidenceId": source["evidenceId"], "contentSha256": source["originalSha256"],
                "projectionSha256": source["projectionSha256"], "locator": source["source"]["locator"],
                "captureLimitationsAcknowledged": True, "checkedAt": now(), "notes": "Synthetic exact source read",
                **dict.fromkeys(("anonymousFullContent", "locatorSupported", "rightsRecorded",
                    "sourceIdentitySupported", "sourceMetadataSupported", "materialTestScopePreserved"), True)})
        if self.legacy and self.source_checks_mutator is not None:
            self.source_checks_mutator(checks)
        response["sourceChecksJson"] = json.dumps(checks)
        if self.legacy and role == qualification.AUTHOR_ROLE:
            answers = json.loads(response["answersJson"])
            for answer in answers:
                answer["answerUnitsJson"] = json.loads(answer["answerUnitsJson"])
                answer["criterionMappingsJson"] = json.loads(answer["criterionMappingsJson"])
                answer["criticalCriteriaChecksJson"] = copy.deepcopy(self.extra_metadata)
            if self.author_mutator is not None:
                self.author_mutator(answers)
            response["answersJson"] = self.answers_encoder(answers)
        atomic_json(Path(worker) / "completion.json", {"workerToken": Path(worker).name,
            "reason": "completed", "returncode": 0, "cleanupComplete": True}, private=True)
        return response


class RecoveryFixture:
    """Attach cleanup to a unittest owner and expose real public recovery inputs."""
    def __init__(self, test):
        self.test = test
        source = captured_fixture.CommissioningCapturedSourcesTestsFixture(methodName="runTest")
        source.setUp()
        test.addCleanup(source.doCleanups)
        test.addCleanup(clear_reservation)
        self.source = source
        self.root, self.store, self.campaign_id = source.root, source.store, source.campaign
        source.qualify()
        self.condition = capture.condition_for_slot(self.root, source.charter, source.slot)
        self.evidence_id = source.evidence["@id"]
        self.inputs = panel_fixture.inputs()
        for value in self.inputs["cases"].values():
            value["sourceCondition"] = copy.deepcopy(self.condition)
            value["reference"]["reviewerSourceCondition"] = copy.deepcopy(self.condition)
            value["reference"]["sourceRecords"] = [copy.deepcopy(source.evidence)]
            value["corpus"]["records"][1] = copy.deepcopy(source.evidence)
        self.inputs = json.loads(json.dumps(self.inputs).replace("source:one", self.evidence_id))
        # Availability binds the exact supplied corpus, including real archived
        # evidence metadata, rather than the older minimalist source fixture.
        for value in self.inputs["cases"].values():
            layer = freeze_availability(value["reference"], value["corpus"], "available",
                [witness(value["corpus"]["records"][0], "text")])
            value["availability"]["byCorpusHash"] = {layer["allowedCorpusHash"]: layer}
        self.worker_folders = []
        self.backend = RecoveryBackend(self)
        self.parent_id = None

    @contextlib.contextmanager
    def scoped(self):
        @contextlib.contextmanager
        def server(service):
            self.backend.service = service
            yield "/private/tmp/oopc-rpc-recovery-fixture/mcp.sock"
        with patch.object(qualification, "_source_inputs", return_value=self.inputs), \
                patch("oopc.evolution_runner.CodexBackend", return_value=self.backend), \
                patch("oopc.benchmark_adapter.corpus_server", server):
            yield self

    def make_parent(self, *, seed="synthetic-recovery-order", limits=None):
        # A historical parent recorded whole-file pins (before TD-19), including the
        # two known defective files the recovery protocol names.
        from oopc.reviewer_qualification_recovery import LEGACY_RUNTIME_HASHES
        import sys
        runtime = {"codeHashes": dict(LEGACY_RUNTIME_HASHES, **{"benchmark_adapter.py": "b" * 64}),
                   "nativeContextPolicy": dict(qualification._runtime_pins()["nativeContextPolicy"],
                                               proxyCommand=sys.executable)}
        original_request = qualification._author_request
        def historical_request(intent, inputs):
            request = original_request(intent, inputs)
            request["instruction"] = request["instruction"].replace(
                qualification.AUTHOR_WIRE_INSTRUCTION, "")
            request["criticalCriteria"] = review_instructions(inputs["case"], inputs["reference"])
            return request
        legacy_stages = reviewer_sources.JSON_CHECK_COMMISSIONING_STAGES - {
            "qualification-author", "qualification-adjudicator", "reviewer-qualification"}
        from oopc.benchmark_adapter import MODEL_CONFIGURATION
        # Historical parents recorded the single Codex configuration (before TD-24).
        with self.scoped(), patch.object(qualification, "_runtime_pins", return_value=runtime), \
                patch("oopc.worker_runtime.pooled_runtime_policy", return_value=dict(MODEL_CONFIGURATION)), \
                patch.object(qualification, "_author_request", side_effect=historical_request), \
                patch.object(reviewer_sources, "JSON_CHECK_COMMISSIONING_STAGES", legacy_stages):
            self.backend.legacy = True
            try:
                registered = qualification.register(self.root, self.inputs["sourceComparisonId"],
                    condition(version=2), seed=seed, limits=limits)
                self.parent_id = registered["qualificationId"]
                outcome = qualification.advance(self.root, self.campaign_id, self.parent_id,
                    seconds=1200, quota_reader=lambda: 100, prepare_only=True)
            finally:
                self.backend.legacy = False
        self.test.assertEqual(outcome["status"], "panel-rejected", outcome)
        self.test.assertEqual(outcome["stage"], "author")
        self.test.assertEqual(len(self.backend.calls), 1)
        self.parent_folder = qualification.folder(self.root, self.parent_id)
        self.case_id = sorted(self.inputs["cases"])[0]
        self.case_folder = qualification._case_folder(self.root, self.parent_id, self.case_id)
        self.response = read_private(self.case_folder / "author-response.json")
        self.access_folder = self.root / ".oopc/reviewer-source-access" / self.response["capturedSourceAccess"]["accessId"]
        return self.parent_id

    def retained(self):
        """Exact original scientific, access, worker and selection bytes."""
        paths = [*self.parent_folder.rglob("*"), *self.access_folder.rglob("*")]
        for worker in self.worker_folders[:1]:
            paths.extend(worker.parent.parent.rglob("*"))
        intent = read_private(self.parent_folder / "intent.json")
        paths.append(qualification._registration(self.root, intent["sourceComparisonId"], intent["execution"]["condition"]))
        return {path: path.read_bytes() for path in paths if path.is_file()}

    def assert_retained(self, before):
        self.test.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))

    def advance(self, identifier, *, max_new_calls=None, **kwargs):
        stop = None if max_new_calls is None else len(self.backend.calls) + max_new_calls
        quota = lambda: 100 if stop is None or len(self.backend.calls) < stop else 0
        with self.scoped():
            return qualification.advance(self.root, self.campaign_id, identifier,
                seconds=1200, quota_reader=quota, **kwargs)
