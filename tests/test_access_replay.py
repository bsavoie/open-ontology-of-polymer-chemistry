"""Behavioral acceptance tests for model-neutral access and durable offline replay."""
import copy
import io
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from oopc.graph import Graph
from oopc.mcp import MCP
from oopc.release import build_release, verify_release
from oopc.server import make_server
from oopc.trace import TraceStore, import_replay
from oopc.util import canonical, digest
from oopc.vocabulary import get_ontology
from fixtures.access_replay import fixture_records


class AccessReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.records = fixture_records()
        self.release = build_release(self.root / "releases" / "seed", self.records, get_ontology(), {"description": "Public fixture"})
        self.store = TraceStore(self.root)
        self.run = self.store.create(self.release, "Private task", capabilities={"context_delivery": False, "full_context": False}, task={"prompt": "PRIVATE-TASK-SENTINEL"})
        self.graph = Graph(self.release, self.run)

    def tearDown(self):
        self.temp.cleanup()

    def test_search_and_repeated_access_are_returned_not_traversed(self):
        first = self.graph.search("Alpha")
        self.graph.get("wop-000001")
        self.graph.get("wop-000001")
        events = self.run.events()["events"]
        self.assertEqual(len(events), 3)
        self.assertEqual([e["sequence"] for e in events], [1, 2, 3])
        self.assertEqual(len({e["event_id"] for e in events}), 3)
        self.assertTrue(all(not e["traversed_edges"] and not e["paths"] for e in events))
        self.assertIn("claim:ab", events[0]["result_ids"])
        self.assertEqual(self.run.payload(events[0]["payload_hash"]), first)
        self.assertEqual(events[0]["payload_hash"], digest(canonical(first)))
        self.assertFalse(self.run.graph()["highlights"]["traversed"])
        self.assertEqual(events[0]["retrieval_index_version"], verify_release(self.release)["index_version"])

    def test_explicit_paths_and_truncation_are_recorded_exactly(self):
        result = self.graph.traverse("wop-000001", direction="out", limit=1)
        event = self.run.events()["events"][-1]
        self.assertEqual(event["paths"], result["paths"])
        self.assertEqual(event["traversed_edges"], ["claim:ab"])
        self.assertEqual(event["paths"][0]["directions"], ["forward"])
        self.assertEqual(event["truncated"], result["truncated"])
        self.assertEqual(self.run.payload(event["payload_hash"]), result)

    def test_parallel_agents_keep_contiguous_sequence_and_agent_identity(self):
        def access(i):
            return Graph(self.release, self.run, agent_id="worker-"+str(i % 3), verify=False).get("wop-000001")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(access, range(18)))
        events = self.run.events()["events"]
        self.assertEqual([e["sequence"] for e in events], list(range(1, 19)))
        self.assertEqual(len({e["event_id"] for e in events}), 18)
        self.assertEqual(set(self.run.meta()["agents"]), {"worker-0", "worker-1", "worker-2"})
        self.assertEqual({r["_access"]["event_id"] for r in results}, {e["event_id"] for e in events})

    def test_old_time_and_filtered_agent_do_not_see_future_or_other_agent_payload(self):
        alpha = Graph(self.release, self.run, agent_id="alpha", verify=False)
        beta = Graph(self.release, self.run, agent_id="beta", verify=False)
        alpha.get("claim:ab")
        beta.get("wop-000002")
        old = {r["@id"]: r for r in self.run.graph(sequence=1)["nodes"]}
        filtered = {r["@id"]: r for r in self.run.graph(sequence=2, agent_id="alpha")["nodes"]}
        self.assertEqual(old["wop-000002"]["@type"], "Unobserved")
        self.assertEqual(filtered["wop-000002"]["@type"], "Unobserved")
        self.assertEqual({r["@id"]: r for r in self.run.graph(sequence=2)["nodes"]}["wop-000002"]["label"], "Material Beta")
        with self.assertRaises(ValueError):
            changed = copy.deepcopy(self.records)
            changed[0]["label"] = "New release value"
            future = build_release(self.root / "releases" / "future", changed, get_ontology(), {"description": "Changed"})
            Graph(future, self.run)

    def test_disconnected_search_and_absent_source_remain_explicit_gaps(self):
        self.graph.get("claim:ab")
        self.graph.get("wop-000003")
        visible = self.run.graph()
        self.assertEqual([r["@id"] for r in visible["edges"]], ["claim:ab"])
        nodes = {r["@id"]: r for r in visible["nodes"]}
        self.assertEqual(nodes["wop-000003"]["label"], "Disconnected Gamma")
        self.assertEqual(nodes["wop-000001"]["@type"], "Unobserved")
        self.assertNotIn("evidence:one", nodes)
        self.assertFalse(visible["highlights"]["traversed"])

    def test_delivery_requires_observed_record_and_does_not_claim_full_context(self):
        result = self.graph.get("wop-000001")
        event_id = result["_access"]["event_id"]
        with self.assertRaises(ValueError):
            self.run.delivery(event_id, ["wop-000003"], "model-1")
        self.run.delivery(event_id, ["wop-000001"], "model-1", representation="summary")
        meta = self.run.meta()
        self.assertTrue(meta["capabilities"]["context_delivery"])
        self.assertFalse(meta["capabilities"]["full_context"])
        self.assertEqual(self.run.graph()["highlights"]["delivered"], ["wop-000001"])

    def test_explicit_handoff_shares_only_delivered_context_between_agents(self):
        alpha = Graph(self.release, self.run, agent_id="alpha", verify=False)
        result = alpha.search("Material")
        self.run.delivery(result["_access"]["event_id"], ["wop-000002"], "beta-call", agent_id="beta")
        visible = self.run.graph(agent_id="beta")
        self.assertEqual([r["@id"] for r in visible["nodes"]], ["wop-000002"])
        self.assertEqual(visible["nodes"][0]["label"], "Material Beta")
        self.assertEqual(visible["highlights"]["returned"], [])
        self.assertEqual(visible["highlights"]["delivered"], ["wop-000002"])

    def test_payload_corruption_is_detected(self):
        self.graph.get("wop-000001")
        event = self.run.events()["events"][0]
        path = self.run.path / "payloads" / (event["payload_hash"] + ".json")
        path.write_text('{"modified":true}')
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.run.payload(event["payload_hash"])
        with self.assertRaises(ValueError):
            self.run.export(self.root / "bad.zip")
        self.assertFalse((self.root / "bad.zip").exists())

    def test_committed_delivery_survives_interrupted_metadata_write_and_replays(self):
        result = self.graph.get("wop-000001")
        original_metadata = (self.run.path / "run.json").read_bytes()
        with patch("oopc.trace.atomic_json", side_effect=OSError("interrupted metadata write")):
            with self.assertRaisesRegex(OSError, "interrupted metadata"):
                self.run.delivery(result["_access"]["event_id"], ["wop-000001"], "model-1", agent_id="consumer")
        events = self.run.events()["events"]
        journal = (self.run.path / "events.jsonl").read_bytes()
        self.assertEqual(len(events), 2)
        self.assertEqual(json.loads(original_metadata)["last_sequence"], 1)
        meta = self.run.meta()
        self.assertEqual(meta["last_sequence"], 2)
        self.assertEqual(meta["agents"], ["agent", "consumer"])
        self.assertTrue(meta["capabilities"]["context_delivery"])
        self.assertEqual(meta["status"], "running")
        self.assertEqual(self.store.list()[0]["last_sequence"], 2)
        bundle = self.root / "interrupted-metadata.zip"
        self.run.export(bundle)
        offline = TraceStore(self.root / "offline")
        replay = offline.run(import_replay(bundle, offline)["run_id"])
        self.assertEqual(replay.events()["events"], events)
        self.assertEqual(replay.graph(), self.run.graph())
        self.assertEqual((self.run.path / "run.json").read_bytes(), original_metadata)
        self.assertEqual((self.run.path / "events.jsonl").read_bytes(), journal)

    def test_committed_access_survives_interruption_before_journal_append(self):
        real_open = open

        def interrupted_open(path, mode="r", *args, **kwargs):
            if Path(path) == self.run.path / "events.jsonl" and mode == "ab":
                raise OSError("interrupted journal append")
            return real_open(path, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=interrupted_open):
            with self.assertRaisesRegex(OSError, "interrupted journal"):
                self.run.record("get", {"id": "wop-000001"}, {"record": copy.deepcopy(self.records[0])})
        self.assertEqual((self.run.path / "events.jsonl").read_bytes(), b"")
        self.run.finish("failed")
        bundle = self.root / "interrupted-journal.zip"
        self.run.export(bundle)
        offline = TraceStore(self.root / "offline")
        replay = offline.run(import_replay(bundle, offline)["run_id"])
        self.assertEqual(replay.events(), self.run.events())
        self.assertEqual(replay.meta()["last_sequence"], 1)
        self.assertEqual(self.run.meta()["status"], "failed")

    def test_offline_export_import_is_identical_and_preserves_private_boundary(self):
        self.graph.traverse("wop-000001")
        self.graph.evidence("claim:ab")
        self.run.artifact({"id": "answer", "text": "Qualified answer", "citations": ["evidence:one", "missing:source"]})
        self.run.finish()
        original = self.run.graph()
        bundle = self.root / "task.zip"
        self.run.export(bundle)
        with zipfile.ZipFile(bundle) as archive:
            meta = json.loads(archive.read("run.json"))
            self.assertNotIn("release_path", meta)
            self.assertTrue(meta["private"])
            self.assertNotIn("graph.sqlite", archive.namelist())
        public_manifest = verify_release(self.release)
        self.assertFalse(any("runs" in name or "payloads" in name or "task" in name for name in public_manifest["files"]))
        self.assertNotIn("PRIVATE-TASK-SENTINEL", (self.release / "records.jsonl").read_text())
        shutil.rmtree(self.release)
        store = TraceStore(self.root / "offline")
        replay_meta = import_replay(bundle, store)
        replay = store.run(replay_meta["run_id"])
        self.assertEqual(replay.graph(), original)
        self.assertEqual(replay.events(), self.run.events())
        self.assertEqual(replay.artifacts(), self.run.artifacts())
        for event in self.run.events()["events"]:
            self.assertEqual(replay.payload(event["payload_hash"]), self.run.payload(event["payload_hash"]))
        self.assertIn("missing:source", replay.artifacts()["artifacts"][0]["unobserved_citations"])
        with self.assertRaises(ValueError):
            replay.artifact({"id": "later", "text": "Must stay immutable"})

    def test_candidate_revision_is_separate_from_original_accessed_records(self):
        self.graph.get("claim:ab")
        proposed = copy.deepcopy(next(r for r in self.records if r["@id"] == "claim:ab"))
        proposed["label"] = "A revised candidate label"
        self.run.artifact({"id": "proposal", "records": [proposed]}, kind="candidate")
        visible = self.run.graph()
        edges = {r["@id"]: r for r in visible["edges"]}
        self.assertEqual(edges["claim:ab"]["label"], "Alpha related to Beta")
        candidates = visible["highlights"]["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertNotEqual(candidates[0], "claim:ab")
        self.assertEqual(edges[candidates[0]]["label"], proposed["label"])
        self.assertEqual(edges[candidates[0]]["original_record_id"], "claim:ab")
        self.assertEqual(edges[candidates[0]]["status"], "candidate")
        self.graph.get("claim:ab")
        bundle = self.root / "candidate.zip"
        self.run.export(bundle)
        imported = import_replay(bundle, TraceStore(self.root / "candidate-replay"))
        self.assertEqual(TraceStore(self.root / "candidate-replay").run(imported["run_id"]).graph(), self.run.graph())

    def test_replay_preserves_terminal_outcomes_and_their_original_timestamps(self):
        for status in ("completed", "failed", "cancelled", "paused"):
            with self.subTest(status=status):
                source = self.store.create(self.release, "Recorded " + status)
                Graph(self.release, source, verify=False).get("wop-000001")
                original = source.finish(status)
                bundle = self.root / (status + ".zip")
                source.export(bundle)
                store = TraceStore(self.root / (status + "-replay"))
                meta = import_replay(bundle, store)
                replay = store.run(meta["run_id"])
                self.assertEqual(meta["status"], status)
                self.assertEqual(meta["recorded_status"], status)
                self.assertEqual(meta["finished_at"], original["finished_at"])
                self.assertTrue(meta["immutable_replay"])
                self.assertEqual(replay.events(), source.events())
                self.assertEqual(replay.graph(), source.graph())
                with self.assertRaisesRegex(ValueError, "immutable"):
                    replay.finish()

    def test_running_replay_is_an_immutable_checkpoint_not_a_live_or_completed_task(self):
        self.graph.get("wop-000001")
        bundle = self.root / "checkpoint.zip"
        self.run.export(bundle)
        store = TraceStore(self.root / "checkpoint-replay")
        meta = import_replay(bundle, store)
        replay = store.run(meta["run_id"])
        self.assertEqual(meta["status"], "checkpoint")
        self.assertEqual(meta["recorded_status"], "running")
        self.assertTrue(meta["immutable_replay"])
        self.assertNotIn("finished_at", meta)
        self.assertEqual(self.run.meta()["status"], "running")
        self.assertEqual(replay.events(), self.run.events())
        with self.assertRaisesRegex(ValueError, "immutable"):
            Graph(self.release, replay, verify=False).get("wop-000002")
        second_bundle = self.root / "checkpoint-export.zip"
        replay.export(second_bundle)
        second_store = TraceStore(self.root / "checkpoint-second")
        second_meta = import_replay(second_bundle, second_store)
        second = second_store.run(second_meta["run_id"])
        self.assertEqual(second_meta["status"], "checkpoint")
        self.assertEqual(second_meta["recorded_status"], "running")
        self.assertEqual(second_meta["original_run_id"], self.run.meta()["run_id"])
        self.assertEqual(second.events(), self.run.events())
        for event in self.run.events()["events"]:
            self.assertEqual(second.payload(event["payload_hash"]), self.run.payload(event["payload_hash"]))

    def test_legacy_reexport_does_not_guess_the_outcome_overwritten_by_older_importers(self):
        self.graph.get("wop-000001")
        self.run.finish("failed")
        bundle = self.root / "legacy-reexport.zip"
        self.run.export(bundle)
        with zipfile.ZipFile(bundle) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        legacy = json.loads(files["run.json"])
        legacy.update(imported=True, original_run_id=legacy["run_id"], run_id="replay-legacy", status="completed")
        files["run.json"] = canonical(legacy)
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["run.json"] = digest(files["run.json"])
        files["manifest.json"] = canonical(manifest)
        with zipfile.ZipFile(bundle, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        store = TraceStore(self.root / "legacy-replay")
        meta = import_replay(bundle, store)
        self.assertEqual(meta["status"], "checkpoint")
        self.assertEqual(meta["recorded_status"], "unknown")
        self.assertIn("original task status", meta["replay_status_note"])
        self.assertEqual(store.run(meta["run_id"]).events(), self.run.events())

    def test_duplicate_artifact_is_atomic_and_cannot_add_phantom_events(self):
        self.run.artifact({"id": "answer", "text": "First answer"})
        before = self.run.events()
        with self.assertRaises(ValueError):
            self.run.artifact({"id": "answer", "text": "Duplicate answer"})
        self.assertEqual(self.run.events(), before)
        self.assertEqual(len(self.run.artifacts()["artifacts"]), 1)

    def test_invalid_replay_is_rejected_before_creating_a_run(self):
        self.graph.search("Alpha")
        bundle = self.root / "valid.zip"
        self.run.export(bundle)
        with zipfile.ZipFile(bundle) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        events = [json.loads(line) for line in files["events.jsonl"].splitlines() if line]
        events[0]["traversed_edges"] = ["claim:ab"]
        files["events.jsonl"] = b"".join(canonical(event)+b"\n" for event in events)
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["events.jsonl"] = digest(files["events.jsonl"])
        files["manifest.json"] = canonical(manifest)
        bad = self.root / "invalid.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        store = TraceStore(self.root / "invalid-store")
        with self.assertRaisesRegex(ValueError, "Only explicit traversal"):
            import_replay(bad, store)
        self.assertFalse(store.list())
        self.assertFalse(store.path.exists())

    def test_export_while_agents_run_produces_one_consistent_snapshot(self):
        self.graph.get("wop-000001")
        barrier = threading.Barrier(2)
        def writer():
            barrier.wait()
            for _ in range(15):
                Graph(self.release, self.run, "parallel", verify=False).get("wop-000002")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            barrier.wait()
            bundle = self.root / "live.zip"
            self.run.export(bundle)
            future.result()
        store = TraceStore(self.root / "live-replay")
        imported = import_replay(bundle, store)
        replay = store.run(imported["run_id"])
        self.assertEqual(replay.meta()["last_sequence"], len(replay.events()["events"]))
        self.assertGreaterEqual(replay.meta()["last_sequence"], 1)
        self.assertLessEqual(replay.meta()["last_sequence"], 16)

    def test_inspector_browsing_and_export_do_not_append_agent_events(self):
        self.graph.get("wop-000001")
        baseline = self.run.events()
        try:
            server = make_server(self.root, self.release, port=0)
        except PermissionError:
            self.skipTest("Sandbox blocks loopback binding; rerun with local-server permission")
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = "http://127.0.0.1:"+str(server.server_port)
        try:
            for path in ("/api/search?q=Alpha", "/api/graph?id=wop-000001", "/api/runs/"+self.run.path.name+"/graph", "/api/runs/"+self.run.path.name+"/export"):
                with urlopen(base+path) as response:
                    self.assertEqual(response.status, 200)
                    response.read()
            self.assertEqual(self.run.events(), baseline)
            with self.assertRaises(HTTPError) as context:
                urlopen(Request(base+"/api/runs", headers={"Origin": "https://foreign.example"}))
            self.assertEqual(context.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_mcp_protocol_preserves_access_payload_and_never_confirms_delivery(self):
        mcp = MCP(self.root, self.release, run_id=self.run.path.name)
        message = {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_record","arguments":{"id":"wop-000001"}}}
        response = mcp.handle(message)
        value = response["result"]["structuredContent"]
        event = self.run.events()["events"][0]
        self.assertEqual(value, self.run.payload(event["payload_hash"]))
        self.assertFalse(self.run.meta()["capabilities"]["context_delivery"])
        response = mcp.handle({**message, "params":{"name":"get_record","arguments":{"id":"missing:record"}}})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(self.run.events()["events"][-1]["status"], "error")
        source, output = io.StringIO('not-json\n'+json.dumps({"jsonrpc":"2.0","id":3,"method":"ping"})+'\n'), io.StringIO()
        mcp.serve(source, output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})

    def test_external_sources_preserve_metadata_receipts_and_content_gaps_offline(self):
        external = {"@id":"evidence:new", "@type":"Evidence", "label":"New open paper",
                    "locator":"Table 2, material grade PLA-A", "url":"https://example.org/new",
                    "accessStatus":"anonymous_full_content", "reuseStatus":"citation_only"}
        receipt = {"evidenceId":"evidence:new", "locator":"Table 2", "verdict":"checked",
                   "note":"Worker reports inspecting source; browser access was not instrumented"}
        attachment = self.run.external_evidence([external], [receipt])
        answer = self.run.artifact({"id":"answer", "claims":[{"id":"answer:1", "text":"Qualified result",
                                     "citations":[external["@id"]]}]})
        resolved = self.run.citation(external["@id"], event_id=answer["event_id"])
        self.assertIsNone(resolved["access_event"])
        self.assertIsNone(resolved["record"])
        self.assertIn("No successful instrumented access", resolved["capture_gap"])
        attached = resolved["attachments"][0]
        self.assertEqual(attached["record"], external)
        self.assertEqual(attached["source_checks"], [receipt])
        self.assertEqual(attached["content"]["status"], "unavailable")
        self.assertEqual(attached["event_id"], attachment["event_id"])
        self.assertNotIn("_access", attachment)
        self.assertEqual(self.run.graph()["highlights"]["returned"], [])
        self.assertEqual(self.run.graph()["nodes"][0]["@type"], "Unobserved")
        self.assertFalse(self.run.meta()["capabilities"]["context_delivery"])
        bundle = self.root / "external.zip"
        self.run.finish()
        self.run.export(bundle)
        offline = TraceStore(self.root / "external-offline")
        meta = import_replay(bundle, offline)
        replay = offline.run(meta["run_id"])
        self.assertEqual(replay.citation(external["@id"], event_id=answer["event_id"]), resolved)

    def test_source_content_requires_rights_and_checksummed_payload_or_explicit_gap(self):
        external = {"@id":"evidence:excerpt", "@type":"Evidence", "label":"Permitted source excerpt"}
        with self.assertRaisesRegex(ValueError, "permission"):
            self.run.external_evidence([external],content={external["@id"]:{"status":"included","text":"A"}})
        with self.assertRaisesRegex(ValueError, "cannot contain text"):
            self.run.external_evidence([external],content={external["@id"]:{"status":"excluded","reason":"No reuse rights","text":"Hidden content"}})
        self.assertEqual(self.run.events()["events"], [])
        self.run.external_evidence([external], content={external["@id"]:{"status":"included",
            "text":"Original structured result: temperature 23 °C", "permission_basis":"Original author contribution, CC0"}})
        resolved = self.run.citation(external["@id"])
        content = resolved["attachments"][0]["content"]
        self.assertEqual(content["sha256"], digest(content["text"].encode("utf-8")))
        self.assertIsNone(resolved["access_event"])
        self.assertEqual(self.run.graph()["nodes"], [])

    def test_citation_does_not_use_candidate_review_or_future_access(self):
        answer = self.run.artifact({"id":"answer", "citations":["evidence:one"]})
        self.run.artifact({"id":"review", "findings":[{"claimId":"answer:1", "verdict":"pass",
                            "citations":["evidence:one"]}]},kind="review")
        self.graph.get("evidence:one")
        resolved = self.run.citation("evidence:one", event_id=answer["event_id"])
        self.assertIsNone(resolved["access_event"])
        self.assertEqual(resolved["access_events"], [])
        self.graph.get("evidence:one")
        self.assertEqual(len(self.run.citation("evidence:one")["access_events"]), 2)

    def test_mixed_review_only_highlights_sources_of_passing_claims(self):
        self.run.artifact({"findings":[
            {"claimId":"passed", "verdict":"pass", "citations":["evidence:one"]},
            {"claimId":"uncertain", "verdict":"uncertain", "citations":["missing:source"]},
            {"claimId":"failed", "verdict":"fail", "citations":["bad:source"]},
        ]},kind="review")
        self.assertEqual(self.run.graph()["highlights"]["reviewer_supported"], ["evidence:one"])
        self.assertEqual(self.run.graph()["highlights"]["returned"], [])

    def test_citation_objects_preserve_explicit_event_and_claim_lineage(self):
        payload = self.graph.get("evidence:one")
        source_event = payload["_access"]["event_id"]
        citation = {"record_id":"evidence:one", "event_id":source_event, "label":"Table 2"}
        artifact = self.run.artifact({"claims":[{"id":"answer:qualified", "text":"Qualified result", "citations":[citation]}]})
        self.assertEqual(artifact["claims"][0]["citations"], [citation])
        self.assertEqual(self.run.events()["events"][-1]["result_ids"], ["evidence:one"])
        self.assertEqual(self.run.citation("evidence:one",source_event)["access_event"]["event_id"], source_event)

    def test_mcp_argument_validation_failures_are_recorded_once(self):
        mcp = MCP(self.root, self.release, run_id=self.run.path.name)
        for arguments in ({"limit":501}, {"unknown":"x"}, {"limit":"two"}):
            before = len(self.run.events()["events"])
            response = mcp.handle({"jsonrpc":"2.0","id":1,"method":"tools/call",
                                   "params":{"name":"search","arguments":arguments}})
            self.assertTrue(response["result"]["isError"])
            events = self.run.events()["events"]
            self.assertEqual(len(events), before+1)
            self.assertEqual(events[-1]["status"], "error")
            self.assertEqual(events[-1]["result_ids"], [])
            self.assertEqual(events[-1]["request"]["arguments"], arguments)


if __name__ == "__main__":
    unittest.main()
