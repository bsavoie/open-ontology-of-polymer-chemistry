"""The confirmation run's harness offline (`confirm/confirm.py`), with a scripted engine and its own release and stores
in a temporary folder: the pins and the refusals before anything is prepared or run; A2's plan (K0 and KF on test 1's
questions in test 1's order) run end to end through both turns; the case studies' replicate run and scored blind; and
the report's predictions, on those records and on a hand-made example. Nothing reaches an engine, and nothing is
written under `.oopc/`: every run folder is under `--into`, every Part A input a fixture."""
import contextlib, io, json, random, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402
import driver  # noqa: E402
from analysis import kf as kf_pins  # noqa: E402
from case_studies import case_studies  # noqa: E402
from confirm import confirm  # noqa: E402
from part_a import estimate, part_a  # noqa: E402
from scaling import scaling  # noqa: E402
from oopc import ask, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

REAL_PINS, REAL_FROZEN = confirm.PINS, confirm.frozen  # as committed, before any test replaces them
STRATA = ("near", "mid", "far")


def release(root):
    path = build_release(root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                         "label": "Polylactide", "status": "seed", "layer": "science"}], get_ontology(), {})
    release_id = json.loads((path / "manifest.json").read_text())["release_id"]
    path.rename(root / "releases" / release_id)
    atomic_json(root / "releases/current.json", {"release_id": release_id})
    return release_id


def store(root, findings):
    """A store with `findings` (n) about polymer 1's crystallinity, each with a source note."""
    with knowledge.connect(root) as db:
        for n in range(findings):
            q = "q%d" % n
            knowledge._insert_finding(db, "finding:%s-1" % q, q, "research", knowledge.clean_finding({
                "statement": "Polymer 1 reached 4%d%% crystallinity in study %s." % (n, q), "material": "polymer 1",
                "property": "crystallinity", "value": "4%d" % n, "unit": "%", "conditions": "second heating",
                "subject": "", "sourceTitle": "Paper " + q, "sourceDoi": "", "sourceUrl": "https://example.org/" + q,
                "locator": "Table 1", "excerpt": "4%d" % n, "needsReview": False, "reviewFlag": ""}),
                status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-10-01T12:00:00+00:00",
                reviewed_at="2026-10-01T13:00:00+00:00", reviewer_engine="codex",
                detail={"reviewMode": "researcher", "needsReview": False})
            knowledge._insert_note(db, "note:%s-1" % q, q, "research", {
                "title": "Paper " + q, "url": "https://example.org/n/" + q, "doi": "", "locator": "p. 1",
                "excerpts": [], "supports": "crystallinity of polymer 1", "conditions": "", "readUrl": ""},
                created_at="2026-10-01T12:00:00+00:00")


class Engine:
    """Answers by schema and counts each kind. The researcher searches saved knowledge for polymer 1's crystallinity:
    with a finding it cites it at no web cost (1,000 input tokens, 3 s), without one it searches the web (2,000 tokens,
    6 s); its second turn (resumed) writes nothing new (500 tokens, 2 s). The blind scorer reads only the blinded text:
    a value with a citation mark is sourced, "Interpretation" labels an explanation, and no answer gives a value as
    reported."""

    def __init__(self):
        self.calls, self.prompts = [], []

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, **options):
        usage = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 10}
        seconds, observed = 1.0, []
        props = schema.get("properties", {})
        if options.get("resume"):
            kind, seconds = "deposit", 2.0
            usage = {"input_tokens": 500, "cached_input_tokens": 0, "output_tokens": 20}
            answer = {"answer": "", "citations": [], "findings": [], "limitations": [], "openQuestions": [],
                      "sources": [{"title": "Handbook", "url": "https://example.org/h", "doi": "", "locator": "Table 2",
                                   "excerpts": [], "supports": "no such value", "conditions": "", "readUrl": ""}]}
        elif schema is parity.DIRECT_SCHEMA:
            kind, answer = "plain", {"answer": "Values of 40 and 45 were reported.", "citations": [], "limitations": []}
        elif schema is ask.ANSWER_SCHEMA:
            kind = "research"
            found = tools.call("search_knowledge", {"q": "polymer 1 crystallinity"}) if tools else {}
            ids = [f["id"] for g in ("reviewed", "added") for f in found.get(g, [])]
            if ids:
                text, seconds = "Polymer 1 reached 41%% crystallinity `%s`. Interpretation: it varies." % ids[0], 3.0
            else:
                text, seconds = "Not found in open sources. Interpretation: none reported.", 6.0
                usage = dict(usage, input_tokens=2000)
                observed = [{"type": "web_search", "action": "search", "query": "polymer 1 crystallinity"}]
            answer = {"answer": text, "citations": ids[:1], "findings": [], "limitations": [], "openQuestions": [],
                      "sources": []}
        elif schema is reviewer.CHECK_SCHEMA:
            kind, answer = "check", {"verdict": "pass", "resultGiven": True, "notes": "", "statements": [
                {"statement": "s", "verdict": "supported", "reason": "r", "kind": "completeness", "category": "none",
                 "evidence": "live"}]}
        elif "scores" in props:
            kind = "score"
            self.prompts.append(prompt)
            fields = props["scores"]["items"]["properties"]
            scores = []
            for entry in json.loads(prompt[prompt.index("\n[") + 1:]):
                sourced = "[S" in entry["answer"]
                value = {"code": entry["code"]}
                for key, spec in fields.items():
                    if key == "code":
                        continue
                    if spec["type"] == "integer":
                        value[key] = (0 if sourced else 2) if key == "uncitedValues" else (3 if sourced else 1)
                    else:
                        value[key] = ("Interpretation" in entry["answer"] if key == "explanationLabelled" else
                                      key != "givesValueAsReported")
                scores.append(value)
            answer = {"notes": "", "scores": scores}
        else:
            kind = "review"
            ids = [f["id"] for f in json.loads(prompt[prompt.index("{"):])["findings"]]
            answer = {"notes": "", "verdicts": [{"id": i, "verdict": "supported", "reason": "ok", "excerpt": "",
                                                 "material": ""} for i in ids]}
        self.calls.append(kind)
        return {"engine": engine, "model": "scripted", "sessionId": options.get("resume") or "session-0001",
                "answer": answer, "usage": usage, "observedTools": observed, "agentSeconds": seconds}


def heldout(n=9):
    """Test 1's held-out questions in miniature: three per stratum, the near ones with a parent."""
    return [{"id": "h%d" % i, "question": "What crystallinity did polymer %d reach in study %d?" % (i % 2, i),
             "stratum": STRATA[i % 3], "kind": "property", "material": "M%d" % i, "property": "P%d" % i,
             "depth": "standard", "parent": "q0" if i % 3 == 0 else None} for i in range(n)]


def part_a_fixture(folder, ids):
    """Part A's recorded inputs in miniature: A2's answer rows (three replicates; KF cheaper, fewer web calls, 60 s to
    the answer; KF gave no sourced result in replicate 3 once), the A2 results built from them as a2a3e8_results does,
    and A5's per-replicate case-study summaries."""
    strata = {q["id"]: q["stratum"] for q in heldout()}
    rows = [{"id": i, "stratum": strata[i], "arm": arm, "replicate": rep, "answered": True, "checked": True,
             "contradicted": 0, "complete": True, "resultGiven": not (arm == "KF" and rep == 3 and i == ids[0]),
             "pass": True, "accessUncertain": 0, "newTokens": 20000 if arm == "KF" else 40000,
             "webCalls": 2 if arm == "KF" else 7, "seconds": 60.0 if arm == "KF" else 70.0, "findingCitations": 0,
             "parentInStore": None} for i in ids for arm in ("K0", "KF") for rep in (1, 2, 3)]
    by = {}
    for s in STRATA + ("all",):
        mine = [r for r in rows if s == "all" or r["stratum"] == s]
        paired = estimate.paired(mine, "KF", "K0")
        paired["seconds"] = estimate.paired(confirm.swapped(mine, "seconds"), "KF", "K0")["tokens"]
        by[s] = {"arms": {a: confirm.counts([r for r in mine if r["arm"] == a]) for a in ("K0", "KF")},
                 "paired": {"KF": paired}}
    atomic_json(folder / "a2-rows.json", rows)
    atomic_json(folder / "a2-results.json", {"meta": {"codeTag": "study-freeze-2", "prompt": "0b7bb1483235"},
                                             "A2": {"byStratum": by}})
    summaries = {"cs1-conditions": {"R": (3, {"uncitedValues": 2}), "P": (3, {"uncitedValues": 20})},
                 "cs2-conflicts": {"R": (3, {"explanationLabelled": 3}), "P": (3, {"explanationLabelled": 0})},
                 "cs3-screening": {"R": (2, {"rankedWithSourcedValue": 9}), "R0": (2, {"rankedWithSourcedValue": 4}),
                                   "P": (2, {"rankedWithSourcedValue": 9})},
                 "cs4-first": {"first": (3, {"givesValueAsReported": 0})},
                 "cs4-repeat": {"R": (3, {"givesValueAsReported": 0}), "P": (3, {"givesValueAsReported": 0})}}
    a5 = {"replicates": [1, 2, 3, 4, 5], "byReplicate": {
        study: {arm: [{"replicate": r, "answers": n, "newTokens": 100000 if arm == "R" else 150000,
                       "blind": dict(blind, answers=n)} for r in (1, 2, 3, 4, 5)] for arm, (n, blind) in arms.items()}
        for study, arms in summaries.items()}}
    atomic_json(folder / "a5-results.json", {"meta": {"codeTag": "study-freeze-2"}, "caseStudies": a5})
    return {"a2": folder / "a2-results.json", "a2Rows": folder / "a2-rows.json", "a5": folder / "a5-results.json"}


class Confirm(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-confirm-test-")
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name).resolve()
        self.kf, self.k0, self.into = self.tmp / "kf/workspaces/KF", self.tmp / "k0", self.tmp / "harness"
        release_id = release(self.kf)
        store(self.kf, 3)  # KF: polymer 1's crystallinity is saved
        with knowledge.connect(self.k0):  # K0: nothing about it
            pass
        atomic_json(self.tmp / "heldout.json", heldout())
        self.pins = dict(REAL_PINS, tagCommit="918a64c", promptVersion=ask.prompt_version(),
                         models={e: engines.ENGINES[e]["model"] for e in REAL_PINS["models"]}, release=release_id,
                         kf=driver.fingerprint(self.kf), k0=driver.fingerprint(self.k0))
        self.inputs = part_a_fixture(self.tmp, [q["id"] for q in heldout()])
        # configure() sets these in the reused modules; each is put back after the test.
        kept = [(part_a, n) for n in ("PINS", "ROOT", "K0", "HELDOUT", "EXPERIMENTS", "CASE_STUDIES", "PLANTED")]
        kept += [(case_studies, n) for n in ("TAG", "ROOT", "frozen")]
        patches = [mock.patch.object(t, n, getattr(t, n)) for t, n in kept] + [
            mock.patch.object(confirm, "KF", self.kf), mock.patch.object(confirm, "K0", self.k0),
            mock.patch.object(confirm, "HELDOUT", self.tmp / "heldout.json"),
            mock.patch.object(confirm, "PINS", self.pins), mock.patch.object(confirm, "PART_A", self.inputs),
            mock.patch.object(confirm, "OUT", self.tmp / "analysis/confirm"),
            mock.patch.object(confirm, "frozen", lambda: "918a64c" + "0" * 33),
            mock.patch.object(part_a, "dirty", lambda: {})]  # the refusal of uncommitted code has its own test
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.engine = Engine()
        real = driver.Guard

        def guard(deadline, base=None, **_):
            return real(deadline, read_quota=lambda e: {"remainingPercent": 80}, run_session=self.engine,
                        signed=lambda e: True, base=base)
        patch = mock.patch.object(driver, "Guard", guard)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_pins_are_the_plans_and_configure_points_the_reused_modules_at_them(self):
        self.assertEqual((REAL_PINS["tag"], REAL_PINS["tagCommit"], REAL_PINS["promptVersion"], REAL_PINS["models"]),
                         ("study-freeze-4", "918a64c", "86404bf073ce",
                          {engines.CODEX: "gpt-6.1-sol", engines.CLAUDE: "claude-opus-5-5"}))
        self.assertEqual((REAL_PINS["release"], REAL_PINS["knowledgeSnapshot"], REAL_PINS["kf"]),
                         (kf_pins.RELEASE_ID, kf_pins.SNAPSHOT_ID, kf_pins.FINGERPRINT))
        self.assertEqual(REAL_PINS["k0"]["findings"], 150)
        self.assertEqual(part_a.PINS["tag"], "study-freeze-2")  # untouched until configured
        confirm.configure()
        self.assertIs(part_a.PINS, self.pins)
        self.assertEqual((part_a.ROOT, case_studies.ROOT, case_studies.TAG), (self.kf, self.kf, "study-freeze-4"))
        self.assertEqual(list(part_a.EXPERIMENTS), [confirm.EXPERIMENT])
        self.assertEqual(part_a.specs(confirm.EXPERIMENT, None), [("K0", self.k0, True, engines.CODEX),
                                                                  ("KF", self.kf, True, engines.CODEX)])
        order = heldout()
        random.Random(scaling.SEED).shuffle(order)
        self.assertEqual(part_a.questions_of(confirm.EXPERIMENT), order)  # all 60 in test 1's order, as A2
        self.assertEqual(case_studies.frozen(), "918a64c" + "0" * 33)  # this run's check
        self.assertEqual(part_a.pinned()["kf"], self.pins["kf"])

    def test_the_committed_paths_are_kfs_frozen_copy_and_test_1s_k0(self):
        with open(confirm.__file__, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('KF = common.analysis_dir("kf") / "workspaces" / "KF"', text)
        self.assertIn('K0 = common.run_dir("2026-10-ablation") / "workspaces" / "K0"', text)
        self.assertEqual(common.analysis_dir("kf") / "workspaces" / "KF", kf_pins.FOLDER / "workspaces" / "KF")
        self.assertEqual(common.run_dir("2026-10-ablation") / "workspaces" / "K0", part_a.stores.K0)

    def test_nothing_prepares_or_runs_unless_every_pin_holds(self):
        other = self.tmp / "other"  # a store with its graph release that is not KF
        release(other)
        store(other, 1)
        refusals = [
            (mock.patch.object(confirm, "frozen", mock.Mock(side_effect=SystemExit("not the tag"))), "not the tag"),
            (mock.patch.dict(self.pins, promptVersion="000000000000"), "promptVersion"),
            (mock.patch.dict(self.pins, models={engines.CODEX: "another", engines.CLAUDE: "claude-opus-5-5"}),
             "models"),
            (mock.patch.dict(self.pins, release="oopc-another"), "release"),
            (mock.patch.object(confirm, "KF", self.tmp / "missing"), "frozen copy"),
            (mock.patch.object(confirm, "KF", other), "kf"),  # a KF copy without KF's fingerprint
            (mock.patch.object(confirm, "K0", other), "K0"),
            (mock.patch.object(part_a, "dirty", lambda: {"harness": [" M studies/x.py"]}), "Uncommitted")]
        for patch, says in refusals:
            for step in (lambda: confirm.prepare_a2(into=self.into), lambda: confirm.prepare_cs(into=self.into),
                         lambda: confirm.run_a2(into=self.into), lambda: confirm.score_cs(into=self.into)):
                with patch, self.assertRaisesRegex(SystemExit, says):
                    step()
        self.assertFalse(self.into.exists())
        self.assertEqual(self.engine.calls, [])

    def test_frozen_checks_the_tag_its_commit_and_the_code_under_test(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *a], cwd=repo,
                                        check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "the release")
        commit = git("rev-parse", "HEAD")
        with mock.patch.object(common, "ROOT", repo), mock.patch.object(common, "CODE", repo), \
                mock.patch.dict(self.pins, tagCommit=commit[:7]):
            with self.assertRaisesRegex(SystemExit, "does not exist"):
                REAL_FROZEN()
            git("tag", "study-freeze-4")
            self.assertEqual(REAL_FROZEN(), commit)
            with mock.patch.dict(self.pins, tagCommit="0000000"), self.assertRaisesRegex(SystemExit, "not the pinned"):
                REAL_FROZEN()
            git("commit", "-q", "--allow-empty", "-m", "later")
            with self.assertRaisesRegex(SystemExit, "is not study-freeze-4"):
                REAL_FROZEN()

    def test_a2_runs_k0_and_kf_on_test_1s_questions_through_both_turns(self):
        layout = confirm.prepare_a2(into=self.into)
        self.assertEqual((layout["experiment"], layout["folders"], layout["arms"], layout["questions"],
                          layout["answers"], layout["replicates"]), ("A2-confirm", ["r1-s1"], ["K0", "KF"], 9, 18, 1))
        run = self.into / confirm.A2 / "r1-s1"
        plan, pins = read_json(run / "plan.json"), read_json(run / "pins.json")
        order = heldout()
        random.Random(scaling.SEED).shuffle(order)
        self.assertEqual([q["id"] for q in plan["questions"]], [q["id"] for q in order])
        self.assertEqual([(a["name"], a["kind"], a["web"], a["engine"]) for a in plan["arms"]],
                         [("K0", "researcher", True, engines.CODEX), ("KF", "researcher", True, engines.CODEX)])
        self.assertEqual((plan["name"], plan["checker"], plan["stores"]),
                         ("a2-confirm-r1-s1", engines.CODEX, {"K0": self.pins["k0"], "KF": self.pins["kf"]}))
        self.assertEqual((pins["kind"], pins["tag"], pins["tagCommit"][:7], pins["promptVersion"], pins["k0"]),
                         ("driver", "study-freeze-4", "918a64c", ask.prompt_version(), self.pins["k0"]))
        current = read_json(run / "workspaces/KF/releases/current.json")["release_id"]
        self.assertEqual(current, self.pins["release"])  # the graph release linked from KF's frozen copy
        self.assertEqual(confirm.prepare_a2(into=self.into)["at"], layout["at"])  # fixed once written
        sharded = confirm.prepare_a2(shards=2, into=self.tmp / "sharded")
        self.assertEqual(sharded["folders"], ["r1-s1", "r1-s2"])
        second = read_json(self.tmp / "sharded" / confirm.A2 / "r1-s2/plan.json")["questions"]
        self.assertEqual([q["id"] for q in second], [q["id"] for q in order[1::2]])
        state = confirm.run_a2(into=self.into)
        self.assertEqual(state["status"], "completed")
        self.assertEqual([self.engine.calls.count(k) for k in ("research", "deposit", "check", "plain")],
                         [18, 18, 18, 0])
        self.assertEqual(len((run / "runs.jsonl").read_text().splitlines()), 1)
        _, rows = confirm.a2_rows(self.into)
        kf = [r for r in rows if r["arm"] == "KF"]
        self.assertEqual({(r["newTokens"], r["seconds"], r["depositSeconds"], r["totalSeconds"], r["webCalls"])
                          for r in kf}, {(1010 + 520, 3.0, 2.0, 5.0, 0)})  # both turns' new tokens
        self.assertEqual({r["newTokens"] for r in rows if r["arm"] == "K0"}, {2010 + 520})
        confirm.run_a2(into=self.into)  # resuming asks nothing again
        self.assertEqual(len(self.engine.calls), 54)

    def test_the_case_studies_run_once_more_scored_blind_and_the_report_judges_every_prediction(self):
        pins = confirm.prepare_cs(into=self.into)
        self.assertEqual((pins["kind"], pins["replicate"], pins["tag"]), ("case-studies", 6, "study-freeze-4"))
        others = {(s, a) for s, arms in pins["stores"].items() for a, fp in arms.items() if fp != self.pins["kf"]}
        self.assertEqual(others, {("cs3-screening", "R0")})  # every researcher copy is KF but the empty store
        with self.assertRaisesRegex(SystemExit, "settled"):
            confirm.score_cs(into=self.into)
        state = confirm.run_cs(into=self.into)
        self.assertEqual(state["status"], "completed")
        calls = list(self.engine.calls)
        self.assertEqual((calls.count("plain"), calls.count("check"), calls.count("score")), (11, 27, 4))
        self.assertTrue(all('"arm"' not in p and "finding:" not in p for p in self.engine.prompts))  # blind
        self.assertEqual(confirm.score_cs(into=self.into)["pending"], [])
        self.assertEqual(len(self.engine.calls), len(calls))  # everything was scored: no session
        confirm.prepare_a2(into=self.into)
        confirm.run_a2(into=self.into)
        value, out = confirm.report(self.into, self.tmp / "out")
        self.assertEqual(value["crossChecks"]["mismatches"], [])
        verdicts = {p["id"]: p["verdict"] for p in value["predictions"]}
        # KF is cheaper on every question (0.60 of K0), so mid and far are not flat; Part A's seconds were 60.
        self.assertEqual(verdicts, {"1": "met", "2": "not met", "3": "met", "4": "met", "5": "met"})
        self.assertEqual(value["decision"]["hold"], False)
        self.assertEqual(value["A2"]["byStratum"]["near"]["paired"]["tokens"]["median"], round(1530 / 2530, 3))
        self.assertEqual(value["partA"]["A2"]["byReplicate"]["KF"]["3"]["resultGiven"], 8)
        self.assertEqual(value["caseStudies"]["values"]["cs3"]["ranked"], {"R": [6], "R0": [2]})
        self.assertTrue((out / "results.md").read_text().startswith("# Confirmation run"))
        self.assertNotIn(str(self.tmp), (out / "results.json").read_text())
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["results.json", "results.md"])


class Predictions(unittest.TestCase):
    """The report's verdicts on a hand-made example, where every number is known."""

    def example(self):
        rows, theirs = [], []
        tokens = {"near": 20000, "mid": 48000, "far": 32000}
        for i in range(12):
            stratum = STRATA[i // 4]
            for arm in ("K0", "KF"):
                kf = arm == "KF"
                rows.append({"id": "q%d" % i, "stratum": stratum, "arm": arm, "replicate": 1, "folder": "r1-s1",
                             "answered": True, "checked": True, "contradicted": 3 if kf and i == 5 else 0,
                             "complete": True, "resultGiven": not (arm == "K0" and i == 11), "pass": True,
                             "accessUncertain": 0, "newTokens": tokens[stratum] if kf else 40000,
                             "webCalls": (2 if stratum == "near" else 6) if kf else 8, "findingCitations": int(kf),
                             "seconds": 50.0 if kf else 90.0, "depositSeconds": 30.0,
                             "totalSeconds": 80.0 if kf else 120.0,
                             "depositFailed": False, "parentInStore": None})
                theirs += [{"id": "q%d" % i, "stratum": stratum, "arm": arm, "replicate": r, "answered": True,
                            "checked": True, "resultGiven": True, "newTokens": 40000, "webCalls": 5,
                            "seconds": 100.0} for r in (1, 2, 3)]
        rows[7] = dict(rows[7], depositFailed=True, newTokens=None)  # q3's KF second turn reported no tokens
        a2 = {"byStratum": confirm.a2_summary(rows), "acrossRuns": confirm.across(rows, theirs)}
        part = {"median": 0.52, "low": 0.414, "high": 0.566, "n": 20}
        base = {"byStratum": {s: {"arms": {a: {"answered": 36, "contradicted": 0, "complete": 36, "resultGiven": 36,
                                               "meanWebCalls": 5.0}
                                           for a in ("K0", "KF")}, "paired": {"tokens": part, "webCalls": None}}
                              for s in STRATA + ("all",)},
                "byReplicate": {arm: {str(r): {"answered": 12, "resultGiven": n} for r, n in enumerate(given, 1)}
                                for arm, given in (("KF", (12, 11, 10)), ("K0", (12, 12, 12)))},
                "seconds": {"KF": {"answers": 36, "questions": 12, "median": 66.5},
                            "K0": {"answers": 36, "questions": 12, "median": 70.0}}}
        cases = {"replicates": [6], "cs1": {"uncitedValues": {"R": [1], "P": [5]}, "scored": {"R": [3], "P": [3]}},
                 "cs2": {"labelled": [2], "scored": [3], "answered": [3]},
                 "cs3": {"ranked": {"R": [9], "R0": [4]}, "scored": {"R": [2], "R0": [2]},
                         "newTokens": {"R": [100000], "R0": [150000]}, "answered": {"R": [2], "R0": [2]}},
                 "cs4": {"valueAsReported": [0], "scored": [9], "answered": [9]}}
        before = {"replicates": [1, 2, 3, 4, 5],
                  "cs1": {"uncitedValues": {"R": [2, 1, 13, 1, 7], "P": [14, 33, 21, 26, 28]}},
                  "cs2": {"labelled": [3] * 5}, "cs3": {"ranked": {"R": [8, 9, 9, 8, 9], "R0": [4, 3, 5, 5, 4]},
                                                        "newTokens": {"R": [1] * 5, "R0": [2] * 5}},
                  "cs4": {"valueAsReported": [0] * 5, "scored": [9] * 5}}
        return rows, a2, base, cases, before

    def judged(self, a2, base, cases, before):
        found = confirm.predictions({"A2": a2, "caseStudies": cases}, {"A2": base, "caseStudies": before})
        return found, {p["id"]: (p["verdict"], [q["met"] for q in p["parts"]]) for p in found}

    def test_each_prediction_with_its_numbers(self):
        rows, a2, base, cases, before = self.example()
        near = a2["byStratum"]["near"]
        self.assertEqual(near["paired"]["tokens"], {"n": 3, "median": 0.5, "low": 0.5, "high": 0.5})  # q3 left out
        self.assertEqual((near["arms"]["KF"]["depositFailed"], near["arms"]["KF"]["medianNewTokens"]), (1, 20000))
        self.assertEqual(a2["acrossRuns"]["KF"]["all"]["seconds"]["median"], 0.5)
        found, got = self.judged(a2, base, cases, before)
        self.assertEqual(got, {
            "1": ("met", [True, True, True]),  # near 0.50 (0.50–0.50); web 2 against 8
            "2": ("partly met", [True, False]),  # mid 1.20 lies above 1; far 0.80 (0.80–0.80) excludes it
            "3": ("partly met", [True, True, False, True]),  # KF has 3 contradicted statements; K0 11 ≥ 12 − 3
            "4": ("partly met", [True, False, True, True]),  # cs2: R labelled 2 of 3
            "5": ("met", [True])})  # 50 s against Part A's 66.5 s
        self.assertIn("KF/K0 near 0.50 (0.50–0.50) (Part A 0.52 (0.41–0.57))", found[0]["parts"][0]["numbers"])
        self.assertIn("Part A per replicate 12, 11, 10 of 12 each, mean 11.0, so at least 8.0",
                      found[2]["parts"][3]["numbers"])
        self.assertFalse(confirm.decision(found)["hold"])

    def test_all_four_hold_only_when_every_part_is_met_and_judged(self):
        rows, _, base, cases, before = self.example()
        rows = [dict(r, contradicted=0, newTokens=40000 if r["stratum"] == "far" else r["newTokens"]) for r in rows]
        a2 = {"byStratum": confirm.a2_summary(rows), "acrossRuns": confirm.across(rows, [])}
        cases = dict(cases, cs2=dict(cases["cs2"], labelled=[3]))
        found, got = self.judged(a2, base, cases, before)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"1": "met", "2": "met", "3": "met", "4": "met",
                                                             "5": "met"})
        self.assertEqual(confirm.decision(found)["hold"], True)
        unscored = dict(cases, cs4=dict(cases["cs4"], scored=[8]))  # one cs4 answer left unscored, none with a value
        found, got = self.judged(a2, base, unscored, before)
        self.assertEqual(got["4"], ("not judged", [True, True, True, None]))
        self.assertFalse(confirm.decision(found)["hold"])
        found, got = self.judged(None, base, None, before)
        self.assertEqual({k: v[0] for k, v in got.items()}, dict.fromkeys("12345", "not judged"))
        stopped = dict(a2, complete={"folders": {"r1-s1": {"state": "stopped"}}})  # A2 is judged once it has finished
        found, got = self.judged(stopped, base, cases, before)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"1": "not judged", "2": "not judged", "3": "not judged",
                                                             "4": "met", "5": "not judged"})
        self.assertTrue(found[0]["note"].startswith("A2 has not finished (r1-s1 stopped)"))


if __name__ == "__main__":
    unittest.main()
