"""Guard tests use fake quota and engine calls; never invoke host engines.

The 200-task observation's test_guard.py (`.oopc/loop/harness/2026-10-03-200/`), moved to the repository on 2026-10-13
unchanged except imports and paths. Reads no private record, so it runs in a fresh clone too."""
import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY  # noqa: E402  (common puts CODE first on sys.path)
from oopc import calls

spec = importlib.util.spec_from_file_location("overnight", STUDY / "observation_200" / "guard.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(run,"BASE",Path(self.temp.name)),
                        patch.object(run,"seconds_left",return_value=3600),
                        patch.object(run.engines,"signed_in",return_value=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_floor_prevents_model_call(self):
        called=[]
        guard=run.Guard(read_quota=lambda e:{"remainingPercent":10},run_session=lambda *a,**k:called.append(True))
        with self.assertRaises(run.engines.EngineError) as failure:
            guard("codex","prompt",{})
        self.assertEqual(failure.exception.reason,"quota")
        self.assertEqual(called,[])

    def test_unknown_codex_quota_is_read_twice_and_fails_closed(self):
        reads=[]
        guard=run.Guard(read_quota=lambda e:reads.append(e) or {"remainingPercent":None})
        self.assertFalse(guard.eligible("codex"))
        self.assertEqual(reads,["codex","codex"])
        self.assertEqual(guard.codex_suspended,"quota-unavailable")

    def test_codex_reserve_falls_back_to_claude(self):
        guard=run.Guard(read_quota=lambda e:{"remainingPercent":14 if e=="codex" else 60})
        self.assertEqual(guard.choose("codex"),"claude-code")
        self.assertEqual(guard.codex_suspended,"reserve-launch-margin")

    def test_owner_stop_prevents_any_call(self):
        (run.BASE/"STOP").touch()
        guard=run.Guard(read_quota=lambda e:(_ for _ in ()).throw(AssertionError("No quota read expected")))
        with self.assertRaises(run.engines.EngineError) as failure:
            guard("codex","prompt",{})
        self.assertEqual(failure.exception.reason,"interrupted")

    def test_inflight_floor_interrupts_only_owned_workers(self):
        halted=threading.Event()
        reads=[]
        def quota(engine):
            reads.append(engine)
            return {"remainingPercent":69 if len(reads)==1 else 11}
        def session(*args,**options):
            self.assertTrue(halted.wait(3),"Monitor must interrupt in-flight work")
            raise run.engines.EngineError("crashed","fake cancelled worker")
        guard=run.Guard(read_quota=quota,run_session=session)
        guard.poll_seconds=0.02
        with patch.object(run.engines,"_stop_live_workers",side_effect=halted.set) as kill:
            with self.assertRaises(run.engines.EngineError) as failure:
                guard("codex","prompt",{},web=True)
        self.assertEqual(failure.exception.reason,"quota")
        self.assertEqual(guard.codex_suspended,"quota")
        self.assertEqual(guard.calls[0]["outcome"],"failed")
        kill.assert_called_once()

    def test_completed_response_preserved_and_usage_accounted(self):
        def session(*args,**options):
            options["progress"]('{"type":"example","payload":"actual"}\n')
            return {"answer":{"answer":"supported"},"usage":{"input_tokens":120,"cached_input_tokens":100,"output_tokens":8},"agentSeconds":1}
        guard=run.Guard(read_quota=lambda e:{"remainingPercent":69},run_session=session)
        result=guard("codex","prompt",{})
        self.assertEqual(result["answer"]["answer"],"supported")
        self.assertEqual(calls.new_tokens(guard.calls[0]["usage"]),28)
        self.assertIn('"payload":"actual"',(run.BASE/"streams/0001-codex.jsonl").read_text())

    def test_different_engines_overlap_without_mixing_question_metadata(self):
        barrier=threading.Barrier(2)
        def session(*args,**options):
            barrier.wait(2)
            return {"answer":{},"usage":{},"agentSeconds":0.1}
        guard=run.Guard(read_quota=lambda e:{"remainingPercent":69},run_session=session)
        def task(engine,number,phase):
            guard.number,guard.phase=number,phase
            return guard(engine,"prompt",{})
        with ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(task,"codex",8,"research"),pool.submit(task,"claude-code",7,"answer-check")]
            for f in futures:
                f.result()
        calls=guard.call_snapshot()
        self.assertEqual({(c["engine"],c["question"],c["phase"]) for c in calls},
                         {("codex",8,"research"),("claude-code",7,"answer-check")})
        self.assertEqual(sorted(c["index"] for c in calls),[1,2])
        self.assertEqual(len(list((run.BASE/"streams").glob('*'))),2)

    def test_same_engine_calls_remain_serial_for_quota_control(self):
        state={"live":0,"max":0}
        lock=threading.Lock()
        def session(*args,**options):
            with lock:
                state["live"]+=1
                state["max"]=max(state["live"],state["max"])
            time.sleep(0.03)
            with lock:
                state["live"]-=1
            return {"answer":{},"usage":{},"agentSeconds":0.03}
        guard=run.Guard(read_quota=lambda e:{"remainingPercent":69},run_session=session)
        with ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(guard,"codex","prompt",{}) for _ in range(2)]
            for f in futures:
                f.result()
        self.assertEqual(state["max"],1)


if __name__=="__main__":
    unittest.main()
