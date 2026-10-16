"""Local ChatGPT sign-in through the official Codex app-server protocol.

Only the app-server owns credentials. This service retains sanitized display
state in memory; it does not log, read credential files, or start model work.
https://developers.openai.com/codex/app-server
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import selectors
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit

from .engines import resolve_codex_binary

AUTH_HOSTS = frozenset({"auth.openai.com", "auth0.openai.com", "chatgpt.com"})
MAX_LINE_BYTES = 65_536
MAX_TRANSPORT_BYTES = 4 * 1024 * 1024


class _ProtocolError(RuntimeError):
    """Transport failures are intentionally never displayed verbatim."""


def _login_url(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 8192
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or "\\" in value):
        raise _ProtocolError("Invalid login URL")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname in AUTH_HOSTS
                 and parsed.username is None and parsed.password is None
                 and parsed.port in (None, 443) and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise _ProtocolError("Invalid login URL")
    return value


def _account_state(response):
    if not isinstance(response, dict) or type(response.get("requiresOpenaiAuth")) is not bool:
        raise _ProtocolError("Invalid account response")
    account = response.get("account")
    if not response["requiresOpenaiAuth"]:
        return {"status": "unsupported", "account": None,
                "message": "This connection uses another provider. Configure ChatGPT in the official app first."}
    if account is None:
        return {"status": "disconnected", "account": None, "message": "Connect your ChatGPT account."}
    if not isinstance(account, dict) or not isinstance(account.get("type"), str):
        raise _ProtocolError("Invalid account response")
    if account["type"] != "chatgpt":
        return {"status": "unsupported", "account": None,
                "message": "This connection uses another sign-in method. It will not be replaced here."}
    email, plan = account.get("email"), account.get("planType")
    if (email is not None and (not isinstance(email, str) or len(email) > 320
            or any(ord(char) < 32 or ord(char) == 127 for char in email))):
        raise _ProtocolError("Invalid account display fields")
    if not isinstance(plan, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", plan):
        raise _ProtocolError("Invalid account display fields")
    return {"status": "connected", "account": {"email": email, "planType": plan},
            "message": "Connected through ChatGPT."}


class _StdioTransport:
    """One bounded JSON-lines subprocess. No stderr or raw messages retained."""
    def __init__(self, binary, *, popen=subprocess.Popen):
        self._process = None
        self._selector = selectors.DefaultSelector()
        self._buffer = b""
        self._received = 0
        self._request_id = 0
        self._close_lock = threading.Lock()
        self._closed = False
        try:
            self._process = popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                start_new_session=True)
            os.set_blocking(self._process.stdin.fileno(), False)
            os.set_blocking(self._process.stdout.fileno(), False)
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
        except BaseException:
            self.close()
            raise

    def _send(self, message, timeout):
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > MAX_LINE_BYTES:
            raise _ProtocolError("Oversized account request")
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as writable:
            writable.register(self._process.stdin, selectors.EVENT_WRITE)
            while payload:
                remaining = deadline - time.monotonic()
                if self._closed or remaining <= 0 or not writable.select(remaining):
                    raise TimeoutError("Account request timed out")
                written = os.write(self._process.stdin.fileno(), payload)
                if written <= 0:
                    raise _ProtocolError("Account transport closed")
                payload = payload[written:]

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                if len(line) > MAX_LINE_BYTES:
                    raise _ProtocolError("Oversized account response")
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError, RecursionError) as error:
                    raise _ProtocolError("Invalid account response") from error
                if not isinstance(event, dict):
                    raise _ProtocolError("Invalid account response")
                return event
            if len(self._buffer) > MAX_LINE_BYTES:
                raise _ProtocolError("Oversized account response")
            remaining = deadline - time.monotonic()
            if self._closed:
                raise _ProtocolError("Account transport closed")
            if remaining <= 0 or not self._selector.select(remaining):
                return None
            block = os.read(self._process.stdout.fileno(), 16_384)
            if not block:
                raise _ProtocolError("Account transport closed")
            self._received += len(block)
            if self._received > MAX_TRANSPORT_BYTES:
                raise _ProtocolError("Account transport limit exceeded")
            self._buffer += block

    def request(self, method, params, *, timeout, on_notification):
        self._request_id += 1
        identifier = self._request_id
        deadline = time.monotonic() + timeout
        self._send({"id": identifier, "method": method, "params": params}, timeout)
        while time.monotonic() < deadline:
            event = self.receive(max(0, deadline - time.monotonic()))
            if event is None:
                break
            if type(event.get("id")) is int and event["id"] == identifier and "method" not in event:
                if "error" in event or "result" not in event:
                    raise _ProtocolError("Account request failed")
                return event["result"]
            if "method" in event and "id" not in event:
                on_notification(event)
            elif "method" in event and "id" in event:
                # External credential refresh and other server requests have no
                # implementation here; never provide secrets or grant actions.
                raise _ProtocolError("Unsupported account server request")
        raise TimeoutError("Account request timed out")

    def initialized(self, timeout):
        self._send({"method": "initialized"}, timeout)

    def close(self):
        with self._close_lock:
            if self._closed and (self._process is None or self._process.poll() is not None):
                return True
            self._closed = True
            process = self._process
            if process is not None:
                try:
                    if process.poll() is None:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGTERM)
                        else:
                            process.terminate()
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                            process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            self._selector.close()
            self._buffer = b""
            return process is None or process.poll() is not None


class OpenAIAccount:
    """Nonblocking UI facade; one background operation and subprocess at a time.

    ``transport_factory(binary)`` is an offline test seam. Its transport exposes
    request, initialized, receive, and close as on _StdioTransport. No public
    method accepts an account, token, URL, login ID, or arbitrary RPC method.
    """
    def __init__(self, *, binary=None, transport_factory=None, refresh_seconds=30,
                 rpc_timeout=10, login_timeout=600):
        for value, maximum in ((refresh_seconds, 300), (rpc_timeout, 30), (login_timeout, 900)):
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError("Account service timing must be finite and bounded")
        self._binary = binary
        self._factory = transport_factory or _StdioTransport
        self._refresh_seconds = refresh_seconds
        self._rpc_timeout = rpc_timeout
        self._login_timeout = login_timeout
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._transport = None
        self._closed = False
        self._refresh_at = 0
        self._state = {"status": "checking", "account": None, "message": "Checking your ChatGPT connection."}

    def _snapshot(self):
        return copy.deepcopy(self._state)

    def _begin(self, operation):
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, args=(operation,),
            name="oopc-account", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None
            self._refresh_at = time.monotonic() + self._refresh_seconds
            self._state = {"status": "error", "account": None,
                "message": "The ChatGPT connection could not be checked. Please try again shortly."}

    def status(self):
        with self._lock:
            if (not self._closed and self._thread is None and self._transport is None
                    and time.monotonic() >= self._refresh_at):
                self._begin("read")
            return self._snapshot()

    def start_login(self):
        with self._lock:
            if self._closed:
                raise ValueError("The account service is closed.")
            if self._state["status"] in {"connected", "unsupported"}:
                raise ValueError("The saved connection cannot be replaced here.")
            if self._state["status"] == "login-pending":
                return self._snapshot()
            if self._thread is not None or self._transport is not None:
                raise ValueError("The connection is being checked. Please try again shortly.")
            self._state = {"status": "login-pending", "account": None, "message": "Preparing secure ChatGPT sign-in."}
            self._begin("login")
            return self._snapshot()

    def cancel_login(self):
        with self._lock:
            if self._closed or self._state["status"] in {"connected", "unsupported"}:
                raise ValueError("There is no pending sign-in to cancel.")
            if self._state["status"] == "login-pending":
                self._cancel.set()
                self._state = {"status": "login-pending", "account": None, "message": "Canceling sign-in."}
            return self._snapshot()

    def _publish(self, state):
        with self._lock:
            if not self._closed:
                if state["status"] == "login-pending" and self._cancel.is_set():
                    return
                self._state = state

    def _run(self, operation):
        transport = None
        terminal = None
        notifications = []
        def notification(event):
            if event.get("method") in {"account/login/completed", "account/updated"}:
                if len(notifications) >= 32:
                    raise _ProtocolError("Excess account notifications")
                notifications.append(event)
        def request(method, params):
            return transport.request(method, params, timeout=self._rpc_timeout, on_notification=notification)
        def read():
            return _account_state(request("account/read", {"refreshToken": False}))
        try:
            transport = self._factory(self._binary or resolve_codex_binary())
            with self._lock:
                self._transport = transport
                if self._closed:
                    return
            request("initialize", {"clientInfo": {"name": "oopc-account", "version": "1.0.0"}})
            transport.initialized(self._rpc_timeout)
            current = read()
            if operation == "read" or current["status"] != "disconnected" or self._cancel.is_set():
                terminal = current
                return
            result = request("account/login/start", {"type": "chatgpt",
                "useHostedLoginSuccessPage": True, "appBrand": "chatgpt"})
            if (not isinstance(result, dict) or result.get("type") != "chatgpt"
                    or not isinstance(result.get("loginId"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result["loginId"])):
                raise _ProtocolError("Invalid login response")
            login_id, login_url = result["loginId"], _login_url(result.get("authUrl"))
            deadline = time.monotonic() + self._login_timeout
            if not self._cancel.is_set():
                self._publish({"status": "login-pending", "account": None,
                    "loginUrl": login_url, "message": "Continue sign-in in the secure ChatGPT window."})
            while True:
                with self._lock:
                    if self._closed:
                        return
                if self._cancel.is_set() or time.monotonic() >= deadline:
                    result = request("account/login/cancel", {"loginId": login_id})
                    if not isinstance(result, dict) or result.get("status") not in {"canceled", "notFound"}:
                        raise _ProtocolError("Invalid cancel response")
                    terminal = read()
                    return
                while notifications:
                    event = notifications.pop(0)
                    params = event.get("params")
                    if not isinstance(params, dict):
                        raise _ProtocolError("Invalid account notification")
                    if event["method"] == "account/login/completed" and params.get("loginId") == login_id:
                        current = read()
                        if current["status"] == "disconnected":
                            current = {"status": "error", "account": None,
                                "message": "Sign-in did not complete. Please try again."}
                        terminal = current
                        return
                    if event["method"] == "account/updated":
                        current = read()
                        if current["status"] != "disconnected":
                            terminal = current
                            return
                event = transport.receive(min(0.1, max(0, deadline - time.monotonic())))
                if event is not None:
                    if "id" in event and "method" in event:
                        raise _ProtocolError("Unsupported account server request")
                    notification(event)
        except Exception:
            terminal = {"status": "error", "account": None,
                "message": "The ChatGPT connection could not be checked. Please try again shortly."}
        finally:
            cleaned = transport is None
            try:
                if transport is not None:
                    cleaned = transport.close() is not False
            except Exception:
                cleaned = False
            finally:
                with self._lock:
                    self._transport = None if cleaned else transport
                    self._thread = None
                    self._refresh_at = time.monotonic() + self._refresh_seconds
                    if not self._closed:
                        if not cleaned and operation == "login":
                            self._state = {"status": "login-pending", "account": None,
                                "message": "Sign-in is still stopping. Keep research paused until it closes."}
                        elif terminal is not None:
                            self._state = terminal

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
            self._state = {"status": "error", "account": None, "message": "The account service is closed."}
            transport, thread = self._transport, self._thread
        if transport is not None:
            transport.close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.5)
