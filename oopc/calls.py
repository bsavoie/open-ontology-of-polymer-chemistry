"""Private accounting of actual engine attempts, including failures."""
import os
import time
import uuid
from pathlib import Path
from . import engines
from .util import atomic_json, locked, now, read_json


def new_tokens(usage):
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int for k in
                                         ("input_tokens", "cached_input_tokens", "output_tokens")):
        return None
    return max(0, usage["input_tokens"] - usage["cached_input_tokens"]) + usage["output_tokens"]


def invoke(root, phase, owner, runner, engine, prompt, schema, **options):
    """Run one engine session and record the attempt, its outcome and its usage. Sessions on one engine take turns."""
    identifier = uuid.uuid4().hex
    path = Path(root) / ".oopc" / "loop" / "calls" / (identifier + ".json")
    item = {"callId": identifier, "phase": phase, "owner": owner, "engine": engine, "pid": os.getpid(),
            "startedAt": now(), "outcome": "running", "usage": None, "newTokens": None}
    atomic_json(path, item, private=True)
    clock, started = time.monotonic(), None
    try:
        with locked(path.parent / (engine + ".lock")):
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
