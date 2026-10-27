"""A4's results (part_a/a4_results.py) and Figure 4b (figures/fig4b.py) from small synthetic records in a temporary
folder: A4's ladder (4 parents × 3 rungs, 2 replicates) and A2's K0 and KF arms (3 questions per stratum, 3
replicates, beside a plain arm that must be ignored), laid out as the harness writes them, and A1's campaign revisits.
The verdicts follow the rules in `predictions`; the figure carries KF's pins and a caption whose numbers are the
results'. No engine, store or network; nothing is written under .oopc/.

    python -B -m unittest discover -s studies/macromolecules/tests -p "test_figures_a4.py"
"""
import json, math, sys, tempfile, unittest
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY / "figures"))
try:
    import style as S  # noqa: E402,F401  (imports common and analysis.kf)
    import fig4b  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
from analysis import kf  # noqa: E402
from part_a import a4_results  # noqa: E402

PINS = {"promptVersion": kf.PROMPT, "release": kf.RELEASE_ID, "knowledgeSnapshot": kf.SNAPSHOT_ID, "kf": kf.FINGERPRINT,
        "models": a4_results.MODELS, "tag": kf.TAG, "tagCommit": a4_results.TAG_COMMIT + "aaaaaaaaa",
        "checker": "codex", "harness": {"revision": "c" * 40}, "at": "2026-10-19T08:00:00+00:00"}
STORES = {"K0": {"findings": 150, "notes": 160}, "KF": kf.FINGERPRINT}
LADDER = {"exact": (0.30, (0, 1)), "paraphrase": (0.45, (1, 1)), "sibling": (0.50, (1, 2))}  # KF/K0 tokens; KF web
HELDOUT = {"near": (0.55, 2), "mid": (1.10, 5.4), "far": (0.95, 5.4)}  # KF/K0 tokens; KF web per answer
K0_TOKENS, K0_WEB = 50000, 6


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def item(question, arm, day, tokens, web, cited=(), contradicted=0):
    statements = [{"kind": "source-fact", "category": "bibliography", "verdict": "unsupported", "evidence": "live",
                   "statement": "Table 2 is on page 5.", "reason": "It is on page 6."}] * contradicted
    statements.append({"kind": "completeness", "category": "completeness", "verdict": "supported"})
    at = "%sT10:00:00+00:00" % day
    return {"question": question, "arm": arm, "attempts": [{"outcome": "completed"}] * 2,
            "answer": {"at": at, "engine": "codex", "model": "gpt-6.1-sol",
                       "answer": {"answer": "text", "citations": list(cited)},
                       "metrics": {"newTokens": round(tokens), "webCalls": web}},
            "check": {"at": at, "engine": "codex", "verdict": "fail" if contradicted else "pass",
                      "statements": statements, "resultGiven": True}}


def experiment(base, questions, replicates, arms, answer):
    """An experiment's folders r<k>-s1 with every arm's items, each from `answer(question, index, arm, replicate)`."""
    folders = ["r%d-s1" % k for k in range(1, replicates + 1)]
    write(base / "experiment.json", {"folders": folders})
    for k, name in enumerate(folders, 1):
        folder = base / name
        write(folder / "plan.json", {"questions": questions, "arms": [{"name": a} for a in arms],
                                     "stores": {a: STORES.get(a) for a in arms}})
        write(folder / "pins.json", dict(PINS, stores={a: STORES[a] for a in arms if a in STORES}))
        (folder / "runs.jsonl").write_text(json.dumps({"startedAt": "2026-10-19T09:00:00+00:00",
                                                       "finishedAt": "2026-10-19T12:00:00+00:00",
                                                       "status": "completed", "harness": PINS["harness"]}) + "\n")
        write(folder / "state.json", {"status": "completed", "failedItems": 0,
                                      "finishedAt": "2026-10-19T12:00:00+00:00"})
        for i, q in enumerate(questions):
            for arm in arms:
                write(folder / "items" / ("%04d-%s.json" % (i, arm)), answer(q, i, arm, k))


def records(root):
    parents = ["%012x%020x" % (0xabc000 + p, p) for p in range(4)]  # distinct in their first 12 characters
    ladder = [{"id": "a4-%s-%s" % (p[:12], rung), "stratum": rung, "kind": "property", "parent": p,
               "material": "polymer %d" % n, "property": "Tg"} for n, p in enumerate(parents) for rung in LADDER]

    def a4(q, i, arm, rep):
        day = "2026-10-%d" % (18 + rep)
        factor = 0.9 + 0.05 * (i // 3)  # per parent: the KF/K0 ratios differ a little between questions
        if arm == "K0":
            return item(q["id"], arm, day, K0_TOKENS, K0_WEB)
        ratio, web = LADDER[q["stratum"]]
        slip = 1 if q["stratum"] == "sibling" and i // 3 == 2 else 0  # one parent's sibling, both replicates
        return item(q["id"], arm, day, K0_TOKENS * ratio * factor, web[rep - 1],
                    cited=["finding:%s-1" % q["parent"][:12], "https://doi.org/10.1/x"], contradicted=slip)
    experiment(Path(root) / a4_results.LADDER, ladder, 2, ["K0", "KF"], a4)
    held = [{"id": "h-%s-%d" % (s, n), "stratum": s, "kind": "property", "material": "m", "property": "p"}
            for s in HELDOUT for n in range(3)]

    def a2(q, i, arm, rep):
        factor = 0.9 + 0.05 * (i % 3)
        ratio, web = HELDOUT[q["stratum"]]
        if arm == "KF":
            return item(q["id"], arm, "2026-10-19", K0_TOKENS * ratio * factor, web)
        return item(q["id"], arm, "2026-10-19", K0_TOKENS * (3 if arm == "P" else 1), 9 if arm == "P" else K0_WEB)
    experiment(Path(root) / a4_results.SCALING, held, 3, ["P", "K0", "KF"], a2)


def revisits(analysis):
    rung = {"pairs": 49, "medianTokenRatio": 0.628, "medianWebRatio": 0.267, "totalsTokenRatio": 0.653,
            "totalsWebRatio": 0.374, "noWeb": 16, "citingFindings": 45}
    write(Path(analysis) / a4_results.REVISITS, {"meta": dict(kf.meta("test"), builtAt="2026-10-19T00:00:00+00:00"),
                                                 "summary": {"campaignByType": {r: rung for r in LADDER}}})


class A4Tests(unittest.TestCase):

    def test_results_from_records_then_figure_4b(self):
        with tempfile.TemporaryDirectory(prefix="oopc-a4-test-") as folder:
            root, analysis = Path(folder) / "harness", Path(folder) / "analysis"
            records(root)
            revisits(analysis)
            value = a4_results.build(root, analysis)
            a4, a2 = value["A4"], value["A2"]
            self.assertEqual(len(a4["rows"]), 12 * 2 * 2)
            self.assertEqual(len(a2["rows"]), 9 * 3 * 2)  # the plain arm is not read
            exact = a4["byRung"]["exact"]
            self.assertEqual((exact["arms"]["KF"]["noWeb"], exact["arms"]["K0"]["noWeb"]), (4, 0))
            self.assertEqual(exact["arms"]["KF"]["citingParentFindings"], 8)
            # KF/K0 per question 0.30 × (0.90, 0.95, 1.00, 1.05); the median of four: the middle two's geometric mean
            self.assertAlmostEqual(exact["paired"]["tokens"]["median"], round(0.30 * math.sqrt(0.95), 3), places=3)
            self.assertEqual(exact["paired"]["webRatio"], round(0.5 / K0_WEB, 3))
            interval = a4["byRung"]["sibling"]["paired"]["webRatioInterval"]
            self.assertLessEqual(interval["low"], interval["ratio"])
            self.assertLessEqual(interval["ratio"], interval["high"])
            self.assertEqual(a4["byRung"]["sibling"]["arms"]["KF"]["contradicted"], 2)
            self.assertEqual(a4["carried"]["statements"], 2)
            self.assertEqual(a4["carried"]["others"], {"exact": 0, "paraphrase": 0, "sibling": 0})
            self.assertEqual(a4["records"]["harnessRevisions"], ["c" * 12])
            self.assertEqual(a4["records"]["harnessCodeChanges"], [])
            self.assertEqual(a2["byStratum"]["near"]["paired"]["webRatio"], round(2 / K0_WEB, 3))
            verdicts = {p["id"]: p["verdict"] for p in value["predictions"]}
            self.assertEqual(verdicts, {"A4.1": "partly met",   # sibling has 2 more contradicted statements
                                        "A4.2": "met",          # 0.29, 0.44, 0.49 against near 0.52
                                        "A4.3": "partly met",   # web below tokens, but 8 answers cannot reach 20
                                        "A4.4": "met"})
            problems = value["crossChecks"]["mismatches"]
            self.assertEqual([m["what"] for m in problems], ["part_a report"])  # none written here; pins all hold
            out = a4_results.write(value, analysis / "a4")
            text = (out / "results.md").read_text()
            self.assertIn("**A4.4, met.**", text)
            self.assertIn("| near (A2) | 3 × 3 |", text)
            figures = Path(folder) / "figures"
            entry = fig4b.render(analysis, figures)
            manifest = json.loads((figures / "manifest.json").read_text())
            for name in entry["panels"][0]["files"]:
                self.assertTrue((figures / name).stat().st_size > 1000)
        self.assertEqual(entry["panels"][0]["files"], ["fig4b_ladder.pdf", "fig4b_ladder.svg", "fig4b_ladder.png"])
        self.assertIn("fig4b", manifest["figures"])
        self.assertEqual(entry["pins"]["knowledgeSnapshot"], kf.SNAPSHOT_ID)
        self.assertEqual(entry["pins"]["records"]["A4"]["folders"], ["r1-s1", "r2-s1"])
        caption = entry["panels"][0]["caption"]
        t, w = exact["paired"]["tokens"], exact["paired"]["webRatioInterval"]
        self.assertIn("exact %.2f (%.2f-%.2f) and %.2f (%.2f-%.2f)" % (t["median"], t["low"], t["high"], w["ratio"],
                                                                      w["low"], w["high"]), caption)
        self.assertIn("without the web in 4 of 8, 0 of 8, 0 of 8, 0 of 9, 0 of 9, 0 of 9 answers", caption)
        self.assertIn("tokens 0.63, 0.63, 0.63", caption)

    def test_figure_refuses_question_ratios_that_do_not_give_the_median(self):
        with tempfile.TemporaryDirectory(prefix="oopc-a4-test-") as folder:
            root, analysis = Path(folder) / "harness", Path(folder) / "analysis"
            records(root)
            revisits(analysis)
            value = a4_results.build(root, analysis)
            value["A4"]["byRung"]["paraphrase"]["paired"]["questionTokenRatios"][-1] *= 10
            value["A4"]["byRung"]["paraphrase"]["paired"]["questionTokenRatios"][-2] *= 10
            a4_results.write(value, analysis / "a4")
            with self.assertRaises(SystemExit):
                fig4b.render(analysis, Path(folder) / "figures")

    def test_campaign_records_not_built_on_kf_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="oopc-a4-test-") as folder:
            write(Path(folder) / a4_results.REVISITS, {"meta": {"knowledgeSnapshot": "another"}, "summary": {}})
            with self.assertRaises(SystemExit):
                a4_results.campaign(folder)


if __name__ == "__main__":
    unittest.main()
