"""What a running private question is doing, for the Ask page.

A tracker receives each line of the worker's event stream (Claude Code
stream-JSON or Codex JSON), keeps counts of ontology, local-knowledge and web
activity plus the latest action, and writes a small private `progress.json`
beside the task. It is display only: it never changes the worker, its answer or
any accounting, and counts are what the stream reported, not a verified trace.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .util import atomic_json, now

FORMAT = "oopc-task-progress-v1"
WEB_ACTIVITY = "oopc-stream-web-activity-v2"
GRAPH_KINDS = {"search": "searches", "get_record": "records", "get_evidence": "records", "get_claims": "records",
               "traverse": "hops", "describe_vocabulary": "vocabulary", "get_recipes": "recipes",
               "search_knowledge": "knowledge"}
MAX_SITES = 12


def _quote(text, limit=80):
    text = " ".join(str(text or "").split())
    return "“" + (text[:limit] + "…" if len(text) > limit else text) + "”"


def _site(url):
    try:
        host = urlsplit(str(url)).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


class ProgressTracker:
    def __init__(self, path, *, phase, budget_seconds=None, minimum_interval=1.0):
        self.path, self.phase, self.budget = Path(path), phase, budget_seconds
        self.minimum_interval = minimum_interval
        self.lock = threading.Lock()
        self.started, self.startedAt = time.monotonic(), now()
        self.graph = {value: 0 for value in set(GRAPH_KINDS.values())}
        self.web = {"searches": 0, "pages": 0, "unclassified": 0}
        self.codex_web_items = {}
        self.sites, self.turns, self.output_tokens = [], 0, 0
        self.sources = set()  # Distinct documents opened; re-reading one does not add to it.
        self.last_action, self.last_write = "Starting the research session", 0.0
        self.waiting = False
        self._write(force=True)

    def wait(self, action):
        """The session is waiting for its engine's turn (`calls.invoke`): no clock runs, and the action says why."""
        with self.lock:
            self.waiting, self.last_action = True, action
            self._write(force=True)

    def begin(self):
        """The session has its engine: its clock starts now, as its time limit does."""
        with self.lock:
            self.started, self.startedAt, self.waiting = time.monotonic(), now(), False
            self.last_action = "Starting the research session"
            self._write(force=True)

    def __call__(self, line):
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return
        with self.lock:
            changed = self._claude(event) or self._codex(event)
            if changed:
                self._write()

    # Claude Code stream-JSON: assistant messages carry tool_use blocks.
    def _claude(self, event):
        message = event.get("message") if isinstance(event.get("message"), dict) else None
        if event.get("type") != "assistant" or message is None:
            return False
        self.turns += 1
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        if isinstance(usage.get("output_tokens"), int):
            self.output_tokens += usage["output_tokens"]
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, arguments = str(block.get("name") or ""), block.get("input") if isinstance(block.get("input"), dict) else {}
            if name.startswith("mcp__"):
                self._graph(name.rsplit("__", 1)[-1], arguments)
            elif name == "WebSearch":
                self._web_search(arguments.get("query"))
            elif name == "WebFetch":
                self._page(arguments.get("url"))
            elif name == "StructuredOutput":
                self.last_action = "Writing the answer"
        return True

    # Codex JSON: item events for web search and MCP tool calls.
    def _codex(self, event):
        item = event.get("item") if isinstance(event.get("item"), dict) else None
        if event.get("type") == "turn.completed":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            if isinstance(usage.get("output_tokens"), int):
                self.output_tokens += usage["output_tokens"]
            self.turns += 1
            return True
        if item is None:
            return False
        kind = item.get("type")
        if kind == "web_search" and event.get("type") in {"item.started", "item.updated", "item.completed"}:
            return self._codex_web(item, event["type"])
        if event.get("type") != "item.started":
            return False
        if kind == "mcp_tool_call":
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            self._graph(str(item.get("tool") or ""), arguments)
        elif kind == "agent_message":
            self.last_action = "Writing the answer"
        else:
            return False
        return True

    def _codex_web(self, item, event_type):
        """Enrich one observed item without counting each lifecycle event."""
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            if event_type != "item.started":
                return False  # No identity with which to reconcile an update.
            identifier = None
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        query = item.get("query") or action.get("query")
        queries = action.get("queries")
        if not query and isinstance(queries, list):
            query = next((value for value in queries if isinstance(value, str) and value.strip()), None)
        query = " ".join(str(query or "").split())
        url = action.get("url")
        kind = ("pages" if url or action.get("type") in {"open_page", "find_in_page"} else
                "searches" if query or action.get("type") == "search" else "unclassified")
        observed = (kind, query, str(url or ""))
        previous = self.codex_web_items.get(identifier) if identifier else None
        if previous == observed or previous and kind == "unclassified":
            return False  # A later partial event cannot erase observed detail.
        if previous:
            self.web[previous[0]] -= 1
        if identifier:
            self.codex_web_items[identifier] = observed
        if kind == "pages":
            self._page(url)
        elif kind == "searches":
            self._web_search(query)
        else:
            self.web["unclassified"] += 1
            self.last_action = "Using the web"
        return True

    def _graph(self, tool, arguments):
        kind = GRAPH_KINDS.get(tool)
        if kind is None:
            return
        self.graph[kind] += int(arguments.get("depth") or 1) if kind == "hops" else 1
        if tool == "search":
            self.last_action = "Searching the ontology for " + _quote(arguments.get("q"))
        elif tool == "search_knowledge":
            self.last_action = "Checking local knowledge for " + _quote(arguments.get("q"))
        elif tool == "traverse":
            self.last_action = "Following links from " + str(arguments.get("start", "a record"))[:80]
        else:
            self.last_action = "Reading ontology record " + str(arguments.get("id") or arguments.get("subject") or "")[:80]

    def _web_search(self, query):
        self.web["searches"] += 1
        query = " ".join(str(query or "").split())
        self.last_action = "Searching the web" + (" for " + _quote(query) if query else "")

    def _page(self, url):
        self.web["pages"] += 1
        if url:
            self.sources.add(str(url).split("#")[0].split("?")[0].rstrip("/").lower())
        site = _site(url)
        if site and site not in self.sites and len(self.sites) < MAX_SITES:
            self.sites.append(site)
        self.last_action = "Reading " + (site or "a web page")

    def snapshot(self):
        return {"format": FORMAT, "phase": self.phase, "updatedAt": now(), "waiting": self.waiting,
                "startedAt": None if self.waiting else self.startedAt,
                "elapsedSeconds": 0 if self.waiting else round(time.monotonic() - self.started, 1), "budgetSeconds": self.budget,
                "graph": dict(self.graph), "web": dict(self.web), "sites": list(self.sites),
                "webActivityProtocol": WEB_ACTIVITY,
                "sourcesOpened": len(self.sources),
                "turns": self.turns, "outputTokens": self.output_tokens, "lastAction": self.last_action,
                "notice": "Counts are what the worker reported while running; the recorded trace is authoritative."}

    def _write(self, force=False):
        if not force and time.monotonic() - self.last_write < self.minimum_interval:
            return
        self.last_write = time.monotonic()
        try:
            atomic_json(self.path, self.snapshot(), private=True)
        except OSError:
            pass  # Display only.

    def finish(self, action="Finished"):
        with self.lock:
            self.last_action = action
            self._write(force=True)


def read_progress(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("format") == FORMAT else None


def effort(result, progress=None):
    """A completed answer's effort from its retained worker result."""
    tools = result.get("observedTools") or []
    counts = {"graphLookups": 0, "knowledgeLookups": 0, "webSearches": 0, "pagesRead": 0}
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("tool") or tool.get("name") or "")
        # Claude reports both web tools with type web_search; the tool name decides.
        if tool.get("type") == "mcp_tool_call":
            counts["knowledgeLookups" if name == "search_knowledge" else "graphLookups"] += 1
        elif name == "WebFetch" or tool.get("action") in {"open", "find"}:  # Codex reports pages as web_search too.
            counts["pagesRead"] += 1
        elif tool.get("type") == "web_search" or name == "WebSearch":
            counts["webSearches"] += 1
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    value = dict(counts, inputTokens=usage.get("input_tokens"), cachedInputTokens=usage.get("cached_input_tokens"),
                 outputTokens=usage.get("output_tokens"), seconds=result.get("agentSeconds"))
    if progress:
        value.update(sites=progress.get("sites", []), graphHops=progress.get("graph", {}).get("hops"))
        if progress.get("webActivityProtocol") == WEB_ACTIVITY:
            # New trackers reconcile exact item lifecycle events. Older stored
            # counters keep their meaning; never infer pages from citations.
            value.update(webSearches=progress["web"]["searches"], pagesRead=progress["web"]["pages"],
                         unclassifiedWebCalls=progress["web"].get("unclassified", 0))
        elif not tools:  # Fall back to the live counts when the final tool list is unavailable.
            value.update(webSearches=progress["web"]["searches"], pagesRead=progress["web"]["pages"])
    return value
