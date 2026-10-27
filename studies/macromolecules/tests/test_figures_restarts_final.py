"""Part B's final evaluation analysis (recursive/final_results.py) and its figure (figures/fig_restarts_final.py),
offline: the analysis's pure rules on small inputs (the dose read from a trace, the hierarchical bootstrap, the arm
lookup, the verdicts) and the figure drawn from a small synthetic results file, all in a temporary folder. When the
real results are present (OOPC_STUDY_ROOT naming the main checkout), the figure's caption is also checked against them.
No store, engine or network is touched and nothing is written under .oopc/.

    python -B -m unittest discover -s studies/macromolecules/tests -p "test_figures_restarts_final.py"
"""
import json, math, sys, tempfile, unittest
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY / "figures"))
sys.path.insert(0, str(STUDY / "recursive"))
try:
    import style as S  # noqa: E402  (imports common and analysis.kf)
    import fig_restarts_final as fig  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
import final_results as F  # noqa: E402

RESTARTS = F.RESTARTS
ADOPTED = {"R1": [2], "R2": [4, 5], "R3": [1, 2], "R4": [2, 3, 5], "R5": [2, 4, 5]}


def arm_names():
    names = ["E0"]
    for r in RESTARTS:
        names += ["%s-P0-S%d" % (r, k) for k in range(1, 6)]
        names += ["%s-P%d-S%d" % (r, k, k) for k in range(1, 6) if any(a <= k for a in ADOPTED[r])]
        names.append("%s-P5-S0" % r)
    return names


def interval(estimate, half):
    return {"estimate": estimate, "low": round(estimate - half, 3), "high": round(estimate + half, 3), "n": 100}


def ratio_interval(estimate, factor=1.2):
    return {"estimate": estimate, "low": round(estimate / factor, 3), "high": round(estimate * factor, 3), "n": 100}


def synthetic():
    """A results file with the keys the figure reads: near questions halve in cost from S0 to S5, mid rise by a half,
    far stay flat; every arm has 0 or 1 contradicted statement."""
    names = arm_names()
    strata = ("all", "near", "mid", "far")
    arms = {}
    for i, name in enumerate(names):
        arms[name] = {s: {"contradicted": i % 2 if s == "all" else 0, "resultGiven": 55 + i % 5, "pass": 54 + i % 6,
                          "complete": 60 - i % 2, "meanWebCalls": 6.0, "medianTokens": 40000} for s in strata}
    shape = {"near": lambda k: 1 - 0.1 * k, "mid": lambda k: 1 + 0.1 * k, "far": lambda k: 1.0}
    web = {"near": lambda k: 6 - k, "mid": lambda k: 5 + 0.2 * k, "far": lambda k: 7.0}
    growth = {}
    for j, r in enumerate(RESTARTS):
        growth[r] = [dict({"store": k, "findings": 900 * k + 10 * j},
                          **{s: {"tokens": {"median": round(shape[s](k) * (1 + 0.02 * j), 3)},
                                 "counts": {"meanWebCalls": web[s](k) + 0.1 * j}} for s in F.STRATA})
                     for k in range(6)]
    mean = [dict({"store": k, "findings": 900 * k + 20},
                 **{s: {"meanWebCalls": {"mean": round(web[s](k) + 0.2, 4)}} for s in F.STRATA}) for k in range(6)]
    pooled = {"S%d" % k: {s: {"tokens": ratio_interval(round(shape[s](k), 3)),
                              "webCalls": interval(round(web[s](k) - web[s](0), 3), 1.5)} for s in F.STRATA}
              for k in range(1, 6)}
    per_store = {}
    for k in range(1, 6):
        per_store["S%d" % k] = {"split": {
            "with": {"answers": 20 * k, "tokens": ratio_interval(0.45), "webCalls": interval(-4.0, 2.0)},
            "without": {"answers": 100 - 20 * k, "tokens": ratio_interval(1.3) if k < 5 else None,
                        "webCalls": interval(1.0, 2.0) if k < 5 else None}}}
    effects = {"knowledge": (0.9, 0.5, -1.5, -4.0), "prompt": (1.0, 1.0, 0.0, 0.3), "system": (0.95, 0.55, -1.6, -4.2),
               "promptOnGrown": (1.0, 1.0, -0.1, -0.2), "storeUnderP5": (1.0, 0.56, -1.7, -4.6)}
    crossing = {}
    for key, (t_all, t_near, w_all, w_near) in effects.items():
        values = {"all": (t_all, w_all), "near": (t_near, w_near), "mid": (1.5, 0.5), "far": (0.95, -1.0)}
        crossing[key] = {
            "pooled": {s: {"tokens": ratio_interval(t), "webCalls": interval(w, 1.0)} for s, (t, w) in values.items()},
            "perRestart": {s: {r: {"tokens": {"median": round(t * (1 + 0.03 * (j - 2)), 3)},
                                   "webCalls": {"mean": round(w + 0.2 * (j - 2), 3)}} for j, r in enumerate(RESTARTS)}
                           for s, (t, w) in values.items()}}
    pins = {"tag": "1c06a7f", "code": "1c06a7faaab3", "harness": "fbd85f9ac679", "promptP0": "0b7bb1483235",
            "preparedAt": "2026-10-20T23:30:45+00:00", "models": {"codex": "gpt-6.1-sol"}, "checker": "codex",
            "restarts": {r: {"snapshots": {"S%d" % k: {"findings": 900 * k, "notes": 0, "sha256": "%s-%d" % (r, k)}
                                           for k in range(6)},
                             "prompts": {"P0": "0b7bb1483235"}, "adoptedRounds": ADOPTED[r]} for r in RESTARTS}}
    return {"meta": {"builder": "studies/macromolecules/recursive/final_results.py", "analysisRevision": "abc123",
                     "builtAt": "2026-10-21T00:00:00+00:00", "answers": 60 * len(names), "pins": pins},
            "arms": arms, "curves": {"growth": growth, "growthMean": mean, "growthPooled": pooled},
            "parents": {"perStore": per_store, "e0MeanWebCalls": 6.0}, "crossing": crossing,
            "contradicted": {"total": sum(a["all"]["contradicted"] for a in arms.values())},
            "predictions": [{"id": "2", "verdict": "partly met"}, {"id": "3", "verdict": "met"},
                            {"id": "4-heldout", "verdict": "met"}, {"id": "5", "verdict": "met"}],
            "crossChecks": {"count": 0, "mismatches": []}}


class AnalysisRules(unittest.TestCase):
    def test_dose_is_the_union_of_what_the_searches_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "payloads").mkdir()
            returns = [{"reviewed": [{"id": "finding:a"}], "added": [{"id": "finding:b"}, {"id": "finding:c"}],
                        "unreviewed": [], "notes": [{"id": "note:x"}]},
                       {"reviewed": [], "added": [{"id": "finding:b"}], "unreviewed": [{"id": "finding:d"}],
                        "notes": [{"id": "note:x"}, {"id": "note:y"}]}]
            lines = []
            for i, result in enumerate(returns):
                (run / "payloads" / ("h%d.json" % i)).write_text(json.dumps({"_access": {}, "result": result}))
                lines.append(json.dumps({"operation": "knowledge.search_knowledge", "status": "ok",
                                         "payload_hash": "h%d" % i}))
            lines.append(json.dumps({"operation": "graph.search", "status": "ok", "payload_hash": "other"}))
            (run / "events.jsonl").write_text("\n".join(lines) + "\n")
            self.assertEqual(F.dose(run), {"dose": 4, "doseFirst": 3, "doseNotes": 2, "searches": 2})
            self.assertEqual(F.dose(run / "missing"), {"dose": 0, "doseFirst": 0, "doseNotes": 0, "searches": 0})

    def test_hierarchical_bootstrap(self):
        cells = {(r, q): math.log(0.5) for r in RESTARTS for q in ("q1", "q2", "q3")}
        value = F.hier(cells, list(RESTARTS), ["q1", "q2", "q3"], F.statistics.median, math.exp)
        self.assertEqual((value["estimate"], value["low"], value["high"], value["n"]), (0.5, 0.5, 0.5, 15))
        spread = {(r, q): float(i) for i, r in enumerate(RESTARTS) for q in ("q1", "q2", "q3")}
        value = F.hier(spread, list(RESTARTS), ["q1", "q2", "q3"], F.statistics.mean)
        self.assertEqual(value["estimate"], 2.0)
        self.assertLess(value["low"], 2.0)
        self.assertGreater(value["high"], 2.0)
        self.assertIsNone(F.hier({("R1", "q1"): 1.0}, ["R1"], ["q1"], F.statistics.mean))

    def test_arms_and_slots(self):
        names = set(arm_names())
        self.assertEqual(len(names), 50)
        self.assertEqual(F.parse("E0"), (None, 0, 0))
        self.assertEqual(F.parse("R4-P3-S3"), ("R4", 3, 3))
        self.assertEqual(F.arm_of(names, "R1", 0, 0), "E0")
        self.assertEqual(F.arm_of(names, "R1", 1, 1), "R1-P0-S1")  # P1 equals P0 in R1: P0's arm
        self.assertEqual(F.system_arm(names, "R3", 1), "R3-P1-S1")
        self.assertEqual(F.system_arm(names, "R2", 3), "R2-P0-S3")
        self.assertEqual(F.arm_of(names, "R5", 5, 0), "R5-P5-S0")

    def test_verdicts_and_edits(self):
        part = F.part
        self.assertEqual(F.judge([part("a", True, ""), part("b", True, "")]), "met")
        self.assertEqual(F.judge([part("a", True, ""), part("b", False, "")]), "partly met")
        self.assertEqual(F.judge([part("a", False, "")]), "not met")
        self.assertTrue(F.below({"low": 0.4, "high": 0.9}, 1) and F.contains({"low": 0.8, "high": 1.2}, 1))
        edits = [{"restart": "R3", "edits": ["R3 r1"], "all": {"arm": {"contradicted": 2}, "reference": {"contradicted": 0}}},
                 {"restart": "R3", "edits": ["R3 r1", "R3 r2"], "all": {"arm": {"contradicted": 0},
                                                                        "reference": {"contradicted": 1}}},
                 {"restart": "R1", "edits": ["R1 r2"], "all": {"arm": {"contradicted": 0}, "reference": {"contradicted": 1}}}]
        for e in edits:
            e["arm"] = "x"
        alone = F.edit_alone(edits)
        self.assertEqual((alone["R3 r1"]["arm"], alone["R3 r1"]["reference"], alone["R3 r1"]["arms"]), (2, 0, 1))
        self.assertEqual(alone["R1 r2"]["reference"], 1)

    def test_spread_against_the_effect(self):
        cross = {key: {"perRestart": {s: {r: {"tokens": {"median": 0.5 + 0.01 * j}, "webCalls": {"mean": -4 + 0.1 * j}}
                                          for j, r in enumerate(RESTARTS)} for s in F.SUBSETS}}
                 for key in ("knowledge", "prompt", "system", "promptOnGrown")}
        cross["prompt"]["perRestart"]["near"]["R2"]["tokens"]["median"] = 1.3
        value = F.spread(cross)
        self.assertTrue(value["knowledge"]["near"]["tokens"]["sameSign"])
        self.assertTrue(value["knowledge"]["near"]["tokens"]["rangeBelowEffect"])
        self.assertFalse(value["prompt"]["near"]["tokens"]["sameSign"])


class Figure(unittest.TestCase):
    def test_drawn_from_synthetic_results(self):
        data = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "in"
            (inputs / "restarts-final").mkdir(parents=True)
            (inputs / fig.INPUT).write_text(json.dumps(data))
            out = Path(tmp) / "out"
            entry = fig.render(inputs, out)
            for name in entry["assembled"]["files"]:
                self.assertGreater((out / name).stat().st_size, 1000, name)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertIn(fig.NAME, manifest["figures"])
            text = entry["panels"][0]["caption"]
            self.assertIn("50 arms × 60 = 3,000 answers", text)
            self.assertIn("Near: 0.90, 0.80, 0.70, 0.60, 0.50 at S1–S5", text)
            self.assertIn("4, 8, 12, 16, 20 of 20", text)
            self.assertIn("2 partly met, 3 met, 4 (held-out half) met, 5 met", text)
            self.assertNotIn("/Users/", json.dumps(manifest))
            pinned = entry["pins"]
            self.assertEqual(set(pinned["restarts"]), set(RESTARTS))
            self.assertEqual(pinned["restarts"]["R2"]["snapshots"]["S3"], "R2-3")
            self.assertEqual(pinned["figureScript"], "studies/macromolecules/figures/fig_restarts_final.py")
            from PIL import Image
            with Image.open(out / (fig.NAME + ".png")) as image:
                self.assertIn("fbd85f9ac679", image.info.get("Pins", ""))

    def test_refuses_unpinned_or_mismatched_results(self):
        for change in ("pins", "mismatch"):
            data = synthetic()
            if change == "pins":
                data["meta"]["pins"]["restarts"].pop("R5")
            else:
                data["crossChecks"]["count"] = 1
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "restarts-final").mkdir()
                (Path(tmp) / fig.INPUT).write_text(json.dumps(data))
                with self.assertRaises(SystemExit, msg=change):
                    fig.load(tmp)

    def test_slots_skip_arms_whose_prompt_is_p0(self):
        groups = fig.slots(synthetic())
        self.assertEqual(len(groups), 12)
        system_s1 = [g for g in groups if g[0] == "Pk" and g[1] == "S1"][0]
        self.assertEqual(sorted(system_s1[2]), ["R3"])
        self.assertEqual(sum(len(g[2]) for g in groups), 50)

    @unittest.skipUnless((S.common.analysis_dir(fig.INPUT)).exists(), "no real results present")
    def test_caption_from_the_real_results(self):
        data = fig.load()
        text = fig.caption(data)
        self.assertIn("%d arms × 60" % len(data["arms"]), text)
        verdict = {p["id"]: p["verdict"] for p in data["predictions"]}["5"]
        self.assertIn("5 %s" % verdict, text)


if __name__ == "__main__":
    unittest.main()
