"""Loopback-only app server: researcher app, operator inspector and their APIs.

Browsing uses an uninstrumented graph reader and never creates trace events.
Writes (asking, retrying, research queue, loop runs, sign-in, engine choice)
require the same origin and the per-server CSRF token.
"""
import json
import mimetypes
import secrets
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import engines, knowledge, loop
from .graph import Graph, release_diff
from .inspector_summary import read_run_summary
from .trace import TraceStore
from .util import canonical, digest, read_json, resolve_release, safe_name

MUTATIONS = {"/api/tasks", "/api/research", "/api/loop/tick", "/api/settings", "/api/account/login", "/api/account/cancel",
             "/api/runtimes/select", "/api/runtimes/claude-code/login", "/api/runtimes/claude-code/cancel"}


class Busy(ValueError):
    pass


def make_server(root, release=None, port=8765, host="127.0.0.1", *, task_service=None, account_service=None,
                claude_account_service=None, quota_service=None, loop_runner=None):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("The app binds only to loopback; private questions and traces are local")
    root = Path(root).resolve()
    release = Path(release).resolve() if release else None
    graph = Graph(release) if release else None
    release_readers = {str(release): graph} if release else {}
    traces = TraceStore(root)
    assets = Path(__file__).parent / "web"
    if task_service is None:
        from .ask import Questions
        task_service = Questions(root)
        task_service.recover()
    questions = task_service
    if account_service is None:
        from .openai_account import OpenAIAccount
        account_service = OpenAIAccount()
    accounts = account_service
    claude_accounts = claude_account_service or engines.ClaudeAccounts()
    read_quota = quota_service or engines.read_quota
    quota_cache, quota_lock = {}, threading.Lock()
    action_lock = threading.RLock()
    loop_state = {"thread": None, "last": None}
    connection = {"requested": False}
    csrf_token = secrets.token_urlsafe(32)

    def quota_hint():
        import time
        engine = engines.preferred_engine(root)
        with quota_lock:
            cached = quota_cache.get(engine)
            if cached is None or time.monotonic() - cached[0] > 60:
                cached = quota_cache[engine] = (time.monotonic(), read_quota(engine))
        summary = cached[1]
        return {"runtime": engine, "remainingPercent": summary.get("remainingPercent"), "status": summary.get("status"),
                "checkedAt": summary.get("checkedAt"), **({"reason": summary["reason"]} if summary.get("reason") else {})}

    def running_question():
        # A delivered answer whose findings are still being saved has an engine session running too.
        return any(item.get("status") == "running" or (item.get("depositState") or {}).get("status") == "saving"
                   for item in questions.list()["tasks"])

    def connect_account():
        if running_question():
            raise Busy("Wait for the running question to finish before connecting an account")
        status = accounts.status()
        if status.get("status") == "login-pending":
            connection["requested"] = True
            return status
        if status.get("status") != "disconnected":
            raise Busy("Account connection is available only after the saved account is confirmed disconnected")
        connection["requested"] = True
        return accounts.start_login()

    def run_loop():
        with action_lock:
            thread = loop_state["thread"]
            if thread is not None and thread.is_alive():
                raise Busy("The loop is already running")

            def work():
                try:
                    loop_state["last"] = loop.tick(root, runner=loop_runner)
                except Exception as error:  # Reported in the loop status; never crashes the app.
                    loop_state["last"] = {"status": "failed", "error": type(error).__name__ + ": " + str(error)[:300]}
            loop_state["thread"] = threading.Thread(target=work, daemon=True, name="oopc-loop")
            loop_state["thread"].start()
        return {"status": "started"}

    def loop_status():
        value = loop.status(root)
        thread = loop_state["thread"]
        value["running"] = bool(thread is not None and thread.is_alive())
        return value

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON fields are not allowed")
            value[key] = item
        return value

    def local_release(value):
        return resolve_release(root, safe_name(value))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, data, content_type="application/json", status=200, headers=None):
            if not isinstance(data, bytes):
                data = canonical(data)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if status != 304:
                self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if status != 304:
                self.wfile.write(data)

        def local_origin(self, write=False):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise PermissionError("Local origin required")
            authority = urlparse("http://" + hosts[0])
            if (authority.hostname not in ("localhost", "127.0.0.1", "::1") or
                    authority.username is not None or authority.password is not None or
                    authority.path or authority.query or authority.fragment or
                    (authority.port or 80) != self.server.server_port):
                raise PermissionError("Local origin required")
            origin = self.headers.get("Origin")
            if origin:
                supplied = urlparse(origin)
                if (supplied.scheme != "http" or supplied.netloc != hosts[0] or
                        supplied.path or supplied.query or supplied.fragment):
                    raise PermissionError("Local origin required")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("Local origin required")
            if write and (not origin or len(self.headers.get_all("Origin", [])) != 1
                          or len(self.headers.get_all("X-OOPC-CSRF", [])) != 1
                          or not secrets.compare_digest(self.headers.get("X-OOPC-CSRF", ""), csrf_token)):
                raise PermissionError("Explicit same-origin request required")

        def do_POST(self):
            from .ask import NeedsClarification, QuestionUnavailable
            parsed = urlparse(self.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                return self.send({"error": "Local target required"}, status=400)
            path = unquote(parsed.path)
            parts = path.split("/")
            retry = len(parts) == 5 and parts[1:3] == ["api", "tasks"] and parts[4] == "retry"
            if path not in MUTATIONS and not retry:
                return self.send({"error": "Unsupported mutation"}, status=501)
            try:
                self.local_origin(write=True)
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get_all("Transfer-Encoding", []):
                    raise ValueError("A single bounded Content-Length is required")
                length = int(lengths[0])
                if not 1 <= length <= 40000:
                    return self.send({"error": "Request body exceeds its limit"}, status=413)
                if self.headers.get_content_type() != "application/json":
                    return self.send({"error": "JSON body required"}, status=415)
                self.connection.settimeout(5)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete request body")
                request = json.loads(body, object_pairs_hook=unique_object)
                with action_lock:
                    if path == "/api/runtimes/select":
                        if (not isinstance(request, dict) or set(request) != {"runtime", "authorizeRuntimeSelection"}
                                or request["authorizeRuntimeSelection"] is not True):
                            raise ValueError("Explicit engine selection is required")
                        engines.select_engine(root, request["runtime"])
                        return self.send(dict(engines.engines_status(root, claude_accounts, accounts), csrfToken=csrf_token))
                    if path in {"/api/runtimes/claude-code/login", "/api/runtimes/claude-code/cancel",
                                "/api/account/login", "/api/account/cancel"}:
                        field = "authorizeAccountConnection" if path.endswith("/login") else "cancelAccountConnection"
                        if not isinstance(request, dict) or set(request) != {field} or request[field] is not True:
                            raise ValueError("Explicit account connection authorization is required")
                        if path.startswith("/api/runtimes/"):
                            result = claude_accounts.start_login() if path.endswith("/login") else claude_accounts.cancel_login()
                        else:
                            result = connect_account() if path.endswith("/login") else accounts.cancel_login()
                        return self.send(dict(result, csrfToken=csrf_token), status=202)
                    if (path == "/api/tasks" and connection["requested"]
                            and accounts.status().get("status") == "login-pending"):
                        raise Busy("Finish or cancel the pending account connection before asking")
                    if path == "/api/tasks":
                        return self.send(questions.submit(request), status=202)
                    if retry:
                        if request != {"authorizeSubscription": True}:
                            raise ValueError("Explicit retry authorization is required")
                        return self.send(questions.retry(parts[3]), status=202)
                    if path == "/api/research":
                        if (not isinstance(request, dict) or set(request) - {"question", "fromQuestion"}
                                or "question" not in request):
                            raise ValueError("A research question is required")
                        return self.send(loop.add_research(root, request["question"],
                                                           from_question=request.get("fromQuestion")), status=201)
                    if path == "/api/settings":
                        return self.send(dict(loop.update_settings(root, request), csrfToken=csrf_token))
                    if path == "/api/loop/tick":
                        if request != {"authorizeSubscription": True}:
                            raise ValueError("Explicit authorization is required to run the loop")
                        return self.send(run_loop(), status=202)
            except PermissionError as error:
                self.send({"error": str(error)}, status=403)
            except NeedsClarification as error:
                self.send({"error": str(error), "clarify": error.choices}, status=409)
            except (Busy, QuestionUnavailable, BlockingIOError) as error:
                self.send({"error": str(error)}, status=409)
            except FileNotFoundError:
                self.send({"error": "Question not found"}, status=404)
            except (ValueError, TypeError, KeyError, UnicodeError, TimeoutError) as error:
                self.send({"error": "Invalid request" if isinstance(error, (KeyError, UnicodeError)) else str(error)}, status=400)
            except Exception:
                self.send({"error": "The request could not be completed"}, status=409)

        def do_GET(self):
            try:
                self.local_origin()
                parsed = urlparse(self.path)
                if parsed.scheme or parsed.netloc:
                    return self.send({"error": "Local request target required"}, status=400)
                path = unquote(parsed.path)
                q = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                if path == "/api/account/status":
                    return self.send(dict(accounts.status(), csrfToken=csrf_token))
                if path == "/api/runtimes/quota":
                    return self.send(quota_hint())
                if path == "/api/runtimes":
                    return self.send(dict(engines.engines_status(root, claude_accounts, accounts), csrfToken=csrf_token))
                if path == "/api/tasks/status":
                    return self.send(dict(questions.status(), csrfToken=csrf_token))
                if path == "/api/tasks":
                    return self.send(questions.list())
                if path.startswith("/api/tasks/"):
                    return self.send(questions.get(path.split("/")[3]))
                if path == "/api/knowledge":
                    # "Needs checking" groups findings awaiting review with ones the reviewer could not confirm.
                    status = ([knowledge.UNREVIEWED, knowledge.UNCERTAIN] if q.get("status") == "needs-checking" else
                              q.get("status") if q.get("status") in knowledge.STATUSES else None)
                    return self.send({"summary": knowledge.summary(root),
                                      "findings": knowledge.recent(root, status, min(int(q.get("limit", 50)), 200))})
                if path == "/api/settings":
                    return self.send(dict(loop.settings(root), csrfToken=csrf_token))
                if path == "/api/improvement":
                    from . import improve
                    return self.send({"summary": improve.summary(root)})
                if path == "/api/parity":
                    from . import parity
                    return self.send({"report": parity.report(root)})
                if path == "/api/loop":
                    return self.send(dict(loop_status(), csrfToken=csrf_token))
                filters = {key: q[key] for key in ("type", "status", "layer", "predicate", "property", "process",
                                                   "application", "environment", "source", "facet") if q.get(key)}
                selected = graph
                if q.get("release"):
                    selected_path = local_release(q["release"])
                    if str(selected_path) not in release_readers:
                        release_readers[str(selected_path)] = Graph(selected_path)
                    selected = release_readers[str(selected_path)]
                if path == "/api/meta":
                    data = selected.metadata() if selected else {"release_id": None, "counts": {}, "record_count": 0}
                    data["replayOnly"] = selected is None
                    data["releases"] = []
                    for manifest in sorted((root / "releases").glob("*/manifest.json")):
                        value = read_json(manifest)
                        data["releases"].append({"release_id": value["release_id"], "counts": value.get("counts", {})})
                    data["trace_version"] = "oopc-trace-v1"
                    return self.send(data)
                if selected is None and path in ("/api/search", "/api/record", "/api/claims", "/api/evidence", "/api/graph"):
                    return self.send({"error": "This workspace contains replay bundles only; select a graph release for live graph browsing", "replayOnly": True}, status=409)
                if path == "/api/search":
                    return self.send(selected.search(q.get("q", ""), limit=q.get("limit", 50), offset=q.get("offset", 0), **filters))
                if path == "/api/record":
                    try:
                        return self.send(selected.get(q["id"]))
                    except KeyError:
                        found = knowledge.get(root, q["id"])  # Findings and source notes, labelled with their status.
                        if found is None:
                            raise
                        return self.send(found)
                if path == "/api/claims":
                    predicate = filters.pop("predicate", None)
                    value = selected.claims(subject=q.get("subject"), predicate=predicate, object=q.get("object"),
                                            limit=q.get("limit", 100), offset=q.get("offset", 0), **filters)
                    if q.get("subject") and not q.get("offset"):
                        found = knowledge.about(root, q["subject"])
                        if found:
                            value = dict(value, findings=found)
                    return self.send(value)
                if path == "/api/evidence":
                    return self.send(selected.evidence(q["id"]))
                if path == "/api/graph":
                    return self.send(selected.neighborhood(q["id"], depth=q.get("depth", 1), limit=q.get("limit", 150),
                                                           direction=q.get("direction", "both"), offset=q.get("offset"), **filters))
                if path == "/api/diff":
                    return self.send(release_diff(local_release(q["from"]), local_release(q["to"])))
                if path == "/api/runs":
                    runs = traces.list()
                    for meta in runs:
                        meta["inspectorSummary"] = read_run_summary(traces.run(meta["run_id"]), meta)
                    return self.send({"runs": runs})
                if path.startswith("/api/runs/"):
                    parts = path.split("/")
                    run = traces.run(parts[3])
                    action = parts[4] if len(parts) > 4 else ""
                    if action == "events":
                        return self.send(run.events(q.get("after", 0)))
                    if action == "payload":
                        return self.send(run.payload(q["hash"]))
                    if action == "graph":
                        return self.send(run.graph(q.get("sequence"), q.get("cumulative", "true") != "false", q.get("agent")))
                    if action == "artifacts":
                        return self.send(run.artifacts())
                    if action == "citation":
                        return self.send(run.citation(q["id"], event_id=q.get("event"), sequence=q.get("sequence"), agent_id=q.get("agent")))
                    if action == "ontology":
                        return self.send(read_json(run.path / "ontology.json"))
                    if action == "record":
                        visible = run.graph(q.get("sequence"), agent_id=q.get("agent"))
                        record = next((r for r in visible["nodes"] + visible["edges"] if r["@id"] == q["id"]), None)
                        if record is None:
                            raise KeyError("Record was not observed at this point in the task")
                        return self.send(record)
                    if action == "export":
                        with tempfile.TemporaryDirectory() as directory:
                            output = Path(directory) / "replay.zip"
                            run.export(output)
                            return self.send(output.read_bytes(), "application/zip",
                                             headers={"Content-Disposition": 'attachment; filename="' + parts[3] + '.zip"'})
                    if not action:
                        meta = run.meta()
                        meta.pop("release_path", None)
                        meta["inspectorSummary"] = read_run_summary(run, meta)
                        return self.send(meta)
                    raise KeyError("Unknown run operation")
                if path.startswith("/api/"):
                    raise KeyError("Unknown endpoint")
                relative = path.lstrip("/") or "index.html"
                asset = (assets / relative).resolve()
                if not asset.is_relative_to(assets.resolve()) or not asset.is_file():
                    return self.send({"error": "Not found"}, status=404)
                data = asset.read_bytes()
                etag = '"' + digest(data)[:32] + '"'
                kind = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
                if etag in {tag.strip() for tag in self.headers.get("If-None-Match", "").split(",")}:
                    return self.send(b"", kind, status=304, headers={"ETag": etag})
                return self.send(data, kind, headers={"ETag": etag})
            except PermissionError as error:
                self.send({"error": str(error)}, status=403)
            except (KeyError, FileNotFoundError) as error:
                self.send({"error": str(error)}, status=404)
            except (ValueError, TypeError) as error:
                self.send({"error": str(error)}, status=400)
            except Exception:
                self.send({"error": "Operation failed"}, status=500)

    class AppServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET
        daemon_threads = True
        _account_closed = False

        def server_close(self):
            try:
                with action_lock:
                    if not self._account_closed:
                        self._account_closed = True
                        try:
                            accounts.close()
                        finally:
                            claude_accounts.cancel_login()
            finally:
                super().server_close()

    return AppServer((host, int(port)), Handler)
