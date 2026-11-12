"""The people who share one host's knowledge base (owner, 2026-11-05: several people on one machine, one host).

With nobody added, the app works as it always has, for the one person who runs it. Once people are added (`oopc people
add`), each signs in to the app, and:

- their questions, answers, traces and conversations are theirs alone; findings, the review queue, conflicts and
  reflection's edits are shared by everyone;
- each records who did it: the questions they ask, the findings their answers save, the conflicts they settle;
- each uses their own Codex or Claude account, kept in an engine folder of their own (`home`: its `codex` and `claude`
  folders become `CODEX_HOME` and `CLAUDE_CONFIG_DIR` for their sessions), so nobody's subscription pays for another's
  questions; the owner, the first person added, keeps the host's own sign-ins, and so does a person the owner sets to
  use them (`hostEngines`: `oopc people add --host-engines`, `oopc people engines`), whose sessions then share the
  host's account and its session slots. One account's sign-in cannot be copied into several folders: its first token
  refresh ends the other copies (Codex: "your refresh token was already used"), so people who share an account share
  the host's folder rather than each holding a copy;
- only the owner changes settings, runs the loop, queues background research or reverts reflection's edits.

`people.json` keeps each person's name and a salted PBKDF2 hash of their password, never the password itself. It and
the engine folders live under the host's private `.oopc/loop/`, so the operating-system user who runs the host can read
everyone's engine sign-ins: one host is for people who trust whoever runs it.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid

from . import knowledge
from .util import atomic_json, locked, now, read_json

FORMAT = "oopc-people-v1"
ITERATIONS = 240_000
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'-]{0,39}$")
MIN_PASSWORD = 8
SESSION_SECONDS = 12 * 3600


def _path(root):
    return knowledge.folder(root) / "people.json"


def _load(root):
    path = _path(root)
    value = read_json(path) if path.exists() else {}
    if not isinstance(value, dict) or value.get("format") != FORMAT or not isinstance(value.get("people"), list):
        value = {"format": FORMAT, "people": []}
    return value


def public(person):
    """What anyone may see of a person: id, name, whether they are the owner, and whether their engine sessions use the
    host's own sign-ins (the owner's always do)."""
    if not person:
        return None
    return {"id": person["id"], "name": person["name"], "owner": bool(person.get("owner")),
            "hostEngines": bool(person.get("owner") or person.get("hostEngines"))}


def everyone(root):
    return [public(p) for p in _load(root)["people"]]


def active(root):
    """Whether people have been added, so the app asks each to sign in."""
    return bool(_load(root)["people"])


def get(root, identifier):
    return public(next((p for p in _load(root)["people"] if p["id"] == identifier), None))


def owner(root):
    return public(next((p for p in _load(root)["people"] if p.get("owner")), None))


def _hash(password, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()


def _secret(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ValueError("A password needs at least %d characters" % MIN_PASSWORD)
    salt = secrets.token_hex(16)
    return {"salt": salt, "iterations": ITERATIONS, "hash": _hash(password, salt)}


def _find(people, name):
    return next((p for p in people if p["name"].casefold() == (name or "").strip().casefold()), None)


def add(root, name, password, host_engines=False):
    """Add a person; the first one added is the owner. With `host_engines`, their engine sessions use the host's own
    sign-ins instead of a folder of their own (`set_engines`). Returns what anyone may see of them."""
    name = " ".join((name or "").split())
    if not NAME.match(name):
        raise ValueError("A name is 1 to 40 letters, digits, spaces, dots, apostrophes or hyphens")
    secret = _secret(password)
    knowledge.folder(root).mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(knowledge.folder(root) / "people.lock"):
        value = _load(root)
        if _find(value["people"], name):
            raise ValueError("%s is already a person here" % name)
        person = {"id": "p-" + uuid.uuid4().hex[:12], "name": name, "owner": not value["people"], "password": secret,
                  "addedAt": now()}
        if host_engines:
            person["hostEngines"] = True
        value["people"].append(person)
        atomic_json(_path(root), value, private=True)
    return public(person)


def remove(root, name):
    """Remove a person (never the owner) and end their sign-ins. Their questions and engine folder stay on disk; the
    findings they saved stay in the shared knowledge, recorded as theirs."""
    with locked(knowledge.folder(root) / "people.lock"):
        value = _load(root)
        person = _find(value["people"], name)
        if person is None:
            raise ValueError("No person named %s" % name)
        if person.get("owner"):
            raise ValueError("The owner cannot be removed")
        value["people"].remove(person)
        atomic_json(_path(root), value, private=True)
        _end_sessions(root, person["id"])
    return public(person)


def set_password(root, name, password):
    secret = _secret(password)
    with locked(knowledge.folder(root) / "people.lock"):
        value = _load(root)
        person = _find(value["people"], name)
        if person is None:
            raise ValueError("No person named %s" % name)
        person["password"] = secret
        atomic_json(_path(root), value, private=True)
        _end_sessions(root, person["id"])  # A new password signs them out everywhere.
    return public(person)


def set_engines(root, name, host):
    """Whether a person's engine sessions use the host's own sign-ins (`host` true) or their own folder's. The owner's
    always use the host's. Their own folder, and any sign-in in it, stays on disk either way."""
    with locked(knowledge.folder(root) / "people.lock"):
        value = _load(root)
        person = _find(value["people"], name)
        if person is None:
            raise ValueError("No person named %s" % name)
        if person.get("owner"):
            raise ValueError("The owner always uses the host's engine sign-ins")
        if host:
            person["hostEngines"] = True
        else:
            person.pop("hostEngines", None)
        atomic_json(_path(root), value, private=True)
    return public(person)


def verify(root, name, password):
    """The person this name and password sign in, or None (the same work either way, so a wrong name and a wrong
    password cannot be told apart by time)."""
    person = _find(_load(root)["people"], name)
    secret = (person or {}).get("password") or {"salt": "00" * 16, "iterations": ITERATIONS, "hash": ""}
    given = _hash(password if isinstance(password, str) else "", secret["salt"], secret["iterations"])
    return public(person) if person and hmac.compare_digest(given, secret["hash"]) else None


# ----- sign-ins -----
# Kept in one file for every instance of the app on this host (several run at once, and the browser sends one cookie to
# all of them, whatever their port), by a hash of their token, never the token: signed in on one instance, a person is
# signed in on all, and a restart keeps them signed in (2026-11-05: in each server's memory, signing in on a second
# instance signed the person out of the first).

def _sessions_path(root):
    return knowledge.folder(root) / "sessions.json"


def _token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sessions(root):
    path = _sessions_path(root)
    value = read_json(path).get("sessions") if path.exists() else None
    return value if isinstance(value, dict) else {}


def _save_sessions(root, sessions):
    moment = time.time()
    atomic_json(_sessions_path(root), {"sessions": {k: v for k, v in sessions.items() if v.get("expires", 0) > moment}},
                private=True)


def open_session(root, person, seconds=SESSION_SECONDS):
    """A new sign-in for a person, lasting `seconds`; returns its token, which only the person's browser keeps."""
    token = secrets.token_urlsafe(32)
    with locked(knowledge.folder(root) / "people.lock"):
        sessions = _sessions(root)
        sessions[_token(token)] = {"person": person["id"], "expires": time.time() + seconds}
        _save_sessions(root, sessions)
    return token


def session_person(root, token):
    """The person a sign-in token belongs to, while it lasts; None otherwise."""
    if not isinstance(token, str) or not token:
        return None
    entry = _sessions(root).get(_token(token))
    if not isinstance(entry, dict) or entry.get("expires", 0) < time.time():
        return None
    return get(root, entry.get("person"))


def close_session(root, token):
    if not isinstance(token, str) or not token:
        return
    with locked(knowledge.folder(root) / "people.lock"):
        sessions = _sessions(root)
        sessions.pop(_token(token), None)
        _save_sessions(root, sessions)


def _end_sessions(root, person_id):
    """Every sign-in of one person ends (called with the people lock held)."""
    sessions = _sessions(root)
    _save_sessions(root, {k: v for k, v in sessions.items() if v.get("person") != person_id})


def home(root, person):
    """A person's engine folder (`codex` and `claude` inside), created owner-only; None for the owner, for a person set
    to use the host's sign-ins, and for the one person of a host nobody was added to, who use the host's own."""
    from .engines import own_accounts
    if not own_accounts(person):
        return None
    folder = knowledge.folder(root) / "people" / person["id"]
    for part in (folder, folder / "codex", folder / "claude"):
        part.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def runtime(root, person):
    """A person's chosen engine, or None (then the host's choice)."""
    found = next((p for p in _load(root)["people"] if person and p["id"] == person["id"]), None)
    return (found or {}).get("runtime")


def choose_runtime(root, person, engine):
    with locked(knowledge.folder(root) / "people.lock"):
        value = _load(root)
        found = next((p for p in value["people"] if p["id"] == person["id"]), None)
        if found is None:
            raise ValueError("No such person")
        found["runtime"] = engine
        atomic_json(_path(root), value, private=True)
    return engine


def asked_by(item, root):
    """Whose a question is: its asker, else (asked before people were added, or by the loop) the owner's."""
    return item.get("askedBy") or ((owner(root) or {}).get("id"))


def may_see(root, person, item):
    """Whether a person may see a question: their own; everyone's when nobody was added."""
    return person is None or asked_by(item, root) == person["id"]
