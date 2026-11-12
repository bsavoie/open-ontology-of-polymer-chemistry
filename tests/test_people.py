"""Several people on one host (owner, 2026-11-05): private questions, shared findings, each person's own engine
accounts, who did what, and an app that asks each person to sign in."""
import http.client
import json
import threading
import time
import unittest

import test_core_loop as core
from fixtures.account_server import AccountFixture
from oopc import calls, consistency, engines, knowledge, loop, people, reflect
from oopc.ask import Questions
from oopc.server import make_server
from oopc.util import atomic_json


class People(unittest.TestCase):
    setUp = core.CoreLoopTests.setUp

    def two(self):
        return people.add(self.root, "Ada", "first-password"), people.add(self.root, "Grace", "second-password")

    def question(self, identifier, asked_by=None, status="completed"):
        item = {"id": identifier, "question": "What crystallinity does annealed PLA reach (%s)?" % identifier[:4],
                "origin": "ask", "engine": "codex", "budgetSeconds": 300, "depth": "quick", "status": status,
                "submittedAt": "2026-11-05T10:00:00+00:00", "attempts": []}
        if asked_by:
            item["askedBy"] = asked_by
        atomic_json(knowledge.folder(self.root) / "questions" / identifier / "question.json", item)
        return item

    def test_the_first_person_added_is_the_owner_and_passwords_are_never_stored(self):
        self.assertFalse(people.active(self.root))
        ada, grace = self.two()
        self.assertEqual((ada["owner"], grace["owner"]), (True, False))
        self.assertTrue(people.active(self.root))
        self.assertEqual(people.verify(self.root, "grace", "second-password"), grace)  # Names ignore case.
        self.assertIsNone(people.verify(self.root, "Grace", "first-password"))
        self.assertIsNone(people.verify(self.root, "Nobody", "first-password"))
        stored = (knowledge.folder(self.root) / "people.json").read_text()
        self.assertNotIn("second-password", stored)
        for bad in (("Grace", "another-password"), ("Linus", "short"), ("", "a-long-password")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                people.add(self.root, *bad)
        with self.assertRaises(ValueError):
            people.remove(self.root, "Ada")
        people.set_password(self.root, "Grace", "a-new-password")
        self.assertEqual(people.verify(self.root, "Grace", "a-new-password"), grace)

    def test_questions_are_private_and_older_ones_are_the_owners(self):
        ada, grace = self.two()
        self.question("a" * 32, ada["id"])
        self.question("b" * 32, grace["id"])
        self.question("c" * 32)  # Asked before people were added: the owner's.
        service = Questions(self.root, runner=core.ScriptedEngine())
        self.assertEqual({t["taskId"] for t in service.list(person=grace)["tasks"]}, {"b" * 32})
        self.assertEqual({t["taskId"] for t in service.list(person=ada)["tasks"]}, {"a" * 32, "c" * 32})
        self.assertEqual(len(service.list()["tasks"]), 3)  # Nobody signed in: a host nobody was added to.
        with self.assertRaises(FileNotFoundError):
            service.get("a" * 32, person=grace)
        with self.assertRaises(FileNotFoundError):  # Nor follow another person's conversation up.
            service.submit({"question": "And how fast does it crystallize?", "parentId": "a" * 32, "budgetSeconds": 300,
                            "authorizeSubscription": True, "runtime": "codex"}, person=grace)

    def test_a_persons_question_runs_on_their_own_engine_accounts_and_its_findings_record_them(self):
        _, grace = self.two()
        homes = []

        def research(tools):
            homes.append(engines.current_home())
            return core.answer("Crystallinity reached 45%.", [], [core.FINDING])
        service = Questions(self.root, runner=core.ScriptedEngine(research))
        view = service.submit({"question": "How does annealing change PLA crystallinity?", "budgetSeconds": 300,
                               "authorizeSubscription": True, "runtime": "codex"}, person=grace)
        service.wait(10, reviews=True)
        done = service.get(view["id"], person=grace)
        home = knowledge.folder(self.root) / "people" / grace["id"]
        self.assertEqual(homes, [home])
        self.assertEqual(service._read(view["id"])["askedBy"], grace["id"])
        [finding] = done["findings"]
        self.assertEqual(finding["savedBy"], "Grace")
        with knowledge.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT person FROM deposits").fetchone()[0], grace["id"])
        with engines.as_person(grace, home):
            self.assertEqual(engines.codex_environment()["CODEX_HOME"], str(home / "codex"))
            self.assertEqual(engines.claude_environment()["CLAUDE_CONFIG_DIR"], str(home / "claude"))
            self.assertEqual(engines.engine_home("codex"), home / "codex")
            engines.select_engine(self.root, "claude-code")  # Their own choice of engine, not the host's.
            self.assertEqual(engines.preferred_engine(self.root), "claude-code")
        self.assertEqual(engines.preferred_engine(self.root), "codex")
        self.assertNotIn("CODEX_HOME", {k for k, v in engines.codex_environment().items() if v == str(home / "codex")})

    def test_two_peoples_sessions_do_not_wait_for_each_other(self):
        ada, grace = self.two()
        together = threading.Barrier(2, timeout=5)

        def session(*a, **k):
            together.wait()  # Both run at once, on one engine, with one slot each.
            return {"engine": "codex", "answer": {}}

        def as_(person):
            with engines.as_person(person, people.home(self.root, person)):
                calls.invoke(self.root, "research", person["id"], session, "codex", "", {})
        threads = [threading.Thread(target=as_, args=(p,)) for p in (ada, grace)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual({r.get("person") for r in calls.records(self.root)}, {ada["id"], grace["id"]})

    def test_a_person_set_to_use_the_hosts_sign_ins_shares_its_folder_and_its_slots(self):
        """People who share one account share the host's folder: copies of one sign-in end each other at their first
        token refresh (Codex: "your refresh token was already used")."""
        ada = people.add(self.root, "Ada", "first-password")
        grace = people.add(self.root, "Grace", "second-password", host_engines=True)
        self.assertEqual((ada["hostEngines"], grace["hostEngines"]), (True, True))  # The owner's always are.
        self.assertIsNone(people.home(self.root, grace))
        self.assertFalse((knowledge.folder(self.root) / "people").exists())
        with self.assertRaises(ValueError):
            people.set_engines(self.root, "Ada", False)
        held = []

        def research(tools):
            held.append((engines.current_home(), [name for name, _ in calls._BUSY]))
            return core.answer("Crystallinity reached 45%.", [], [core.FINDING])
        service = Questions(self.root, runner=core.ScriptedEngine(research))
        view = service.submit({"question": "How does annealing change PLA crystallinity?", "budgetSeconds": 300,
                               "authorizeSubscription": True, "runtime": "codex"}, person=grace)
        service.wait(10, reviews=True)
        self.assertEqual(held[0], (None, ["codex"]))  # The host's folder and the host's slot.
        self.assertEqual(service.get(view["id"], person=grace)["findings"][0]["savedBy"], "Grace")  # Still hers.
        own = people.set_engines(self.root, "Grace", False)  # Back to a folder of her own.
        self.assertFalse(own["hostEngines"])
        self.assertEqual(people.home(self.root, own), knowledge.folder(self.root) / "people" / grace["id"])
        self.assertEqual([p["hostEngines"] for p in people.everyone(self.root)], [True, False])

    def test_settlements_settings_and_reverts_record_who(self):
        ada, grace = self.two()
        q = "a" * 32
        knowledge.deposit(self.root, q, core.answer("", [], [core.FINDING]), engine="codex", review_mode="all")
        saved = knowledge.for_question(self.root, q)[0]["id"]
        other = dict(core.FINDING, value="62", statement="PLA film annealed at 100 °C for 1 h reached 62% crystallinity.",
                     sourceUrl="https://example.org/other", sourceDoi="10.1234/example.9")
        knowledge.deposit(self.root, "b" * 32, core.answer("", [], [other]), engine="codex", review_mode="all")
        new = knowledge.for_question(self.root, "b" * 32)[0]["id"]
        with knowledge.connect(self.root, write=True) as db:
            consistency.record(db, "b" * 32, [{"finding": new, "with": saved, "reading": "unresolved", "reason": "?"}],
                               {}, engine="codex", stamp="2026-11-05T10:00:00+00:00", resolution="person", compared=1)
        [conflict] = consistency.conflicts(self.root, "open")
        settled = consistency.settle(self.root, conflict["id"], "sources-disagree", person=grace)
        self.assertEqual(settled["settledByName"], "Grace")
        loop.update_settings(self.root, {"spotCheckRate": 0.5}, person=ada)
        self.assertEqual(loop.recent_log(self.root, 1)[0]["by"], "Ada")
        reflect.apply(self.root, {"id": "e-name", "type": "name", "fields": {"polymer": "wop-000001",
                                  "field": "alternateNames", "name": "polylactic acid resin", "ambiguous": False}})
        self.assertEqual(reflect.revert(self.root, "e-name", person=ada)["revertedBy"], "Ada")

    def test_reflection_mines_everyones_answers_but_never_quotes_another_persons_question(self):
        ada, grace = self.two()
        secret = "Grace's private question about Halar ECTFE and NEOFLON wire jackets?"
        for identifier, asker, search in (("a" * 32, ada["id"], "PLA crystallinity"),
                                          ("b" * 32, grace["id"], "Halar ECTFE dielectric constant"),
                                          ("c" * 32, None, "PLA crystallinity")):
            item = self.question(identifier, asker)
            item.update(runId="run-" + identifier, finishedAt="2026-11-05T11:00:00+00:00",
                        **({"question": secret} if asker == grace["id"] else {}))
            atomic_json(knowledge.folder(self.root) / "questions" / identifier / "question.json", item)
            atomic_json(knowledge.folder(self.root) / "questions" / identifier / "result.json", {"answer": {"answer": ""}})
            events = self.root / ".oopc/runs" / ("run-" + identifier) / "events.jsonl"
            events.parent.mkdir(parents=True)
            events.write_text(json.dumps({"operation": reflect.TOOL, "status": "ok",
                                          "request": {"arguments": {"q": search, "limit": 10}}}) + "\n")
        mined = {a["id"]: a for a in reflect.answers(self.root)}
        self.assertEqual(set(mined), {"a" * 32, "b" * 32, "c" * 32})  # Across the whole knowledge base.
        self.assertEqual((mined["b" * 32]["question"], mined["b" * 32]["theirs"]), ("", True))
        record = reflect.run(self.root, dry_run=True)
        dossier = json.dumps(record["dossier"])
        self.assertIn("ECTFE", dossier)  # Grace's search missed a name the graph lacks: it counts ...
        self.assertIn("another person's question, not shown", dossier)  # ... without her question,
        self.assertNotIn("NEOFLON", dossier)  # nor a name only her question gives.


class PeopleServer(unittest.TestCase):
    setUp = core.CoreLoopTests.setUp

    def start(self):
        self.ada, self.grace = people.add(self.root, "Ada", "first-password"), people.add(self.root, "Grace", "second-password")
        People.question(self, "a" * 32, self.ada["id"])
        People.question(self, "b" * 32, self.grace["id"])
        self.homes = []

        def theirs(person, home):
            self.homes.append(home)
            return AccountFixture(), AccountFixture()
        try:
            self.server = make_server(self.root, port=0, task_service=Questions(self.root, runner=core.ScriptedEngine()),
                                      account_service=AccountFixture(), claude_account_service=AccountFixture(),
                                      person_accounts=theirs)
        except PermissionError:
            self.skipTest("Sandbox blocks loopback binding; rerun with local-server permission")
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(3)))
        self.origin = "http://127.0.0.1:%d" % self.server.server_port
        self.csrf = self.request("GET", "/api/session")[1]["csrfToken"]

    def use(self, server):
        """Talk to another instance, with its own origin and its own page's CSRF token, as its page would."""
        self.server = server
        self.origin = "http://127.0.0.1:%d" % server.server_port
        self.csrf = self.request("GET", "/api/session")[1]["csrfToken"]

    def request(self, method, path, value=None, cookie=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        if method == "POST":
            headers.update({"Origin": self.origin, "Content-Type": "application/json", "X-OOPC-CSRF": self.csrf})
        try:
            connection.request(method, path, body=json.dumps(value) if method == "POST" else None, headers=headers)
            response = connection.getresponse()
            data = response.read()
            body = json.loads(data) if response.getheader("Content-Type") == "application/json" else data
            return response.status, body, response.getheader("Set-Cookie")
        finally:
            connection.close()

    def sign_in(self, name, password):
        code, value, cookie = self.request("POST", "/api/session", {"name": name, "password": password})
        self.assertEqual((code, value["person"]["name"]), (200, name))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        return cookie.split(";")[0]

    def test_each_person_signs_in_and_sees_only_their_own_questions(self):
        self.start()
        self.assertEqual(self.request("GET", "/")[0], 200)  # The page that shows the sign-in.
        self.assertEqual(self.request("GET", "/api/session")[1]["people"], True)
        code, value, _ = self.request("GET", "/api/tasks")
        self.assertEqual((code, value["signIn"]), (401, True))
        self.assertEqual(self.request("POST", "/api/tasks", {})[0], 401)
        started = time.monotonic()
        self.assertEqual(self.request("POST", "/api/session", {"name": "Grace", "password": "wrong-password"})[0], 403)
        self.assertGreaterEqual(time.monotonic() - started, 0.9)  # Guessing stays slow.
        grace = self.sign_in("Grace", "second-password")
        self.assertEqual([t["taskId"] for t in self.request("GET", "/api/tasks", cookie=grace)[1]["tasks"]], ["b" * 32])
        self.assertEqual(self.request("GET", "/api/tasks/" + "a" * 32, cookie=grace)[0], 404)
        self.assertEqual(self.request("GET", "/api/knowledge", cookie=grace)[0], 200)  # Shared knowledge.
        # Their own engine accounts, in their own folder.
        self.assertEqual(self.request("GET", "/api/runtimes", cookie=grace)[0], 200)
        self.assertEqual(self.homes, [knowledge.folder(self.root) / "people" / self.grace["id"]])
        # Only the owner changes settings or reads the operator's views.
        self.assertEqual(self.request("POST", "/api/settings", {"spotCheckRate": 0.5}, cookie=grace)[0], 403)
        self.assertEqual(self.request("GET", "/api/settings", cookie=grace)[0], 200)  # Anyone may read them.
        self.assertEqual(self.request("GET", "/api/runs", cookie=grace)[0], 403)
        code, shared, _ = self.request("GET", "/api/loop", cookie=grace)  # The Knowledge tab's shared counts only.
        self.assertEqual(code, 200)
        self.assertIn("knowledge", shared)
        self.assertFalse({"research", "log", "reflection", "reviews"} & set(shared))
        ada = self.sign_in("Ada", "first-password")
        self.assertEqual(self.request("POST", "/api/settings", {"spotCheckRate": 0.5}, cookie=ada)[0], 200)
        self.assertEqual(self.request("GET", "/api/runs", cookie=ada)[0], 200)
        self.assertEqual([t["taskId"] for t in self.request("GET", "/api/tasks", cookie=ada)[1]["tasks"]], ["a" * 32])
        # Signed out, the session no longer works.
        self.assertEqual(self.request("POST", "/api/session/end", {"signOut": True}, cookie=grace)[0], 200)
        self.assertEqual(self.request("GET", "/api/tasks", cookie=grace)[0], 401)

    def test_a_person_on_the_hosts_sign_ins_cannot_connect_or_cancel_them(self):
        self.start()
        people.set_engines(self.root, "Grace", True)
        grace = self.sign_in("Grace", "second-password")
        self.assertEqual(self.request("GET", "/api/runtimes", cookie=grace)[0], 200)
        self.assertEqual(self.homes, [])  # The host's own sign-in services, not a folder of hers.
        for path, field in (("/api/account/login", "authorizeAccountConnection"),
                            ("/api/account/cancel", "cancelAccountConnection"),
                            ("/api/runtimes/claude-code/login", "authorizeAccountConnection")):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, {field: True}, cookie=grace)[0], 403)
        ada = self.sign_in("Ada", "first-password")
        self.assertEqual(self.request("POST", "/api/account/cancel", {"cancelAccountConnection": True}, cookie=ada)[0], 202)

    def test_a_sign_in_on_one_instance_works_on_every_instance_of_the_host(self):
        """The browser sends one cookie to every port of the host; each instance must know it (2026-11-05: kept in each
        server's memory, signing in on a second instance signed the person out of the first)."""
        self.start()
        first = self.server
        second = make_server(self.root, port=0, task_service=Questions(self.root, runner=core.ScriptedEngine()),
                             account_service=AccountFixture(), claude_account_service=AccountFixture(),
                             person_accounts=lambda person, home: (AccountFixture(), AccountFixture()))
        thread = threading.Thread(target=second.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (second.shutdown(), second.server_close(), thread.join(3)))
        grace = self.sign_in("Grace", "second-password")
        self.use(second)  # The same cookie on the other instance.
        self.assertEqual([t["taskId"] for t in self.request("GET", "/api/tasks", cookie=grace)[1]["tasks"]], ["b" * 32])
        self.assertEqual(self.request("POST", "/api/session/end", {"signOut": True}, cookie=grace)[0], 200)
        self.use(first)  # Signed out there, signed out here.
        self.assertEqual(self.request("GET", "/api/tasks", cookie=grace)[0], 401)
        ada = self.sign_in("Ada", "first-password")
        self.assertNotIn(ada.split("=", 1)[1], (knowledge.folder(self.root) / "sessions.json").read_text())  # A hash.
        people.set_password(self.root, "Ada", "a-new-password")  # A new password signs them out everywhere.
        self.assertEqual(self.request("GET", "/api/tasks", cookie=ada)[0], 401)


if __name__ == "__main__":
    unittest.main()
