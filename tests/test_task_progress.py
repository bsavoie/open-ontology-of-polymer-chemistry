"""Live progress for private questions: display only, identical worker output."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from oopc.task_progress import ProgressTracker, WEB_ACTIVITY, effort, read_progress
from oopc.engines import _run_process


def claude(*blocks, output_tokens=5):
    return json.dumps({"type": "assistant", "message": {"content": list(blocks), "usage": {"output_tokens": output_tokens}}})


def tool(name, **arguments):
    return {"type": "tool_use", "name": name, "input": arguments}


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "progress.json"
        self.tracker = ProgressTracker(self.path, phase="research", budget_seconds=600, minimum_interval=0)

    def test_claude_stream_counts_ontology_knowledge_and_web_activity(self):
        for line in (claude(tool("mcp__oopc__search_knowledge", q="PTFE annealing")),
                     claude(tool("mcp__oopc__search", q="polytetrafluoroethylene"), tool("mcp__oopc__traverse", start="wop-1", depth=2)),
                     claude(tool("mcp__oopc__get_record", id="wop-1")),
                     claude(tool("WebSearch", query="PTFE annealing crystallinity")),
                     claude(tool("WebFetch", url="https://www.example.org/a"), tool("WebFetch", url="https://pubs.example.com/b")),
                     "not json", json.dumps({"type": "user"})):
            self.tracker(line)
        value = read_progress(self.path)
        self.assertEqual(value["graph"]["searches"], 1)
        self.assertEqual(value["graph"]["hops"], 2)
        self.assertEqual(value["graph"]["records"], 1)
        self.assertEqual(value["graph"]["knowledge"], 1)
        self.assertEqual(value["web"], {"searches": 1, "pages": 2, "unclassified": 0})
        self.assertEqual(value["sites"], ["example.org", "pubs.example.com"])
        self.assertEqual(value["lastAction"], "Reading pubs.example.com")
        self.assertEqual((value["turns"], value["outputTokens"]), (5, 25))

    def test_codex_events_are_counted(self):
        for event in ({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "search", "arguments": {"q": "PVDF"}}},
                      {"type": "item.started", "item": {"type": "web_search", "query": "PVDF annealing"}},
                      {"type": "item.started", "item": {"type": "web_search", "action": {"type": "open_page", "url": "https://a.example/x"}}},
                      {"type": "turn.completed", "usage": {"output_tokens": 40}}):
            self.tracker(json.dumps(event))
        value = read_progress(self.path)
        self.assertEqual((value["graph"]["searches"], value["web"]["searches"], value["web"]["pages"]), (1, 1, 1))
        self.assertEqual(value["outputTokens"], 40)

    def test_web_search_start_without_query_uses_a_generic_action(self):
        self.tracker(json.dumps({'type': 'item.started', 'item': {'type': 'web_search'}}))
        value = read_progress(self.path)
        self.assertEqual(value['lastAction'], 'Using the web')
        self.assertEqual(value['web']['searches'], 0)
        self.assertEqual(value['web']['unclassified'], 1)
        self.tracker(claude(tool('WebSearch', query='  ')))
        value = read_progress(self.path)
        self.assertEqual(value['lastAction'], 'Searching the web')
        self.assertEqual(value['web']['searches'], 1)

    def test_codex_lifecycle_enriches_unique_web_items_without_inventing_page_reads(self):
        events = [
            ('item.started', {'id': 'one', 'type': 'web_search'}),
            ('item.updated', {'id': 'one', 'type': 'web_search', 'action': {'type': 'search', 'query': 'PTFE'}}),
            ('item.completed', {'id': 'one', 'type': 'web_search', 'action': {'type': 'search', 'query': 'PTFE'}}),
            ('item.started', {'id': 'two', 'type': 'web_search'}),
            ('item.completed', {'id': 'two', 'type': 'web_search', 'action': {'type': 'open_page', 'url': 'https://example.org/p'}}),
            ('item.completed', {'id': 'two', 'type': 'web_search', 'action': {'type': 'open_page', 'url': 'https://example.org/p'}}),
            ('item.updated', {'id': 'two', 'type': 'web_search'}),
            ('item.started', {'id': 'three', 'type': 'web_search'}),
            ('item.completed', {'id': 'three', 'type': 'web_search'}),
        ]
        for kind, item in events:
            self.tracker(json.dumps({'type': kind, 'item': item}))
        value = read_progress(self.path)
        self.assertEqual(value['web'], {'searches': 1, 'pages': 1, 'unclassified': 1})
        self.assertEqual(value['sites'], ['example.org'])
        self.assertEqual(value['webActivityProtocol'], WEB_ACTIVITY)
        result = {'observedTools': [{'type': 'web_search', 'id': str(i)} for i in range(3)],
                  'citations': ['https://unobserved.example/p']}
        metrics = effort(result, value)
        self.assertEqual((metrics['webSearches'], metrics['pagesRead'], metrics['unclassifiedWebCalls']), (1, 1, 1))
        historical = dict(value)
        historical.pop('webActivityProtocol')
        self.assertEqual(effort(result, historical)['webSearches'], 3)
        self.assertEqual(effort(result, historical)['pagesRead'], 0)

    def test_effort_summarizes_the_retained_result(self):
        result = {"observedTools": [{"type": "mcp_tool_call", "tool": "search"}, {"type": "mcp_tool_call", "tool": "search_knowledge"},
                                    {"type": "web_search", "tool": "WebFetch"}, {"type": "web_search", "tool": "WebSearch"}],
                  "usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 50}, "agentSeconds": 42.0}
        value = effort(result, {"sites": ["example.org"], "graph": {"hops": 3}, "web": {"searches": 9, "pages": 9}})
        self.assertEqual((value["graphLookups"], value["knowledgeLookups"], value["webSearches"], value["pagesRead"]), (1, 1, 1, 1))
        self.assertEqual((value["inputTokens"], value["graphHops"], value["sites"]), (1000, 3, ["example.org"]))


class SourceCountTests(unittest.TestCase):
    def test_re_reading_a_source_does_not_count_as_a_new_one(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker = ProgressTracker(Path(folder) / "progress.json", phase="research", minimum_interval=0)
            for url in ("https://example.org/paper#results", "https://example.org/paper?page=2", "https://example.org/paper.pdf"):
                tracker(claude(tool("WebFetch", url=url)))
            snapshot = tracker.snapshot()
        self.assertEqual((snapshot["web"]["pages"], snapshot["sourcesOpened"]), (3, 2))


class StreamingRunTests(unittest.TestCase):
    def test_streaming_captures_all_output_and_shows_each_line(self):
        command = [sys.executable, "-c", "import sys; data=sys.stdin.read(); print('a'); print(len(data)); sys.stderr.write('warn')"]
        seen = []
        code, out, err, timed_out = _run_process(command, prompt="x" * 200000, cwd=None, env=None, timeout=30, on_line=seen.append)
        self.assertEqual((code, out, err, timed_out), (0, "a\n200000\n", "warn", ""))
        self.assertEqual(seen, ["a\n", "200000\n"])

    def test_a_failing_callback_never_affects_the_worker(self):
        def broken(line):
            raise RuntimeError("display failed")
        code, out, _, _ = _run_process([sys.executable, "-c", "print('ok')"], prompt="", cwd=None, env=None, timeout=30, on_line=broken)
        self.assertEqual((code, out), (0, "ok\n"))

    def test_timeout_stops_the_whole_process_group(self):
        code, _, _, timed_out = _run_process([sys.executable, "-c", "import time; time.sleep(30)"], prompt="", cwd=None,
                                             env=None, timeout=1, on_line=None)
        self.assertTrue(timed_out)
        self.assertLess(code, 0)

    def test_a_silent_session_is_stopped_as_stalled_before_its_limit(self):
        script = "import sys, time; print('started', flush=True); time.sleep(30)"
        clock = time.monotonic()
        code, out, _, stopped = _run_process([sys.executable, "-c", script], prompt="", cwd=None, env=None, timeout=30,
                                             on_line=None, idle=1)
        self.assertEqual((stopped, out), ("idle", "started\n"))
        self.assertLess(time.monotonic() - clock, 10)
        self.assertLess(code, 0)

    def test_a_session_that_keeps_writing_is_not_stalled(self):
        script = "import time\nfor _ in range(4):\n    print('.', flush=True); time.sleep(0.4)"
        code, out, _, stopped = _run_process([sys.executable, "-c", script], prompt="", cwd=None, env=None, timeout=30,
                                             on_line=None, idle=1)
        self.assertEqual((code, stopped, out.count(".")), (0, "", 4))


if __name__ == "__main__":
    unittest.main()
