"""Part B of the Macromolecules study, five fresh restarts (owner, 2026-10-18), pre-registered in
docs/exec-plans/active/restart-study-plan.md.

Each restart R<n> builds an ontology from an empty store with the self-improvement heuristics on, in its own folder
(`.oopc/loop/harness/2026-10-restarts/R<n>/`), as one process. Five rounds; each round:
1. tasks: the round's 100 tasks (rounds.json, drawn by make_tasks.py with the restart's seed, four of them the campaign
   questions test 1's near held-out questions were drawn from) through freeze-2's own loop under the current prompt,
   held to Codex: answered and deposited by `ask.Questions` (the narrow review policy:
   a value read in the text or a table is Added, one read off a figure, converted or combined waits for review, and 1
   in 5 Added findings is sampled), then, as the app does once an answer is delivered, its DOIs' Crossref titles applied
   and its cited sources captured (`ask.after_answer`) and its findings waiting for review reviewed in a fresh Codex
   session (`reviewer.review`); 12 tasks get a whole-answer check on Codex (`parity.check`, given the session's
   knowledge searches and web actions);
2. snapshot S<r> (S0 is the empty store);
3. improve: one Claude Code session (no web, no tools) reads the round's records and proposes one edit to the prompt
   (`old` at most 600 characters, `new` at most 1,000, as it is told); one retry with the reason if it cannot be applied;
4. dev: the current and the proposed prompt answer test 2's 30 dev questions on S<r> through driver.py (each
   question's two arms in turn, then checked together), in `devSessions` shard folders at once, and the edit is
   adopted by the owner's rule (`recursive.decide`).
Each restart evolves its own lineage P0..P5; there is no per-round held-out evaluation. After all five have finished,
`final-prepare` writes the final evaluation's driver plans: test 1's 60 held-out questions on E0 = P0 x S0 and, per
restart, P0 x S1..S5, Pk x Sk (k = 1..5; an arm whose prompt equals P0 is skipped) and P5 x S0 (skipped if P5 equals
P0), sharded by question into folders that each hold every arm, so several streams run at once.

The steps are recursive.py's, pointed at the restart's folder (`recursive.configure`). The code under test is tag
`study-freeze-2`, imported from its worktree (OOPC_STUDY_CODE); nothing runs from anything else, and PINS are asserted
at prepare and at every run, as is that neither the code under test (`oopc`, `config`) nor the harness's own study code
(`studies/` of the repository this file is in, which may be a worktree of the harness commit run with OOPC_STUDY_ROOT
pointing at the main checkout) has uncommitted changes. Each run appends both commits and the Codex floor to `runs.jsonl`
in its folder. Every snapshot's `driver.fingerprint` is recorded when it is taken (`snapshots.json`, with S0, the empty
store) and checked before a run starts, before each dev evaluation and at `final-prepare`. A refusal leaves state.json
as it was and exits non-zero, so a supervisor holds the stream rather than relaunching it.

Failures. A task, answer, check, review or improver call that fails for a TRANSIENT reason (quota, rate-limited,
not-signed-in, or interrupted: a STOP file, the Codex floor, a slept machine) stops its phase and stays to do; a rerun
resumes it. A dev decision is taken only when every dev pair is done or failed for another reason. Other failures keep
their named reason, as the driver does.

    python -B restart.py prepare --restart N [--base FOLDER] [--rounds 5] [--seed S] [--dev-sessions 2]
    python -B restart.py run --restart N [--base FOLDER]   # resumable; a STOP file in the folder stops it
    python -B restart.py status --restart N [--base FOLDER]
    python -B restart.py final-prepare [--shards 6]        # refused until all five restarts have finished
    python -B restart.py final-run --shard J [--hours 96]  # one process per shard; STOP in final/ stops every shard
    python -B restart.py final-status
"""
import argparse, concurrent.futures, functools, hashlib, json, os, re, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common and driver
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from case_studies import case_studies  # noqa: E402
from recursive import make_tasks, recursive  # noqa: E402
from oopc import ask, engines, knowledge, loop, parity, reviewer, sources  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

campaign = recursive.campaign
RESTARTS = common.run_dir("2026-10-restarts")
COUNT, ROUNDS, DEV_SESSIONS, SHARDS = 5, 5, 2, 6
EDIT_LIMITS = (600, 1000)
TRANSIENT = ("quota", "rate-limited", "not-signed-in", "interrupted")
PINS = {"tag": "1c06a7f", "prompt": "0b7bb1483235", "model": "gpt-6.1-sol", "improver": "claude-opus-5-5",
        "release": "oopc-6ad56d8b354d053bcc3cf3a1"}
RELEASES = common.ROOT  # its releases/current.json names the graph release every workspace links to
HELDOUT = make_tasks.ABLATION / "heldout.json"  # test 1's 60 held-out questions, in test 1's order
DEV = make_tasks.BASE / "dev.json"  # test 2's 30 dev questions
CAMPAIGN = make_tasks.CAMPAIGN / "questions.json"  # where the near held-out questions' parents come from
QUESTIONS = 60
PREREGISTRATION = common.ROOT / "docs/exec-plans/active/restart-study-plan.md"
HARNESS = Path(__file__).resolve().parents[3]  # the repository (or worktree) this harness runs from


class Guard(driver.Guard):
    """driver.Guard (quota floor, stop file, deadline and raw streams in `base`, and a session the machine slept through
    stopped) that also stops at the STOP file of `home`: the restart's or the final evaluation's folder, for sessions
    whose records live in one of its sub-folders."""

    def __init__(self, deadline, *args, base, home=None, **options):
        super().__init__(deadline, *args, base=base, **options)
        self.home = Path(home) if home else None

    def boundary(self):
        if self.home and (self.home / "STOP").exists():
            return "owner-stop"
        return super().boundary()


def provenance():
    """What a run runs: the commit of the code under test and of the harness, whether each is clean (`oopc` and
    `config` of the code, `studies` of the harness's own repository), and the Codex floor."""
    git = lambda cwd, *args: subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
    return {"code": git(common.CODE, "rev-parse", "HEAD"),
            "codeClean": not git(common.CODE, "status", "--porcelain", "--", "oopc", "config"),
            "harness": git(HARNESS, "rev-parse", "HEAD"),
            "harnessClean": not git(HARNESS, "status", "--porcelain", "--", "studies"), "floor": common.FLOOR}


def pinned():
    """The code under test is tag study-freeze-2 (`case_studies.frozen`), every pin holds, and neither the code nor the
    harness has uncommitted changes; returns the tag's commit and the `provenance` to record."""
    tag = case_studies.frozen()
    release = read_json(RELEASES / "releases/current.json")["release_id"]
    found = {"tag": tag[:len(PINS["tag"])], "prompt": ask.prompt_version(), "release": release,
             "model": engines.ENGINES[engines.CODEX]["model"], "improver": engines.ENGINES[engines.CLAUDE]["model"]}
    wrong = ["%s is %s, not %s" % (k, found[k], v) for k, v in PINS.items() if found[k] != v]
    if wrong:
        raise SystemExit("The restarts' pins do not hold: " + "; ".join(wrong))
    record = provenance()
    dirty = [name for name, clean in (("the code under test (oopc, config)", record["codeClean"]),
                                      ("the harness's study code (studies)", record["harnessClean"])) if not clean]
    if dirty:
        raise SystemExit("Uncommitted changes in %s; commit or remove them first." % " and ".join(dirty))
    return tag, record


def logged(path, record):
    """Append this run's provenance to runs.jsonl in `path`."""
    with open(Path(path) / "runs.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record, at=now(), pid=os.getpid())) + "\n")
    os.chmod(Path(path) / "runs.jsonl", 0o600)


# ----- snapshots -----

def recorded(base):
    path = Path(base) / "snapshots.json"
    return read_json(path) if path.exists() else {}


def record_snapshot(base, name, root):
    """Record a snapshot's fingerprint once, when it is taken (a resumed run never records it again)."""
    values = recorded(base)
    if name not in values:
        values[name] = driver.fingerprint(root)
        atomic_json(Path(base) / "snapshots.json", values, private=True)


def check_snapshots(base, names=None):
    """Refuse if a recorded snapshot changed. S0, the empty store, has no folder, and a missing store prints as an
    empty one, so S0 is checked against that."""
    values = recorded(base)
    for name in names or sorted(values):
        if name not in values:
            raise SystemExit("Snapshot %s of %s was never recorded." % (name, base))
        if driver.fingerprint(Path(base) / "snapshots" / name) != values[name]:
            raise SystemExit("Snapshot %s of %s changed since it was taken." % (name, base))
    return values


def snapshot(r):
    """Round r's snapshot S<r> (`recursive.snapshot`) and its recorded fingerprint."""
    recursive.snapshot(r)
    record_snapshot(recursive.BASE, "S%d" % r, recursive.SNAPSHOTS / ("S%d" % r))


def folder(n, base=None):
    return Path(base) if base else RESTARTS / ("R%d" % n)


def configure(base, rounds=ROUNDS):
    recursive.configure(base, rounds=range(1, rounds + 1), guard=Guard, releases=RELEASES, edit_limits=EDIT_LIMITS,
                        transient=TRANSIENT)


def transient(state):
    return ((state or {}).get("error") or {}).get("reason") in TRANSIENT


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----- prepare -----

def loop_record():
    """What freeze-2's loop does with each task as this harness runs it, for the baseline."""
    return {"settings": loop.settings(recursive.WORK), "addedAtOnce": "read",
            "reviewedFirst": sorted(k for k in knowledge.DERIVATIONS if k != "read"),
            "maxReviewAttempts": knowledge.MAX_REVIEW_ATTEMPTS, "reviewSeconds": reviewer.REVIEW_SECONDS,
            "idleSeconds": reviewer.IDLE_SECONDS, "depth": dict(ask.DEPTHS["standard"], name="standard"),
            "researchAttempts": ask.MAX_ATTEMPTS, "retryable": sorted(engines.RETRYABLE),
            "rateLimitPause": engines.RATE_LIMIT_PAUSE, "reservePercent": loop.RESERVE_PERCENT, "origin": "research",
            "engines": {"research": engines.CODEX, "review": engines.CODEX, "check": engines.CODEX,
                        "improver": engines.CLAUDE},
            "afterAnswer": "ask.after_answer: Crossref titles, then source captures", "network": sources.network_allowed(),
            "codexFloor": common.FLOOR}


def prepare(n, base=None, rounds=ROUNDS, seed=None, dev_sessions=DEV_SESSIONS, tasks=None):
    """Restart n's folder: its tasks (drawn from `seed`, default the restart's own; `tasks` gives them directly), test
    2's dev questions, an empty store linked to the graph release (S0, its fingerprint recorded), P0 and the baseline. A
    workspace is never reset."""
    tag, record = pinned()
    base = folder(n, base)
    configure(base, rounds)
    if recursive.WORK.exists():
        raise SystemExit("The restart's workspace exists; it is never reset.")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    seed = seed or make_tasks.RESTART_SEED % n
    heldout, dev = json.loads(HELDOUT.read_text()), json.loads(DEV.read_text())
    if tasks is None:
        tasks = make_tasks.restart_tasks(n, heldout, dev, json.loads(CAMPAIGN.read_text()), rounds, seed)
    if sorted({t["round"] for t in tasks}) != list(recursive.ROUNDS) or len({t["taskId"] for t in tasks}) != len(tasks):
        raise SystemExit("The tasks must cover rounds 1 to %d with unique ids." % rounds)
    path = base / "rounds.json"
    if path.exists() and json.loads(path.read_text()) != tasks:
        raise SystemExit("rounds.json exists with other tasks.")
    make_tasks.write(path, tasks)
    shutil.copyfile(DEV, base / "dev.json")  # the questions every dev decision of this restart is judged on
    (base / "dev.json").chmod(0o600)
    part = recursive.WORK.with_name("workspace.partial")  # S0: an empty store and the graph release
    shutil.rmtree(part, ignore_errors=True)
    recursive._release_link(part)
    with knowledge.connect(part):
        pass
    part.rename(recursive.WORK)
    record_snapshot(base, "S0", recursive.WORK)
    settings = loop.update_settings(recursive.WORK, {"reviewMode": "researcher", "spotCheckRate": 0.2,
                                                     "researchPerWeek": 0})
    if settings != loop.DEFAULT_SETTINGS:
        raise SystemExit("The loop's default settings are not the narrow review policy this study runs.")
    recursive.PROMPTS.mkdir(mode=0o700)
    (recursive.PROMPTS / "P0.txt").write_text(ask.RESEARCHER)
    sample = heldout[0]["question"]
    assert recursive.render(ask.RESEARCHER, sample, "standard") == ask.researcher_prompt(sample, "standard") == \
        driver.render(ask.RESEARCHER, sample, "standard")
    atomic_json(base / "baseline.json", dict(
        at=now(), restart=n, seed=seed, rounds=rounds, devSessions=dev_sessions, tag=tag, revision=record["code"],
        coreClean=record["codeClean"], harness=record["harness"], harnessClean=record["harnessClean"],
        promptVersion=ask.prompt_version(), model=engines.ENGINES[engines.CODEX]["model"],
        improverModel=engines.ENGINES[engines.CLAUDE]["model"],
        release=read_json(RELEASES / "releases/current.json")["release_id"], editLimits=list(EDIT_LIMITS),
        transient=list(TRANSIENT), minPairs=recursive.MIN_PAIRS, tokenLimit=recursive.TOKEN_LIMIT, loop=loop_record(),
        knowledge=recursive.fingerprint(recursive.WORK),
        files={"rounds.json": digest(path), "dev.json": digest(DEV), "heldout.json": digest(HELDOUT),
               "campaign questions.json": digest(CAMPAIGN) if CAMPAIGN.exists() else None,
               "preregistration": digest(PREREGISTRATION) if PREREGISTRATION.exists() else None}), private=True)
    recursive.emit("prepared", restart=n, seed=seed, tasks=len(tasks), prompt=ask.prompt_version())


# ----- 1. a round's tasks through freeze-2's own loop -----

def checked(path):
    """A whole-answer check is done: it has a verdict, or failed for a reason that is not transient."""
    if not path.exists():
        return False
    value = read_json(path)
    return "verdict" in value or not transient(value)


def forgive(root, question_id):
    """Undo the attempt freeze-2's reviewer recorded for a review that failed for a transient reason
    (`knowledge.record_review_failure` counts every failure towards the two a review gets, and after the second leaves
    its sampled findings unchecked): the review stays to do, as an answer or check that failed that way does. The
    failed attempt stays in the store's reviews table."""
    with knowledge.connect(root) as db:
        db.execute("UPDATE deposits SET review_attempts=MAX(review_attempts - 1, 0) WHERE question_id=?", (question_id,))
        attempts = db.execute("SELECT review_attempts FROM deposits WHERE question_id=?", (question_id,)).fetchone()[0]
        if attempts < knowledge.MAX_REVIEW_ATTEMPTS:
            for (identifier,) in db.execute("SELECT id FROM findings WHERE question_id=? AND status=? AND "
                                            "json_extract(detail, '$.spotCheck')='failed'",
                                            (question_id, knowledge.ACCEPTED)).fetchall():
                knowledge._set_detail(db, identifier, spotCheck="pending")


def retry(service, question_id):
    """Ask a task that failed for a transient reason again with the app's own retry (`ask.Questions.retry`), on a fresh
    trace run: freeze-2's retry reuses the failed attempt's run, which it has already finished, and the answer then
    crashes ("Cannot append access to a finished run"). The failed run stays in the trace store, named in the
    question's record."""
    path = ask.folder(recursive.WORK) / question_id / "question.json"
    item = read_json(path)
    if item.get("runId"):
        item.setdefault("failedRuns", []).append(item.pop("runId"))
        atomic_json(path, item, private=True)
    service.retry(question_id)


class Round(recursive.Round):
    """A round's tasks as freeze-2's own loop processes a question (`ask.Questions`, then what the app does once an
    answer is delivered), research, reviews and checks held to Codex, no app server. One research session at a time;
    the audit worker reviews and checks beside it, the two taking turns on the workspace's Codex lock as in the app. A
    task, review or check that fails for a transient reason stays to do and halts the round; a task failed that way is
    asked again on the rerun (`retry`)."""

    def __init__(self, number, limit=None):
        super().__init__(number, limit)
        self.after = self.folder / "after-answer"
        self.after.mkdir(exist_ok=True, mode=0o700)
        self.halt = None

    def needs_audit(self, task):
        qid, number = task["taskId"], task["number"]
        if not (self.after / ("after-%04d.json" % number)).exists() or qid in knowledge.review_queue(recursive.WORK):
            return True
        return task["checkSample"] and not checked(self.checks / ("check-%04d.json" % number))

    def finished(self, task):
        state = campaign.task_state(task["taskId"]) or {}
        if state.get("status") == "failed":
            return not transient(state)
        return state.get("status") == "completed" and not self.needs_audit(task)

    def unavailable(self, guard):
        """Halt the round unless Codex can start a session now (allowing a reading that fails for a moment)."""
        if not self.halt and not recursive.codex_ready(guard):
            self.halt = guard.boundary() or ("quota" if guard.signed(engines.CODEX) else "not-signed-in")
        return self.halt

    def audit(self, guard, task):
        """As freeze-2's app does once an answer is delivered (`ask.Questions._review_in_background`): its DOIs' Crossref
        titles and its cited sources' text (`ask.after_answer`, where the network is allowed), then its findings
        waiting for review in a fresh Codex session, a failed review tried once more as the loop does; then, for a
        sampled task, the whole-answer check. A transient failure leaves the rest to do and halts the round."""
        if self.halt:
            return
        qid, number = task["taskId"], task["number"]
        result = read_json(ask.folder(recursive.WORK) / qid / "result.json")
        marker = self.after / ("after-%04d.json" % number)
        if not marker.exists():
            allowed = sources.network_allowed()
            if allowed:
                ask.after_answer(recursive.WORK, qid, result["answer"])
            atomic_json(marker, {"at": now(), "network": allowed}, private=True)
        woke = False
        while qid in knowledge.review_queue(recursive.WORK):
            if self.unavailable(guard):
                return
            try:
                reviewer.review(recursive.WORK, qid, runner=guard, engine=engines.CODEX,
                                reserve_percent=loop.RESERVE_PERCENT)
            except engines.EngineError as error:
                recursive.emit("review-failed", task=number, engine=engines.CODEX, reason=error.reason)
                if error.reason in TRANSIENT:
                    forgive(recursive.WORK, qid)
                    if error.reason == "interrupted" and not guard.boundary() and not woke:
                        woke = True  # stopped with a slept machine, not by a STOP or the deadline: tried once more
                        continue
                    self.halt = guard.boundary() or error.reason
                    return
        path = self.checks / ("check-%04d.json" % number)
        if not task["checkSample"] or checked(path) or self.unavailable(guard):
            return
        state = campaign.task_state(qid) or {}
        failures = []
        for attempt in (1, 2):  # two attempts, as test 2 gave (each tries a crashed or invalid session twice itself)
            try:
                value = parity.check(recursive.WORK, {"id": qid, "question": task["question"]}, result["answer"],
                                     engine=engines.CODEX, runner=guard, timeout=reviewer.REVIEW_SECONDS,
                                     run_id=state.get("runId"), web=parity.web_actions(result))
                atomic_json(path, dict(value, engine=engines.CODEX, failedAttempts=failures), private=True)
                return
            except engines.EngineError as error:
                failures.append(dict(error.summary(), at=now()))
                if error.reason in TRANSIENT or attempt == 2:  # stays to do if transient, else final with its reason
                    atomic_json(path, dict(error=error.summary(), at=now(), engine=engines.CODEX,
                                           failedAttempts=failures[:-1]), private=True)
                    if error.reason in TRANSIENT:
                        self.halt = guard.boundary() or error.reason
                    return
                if self.unavailable(guard):
                    return  # the second attempt is left to the rerun

    def run(self):
        prompt = ask.prompt_version()
        if self.state.get("promptVersion") and self.state["promptVersion"] != prompt:
            raise SystemExit("The researcher prompt changed since this round started (%s, now %s)."
                             % (self.state["promptVersion"], prompt))
        self.update(status="running", pid=os.getpid(), promptVersion=prompt, startedAt=self.state.get("startedAt") or now(),
                    resumedAt=now(), planned=len(self.tasks), stopReason=None)
        guard = campaign.Guard(time.time() + campaign.WAVE_HOURS * 3600, base=campaign.BASE)
        for engine in engines.ENGINES:
            guard.quota(engine)
        service = ask.Questions(recursive.WORK, runner=guard, reviews=False)
        service.recover()  # a task left running by a stopped run is retried once, as the app does
        service.wait()
        worker = threading.Thread(target=self.auditor, args=(guard,), daemon=True, name="restart-audit")
        worker.start()
        for task in self.tasks:  # audits left from an earlier run of this round
            state = campaign.task_state(task["taskId"])
            if state and state["status"] == "completed" and self.needs_audit(task):
                self.jobs.put(task)
        stop_reason = None
        try:
            for task in self.tasks:
                state = campaign.task_state(task["taskId"])
                if state and (state["status"] == "completed" or state["status"] == "failed" and not transient(state)):
                    continue
                stop_reason = self.halt or guard.boundary()
                if stop_reason:
                    break
                if ask.prompt_version() != prompt:
                    stop_reason = "prompt-changed"
                    break
                if self.research_engine(guard) is None:
                    stop_reason = guard.boundary() or "no-eligible-engine"
                    break
                self.update(task=task["number"], engine=engines.CODEX)
                recursive.emit("task-start", task=task["number"], kind=task["kind"], revisit=task["revisit"],
                               retry=bool(state and state["status"] == "failed"))
                if state and state["status"] == "failed":  # failed for a transient reason: asked again
                    retry(service, task["taskId"])
                else:
                    service.submit(dict(question=task["question"], depth="standard", runtime=engines.CODEX,
                                        origin="research", taskId=task["taskId"], authorizeSubscription=True))
                while campaign.task_state(task["taskId"])["status"] in ("queued", "running"):
                    service.wait(timeout=2)
                    if guard.boundary():
                        engines._stop_live_workers()
                state = campaign.task_state(task["taskId"])
                recursive.emit("task-end", task=task["number"], status=state["status"], error=state.get("error"))
                if state["status"] == "completed":
                    self.jobs.put(task)  # every answer gets its after-answer step, and a review or check when due
                elif transient(state):
                    stop_reason = state["error"]["reason"]
                    break
                self.update(**self.counts())
            self.update(phase="finishing-audits", task=None)
            self.jobs.put(None)
            while worker.is_alive():
                worker.join(5)
                if guard.boundary():
                    engines._stop_live_workers()
            left = [t["number"] for t in self.tasks if not self.finished(t)]
            stop_reason = stop_reason or self.halt or ("%d tasks left to do" % len(left) if left else None)
            status = "stopped" if stop_reason else "completed"
            self.update(status=status, phase="done", stopReason=stop_reason, left=left, finishedAt=now(),
                        **self.counts())
            recursive.emit("round-" + status, round=self.number, reason=stop_reason, **self.counts())
        except BaseException as error:
            engines._stop_live_workers()
            self.update(status="stopped", phase="done", error=repr(error)[:400], finishedAt=now(), **self.counts())
            recursive.emit("round-crashed", round=self.number, error=repr(error)[:400])
            raise


# ----- 4. the dev evaluation -----

def dev_rows(r, snapshot, current, candidate, sessions=DEV_SESSIONS):
    """Round r's dev evaluation through driver.py: the current prompt (P<r-1>) and the candidate as two arms with their
    own prompt files, each on its own copy of S<r>, the questions split into `sessions` shard folders run at once.
    Rows for recursive.decide only once every pair is done or failed for a reason that is not transient (the driver
    has given each failed item one more chance; a pair still failed is a missing pair, as in test 2); until then Stop,
    and a rerun resumes the shards. Refused if S<r>, or a shard's copy of it, is not the snapshot as taken."""
    prompts = {"current": recursive.PROMPTS / ("P%d.txt" % (r - 1)), "candidate": recursive.PROMPTS / ("P%d-candidate.txt" % r)}
    assert [recursive.version(p.read_text()) for p in prompts.values()] == [recursive.version(current),
                                                                            recursive.version(candidate)]
    taken = check_snapshots(recursive.BASE, ["S%d" % r])["S%d" % r]
    questions = json.loads((recursive.BASE / "dev.json").read_text())
    shards = []
    for j in range(sessions):
        shard = recursive.EVAL / ("round-%d" % r) / "dev" / ("shard-%d" % (j + 1))
        arms = [{"name": name, "kind": "researcher", "prompt": str(path),
                 "root": driver.workspace(shard, name, releases=RELEASES, store=snapshot)} for name, path in prompts.items()]
        plan = driver.prepare(shard, "%s-round-%d-dev-%d" % (recursive.BASE.name, r, j + 1), questions[j::sessions], arms)
        if any(plan["stores"][name] != taken for name in prompts):
            raise SystemExit("A dev arm's store in %s is not snapshot S%d as taken." % (shard, r))
        shards.append(shard)
    deadline = time.time() + 24 * 3600
    with concurrent.futures.ThreadPoolExecutor(max_workers=sessions) as pool:
        states = list(pool.map(lambda shard: driver.run(shard, runner=Guard(deadline, base=shard, home=recursive.BASE)),
                               shards))
    stopped = sorted({s.get("stopReason") or s["status"] for s in states if s["status"] != "completed"})
    if stopped:
        raise recursive.Stop("round %d dev stopped (%s)" % (r, ", ".join(stopped)))
    rows, left = [], 0
    for shard in shards:
        for index, question in enumerate(read_json(shard / "plan.json")["questions"]):
            items = {name: driver._item(shard, index, question, name) for name in prompts}
            left += sum(((item.get(part) or {}).get("error") or {}).get("reason") in TRANSIENT
                        for item in items.values() for part in ("answer", "check"))
            rows.append(dict({"id": question["id"], "stratum": question.get("stratum")},
                             **{name: recursive.arm_row(item.get("answer"), item.get("check")) for name, item in items.items()}))
    if left:
        raise recursive.Stop("round %d dev: %d answers or checks failed for a transient reason" % (r, left))
    return rows


# ----- a restart -----

def phases(sessions):
    """A restart's phases in order, as recursive.run takes them: per round its tasks, snapshot and dev decision."""
    evaluate = functools.partial(dev_rows, sessions=sessions)
    for r in recursive.ROUNDS:
        yield "round-%d-tasks" % r, functools.partial(recursive.run_tasks, r, Round), False
        yield "round-%d-snapshot" % r, functools.partial(snapshot, r), False
        yield "round-%d-dev" % r, functools.partial(recursive.dev, r, evaluate), False


def run(n, base=None):
    """Restart n from where it stopped; returns its state. Every refusal (a pin, uncommitted changes, the freeze
    worktree, P0 or the model since prepare, a changed snapshot) comes before state.json is touched."""
    tag, record = pinned()
    base = folder(n, base)
    baseline = read_json(base / "baseline.json")
    if baseline["tag"] != tag:
        raise SystemExit("The restart was prepared from another commit of the tag.")
    configure(base, baseline["rounds"])
    recursive.unchanged(baseline)
    check_snapshots(base)
    logged(base, record)
    path = base / "state.json"
    if path.exists():  # a resumed restart's state names only this run's stop; earlier stops are in activity.jsonl
        atomic_json(path, {k: v for k, v in read_json(path).items() if k not in ("stopReason", "stoppedAt", "error")},
                    private=True)
    recursive.run(phases(baseline["devSessions"]), name="restart")
    return read_json(path)


def status(n, base=None):
    base = folder(n, base)
    baseline = read_json(base / "baseline.json") if (base / "baseline.json").exists() else {}
    configure(base, baseline.get("rounds", ROUNDS))
    recursive.status()
    for r in recursive.ROUNDS:
        path = recursive.EVAL / ("round-%d" % r) / "dev" / "decision.json"
        if path.exists():
            value = read_json(path)
            print("round", r, "dev", {k: value.get(k) for k in ("adopted", "reason", "pairs", "adoptedVersion")})


# ----- the final evaluation -----

def final_arms(bases):
    """The final evaluation's arms in order, as (name, store or None, prompt file or None): E0, then per restart P0 x S1..
    S<rounds>, Pk x Sk (skipping an arm whose prompt equals P0) and P<rounds> x S0 (skipped if it equals P0). P0 is the
    code's own prompt, which every restart started from; S0 is an empty store."""
    arms = [("E0", None, None)]
    for n, base in bases.items():
        rounds = read_json(base / "baseline.json")["rounds"]
        prompts = {k: base / "prompts" / ("P%d.txt" % k) for k in range(rounds + 1)}
        versions = {k: recursive.version(path.read_text()) for k, path in prompts.items()}
        if versions[0] != ask.prompt_version():
            raise SystemExit("R%d did not start from the code's prompt." % n)
        stores = {k: base / "snapshots" / ("S%d" % k) for k in range(1, rounds + 1)}
        arms += [("R%d-P0-S%d" % (n, k), stores[k], None) for k in range(1, rounds + 1)]
        arms += [("R%d-P%d-S%d" % (n, k, k), stores[k], prompts[k]) for k in range(1, rounds + 1) if versions[k] != versions[0]]
        if versions[rounds] != versions[0]:
            arms.append(("R%d-P%d-S0" % (n, rounds), None, prompts[rounds]))
    return arms


def final_prepare(shards=SHARDS, base=None):
    """The final evaluation's driver plans, one per shard folder (`shard-<j>`, questions j, j + shards, ...), each with
    every arm on its own copies of the stores; refused until every restart has finished, and if a snapshot, or an
    arm's copy of one, is not the snapshot as taken."""
    tag, provenance_ = pinned()
    bases = {n: RESTARTS / ("R%d" % n) for n in range(1, COUNT + 1)}
    unfinished = ["R%d" % n for n, b in bases.items()
                  if not (b / "state.json").exists() or read_json(b / "state.json").get("status") != "completed"]
    if unfinished:
        raise SystemExit("The final evaluation waits for every restart to finish: %s not finished." % ", ".join(unfinished))
    taken = {n: check_snapshots(b, ["S%d" % k for k in range(read_json(b / "baseline.json")["rounds"] + 1)])
             for n, b in bases.items()}
    base = Path(base or RESTARTS / "final")
    record = base / "final.json"
    if record.exists() and read_json(record)["shards"] != shards:
        raise SystemExit("The final evaluation was prepared with %d shards." % read_json(record)["shards"])
    questions = json.loads(HELDOUT.read_text())
    if len(questions) != QUESTIONS:
        raise SystemExit("Test 1's held-out set has %d questions, not %d." % (len(questions), QUESTIONS))
    arms = final_arms(bases)
    for j in range(shards):
        shard = base / ("shard-%d" % (j + 1))
        plan = driver.prepare(shard, "restarts-final-%d" % (j + 1), questions[j::shards], [
            dict({"name": name, "kind": "researcher", "root": driver.workspace(shard, name, releases=RELEASES, store=store)},
                 **({"prompt": str(prompt)} if prompt else {})) for name, store, prompt in arms])
        for name, store, _ in arms:  # each arm's copy is its snapshot as taken (E0 and P5 x S0: the empty store, S0)
            n, k = map(int, re.fullmatch(r"R(\d+)-P\d+-S(\d+)", name).groups()) if name != "E0" else (min(taken), 0)
            if plan["stores"][name] != taken[n]["S%d" % k]:
                raise SystemExit("Arm %s in %s is not on snapshot S%d of R%d as taken." % (name, shard, k, n))
    if not record.exists():
        atomic_json(record, {"at": now(), "tag": tag, "provenance": provenance_, "shards": shards,
                             "questions": len(questions),
                             "arms": [{"name": name, "store": str(store) if store else None,
                                       "promptVersion": recursive.version(prompt.read_text()) if prompt else ask.prompt_version()}
                                      for name, store, prompt in arms]}, private=True)
    return arms


def final_run(shard, hours=96, base=None):
    """One shard of the final evaluation through driver.run; a STOP file in the shard or in final/ stops it. Each run's
    provenance goes to the shard's runs.jsonl."""
    _, record = pinned()
    base = Path(base or RESTARTS / "final")
    folder_ = base / ("shard-%d" % shard)
    logged(folder_, record)
    return driver.run(folder_, runner=Guard(time.time() + hours * 3600, base=folder_, home=base))


def final_status(base=None):
    base = Path(base or RESTARTS / "final")
    for shard in sorted(base.glob("shard-*")):
        state = read_json(shard / "state.json") if (shard / "state.json").exists() else {}
        done = sum(1 for _ in (shard / "items").glob("*.json")) if (shard / "items").exists() else 0
        print(shard.name, {k: state.get(k) for k in ("status", "reached", "stopReason", "updatedAt")}, "items", done)


def locked_run(path, work):
    """`work()` under the runner lock `path`, so two processes never run one folder; SIGTERM interrupts it."""
    import fcntl
    lock = open(path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another runner is active in %s." % path.parent)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("runner terminated")))
    return work()


def main():
    parser = argparse.ArgumentParser(description="Part B: five fresh restarts and their final evaluation.")
    parser.add_argument("command", choices=["prepare", "run", "status", "final-prepare", "final-run", "final-status"])
    parser.add_argument("--restart", type=int, choices=range(1, COUNT + 1))
    parser.add_argument("--base", help="The restart's folder (default .oopc/loop/harness/2026-10-restarts/R<n>)")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--seed", help="The task seed (default oopc-restart-2026-10-18-R<n>)")
    parser.add_argument("--dev-sessions", type=int, default=DEV_SESSIONS, help="Dev sessions at once, fixed at prepare")
    parser.add_argument("--shards", type=int, default=SHARDS, help="Final-evaluation shard folders")
    parser.add_argument("--shard", type=int, help="The final-evaluation shard to run")
    parser.add_argument("--hours", type=float, default=96, help="A final-evaluation shard's deadline")
    args = parser.parse_args()
    if args.command in ("prepare", "run", "status") and not args.restart:
        parser.error("--restart is required")
    if args.command == "prepare":
        prepare(args.restart, args.base, args.rounds, args.seed, args.dev_sessions)
    elif args.command == "run":
        base = folder(args.restart, args.base)
        if not (base / "baseline.json").exists():
            parser.error("R%d is not prepared (%s)" % (args.restart, base))
        print(locked_run(base / "runner.lock", lambda: run(args.restart, base)))
    elif args.command == "status":
        status(args.restart, args.base)
    elif args.command == "final-prepare":
        print(len(final_prepare(args.shards)), "arms")
    elif args.command == "final-run":
        if not args.shard:
            parser.error("--shard is required")
        shard = RESTARTS / "final" / ("shard-%d" % args.shard)
        print(locked_run(shard / "runner.lock", lambda: final_run(args.shard, args.hours)))
    else:
        final_status()


if __name__ == "__main__":
    main()
