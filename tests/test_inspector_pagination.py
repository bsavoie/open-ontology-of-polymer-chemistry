"""Dense inspector expansion is paged independently of agent traversal."""
import tempfile
import threading
import unittest
import json
from pathlib import Path
from urllib.request import urlopen
from oopc.graph import Graph
from oopc.release import build_release
from oopc.server import make_server
from oopc.trace import TraceStore
from oopc.vocabulary import get_ontology

class InspectorPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        records = [{"@id": "center", "@type": "PolymerConcept", "label": "Center", "status": "seed", "layer": "science"}]
        for i in range(236):
            records += [{"@id": f"neighbor:{i:03}", "@type": "PolymerConcept", "label": f"Neighbor {i}", "status": "seed", "layer": "science"},
                        {"@id": f"edge:{i:03}", "@type": "Claim", "label": f"Edge {i}", "subject": "center" if i % 2 else f"neighbor:{i:03}",
                         "object": f"neighbor:{i:03}" if i % 2 else "center", "predicate": "related", "status": "seed", "layer": "science",
                         "context": {"scopeNote": "Fixture", "environment": "wet" if i % 2 else "dry"}}]
        self.release = build_release(self.root / "releases" / "fixture", records, get_ontology(), {})
        self.run = TraceStore(self.root).create(self.release, "Unrelated agent")
        self.graph = Graph(self.release, self.run)

    def tearDown(self):
        self.temp.cleanup()

    def test_dense_pages_are_disjoint_complete_stable_and_unobserved(self):
        first = self.graph.neighborhood("center", limit=150, offset=0)
        second = self.graph.neighborhood("center", limit=150, offset=first["next_offset"])
        self.assertEqual((len(first["edges"]), len(second["edges"]), first["total"]), (150, 86, 236))
        ids = [r["@id"] for r in first["edges"] + second["edges"]]
        self.assertEqual(len(set(ids)), 236)
        self.assertEqual(first, self.graph.neighborhood("center", limit=150, offset=0))
        self.assertFalse(second["truncated"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(self.run.events()["events"], [])
        # Existing agent traversal and its recorded pagination contract stay fixed.
        traversed = self.graph.traverse("center", limit=150)
        self.assertEqual(traversed["edges"], first["edges"])
        self.assertNotIn("offset", traversed)
        self.assertEqual(len(self.run.events()["events"]), 1)

    def test_filters_direction_and_offsets_retain_scope(self):
        page = self.graph.neighborhood("center", offset=100, limit=50, environment="wet", direction="out")
        self.assertEqual((page["total"], len(page["edges"])), (118, 18))
        self.assertTrue(all(e["context"]["environment"] == "wet" for e in page["edges"]))
        self.assertTrue(all(p["directions"] == ["forward"] for p in page["paths"]))
        self.assertEqual(self.graph.neighborhood("center", offset=300)["edges"], [])
        with self.assertRaises(ValueError):
            self.graph.neighborhood("center", depth=2, offset=0)

    def test_server_forwards_page_cursor_without_recording_access(self):
        server = make_server(self.root, self.release, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/graph?id=center&offset=150&limit=150", timeout=5) as response:
                page = json.load(response)
            self.assertEqual(page["offset"], 150)
            self.assertEqual(len(page["edges"]), 86)
            self.assertEqual(self.run.events()["events"], [])
        finally:
            server.shutdown(); server.server_close(); thread.join()
