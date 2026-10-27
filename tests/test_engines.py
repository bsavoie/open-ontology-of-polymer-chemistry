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
import json, os, sys, time, uuid
args = sys.argv[1:]
prompt = sys.stdin.read()
mode = open(%(mode)r).read().strip()
def emit(value): print(json.dumps(value), flush=True)
def config(key):
    for flag, value in zip(args, args[1:]):
        if flag == "-c" and value.startswith(key + "="):
            return json.loads(value.split("=", 1)[1])
home = os.environ["CODEX_HOME"]
# Like Codex: its state databases (the index of threads and their turns) live in sqlite_home, by default $CODEX_HOME;
# a new one first copies in every thread with a rollout under $CODEX_HOME/sessions (the backfill).
state = os.path.join(config("sqlite_home") or home, "state_5.sqlite")
if not os.path.exists(state):
    found = [name.split("T00-00-00-")[1].split(".jsonl")[0]
             for _, _, names in os.walk(os.path.join(home, "sessions")) for name in names]
    os.makedirs(os.path.dirname(state), exist_ok=True)
    open(state, "w").write(json.dumps({"backfill": "complete", "threads": found}))
# A thread is saved as a rollout under $CODEX_HOME unless --ephemeral, and `exec resume ID -` continues it, reporting
# the thread's usage from its start.
resume = args[1] == "resume"
thread = args[-2] if resume else str(uuid.uuid4())
rollout = os.path.join(home, "sessions", "2026", "10", "25", "rollout-2026-10-25T00-00-00-" + thread + ".jsonl")
before = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
if resume:
    if not os.path.exists(rollout):
        print("ERROR: no rollout found for thread id " + thread, file=sys.stderr); sys.exit(1)
    before = json.loads(open(rollout).read().splitlines()[-1])
if "--ephemeral" not in args or resume:
    index = json.loads(open(state).read())
    index["threads"] = index["threads"] + [thread] * (thread not in index["threads"])
    open(state, "w").write(json.dumps(index))
emit({"type": "thread.started", "thread_id": thread})
if mode == "two-ids":
    emit({"type": "thread.started", "thread_id": str(uuid.uuid4())})
if mode in ("busy", "busy-once"):  # Too many requests: no turn was taken.
    calls = %(mode)r + ".calls"
    seen = int(open(calls).read()) if __import__("os").path.exists(calls) else 0
    open(calls, "w").write(str(seen + 1))
    if mode == "busy" or seen == 0:
        emit({"type": "error", "message": "exceeded retry limit, last status: 429 Too Many Requests"}); sys.exit(1)
turn = ({"input_tokens": 30, "cached_input_tokens": 25, "output_tokens": 7} if resume else
        {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2})
total = {key: before[key] + turn[key] for key in turn}
if "--ephemeral" not in args or resume:  # Codex 0.164 appends a resumed turn even with --ephemeral.
    os.makedirs(os.path.dirname(rollout), exist_ok=True)
    open(rollout, "a").write(json.dumps(total) + "\\n")
if mode == "echo":
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": json.dumps(
        {"args": args, "cwd": os.getcwd()})})}})
    emit({"type": "turn.completed", "usage": total}); sys.exit(0)
if mode == "sleep":
    time.sleep(30)
if mode == "reject":
    print("ERROR: The 'gpt-6-astra' model requires a newer version of Codex.", file=sys.stderr); sys.exit(1)
if mode == "limit":
    print("You've hit your usage limit. Try again later.", file=sys.stderr); sys.exit(1)
if mode == "garbage":
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "not json"}}); sys.exit(0)
emit({"type": "item.completed", "item": {"type": "web_search", "id": "w1", "status": "completed", "action": {"type": "search", "query": "PLA"}}})
emit({"type": "item.completed", "item": {"type": "mcp_tool_call", "id": "m1", "server": "oopc", "tool": "search_knowledge", "status": "completed"}})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ok:" + str("--output-schema" in args) + ":" + str("features.shell_tool=false" in args)})}})
emit({"type": "turn.completed", "usage": total})
if mode == "crash-after-answer":
    sys.exit(3)
"""

CLAUDE = """
import json, os, re, sys, uuid
args = sys.argv[1:]
prompt = sys.stdin.read()
def emit(value): print(json.dumps(value), flush=True)
# Like Claude Code: a session is saved under $CLAUDE_CONFIG_DIR/projects/<working folder> unless
# --no-session-persistence, and --resume ID continues it from the same working folder.
session = args[args.index("--resume") + 1] if "--resume" in args else str(uuid.uuid4())
project = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
transcript = os.path.join(project, session + ".jsonl")
if "--resume" in args and not os.path.exists(transcript):
    print("No conversation found with session ID: " + session, file=sys.stderr); sys.exit(1)
emit({"type": "system", "subtype": "init", "session_id": session, "cwd": os.getcwd()})
# Large tool results (fetched pages and PDFs) are kept beside the session even when it is not saved.
os.makedirs(os.path.join(project, session, "tool-results"), exist_ok=True)
open(os.path.join(project, session, "tool-results", "webfetch.pdf"), "w").write("%PDF")
if "--no-session-persistence" not in args:
    os.makedirs(project, exist_ok=True)
    open(transcript, "a").write(json.dumps({"prompt": prompt}) + "\\n")
emit({"type": "result", "subtype": "success", "session_id": session,
      "structured_output": {"answer": json.dumps({"args": args, "cwd": os.getcwd()})},
      "usage": {"input_tokens": 3, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 1, "output_tokens": 4}})
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
                 ("Failed to authenticate: OAuth session expired and could not be refreshed", "not-signed-in"),
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
        claude = self.folder / "claude"
        claude.write_text("#!" + sys.executable + "\n" + CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
        self.codex_home, self.claude_home = self.folder / "codex-home", self.folder / "claude-home"
        (self.folder / "tmp").mkdir()
        patches = [mock.patch.dict(os.environ, {"OOPC_CODEX_BINARY": str(binary), "OOPC_CLAUDE_BINARY": str(claude),
                                                "CODEX_HOME": str(self.codex_home),
                                                "CLAUDE_CONFIG_DIR": str(self.claude_home)}),
                   mock.patch.object(engines, "host_engines_allowed", return_value=True),
                   mock.patch.object(tempfile, "tempdir", str(self.folder / "tmp"))]
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
        self.assertEqual(len(lines), 5)

    def index(self, folder):
        """The threads the fake Codex's state database in `folder` holds."""
        path = Path(folder) / "state_5.sqlite"
        return json.loads(path.read_text())["threads"] if path.exists() else []

    def test_an_unsaved_session_is_ephemeral_and_returns_the_engines_own_session_id(self):
        result, lines = self.run_mode("echo")
        self.assertIn("--ephemeral", json.loads(result["answer"]["answer"])["args"])
        self.assertEqual(result["sessionId"], json.loads(lines[0])["thread_id"])
        self.assertEqual(list(self.codex_home.rglob("*.jsonl")), [])
        self.assertNotIn(result["sessionId"], self.index(self.codex_home))
        self.mode.write_text("two-ids")  # The first id the stream reports is the session's.
        result = engines.run_session("codex", "Question", SCHEMA, timeout=20, progress=lines.append)
        self.assertEqual(result["sessionId"], json.loads(lines[-6])["thread_id"])
        self.mode.write_text("echo")
        result = engines.run_session("claude-code", "Question", SCHEMA, timeout=20)
        self.assertIn("--no-session-persistence", json.loads(result["answer"]["answer"])["args"])
        self.assertTrue(result["sessionId"])
        # Nothing of an unsaved Claude Code session is left: no transcript, fetched files or project folder.
        self.assertEqual(list((self.claude_home / "projects").iterdir()), [])
        with self.assertRaises(ValueError):  # A saved session needs a working folder for its later turns.
            engines.run_session("codex", "Question", SCHEMA, timeout=20, persist=True)

    def test_a_saved_codex_session_is_resumed_in_its_folder_with_its_own_usage_then_deleted(self):
        self.mode.write_text("echo")
        mine = self.codex_home / "sessions/2026/10/25/rollout-2026-10-25T00-00-00-01a16980-5f53-7bb0-9424-b3e5e61463a1.jsonl"
        mine.parent.mkdir(parents=True)
        mine.write_text("{}\n")  # The user's own history
        work = engines.session_folder("question")
        self.assertEqual(stat.S_IMODE(work.stat().st_mode), 0o700)
        first = engines.run_session("codex", "Question", SCHEMA, timeout=20, persist=True, folder=work)
        seen = json.loads(first["answer"]["answer"])
        self.assertNotIn("--ephemeral", seen["args"])
        self.assertEqual(Path(seen["cwd"]).resolve(), work.resolve())
        # Codex's index of the thread is in the session's folder, never in $CODEX_HOME, and that index was made empty
        # first, so the user's own threads were not copied into it; no memories are made of the session.
        self.assertEqual((self.index(work), (self.codex_home / "state_5.sqlite").exists()), ([first["sessionId"]], False))
        for flag in ('sqlite_home="%s"' % work, "memories.generate_memories=false", "memories.use_memories=false"):
            self.assertIn(flag, seen["args"])
        [rollout] = self.codex_home.rglob("rollout-*-%s.jsonl" % first["sessionId"])
        self.assertTrue(engines.saved_session_exists("codex", first["sessionId"]))
        self.assertEqual(json.loads((work / engines.SESSION_RECORD).read_text())["sessionIds"], [first["sessionId"]])
        second = engines.run_session("codex", "Findings", SCHEMA, timeout=20, resume=first["sessionId"],
                                     previous_usage=first["sessionUsage"], folder=work)
        seen = json.loads(second["answer"]["answer"])
        # `codex exec resume` takes neither -s nor --cd: the sandbox by config, the folder as the working folder.
        self.assertEqual((seen["args"][:2], seen["args"][-2:]), (["exec", "resume"], [first["sessionId"], "-"]))
        self.assertFalse({"-s", "--cd"} & set(seen["args"]))
        for flag in ("--ephemeral", 'sandbox_mode="read-only"', 'sqlite_home="%s"' % work,
                     "memories.generate_memories=false", "memories.use_memories=false"):
            self.assertIn(flag, seen["args"])
        self.assertEqual(Path(seen["cwd"]).resolve(), work.resolve())
        self.assertEqual((self.index(work), (self.codex_home / "state_5.sqlite").exists()), ([first["sessionId"]], False))
        # Codex reports the thread's usage from its start: the turn's own usage is the difference.
        self.assertEqual(first["usage"], {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2})
        self.assertEqual(second["usage"], {"input_tokens": 30, "cached_input_tokens": 25, "output_tokens": 7})
        self.assertEqual(second["sessionUsage"], {"input_tokens": 40, "cached_input_tokens": 29, "output_tokens": 9})
        self.assertEqual((second["sessionId"], engines.discard_session("codex", first["sessionId"], work)),
                         (first["sessionId"], []))
        self.assertFalse(rollout.exists() or work.exists() or engines.saved_session_exists("codex", first["sessionId"]))
        self.assertEqual([p.name for p in self.codex_home.rglob("*")
                          if p.is_file() and first["sessionId"] in p.read_text()], [])  # Nothing names it any more.
        # A resumed turn whose session is gone fails with a named reason.
        work = engines.session_folder("question")
        with self.assertRaises(engines.EngineError) as raised:
            engines.run_session("codex", "Findings", SCHEMA, timeout=20, resume=first["sessionId"], folder=work)
        self.assertEqual(raised.exception.reason, "crashed")
        engines.discard_session("codex", None, work)

    def test_a_saved_claude_session_is_resumed_by_its_id_in_the_same_folder_then_deleted(self):
        work = engines.session_folder("question")
        first = engines.run_session("claude-code", "Question", SCHEMA, timeout=20, persist=True, folder=work)
        self.assertNotIn("--no-session-persistence", json.loads(first["answer"]["answer"])["args"])
        [transcript] = self.claude_home.rglob(first["sessionId"] + ".jsonl")
        second = engines.run_session("claude-code", "Findings", SCHEMA, timeout=20, resume=first["sessionId"],
                                     previous_usage=first["sessionUsage"], folder=work)
        args = json.loads(second["answer"]["answer"])["args"]
        self.assertEqual(args[args.index("--resume") + 1], first["sessionId"])
        self.assertNotIn("--no-session-persistence", args)
        # Taken as each run's own usage (unverified for a resumed run): nothing is subtracted.
        self.assertEqual(second["usage"], first["usage"])
        self.assertEqual(second["sessionUsage"], {key: 2 * value for key, value in first["usage"].items()})
        self.assertEqual(engines.discard_session("claude-code", first["sessionId"], work), [])
        self.assertFalse(transcript.exists() or transcript.parent.exists() or work.exists())

    def test_a_failed_first_turn_deletes_what_it_saved(self):
        self.mode.write_text("garbage")
        work = engines.session_folder("question")
        with self.assertRaises(engines.EngineError) as raised:
            engines.run_session("codex", "Question", SCHEMA, timeout=20, persist=True, folder=work)
        self.assertEqual(raised.exception.reason, "invalid-output")
        self.assertTrue(raised.exception.session_id)
        self.assertEqual(list(self.codex_home.rglob("*.jsonl")), [])  # Never resumed, so deleted at once.
        engines.discard_session("codex", None, work)
        self.assertFalse(work.exists())

    def test_claude_quota_that_the_cli_no_longer_reports_is_named_so(self):
        # Claude Code 2.1.308 answers `/usage` in print mode with the session's cost, not its subscription limits.
        report = json.dumps({"type": "result", "local_command": "usage", "result": "Total cost:            $0.0000\n"
                             "Usage:                 0 input, 0 output, 0 cache read, 0 cache write"})
        done = subprocess.CompletedProcess([], 0, stdout=report, stderr="")
        with mock.patch.object(engines.subprocess, "run", return_value=done):
            value = engines.read_quota("claude-code")
        self.assertEqual((value["remainingPercent"], value["reason"]), (None, "not-reported"))

    def test_engine_homes_are_only_used_when_set_under_tests(self):
        with mock.patch.object(engines, "host_engines_allowed", return_value=False):
            with mock.patch.dict(os.environ, {"CODEX_HOME": "", "CLAUDE_CONFIG_DIR": ""}):
                self.assertEqual((engines.engine_home("codex"), engines.engine_home("claude-code")), (None, None))
                self.assertFalse(engines.saved_session_exists("codex", "01a16980-5f53-7bb0-9424-b3e5e61463a1"))
            # An inherited CODEX_HOME is not a test's own: honoured only when the test opts in.
            self.assertEqual(engines.engine_home("codex"), None)
            with mock.patch.dict(os.environ, {"OOPC_TEST_ENGINE_HOMES": "1"}):
                self.assertEqual(engines.engine_home("codex"), self.codex_home)
        self.assertEqual(engines.engine_home("codex"), self.codex_home)
        # A recorded folder that is not a session folder is never deleted.
        other = self.folder / "not-a-session"
        other.mkdir()
        engines.discard_session("codex", None, other)
        self.assertTrue(other.exists())

    def test_a_rate_limited_resumed_turn_resumes_the_same_session_after_the_pause(self):
        self.mode.write_text("echo")
        work = engines.session_folder("question")
        first = engines.run_session("codex", "Question", SCHEMA, timeout=20, persist=True, folder=work)
        self.mode.write_text("busy-once")
        with mock.patch.object(engines, "RATE_LIMIT_PAUSE", 0), mock.patch.object(engines, "RATE_LIMIT_MIN_SECONDS", 1), \
                mock.patch.object(engines.time, "sleep"):
            second = engines.run_session("codex", "Findings", SCHEMA, timeout=20, resume=first["sessionId"],
                                         previous_usage=first["sessionUsage"], folder=work)
        self.assertEqual((second["sessionId"], second["answer"]["answer"]), (first["sessionId"], "ok:True:True"))
        self.assertEqual(Path(str(self.mode) + ".calls").read_text(), "2")
        self.assertEqual(second["usage"], {"input_tokens": 30, "cached_input_tokens": 25, "output_tokens": 7})
        engines.discard_session("codex", first["sessionId"], work)
        self.assertEqual(list(self.codex_home.rglob("*.jsonl")), [])

    def test_a_turns_own_usage_is_the_difference_only_when_the_report_covers_the_earlier_turns(self):
        before = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}
        later = {"input_tokens": 250, "cached_input_tokens": 140, "output_tokens": 25}
        self.assertEqual(engines.turn_usage("codex", later, before),
                         {"input_tokens": 150, "cached_input_tokens": 100, "output_tokens": 15})
        own = {"input_tokens": 90, "cached_input_tokens": 80, "output_tokens": 20}  # Smaller: only the turn's own.
        self.assertEqual(engines.turn_usage("codex", own, before), own)
        self.assertEqual(engines.turn_usage("claude-code", later, before), later)

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
