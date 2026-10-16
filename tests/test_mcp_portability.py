"""Third-party MCP clients can page the whole graph without false access success."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from oopc.mcp import MCP, SPECS
from oopc.release import build_release
from oopc.vocabulary import get_ontology


class MCPPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        records = [{"@id":"wop-%06d"%i, "@type":"PolymerConcept", "label":"Fixture %04d"%i, "status":"seed", "layer":"science"} for i in range(1, 602)]
        release = build_release(self.root/"releases/fixture", records, get_ontology(), {})
        self.mcp = MCP(self.root, release)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, arguments):
        return self.mcp.handle({"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":name,"arguments":arguments}})

    def test_search_paginates_beyond_first_500_records(self):
        result = self.call("search", {"type":"PolymerConcept", "offset":600, "limit":1})["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["records"][0]["@id"], "wop-000601")
        event = self.mcp.run.events()["events"][-1]
        self.assertEqual(event["request"]["offset"], 600)
        self.assertFalse(event["paths"])
        self.assertFalse(event["traversed_edges"])

    def test_retired_recipe_and_proposal_tools_are_not_offered(self):
        names = {tool["name"] for tool in self.mcp.tools()["tools"]}
        self.assertFalse(names & {"get_recipes", "propose_change"})
        self.assertTrue(self.call("get_recipes", {})["result"]["isError"])

    def test_bad_page_arguments_fail_and_are_recorded_once(self):
        for arguments in ({"offset":-1}, {"limit":0}, {"limit":501}, {"offset":True}):
            before = self.mcp.run.events()["last_sequence"]
            result = self.call("search", arguments)["result"]
            self.assertTrue(result["isError"])
            events = self.mcp.run.events()["events"]
            self.assertEqual(len(events), before+1)
            self.assertEqual(events[-1]["status"], "error")

    def test_invalid_jsonrpc_and_cursor_are_protocol_errors(self):
        for message in ({"jsonrpc":"2.0","id":True,"method":"ping"}, {"jsonrpc":"2.0","id":1,"method":[]}, []):
            self.assertEqual(self.mcp.handle(message)["error"]["code"], -32600)
        message = {"jsonrpc":"2.0", "id":2, "method":"tools/list", "params":{"cursor":"not-issued"}}
        self.assertEqual(self.mcp.handle(message)["error"]["code"], -32602)
        self.assertFalse(self.mcp.run.meta()["capabilities"]["context_delivery"])
