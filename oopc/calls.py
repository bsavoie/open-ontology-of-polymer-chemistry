"""Private accounting of actual engine attempts, including failures."""
import os
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from . import engines
from .util import atomic_json, locked, now, read_json

# What each engine is doing for this process, so a session waiting for its turn can say what it waits for.
_BUSY = {}
WAITING = {"deposit": "Waiting for the last answer's findings to be saved",
           "review": "Waiting for the last answer's review to finish",
           "research": "Waiting for the question before it to finish"}


def new_tokens(usage):
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int for k in
                                         ("input_tokens", "cached_input_tokens", "output_tokens")):
        return None
    return max(0, usage["input_tokens"] - usage["cached_input_tokens"]) + usage["output_tokens"]


def slots(root):
    """How many sessions each engine runs at once on this workspace (the `parallelQuestions` setting, 1 by default)."""
    from .loop import settings
    try:
        return settings(root)["parallelQuestions"]
    except (OSError, ValueError, KeyError):
        return 1


def _slot(path, engine, count, progress):
    """A free session slot of `engine` (a lock file: `<engine>.lock`, then `<engine>-2.lock` ...), waiting for one when
    all `count` are busy; returns the held lock's context manager, entered."""
    names = [engine + ".lock"] + ["%s-%d.lock" % (engine, n) for n in range(2, count + 1)]
    told = False
    while True:
        for name in names:
            held = locked(path / name, blocking=False)
            try:
                held.__enter__()
            except BlockingIOError:
                continue
            return held, name
        if count == 1:  # One slot: wait on it, as sessions always did.
            if hasattr(progress, "wait") and not told:
                progress.wait(WAITING.get(_busy(engine), "Waiting for the engine to finish another task"))
            held = locked(path / names[0])
            held.__enter__()
            return held, names[0]
        if hasattr(progress, "wait") and not told:
            progress.wait(WAITING.get(_busy(engine), "Waiting for the engine to finish another task"))
            told = True
        time.sleep(0.2)


def _busy(engine):
    return next((phase for (name, _), phase in list(_BUSY.items()) if name == engine), None)


def invoke(root, phase, owner, runner, engine, prompt, schema, **options):
    """Run one engine session and record the attempt, its outcome and its usage. Sessions on one engine take turns,
    background ones (an answer's findings, its review) included: a question asked right after another, often a follow-up,
    then reads the findings the last answer saved (2026-10-26: letting it start sooner made that a race). With
    `parallelQuestions` above 1, that many sessions of one engine run at once (`slots`); a follow-up still waits for the
    answer before it (`ask.Questions._await_parent`)."""
    identifier = uuid.uuid4().hex
    path = Path(root) / ".oopc" / "loop" / "calls" / (identifier + ".json")
    person = engines.current_person()
    item = {"callId": identifier, "phase": phase, "owner": owner, "engine": engine, "pid": os.getpid(),
            "startedAt": now(), "outcome": "running", "usage": None, "newTokens": None}
    if person:
        item["person"] = person["id"]
    atomic_json(path, item, private=True)
    clock, started, progress = time.monotonic(), None, options.get("progress")
    try:
        with ExitStack() as turn:
            # A live question shows what it waits for while every slot is busy; its clock has not started.
            # A person of a shared host with their own sign-ins has slots of their own: their sessions run on their own
            # subscription. One who uses the host's sign-ins shares the host's slots, as they share its account.
            mine = engine + ("@" + person["id"] if engines.own_accounts(person) else "")
            held, name = _slot(path.parent, mine, slots(root), progress)
            turn.callback(held.__exit__, None, None, None)
            _BUSY[(mine, name)] = phase
            turn.callback(_BUSY.pop, (mine, name), None)
            if hasattr(progress, "begin"):
                progress.begin()
            started = time.monotonic()
            result = (runner or engines.run_session)(engine, prompt, schema, **options)
        item.update(outcome="completed", usage=result.get("usage"), sessionId=result.get("sessionId"))
        return dict(result, callId=identifier)
    except engines.EngineError as error:
        item.update(outcome="failed", reason=error.reason, usage=error.usage, message=str(error)[:400])
        raise
    except BaseException as error:
        item.update(outcome="failed", reason="interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "crashed",
                    message=str(error)[:400])
        raise
    finally:
        item.update(finishedAt=now(), elapsedSeconds=round(time.monotonic() - clock, 3),
                    seconds=round(time.monotonic() - started, 3) if started is not None else 0)
        item["newTokens"] = new_tokens(item.get("usage"))
        atomic_json(path, item, private=True)


def records(root, since=""):
    rows = []
    for path in (Path(root) / ".oopc" / "loop" / "calls").glob("*.json"):
        value = read_json(path)
        if value.get("startedAt", "") < since:
            continue
        if value.get("outcome") == "running":
            try:
                os.kill(value["pid"], 0)
            except ProcessLookupError:
                value.update(outcome="failed", reason="interrupted", finishedAt=now(), recoveredFromCrash=True)
                atomic_json(path, value, private=True)
            except PermissionError:
                pass
        rows.append(value)
    return sorted(rows, key=lambda r: r["startedAt"])


def summary(root, since=""):
    rows, phases, failures = records(root, since), {}, {}
    for row in rows:
        bucket = phases.setdefault(row["phase"], {"calls": 0, "newTokens": 0, "missingUsage": 0, "seconds": 0})
        bucket["calls"] += 1
        bucket["newTokens"] += row.get("newTokens") or 0
        bucket["missingUsage"] += row.get("newTokens") is None
        bucket["seconds"] += row.get("seconds") or 0
        if row["outcome"] == "failed":
            reason = row.get("reason", "interrupted")
            failures[reason] = failures.get(reason, 0) + 1
    measured = sum(b["newTokens"] for b in phases.values())
    checking = sum(b["newTokens"] for p, b in phases.items() if p in {"review", "flagged-review", "spot-check", "answer-check"})
    return {"calls": len(rows), "measuredNewTokens": measured, "missingUsage": sum(b["missingUsage"] for b in phases.values()),
            "coverageStartsAt": rows[0]["startedAt"] if rows else None, "byPhase": phases, "checkingTokenFraction": checking / measured if measured else None, "failed": failures,
            "accumulatedCallSeconds": sum(r.get("seconds") or 0 for r in rows)}
