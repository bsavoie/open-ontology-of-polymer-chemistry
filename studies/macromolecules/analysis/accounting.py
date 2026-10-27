#!/usr/bin/env python3
"""The Macromolecules study's run accounting (SI, "failure and retry accounting"), from the records only: no engine
call, no store opened, nothing under the run folders written.

Per experiment, from its run folders under `.oopc/loop/harness/`:

- A2 `2026-10-kf-scaling`, A3 `2026-10-kf-resampled`, A4 `2026-10-kf-ladder` and E8 `2026-10-kf-e8`: driver folders
  `r<replicate>-s<shard>`;
- A5's case studies, the 2026-10-16 run `2026-10-case-studies` (r1) and `2026-10-case-studies-r2` ... `-r5`: four
  driver folders per replicate, cs4's first askings through the loop (`cs4-first`) and the blind scoring (`scoring`);
- E9 `2026-10-planted-kf-r1` ... `-r5`: the driver folders `before` and `after`, the review of the planted store and
  the blind scoring; and the blind scoring of the 2026-10-13 E9 run (`2026-10-kf-a5/e9-2026-10-13`), listed apart;
- Part B's rounds, `2026-10-restarts/R1` ... `R5`: the tasks through freeze-2's loop (research, reviews and
  whole-answer checks in `R<n>/workspace`), the improver, and the dev evaluations (`R<n>/eval/round-*/dev/shard-*`);
- Part B's final evaluation, `2026-10-restarts/final/shard-*`.

What is read, and how:

- Engine sessions and new tokens: every token ledger (`<workspace>/.oopc/loop/calls/*.json`, one file per attempt, as
  `oopc.calls.records` reads them; read here as files, so a record left "running" is reported, never rewritten). A
  session's phase is its ledger phase: research (`study:*:research`, the loop's `research`), check (`study:*:check`, the
  loop's `answer-check`), review, improver and blind scoring (`study:*:score`); Part B's rounds split research and checks
  into the tasks' and the dev evaluations'. New tokens are `calls.new_tokens` (uncached input plus output), the total
  over every attempt, the median over completed sessions.
- Failed attempts: each failed ledger record by its named reason. `slept` is named when the session was stopped because
  the machine slept (the Guard's reason) or when the machine slept during it: its wall-clock time ran more than 60 s
  ahead of its monotonic time (`driver.SLEPT`), whatever the engine then reported; the recorded reason is kept beside
  it. A failed attempt "retried and completed" when a later attempt of the same work (same workspace, ledger phase and
  owner: the question, task or round) completed, and "failed for good" otherwise. A completed session whose result
  was later replaced (a question's checks run again together after one failed, a question answered again) is counted
  as redone. The driver items' own attempt records (`items/*.json`) are counted beside the ledger as a cross-check, and
  so are the Guard's raw stream files (`streams/*.jsonl`, one per session started).
- Work completed: driver items answered and checked; cs4's first askings; Part B's tasks (`question.json`), sampled
  whole-answer checks (`waves/*/checks`), reviews, improver proposals (`improver/round-*.json`, with proposals that
  could not be applied); E9's reviews (`review.json`); blind scoring groups (`scoring/*.json`).
- Wall-clock span: the first ledger session's start to the last one's end; active hours are the union of the session
  intervals.
- Harness revisions: each run's `runs.jsonl` (Part A: `harness.revision`; Part B: `harness` and the code under test),
  the restarts' `baseline.json` and the final evaluation's `final.json`.

The supervisor (`supervisor/activity.jsonl`): its runs, stream launches, exits by reason, and a short timeline with the
periods the machine slept (gaps in every run folder's activity log, each inside a session that recorded the sleep)
and the periods Codex was at its floor (its quota readings at or below the supervisor's launch threshold, 10%).

Writes `.oopc/study/analysis/accounting/results.json` and `results.md`.

    OOPC_STUDY_ROOT=<main checkout> python -B studies/macromolecules/analysis/accounting.py [--out DIR]
"""
import argparse, collections, datetime as dt, json, os, re, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402

HARNESS = common.ROOT / ".oopc/loop/harness"
OUT = common.analysis_dir("accounting")
SLEPT = 60  # seconds wall-clock may run ahead of monotonic time before a session counts as slept through (driver.SLEPT)
GAP = 60  # seconds without any activity event, inside a slept session, that locate a sleep
AFTER_WAKE = 120  # a failure starting this soon after a located sleep ended is flagged as just after waking
CODEX_LOW = 10  # the supervisor launches nothing while Codex has this percent or less left (FLOOR 0 + MARGIN 10)
REASONS = ("timeout", "crashed", "rejected", "invalid-output", "interrupted", "not-signed-in", "quota", "rate-limited",
           "slept")
PHASES = ("research", "check", "review", "improver", "blind scoring")
EXPERIMENTS = (  # key, label, folders under the harness folder
    ("A2", "A2: memory and scaling (60 questions x 8 arms x 3 replicates)", ["2026-10-kf-scaling"]),
    ("A3", "A3: resampled stores (60 questions x 22 arms)", ["2026-10-kf-resampled"]),
    ("A4", "A4: similarity ladder (90 questions x 2 arms x 2 replicates)", ["2026-10-kf-ladder"]),
    ("A5", "A5: case studies, five replicates (r1 = 2026-10-16)",
     ["2026-10-case-studies"] + ["2026-10-case-studies-r%d" % r for r in range(2, 6)]),
    ("E9", "A5: E9 planted findings, five replicates", ["2026-10-planted-kf-r%d" % r for r in range(1, 6)]),
    ("E9-2026-10-13", "A5: the 2026-10-13 E9 run, scored blind", ["2026-10-kf-a5/e9-2026-10-13"]),
    ("E8", "E8: the researcher on Claude Code (20 near questions x 2 arms)", ["2026-10-kf-e8"]),
    ("B-rounds", "Part B: five restarts x five rounds (tasks, reviews, checks, improver, dev)",
     ["2026-10-restarts/R%d" % r for r in range(1, 6)]),
    ("B-final", "Part B: final evaluation (60 questions x 50 arms, 10 shards)", ["2026-10-restarts/final"]),
)
SKIP = {"releases", "items", "streams", "snapshots", "prompts"}  # never holds a ledger (releases are symlinks)


def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def jlines(path):
    rows = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def when(text):
    return dt.datetime.fromisoformat(text)


def iso(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z") if value else None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def walk(folder):
    """Every directory under `folder`, without following symlinks or entering folders that never hold a ledger."""
    for path, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        yield Path(path), files


# ----- engine sessions -----

def phase_of(experiment, rel, raw):
    """The accounting phase of a ledger record: research, check, review, improver or blind scoring; Part B's rounds name
    the tasks' and the dev evaluations' research and checks apart."""
    if raw.endswith(":score"):
        phase = "blind scoring"
    elif raw == "research" or raw.startswith("study:") and raw.endswith(":research"):
        phase = "research"
    elif raw == "answer-check" or raw.startswith("study:") and raw.endswith(":check"):
        phase = "check"
    elif raw in ("review", "improver"):
        phase = raw
    else:
        phase = raw
    if experiment == "B-rounds" and phase in ("research", "check", "review"):
        phase += " (dev)" if "/eval/" in rel else " (tasks)"
    return phase


def sessions(experiment, folders):
    """Every ledger record of the experiment's folders, with where it was found, its accounting phase and how far its
    wall-clock time ran ahead of its monotonic time (`drift`)."""
    rows = []
    for name in folders:
        base = HARNESS / name
        for path, files in walk(base):
            if path.name != "calls" or path.parent.name != "loop":
                continue
            ledger = str(path.parent.parent.parent.relative_to(HARNESS))
            for file in sorted(files):
                if not file.endswith(".json"):
                    continue
                r = jread(path / file)
                start, end = when(r["startedAt"]), when(r["finishedAt"]) if r.get("finishedAt") else None
                drift = (end - start).total_seconds() - (r.get("elapsedSeconds") or 0) if end else None
                rows.append(dict(r, ledger=ledger, experiment=experiment, folder=name,
                                 accountingPhase=phase_of(experiment, ledger, r.get("phase", "")),
                                 start=start, end=end, drift=drift))
    return sorted(rows, key=lambda r: r["start"])


def name_reason(row):
    """The failure's named reason: `slept` when the Guard stopped the session for a sleep or the machine slept during it,
    else the reason the ledger recorded."""
    if row.get("message") == "slept" or (row.get("drift") or 0) > SLEPT:
        return "slept"
    return row.get("reason") or "interrupted"


def interrupted_detail(row):
    message = row.get("message") or ""
    if message == "owner-stop":
        return "owner stop (STOP file), refused or stopped by the Guard"
    if "exited with -15" in message:
        return "engine killed by SIGTERM when its run was stopped"
    if "exited with -" in message:
        return "engine killed when a sibling session was stopped"
    return message[:60] or "unspecified"


def settle(rows):
    """Mark each failed record retried-and-completed or failed for good, and count completed sessions redone."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["ledger"], r.get("phase"), r.get("owner"))].append(r)
    redone = collections.Counter()
    for group in groups.values():
        group.sort(key=lambda r: r["start"])
        done = [r for r in group if r["outcome"] == "completed"]
        for r in done[:-1]:
            redone[r["accountingPhase"]] += 1
        for i, r in enumerate(group):
            if r["outcome"] != "completed":
                r["ended"] = ("retried and completed" if any(x["outcome"] == "completed" for x in group[i + 1:])
                              else "failed for good")
    return redone


def summarize_sessions(rows, wakes):
    """Sessions, failures and new tokens by engine and phase."""
    by = collections.defaultdict(lambda: {"calls": 0, "completed": 0, "failed": 0, "neverStarted": 0,
                                          "newTokens": 0, "missingUsage": 0, "seconds": 0.0, "done": []})
    failures = []
    for r in rows:
        b = by[(r["engine"], r["accountingPhase"])]
        b["calls"] += 1
        b["seconds"] += r.get("seconds") or 0
        b["newTokens"] += r.get("newTokens") or 0
        b["missingUsage"] += r.get("newTokens") is None
        if r["outcome"] == "completed":
            b["completed"] += 1
            if r.get("newTokens") is not None:
                b["done"].append(r["newTokens"])
        else:
            b["failed"] += 1
            b["neverStarted"] += not r.get("seconds")
            reason = name_reason(r)
            after_wake = any(0 <= (r["start"] - w).total_seconds() <= AFTER_WAKE for w in wakes)
            failures.append({"at": iso(r["start"]), "engine": r["engine"], "phase": r["accountingPhase"],
                             "reason": reason, "recordedReason": r.get("reason"),
                             "detail": interrupted_detail(r) if reason == "interrupted" else None,
                             "afterWake": after_wake and reason != "slept", "ended": r.get("ended"),
                             "seconds": r.get("seconds"), "drift": round(r["drift"]) if r.get("drift") else None,
                             "ledger": r["ledger"], "owner": r.get("owner"),
                             "message": (r.get("message") or "")[:160]})
    table = []
    for (engine, phase), b in sorted(by.items(), key=lambda kv: (kv[0][0], order(kv[0][1]))):
        table.append({"engine": engine, "phase": phase, "calls": b["calls"], "completed": b["completed"],
                      "failed": b["failed"], "neverStarted": b["neverStarted"], "newTokens": b["newTokens"],
                      "medianNewTokens": median(b["done"]), "missingUsage": b["missingUsage"],
                      "sessionHours": round(b["seconds"] / 3600, 2)})
    return table, failures


def order(phase):
    base = phase.split(" (")[0]
    return (PHASES.index(base) if base in PHASES else len(PHASES), phase)


def failure_table(failures):
    """Failed attempts by named reason and how each ended."""
    table = {}
    for f in failures:
        row = table.setdefault(f["reason"], {"attempts": 0, "retried and completed": 0, "failed for good": 0,
                                             "recordedAs": collections.Counter(), "afterWake": 0,
                                             "byPhase": collections.Counter(), "details": collections.Counter()})
        row["attempts"] += 1
        row[f["ended"]] += 1
        row["recordedAs"][f["recordedReason"]] += 1
        row["afterWake"] += f["afterWake"]
        row["byPhase"][f["phase"]] += 1
        if f["detail"]:
            row["details"][f["detail"]] += 1
    return {reason: dict(v, recordedAs=dict(v["recordedAs"]), byPhase=dict(v["byPhase"]), details=dict(v["details"]))
            for reason, v in sorted(table.items(), key=lambda kv: REASONS.index(kv[0]) if kv[0] in REASONS else 99)}


def span(rows):
    if not rows:
        return {}
    start, end = min(r["start"] for r in rows), max(r["end"] or r["start"] for r in rows)
    merged, active = [], 0.0
    for r in sorted(rows, key=lambda r: r["start"]):
        s, e = r["start"], r["end"] or r["start"]
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    active = sum((e - s).total_seconds() for s, e in merged)
    days = sorted({r["start"].date().isoformat() for r in rows})
    return {"first": iso(start), "last": iso(end), "hours": round((end - start).total_seconds() / 3600, 1),
            "activeHours": round(active / 3600, 1), "days": days}


# ----- work completed, from the run records -----

def driver_folders(folder):
    """Driver folders (a plan with arms, and items) under `folder`."""
    found = []
    for path, files in walk(HARNESS / folder):
        if "plan.json" in files and (path / "items").is_dir():
            plan = jread(path / "plan.json")
            if isinstance(plan.get("arms"), list):
                found.append(path)
    return found


def driver_work(paths):
    """Items answered and checked, failed for good, redone, and the driver's own attempt records."""
    value = collections.Counter()
    attempts = collections.Counter()
    for path in paths:
        plan = jread(path / "plan.json")
        for index, question in enumerate(plan["questions"]):
            for arm in plan["arms"]:
                item_path = path / "items" / ("%04d-%s.json" % (index, arm["name"]))
                item = jread(item_path) if item_path.exists() else {}
                value["items"] += 1
                for part in ("answer", "check"):
                    got = item.get(part)
                    if got is None:
                        value[part + "Missing"] += 1
                    elif "error" in got:
                        value[part + "FailedForGood"] += 1
                    else:
                        value[part + "s"] += 1
                value["answersRedone"] += len(item.get("previousAnswers", []))
                value["checksRedone"] += len(item.get("previousChecks", []))
                for a in item.get("attempts", []):
                    key = "%s %s" % (a["part"], a["outcome"])
                    if a["outcome"] != "completed":
                        key += " " + ("slept" if a.get("slept") else a.get("reason", "?"))
                    attempts[key] += 1
    return dict(value), dict(attempts)


def first_asks(base):
    value = collections.Counter()
    for path in sorted((base / "cs4-first" / "items").glob("*.json")):
        item = jread(path)
        value["answers"] += "answer" in item
        value["checks"] += "check" in item
        value["checkFailed"] += "checkError" in item
    return dict(value)


def scoring(base):
    value = collections.Counter()
    folder = base / "scoring"
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if path.name == "report.json" or path.name.endswith("-key.json"):
            continue
        group = jread(path)
        value["groups"] += 1
        value["scored"] += bool(group.get("scores"))
        value["attempts"] += group.get("attempts") or 0
    return dict(value)


def restart_work(base):
    """A restart's tasks, sampled whole-answer checks and improver proposals."""
    value = collections.Counter()
    tasks = {t["taskId"] for t in jread(base / "rounds.json")}
    for path in (base / "workspace/.oopc/loop/questions").iterdir():
        if path.name in tasks and (path / "question.json").exists():
            state = jread(path / "question.json")
            value["tasks" + state["status"].capitalize()] += 1
            if state["status"] == "failed":
                value["tasksFailed:" + ((state.get("error") or {}).get("reason") or "?")] += 1
            value["taskRetriesRequested"] += sum(a.get("outcome") == "retry-requested" for a in state.get("attempts", []))
    value["tasks"] = len(tasks)
    for path in sorted((base / "waves").glob("wave-*/checks/check-*.json")):
        check = jread(path)
        value["checksFailedForGood" if "error" in check else "checks"] += 1
        value["checkFailedAttempts"] += len(check.get("failedAttempts") or [])
    for path in sorted((base / "improver").glob("round-*.json")):
        if path.name.endswith("-records.json"):
            continue
        record = jread(path)
        value["improverRounds"] += 1
        value["improverProposals"] += bool(record.get("proposal"))
        value["improverNotApplicable"] += sum(bool(a.get("problem")) for a in record.get("attempts", []))
        value["improverAttemptsFailed"] += sum("error" in a for a in record.get("attempts", []))
    return dict(value)


def work(key, folders):
    """What the experiment completed, from its run records."""
    value = collections.Counter()
    for name in folders:
        base = HARNESS / name
        got, _ = driver_work(driver_folders(name))
        for k, v in got.items():
            value["driver." + k] += v
        if (base / "cs4-first").exists():
            for k, v in first_asks(base).items():
                value["cs4First." + k] += v
        for k, v in scoring(base).items():
            value["scoring." + k] += v
        if (base / "review.json").exists():
            review = jread(base / "review.json")
            value["e9Reviews"] += 1
            value["e9ReviewFailures"] += len(review.get("failures") or [])
            value["e9PlantsJudged"] += len(review.get("verdicts") or {})
        if key == "B-rounds":
            for k, v in restart_work(base).items():
                value["restart." + k] += v
    answers = value["driver.answers"] + value["cs4First.answers"] + value["restart.tasksCompleted"]
    checks = value["driver.checks"] + value["cs4First.checks"] + value["restart.checks"]
    return dict(sorted(value.items())), answers, checks


def driver_attempts(folders):
    total = collections.Counter()
    for name in folders:
        _, got = driver_work(driver_folders(name))
        total.update(got)
    return dict(sorted(total.items()))


def streams(folders):
    count = 0
    for name in folders:
        for path, dirs, files in os.walk(HARNESS / name, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ("releases", "items", ".oopc")]
            if Path(path).name == "streams":
                count += sum(f.endswith(".jsonl") for f in files)
    return count


# ----- revisions -----

def revisions(folders):
    """The harness (and, for Part B, code) revisions each run started from, with the run's stop where recorded."""
    runs = collections.Counter()
    code = collections.Counter()
    stops = collections.Counter()
    clean = True
    for name in folders:
        for path, files in walk(HARNESS / name):
            if "runs.jsonl" in files:
                for entry in jlines(path / "runs.jsonl"):
                    harness = entry.get("harness")
                    revision = harness.get("revision") if isinstance(harness, dict) else harness
                    runs[(revision or "?")[:7]] += 1
                    clean = clean and (harness.get("clean") if isinstance(harness, dict) else entry.get("harnessClean"))
                    if entry.get("code"):
                        code[entry["code"][:7]] += 1
                    if "status" in entry:
                        stops[entry.get("stopReason") or entry.get("status")] += 1
            for file in ("baseline.json", "final.json", "pins.json"):
                if file in files:
                    record = jread(path / file)
                    tag = record.get("revision") or (record.get("provenance") or {}).get("code") or record.get("tagCommit")
                    if tag:
                        code[tag[:7]] += 0
    return {"runs": dict(runs), "launches": sum(runs.values()), "allClean": bool(clean),
            "code": sorted(code), "runEnds": dict(stops)}


# ----- sleeps, Codex's floor and the supervisor -----

def activity_events():
    """Every event of the study's run folders' activity logs (not the supervisor's), as (time, event record)."""
    events = []
    for _, _, folders in EXPERIMENTS:
        for name in folders:
            for path, dirs, files in os.walk(HARNESS / name, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP | {"workspaces", "workspace", ".oopc"})
                if "activity.jsonl" in files:
                    folder = str(Path(path).relative_to(HARNESS))
                    for r in jlines(Path(path) / "activity.jsonl"):
                        if "at" in r:
                            events.append((when(r["at"]), dict(r, _folder=folder)))
    return sorted(events, key=lambda e: e[0])


def sleeps(events, rows):
    """Sleeps located as gaps in every activity log that lie inside a session whose wall-clock time ran ahead of its
    monotonic time; each with the largest drift recorded by a session spanning it."""
    slept = [r for r in rows if (r.get("drift") or 0) > SLEPT and r["end"]]
    found = []
    times = [t for t, _ in events]
    for a, b in zip(times, times[1:]):
        gap = (b - a).total_seconds()
        if gap <= GAP:
            continue
        spanning = [r for r in slept if r["start"] <= a and r["end"] >= b]
        if spanning:
            found.append({"from": iso(a), "to": iso(b), "minutes": round(gap / 60, 1),
                          "sessionsSpanning": len(spanning),
                          "largestDrift": round(max(r["drift"] for r in spanning) / 60, 1)})
    return found


def codex_low(events):
    """Periods in which Codex's readings were at or below the supervisor's launch threshold."""
    readings = [(t, r.get("remaining")) for t, r in events
                if r.get("event") == "quota" and r.get("engine") == "codex" and r.get("remaining") is not None]
    periods, current = [], None
    for t, remaining in readings:
        if remaining <= CODEX_LOW:
            if current is None:
                current = {"from": t, "to": t, "lowest": remaining, "readings": 0}
            current["to"], current["lowest"] = t, min(current["lowest"], remaining)
            current["readings"] += 1
        elif current is not None:
            current["recoveredTo"], current["recoveredAt"] = remaining, t
            periods.append(current)
            current = None
    if current:
        periods.append(current)
    return [{"from": iso(p["from"]), "lastLow": iso(p["to"]), "lowest": p["lowest"], "readings": p["readings"],
             "recoveredAt": iso(p.get("recoveredAt")), "recoveredTo": p.get("recoveredTo")} for p in periods]


def claude_low(events, floor=40):
    readings = [(t, r.get("remaining")) for t, r in events
                if r.get("event") == "quota" and r.get("engine") == "claude-code" and r.get("remaining") is not None]
    periods, current = [], None
    for t, remaining in readings:
        if remaining <= floor:
            current = current or {"from": t, "lowest": remaining}
            current["to"], current["lowest"] = t, min(current["lowest"], remaining)
        elif current:
            periods.append(dict(current, recoveredAt=t, recoveredTo=remaining))
            current = None
    if current:
        periods.append(current)
    return [{"from": iso(p["from"]), "lastLow": iso(p["to"]), "lowest": p["lowest"],
             "recoveredAt": iso(p.get("recoveredAt")), "recoveredTo": p.get("recoveredTo")} for p in periods]


def stream_experiment(name):
    for prefix, key in (("R", "B-rounds"), ("final-", "B-final"), ("kf-scaling", "A2"), ("kf-resampled", "A3"),
                        ("kf-ladder", "A4"), ("case-studies", "A5"), ("planted", "E9"), ("kf-e8", "E8")):
        if name.startswith(prefix) and (prefix != "R" or name[1:].isdigit()):
            return key
    return "?"


def stop_reason(reason):
    """A stream's stop reason without its phase: "round 3 tasks stopped (no-eligible-engine)" -> no-eligible-engine."""
    if not reason:
        return None
    found = re.search(r"\(([^)]*)\)\s*$", reason)
    if found:
        return found.group(1)
    if reason.startswith("improver failed: "):
        return reason.split(": ", 1)[1]
    return reason


def supervisor(events, rows):
    path = HARNESS / "supervisor" / "activity.jsonl"
    log = jlines(path)
    runs, current = [], None
    for r in log:
        if r["event"] == "supervisor-started":
            current = {"started": r["at"][:19] + "Z", "config": Path(r.get("config", "")).name, "launches": 0,
                       "exits": collections.Counter()}
            runs.append(current)
        elif r["event"] == "supervisor-stopped" and current:
            current["stopped"] = r["at"][:19] + "Z"
            current["leftRunning"] = r.get("running") or []
        elif r["event"] == "stream-launched" and current:
            current["launches"] += 1
        elif r["event"] == "stream-exited" and current:
            current["exits"][stop_reason(r.get("reason")) or r.get("status")] += 1
    launches = collections.Counter(stream_experiment(r["stream"]) for r in log if r["event"] == "stream-launched")
    exits = collections.Counter(stop_reason(r.get("reason")) or r.get("status") for r in log
                                if r["event"] == "stream-exited")
    exits_by = collections.defaultdict(collections.Counter)
    for r in log:
        if r["event"] == "stream-exited":
            exits_by[stream_experiment(r["stream"])][stop_reason(r.get("reason")) or r.get("status")] += 1
    revisions_ = collections.Counter(r["revision"][:7] for r in log if r["event"] == "stream-launched")
    completed = {}
    for r in log:
        if r["event"] == "stream-exited" and r.get("status") == "completed":
            completed[stream_experiment(r["stream"])] = r["at"][:19] + "Z"
    waits = [{"at": r["at"][:19] + "Z", "codex": r.get("remaining")} for r in log if r["event"] == "waiting-for-codex"]
    asleep = sleeps(events, rows)
    codex = codex_low(events)
    claude = claude_low(events)
    readings = {engine: [(t, r["remaining"], r["_folder"]) for t, r in events if r.get("event") == "quota"
                         and r.get("engine") == engine]
                for engine in ("codex", "claude-code")}
    folders = {}
    for config in sorted((HARNESS / "supervisor").glob("streams*.json")):
        for stream in jread(config).get("streams", []):
            folders[stream["name"]] = stream["folder"].split(".oopc/loop/harness/", 1)[-1]
    stops = owner_stops(rows)
    timeline = timeline_of(log, runs, asleep, codex, claude, completed, readings, stops, folders)
    return {"runs": [dict(r, exits=dict(r["exits"])) for r in runs], "launches": sum(launches.values()),
            "launchesByExperiment": dict(launches), "exits": dict(exits),
            "exitsByExperiment": {k: dict(v) for k, v in exits_by.items()}, "launchRevisions": dict(revisions_),
            "waitingForCodex": waits, "ownerStops": stops, "sleeps": asleep,
            "sleptMinutes": round(sum(s["minutes"] for s in asleep), 1), "codexLow": codex,
            "claudeBelowE8Floor": claude, "experimentsCompleted": completed, "timeline": timeline}


def owner_stops(rows):
    """Sessions ended by an owner's STOP file, clustered within 30 minutes."""
    clusters = []
    marked = [r["end"] for r in rows if r["outcome"] != "completed" and r.get("message") == "owner-stop"]
    killed = [r for r in rows if r["outcome"] != "completed" and "exited with -15" in (r.get("message") or "")
              and (r.get("drift") or 0) <= SLEPT and any(abs((r["end"] - t).total_seconds()) <= 120 for t in marked)]
    for r in sorted([r for r in rows if r["outcome"] != "completed" and r.get("message") == "owner-stop"] + killed,
                    key=lambda r: r["start"]):
        if clusters and (r["start"] - clusters[-1]["last"]).total_seconds() <= 1800:
            clusters[-1]["last"] = r["start"]
            clusters[-1]["sessions"] += 1
            clusters[-1]["folders"].add(r["folder"])
        else:
            clusters.append({"first": r["start"], "last": r["start"], "sessions": 1, "folders": {r["folder"]}})
    return [{"from": iso(c["first"]), "to": iso(c["last"]), "sessions": c["sessions"], "folders": sorted(c["folders"])}
            for c in clusters]


def reading(readings, at, folders=None, window=2400):
    """The last numeric quota reading at or before `at` in any folder, and whether a reading in `folders` failed (null)
    in the `window` seconds before."""
    found, failed = None, False
    for t, value, folder in readings:
        if t > at:
            break
        if value is not None:
            found = value
        elif ((at - t).total_seconds() <= window and folders is not None
              and any(folder == f or folder.startswith(f + "/") for f in folders)):
            failed = True
    return found, failed


def quota_note(readings, at, names, folders):
    mine = [folders[n] for n in names if n in folders]
    codex, failed = reading(readings["codex"], at, mine)
    note = "; Codex at %s%%" % codex
    if failed:
        note += ", a Codex reading failed (null) just before"
    if any(name.startswith("kf-e8") for name in names):
        note += ", Claude Code at %s%%" % reading(readings["claude-code"], at, mine)[0]
    return note


def timeline_of(log, runs, asleep, codex, claude, completed, readings, stops, folders):
    """A short timeline: supervisor runs, stop clusters, sleeps, Codex at its floor, experiments finishing."""
    items = []
    for s in stops:
        items.append((s["from"], "owner stop: %d sessions stopped or refused by a STOP file until %s (%s)" % (
            s["sessions"], s["to"][11:16], ", ".join(f.split("/")[-1] for f in s["folders"]))))
    for r in runs:
        items.append((r["started"], "supervisor started (%s); %d launches in this run" % (r["config"], r["launches"])))
        if r.get("stopped"):
            items.append((r["stopped"], "supervisor stopped; %d streams left running" % len(r.get("leftRunning", []))))
    clusters = []
    for r in log:
        if r["event"] != "stream-exited" or r.get("status") == "completed":
            continue
        reason = stop_reason(r.get("reason")) or r.get("status")
        at = when(r["at"])
        if clusters and clusters[-1]["reason"] == reason and (at - clusters[-1]["last"]).total_seconds() <= 1800:
            clusters[-1]["last"] = at
            clusters[-1]["streams"].append(r["stream"])
        else:
            clusters.append({"reason": reason, "first": at, "last": at, "streams": [r["stream"]]})
    for c in clusters:
        names = sorted(set(c["streams"]))
        note = ""
        if c["reason"] in ("quota", "no-eligible-engine"):
            note = quota_note(readings, c["last"], names, folders)
        items.append((iso(c["first"]), "%d stream stop%s for %s (%s%s)" % (
            len(c["streams"]), "s" if len(c["streams"]) > 1 else "", c["reason"],
            ", ".join(names[:6]) + (" ..." if len(names) > 6 else ""), note)))
    for s in asleep:
        items.append((s["from"], "machine asleep about %.0f min (to %s)" % (s["minutes"], s["to"][11:16])))
    for p in codex:
        items.append((p["from"], "Codex at or below %d%% (lowest %s%%) until %s, back to %s%%" % (
            CODEX_LOW, p["lowest"], (p["recoveredAt"] or "end")[:16], p["recoveredTo"])))
    for p in claude:
        items.append((p["from"], "Claude Code at or below E8's 40%% floor (lowest %s%%) until %s" % (
            p["lowest"], (p["recoveredAt"] or "end")[:16])))
    for key, at in completed.items():
        items.append((at, "last %s stream completed" % key))
    return [{"at": at, "event": text} for at, text in sorted(items)]


# ----- the report -----

def experiment(key, label, folders, wakes):
    rows = sessions(key, folders)
    redone = settle(rows)
    table, failures = summarize_sessions(rows, wakes)
    done, answers, checks = work(key, folders)
    value = {"key": key, "label": label, "folders": folders, "answersCompleted": answers, "checksCompleted": checks,
             "work": done, "sessions": table, "sessionsTotal": len(rows),
             "sessionsByEngine": dict(collections.Counter(r["engine"] for r in rows)),
             "failedAttempts": len(failures), "failures": failure_table(failures), "failureList": failures,
             "redoneCompletedSessions": dict(redone),
             "newTokens": sum(r.get("newTokens") or 0 for r in rows),
             "newTokensByEngine": dict(collections.Counter({e: sum(r.get("newTokens") or 0 for r in rows
                                                                    if r["engine"] == e)
                                                            for e in {r["engine"] for r in rows}})),
             "span": span(rows), "folderSpans": {name: span([r for r in rows if r["folder"] == name]) for name in folders},
             "neverStarted": sum(1 for r in rows if r["outcome"] != "completed" and not r.get("seconds")),
             "revisions": revisions(folders), "driverAttempts": driver_attempts(folders),
             "rawStreams": streams(folders),
             "stillRunning": sum(r["outcome"] == "running" for r in rows)}
    return value, rows


def totals(experiments, rows):
    table, _ = summarize_sessions(rows, [])
    failures = collections.Counter()
    ended = collections.Counter()
    for e in experiments:
        for reason, v in e["failures"].items():
            failures[reason] += v["attempts"]
            ended["retried and completed"] += v["retried and completed"]
            ended["failed for good"] += v["failed for good"]
    return {"failures": failure_table([f for e in experiments for f in e["failureList"]]),
            "failedForGood": [dict(f, experiment=e["key"]) for e in experiments for f in e["failureList"]
                              if f["ended"] == "failed for good"],
            "answersCompleted": sum(e["answersCompleted"] for e in experiments),
            "checksCompleted": sum(e["checksCompleted"] for e in experiments),
            "sessionsTotal": len(rows), "sessionsByEngine": dict(collections.Counter(r["engine"] for r in rows)),
            "sessions": table, "failedAttempts": sum(failures.values()), "failuresByReason": dict(failures),
            "failuresEnded": dict(ended), "newTokens": sum(r.get("newTokens") or 0 for r in rows),
            "newTokensByEngine": {e: sum(r.get("newTokens") or 0 for r in rows if r["engine"] == e)
                                  for e in sorted({r["engine"] for r in rows})},
            "span": span(rows), "rawStreams": sum(e["rawStreams"] for e in experiments)}


def revision():
    try:
        head = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=common.STUDY, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(Path(__file__).resolve())], cwd=common.STUDY,
                               capture_output=True, text=True, check=True).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def build():
    events = activity_events()
    everything = []
    for key, label, folders in EXPERIMENTS:
        everything += sessions(key, folders)
    located = sleeps(events, everything)
    wakes = [when(s["to"].replace("Z", "+00:00")) for s in located]
    experiments, rows = [], []
    for key, label, folders in EXPERIMENTS:
        value, got = experiment(key, label, folders, wakes)
        experiments.append(value)
        rows += got
    return {"meta": {"builder": "studies/macromolecules/analysis/accounting.py", "analysisRevision": revision(),
                     "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     "harness": str(HARNESS), "sleptThresholdSeconds": SLEPT, "codexLowPercent": CODEX_LOW},
            "experiments": experiments, "total": totals(experiments, rows), "supervisor": supervisor(events, rows)}


# ----- markdown -----

def n(x):
    if x is None:
        return "–"
    if isinstance(x, float):
        return "{:,.0f}".format(x) if abs(x) >= 100 else "{:.1f}".format(x)
    return "{:,}".format(x) if isinstance(x, int) else str(x)


def mtok(x):
    return "–" if x is None else "{:.2f} M".format(x / 1e6)


def ktok(x):
    return "–" if x is None else "{:.1f} k".format(x / 1e3)


def session_lines(table):
    lines = ["| Engine | Phase | Sessions | Completed | Failed | New tokens (total) | Median per completed session |"
             " Session hours |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in table:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["engine"], r["phase"], n(r["calls"]), n(r["completed"]), n(r["failed"]), mtok(r["newTokens"]),
            ktok(r["medianNewTokens"]), r["sessionHours"]))
    return lines


def failure_lines(failures):
    if not failures:
        return ["No failed attempt."]
    lines = ["| Reason | Attempts | Retried and completed | Failed for good | Phases | Notes |",
             "| --- | ---: | ---: | ---: | --- | --- |"]
    for reason, v in failures.items():
        notes = []
        recorded = {k: c for k, c in v["recordedAs"].items() if k != reason}
        if recorded:
            notes.append("recorded as " + ", ".join("%s %d" % kv for kv in sorted(recorded.items())))
        if v["afterWake"]:
            notes.append("%d within 2 min of waking" % v["afterWake"])
        if v["details"]:
            notes.append("; ".join("%s %d" % kv for kv in sorted(v["details"].items())))
        lines.append("| %s | %d | %d | %d | %s | %s |" % (
            reason, v["attempts"], v["retried and completed"], v["failed for good"],
            ", ".join("%s %d" % kv for kv in sorted(v["byPhase"].items())), "; ".join(notes) or ""))
    return lines


def work_line(e):
    w = e["work"]
    parts = ["%s answers and %s checks completed" % (n(e["answersCompleted"]), n(e["checksCompleted"]))]
    if w.get("driver.items"):
        parts.append("driver items %s (answers failed for good %d, checks failed for good %d; answers redone %d, "
                     "checks redone %d)" % (n(w["driver.items"]), w.get("driver.answerFailedForGood", 0),
                                            w.get("driver.checkFailedForGood", 0), w.get("driver.answersRedone", 0),
                                            w.get("driver.checksRedone", 0)))
    if w.get("cs4First.answers"):
        parts.append("cs4 first askings %d answered, %d checked" % (w["cs4First.answers"], w.get("cs4First.checks", 0)))
    if w.get("restart.tasks"):
        parts.append("tasks %s planned, %s completed, %d failed for good (%s); %d tasks asked again after a transient "
                     "failure" % (n(w["restart.tasks"]), n(w.get("restart.tasksCompleted", 0)),
                                  w.get("restart.tasksFailed", 0),
                                  ", ".join("%s %d" % (k.split(":")[1], v) for k, v in w.items()
                                            if k.startswith("restart.tasksFailed:")) or "none",
                                  w.get("restart.taskRetriesRequested", 0)))
        parts.append("sampled whole-answer checks %d (failed for good %d)" % (w.get("restart.checks", 0),
                                                                             w.get("restart.checksFailedForGood", 0)))
        parts.append("improver: %d rounds, %d proposals adopted as candidates, %d proposals that could not be applied "
                     "(asked again)" % (w.get("restart.improverRounds", 0), w.get("restart.improverProposals", 0),
                                        w.get("restart.improverNotApplicable", 0)))
    if w.get("e9Reviews"):
        parts.append("reviews of the planted store %d (%d plants judged, %d failures)" % (
            w["e9Reviews"], w.get("e9PlantsJudged", 0), w.get("e9ReviewFailures", 0)))
    if w.get("scoring.groups"):
        parts.append("blind scoring groups %d scored of %d" % (w.get("scoring.scored", 0), w["scoring.groups"]))
    return "; ".join(parts) + "."


def markdown(value):
    t, sup = value["total"], value["supervisor"]
    lines = ["# Run accounting of the Macromolecules study", "",
             "Drawn from the records only by `%s` (revision %s) on %s; no engine call. Sessions, failures and new tokens "
             "come from every workspace's token ledger (one record per engine attempt); work completed from the run "
             "records; times are UTC. A failed attempt is named `slept` when the machine slept during it or the Guard "
             "stopped it for a sleep (the reason the engine recorded is given beside it); it was \"retried and "
             "completed\" when a later attempt of the same work completed. New tokens are uncached input plus output." % (
                 value["meta"]["builder"], value["meta"]["analysisRevision"], value["meta"]["builtAt"]), "",
             "## Study total", "",
             "- %s answers and %s checks completed; %s engine sessions (%s); %s raw session streams." % (
                 n(t["answersCompleted"]), n(t["checksCompleted"]), n(t["sessionsTotal"]),
                 ", ".join("%s %s" % (k, n(v)) for k, v in sorted(t["sessionsByEngine"].items())), n(t["rawStreams"])),
             "- %d failed attempts (%s): %d retried and completed, %d failed for good." % (
                 t["failedAttempts"], ", ".join("%s %d" % kv for kv in t["failuresByReason"].items()),
                 t["failuresEnded"].get("retried and completed", 0), t["failuresEnded"].get("failed for good", 0)),
             "- New tokens %s (%s)." % (mtok(t["newTokens"]), ", ".join("%s %s" % (k, mtok(v)) for k, v in
                                                                         t["newTokensByEngine"].items())),
             "- Sessions from %s to %s (%s); the 2026-10-19 launch ran %s to %s." % (
                 t["span"]["first"], t["span"]["last"], ", ".join(t["span"]["days"]),
                 min(e["span"]["first"] for e in value["experiments"] if e["span"]["first"] >= "2026-10-19"),
                 t["span"]["last"]), ""]
    lines += ["| Experiment | Answers | Checks | Sessions (Codex / Claude Code) | Failed attempts | Failed for good |"
              " New tokens | Span (UTC) | Wall hours | Active hours | Harness revisions (runs) |",
              "| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |"]
    for e in value["experiments"]:
        bad = sum(v["failed for good"] for v in e["failures"].values())
        revs = e["revisions"]["runs"]
        lines.append("| %s | %s | %s | %s (%s / %s) | %d | %d | %s | %s to %s | %s | %s | %s |" % (
            e["key"], n(e["answersCompleted"]), n(e["checksCompleted"]), n(e["sessionsTotal"]),
            n(e["sessionsByEngine"].get("codex", 0)), n(e["sessionsByEngine"].get("claude-code", 0)),
            e["failedAttempts"], bad, mtok(e["newTokens"]), e["span"]["first"][:16], e["span"]["last"][:16],
            e["span"]["hours"], e["span"]["activeHours"],
            ", ".join("%s (%d)" % kv for kv in sorted(revs.items())) or "not recorded"))
    lines += ["", "Answers are driver answers, cs4's first askings and Part B's tasks; checks are driver checks, cs4's first "
              "askings' checks and Part B's sampled whole-answer checks. Part B's rounds: %s." % work_line(
                  next(e for e in value["experiments"] if e["key"] == "B-rounds")).split("; ", 1)[1].rstrip(".")]
    lines += ["", "Sessions and new tokens over the study, by engine and phase:", ""] + session_lines(t["sessions"])
    lines += ["", "Failed attempts over the study (%d):" % t["failedAttempts"], ""] + failure_lines(t["failures"])
    lines += ["", "Failed for good (%d): %s." % (len(t["failedForGood"]), "; ".join(
        "%s %s %s %s, %s (recorded %s, %s)" % (f["experiment"], f["at"][:16], f["phase"], f["ledger"].split("/")[1],
                                             f["reason"], f["recordedReason"], f["message"][:40].strip())
        for f in t["failedForGood"]) or "none")]
    for e in value["experiments"]:
        lines += ["", "## " + e["label"], "",
                  "Folders: %s. %s" % (", ".join("`%s`" % f for f in e["folders"]), work_line(e)), "",
                  "Ran %s to %s (%s h wall clock, %s h with a session running); harness revisions %s; code %s%s." % (
                      e["span"]["first"], e["span"]["last"], e["span"]["hours"], e["span"]["activeHours"],
                      ", ".join("%s (%d run%s)" % (k, v, "" if v == 1 else "s")
                                for k, v in sorted(e["revisions"]["runs"].items())) or "not recorded",
                      ", ".join(e["revisions"]["code"]) or "not recorded",
                      "" if e["revisions"]["allClean"] else " (a run from uncommitted code)"), ""]
        if len(e["folders"]) > 1:
            lines += ["Per folder: %s." % "; ".join("%s %s to %s" % (name.split("/")[-1], s.get("first", "–")[:16],
                                                                     s.get("last", "–")[:16])
                                                  for name, s in e["folderSpans"].items()), ""]
        lines += session_lines(e["sessions"])
        lines += ["", "Failed attempts (%d):" % e["failedAttempts"], ""] + failure_lines(e["failures"])
        if e["redoneCompletedSessions"]:
            lines += ["", "Completed sessions redone: %s." % ", ".join(
                "%s %d" % kv for kv in sorted(e["redoneCompletedSessions"].items()))]
        attempts = {k: v for k, v in e["driverAttempts"].items() if "failed" in k}
        streams_note = "raw session streams %s for %s ledger sessions, %d of which were refused before a session " \
                       "started" % (n(e["rawStreams"]), n(e["sessionsTotal"]), e["neverStarted"])
        if e["driverAttempts"]:
            lines += ["", "Cross-check, the driver items' own attempt records: %s; %s." % (
                ", ".join("%s %d" % kv for kv in sorted(attempts.items())) or "no failed attempt", streams_note)]
        else:
            lines += ["", "Cross-check: %s." % streams_note]
    lines += ["", "## The supervisor", "",
              "%d supervisor runs, %d stream launches (%s), %d exits: %s. Launch revisions: %s." % (
                  len(sup["runs"]), sup["launches"],
                  ", ".join("%s %d" % kv for kv in sorted(sup["launchesByExperiment"].items())),
                  sum(sup["exits"].values()), ", ".join("%s %d" % kv for kv in sorted(sup["exits"].items(),
                                                                                     key=lambda kv: -kv[1])),
                  ", ".join("%s %d" % kv for kv in sorted(sup["launchRevisions"].items()))), "",
              "| Supervisor run | Config | Launches | Exits by reason | Stopped |", "| --- | --- | ---: | --- | --- |"]
    for r in sup["runs"]:
        lines.append("| %s | %s | %d | %s | %s |" % (r["started"][:16], r["config"], r["launches"],
                                                    ", ".join("%s %d" % kv for kv in sorted(r["exits"].items())) or "–",
                                                    (r.get("stopped") or "–")[:16]))
    lines += ["", "Exits by experiment: %s." % "; ".join(
        "%s: %s" % (k, ", ".join("%s %d" % kv for kv in sorted(v.items()))) for k, v in sorted(sup["exitsByExperiment"].items())),
        "", "A stop for `quota` or `no-eligible-engine` (the restarts' word) is a run finding no engine it may use: Codex "
            "at its floor, Claude Code below E8's 40% floor for E8, or a Codex quota reading that failed (null), which the "
            "Guard treats as not eligible. `interrupted` stops are restarts whose session was stopped (a STOP file or a "
            "sleep); the supervisor relaunched every stopped stream after its cooldown.",
        "", "The machine slept %d times, about %.0f min in all (each a gap in every activity log inside a session that "
            "recorded the sleep). Codex was at or below %d%% of its window %d times; Claude Code was at or below E8's "
            "40%% floor %d time%s." % (len(sup["sleeps"]), sup["sleptMinutes"], CODEX_LOW, len(sup["codexLow"]),
                                        len(sup["claudeBelowE8Floor"]), "" if len(sup["claudeBelowE8Floor"]) == 1 else "s"),
        "", "Timeline (UTC):", ""]
    for item in sup["timeline"]:
        lines.append("- %s %s" % (item["at"][:16].replace("T", " "), item["event"]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    value = build()
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (args.out / "results.json").write_text(json.dumps(value, indent=1, ensure_ascii=False, default=str) + "\n")
    (args.out / "results.md").write_text(markdown(value))
    os.chmod(args.out / "results.json", 0o600)
    os.chmod(args.out / "results.md", 0o600)
    print(json.dumps({"out": str(args.out), "total": {k: v for k, v in value["total"].items() if k != "sessions"}},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
