"""Offline account facade and real stdio framing; never run Codex or log in."""
import copy
import json
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from oopc.openai_account import OpenAIAccount, _StdioTransport, _ProtocolError, _login_url

DISCONNECTED = {"account": None, "requiresOpenaiAuth": True}
CONNECTED = {"account": {"type": "chatgpt", "email": "reader@example.org", "planType": "plus",
                         "token": "never-return-this"}, "requiresOpenaiAuth": True,
             "credential": "never-return-this-either"}


class FakeTransport:
    def __init__(self, reads=None, *, read_gate=None, url="https://auth.openai.com/authorize?state=opaque"):
        self.reads = list(reads or [DISCONNECTED])
        self.read_gate = read_gate
        self.url = url
        self.calls = []
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.read_started = threading.Event()
        self.login_started = threading.Event()

    def request(self, method, params, *, timeout, on_notification):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "initialize":
            return {"userAgent": "fixture"}
        if method == "account/read":
            self.read_started.set()
            if self.read_gate is not None and not self.read_gate.wait(timeout):
                raise TimeoutError("secret unsafe diagnostics")
            value = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        if method == "account/login/start":
            self.login_started.set()
            return {"type": "chatgpt", "loginId": "fixture-login", "authUrl": self.url}
        if method == "account/login/cancel":
            return {"status": "canceled"}
        raise AssertionError(method)

    def initialized(self, timeout):
        self.calls.append(("initialized", None))

    def receive(self, timeout):
        if self.closed.is_set():
            raise RuntimeError("closed")
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self.closed.set()
        if self.read_gate is not None:
            self.read_gate.set()


class AccountTests(unittest.TestCase):
    def service(self, transports, **kwargs):
        pending = list(transports)
        self.launched = []
        def factory(binary):
            self.launched.append(binary)
            return pending.pop(0)
        service = OpenAIAccount(binary="offline-codex", transport_factory=factory,
            refresh_seconds=kwargs.pop("refresh_seconds", 30), **kwargs)
        self.addCleanup(service.close)
        return service

    def wait(self, service, status, *, url=False):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = service.status()
            if state["status"] == status and (not url or "loginUrl" in state):
                return state
            time.sleep(0.002)
        self.fail(service.status())

    def settled(self, service):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with service._lock:
                if service._thread is None:
                    return
            time.sleep(0.002)
        self.fail("Account worker did not settle")

    def test_status_is_fast_single_background_read_and_returns_only_display_fields(self):
        gate = threading.Event()
        transport = FakeTransport([CONNECTED], read_gate=gate)
        service = self.service([transport])
        self.assertEqual(self.launched, [])
        started = time.monotonic()
        self.assertEqual(service.status()["status"], "checking")
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertTrue(transport.read_started.wait(1))
        for _ in range(20):
            self.assertEqual(service.status()["status"], "checking")
        self.assertEqual(len(self.launched), 1)
        gate.set()
        state = self.wait(service, "connected")
        self.settled(service)
        self.assertEqual(state["account"], {"email": "reader@example.org", "planType": "plus"})
        self.assertNotIn("never-return", json.dumps(state))
        state["account"]["email"] = "caller-mutation"
        self.assertEqual(service.status()["account"]["email"], "reader@example.org")
        self.assertEqual(transport.calls[:3], [("initialize", {"clientInfo": {"name": "oopc-account", "version": "1.0.0"}}),
            ("initialized", None), ("account/read", {"refreshToken": False})])
        self.assertTrue(transport.closed.is_set())
        with self.assertRaises(ValueError):
            service.start_login()
        with self.assertRaises(ValueError):
            service.cancel_login()

    def test_login_completion_refreshes_and_exposes_no_login_id_or_tokens(self):
        transport = FakeTransport([DISCONNECTED, CONNECTED])
        service = self.service([transport])
        self.assertEqual(service.start_login()["status"], "login-pending")
        self.wait(service, "login-pending", url=True)
        for _ in range(5):
            self.assertEqual(service.start_login()["status"], "login-pending")
        transport.events.put({"method": "account/login/completed", "params": {
            "loginId": "fixture-login", "success": True, "error": None}})
        state = self.wait(service, "connected")
        self.settled(service)
        self.assertNotIn("loginUrl", state)
        self.assertNotIn("loginId", state)
        login_calls = [row for row in transport.calls if row[0] == "account/login/start"]
        self.assertEqual(login_calls, [("account/login/start", {"type": "chatgpt",
            "useHostedLoginSuccessPage": True, "appBrand": "chatgpt"})])
        self.assertEqual(sum(method == "account/read" for method, _ in transport.calls), 2)

    def test_fresh_read_prevents_replacing_newly_connected_or_unsupported_account(self):
        for account in (CONNECTED, {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True},
                        {"account": None, "requiresOpenaiAuth": False}):
            with self.subTest(account=account):
                initial, mutation = FakeTransport(), FakeTransport([account])
                service = self.service([initial, mutation])
                self.wait(service, "disconnected")
                self.settled(service)
                service.start_login()
                final = "connected" if account == CONNECTED else "unsupported"
                self.wait(service, final)
                self.settled(service)
                self.assertFalse(mutation.login_started.is_set())
                with self.assertRaises(ValueError):
                    service.start_login()
                with self.assertRaises(ValueError):
                    service.cancel_login()

    def test_cancel_before_initial_read_never_starts_oauth(self):
        gate = threading.Event()
        transport = FakeTransport(read_gate=gate)
        service = self.service([transport])
        service.start_login()
        self.assertTrue(transport.read_started.wait(1))
        self.assertEqual(service.cancel_login()["status"], "login-pending")
        gate.set()
        self.wait(service, "disconnected")
        self.settled(service)
        self.assertFalse(transport.login_started.is_set())

    def test_cancel_pending_uses_only_its_owned_login_and_drops_url_immediately(self):
        transport = FakeTransport()
        service = self.service([transport])
        service.start_login()
        self.wait(service, "login-pending", url=True)
        self.assertNotIn("loginUrl", service.cancel_login())
        self.wait(service, "disconnected")
        self.settled(service)
        self.assertIn(("account/login/cancel", {"loginId": "fixture-login"}), transport.calls)
        self.assertTrue(transport.closed.is_set())

    def test_expiry_cancels_and_cleans_up_without_browser_polling(self):
        transport = FakeTransport()
        service = self.service([transport], login_timeout=0.03)
        service.start_login()
        self.assertTrue(transport.login_started.wait(1))
        self.assertTrue(transport.closed.wait(1))
        self.assertIn(("account/login/cancel", {"loginId": "fixture-login"}), transport.calls)
        self.assertNotIn("loginUrl", service.status())

    def test_unrelated_completion_is_ignored_and_failed_completion_is_sanitized(self):
        transport = FakeTransport()
        service = self.service([transport])
        service.start_login()
        self.wait(service, "login-pending", url=True)
        transport.events.put({"method": "account/login/completed", "params": {
            "loginId": "some-other-login", "success": True}})
        transport.events.put({"method": "account/login/completed", "params": {
            "loginId": "fixture-login", "success": False, "error": "secret-token-path"}})
        result = self.wait(service, "error")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(sum(method == "account/read" for method, _ in transport.calls), 2)

    def test_account_update_refreshes_after_login_and_does_not_trust_notification_fields(self):
        transport = FakeTransport([DISCONNECTED, CONNECTED])
        service = self.service([transport])
        service.start_login()
        self.wait(service, "login-pending", url=True)
        transport.events.put({"method": "account/updated", "params": {"authMode": "apiKey", "token": "secret"}})
        self.assertEqual(self.wait(service, "connected")["account"], {"email": "reader@example.org", "planType": "plus"})

    def test_errors_are_sanitized_and_retry_is_lazy_with_backoff(self):
        transport = FakeTransport([RuntimeError("credential /private/path secret")])
        service = self.service([transport, FakeTransport([CONNECTED])], refresh_seconds=0.03)
        result = self.wait(service, "error")
        self.settled(service)
        self.assertNotIn("credential", json.dumps(result))
        self.assertNotIn("/private", json.dumps(result))
        for _ in range(10):
            service.status()
        self.assertEqual(len(self.launched), 1)
        time.sleep(0.04)
        self.wait(service, "connected")
        self.assertEqual(len(self.launched), 2)

    def test_unsafe_login_url_is_never_exposed_and_process_is_closed(self):
        service = self.service([FakeTransport(url="https://auth.openai.com.evil.example/authorize")])
        service.start_login()
        result = self.wait(service, "error")
        self.assertNotIn("loginUrl", result)
        self.settled(service)

    def test_close_stops_owned_pending_process_and_cannot_restart(self):
        transport = FakeTransport()
        service = self.service([transport])
        service.start_login()
        self.wait(service, "login-pending", url=True)
        service.close()
        self.assertTrue(transport.closed.is_set())
        self.assertIsNone(service._thread)
        self.assertNotIn("loginUrl", service.status())
        self.assertEqual(len(self.launched), 1)
        with self.assertRaises(ValueError):
            service.start_login()

    def test_login_error_remains_pending_until_transport_cleanup_finishes(self):
        cleanup_started, release_cleanup = threading.Event(), threading.Event()
        transport = FakeTransport(url="https://untrusted.example/login")
        ordinary_close = transport.close
        def held_close():
            cleanup_started.set()
            release_cleanup.wait(1)
            ordinary_close()
        transport.close = held_close
        service = self.service([transport])
        service.start_login()
        self.assertTrue(cleanup_started.wait(1))
        self.assertEqual(service.status()["status"], "login-pending")
        self.assertNotIn("loginUrl", service.status())
        release_cleanup.set()
        self.wait(service, "error")

    def test_cancel_at_url_publication_cannot_restore_canceled_link(self):
        transport = FakeTransport()
        service = self.service([transport])
        ordinary_publish = service._publish
        canceled = threading.Event()
        def cancel_first(state):
            service.cancel_login()
            ordinary_publish(state)
            self.assertNotIn("loginUrl", service.status())
            canceled.set()
        with patch.object(service, "_publish", side_effect=cancel_first):
            service.start_login()
            self.assertTrue(canceled.wait(1))
            self.wait(service, "disconnected")

    def test_unconfirmed_login_cleanup_keeps_task_blocking_pending_state(self):
        transport = FakeTransport(url="https://untrusted.example/login")
        ordinary_close = transport.close
        transport.close = lambda: False
        service = self.service([transport])
        service.start_login()
        self.settled(service)
        self.assertEqual(service.status()["status"], "login-pending")
        self.assertNotIn("loginUrl", service.status())
        self.assertEqual(len(self.launched), 1)
        transport.close = ordinary_close

    def test_timing_bounds_and_url_allowlist(self):
        for value in (0, -1, float("nan"), float("inf"), True, 901):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OpenAIAccount(login_timeout=value)
        for url in ("http://auth.openai.com/a", "https://auth.openai.com:444/a", "https://evil@auth.openai.com/a",
                    "https://auth.openai.com.evil/a", "https://auth.openai.com./a", "https://auth.openai.com/a#token",
                    "https://auth.openai.com/\na", "https://auth.openai.com\\@evil/a", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(_ProtocolError):
                _login_url(url)
        for host in ("auth.openai.com", "auth0.openai.com", "chatgpt.com"):
            self.assertEqual(_login_url("https://" + host + ":443/authorize?state=test"),
                             "https://" + host + ":443/authorize?state=test")


class StdioTests(unittest.TestCase):
    def transport(self, program):
        processes = []
        def popen(command, **kwargs):
            self.assertEqual(command, ["never-execute-codex", "app-server", "--stdio"])
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
            process = subprocess.Popen([sys.executable, "-u", "-c", program], **kwargs)
            processes.append(process)
            return process
        transport = _StdioTransport("never-execute-codex", popen=popen)
        self.addCleanup(transport.close)
        return transport, processes[0]

    def test_real_stdio_handshake_notifications_and_cleanup(self):
        transport, process = self.transport("""
import sys,json
for line in sys.stdin:
    request=json.loads(line)
    if request['method']=='initialized': continue
    print(json.dumps({'method':'account/updated','params':{'authMode':None}}),flush=True)
    print(json.dumps({'id':request['id'],'result':{'account':None,'requiresOpenaiAuth':True}}),flush=True)
""")
        seen = []
        transport.request("initialize", {}, timeout=1, on_notification=seen.append)
        transport.initialized(1)
        self.assertEqual(transport.request("account/read", {"refreshToken": False}, timeout=1,
                         on_notification=seen.append), DISCONNECTED)
        self.assertEqual(len(seen), 2)
        transport.close()
        self.assertIsNotNone(process.poll())

    def test_timeout_closes_process_without_unbounded_wait(self):
        transport, process = self.transport("import time; time.sleep(30)")
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            transport.request("initialize", {}, timeout=0.03, on_notification=lambda event: None)
        transport.close()
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertIsNotNone(process.poll())

    def test_oversized_unterminated_line_and_invalid_json_fail_closed(self):
        for content in ("'x'*70000", "'not-json\\n'", "'[]\\n'"):
            with self.subTest(content=content):
                transport, process = self.transport("import sys,time; sys.stdout.write(" + content + ");sys.stdout.flush();time.sleep(30)")
                with self.assertRaises(_ProtocolError):
                    transport.request("initialize", {}, timeout=1, on_notification=lambda event: None)
                transport.close()
                self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()
