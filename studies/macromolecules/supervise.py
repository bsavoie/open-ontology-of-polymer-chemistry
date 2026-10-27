"""The supervisor of the 2026-10-18 runs (launch brief, Phase 2): keeps the study's streams going in the background and
restarts a stopped one after a cooldown. A stream is one resumable harness command (a restart, a Part A folder, a final
evaluation shard). The supervisor only ever reruns that command and the harness skips what is done, so a completed item
is never touched.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main>/.oopc/study/freeze-2 OOPC_STUDY_CODEX_FLOOR=0 \
        caffeinate -i python -B <harness>/studies/macromolecules/supervise.py streams.json

Run it from a dedicated worktree of the harness commit that nobody edits (`<harness>`, e.g. `.oopc/study/harness`):
each command runs from the supervisor's own repository, so an edit or checkout in the shared checkout never changes what
a relaunch runs, while OOPC_STUDY_ROOT points the data (records, stores, run folders) at the main checkout. A STOP file
beside streams.json stops the supervisor.

`streams.json` (private, in the supervisor's folder) lists the streams in priority order and how many may run at once.
It is reread every cycle, so streams can be added and the cap raised while the supervisor runs:

    {"cap": 8, "streams": [{"name": "R1", "cmd": ["studies/macromolecules/recursive/restart.py", "run", "--restart", "1"],
                            "folder": ".oopc/loop/harness/2026-10-restarts/R1", "state": "state.json",
                            "lock": "runner.lock", "env": {}}, ...]}

`folder` is relative to ROOT (the data); `cmd[0]` is relative to the supervisor's repository. A command runs as
`python -B <cmd>` from that repository, in a session of its own, with the supervisor's environment plus the stream's
`env` (E8's runs carry a Claude floor); its output is appended to `<folder>/runner.log`. Each cycle, in priority order, a
stream is:

- running, while a process holds its lock (`lock`, in its folder), whoever started it;
- done, once its record says completed (`state`: a JSON file with `status` and `stopReason`, or a JSON lines file whose
  last entry has them);
- held, while a STOP file is in its folder (or one of its `stop` paths exists); removing the file resumes it;
- held until this supervisor restarts, after a launch that crashed, ended `failed` (an E9 replicate whose review
  failed for good) or exited without updating its record (a refusal: a pin changed), because a rerun would fail the
  same way; the log says so;
- otherwise launched, once the cooldown after its last stop has passed: 15 min after a stop whose reason mentions
  rate-limited, 30 min after one for sign-in, 5 min after one for quota (the launch waits for Codex anyway, so a stream
  resumes within minutes of a reset; 2026-10-20: doubled quota cooldowns kept streams idle for an hour after one), 5 min
  after
  anything else (interrupted, slept, a deadline), doubled while the stream keeps stopping within ten minutes of its
  launch (at most 4 h).

A stream may name a `group` and `caps` may cap a group, so one part's long streams cannot take the slots another part
needs (2026-10-19: three A3 streams took the slots of three restarts that had stopped for a few minutes, and held them;
the restarts then reserve five slots). A stream is launched only while fewer than `cap` streams run, its group is under
its cap, and Codex has more than FLOOR + MARGIN percent of its
weekly window left (read at most every five minutes). Every launch and exit goes to `activity.jsonl` beside
streams.json, with the git revision and whether the study code was clean.
"""
import collections, fcntl, json, os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # studies/macromolecules, for common
import common  # noqa: E402  (puts the code under test first on sys.path)
from oopc import engines  # noqa: E402

HARNESS = Path(__file__).resolve().parents[2]  # the repository the supervisor (and every command it runs) comes from
CYCLE = 60
MARGIN = 10  # above the floor: the harness Guards keep a margin of at least 5 plus 1.5 times a session's cost
QUOTA_EVERY = 300
QUICK = 600
LONGEST = 4 * 3600
COOLDOWN = (("rate-limited", 900), ("not-signed-in", 1800))  # matched in the stop reason, in this order
QUOTA = ("quota", "floor", "not-eligible", "not eligible", "no-eligible-engine")  # waits for Codex, not a cooldown
DEFAULT_COOLDOWN = 300


def quota_stop(reason):
    return any(word in (reason or "") for word in QUOTA)


def cooldown(reason):
    """The wait after a stop: by the first COOLDOWN word in its reason (reasons can be composite, such as
    "review: rate-limited" or "round 1 tasks stopped (quota)"). A stop for quota waits only the default: the launch
    itself waits until Codex is above the floor, so a stream resumes as soon as the window resets."""
    return next((wait for word, wait in COOLDOWN if word in (reason or "")), DEFAULT_COOLDOWN)


def record(root, stream):
    """The stream's last record: (status, stop reason, modification time), or Nones when there is none."""
    path = Path(root) / stream["folder"] / stream.get("state", "state.json")
    if not path.exists():
        return None, None, None
    if path.suffix == ".jsonl":
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        value = json.loads(lines[-1]) if lines else {}
    else:
        value = json.loads(path.read_text())
    return value.get("status"), value.get("stopReason") or value.get("error"), path.stat().st_mtime


def busy(root, stream):
    """Whether a process holds the stream's lock (probed without waiting, and let go at once)."""
    path = Path(root) / stream["folder"] / stream.get("lock", "runner.lock")
    if not path.exists():
        return False
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def stopped_by_owner(root, stream):
    paths = [Path(root) / stream["folder"] / "STOP"] + [Path(root) / p for p in stream.get("stop", [])]
    return any(p.exists() for p in paths)


class Supervisor:
    def __init__(self, config, *, root=None, read_quota=engines.read_quota, launch=None, clock=time.time):
        self.config = Path(config).resolve()
        self.base = self.config.parent
        self.root = Path(root or common.ROOT)
        self.read_quota, self.clock = read_quota, clock
        self.launch = launch or self._launch
        self.procs, self.launched, self.cooldown, self.held = {}, {}, {}, set()
        self.waiting = False  # whether launches wait for Codex (logged once when the wait starts)
        self.quota = (None, -QUOTA_EVERY)

    def emit(self, event, **fields):
        common.emit(self.base, event, **fields)

    def revision(self):
        git = lambda *args: subprocess.check_output(["git", *args], cwd=HARNESS, text=True).strip()
        return {"revision": git("rev-parse", "HEAD"), "clean": not git("status", "--porcelain", "--", "studies")}

    def _launch(self, stream):
        log = open(self.root / stream["folder"] / "runner.log", "a")
        command = [sys.executable, "-B", str(HARNESS / stream["cmd"][0]), *stream["cmd"][1:]]
        return subprocess.Popen(command, cwd=HARNESS, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=dict(os.environ, **stream.get("env", {})), start_new_session=True)

    def codex_left(self):
        value, at = self.quota
        if self.clock() - at >= QUOTA_EVERY:
            value = self.read_quota(engines.CODEX).get("remainingPercent")
            self.quota = (value, self.clock())
        return value

    def exited(self, stream):
        """This supervisor's process for the stream has exited: hold it if the harness did not record a stop it can
        resume from, else set the cooldown before its next launch."""
        name, proc = stream["name"], self.procs.pop(stream["name"])
        status, reason, mtime = record(self.root, stream)
        ran = self.clock() - self.launched[name]
        self.emit("stream-exited", stream=name, code=proc.returncode, status=status, reason=reason, seconds=round(ran))
        if status != "completed" and (mtime is None or mtime < self.launched[name]
                                      or status in ("crashed", "running", "failed")):
            self.held.add(name)
            self.emit("stream-held", stream=name, why="exited without a stop it can resume from; see runner.log")
            return
        base = cooldown(reason)
        quick = ran < QUICK and self.cooldown.get(name) and not quota_stop(reason)
        self.cooldown[name] = min(LONGEST, self.cooldown[name] * 2) if quick else base

    def due(self, stream):
        """Whether the cooldown since the stream's last stop has passed (a stop recorded before this supervisor started
        counts from its record's time)."""
        status, reason, mtime = record(self.root, stream)
        if mtime is None:
            return True
        wait = self.cooldown.get(stream["name"], cooldown(reason))
        return self.clock() >= max(mtime, self.launched.get(stream["name"], 0)) + wait

    def cycle(self):
        """One pass over the streams in priority order; returns each stream's state."""
        config = json.loads(self.config.read_text())
        states = {}
        for stream in config["streams"]:
            name = stream["name"]
            if name in self.procs and self.procs[name].poll() is not None:
                self.exited(stream)
            status, reason, _ = record(self.root, stream)
            if name in self.procs or busy(self.root, stream):
                states[name] = "running"
            elif status == "completed":
                states[name] = "done"
            elif name in self.held or status == "failed" or stopped_by_owner(self.root, stream):
                states[name] = "held"
            else:
                states[name] = "waiting"
        running = sum(s == "running" for s in states.values())
        caps, groups = config.get("caps", {}), collections.Counter(
            stream.get("group") for stream in config["streams"] if states[stream["name"]] == "running")
        for stream in config["streams"]:
            name, group = stream["name"], stream.get("group")
            if running >= config.get("cap", 8):
                break
            if states[name] != "waiting" or not self.due(stream) or groups[group] >= caps.get(group, float("inf")):
                continue
            left = self.codex_left()
            if left is None or left <= common.FLOOR + MARGIN:
                if not self.waiting:
                    self.emit("waiting-for-codex", remaining=left)
                self.waiting = True
                break
            self.waiting = False
            self.procs[name], self.launched[name] = self.launch(stream), self.clock()
            states[name] = "running"
            running += 1
            groups[group] += 1
            self.emit("stream-launched", stream=name, pid=self.procs[name].pid, cmd=stream["cmd"], floor=common.FLOOR,
                      codex=left, **self.revision())
        return states

    def run(self):
        self.emit("supervisor-started", pid=os.getpid(), config=str(self.config), floor=common.FLOOR)
        last = None
        while not (self.base / "STOP").exists():
            states = self.cycle()
            if states != last:
                self.emit("states", **states)
                last = states
            time.sleep(CYCLE)
        self.emit("supervisor-stopped", running=sorted(self.procs))


if __name__ == "__main__":
    Supervisor(sys.argv[1]).run()
