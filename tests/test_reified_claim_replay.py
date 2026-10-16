"""Addressable assertions keep their provenance edges in live and offline views."""
import tempfile
import unittest
from pathlib import Path

from oopc.graph import Graph
from oopc.release import build_release
from oopc.trace import TraceStore, import_replay
from oopc.vocabulary import get_ontology
from fixtures.access_replay import fixture_records


class ReifiedClaimReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        records = fixture_records() + [{
            "@id": "claim:support", "@type": "Claim", "label": "Assertion names its evidence",
            "status": "seed", "layer": "provenance", "subject": "claim:ab",
            "predicate": "supportedBy", "object": "evidence:one", "context": {},
        }]
        self.release = build_release(self.root / "release", records, get_ontology(), {})
        self.store = TraceStore(self.root)
        self.run = self.store.create(self.release)
        self.graph = Graph(self.release, self.run, agent_id="reader", verify=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_reified_endpoint_is_the_exact_returned_assertion_without_invented_edges(self):
        claim = self.graph.get("claim:ab")
        self.graph.get("evidence:one")
        support = self.graph.get("claim:support")
        visible = self.run.graph()
        nodes = {r["@id"]: r for r in visible["nodes"]}
        edges = {r["@id"]: r for r in visible["edges"]}
        self.assertEqual(nodes["claim:ab"], claim)
        self.assertEqual(edges, {"claim:ab": claim, "claim:support": support})
        self.assertEqual(edges["claim:support"]["subject"], nodes["claim:ab"]["@id"])
        self.assertEqual(visible["highlights"]["traversed"], [])
        self.assertEqual(visible["highlights"]["returned"], ["claim:ab", "evidence:one", "claim:support"])

    def test_reified_endpoint_never_borrows_a_future_or_another_agents_payload(self):
        self.graph.get("claim:support")
        historical = self.run.graph(sequence=1)
        other = Graph(self.release, self.run, agent_id="other", verify=False)
        other.get("claim:ab")
        filtered = self.run.graph(agent_id="reader")
        self.assertEqual({r["@id"]: r for r in historical["nodes"]}["claim:ab"]["@type"], "Unobserved")
        self.assertEqual({r["@id"]: r for r in filtered["nodes"]}["claim:ab"]["@type"], "Unobserved")
        self.assertEqual(self.run.graph(sequence=1), historical)
        self.assertEqual({r["@id"]: r for r in self.run.graph()["nodes"]}["claim:ab"]["@type"], "Claim")

    def test_selected_event_keeps_prior_known_endpoint_without_adding_its_scientific_edge(self):
        self.graph.get("claim:ab")
        traversal = self.graph.traverse("claim:ab", direction="out", predicate="supportedBy")
        claim = next(r for r in traversal["nodes"] if r["@id"] == "claim:ab")
        visible = self.run.graph(sequence=2, cumulative=False)
        self.assertEqual([r["@id"] for r in visible["edges"]], ["claim:ab", "claim:support"])
        self.assertEqual(visible["highlights"]["traversed"], ["claim:support"])
        # A plain support retrieval only returns that edge. Prior knowledge of
        # its assertion endpoint does not count as a repeated edge access.
        self.graph.get("claim:support")
        selected = self.run.graph(sequence=3, cumulative=False)
        self.assertEqual([r["@id"] for r in selected["edges"]], ["claim:support"])
        self.assertEqual({r["@id"]: r for r in selected["nodes"]}["claim:ab"], claim)
        self.assertEqual(selected["highlights"]["returned"], ["claim:support"])

    def test_offline_replay_keeps_reified_endpoint_records_events_and_qualifiers(self):
        self.graph.traverse("claim:ab", direction="out", predicate="supportedBy")
        before = self.run.graph()
        bundle = self.root / "reified.zip"
        self.run.export(bundle)
        offline = TraceStore(self.root / "offline")
        replay = offline.run(import_replay(bundle, offline)["run_id"])
        self.assertEqual(replay.graph(), before)
        self.assertEqual(replay.events(), self.run.events())
        for event in self.run.events()["events"]:
            self.assertEqual(replay.payload(event["payload_hash"]), self.run.payload(event["payload_hash"]))


if __name__ == "__main__":
    unittest.main()
