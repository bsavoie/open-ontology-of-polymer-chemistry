"""Explicit account and question HTTP actions with synthetic services and local state only."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from oopc.release import build_release
from oopc.server import make_server
from oopc.vocabulary import get_ontology
from fixtures.account_server import AccountFixture, TaskFixture


class AccountServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oopc-account-http-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.release = build_release(self.root / "releases/fixture", [{"@id": "wop-000001",
            "@type": "PolymerConcept", "label": "Synthetic fixture", "status": "seed", "layer": "science"}],
            get_ontology(), {})
        self.accounts, self.tasks = AccountFixture(), TaskFixture()
        try:
            self.server = make_server(self.root, self.release, port=0,
                task_service=self.tasks, account_service=self.accounts)
        except PermissionError:
            self.skipTest("Sandbox blocks loopback binding; rerun with local-server permission")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        code, status = self.request("GET", "/api/tasks/status")
        self.assertEqual(code, 200)
        self.headers = {"Origin": self.origin, "Content-Type": "application/json", "X-OOPC-CSRF": status["csrfToken"]}

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, path, value=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            body = raw if raw is not None else json.dumps(value) if method == "POST" else None
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if response.getheader("Content-Type") == "application/json" else data
        finally:
            connection.close()

    def login(self):
        return self.request("POST", "/api/account/login", {"authorizeAccountConnection": True}, headers=self.headers)

    def test_browsing_and_ordinary_questions_do_not_start_account_rpc(self):
        for path in ("/", "/api/meta", "/api/search?q=Synthetic", "/api/tasks/status", "/api/tasks", "/api/knowledge"):
            self.assertEqual(self.request("GET", path)[0], 200)
        self.assertEqual(self.request("POST", "/api/tasks", {}, headers=self.headers)[0], 202)
        self.assertEqual(self.accounts.status_calls, 0)
        self.assertEqual(self.accounts.start_calls, 0)

    def test_an_ambiguous_polymer_name_returns_the_choices_instead_of_queuing(self):
        from oopc.ask import NeedsClarification
        choices = [{"name": "PEI", "options": [{"id": "wop-000084", "label": "Polyetherimide"},
                                               {"id": "wop-000232", "label": "Polyethyleneimine"}]}]

        def ambiguous():
            raise NeedsClarification(choices)
        self.tasks.before_submit = ambiguous
        code, value = self.request("POST", "/api/tasks", {}, headers=self.headers)
        self.assertEqual((code, value["clarify"]), (409, choices))
        self.assertIn("PEI could mean Polyetherimide or Polyethyleneimine", value["error"])
        self.assertEqual(self.tasks.actions, [])

    def test_explicit_status_returns_account_and_same_csrf_without_login(self):
        self.accounts.value = {"status": "connected", "account": {"email": "synthetic@example.invalid", "planType": "test"}, "message": "Synthetic"}
        code, value = self.request("GET", "/api/account/status")
        self.assertEqual(code, 200)
        self.assertEqual(value["account"], self.accounts.value["account"])
        self.assertEqual(value["csrfToken"], self.headers["X-OOPC-CSRF"])
        self.assertEqual(self.accounts.start_calls, 0)

    def test_endpoints_reject_foreign_origin_host_and_csrf(self):
        for headers in ({"Origin": "https://attacker.invalid"}, {"Host": "attacker.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Host": "127.0.0.1:1"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/api/account/status", headers=headers)[0], 403)
        for path, body in (("/api/account/login", {"authorizeAccountConnection": True}), ("/api/tasks", {}),
                           ("/api/loop/tick", {"authorizeSubscription": True}), ("/api/research", {"question": "x" * 20})):
            for headers in ({}, dict(self.headers, Origin="https://attacker.invalid"),
                            dict(self.headers, **{"X-OOPC-CSRF": "wrong"})):
                with self.subTest(path=path, headers=headers):
                    self.assertEqual(self.request("POST", path, body, headers=headers)[0], 403)
        self.assertEqual(self.accounts.start_calls, 0)
        self.assertEqual(self.tasks.actions, [])

    def test_login_and_cancel_require_exact_boolean_authorization(self):
        for path, field in (("/api/account/login", "authorizeAccountConnection"),
                            ("/api/account/cancel", "cancelAccountConnection")):
            for value in ({}, {field: False}, {field: 1}, {field: "true"}, {field: True, "other": 1}, [True]):
                with self.subTest(path=path, value=value):
                    self.assertEqual(self.request("POST", path, value, headers=self.headers)[0], 400)
        self.assertEqual(self.accounts.start_calls, 0)
        self.assertEqual(self.accounts.cancel_calls, 0)

    def test_body_bounds_type_and_duplicate_fields(self):
        path = "/api/account/login"
        self.assertEqual(self.request("POST", path, "x" * 40000, headers=self.headers)[0], 413)
        self.assertEqual(self.request("POST", path, {}, headers=dict(self.headers, **{"Content-Type": "text/plain"}))[0], 415)
        self.assertEqual(self.request("POST", path, headers=self.headers,
            raw='{"authorizeAccountConnection":false,"authorizeAccountConnection":true}')[0], 400)
        self.assertEqual(self.accounts.start_calls, 0)

    def test_retry_and_loop_need_exact_authorization(self):
        retry = "/api/tasks/" + self.tasks.identifier + "/retry"
        for body in ({}, {"authorizeSubscription": False}, {"authorizeSubscription": True, "x": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", retry, body, headers=self.headers)[0], 400)
                self.assertEqual(self.request("POST", "/api/loop/tick", body, headers=self.headers)[0], 400)
        self.assertEqual(self.request("POST", retry, {"authorizeSubscription": True}, headers=self.headers)[0], 202)
        self.assertEqual(self.tasks.actions, ["retry"])
        self.assertEqual(self.request("POST", "/api/tasks/" + self.tasks.identifier + "/resume",
                                      {"authorizeSubscription": True}, headers=self.headers)[0], 501)

    def test_pending_login_blocks_asking_but_not_browsing(self):
        code, value = self.login()
        self.assertEqual(code, 202)
        self.assertEqual(value["status"], "login-pending")
        self.assertEqual(self.request("POST", "/api/tasks", {}, headers=self.headers)[0], 409)
        self.assertEqual(self.tasks.actions, [])
        self.assertEqual(self.request("GET", "/api/meta")[0], 200)

    def test_cancel_remains_blocked_until_service_reports_terminal_connection(self):
        self.login()
        code, value = self.request("POST", "/api/account/cancel", {"cancelAccountConnection": True}, headers=self.headers)
        self.assertEqual(code, 202)
        self.assertEqual(value["status"], "login-pending")
        self.assertEqual(self.request("POST", "/api/tasks", {}, headers=self.headers)[0], 409)
        self.accounts.value = {"status": "disconnected", "account": None, "message": "Cancelled"}
        self.assertEqual(self.request("POST", "/api/tasks", {}, headers=self.headers)[0], 202)
        self.assertEqual(self.accounts.cancel_calls, 1)

    def test_connected_unsupported_checking_or_error_cannot_start_login(self):
        for status in ("connected", "unsupported", "checking", "error"):
            with self.subTest(status=status):
                self.accounts.value["status"] = status
                self.assertEqual(self.login()[0], 409)
        self.assertEqual(self.accounts.start_calls, 0)

    def test_a_running_question_blocks_login(self):
        self.tasks.items = [{"taskId": "b" * 32, "status": "running"}]
        self.assertEqual(self.login()[0], 409)
        self.tasks.items = [{"taskId": "b" * 32, "status": "completed"}]
        self.assertEqual(self.login()[0], 202)

    def test_question_submission_cannot_race_login_transition(self):
        entered, release = threading.Event(), threading.Event()
        self.accounts.start_entered, self.accounts.start_release = entered, release
        results = {}
        login = threading.Thread(target=lambda: results.update(login=self.login()))
        login.start()
        self.assertTrue(entered.wait(3))
        task = threading.Thread(target=lambda: results.update(task=self.request("POST", "/api/tasks", {}, headers=self.headers)))
        task.start()
        try:
            self.assertEqual(self.tasks.actions, [])
        finally:
            release.set()
            login.join(4); task.join(4)
        self.assertEqual(results["login"][0], 202)
        self.assertEqual(results["task"][0], 409)
        self.assertEqual(self.tasks.actions, [])

    def test_login_cannot_race_question_submission(self):
        entered, release = threading.Event(), threading.Event()
        def submit():
            entered.set()
            if not release.wait(3):
                raise AssertionError("Synthetic task gate did not release")
            self.tasks.items = [{"taskId": self.tasks.identifier, "status": "running"}]
        self.tasks.before_submit = submit
        results = {}
        task = threading.Thread(target=lambda: results.update(task=self.request("POST", "/api/tasks", {}, headers=self.headers)))
        task.start()
        self.assertTrue(entered.wait(3))
        login = threading.Thread(target=lambda: results.update(login=self.login()))
        login.start()
        try:
            self.assertEqual(self.accounts.start_calls, 0)
        finally:
            release.set()
            task.join(4); login.join(4)
        self.assertEqual(results["task"][0], 202)
        self.assertEqual(results["login"][0], 409)
        self.assertEqual(self.accounts.start_calls, 0)

    def test_research_queue_accepts_a_question_and_rejects_extra_fields(self):
        code, item = self.request("POST", "/api/research", {"question": "Compare PLA crystallinity after annealing"},
                                  headers=self.headers)
        self.assertEqual(code, 201)
        self.assertEqual(item["status"], "waiting")
        self.assertEqual(self.request("POST", "/api/research", {"question": "short"}, headers=self.headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/research", {"question": "x" * 20, "run": True}, headers=self.headers)[0], 400)
        code, loop = self.request("GET", "/api/loop")
        self.assertEqual(code, 200)
        self.assertEqual([q["question"] for q in loop["research"]["queue"]], ["Compare PLA crystallinity after annealing"])

    def test_settings_default_to_researcher_judgement_and_validate_changes(self):
        code, value = self.request("GET", "/api/settings")
        self.assertEqual((code, value["reviewMode"], value["researchPerWeek"]), (200, "researcher", 0))
        code, value = self.request("POST", "/api/settings", {"reviewMode": "all"}, headers=self.headers)
        self.assertEqual((code, value["reviewMode"]), (200, "all"))
        for body in ({"reviewMode": "never"}, {"autoQueue": True}, {"researchPerWeek": -1}, {"other": 1}, {}):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/settings", body, headers=self.headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/settings", {"researchPerWeek": 5}, headers={})[0], 403)
        self.assertEqual(self.request("GET", "/api/loop")[1]["settings"],
                         {"reviewMode": "all", "spotCheckRate": 0.2, "researchPerWeek": 0})

    def test_the_prompt_cannot_be_changed_through_the_app(self):
        for path in ("/api/improvement/adopt", "/api/improvement/revert"):
            with self.subTest(path=path):
                self.assertGreaterEqual(self.request("POST", path, {"authorizePromptChange": True}, headers=self.headers)[0], 400)
        code, value = self.request("GET", "/api/improvement")
        self.assertEqual((code, value["summary"]["answered"]), (200, 0))
        code, value = self.request("GET", "/api/knowledge?status=needs-checking")
        self.assertEqual((code, value["findings"]), (200, []))

    def test_server_close_closes_account_service(self):
        self.server.server_close()
        self.assertEqual(self.accounts.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
