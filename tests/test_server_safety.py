"""The local inspector cannot be used as a general local-file or mutation API."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from oopc.graph import Graph
from oopc.release import build_release
from oopc.server import make_server
from oopc.trace import TraceStore
from oopc.vocabulary import get_ontology


class ServerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        records = [{"@id":"wop-000001", "@type":"PolymerConcept", "label":"Fixture", "status":"seed", "layer":"science"}]
        self.release = build_release(self.root/"releases/fixture", records, get_ontology(), {})
        self.run = TraceStore(self.root).create(self.release)
        Graph(self.release, self.run).get("wop-000001")
        try:
            self.server = make_server(self.root, self.release, port=0)
        except PermissionError:
            self.temp.cleanup()
            self.skipTest("Sandbox blocks loopback binding")
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.temp.cleanup()

    def request(self, path="/api/meta", headers=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_cross_origin_rebinding_and_wrong_ports_cannot_read_private_runs(self):
        port = self.server.server_port
        for headers in ({"Host":"attacker.example"}, {"Host":"127.0.0.1:1"}, {"Host":"user@127.0.0.1:"+str(port)},
                        {"Origin":"https://attacker.example"}, {"Origin":"null"},
                        {"Origin":"https://127.0.0.1:"+str(port)}, {"Sec-Fetch-Site":"cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/runs", headers)[0], 403)
        self.assertEqual(self.request("/api/runs", {"Origin":"http://127.0.0.1:"+str(port)})[0], 200)

    def test_diff_accepts_release_identity_and_rejects_arbitrary_paths(self):
        self.assertEqual(self.request("/api/diff?from=fixture&to=fixture")[0], 200)
        path = quote(str(self.release), safe="")
        self.assertEqual(self.request("/api/diff?from="+path+"&to=fixture")[0], 400)
        self.assertEqual(self.request("/api/meta?release="+path)[0], 400)

    def test_replay_only_server_needs_no_original_release(self):
        from oopc.trace import import_replay
        bundle = self.root/"replay.zip"
        self.run.export(bundle)
        replay_root = self.root/"isolated-replay"
        result = import_replay(bundle, TraceStore(replay_root))
        server = make_server(replay_root, None, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/meta")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            meta = json.loads(response.read())
            self.assertTrue(meta["replayOnly"])
            self.assertEqual(meta["releases"], [])
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/runs/"+result["run_id"]+"/events")
            response = connection.getresponse()
            self.assertEqual(json.loads(response.read()), self.run.events())
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/search?q=Fixture")
            response = connection.getresponse()
            self.assertEqual(response.status, 409)
            self.assertTrue(json.loads(response.read())["replayOnly"])
            connection.close()
        finally:
            server.shutdown(); server.server_close(); worker.join()

    def test_mutations_and_path_traversal_are_unavailable(self):
        baseline = self.run.events()
        self.assertEqual(self.request("/api/runs", method="POST")[0], 501)
        for path in ("/%2e%2e/trace.py", "/api/runs/../events", "/api/propose", "/api/publish"):
            self.assertIn(self.request(path)[0], (400, 404))
        self.assertEqual(self.run.events(), baseline)

    def test_completion_is_visible_without_appending_an_access_event(self):
        base = "/api/runs/" + self.run.meta()["run_id"]
        before = self.run.events()
        self.run.finish("completed")
        status, _, body = self.request(base + "/events?after=1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"events": [], "last_sequence": 1})
        status, _, body = self.request(base)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "completed")
        self.assertEqual(self.run.events(), before)

    def test_run_list_and_detail_expose_same_read_only_qualified_summary(self):
        self.run.artifact({"evaluation": {"independentlySourceChecked": True, "reviewVerdict": "fail",
                          "referenceConclusionChecks": {"PRIVATE": "not for the summary"}},
                          "findings": [{"verdict": "pass"}]}, kind="review")
        self.run.finish("completed")
        baseline = self.run.events()
        run_id = self.run.meta()["run_id"]
        status, _, body = self.request("/api/runs/"+run_id)
        self.assertEqual(status, 200)
        detail = json.loads(body)
        summary = detail["inspectorSummary"]
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(summary["evaluation"]["verdict"], "fail")
        self.assertEqual(summary["claimFindings"]["pass"], 1)
        self.assertNotIn("PRIVATE", json.dumps(summary))
        status, _, body = self.request("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["runs"][0]["inspectorSummary"], summary)
        self.assertEqual(self.run.events(), baseline)

    def test_assets_are_local_and_security_headers_protect_private_replay(self):
        for path in ("/", "/researcher.js", "/researcher.css", "/operator.html", "/app.js", "/style.css",
                     "/vendor/cytoscape.min.js", "/vendor/openchemlib.js"):
            status, headers, data = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(data)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_static_assets_revalidate_against_a_content_validator(self):
        status, headers, data = self.request("/researcher.js")
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-cache"))
        etag = headers["ETag"]
        self.assertRegex(etag, r'^"[0-9a-f]{32}"$')
        status, headers, body = self.request("/researcher.js", headers={"If-None-Match": '"stale", ' + etag})
        self.assertEqual((status, body, headers["ETag"]), (304, b"", etag))
        self.assertNotIn("Content-Length", headers)
        status, _, body = self.request("/researcher.js", headers={"If-None-Match": '"0000"'})
        self.assertEqual((status, body), (200, data))
        self.assertNotIn("ETag", self.request("/api/meta")[1])
