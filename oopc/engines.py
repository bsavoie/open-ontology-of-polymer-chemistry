"""Subscription engines: run one Codex or Claude Code session and return its answer.

Every call either returns a valid structured answer or raises `EngineError` with
a named reason. There is no "unknown outcome" state: a session that produced a
valid final answer succeeded, whatever happened while its process was cleaned
up, and a session that did not produce one failed. `RETRYABLE` reasons are safe
to try once more.

Both engines use the user's own saved subscription sign-in. API keys and
provider overrides are removed from the worker environment. Workers get web
access and, when given, the coordinator-hosted `oopc` MCP tools; they have no
shell and cannot read local files.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .util import atomic_json, now, read_json

CODEX, CLAUDE = "codex", "claude-code"
ENGINES = {
    CODEX: {"label": "ChatGPT (Codex)", "model": "gpt-6.1-sol"},
    CLAUDE: {"label": "Claude Code", "model": "claude-opus-5-5"},
}
PREFERENCE = ".oopc/worker-runtime.json"
REASONS = ("timeout", "crashed", "rejected", "invalid-output", "interrupted", "not-signed-in", "quota", "rate-limited")
RETRYABLE = frozenset({"crashed", "interrupted", "invalid-output"})
# A rate-limited session (HTTP 429 after the engine's own retries) is tried once more inside `run_session`, after this
# pause, when its time limit leaves at least RATE_LIMIT_MIN_SECONDS; a usage limit (`quota`) is final.
RATE_LIMIT_PAUSE, RATE_LIMIT_MIN_SECONDS = 120, 60
PROJECT = Path(__file__).resolve().parent.parent
API_KEYS = {"CODEX_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
CLAUDE_WEB_TOOLS = ("WebSearch", "WebFetch")
CLAUDE_DENIED = ("Bash", "Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "Task", "Agent", "TodoWrite")
CLAUDE_AUTH_HOSTS = frozenset({"claude.ai", "claude.com", "console.anthropic.com", "platform.claude.com"})


class EngineError(RuntimeError):
    """A failed session, with one of `REASONS`."""

    def __init__(self, reason, message, *, seconds=None, usage=None):
        if reason not in REASONS:
            raise ValueError("Unknown engine failure reason: " + str(reason))
        super().__init__(message)
        self.reason, self.seconds, self.usage = reason, seconds, usage or {}

    @property
    def retryable(self):
        return self.reason in RETRYABLE

    def summary(self):
        return {"reason": self.reason, "message": str(self)[:600], "seconds": self.seconds}


# ---------------------------------------------------------------------------
# Engine choice

def host_engines_allowed():
    """Tests never reach this machine's engines unless explicitly allowed."""
    return "unittest" not in sys.modules or os.environ.get("OOPC_ALLOW_HOST_ENGINES") == "1"


def preferred_engine(root):
    path = Path(root) / PREFERENCE
    try:
        value = read_json(path) if path.is_file() and not path.is_symlink() else {}
    except (OSError, ValueError):
        value = {}
    engine = value.get("runtime") if isinstance(value, dict) else None
    return engine if engine in ENGINES else CODEX


def select_engine(root, engine):
    if engine not in ENGINES:
        raise ValueError("Choose a supported subscription engine")
    path = Path(root) / PREFERENCE
    if path.is_symlink():
        raise ValueError("Engine preference cannot follow symlink storage")
    atomic_json(path, {"runtime": engine}, private=True)
    return engine


def signed_in(engine):
    """Saved subscription sign-in only; never starts a login or a model call."""
    if not host_engines_allowed():
        return False
    if engine == CLAUDE:
        return is_subscription(claude_auth_status())
    if engine == CODEX:
        try:
            login = subprocess.run([resolve_codex_binary(), "login", "status"], capture_output=True, text=True,
                                   timeout=20, env=codex_environment(), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return login.returncode == 0 and "chatgpt" in (login.stdout + login.stderr).lower()
    return False


def available_engines(reserve_percent=0, *, signed=None, quota=None):
    """Signed-in engines whose known remaining quota is above the reserve.

    `reserve_percent` is one number for every engine or a per-engine mapping.

    Unknown quota does not block: a session that hits a limit fails with
    reason `quota`, which is the same outcome with less guessing.
    """
    signed, quota = signed or signed_in, quota or read_quota
    available = {}
    for engine in ENGINES:
        if not signed(engine):
            continue
        reserve = reserve_percent.get(engine, 0) if isinstance(reserve_percent, dict) else reserve_percent
        remaining = quota(engine).get("remainingPercent") if reserve > 0 else None
        if remaining is None or remaining >= reserve:
            available[engine] = remaining
    return available


def choose_engine(preferred=None, *, avoid=None, reserve_percent=0, signed=None, quota=None, excluded=()):
    """The preferred engine if usable, else another; `avoid` is chosen only as a last resort."""
    available = {e: q for e, q in available_engines(reserve_percent, signed=signed, quota=quota).items() if e not in excluded}
    if not available:
        return None
    order = sorted(available, key=lambda e: (e == avoid, e != preferred, -(available[e] or 0), e))
    return order[0]


# ---------------------------------------------------------------------------
# Binaries, environments and sign-in state

def resolve_codex_binary():
    """Prefer the maintained app runtime over an older separately installed CLI."""
    override = os.environ.get("OOPC_CODEX_BINARY")
    if override:
        return override
    for candidate in ("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                      "/Applications/Codex.app/Contents/Resources/codex", "/Applications/ChatGPT.app/Contents/Resources/codex"):
        if Path(candidate).is_file():
            return candidate
    return shutil.which("codex") or "codex"


def resolve_claude_binary():
    """An explicit override, an installed CLI, then the newest desktop-bundled CLI."""
    override = os.environ.get("OOPC_CLAUDE_BINARY")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude"):
        if candidate.is_file():
            return str(candidate)
    bundled = Path.home() / "Library/Application Support/Claude/claude-code"
    versions = []
    if bundled.is_dir():
        for folder in bundled.iterdir():
            parts = folder.name.split(".")
            if not all(part.isdigit() for part in parts):
                continue
            # The app has kept the CLI both directly in the version folder and one folder deeper.
            for binary in [folder / "claude.app/Contents/MacOS/claude", *folder.glob("*/claude.app/Contents/MacOS/claude")]:
                if binary.is_file():
                    versions.append((tuple(int(part) for part in parts), str(binary)))
    return max(versions)[1] if versions else "claude"


def codex_environment(base=None):
    return {k: v for k, v in (base if base is not None else os.environ).items() if k not in API_KEYS}


def claude_environment(base=None):
    """Worker environment without API keys, provider overrides or host session credentials."""
    environment = {}
    for key, value in (base if base is not None else os.environ).items():
        upper = key.upper()
        if (upper.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_", "OPENAI_", "AZURE_OPENAI_", "CODEX_"))
                or upper in {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR",
                             "AWS_BEARER_TOKEN_BEDROCK", "VERTEX_REGION_CLAUDE"}):
            continue
        environment[key] = value
    environment["DISABLE_AUTOUPDATER"] = "1"
    return environment


def claude_auth_status(binary=None, timeout=20):
    """Sanitized `claude auth status`; never reads credential files."""
    try:
        completed = subprocess.run([binary or resolve_claude_binary(), "auth", "status", "--json"], capture_output=True,
                                   text=True, timeout=timeout, env=claude_environment(), stdin=subprocess.DEVNULL)
        value = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"loggedIn": False, "available": False}
    if not isinstance(value, dict):
        return {"loggedIn": False, "available": False}
    keep = ("loggedIn", "authMethod", "apiProvider", "subscriptionType", "email", "organizationName")
    status = {key: value[key] for key in keep if isinstance(value.get(key), (str, bool))}
    status["available"] = True
    return status


def is_subscription(status):
    """A first-party claude.ai login; API-key and third-party billing are refused."""
    method = str(status.get("authMethod", "")).lower()
    return (status.get("loggedIn") is True and status.get("apiProvider", "firstParty") == "firstParty"
            and method not in {"", "none", "api_key", "apikey", "api-key", "console"} and "key" not in method)


def engine_installed(engine):
    if engine == CLAUDE:
        binary = resolve_claude_binary()
        return Path(binary).is_file() or bool(shutil.which(binary))
    return bool(shutil.which(resolve_codex_binary()))


# ---------------------------------------------------------------------------
# Quota (display and background reserve only; never a model call)

_USAGE_LINE = re.compile(r"^\s*(?P<label>Current [^:\n]{1,60}):\s*(?P<used>\d{1,3}(?:\.\d+)?)\s*%\s*used", re.I | re.M)


def _quota(windows, reason=None):
    usable = [w for w in windows if isinstance(w.get("remainingPercent"), (int, float))]
    summary = {"remainingPercent": min(w["remainingPercent"] for w in usable) if usable else None,
               "windows": usable, "checkedAt": now(), "status": "available" if usable else "unavailable"}
    if not usable and reason:
        summary["reason"] = reason
    return summary


def parse_claude_usage(stdout):
    """Extract "N% used" windows from the `/usage` report text."""
    text = stdout or ""
    try:
        value = json.loads(text)
        if isinstance(value, dict) and isinstance(value.get("result"), str):
            text = value["result"]
    except ValueError:
        pass
    windows = []
    for match in _USAGE_LINE.finditer(text):
        used = float(match.group("used"))
        if 0 <= used <= 100:
            windows.append({"limitId": match.group("label").strip().lower(), "usedPercent": used,
                            "remainingPercent": round(100 - used, 2)})
    return windows


def parse_codex_limits(response):
    """Only the exposed Codex/Astra windows; a missing reading stays unknown."""
    buckets = response.get("rateLimitsByLimitId") if isinstance(response, dict) else None
    if isinstance(buckets, dict) and buckets:
        selected = {k: v for k, v in buckets.items() if k == "codex" or "astra" in k.lower() or "gpt-6" in k.lower()}
    else:
        legacy = response.get("rateLimits") if isinstance(response, dict) else None
        selected = {"codex": legacy} if isinstance(legacy, dict) else {}
    windows = []
    for limit_id, snapshot in selected.items():
        if not isinstance(snapshot, dict):
            continue
        for name in ("primary", "secondary"):
            window = snapshot.get(name)
            used = window.get("usedPercent") if isinstance(window, dict) else None
            if isinstance(used, (int, float)) and not isinstance(used, bool) and 0 <= used <= 100:
                windows.append({"limitId": limit_id, "window": name, "usedPercent": used,
                                "remainingPercent": 100 - used, "resetsAt": window.get("resetsAt")})
        if snapshot.get("rateLimitReachedType"):
            windows.append({"limitId": limit_id, "window": "reached-limit", "usedPercent": 100, "remainingPercent": 0})
    return windows


def read_quota(engine, timeout=20):
    if engine not in ENGINES:
        raise ValueError("Unsupported engine: %r" % (engine,))
    if not host_engines_allowed():
        return _quota([], "disabled-under-tests")
    if engine == CLAUDE:
        try:
            completed = subprocess.run([resolve_claude_binary(), "-p", "/usage", "--output-format", "json",
                                        "--setting-sources", "local", "--strict-mcp-config", "--no-session-persistence",
                                        "--tools", ""], capture_output=True, text=True, timeout=timeout * 3,
                                       env=claude_environment(), stdin=subprocess.DEVNULL, cwd=Path.home())
        except (OSError, subprocess.TimeoutExpired):
            return _quota([], "cli-error")
        reason = "cli-error" if completed.returncode or not (completed.stdout or "").strip() else "unrecognized-report"
        return _quota(parse_claude_usage(completed.stdout), reason)
    return _read_codex_quota(timeout)


def _read_codex_quota(timeout):
    """Read saved-account limits through the local app-server; no model calls."""
    import selectors
    process = None
    try:
        process = subprocess.Popen([resolve_codex_binary(), "app-server", "--stdio", "-c", 'forced_login_method="chatgpt"'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=codex_environment())
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending, deadline = b"", time.monotonic() + timeout

        def send(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            process.stdin.flush()

        def receive(request_id):
            nonlocal pending
            while time.monotonic() < deadline:
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if event.get("id") == request_id:
                        if "error" in event:
                            raise RuntimeError("app-server returned an error")
                        return event.get("result", {})
                if process.poll() is not None:
                    raise RuntimeError("app-server exited")
                if selector.select(max(0, deadline - time.monotonic())):
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        raise RuntimeError("app-server closed")
                    pending += block
            raise TimeoutError("quota read timed out")

        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "oopc-quota", "version": "1"}}})
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read"})
        return _quota(parse_codex_limits(receive(2)), "unreadable")
    except (OSError, RuntimeError, TimeoutError, ValueError):
        return _quota([], "cli-error")
    finally:
        if process is not None:
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()


# ---------------------------------------------------------------------------
# Stream parsing: each engine's event stream to (answer text, usage, tools)

# What a page that did not open returns instead of the document: an error page or a browser challenge.
REFUSED_PAGE = re.compile(r"internal error|checking your browser|client challenge|something went wrong|not a bot|"
                          r"establishing a secure connection|just a moment|access denied|forbidden|\b40[34]\b|"
                          r"server returned http [45]\d\d|request failed|unable to (?:fetch|retrieve)|captcha", re.I)
CODEX_ACTIONS = {"search": "search", "open_page": "open", "find_in_page": "find"}


def _codex_web_outcome(item, action):
    """Whether a Codex web action got the document: an opened page reports its length ("Total lines: 1048"); an error
    page or browser challenge has one line under its own title."""
    results = [r for r in item.get("results") or [] if isinstance(r, dict)]
    if action == "search":
        return "searched" if results else "no-results"
    if action not in ("open", "find"):
        return ""
    first = results[0] if results else {}
    lines = re.match(r"Total lines: (\d+)", str(first.get("snippet") or ""))
    if REFUSED_PAGE.search(str(first.get("title") or "")) or not lines or int(lines.group(1)) <= 1:
        return "refused"
    return "opened"


def parse_codex_stream(stdout):
    answer, usage, tools = None, {}, []
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item") if isinstance(event.get("item"), dict) else None
        if event.get("type") == "item.completed" and item:
            if item.get("type") in {"web_search", "mcp_tool_call", "command_execution"}:
                record = {key: item[key] for key in ("type", "id", "server", "tool", "status") if key in item}
                action = item.get("action") if isinstance(item.get("action"), dict) else {}
                query = item.get("query") or action.get("query")
                if query:
                    record["query"] = str(query)[:300]
                if action.get("url"):
                    record["url"] = str(action["url"])[:500]
                if item.get("type") == "web_search":
                    kind = CODEX_ACTIONS.get(action.get("type"), "other")
                    record["action"] = kind
                    outcome = _codex_web_outcome(item, kind)
                    if outcome:
                        record["outcome"] = outcome
                tools.append(record)
            elif item.get("type") == "agent_message":
                answer = item.get("text")
        elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
            usage = {key: raw.get(key) for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
    return answer, usage, tools


def parse_claude_stream(stdout):
    answer, usage, calls, errors = None, {}, [], {}
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if event.get("type") == "assistant":
            calls.extend(block for block in content if isinstance(block, dict) and block.get("type") == "tool_use")
        elif event.get("type") == "user":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    returned = block.get("content")
                    if isinstance(returned, list):
                        returned = " ".join(str(part.get("text") or "") for part in returned if isinstance(part, dict))
                    # A fetch that reached no document says so in its first words ("The server returned HTTP 403").
                    refused = bool(REFUSED_PAGE.search(str(returned or "")[:200]))
                    errors[block.get("tool_use_id")] = "failed" if block.get("is_error") is True else (
                        "refused" if refused else "")
        elif event.get("type") == "result":
            raw = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            if isinstance(raw.get("input_tokens"), int) and isinstance(raw.get("output_tokens"), int):
                cached = raw.get("cache_read_input_tokens") or 0
                usage = {"input_tokens": raw["input_tokens"] + (raw.get("cache_creation_input_tokens") or 0) + cached,
                         "cached_input_tokens": cached, "output_tokens": raw["output_tokens"]}
            if event.get("subtype") == "success" and event.get("is_error") is not True:
                structured = event.get("structured_output")
                if isinstance(structured, dict):
                    answer = json.dumps(structured, ensure_ascii=False)
                elif isinstance(event.get("result"), str) and event["result"].strip():
                    answer = event["result"].strip()
            elif event.get("is_error") or str(event.get("subtype", "")).startswith("error"):
                answer = None
    tools = []
    for block in calls:
        name = str(block.get("name") or "")
        returned = errors.get(block.get("id"))
        record = {"id": block.get("id"), "tool": name, "status": "failed" if returned == "failed" else "completed"}
        arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name.startswith("mcp__"):
            server, _, tool = name[5:].partition("__")
            record.update(type="mcp_tool_call", server=server, tool=tool)
        elif name == "StructuredOutput":
            continue
        elif name in CLAUDE_WEB_TOOLS:
            record["type"] = "web_search"
            if arguments.get("query"):
                record["query"] = str(arguments["query"])[:300]
            if arguments.get("url"):
                record["url"] = str(arguments["url"])[:500]
            record["action"] = "open" if name == "WebFetch" else "search"
            if block.get("id") in errors:
                record["outcome"] = ("refused" if returned else "opened") if name == "WebFetch" else (
                    "failed" if returned == "failed" else "searched")
        else:
            record["type"] = "other_tool"
        tools.append(record)
    return answer, usage, tools


def classify_failure(returncode, stdout, stderr):
    """A named reason for a session that produced no valid answer."""
    text = ((stderr or "") + "\n" + (stdout or "")[-4000:]).lower()
    if re.search(r"usage[ _]limit|quota[ _]exceeded|insufficient_quota|hit your limit|limit[ _]reached", text):
        return "quota"
    # Too many requests at once: the subscription still has quota (2026-10-14: two hours of 429s at 74% remaining).
    if re.search(r"rate[ _]limit|too many requests|\bstatus:? ?429\b", text):
        return "rate-limited"
    if re.search(r"not logged in|login required|please log in|unauthorized|\bstatus:? ?401\b", text):
        return "not-signed-in"
    if re.search(r"invalid_request_error|requires a newer version|400 bad request|model is not supported|unsupported model", text):
        return "rejected"
    if returncode is not None and returncode < 0:
        return "interrupted"
    return "crashed"


# ---------------------------------------------------------------------------
# Hosting MCP tools for a worker

@contextmanager
def hosted_tools(service):
    """Serve an MCP service on a private Unix socket; the worker connects through `proxy`."""
    import io
    with tempfile.TemporaryDirectory(prefix="oopc-rpc-") as folder:
        path = str(Path(folder) / "mcp.sock")

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                source = io.TextIOWrapper(self.rfile, encoding="utf-8")
                target = io.TextIOWrapper(self.wfile, encoding="utf-8", write_through=True)
                try:
                    service.serve(source, target)
                finally:
                    source.detach()
                    target.detach()

        server = socketserver.ThreadingUnixStreamServer(path, Handler)
        server.daemon_threads = True
        os.chmod(path, 0o600)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield {"command": sys.executable,
                   "args": ["-c", "import sys;sys.path.insert(0," + repr(str(PROJECT)) + ");"
                            "from oopc.engines import proxy;proxy(" + repr(path) + ")"]}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def proxy(socket_path):
    """Worker-side bridge between MCP stdio and the coordinator's socket."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(socket_path)

        def outbound():
            try:
                for line in sys.stdin.buffer:
                    connection.sendall(line)
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        threading.Thread(target=outbound, daemon=True).start()
        while True:
            block = connection.recv(65536)
            if not block:
                break
            sys.stdout.buffer.write(block)
            sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Running one session

_LIVE = set()
_LIVE_LOCK = threading.Lock()


def _stop_live_workers():
    with _LIVE_LOCK:
        groups = list(_LIVE)
    for pid in groups:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


atexit.register(_stop_live_workers)


def codex_command(schema_path, folder, *, model, web, tools):
    command = [resolve_codex_binary(), "exec", "-m", model, "-s", "read-only", "--ephemeral", "--ignore-user-config",
               "--skip-git-repo-check", "--json", "--output-schema", str(schema_path), "--cd", str(folder),
               "-c", 'forced_login_method="chatgpt"', "-c", 'web_search="live"' if web else 'web_search="disabled"',
               "-c", "features.apps=false", "-c", "features.skill_mcp_dependency_install=false",
               "-c", "features.shell_tool=false", "-c", "features.unified_exec=false"]
    if tools:
        command += ["-c", "mcp_servers.oopc.command=" + json.dumps(tools["command"]),
                    "-c", "mcp_servers.oopc.args=" + json.dumps(tools["args"]),
                    "-c", "mcp_servers.oopc.required=true", "-c", "mcp_servers.oopc.startup_timeout_sec=60"]
    return command + ["-"]


def claude_command(schema, folder, *, model, web, tools):
    command = [resolve_claude_binary(), "-p", "--model", model, "--output-format", "stream-json", "--verbose",
               "--json-schema", json.dumps(schema), "--restricted", "--strict-mcp-config", "--setting-sources", "local",
               "--disable-slash-commands", "--no-session-persistence", "--permission-mode", "dontAsk",
               "--permission-prompts", "none"]
    command += ["--tools", ",".join(CLAUDE_WEB_TOOLS)] if web else ["--disallowedTools", ",".join(CLAUDE_WEB_TOOLS + CLAUDE_DENIED)]
    allowed = (["mcp__oopc"] if tools else []) + (list(CLAUDE_WEB_TOOLS) if web else [])
    if allowed:
        command += ["--allowedTools", ",".join(allowed)]
    config = Path(folder) / "mcp-config.json"
    servers = {"oopc": {"type": "stdio", "command": tools["command"], "args": tools["args"]}} if tools else {}
    config.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return command + ["--mcp-config", str(config)]


def _run_process(command, *, prompt, cwd, env, timeout, on_line, idle=None):
    """Run in a fresh process group; stream stdout; stop the whole group on timeout, or when it has written nothing
    for `idle` seconds. Returns the exit code, output, errors and why it was stopped ("limit", "idle" or "")."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=cwd, env=env, start_new_session=True)
    with _LIVE_LOCK:
        _LIVE.add(process.pid)
    awake = None
    if sys.platform == "darwin" and Path("/usr/bin/caffeinate").is_file():
        # Keep the Mac from idle-sleeping while this worker runs; ends with it.
        try:
            awake = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(process.pid)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            awake = None
    out, err, heard = [], [], [time.monotonic()]

    def pump_out():
        for line in process.stdout:
            heard[0] = time.monotonic()
            out.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass

    def pump_err():
        err.append(process.stderr.read())
    readers = [threading.Thread(target=pump_out, daemon=True), threading.Thread(target=pump_err, daemon=True)]
    for reader in readers:
        reader.start()
    stopped, deadline = "", time.monotonic() + timeout
    try:
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except BrokenPipeError:
            pass
        while process.poll() is None:
            clock = time.monotonic()
            if clock >= deadline:
                stopped = "limit"
                break
            if idle and clock - heard[0] >= idle:
                stopped = "idle"  # A session silent this long has stalled (seen after a completed web action).
                break
            try:
                process.wait(timeout=min(deadline - clock, 1.0 if idle else deadline - clock))
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except OSError:
                    pass
                try:
                    process.wait(timeout=3)
                    break
                except subprocess.TimeoutExpired:
                    continue
        with _LIVE_LOCK:
            _LIVE.discard(process.pid)
        for reader in readers:
            reader.join(5)
        for stream in (process.stdout, process.stderr):
            stream.close()
        if awake is not None:
            if awake.poll() is None:
                awake.terminate()
            try:
                awake.wait(timeout=2)
            except subprocess.TimeoutExpired:
                awake.kill()
    return process.returncode, "".join(out), "".join(err), stopped


def run_session(engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
    """One fresh session. Returns a result dict or raises EngineError.

    `tools` is an MCP service object (with `serve`) hosted for this session only.
    `progress` receives each raw stream line, for display. A rate-limited session is started once more after
    RATE_LIMIT_PAUSE seconds, within the same time limit; callers' own retry rules apply to the other reasons.
    `idle` stops a session that writes nothing for that many seconds (a `timeout`); reviews and checks use it.
    """
    started = time.monotonic()
    try:
        return _session(engine, prompt, schema, tools=tools, web=web, timeout=timeout, progress=progress, idle=idle)
    except EngineError as error:
        remaining = timeout - (time.monotonic() - started) - RATE_LIMIT_PAUSE
        if error.reason != "rate-limited" or remaining < RATE_LIMIT_MIN_SECONDS:
            raise
    time.sleep(RATE_LIMIT_PAUSE)
    return _session(engine, prompt, schema, tools=tools, web=web, timeout=int(remaining), progress=progress,
                    idle=idle)


def _session(engine, prompt, schema, *, tools, web, timeout, progress, idle=None):
    if engine not in ENGINES:
        raise ValueError("Unsupported engine")
    if not host_engines_allowed():
        raise EngineError("not-signed-in", "Engines are disabled while tests run")
    model = ENGINES[engine]["model"]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="oopc-" + engine + "-") as directory:
        folder = Path(directory)
        with (hosted_tools(tools) if tools is not None else _nothing()) as proxy_config:
            if engine == CODEX:
                schema_path = folder / "schema.json"
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                command = codex_command(schema_path, folder, model=model, web=web, tools=proxy_config)
                env, parse = codex_environment(), parse_codex_stream
            else:
                command = claude_command(schema, folder, model=model, web=web, tools=proxy_config)
                env, parse = claude_environment(), parse_claude_stream
            try:
                returncode, stdout, stderr, stopped = _run_process(command, prompt=prompt, cwd=folder, env=env,
                                                                   timeout=timeout, on_line=progress, idle=idle)
            except FileNotFoundError as error:
                raise EngineError("not-signed-in", engine + " is not installed: " + str(error)) from error
            except (KeyboardInterrupt, SystemExit):
                raise EngineError("interrupted", "The session was interrupted", seconds=time.monotonic() - started)
    seconds = round(time.monotonic() - started, 2)
    text, usage, observed = parse(stdout)
    answer = None
    if isinstance(text, str) and text.strip():
        try:
            answer = json.loads(text)
        except ValueError:
            answer = None
    if isinstance(answer, dict):
        # A valid final answer is a success even if cleanup or exit reporting failed.
        return {"engine": engine, "model": model, "sessionId": uuid.uuid4().hex, "answer": answer,
                "usage": usage, "observedTools": observed, "agentSeconds": seconds}
    if stopped == "idle":
        raise EngineError("timeout", "Stopped after %d seconds without output" % int(idle), seconds=seconds, usage=usage)
    if stopped:
        raise EngineError("timeout", "Stopped at the %d-second limit" % int(timeout), seconds=seconds, usage=usage)
    if returncode == 0:
        raise EngineError("invalid-output", "The session ended without a valid JSON answer", seconds=seconds, usage=usage)
    reason = classify_failure(returncode, stdout, stderr)
    detail = (stderr or "").strip().splitlines()[-3:] if stderr else []
    raise EngineError(reason, "%s exited with %s. %s" % (ENGINES[engine]["label"], returncode, " ".join(detail))[:600],
                      seconds=seconds, usage=usage)


@contextmanager
def _nothing():
    yield None


# ---------------------------------------------------------------------------
# Claude sign-in for the app (Codex sign-in is `openai_account.OpenAIAccount`)

def _claude_login_url(value):
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    host = parsed.hostname or ""
    if (parsed.scheme == "https" and (host in CLAUDE_AUTH_HOSTS or host.endswith(".claude.ai") or host.endswith(".anthropic.com"))
            and parsed.username is None and parsed.password is None and parsed.port in (None, 443)):
        return value
    return None


class ClaudeAccounts:
    """Sign-in through the official `claude auth login --claudeai` flow; only the CLI handles credentials."""

    def __init__(self, binary=None):
        self.binary = binary
        self._lock = threading.Lock()
        self._process = None
        self._login_url = None

    def _binary(self):
        return self.binary or resolve_claude_binary()

    def status(self):
        if not engine_installed(CLAUDE):
            return {"status": "unavailable", "account": None,
                    "message": "Install Claude Code and sign in with your Claude subscription."}
        with self._lock:
            pending = self._process is not None and self._process.poll() is None
            url = self._login_url
        status = claude_auth_status(self._binary())
        if not status.get("available"):
            return {"status": "unavailable", "account": None, "message": "Claude Code could not report its sign-in status."}
        if is_subscription(status):
            self.cancel_login()
            account = {"email": status.get("email"), "planType": status.get("subscriptionType")}
            return {"status": "connected", "account": {k: v for k, v in account.items() if v},
                    "message": "Connected through your Claude subscription."}
        if status.get("loggedIn"):
            return {"status": "unsupported", "account": None,
                    "message": "Claude Code is signed in with API or third-party billing. Sign in with a Claude subscription instead."}
        if pending:
            return {"status": "login-pending", "account": None, "loginUrl": url, "message": "Finish signing in to Claude in your browser."}
        return {"status": "disconnected", "account": None, "message": "Connect your Claude account."}

    def start_login(self):
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._login_url = None
                self._process = subprocess.Popen([self._binary(), "auth", "login", "--claudeai"], stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                 env=claude_environment(), start_new_session=True)
                threading.Thread(target=self._read_login, args=(self._process,), daemon=True).start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self._lock:
                if self._login_url or self._process.poll() is not None:
                    break
            time.sleep(0.2)
        return self.status()

    def _read_login(self, process):
        for line in iter(process.stdout.readline, ""):
            with self._lock:
                if self._login_url is None:
                    for candidate in re.findall(r"https://\S+", line):
                        url = _claude_login_url(candidate.rstrip(".,)"))
                        if url:
                            self._login_url = url
                            break

    def cancel_login(self):
        with self._lock:
            process, self._process, self._login_url = self._process, None, None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        return {"status": "disconnected", "account": None, "message": "Sign-in cancelled."}


def engines_status(root, claude_accounts, codex_accounts=None):
    """Display state for every engine and the preferred one."""
    result = {"selected": preferred_engine(root), "runtimes": {}}
    for engine, info in ENGINES.items():
        entry = {"label": info["label"], "model": info["model"]}
        try:
            entry["account"] = (claude_accounts.status() if engine == CLAUDE else
                                codex_accounts.status() if codex_accounts is not None else None)
        except Exception:
            entry["account"] = {"status": "unavailable", "account": None, "message": "Sign-in status is unavailable."}
        result["runtimes"][engine] = entry
    return result
