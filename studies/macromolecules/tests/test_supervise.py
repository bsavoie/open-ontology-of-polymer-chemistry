"""The supervisor of the 2026-10-18 runs, offline: scripted processes, a scripted clock and quota, a temporary root."""
import fcntl, json, os, sys, tempfile, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supervise  # noqa: E402


class Proc:
    count = 0

    def __init__(self):
        Proc.count += 1
        self.pid, self.returncode = 1000 + Proc.count, None

    def poll(self):
        return self.returncode


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "sup").mkdir()
        self.now, self.left, self.launched = 1_000_000.0, 50, []
        self.streams = []
        for name in ("A", "B", "C"):
            (self.root / name).mkdir()
            self.streams.append({"name": name, "cmd": [name], "folder": name, "state": "state.json"})
        self.write_config(cap=2)
        self.sup = supervise.Supervisor(self.root / "sup/streams.json", root=self.root, clock=lambda: self.now,
                                        read_quota=lambda engine: {"remainingPercent": self.left}, launch=self.start)
        self.sup.revision = lambda: {"revision": "test", "clean": True}

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, cap):
        (self.root / "sup/streams.json").write_text(json.dumps({"cap": cap, "streams": self.streams}))

    def start(self, stream):
        proc = Proc()
        self.launched.append(stream["name"])
        return proc

    def finish(self, name, status, reason=None, code=0):
        self.now += 1
        path = self.root / name / "state.json"
        path.write_text(json.dumps({"status": status, "stopReason": reason}))
        os.utime(path, (self.now, self.now))
        self.sup.procs[name].returncode = code

    def test_cap_priority_and_completion(self):
        self.assertEqual(self.sup.cycle(), {"A": "running", "B": "running", "C": "waiting"})
        self.finish("A", "completed")
        self.now += 60
        self.assertEqual(self.sup.cycle(), {"A": "done", "B": "running", "C": "running"})
        self.assertEqual(self.launched, ["A", "B", "C"])

    def test_cooldown_by_reason_and_doubling(self):
        self.sup.cycle()
        self.finish("A", "stopped", "rate-limited")
        stopped = self.now
        self.now += 60
        states = self.sup.cycle()  # A cools down for 15 min, so C takes its place
        self.assertEqual(states["A"], "waiting")
        self.assertEqual(self.launched, ["A", "B", "C"])
        self.finish("C", "completed")
        self.now = stopped + 899
        self.sup.cycle()
        self.assertEqual(self.launched, ["A", "B", "C"])
        self.now = stopped + 901
        self.sup.cycle()
        self.assertEqual(self.launched, ["A", "B", "C", "A"])
        self.finish("A", "stopped", "rate-limited")  # stopped again within ten minutes: twice the cooldown
        self.assertEqual(self.sup.cycle()["A"], "waiting")
        self.assertEqual(self.sup.cooldown["A"], 1800)
        self.now += 1801
        self.sup.cycle()
        self.assertEqual(self.launched[-1], "A")

    def test_refusal_is_held_and_owner_stop(self):
        self.sup.cycle()
        self.sup.procs["A"].returncode = 1  # exited without touching its record, as a refused pin check does
        self.now += 60
        self.assertEqual(self.sup.cycle()["A"], "held")
        (self.root / "B" / "STOP").write_text("")
        self.finish("B", "stopped", "owner-stop")
        self.now += 3600
        states = self.sup.cycle()
        self.assertEqual((states["A"], states["B"]), ("held", "held"))
        self.assertEqual(self.launched.count("A") + self.launched.count("B"), 2)

    def test_removing_the_stop_file_resumes_an_owner_stopped_stream(self):
        self.write_config(cap=3)
        self.sup.cycle()
        (self.root / "A" / "STOP").write_text("")
        self.finish("A", "stopped", "owner-stop")
        self.now += 3600
        self.assertEqual(self.sup.cycle()["A"], "held")
        (self.root / "A" / "STOP").unlink()
        self.assertEqual(self.sup.cycle()["A"], "running")

    def test_a_group_cap_keeps_slots_for_another_group(self):
        self.streams = [dict(s, group="B" if s["name"] == "A" else "A") for s in self.streams]  # A in group B
        self.streams.append({"name": "D", "cmd": ["D"], "folder": "C", "state": "none.json", "group": "B"})
        (self.root / "sup/streams.json").write_text(json.dumps({"cap": 3, "caps": {"A": 2, "B": 1},
                                                                "streams": self.streams}))
        self.assertEqual(self.sup.cycle(), {"A": "running", "B": "running", "C": "running", "D": "waiting"})
        self.finish("B", "stopped", "slept")  # a group-A stream stops: its slot is not group B's to take
        self.now += 60
        self.assertEqual(self.sup.cycle()["D"], "waiting")
        self.finish("A", "stopped", "slept")  # group B's own stream stops: D, not A again, takes its slot at once
        self.now += 60
        self.assertEqual(self.sup.cycle()["D"], "running")
        self.assertEqual(self.launched, ["A", "B", "C", "D"])

    def test_quota_stops_do_not_double_the_cooldown(self):
        self.write_config(cap=3)
        self.sup.cycle()
        for _ in range(3):  # stopped for quota within minutes, three times: the wait stays the default
            self.finish("A", "stopped", "round 3 tasks stopped (no-eligible-engine)")
            self.now += 60
            self.sup.cycle()
            self.assertEqual(self.sup.cooldown["A"], supervise.DEFAULT_COOLDOWN)
            self.now += supervise.DEFAULT_COOLDOWN + 1
            self.sup.cycle()
            self.assertEqual(self.launched[-1], "A")

    def test_crash_is_held(self):
        self.sup.cycle()
        self.finish("A", "crashed")
        self.now += 3600
        self.assertEqual(self.sup.cycle()["A"], "held")

    def test_a_failed_run_is_held(self):
        self.sup.cycle()
        self.finish("A", "failed", "review failed: rejected")
        self.now += 3600
        self.assertEqual(self.sup.cycle()["A"], "held")
        self.assertEqual(self.launched.count("A"), 1)
        fresh = supervise.Supervisor(self.root / "sup/streams.json", root=self.root, clock=lambda: self.now,
                                     read_quota=lambda engine: {"remainingPercent": 50}, launch=self.start)
        self.assertEqual(fresh.cycle()["A"], "held")  # a restarted supervisor reads the record and holds it too

    def test_codex_floor_blocks_launches(self):
        self.left = supervise.common.FLOOR + supervise.MARGIN
        self.assertEqual(self.sup.cycle(), {"A": "waiting", "B": "waiting", "C": "waiting"})
        self.now += supervise.QUOTA_EVERY
        self.sup.cycle()  # the wait is logged once, not every cycle
        log = (self.root / "sup" / "activity.jsonl").read_text()
        self.assertEqual(log.count("waiting-for-codex"), 1)
        self.assertEqual(self.launched, [])
        self.left = 40
        self.now += supervise.QUOTA_EVERY
        self.sup.cycle()
        self.assertEqual(self.launched, ["A", "B"])

    def test_a_stream_another_process_runs_is_not_launched(self):
        lock = self.root / "A" / "runner.lock"
        with open(lock, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.sup.cycle(), {"A": "running", "B": "running", "C": "waiting"})
        self.assertEqual(self.launched, ["B"])
        self.now += 60
        self.sup.cycle()
        self.assertEqual(self.launched, ["B", "A"])

    def test_a_stop_recorded_before_the_supervisor_counts_from_its_time(self):
        path = self.root / "A" / "state.json"
        path.write_text(json.dumps({"status": "stopped", "stopReason": "rate-limited"}))
        os.utime(path, (self.now - 600, self.now - 600))
        self.sup.cycle()
        self.assertEqual(self.launched, ["B", "C"])

    def test_composite_reasons_pick_their_cooldown(self):
        self.assertEqual(supervise.cooldown("review: rate-limited"), 900)
        self.assertEqual(supervise.cooldown("round 1 tasks stopped (quota)"), supervise.DEFAULT_COOLDOWN)
        self.assertEqual(supervise.cooldown("not-signed-in"), 1800)
        self.assertTrue(supervise.quota_stop("improver: Claude Code not eligible"))
        self.assertEqual(supervise.cooldown("slept"), supervise.DEFAULT_COOLDOWN)
        self.assertEqual(supervise.cooldown(None), supervise.DEFAULT_COOLDOWN)

    def test_launch_runs_the_harness_repository_with_the_stream_env(self):
        seen = {}

        def popen(command, **options):
            seen.update(command=command, **options)
            return Proc()
        real, supervise.subprocess.Popen = supervise.subprocess.Popen, popen
        try:
            supervise.Supervisor(self.root / "sup/streams.json", root=self.root)._launch(
                {"name": "E8", "cmd": ["studies/macromolecules/part_a/part_a.py", "run", "x"], "folder": "A",
                 "env": {"OOPC_STUDY_CLAUDE_FLOOR": "40"}})
        finally:
            supervise.subprocess.Popen = real
        self.assertEqual(seen["command"][2:], [str(supervise.HARNESS / "studies/macromolecules/part_a/part_a.py"),
                                               "run", "x"])
        self.assertEqual(seen["cwd"], supervise.HARNESS)
        self.assertEqual(seen["env"]["OOPC_STUDY_CLAUDE_FLOOR"], "40")
        self.assertTrue((self.root / "A" / "runner.log").exists())

    def test_claude_floor(self):
        common = supervise.common
        guard = common.Guard(time.time() + 3600, read_quota=lambda engine: {"remainingPercent": 35},
                             run_session=None, signed=lambda engine: True, base=self.root / "sup")
        real = common.CLAUDE_FLOOR
        try:
            common.CLAUDE_FLOOR = 0
            self.assertTrue(guard.eligible(common.engines.CLAUDE))
            common.CLAUDE_FLOOR = 40
            self.assertFalse(guard.eligible(common.engines.CLAUDE))
        finally:
            common.CLAUDE_FLOOR = real

    def test_streams_added_while_running(self):
        self.sup.cycle()
        self.streams.insert(0, {"name": "Z", "cmd": ["Z"], "folder": "A", "state": "none.json"})
        self.write_config(cap=3)
        self.assertEqual(self.sup.cycle()["Z"], "running")


if __name__ == "__main__":
    unittest.main()
