"""Engine sessions with fake Codex and Claude binaries: answers, named failures, tools."""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from oopc import engines

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}

CODEX = """
import json, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
mode = open(%(mode)r).read().strip()
def emit(value): print(json.dumps(value), flush=True)
if mode == "sleep":
    time.sleep(30)
if mode == "reject":
    print("ERROR: The 'gpt-6-astra' model requires a newer version of Codex.", file=sys.stderr); sys.exit(1)
if mode == "limit":
    print("You've hit your usage limit. Try again later.", file=sys.stderr); sys.exit(1)
if mode in ("busy", "busy-once"):
    calls = %(mode)r + ".calls"
    seen = int(open(calls).read()) if __import__("os").path.exists(calls) else 0
    open(calls, "w").write(str(seen + 1))
    if mode == "busy" or seen == 0:
        emit({"type": "error", "message": "exceeded retry limit, last status: 429 Too Many Requests"}); sys.exit(1)
if mode == "garbage":
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}}); sys.exit(0)
emit({"type": "item.completed", "item": {"type": "web_search", "id": "w1", "status": "completed", "action": {"type": "search", "query": "PLA"}}})
emit({"type": "item.completed", "item": {"type": "mcp_tool_call", "id": "m1", "server": "oopc", "tool": "search_knowledge", "status": "completed"}})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ok:" + str("--output-schema" in args) + ":" + str("features.shell_tool=false" in args)})}})
emit({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}})
if mode == "crash-after-answer":
    sys.exit(3)
"""


class ParsingTests(unittest.TestCase):
    def test_codex_stream_answer_usage_and_tools(self):
        lines = [{"type": "item.completed", "item": {"type": "web_search", "id": "w", "status": "completed", "action": {"url": "https://x.org/a"}}},
                 {"type": "item.completed", "item": {"type": "agent_message", "text": '{"answer": "a"}'}},
                 {"type": "turn.completed", "usage": {"input_tokens": 5, "cached_input_tokens": 1, "output_tokens": 2}}]
        answer, usage, tools = engines.parse_codex_stream("\n".join(map(json.dumps, lines)) + "\nnot json\n")
        self.assertEqual(answer, '{"answer": "a"}')
        self.assertEqual(usage, {"input_tokens": 5, "cached_input_tokens": 1, "output_tokens": 2})
        self.assertEqual(tools[0]["url"], "https://x.org/a")

    def test_claude_stream_structured_answer_usage_and_tools(self):
        lines = [{"type": "assistant", "message": {"content": [
                     {"type": "tool_use", "id": "t1", "name": "mcp__oopc__search_knowledge", "input": {"q": "PLA"}},
                     {"type": "tool_use", "id": "t2", "name": "WebSearch", "input": {"query": "PLA DSC"}},
                     {"type": "tool_use", "id": "t3", "name": "StructuredOutput", "input": {}}]}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True}]}},
                 {"type": "result", "subtype": "success", "structured_output": {"answer": "b"},
                  "usage": {"input_tokens": 3, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 1, "output_tokens": 4}}]
        answer, usage, tools = engines.parse_claude_stream("\n".join(map(json.dumps, lines)))
        self.assertEqual(json.loads(answer), {"answer": "b"})
        self.assertEqual(usage, {"input_tokens": 11, "cached_input_tokens": 7, "output_tokens": 4})
        self.assertEqual([(t["type"], t.get("tool"), t["status"]) for t in tools],
                         [("mcp_tool_call", "search_knowledge", "completed"), ("web_search", "WebSearch", "failed")])

    def test_web_actions_say_whether_the_page_opened(self):
        def codex(action, title, snippet):
            return {"type": "item.completed", "item": {"type": "web_search", "id": action["type"] + title, "action": action,
                                                       "results": [{"title": title, "snippet": snippet}]}}
        lines = [codex({"type": "search", "query": "PLA Tg"}, "A paper", "PLA has a Tg of 60 °C"),
                 codex({"type": "open_page", "url": "https://a.org/p"}, "A paper", "Total lines: 1048"),
                 codex({"type": "open_page", "url": "https://b.org/p"}, "Internal Error", "Total lines: 1"),
                 codex({"type": "open_page", "url": "https://c.org/p"}, "Checking your browser - reCAPTCHA", "Total lines: 3"),
                 codex({"type": "find_in_page", "url": "https://a.org/p", "pattern": "Tg"}, "A paper", "Total lines: 1048")]
        tools = engines.parse_codex_stream("\n".join(map(json.dumps, lines)))[2]
        self.assertEqual([(t["action"], t["outcome"]) for t in tools],
                         [("search", "searched"), ("open", "opened"), ("open", "refused"), ("open", "refused"),
                          ("find", "opened")])
        claude = [{"type": "assistant", "message": {"content": [
                      {"type": "tool_use", "id": "f1", "name": "WebFetch", "input": {"url": "https://a.org/p", "prompt": "Tg"}},
                      {"type": "tool_use", "id": "f2", "name": "WebFetch", "input": {"url": "https://b.org/p", "prompt": "Tg"}}]}},
                  {"type": "user", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "f1", "content": "Table 2 gives Tg = 60 °C."},
                      {"type": "tool_result", "tool_use_id": "f2", "content": [{"type": "text", "text":
                          "The server returned HTTP 403 Forbidden.\n\nThe response body was not retrieved."}]}]}}]
        tools = engines.parse_claude_stream("\n".join(map(json.dumps, claude)))[2]
        self.assertEqual([(t["url"], t["action"], t["outcome"]) for t in tools],
                         [("https://a.org/p", "open", "opened"), ("https://b.org/p", "open", "refused")])

    def test_claude_usage_report_as_worded_on_2026_10_14(self):
        # CL-2: quota comes from the human-readable /usage report; this is its wording on 2026-10-14.
        report = ("You are currently using your subscription to power your Claude Code usage\n\n"
                  "Current session: 3% used · resets Oct 14 at 12:39am (America/Indianapolis)\n"
                  "Current week (all models): 0% used · resets Oct 20 at 2:59pm (America/Indianapolis)\n\n"
                  "What's contributing to your limits usage?\n"
                  "Last 24h · 1414 requests · 5 sessions\n  95% of your usage was at >150k context\n")
        windows = engines.parse_claude_usage(json.dumps({"type": "result", "result": report}))
        self.assertEqual([(w["limitId"], w["remainingPercent"]) for w in windows],
                         [("current session", 97.0), ("current week (all models)", 100.0)])

    def test_claude_error_result_has_no_answer(self):
        line = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "{}"})
        self.assertIsNone(engines.parse_claude_stream(line)[0])

    def test_failure_classification(self):
        cases = [("You've hit your usage limit", "quota"), ("insufficient_quota", "quota"), ("usage_limit_reached", "quota"),
                 ("rate_limit_exceeded", "rate-limited"),
                 ("exceeded retry limit, last status: 429 Too Many Requests", "rate-limited"),
                 ("Error: Not logged in. Run codex login", "not-signed-in"),
                 ("invalid_request_error: model requires a newer version", "rejected"),
                 ("2026-09-28T11:03:08.909429Z WARN something happened", "crashed")]
        for text, reason in cases:
            with self.subTest(text=text):
                self.assertEqual(engines.classify_failure(1, "", text), reason)
        self.assertEqual(engines.classify_failure(-15, "", ""), "interrupted")

    def test_error_reasons_are_named_and_retry_is_limited_to_transient_ones(self):
        with self.assertRaises(ValueError):
            engines.EngineError("unknown", "x")
        self.assertEqual({r for r in engines.REASONS if engines.EngineError(r, "x").retryable},
                         {"crashed", "interrupted", "invalid-output"})


class SessionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-engine-test-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.mode = self.folder / "mode"
        binary = self.folder / "codex"
        binary.write_text("#!" + sys.executable + "\n" + CODEX % {"mode": str(self.mode)})
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        patches = [mock.patch.dict(os.environ, {"OOPC_CODEX_BINARY": str(binary)}),
                   mock.patch.object(engines, "host_engines_allowed", return_value=True)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_mode(self, mode, timeout=20):
        self.mode.write_text(mode)
        lines = []
        return engines.run_session("codex", "Question", SCHEMA, timeout=timeout, progress=lines.append), lines

    def test_valid_answer_is_returned_with_usage_tools_and_progress(self):
        result, lines = self.run_mode("ok")
        self.assertEqual(result["answer"], {"answer": "ok:True:True"})
        self.assertEqual(result["usage"]["cached_input_tokens"], 4)
        self.assertEqual([t["type"] for t in result["observedTools"]], ["web_search", "mcp_tool_call"])
        self.assertEqual(len(lines), 4)

    def test_a_valid_answer_survives_a_bad_exit(self):
        result, _ = self.run_mode("crash-after-answer")
        self.assertEqual(result["answer"]["answer"], "ok:True:True")

    def test_named_failures(self):
        for mode, reason, timeout in (("sleep", "timeout", 1), ("reject", "rejected", 20), ("limit", "quota", 20),
                                      ("garbage", "invalid-output", 20)):
            with self.subTest(mode=mode):
                with self.assertRaises(engines.EngineError) as raised:
                    self.run_mode(mode, timeout)
                self.assertEqual(raised.exception.reason, reason)

    def test_a_rate_limited_session_is_tried_once_more_after_a_pause_within_its_time_limit(self):
        calls = Path(str(self.mode) + ".calls")
        with mock.patch.object(engines, "RATE_LIMIT_PAUSE", 0), mock.patch.object(engines, "RATE_LIMIT_MIN_SECONDS", 1), \
                mock.patch.object(engines.time, "sleep") as slept:
            result, _ = self.run_mode("busy-once")
            self.assertEqual(result["answer"]["answer"], "ok:True:True")
            self.assertEqual(calls.read_text(), "2")
            self.assertIn(mock.call(0), slept.call_args_list)  # the pause before the second session
            calls.unlink()
            with self.assertRaises(engines.EngineError) as raised:  # still busy after the pause: named, not retried again
                self.run_mode("busy")
            self.assertEqual((raised.exception.reason, raised.exception.retryable, calls.read_text()), ("rate-limited", False, "2"))
        calls.unlink()
        with mock.patch.object(engines, "RATE_LIMIT_PAUSE", 120), mock.patch.object(engines.time, "sleep") as slept:
            with self.assertRaises(engines.EngineError):  # no room left in a 20-second limit: no second session
                self.run_mode("busy")
            self.assertEqual(calls.read_text(), "1")
            self.assertNotIn(mock.call(120), slept.call_args_list)

    def test_missing_binary_is_not_signed_in(self):
        with mock.patch.dict(os.environ, {"OOPC_CODEX_BINARY": str(self.folder / "missing")}):
            with self.assertRaises(engines.EngineError) as raised:
                engines.run_session("codex", "Q", SCHEMA, timeout=5)
        self.assertEqual(raised.exception.reason, "not-signed-in")

    def test_engines_are_disabled_under_tests_by_default(self):
        with mock.patch.object(engines, "host_engines_allowed", return_value=False):
            with self.assertRaises(engines.EngineError):
                engines.run_session("codex", "Q", SCHEMA, timeout=5)
            self.assertFalse(engines.signed_in("codex"))


class BinaryTests(unittest.TestCase):
    def test_the_newest_desktop_bundled_cli_is_found_in_either_layout(self):
        with tempfile.TemporaryDirectory() as home:
            bundled = Path(home) / "Library/Application Support/Claude/claude-code"
            for relative in ("2.1.9/claude.app", "2.1.286/f2326db61802/claude.app", "notes/claude.app"):
                binary = bundled / relative / "Contents/MacOS/claude"
                binary.parent.mkdir(parents=True)
                binary.write_text("")
            with mock.patch.dict(os.environ, {"PATH": "", "OOPC_CLAUDE_BINARY": ""}), \
                    mock.patch.object(Path, "home", return_value=Path(home)):
                self.assertEqual(engines.resolve_claude_binary(),
                                 str(bundled / "2.1.286/f2326db61802/claude.app/Contents/MacOS/claude"))


class ToolHostingTests(unittest.TestCase):
    def test_worker_proxy_reaches_the_hosted_service(self):
        class Echo:
            def serve(self, source, target):
                for line in source:
                    message = json.loads(line)
                    target.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"echo": message["method"]}}) + "\n")
                    target.flush()
        with engines.hosted_tools(Echo()) as config:
            request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            completed = subprocess.run([config["command"], *config["args"]], input=request, capture_output=True,
                                       text=True, timeout=20)
        self.assertEqual(json.loads(completed.stdout), {"jsonrpc": "2.0", "id": 1, "result": {"echo": "tools/list"}})

    def test_commands_disable_shell_and_confine_claude_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            codex = engines.codex_command(Path(folder) / "s.json", folder, model="m", web=True, tools=None)
            claude = engines.claude_command(SCHEMA, folder, model="m", web=True,
                                            tools={"command": "python", "args": ["-c", "pass"]})
            config = json.loads((Path(folder) / "mcp-config.json").read_text())
        self.assertIn("features.shell_tool=false", codex)
        self.assertIn("--ignore-user-config", codex)
        self.assertEqual(claude[claude.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertEqual(claude[claude.index("--allowedTools") + 1], "mcp__oopc,WebSearch,WebFetch")
        self.assertEqual(list(config["mcpServers"]), ["oopc"])


class ChoiceTests(unittest.TestCase):
    def test_preferred_engine_unless_avoided_or_below_reserve(self):
        signed = lambda engine: True
        quota = lambda remaining: (lambda engine: {"remainingPercent": remaining[engine]})
        both = quota({"codex": 80, "claude-code": 60})
        self.assertEqual(engines.choose_engine("codex", signed=signed, quota=both), "codex")
        self.assertEqual(engines.choose_engine("codex", avoid="codex", signed=signed, quota=both), "claude-code")
        low = quota({"codex": 10, "claude-code": 60})
        self.assertEqual(engines.choose_engine("codex", reserve_percent=30, signed=signed, quota=low), "claude-code")
        unknown = lambda engine: {"remainingPercent": None}
        self.assertEqual(engines.choose_engine("claude-code", reserve_percent=30, signed=signed, quota=unknown), "claude-code")
        self.assertEqual(engines.choose_engine("codex", avoid="codex", signed=lambda e: e == "codex", quota=both), "codex")
        self.assertIsNone(engines.choose_engine("codex", signed=lambda e: False, quota=both))
        per_engine = {"codex": 30, "claude-code": 0}
        empty = quota({"codex": 10, "claude-code": 0})
        self.assertEqual(engines.choose_engine("codex", reserve_percent=per_engine, signed=signed, quota=empty), "claude-code")

    def test_an_unknown_engine_has_no_quota(self):
        # "claude" once read back the Codex windows.
        with self.assertRaises(ValueError):
            engines.read_quota("claude")

    def test_quota_report_parsing(self):
        self.assertEqual(engines.parse_claude_usage(json.dumps({"result": "Current session: 68% used · resets 5pm\nCurrent week (all models): 12% used"})),
                         [{"limitId": "current session", "usedPercent": 68.0, "remainingPercent": 32.0},
                          {"limitId": "current week (all models)", "usedPercent": 12.0, "remainingPercent": 88.0}])
        windows = engines.parse_codex_limits({"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 40}, "rateLimitReachedType": None},
                                                                      "other": {"primary": {"usedPercent": 99}}}})
        self.assertEqual([w["remainingPercent"] for w in windows], [60])


if __name__ == "__main__":
    unittest.main()
