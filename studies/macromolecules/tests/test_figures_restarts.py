"""Part B's build (recursive/build_results.py) and its figure (figures/fig_restarts_build.py), offline: the build's
pure rules on small inputs, and the figure drawn from a small synthetic results file, all in a temporary folder. When
the real build is present (OOPC_STUDY_ROOT naming the main checkout), the figure's caption is also checked against it.
No store, engine or network is touched and nothing is written under .oopc/."""
import json, sys, tempfile, unittest
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY / "figures"))
sys.path.insert(0, str(STUDY / "recursive"))
try:
    import style as S  # noqa: E402  (imports common and analysis.kf)
    import fig_restarts_build as fig  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
import build_results as build  # noqa: E402

ORDER = ["Reviewed", "Added", "Needs checking", "Rejected"]


def key(doi, url):
    """The store's source key rule (freeze-2's knowledge.source_key), for tests that do not import the code."""
    import re
    doi = (doi or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    if doi:
        return "doi:" + doi
    url = re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).split("#")[0].split("?")[0].rstrip("/")
    return "url:" + url if url else ""


def snapshot(k, scale):
    findings = 9 * k * scale
    return {"findings": findings, "notes": findings // 3, "sources": findings // 4, "sourcesKeepingQuery": findings // 4 + 2,
            "polymers": int(140 * (1 - 0.5 ** k)), "tasksAnswered": 100 * k, "asTaken": True,
            "byStatus": {"Reviewed": findings // 5, "Added": findings - findings // 5 - k - 1, "Needs checking": k,
                         "Rejected": 1}, "fingerprint": {"findings": findings, "notes": findings // 3, "sha256": "%016d" % k}}


def synthetic():
    """Five restarts, five rounds, R3 with two fewer tasks answered; R1 adopts round 2's edit only, and so on."""
    decisions = {"R1": "rArrr", "R2": "rrrAA", "R3": "AArrr", "R4": "rAArA", "R5": "rArAA"}
    rules = [["fewer complete", "tokens > 1.10"], ["fewer sourced"], ["more contradicted"], ["fewer complete"]]
    restarts, pins = {}, {}
    for i, (name, ds) in enumerate(decisions.items()):
        scale = 100 + 5 * (i % 3)  # final stores 4,500-4,950 findings, within a fifth
        snaps = {"S%d" % k: snapshot(k, scale) for k in range(6)}
        if name == "R3":
            snaps["S5"]["tasksAnswered"] = 498
        curve = {"tasks": list(range(0, snaps["S5"]["tasksAnswered"] + 1))}
        total = snaps["S5"]["findings"]
        for s in ORDER:
            curve[s] = [round(snaps["S5"]["byStatus"][s] * x / curve["tasks"][-1]) for x in curve["tasks"]]
        curve["sources"] = [round(snaps["S5"]["sources"] * x / curve["tasks"][-1]) for x in curve["tasks"]]
        curve["polymers"] = [round(140 * (1 - 0.5 ** (x / 100))) for x in curve["tasks"]]
        curve["notes"] = [round(total / 3 * x / curve["tasks"][-1]) for x in curve["tasks"]]
        rounds = [{"round": r, "dev": {"adopted": d == "A", "rejectedBy": [] if d == "A" else rules[(r + i) % 4]}}
                  for r, d in enumerate(ds, 1)]
        restarts[name] = {"snapshots": snaps, "curve": curve, "rounds": rounds}
        pins[name] = {"tag": "1c06a7f", "promptVersion": "0b7bb1483235", "model": "gpt-6.1-sol",
                      "improverModel": "claude-opus-5-5", "release": "oopc-test", "seed": "seed-%s" % name,
                      "snapshots": {k: v["fingerprint"] for k, v in snaps.items()}, "prompts": {"P0": "0b7bb1483235"}}
    data = {"meta": {"builder": "studies/macromolecules/recursive/build_results.py", "analysisRevision": "abc123",
                     "builtAt": "2026-10-20T00:00:00+00:00", "pins": pins},
            "restarts": restarts, "crossChecks": {"count": 0, "mismatches": []}}
    data["predictions"] = {"1": build.prediction_one(restarts), "4-build": build.prediction_four_build(restarts)}
    data["convergence"] = {"rejectionsByRule": {}}
    for r in restarts.values():
        for row in r["rounds"]:
            for rule in row["dev"]["rejectedBy"]:
                data["convergence"]["rejectionsByRule"][rule] = data["convergence"]["rejectionsByRule"].get(rule, 0) + 1
    return data


class BuildRules(unittest.TestCase):
    def test_query_key_keeps_what_the_store_key_drops(self):
        self.assertEqual(key("", "https://www.example.org/a?doi=1#x"), "url:example.org/a")
        self.assertEqual(build.query_key("", "https://www.example.org/a?doi=1#x", key), "url:example.org/a?doi=1")
        self.assertEqual(build.query_key("10.1/X", "https://example.org/a?b", key), "doi:10.1/x")

    def test_flags_and_reasons(self):
        self.assertEqual(build.flag_kind("Converted or calculated"), "converted")
        self.assertEqual(build.flag_kind("Ambiguous polymer name: PBS could be X or Y"), "ambiguous polymer name")
        self.assertIsNone(build.flag_kind(""))
        self.assertEqual(build.reason_kind("but the supplied title misspells it"), "title differs")
        self.assertEqual(build.reason_kind("do not state the calculated 5.0 kJ/m² value"), "converted value not stated")
        self.assertEqual(build.reason_kind("does not identify the polymer as polyimide"), "material or property label")
        self.assertEqual(build.reason_kind("does not extend that protocol to Table 2"), "method, condition or scope")

    def test_check_measures_as_freeze_two_counts_them(self):
        check = {"verdict": "fail", "resultGiven": True, "statements": [
            {"kind": "source-fact", "verdict": "unsupported", "category": "attribution"},
            {"kind": "source-fact", "verdict": "unsupported", "category": "source-access"},
            {"kind": "completeness", "verdict": "unsupported", "category": "completeness"},
            {"kind": "inference", "verdict": "supported", "category": "none"}]}
        m = build.check_measures(check)
        self.assertEqual((m["contradicted"], m["complete"], m["accessUncertain"], m["pass"]), (2, False, 1, False))
        self.assertIsNone(build.check_measures({"error": {"reason": "timeout"}}))

    def test_fingerprint_of_the_empty_store(self):
        empty = build.fingerprint(None)
        self.assertEqual((empty["findings"], empty["notes"]), (0, 0))
        self.assertEqual(empty, build.fingerprint(Path(tempfile.gettempdir()) / "no-such-store.sqlite"))

    def test_predictions(self):
        data = synthetic()
        p1, p4 = data["predictions"]["1"], data["predictions"]["4-build"]
        self.assertEqual(p1["verdict"], "met")
        self.assertTrue(p1["parts"]["withinAFifth"])
        self.assertEqual(p4["adopted"], {"R1": 1, "R2": 2, "R3": 2, "R4": 3, "R5": 3})
        self.assertEqual((p4["verdict"], p4["total"], p4["proposed"]), ("met", 11, 25))
        climbing = synthetic()["restarts"]  # one restart's polymers still climbing: partly
        climbing["R2"]["snapshots"]["S5"]["polymers"] = 200
        p = build.prediction_one(climbing)
        self.assertEqual((p["verdict"], p["parts"]["steady"], p["parts"]["levelsOff"]), ("partly", True, False))
        stalled = synthetic()["restarts"]  # a round adds nothing, polymers jump and the store ends small: not met
        stalled["R2"]["snapshots"]["S5"] = dict(stalled["R2"]["snapshots"]["S4"], polymers=200, tasksAnswered=500)
        p = build.prediction_one(stalled)
        self.assertEqual((p["verdict"], p["parts"]), ("not met", {"steady": False, "levelsOff": False,
                                                                   "withinAFifth": False}))
        too_many = synthetic()["restarts"]
        for row in too_many["R1"]["rounds"]:
            row["dev"]["adopted"] = True
        self.assertEqual(build.prediction_four_build(too_many)["verdict"], "not met")


class Figure(unittest.TestCase):
    def test_drawn_from_synthetic_results(self):
        data = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "in"
            (inputs / "restarts-build").mkdir(parents=True)
            (inputs / fig.INPUT).write_text(json.dumps(data))
            out = Path(tmp) / "out"
            entry = fig.render(inputs, out)
            for name in entry["assembled"]["files"]:
                self.assertGreater((out / name).stat().st_size, 1000, name)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertIn(fig.NAME, manifest["figures"])
            text = entry["panels"][0]["caption"]
            self.assertIn("2,498 tasks answered", text)
            self.assertIn("11 of 25 adopted (1–3 per restart)", text)
            self.assertIn("Prediction 1 met", text)
            self.assertNotIn("/Users/", json.dumps(manifest))
            pinned = entry["pins"]
            self.assertEqual(set(pinned["restarts"]), set(data["restarts"]))
            self.assertEqual(pinned["restarts"]["R1"]["promptVersion"], "0b7bb1483235")
            self.assertEqual(pinned["figureScript"], "studies/macromolecules/figures/fig_restarts_build.py")
            from PIL import Image
            with Image.open(out / (fig.NAME + ".png")) as image:
                self.assertIn("seed-R3", image.info.get("Pins", ""))

    def test_refuses_unpinned_or_mismatched_results(self):
        for change in ("pins", "snapshot", "mismatch"):
            data = synthetic()
            if change == "pins":
                data["meta"]["pins"].pop("R5")
            elif change == "snapshot":
                data["restarts"]["R2"]["snapshots"]["S3"]["asTaken"] = False
            else:
                data["crossChecks"]["count"] = 1
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "restarts-build").mkdir()
                (Path(tmp) / fig.INPUT).write_text(json.dumps(data))
                with self.assertRaises(SystemExit, msg=change):
                    fig.load(tmp)

    def test_label_spreading_keeps_order_and_gap(self):
        placed = fig.spread_labels({"a": 10.0, "b": 10.5, "c": 30.0}, 2.0)
        self.assertLess(placed["a"], placed["b"])
        self.assertGreaterEqual(placed["b"] - placed["a"], 2.0 - 1e-9)

    @unittest.skipUnless((S.common.analysis_dir(fig.INPUT)).exists(), "no real build present")
    def test_caption_from_the_real_build(self):
        data = fig.load()
        text = fig.caption(data)
        p4 = data["predictions"]["4-build"]
        self.assertIn("%d of %d adopted" % (p4["total"], p4["proposed"]), text)


if __name__ == "__main__":
    unittest.main()
