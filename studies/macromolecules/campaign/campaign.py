"""Owner-approved campaign (2026-10-10): 800 standard-depth tasks in three waves through the core loop, on one
private workspace whose knowledge grows from wave to wave. Private; no core code, prompt or policy changes happen
here, and nothing is merged into the main store.

    python campaign.py prepare            # once: the workspace, from the 200-task run's workspace
    python campaign.py run --wave 1       # resumable; stops on STOP, a prompt change, no engine, or 48 h
    python campaign.py status

Research prefers Codex (10% floor, 2% buffer) and falls back to Claude below it. Reviews run in a fresh Codex session
(owner decision 2026-10-11: Claude could not open 41% of cited sources); a review retry avoids the engine that just
failed. Whole-answer checks prefer the engine that did not write the answer. Claude's binding limit is its 5-hour
session window: when it runs out, Claude is rechecked after a cooldown. Claude is rechecked after a cooldown
instead of being dropped for the rest of a wave after one quota failure. Every engine call is recorded by the core
ledger in the workspace (`.oopc/loop/calls/`); this driver adds quota readings, interruptions and raw streams.

Ran in `.oopc/loop/harness/2026-10-campaign/` (its records are still there); moved to the repository on 2026-10-13
unchanged except imports and paths. Its Guard and emit moved to `common.py`, so later harnesses need not load this file.
"""
import argparse, json, os, queue, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, Guard, emit as _emit, run_dir  # noqa: E402  (common puts CODE first on sys.path)
from oopc import ask, engines, knowledge, loop, parity, reviewer, server  # noqa: E402
from oopc.util import atomic_json, now, read_json, resolve_release  # noqa: E402

BASE = run_dir("2026-10-campaign")
WORK = BASE / "workspace"
SEED_WORKSPACE = run_dir("2026-10-03-200") / "workspace"

WAVE_HOURS = 48
PORT = 8766


def save(path, value):
    atomic_json(path, value, private=True)


def emit(event, **fields):
    _emit(BASE, event, **fields)  # common.emit, into this module's BASE as when it was defined here


def questions():
    return json.loads((BASE / "questions.json").read_text())


def task_state(task_id):
    path = ask.folder(WORK) / task_id / "question.json"
    return read_json(path) if path.exists() else None


def prepare():
    if WORK.exists():
        raise SystemExit("The campaign workspace exists; it is never reset.")
    shutil.copytree(SEED_WORKSPACE, WORK, symlinks=True)
    WORK.chmod(0o700)
    # Graph polymer ids for findings named with a grade number (EVOH44, PHBV28), as new deposits now get them.
    filled = 0
    with knowledge.connect(WORK) as db:
        for row in db.execute("SELECT id, material, statement FROM findings WHERE COALESCE(subject, '')=''").fetchall():
            subject = knowledge.infer_subject(WORK, {"material": row["material"], "statement": row["statement"]})
            if subject:
                db.execute("UPDATE findings SET subject=? WHERE id=?", (subject, row["id"]))
                filled += 1
    loop.update_settings(WORK, {"reviewMode": "researcher", "spotCheckRate": 0.2, "researchPerWeek": 0})
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "oopc"], cwd=CODE, text=True).strip()
    save(BASE / "baseline.json", dict(at=now(), revision=revision, coreClean=not dirty, promptVersion=ask.prompt_version(),
                                     settings=loop.settings(WORK), knowledge=knowledge.summary(WORK),
                                     subjectsFilled=filled, seededFrom=str(SEED_WORKSPACE.relative_to(BASE.parent))))
    emit("prepared", subjectsFilled=filled, knowledge=knowledge.summary(WORK))


class Wave:
    def __init__(self, number, limit=None):
        self.number = number
        self.folder = BASE / "waves" / ("wave-%d" % number)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.checks = self.folder / "checks"
        self.checks.mkdir(exist_ok=True, mode=0o700)
        self.tasks = [t for t in questions() if t["wave"] == number]
        self.limit = limit
        state_path = self.folder / "state.json"
        self.state = read_json(state_path) if state_path.exists() else {}
        self.lock = threading.RLock()
        self.jobs = queue.Queue()

    def update(self, **values):
        with self.lock:
            self.state.update(values, updatedAt=now())
            save(self.folder / "state.json", self.state)

    def research_engine(self, guard):
        return guard.choose(engines.CODEX)

    def audit(self, guard, task):
        """Review the answer's flagged and sampled findings, then check the whole answer if it is in the sample."""
        qid = task["taskId"]
        producer = (task_state(qid) or {}).get("engine")
        attempts = 0
        while qid in knowledge.review_queue(WORK) and not guard.boundary() and attempts < 3:
            attempts += 1
            # Reviews run in a fresh Codex session (owner, 2026-10-11): in wave 2 Claude could not open 41% of the
            # cited sources (publisher 403s, compressed PDFs) against about 5% for Codex. A retry avoids the engine
            # that just failed.
            failed = knowledge.failed_review_engine(WORK, qid)
            engine = guard.choose(engines.CLAUDE if failed == engines.CODEX else engines.CODEX, avoid=failed)
            if engine is None:
                emit("review-deferred", task=task["number"], reason="no-eligible-engine")
                return
            try:
                reviewer.review(WORK, qid, runner=guard, engine=engine)
            except engines.EngineError as error:
                emit("review-failed", task=task["number"], engine=engine, reason=error.reason)
        path = self.checks / ("check-%04d.json" % task["number"])
        if not task["checkSample"] or (path.exists() and "verdict" in read_json(path)):
            return
        result = read_json(ask.folder(WORK) / qid / "result.json")["answer"]
        sources = parity.resolve_sources(WORK, result.get("citations"))
        save(self.checks / ("check-input-%04d.json" % task["number"]),
             dict(at=now(), question=task["question"], answer=result.get("answer"), sources=sources))
        for attempt in range(2):
            engine = guard.choose(engines.CLAUDE if producer == engines.CODEX else engines.CODEX, avoid=producer)
            if engine is None or guard.boundary():
                save(path, dict(error={"reason": "quota", "message": "No eligible engine"}, at=now()))
                return
            try:
                checked = reviewer.check_answer(task["question"], result.get("answer"), sources, engine=engine,
                                                runner=guard, root=WORK, owner=qid)
                save(path, dict(checked, at=now(), attempt=attempt + 1, engine=engine))
                return
            except engines.EngineError as error:
                save(path, dict(error=error.summary(), at=now(), attempt=attempt + 1, engine=engine))
                if not (error.retryable or error.reason in ("timeout", "quota", "not-signed-in")):
                    return

    def auditor(self, guard):
        while True:
            task = self.jobs.get()
            try:
                if task is None:
                    return
                self.update(auditTask=task["number"])
                self.audit(guard, task)
            except Exception as error:  # Never stop the wave for one audit; record it.
                emit("audit-crashed", task=task and task["number"], error=repr(error)[:400])
            finally:
                self.update(auditTask=None, auditsWaiting=self.jobs.qsize())
                self.jobs.task_done()

    def needs_audit(self, task):
        qid = task["taskId"]
        if qid in knowledge.review_queue(WORK):
            return True
        path = self.checks / ("check-%04d.json" % task["number"])
        return task["checkSample"] and not (path.exists() and "verdict" in read_json(path))

    def run(self):
        prompt = ask.prompt_version()
        if self.state.get("promptVersion") and self.state["promptVersion"] != prompt:
            raise SystemExit("The researcher prompt changed since this wave started (%s, now %s); start a new wave."
                             % (self.state["promptVersion"], prompt))
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
        self.update(status="running", pid=os.getpid(), promptVersion=prompt, startedAt=self.state.get("startedAt") or now(),
                    resumedAt=now(), revision=self.state.get("revision") or revision, planned=len(self.tasks))
        guard = Guard(time.time() + WAVE_HOURS * 3600, base=BASE)
        for engine in engines.ENGINES:
            guard.quota(engine)
        service = ask.Questions(WORK, runner=guard, reviews=False)
        service.recover()  # A task left running by a stopped driver is retried once.
        service.wait()
        web = server.make_server(WORK, resolve_release(WORK), PORT, task_service=service, loop_runner=guard)
        threading.Thread(target=web.serve_forever, daemon=True, name="campaign-app").start()
        worker = threading.Thread(target=self.auditor, args=(guard,), daemon=True, name="campaign-audit")
        worker.start()
        for task in self.tasks:  # Audits left from an earlier run of this wave.
            state = task_state(task["taskId"])
            if state and state["status"] == "completed" and self.needs_audit(task):
                self.jobs.put(task)
        stop_reason, started = None, 0
        try:
            for task in self.tasks:
                state = task_state(task["taskId"])
                if state and state["status"] in ("completed", "failed"):
                    continue
                if self.limit is not None and started >= self.limit:
                    stop_reason = "limit"
                    break
                stop_reason = guard.boundary()
                if stop_reason:
                    break
                if ask.prompt_version() != prompt:
                    stop_reason = "prompt-changed"
                    break
                engine = self.research_engine(guard)
                if engine is None:
                    stop_reason = "no-eligible-engine"
                    break
                started += 1
                self.update(task=task["number"], engine=engine)
                emit("task-start", task=task["number"], engine=engine, kind=task["kind"], revisit=task["revisit"])
                service.submit(dict(question=task["question"], depth="standard", runtime=engine, origin="research",
                                    taskId=task["taskId"], authorizeSubscription=True))
                while task_state(task["taskId"])["status"] in ("queued", "running"):
                    service.wait(timeout=2)
                    if guard.boundary():
                        engines._stop_live_workers()
                state = task_state(task["taskId"])
                emit("task-end", task=task["number"], status=state["status"], error=state.get("error"))
                if state["status"] == "completed" and self.needs_audit(task):
                    self.jobs.put(task)
                self.update(**self.counts())
            self.update(phase="finishing-audits", task=None, stopReason=stop_reason)
            self.jobs.put(None)
            while worker.is_alive():
                worker.join(5)
                if guard.boundary():
                    engines._stop_live_workers()
            status = "stopped" if stop_reason and stop_reason != "limit" else "paused" if stop_reason else "completed"
            if status == "completed" and any((task_state(t["taskId"]) or {}).get("status") != "completed" and
                                             (task_state(t["taskId"]) or {}).get("status") != "failed" for t in self.tasks):
                status = "stopped"
            self.update(status=status, phase="done", finishedAt=now(), **self.counts())
            for engine in engines.ENGINES:
                guard.quota(engine)
            emit("wave-" + status, wave=self.number, reason=stop_reason, **self.counts())
        except BaseException as error:
            engines._stop_live_workers()
            self.update(status="stopped", phase="done", error=repr(error)[:400], finishedAt=now(), **self.counts())
            emit("wave-crashed", wave=self.number, error=repr(error)[:400])
            raise
        finally:
            web.shutdown()
            web.server_close()

    def counts(self):
        states = [(task_state(t["taskId"]) or {}).get("status", "unattempted") for t in self.tasks]
        return dict(completed=states.count("completed"), failed=states.count("failed"),
                    unattempted=states.count("unattempted"),
                    checks=len([p for p in self.checks.glob("check-0*.json") if "verdict" in read_json(p)]))


def status():
    for path in sorted((BASE / "waves").glob("wave-*/state.json")):
        state = read_json(path)
        print(path.parent.name, {k: state.get(k) for k in ("status", "phase", "task", "completed", "failed",
                                                           "unattempted", "checks", "stopReason", "updatedAt")})
    if WORK.exists():
        print("knowledge", knowledge.summary(WORK))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    run = sub.add_parser("run")
    run.add_argument("--wave", type=int, required=True)
    run.add_argument("--limit", type=int, help="Start at most this many new tasks, then finish their audits")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "run":
        if not WORK.exists():
            raise SystemExit("Run prepare first.")
        lock = open(BASE / "runner.lock", "w")
        import fcntl
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another campaign runner is active.")
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("runner terminated")))
        Wave(args.wave, args.limit).run()
    else:
        status()


if __name__ == "__main__":
    main()
