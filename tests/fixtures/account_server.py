"""Synthetic account and question services for the app server tests."""
import copy


class AccountFixture:
    def __init__(self):
        self.value = {"status": "disconnected", "account": None, "message": "Synthetic disconnected account"}
        self.status_calls = self.start_calls = self.cancel_calls = self.close_calls = 0
        self.start_entered = self.start_release = None

    def status(self):
        self.status_calls += 1
        return copy.deepcopy(self.value)

    def start_login(self):
        self.start_calls += 1
        self.value = {"status": "login-pending", "account": None, "message": "Synthetic login pending",
                      "loginUrl": "https://auth.openai.com/synthetic-test"}
        if self.start_entered is not None:
            self.start_entered.set()
            if not self.start_release.wait(3):
                raise AssertionError("Synthetic login gate did not release")
        return self.status()

    def cancel_login(self):
        self.cancel_calls += 1
        return self.status()

    def close(self):
        self.close_calls += 1


class TaskFixture:
    identifier = "a" * 32

    def __init__(self):
        self.actions = []
        self.before_submit = None
        self.items = []

    def status(self):
        return {"available": True}

    def list(self):
        return {"tasks": copy.deepcopy(self.items), "omitted": 0}

    def submit(self, request):
        if self.before_submit:
            self.before_submit()
        self.actions.append("submit")
        return {"taskId": self.identifier, "status": "queued"}

    def get(self, identifier):
        self.actions.append("get")
        return {"taskId": identifier, "status": "failed"}

    def retry(self, identifier):
        self.actions.append("retry")
        return {"taskId": identifier, "status": "queued"}
