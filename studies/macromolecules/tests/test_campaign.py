"""Offline check of the campaign driver with a scripted engine: no subscription is used.

The campaign's test_campaign.py (`.oopc/loop/harness/2026-10-campaign/`), moved to the repository on 2026-10-13
unchanged except imports and paths, the guard's run folder passed as `base`, and a skip when the 200-task run's private
workspace (the campaign's seed) is absent."""
import hashlib, json, shutil, sys, tempfile, threading, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402  (common puts CODE first on sys.path)
from campaign import campaign  # noqa: E402
from oopc import ask, engines, knowledge, reviewer  # noqa: E402


def finding(n, flagged=False):
    return {"statement": "Test polymer %d reached %d%% crystallinity by DSC." % (n, 40 + n), "material": "PLA film %d" % n,
            "property": "crystallinity", "value": str(40 + n), "unit": "%", "conditions": "second heating",
            "sourceTitle": "Paper %d" % n, "sourceUrl": "https://example.org/campaign-p%d" % n, "sourceDoi": "",
            "locator": "Table 1", "excerpt": "crystallinity %d%%" % (40 + n), "needsReview": flagged,
            "reviewFlag": "figure" if flagged else ""}


class Engine:
    def __init__(self, fail_reviews_on=None):
        self.calls, self.fail_reviews_on, self.lock = [], fail_reviews_on, threading.Lock()

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None):
        with self.lock:
            self.calls.append((engine, "research" if schema is ask.ANSWER_SCHEMA else
                               "check" if schema is reviewer.CHECK_SCHEMA else "review"))
            n = len(self.calls)
        if progress:
            progress('{"type":"thread.started"}\n')
        if schema is ask.ANSWER_SCHEMA:
            if tools is not None:
                tools.call("search_knowledge", {"q": "PLA crystallinity"})
            answer = {"answer": "It reached 41%% `https://example.org/campaign-p%d`." % n,
                      "citations": ["https://example.org/campaign-p%d" % n], "findings": [finding(n, flagged=True), finding(n + 100)],
                      "sources": [], "limitations": [], "openQuestions": []}
        elif schema is reviewer.CHECK_SCHEMA:
            answer = {"verdict": "pass", "statements": [{"statement": "x", "verdict": "supported", "reason": "ok",
                                                         "kind": "source-fact", "category": "none"}], "notes": ""}
        else:
            if engine == self.fail_reviews_on:
                raise engines.EngineError("timeout", "stalled")
            ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"]]
            answer = {"verdicts": [{"id": i, "verdict": "supported", "reason": "Table 1."} for i in ids], "notes": ""}
        return {"engine": engine, "model": "scripted", "sessionId": "s%d" % n, "answer": answer,
                "usage": {"input_tokens": 1000, "cached_input_tokens": 100, "output_tokens": 50},
                "observedTools": [], "agentSeconds": 0.1}


@unittest.skipUnless((run_dir("2026-10-03-200") / "workspace").exists(),
                     "needs the 200-task run's private workspace (.oopc/loop/harness/2026-10-03-200/workspace)")
class CampaignDriver(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-campaign-test-")
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.saved = {k: getattr(campaign, k) for k in ("BASE", "WORK", "SEED_WORKSPACE", "PORT", "Guard")}
        self.addCleanup(lambda: [setattr(campaign, k, v) for k, v in self.saved.items()])
        campaign.BASE, campaign.WORK, campaign.PORT = self.base, self.base / "workspace", 0
        seed = self.base / "seed"
        shutil.copytree(self.saved["SEED_WORKSPACE"], seed, symlinks=True,
                        ignore=shutil.ignore_patterns("runs", "questions", "calls"))
        campaign.SEED_WORKSPACE = seed
        tasks = [dict(number=i, taskId=hashlib.md5(b"campaign-test-%d" % i).hexdigest(), wave=1, kind="property", revisit=None,
                      materials=["PLA"], property="crystallinity", depth="standard", checkSample=i == 2,
                      question="What crystallinity has been reported for PLA films, test %d?" % i) for i in (1, 2, 3)]
        (self.base / "questions.json").write_text(json.dumps(tasks))

    def use(self, engine, quota=lambda e: {"remainingPercent": 80}):
        class FakeGuard(self.saved["Guard"]):
            def __init__(self, deadline, base):
                super().__init__(deadline, read_quota=quota, run_session=engine, signed=lambda e: True, base=base)
        campaign.Guard = FakeGuard

    def test_a_wave_researches_reviews_checks_and_resumes(self):
        campaign.prepare()
        engine = Engine()
        self.use(engine)
        campaign.Wave(1, limit=2).run()
        state = json.loads((self.base / "waves/wave-1/state.json").read_text())
        self.assertEqual((state["status"], state["completed"], state["unattempted"], state["checks"]), ("paused", 2, 1, 1))
        kinds = [k for _, k in engine.calls]
        self.assertEqual(kinds.count("research"), 2)
        self.assertEqual(kinds.count("check"), 1)
        # Research and reviews on Codex; the whole-answer check on the other engine.
        self.assertEqual({e for e, k in engine.calls if k in ("research", "review")}, {"codex"})
        self.assertEqual({e for e, k in engine.calls if k == "check"}, {"claude-code"})
        self.assertEqual(knowledge.review_queue(campaign.WORK), [])
        campaign.Wave(1).run()  # Resumes with the one task left.
        state = json.loads((self.base / "waves/wave-1/state.json").read_text())
        self.assertEqual((state["status"], state["completed"]), ("completed", 3))
        self.assertEqual([k for _, k in engine.calls].count("research"), 3)
        self.assertTrue(len(list((self.base / "streams").glob("*.jsonl"))) >= 7)
        from campaign import report
        report.BASE, report.WORK = self.base, campaign.WORK
        value = report.build()
        s = value["summary"]
        self.assertEqual(s["tasks"]["counts"], {"completed": 3})
        self.assertEqual(s["quality"]["verdicts"], {"pass": 1})
        self.assertEqual(s["knowledge"]["newFindings"], 6)
        self.assertEqual(s["trust"]["reviewsCompleted"], 3)
        self.assertEqual(s["cost"]["phases"]["research"]["calls"], 3)
        self.assertIn("Memory curve", report.text(value))

    def test_a_failed_review_moves_to_the_other_engine_and_codex_keeps_its_floor(self):
        campaign.prepare()
        engine = Engine(fail_reviews_on="codex")
        self.use(engine)
        campaign.Wave(1, limit=1).run()
        reviews = [e for e, k in engine.calls if k == "review"]
        self.assertEqual(reviews, ["codex", "claude-code"])
        self.assertEqual(knowledge.review_queue(campaign.WORK), [])
        low = Engine()
        self.use(low, quota=lambda e: {"remainingPercent": 13 if e == "codex" else 50})
        campaign.Wave(1, limit=1).run()  # Codex is below its launch margin: research falls back to Claude.
        self.assertEqual([e for e, k in low.calls if k == "research"], ["claude-code"])

    def test_the_stop_file_stops_before_the_next_task(self):
        campaign.prepare()
        (self.base / "STOP").write_text("")
        self.use(Engine())
        campaign.Wave(1).run()
        state = json.loads((self.base / "waves/wave-1/state.json").read_text())
        self.assertEqual((state["status"], state["stopReason"], state["completed"]), ("stopped", "owner-stop", 0))


if __name__ == "__main__":
    unittest.main()
