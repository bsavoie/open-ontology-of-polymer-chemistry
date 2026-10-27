"""The background loop: review what is waiting, then work a small research queue.

`tick` runs two stages once and logs what happened:

1. **Review**: up to `REVIEWS_PER_TICK` answers whose findings are waiting for
   review (normally reviewed right after the answer; this catches the rest). A
   failed review is retried once on a later tick, then left failed.
2. **Research**: up to `researchPerWeek` questions a week from the research
   queue (0, the default, turns background research off), each asked like an
   ordinary question with origin `research`.

The parity set is run on demand (`oopc parity run`), not by the loop.

Background work keeps a quota reserve so it never uses the last part of a
subscription window; questions you ask yourself do not. `install` adds an
hourly launchd job on macOS; nothing runs in the background until then.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import subprocess
import sys
import uuid
from pathlib import Path

from . import engines, knowledge, reviewer
from .util import atomic_json, locked, now, read_json

REVIEWS_PER_TICK = 3
# Background work keeps this share of each engine's window for your own questions.
# Claude's is 0 by the owner's decision of 2026-09-29.
RESERVE_PERCENT = {"codex": 30, "claude-code": 0}
LABEL = "org.oopc.loop"


def _folder(root):
    return knowledge.folder(root)


def _log(root, entry):
    path = _folder(root) / "log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def recent_log(root, limit=20):
    path = _folder(root) / "log.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in reversed(lines) if line.strip()]


# ----- research queue -----

def _queue_path(root):
    return _folder(root) / "research.json"


def research_queue(root):
    path = _queue_path(root)
    return read_json(path).get("items", []) if path.exists() else []


def add_research(root, question, *, from_question=None):
    if not isinstance(question, str) or not 10 <= len(question.strip()) <= 2000:
        raise ValueError("A research question needs 10 to 2000 characters")
    with locked(_folder(root) / "research.lock"):
        items = research_queue(root)
        text = question.strip()
        existing = next((item for item in items if item["question"] == text), None)
        if existing:
            return existing
        item = {"id": uuid.uuid4().hex, "question": text, "fromQuestion": from_question, "addedAt": now(),
                "status": "waiting"}
        items.append(item)
        atomic_json(_queue_path(root), {"items": items}, private=True)
        return item


# ----- settings -----

REVIEW_MODES = ("researcher", "all")
DEFAULT_SETTINGS = {"reviewMode": "researcher", "spotCheckRate": 0.2, "researchPerWeek": 0}


def settings(root):
    """`reviewMode`: `researcher` adds findings on the researcher's judgement and sends only
    the ones it flags for review; `all` reviews every finding before it is used.
    `spotCheckRate`: the share of added findings also sent for review.
    `researchPerWeek`: how many queued questions the loop may ask a week; 0 turns background
    research off, and only then do answers' open questions stop joining the queue."""
    path = _folder(root) / "settings.json"
    value = dict(DEFAULT_SETTINGS)
    if path.exists():
        stored = read_json(path)
        value.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
        if stored.get("backgroundResearch") is False:  # Before 2026-10-02 background research had its own switch.
            value["researchPerWeek"] = 0
    return value


def update_settings(root, changes):
    if not isinstance(changes, dict) or not changes or set(changes) - set(DEFAULT_SETTINGS):
        raise ValueError("Unknown setting")
    if "reviewMode" in changes and changes["reviewMode"] not in REVIEW_MODES:
        raise ValueError("Review mode must be researcher or all")
    if "spotCheckRate" in changes and (type(changes["spotCheckRate"]) not in (int, float)
                                       or not 0 <= changes["spotCheckRate"] <= 1):
        raise ValueError("spotCheckRate must be between 0 and 1")
    if "researchPerWeek" in changes and (type(changes["researchPerWeek"]) is not int
                                         or not 0 <= changes["researchPerWeek"] <= 100):
        raise ValueError("researchPerWeek must be a whole number from 0 to 100")
    value = dict(settings(root), **changes)
    _folder(root).mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(_folder(root) / "settings.json", value, private=True)
    return value


def _week_start(moment=None):
    moment = moment or dt.datetime.now(dt.timezone.utc)
    return (moment - dt.timedelta(days=moment.weekday())).date().isoformat()


def asked_this_week(root, moment=None):
    week = _week_start(moment)
    return sum(1 for item in research_queue(root) if item.get("askedAt", "")[:10] >= week)


# ----- stages -----

def review_stage(root, *, runner=None, engine=None, limit=REVIEWS_PER_TICK, reserve_percent=RESERVE_PERCENT):
    done = []
    for question_id in knowledge.review_queue(root)[:limit]:
        try:
            summary = reviewer.review(root, question_id, runner=runner, engine=engine, reserve_percent=reserve_percent)
            done.append({"questionId": question_id, "status": (summary or {}).get("reviewStatus"),
                         "counts": (summary or {}).get("counts", {})})
        except engines.EngineError as error:
            done.append({"questionId": question_id, "status": "failed", "reason": error.reason, "message": str(error)[:300]})
            if error.reason in {"not-signed-in", "quota", "rate-limited"}:
                break  # Nothing else will succeed on this tick.
    return done


def research_stage(root, *, runner=None, engine=None, moment=None, reserve_percent=RESERVE_PERCENT):
    """Ask the next queued question. `engine`, like the review stage's, fixes the engine for its review."""
    from .ask import Questions
    preferences = settings(root)
    if not preferences["researchPerWeek"]:
        return {"status": "off"}
    if asked_this_week(root, moment) >= preferences["researchPerWeek"]:
        return {"status": "weekly-limit-reached"}
    waiting = [item for item in research_queue(root) if item["status"] == "waiting"]
    if not waiting:
        return {"status": "queue-empty"}
    answerer = engines.choose_engine(engines.preferred_engine(root), reserve_percent=reserve_percent) if runner is None \
        else engines.preferred_engine(root)
    if answerer is None:
        return {"status": "no-engine-available"}
    item = waiting[0]
    service = Questions(root, runner=runner, review_engine=engine)
    view = service.submit({"question": item["question"], "depth": "standard", "authorizeSubscription": True,
                           "runtime": answerer, "origin": "research"})
    with locked(_folder(root) / "research.lock"):
        items = research_queue(root)
        for entry in items:
            if entry["id"] == item["id"]:
                entry.update(status="asked", askedAt=now(), questionId=view["id"])
        atomic_json(_queue_path(root), {"items": items}, private=True)
    service.wait(reviews=True)  # Nothing is waiting on a background answer, so finish its review too.
    return {"status": "asked", "questionId": view["id"], "outcome": service.get(view["id"])["status"]}


def settle_deposits(root, *, runner=None, engine=None):
    """Deposits left saving by a process that stopped (an interrupted `oopc ask`, a killed tick), settled before the
    tick ends: their second turn is tried once more if the session is still saved, else they fail as interrupted."""
    from .ask import Questions
    service = Questions(root, runner=runner, review_engine=engine)
    settled = service.settle_stale()
    service.wait(reviews=True)
    return settled


def tick(root, *, runner=None, engine=None):
    """Run each stage once. Overlapping ticks skip instead of waiting."""
    root = Path(root).resolve()
    entry = {"startedAt": now()}
    try:
        with locked(_folder(root) / "tick.lock", blocking=False):
            entry["deposits"] = settle_deposits(root, runner=runner, engine=engine)
            entry["reviews"] = review_stage(root, runner=runner, engine=engine)
            entry["research"] = research_stage(root, runner=runner, engine=engine)
    except BlockingIOError:
        entry["status"] = "skipped-another-tick-running"
    entry["finishedAt"] = now()
    _log(root, entry)
    return entry


def status(root):
    from .ask import reuse_stats
    return {"knowledge": knowledge.summary(root), "reviews": knowledge.reviews(root, 10), "reuse": reuse_stats(root),
            "settings": settings(root), "spotChecks": knowledge.spot_check_stats(root),
            "research": {"queue": research_queue(root)[-20:], "askedThisWeek": asked_this_week(root),
                         "weeklyLimit": settings(root)["researchPerWeek"]},
            "log": recent_log(root, 10), "schedule": schedule_status(), "reservePercent": dict(RESERVE_PERCENT)}


# ----- launchd -----

def plist_path():
    return Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")


def install(root):
    root = Path(root).resolve()
    logs = _folder(root)
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "oopc", "--root", str(root), "loop", "tick"],
             "WorkingDirectory": str(root), "EnvironmentVariables": {"PATH": os.environ.get("PATH", ""),
                                                                     "PYTHONPATH": str(Path(__file__).resolve().parent.parent)},
             "StartInterval": 3600, "RunAtLoad": False, "ProcessType": "Background", "LowPriorityIO": True,
             "StandardOutPath": str(logs / "launchd.out.log"), "StandardErrorPath": str(logs / "launchd.err.log")}
    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(value))
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), LABEL)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), str(target)], capture_output=True)
    return schedule_status()


def uninstall():
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), LABEL)], capture_output=True)
    existed = plist_path().exists()
    if existed:
        plist_path().unlink()
    return {"status": "uninstalled" if existed else "not-installed"}


def schedule_status():
    return {"installed": plist_path().exists(), "label": LABEL, "interval": "hourly"}
