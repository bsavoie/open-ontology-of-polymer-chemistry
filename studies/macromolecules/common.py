"""Paths and the shared engine guard of the Macromolecules study's private harness (moved to the repository 2026-10-13).

Every study script imports this module before any `oopc` import. It puts CODE first on sys.path and names the private
folder each script reads and writes. Records never live in the repository: they stay under `.oopc/` (git-ignored).

- ROOT: the repository root, for data (the live store, releases, `.oopc/` records, the plans): $OOPC_STUDY_ROOT if set
  (so a git worktree of the study code can read the main checkout's private records), else this file's repository.
- CODE: the oopc code to import: $OOPC_STUDY_CODE if set, else the study freeze worktree `.oopc/study/freeze` (tag
  `study-freeze`) if it exists, else ROOT.
- FLOOR: the Codex quota floor (percent of the weekly window) below which a Guard starts no session and stops a running
  one at FLOOR + BUFFER: $OOPC_STUDY_CODEX_FLOOR if set, else 10. The owner allowed Codex to be maxed out for the
  2026-10-18 runs, which set it to 0.
- CLAUDE_FLOOR: the Claude Code quota (percent) at or below which a Guard starts no Claude session:
  $OOPC_STUDY_CLAUDE_FLOOR if set, else 0. E8's researcher arms run with a higher floor, so they cannot use up the
  Claude window that Part B's improver and the blind scoring need.
- run_dir(name): ROOT/.oopc/loop/harness/<name>, an experiment's private folder.
- analysis_dir(name): ROOT/.oopc/study/analysis/<name>, a records analysis's private outputs.
- Guard and emit: moved from the campaign driver (`.oopc/loop/harness/2026-10-campaign/campaign.py`), unchanged except
  that the run folder they write to (stop file, raw streams, activity log) is passed as `base`; there it was the
  campaign module's BASE, which every later harness reassigned to its own folder after loading the driver.
"""
import json, os, sys, threading, time
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ROOT = (Path(os.environ["OOPC_STUDY_ROOT"]).resolve() if os.environ.get("OOPC_STUDY_ROOT")
        else STUDY.parents[1])
FREEZE = ROOT / ".oopc/study/freeze"
CODE = (Path(os.environ["OOPC_STUDY_CODE"]).resolve() if os.environ.get("OOPC_STUDY_CODE")
        else FREEZE if FREEZE.exists() else ROOT)
sys.path[:] = [str(CODE)] + [p for p in sys.path if p != str(CODE)]
from oopc import engines  # noqa: E402
from oopc.util import now  # noqa: E402

FLOOR, BUFFER = int(os.environ.get("OOPC_STUDY_CODEX_FLOOR", "10")), 2
CLAUDE_FLOOR = int(os.environ.get("OOPC_STUDY_CLAUDE_FLOOR", "0"))
CLAUDE_COOLDOWN = 1800


def run_dir(name):
    return ROOT / ".oopc/loop/harness" / name


def analysis_dir(name):
    return ROOT / ".oopc/study/analysis" / name


def emit(base, event, **fields):
    path = Path(base) / "activity.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(at=now(), event=event, **fields), ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)
    print(now(), event, json.dumps(fields, ensure_ascii=False)[:300], flush=True)


class Guard:
    """Every engine call of the campaign: eligibility, quota floor, stop file, deadline and raw streams."""

    def __init__(self, deadline, read_quota=engines.read_quota, run_session=engines.run_session, signed=engines.signed_in,
                 *, base):
        self.deadline, self.read_quota, self.run_session, self.signed = deadline, read_quota, run_session, signed
        self.base = Path(base)
        self.claude_failed_at = 0.0
        self.max_codex_cost = 2
        self.quota_seen = {}
        self.lock = threading.RLock()
        self.streams = self.base / "streams"
        self.streams.mkdir(exist_ok=True, mode=0o700)
        self.count = len(list(self.streams.glob("*.jsonl")))

    def quota(self, engine):
        value = self.read_quota(engine)
        if value.get("remainingPercent") is None:
            value = self.read_quota(engine)
        with self.lock:
            self.quota_seen[engine] = value
        emit(self.base, "quota", engine=engine, remaining=value.get("remainingPercent"))
        return value

    def boundary(self):
        if (self.base / "STOP").exists():
            return "owner-stop"
        if time.time() > self.deadline:
            return "wave-deadline"
        return None

    def margin(self):
        return max(FLOOR + BUFFER + 3, FLOOR + BUFFER + self.max_codex_cost * 1.5 + 1)

    def eligible(self, engine):
        if self.boundary() or not self.signed(engine):
            return False
        if engine == engines.CLAUDE and time.time() - self.claude_failed_at < CLAUDE_COOLDOWN:
            return False
        remaining = self.quota(engine).get("remainingPercent")
        if engine == engines.CODEX:
            return remaining is not None and remaining > self.margin()
        if remaining is not None and remaining <= 0:
            self.claude_failed_at = time.time()
            return False
        return remaining is None or remaining > CLAUDE_FLOOR

    def choose(self, preferred, avoid=None):
        """The preferred engine if eligible, else the other; `avoid` only when nothing else is eligible."""
        order = [preferred] + [e for e in engines.ENGINES if e != preferred]
        order.sort(key=lambda e: e == avoid)
        return next((e for e in order if self.eligible(e)), None)

    def __call__(self, engine, prompt, schema, **options):
        reason = self.boundary()
        if reason:
            raise engines.EngineError("interrupted", reason)
        before = self.quota_seen.get(engine, {}).get("remainingPercent")
        with self.lock:
            self.count += 1
            index = self.count
        stop, interrupted = threading.Event(), []

        def watch():  # The Codex floor is checked during a session too; a session below it is stopped.
            while not stop.wait(30):
                reason = self.boundary()
                if not reason and engine == engines.CODEX:
                    remaining = self.quota(engine).get("remainingPercent")
                    reason = "reserve-floor" if remaining is not None and remaining <= FLOOR + BUFFER else None
                if reason:
                    interrupted.append(reason)
                    emit(self.base, "interrupt", engine=engine, reason=reason, stream=index)
                    engines._stop_live_workers()
                    return
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        progress = options.pop("progress", None)
        timeout = min(options.pop("timeout", 600), max(1, int(self.deadline - time.time())))
        path = self.streams / ("%05d-%s.jsonl" % (index, engine))
        try:
            with open(path, "w", encoding="utf-8") as raw:
                os.chmod(path, 0o600)

                def on_line(line):
                    raw.write(line)
                    raw.flush()
                    if progress:
                        progress(line)
                return self.run_session(engine, prompt, schema, progress=on_line, timeout=timeout, **options)
        except engines.EngineError as error:
            if interrupted:
                error = engines.EngineError("quota" if interrupted[-1].startswith("reserve") else "interrupted",
                                            interrupted[-1], seconds=error.seconds, usage=error.usage)
            if engine == engines.CLAUDE and error.reason in ("quota", "not-signed-in"):
                self.claude_failed_at = time.time()
            emit(self.base, "call-failed", engine=engine, reason=error.reason, stream=index)
            raise error
        finally:
            stop.set()
            monitor.join(45)
            after = self.quota(engine).get("remainingPercent")
            if engine == engines.CODEX and before is not None and after is not None:
                self.max_codex_cost = max(self.max_codex_cost, before - after)
