"""Private buffered subscription guard, reused from the validated observation.

Ran in `.oopc/loop/harness/2026-10-03-200/` and still writes there; moved to the repository on 2026-10-13 unchanged
except imports and paths."""
import datetime as dt
import json, os, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402  (common puts CODE first on sys.path)
from oopc import engines
from oopc.util import atomic_json, now
BASE = run_dir("2026-10-03-200")
DEADLINE = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=48)
FLOOR, BUFFER = 10, 2
def save(name, value):
    atomic_json(BASE / name, value, private=True)

def emit(event, **fields):
    path = BASE / "activity.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(at=now(), event=event, **fields), ensure_ascii=False)+"\n")
    os.chmod(path, 0o600)
    print(now(), event, json.dumps(fields, ensure_ascii=False), flush=True)

def seconds_left():
    return (DEADLINE - dt.datetime.now(dt.timezone.utc)).total_seconds()

class Guard:
    def __init__(self, read_quota=engines.read_quota, run_session=engines.run_session):
        self.read_quota, self.run_session = read_quota, run_session
        self.codex_suspended = None
        self.claude_exhausted = False
        self.last_quota = {}
        self.max_codex_cost = 2
        self.calls = []
        self.poll_seconds = 30
        self.context = threading.local()
        self.phase, self.number = "setup", None
        self.engine_locks = {engine:threading.Lock() for engine in engines.ENGINES}
        self.records_lock = threading.RLock()

    @property
    def phase(self):
        return getattr(self.context,"phase","setup")

    @phase.setter
    def phase(self,value):
        self.context.phase=value

    @property
    def number(self):
        return getattr(self.context,"number",None)

    @number.setter
    def number(self,value):
        self.context.number=value

    def record_call(self,call,**fields):
        with self.records_lock:
            call.update(fields)
            save("calls.json",self.calls)

    def call_snapshot(self):
        with self.records_lock:
            return json.loads(json.dumps(self.calls))

    def quota_snapshot(self):
        with self.records_lock:
            return json.loads(json.dumps(self.last_quota))

    def quota(self, engine):
        value = self.read_quota(engine)
        if engine == engines.CODEX and value.get("remainingPercent") is None:
            value = self.read_quota(engine)
        with self.records_lock:
            self.last_quota[engine] = value
        emit("quota", engine=engine, reading=value)
        return value

    def launch_margin(self):
        return max(FLOOR+BUFFER+3, FLOOR+BUFFER+self.max_codex_cost*1.5+1)

    def boundary(self):
        if (BASE/"STOP").exists():
            return "owner-stop"
        if seconds_left() <= 20:
            return "run-deadline"
        return None

    def eligible(self, engine):
        if self.boundary():
            return False
        if engine == engines.CODEX:
            if self.codex_suspended:
                return False
            quota = self.quota(engine)
            remaining = quota.get("remainingPercent")
            if remaining is None:
                self.codex_suspended = "quota-unavailable"
                return False
            if remaining <= self.launch_margin():
                self.codex_suspended = "reserve-launch-margin"
                return False
            return engines.signed_in(engine)
        if self.claude_exhausted or not engines.signed_in(engine):
            return False
        quota = self.quota(engine)
        if quota.get("remainingPercent") is not None and quota["remainingPercent"] <= 0:
            self.claude_exhausted = True
            return False
        return True

    def choose(self, preferred):
        other = engines.CLAUDE if preferred == engines.CODEX else engines.CODEX
        return next((engine for engine in (preferred, other) if self.eligible(engine)), None)

    def __call__(self, engine, prompt, schema, **options):
        # Every model call, including reviews, answer checks and the report, comes here.
        # One session per subscription engine. Research and audits may overlap on
        # different engines; two Codex sessions never race the shared reserve.
        with self.engine_locks[engine]:
            boundary = self.boundary()
            if boundary:
                raise engines.EngineError("interrupted", boundary)
            if not self.eligible(engine):
                raise engines.EngineError("quota", self.codex_suspended or "No available subscription allowance")
            before = self.last_quota.get(engine, {}).get("remainingPercent")
            with self.records_lock:
                index = len(self.calls)+1
                call = dict(index=index, question=self.number, phase=self.phase, engine=engine,
                            startedAt=now(), quotaBefore=self.last_quota.get(engine))
                self.calls.append(call)
                save("calls.json", self.calls)
            stop, interrupted = threading.Event(), []
            clock = time.monotonic()
            progress = options.pop("progress", None)
            raw_path = BASE/"streams"/("%04d-%s.jsonl" % (index, engine))
            raw_path.parent.mkdir(exist_ok=True, mode=0o700)

            def watch():
                while not stop.wait(self.poll_seconds):
                    reason = self.boundary()
                    if not reason and engine == engines.CODEX:
                        quota = self.quota(engine)
                        remaining = quota.get("remainingPercent")
                        if remaining is None:
                            reason = "quota-unavailable"
                        elif remaining <= FLOOR+BUFFER:
                            reason = "reserve-floor-buffer"
                    if reason:
                        interrupted.append(reason)
                        if engine == engines.CODEX:
                            self.codex_suspended = reason
                        emit("interrupt", engine=engine, reason=reason, call=index)
                        engines._stop_live_workers()  # Only workers owned by this runner process.
                        return

            monitor = threading.Thread(target=watch, daemon=True)
            monitor.start()
            timeout = min(options.pop("timeout", 600), max(1, int(seconds_left())))
            try:
                with open(raw_path, "w", encoding="utf-8") as raw:
                    os.chmod(raw_path, 0o600)
                    def on_line(line):
                        raw.write(line)
                        raw.flush()
                        if progress:
                            progress(line)
                    result = self.run_session(engine, prompt, schema, progress=on_line, timeout=timeout, **options)
                self.record_call(call,outcome="completed",usage=result.get("usage",{}),
                                 agentSeconds=result.get("agentSeconds"))
                save("call-%04d-result.json" % index, result)
                return result
            except engines.EngineError as error:
                if interrupted:
                    error = engines.EngineError("quota" if interrupted[-1].startswith(("reserve", "quota"))
                                                else "interrupted", interrupted[-1],
                                                seconds=error.seconds, usage=error.usage)
                if engine == engines.CLAUDE and error.reason in {"quota", "not-signed-in"}:
                    self.claude_exhausted = True
                if engine == engines.CODEX and error.reason == "quota":
                    self.codex_suspended = "quota"
                self.record_call(call,outcome="failed",error=error.summary(),usage=error.usage)
                raise error
            finally:
                stop.set()
                monitor.join(45)
                finished_at,wall_seconds=now(),round(time.monotonic()-clock,2)
                after = self.quota(engine)
                if engine == engines.CODEX and before is not None and after.get("remainingPercent") is not None:
                    self.max_codex_cost = max(self.max_codex_cost, before-after["remainingPercent"])
                self.record_call(call,finishedAt=finished_at,wallSeconds=wall_seconds,quotaAfter=after)
                emit("call-finished", index=index, phase=call["phase"], question=call["question"],
                     engine=engine, outcome=call.get("outcome"), wallSeconds=call["wallSeconds"])

