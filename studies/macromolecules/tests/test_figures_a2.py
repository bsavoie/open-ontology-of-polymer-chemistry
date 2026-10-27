"""A2, A3 and E8's results (part_a/a2a3e8_results.py) and Figure 4a and 4c (figures/fig4ac.py), offline: small
synthetic answer rows for the three experiments, reported as `part_a.py report` reports them (the harness's own
`summary`, `estimate.paired` and `estimates`), then the results built from those records and the figure drawn from the
results, all in a temporary folder. When the real reports are present (OOPC_STUDY_ROOT naming the main checkout), the
results are also built from them (read only) and checked against the reports. Nothing is written under .oopc/."""
import json, math, random, sys, tempfile, unittest
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY / "figures"))
try:
    import style as S  # noqa: E402  (imports common and analysis.kf)
    import fig4ac  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
from analysis import kf  # noqa: E402
from part_a import a2a3e8_results as results, estimate, part_a  # noqa: E402

STRATA = {"near": 6, "mid": 4, "far": 4}  # questions per stratum
FINDINGS = {"K0": 150, "KF200": 532, "KF1": 2170, "KF2": 5021, "KF": 8899, "MF1": 2170, "MF": 8899}
NEAR_TOKENS = {"P": 0.9, "K0": 1.0, "KF200": 1.0, "KF1": 1.05, "MF1": 0.6, "MF": 0.55}  # KF2 and KF by parent


def questions():
    out = []
    for stratum, n in STRATA.items():
        out += [{"id": "%s-%d" % (stratum, i), "stratum": stratum, "base": 30000 + 2000 * i} for i in range(n)]
    return out


def row(experiment, q, arm, replicate, rng, *, factor, findings, parent, web=True, web_calls=6, contradicted=0,
        access=0, result=True, citations=0):
    tokens = round(q["base"] * factor * math.exp(rng.gauss(0, 0.04)))
    return {"id": q["id"], "stratum": q["stratum"], "kind": "property", "experiment": experiment,
            "replicate": replicate, "folder": "r%d-s1" % replicate, "arm": arm, "web": web, "storeFindings": findings,
            "answered": True, "checked": True, "newTokens": tokens, "webCalls": web_calls if web else 0,
            "seconds": round(tokens / 400, 2), "findingCitations": citations, "parentInStore": parent,
            "contradicted": contradicted, "accessUncertain": access, "complete": True, "resultGiven": result,
            "pass": result and not contradicted and not access}


def a2_rows():
    rng, rows = random.Random(3), []
    for replicate in (1, 2, 3):
        for q in questions():
            near, i = q["stratum"] == "near", int(q["id"].split("-")[1])
            for arm in ("P", "K0", "KF200", "KF1", "KF2", "KF", "MF1", "MF"):
                parent = None if arm == "P" else near and (arm in ("KF", "MF") or (arm == "KF2" and i < 3))
                factor = (0.5 if parent else 1.05) if arm in ("KF2", "KF") and near else NEAR_TOKENS.get(arm, 1.0)
                web = arm not in ("MF1", "MF")
                rows.append(row("A2", q, arm, replicate, rng, factor=factor, findings=FINDINGS.get(arm),
                                parent=parent, web=web, web_calls=1 if parent else 6,
                                contradicted=int(arm == "MF1" and near and i == 0 and replicate == 1),
                                access=int(arm == "P" and i % 2 == 0 or arm == "KF" and near and i == 5
                                           and replicate == 2), result=web or bool(parent),
                                citations=2 if parent or (arm == "MF1" and near) else 0))
    return rows


def a3_rows():
    rng, rows = random.Random(5), []
    parents = {100: 1, 200: 2, 400: 3, 800: 6}
    arms = [("K0", 150, 0), ("KF", 8899, 6)] + [("R%d-s%d" % (z, s), 9 * z + 30 * s, parents[z] - (s == 1 and z > 100))
                                               for s in range(1, 6) for z in (100, 200, 400, 800)]
    for q in questions():
        near, i = q["stratum"] == "near", int(q["id"].split("-")[1])
        for arm, findings, parents in arms:
            parent = near and i < parents
            rows.append(row("A3", q, arm, 1, rng, factor=0.5 if parent else 1.0, findings=findings, parent=parent,
                            web_calls=0 if parent else 5, contradicted=int(arm == "R400-s2" and near and i == 1),
                            citations=1 if parent else 0))
    return rows


def e8_rows():
    rng, rows = random.Random(7), []
    for q in questions()[:STRATA["near"]]:
        i = int(q["id"].split("-")[1])
        for arm, findings in (("K0c", 150), ("KFc", 8899)):
            kfc = arm == "KFc"
            rows.append(row("E8", q, arm, 1, rng, factor=0.7 if kfc else 1.0, findings=findings, parent=kfc,
                            web_calls=2 if kfc else 10, contradicted=int(i < 2) if not kfc else int(i == 0),
                            access=int(not kfc), citations=3 if kfc else 0))
    return rows


def report(experiment, rows):
    """`report.json` as `part_a.report` writes it, from rows instead of driver folders."""
    spec = part_a.EXPERIMENTS[experiment]
    folders = sorted({r["folder"] for r in rows})
    value = {"experiment": experiment, "reference": spec["reference"], "at": "2026-10-20T00:00:00+00:00",
             "folders": {f: {"items": sum(r["folder"] == f for r in rows), "done": sum(r["folder"] == f for r in rows),
                             "failed": 0, "state": "completed", "stopReason": None} for f in folders},
             "byStratum": {}}
    for stratum in list(dict.fromkeys(r["stratum"] for r in rows)) + ["all"]:
        mine = [r for r in rows if stratum == "all" or r["stratum"] == stratum]
        arms = list(dict.fromkeys(r["arm"] for r in mine))
        value["byStratum"][stratum] = {
            "arms": part_a.summary(mine),
            "paired": {a: estimate.paired(mine, a, spec["reference"]) for a in arms if a != spec["reference"]},
            "pairs": {"%s/%s" % pair: estimate.paired(mine, *pair) for pair in spec["pairs"]}}
    value["estimates"] = part_a.estimates(experiment, rows)
    if experiment == "A3":
        value["storeFindings"] = {r["arm"]: r["storeFindings"] for r in rows if r["arm"] not in ("K0", "KF")}
    return value, folders


def write(root, experiment, rows):
    base = Path(root) / results.FOLDERS[experiment]
    value, folders = report(experiment, rows)
    for name in folders:
        (base / name / "items").mkdir(parents=True)
        (base / name / "pins.json").write_text(json.dumps({
            "tagCommit": "1c06a7f", "promptVersion": kf.PROMPT, "kind": "driver", "code": "/Users/someone/freeze",
            "harness": {"revision": "abc1234", "clean": True, "path": "/Users/someone/harness"}}))
    (base / "experiment.json").write_text(json.dumps({"answers": len(rows), "folders": folders,
                                                      "replicates": len(folders)}))
    (base / "report.json").write_text(json.dumps(value))
    (base / "rows.json").write_text(json.dumps(rows))
    return base


class SyntheticTests(unittest.TestCase):
    def test_results_from_synthetic_records_then_figure_4a_and_4c(self):
        with tempfile.TemporaryDirectory(prefix="oopc-a2a3e8-test-") as folder:
            root = Path(folder) / "harness"
            write(root, "A2", a2_rows())
            write(root, "A3", a3_rows())
            e8 = write(root, "E8", e8_rows())
            (e8 / "r1-s1/items/0000-K0c.json").write_text(json.dumps({"check": {"verdict": "fail", "statements": [
                {"verdict": "unsupported", "category": "inference", "kind": "inference"},
                {"verdict": "unsupported", "category": "source-access", "kind": "source-fact"},
                {"verdict": "supported", "kind": "source-fact"}]}}))
            value = results.build(root)
            self.assertEqual(value["crossChecks"]["mismatches"], [])
            A2, A3, E8 = value["A2"], value["A3"], value["E8"]
            self.assertEqual(A2["complete"]["rows"], 3 * 14 * 8)
            near = A2["byStratum"]["near"]
            self.assertLess(near["paired"]["KF"]["tokens"]["median"], 0.6)
            self.assertIsNotNone(near["paired"]["KF"]["seconds"])  # the time ratio, added
            self.assertEqual(near["arms"]["MF1"]["contradicted"], 1)
            self.assertEqual(A2["estimates"]["split"]["n"], [3, 3])
            self.assertEqual(A2["nonPasses"]["P"]["all"]["accessUncertainOnly"], A2["nonPasses"]["P"]["all"]["nonPasses"])
            self.assertEqual(A3["bySize"]["800"]["nearParents"], [5, 6, 6, 6, 6])
            self.assertEqual(A3["stores"]["R400-s2"]["byStratum"]["all"]["contradicted"], 1)
            self.assertIn("near/R100", A3["estimates"]["seedSpread"])
            self.assertTrue(E8["sameQuestionsAsA2Near"])
            self.assertEqual(E8["byStratum"]["near"]["arms"]["K0c"]["contradicted"], 2)
            self.assertEqual(E8["contradictedKinds"]["K0c"]["contradicted"], {"inference/inference": 1})
            verdicts = {p["id"]: p["verdict"] for p in value["predictions"]}
            self.assertEqual(len(verdicts), 14)
            self.assertEqual(verdicts["E8-1"], "partly met")  # K0c's 2 contradicted statements; KFc's results kept
            self.assertEqual(verdicts["E8-3"], "not judged")
            a31 = next(p for p in value["predictions"] if p["id"] == "A3-1")
            self.assertEqual([q["met"] for q in a31["parts"]], [True, True, False])  # 14 answers per arm, not 57
            kf_near = [q for q in next(p for p in value["predictions"] if p["id"] == "A2-3")["parts"]][0]
            self.assertTrue(kf_near["met"])
            out = results.write(value, Path(folder) / "analysis/a2a3e8")
            text = (out / "results.md").read_text()
            self.assertIn("**E8-1, partly met.**", text)
            self.assertNotIn("/Users/", (out / "results.json").read_text())  # the folders' local paths left out
            entry = fig4ac.render(Path(folder) / "analysis", Path(folder) / "figures")
            figures = Path(folder) / "figures"
            for name in [f for p in entry["panels"] for f in p["files"]] + entry["assembled"]["files"]:
                self.assertGreater((figures / name).stat().st_size, 1000, name)
            self.assertIn(kf.SNAPSHOT_ID.encode(), (figures / "fig4a.pdf").read_bytes())
            manifest = json.loads((figures / "manifest.json").read_text())
        captions = {p["panel"]: p["caption"] for p in entry["panels"]}
        self.assertEqual(list(captions), ["4a", "4c"])
        self.assertIn("near %s" % fig4ac.ci(near["paired"]["KF"]["tokens"]), captions["4a"])
        self.assertIn("contradicted statements 2 and 1 (in 2 and 1 answers", captions["4a"])
        self.assertIn("8,899", captions["4c"])
        self.assertIn("A3 1 in 308 answers", captions["4c"])
        self.assertEqual(manifest["figures"]["fig4ac"]["pins"]["knowledgeSnapshot"], kf.SNAPSHOT_ID)
        self.assertEqual(manifest["figures"]["fig4ac"]["pins"]["records"]["A2"]["harnessRevisions"], ["abc1234"])

    def test_inputs_not_built_on_kf_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="oopc-a2a3e8-test-") as folder:
            path = Path(folder) / "analysis/a2a3e8/results.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"meta": {"knowledgeSnapshot": "oopc-knowledge-other"}}))
            with self.assertRaises(SystemExit):
                fig4ac.render(Path(folder) / "analysis", Path(folder) / "figures")
            self.assertFalse((Path(folder) / "figures").exists())


@unittest.skipUnless((S.common.run_dir("2026-10-kf-e8") / "report.json").exists(), "the A2/A3/E8 reports are not here")
class RealDataTests(unittest.TestCase):
    """The results from the real reports and rows (read only), checked against the reports' own numbers."""

    def test_results_agree_with_the_reports(self):
        value = results.build()
        self.assertEqual(value["crossChecks"]["mismatches"], [])
        a2 = json.loads((S.common.run_dir("2026-10-kf-scaling") / "report.json").read_text())
        self.assertEqual(value["A2"]["byStratum"]["near"]["paired"]["KF"]["tokens"],
                         a2["byStratum"]["near"]["paired"]["KF"]["tokens"])
        self.assertEqual(value["A2"]["estimates"]["slope"], a2["estimates"]["slope"])
        self.assertEqual({p["id"] for p in value["predictions"]},
                         {"A2-%d" % i for i in range(1, 8)} | {"A3-%d" % i for i in range(1, 5)} |
                         {"E8-%d" % i for i in range(1, 4)})


if __name__ == "__main__":
    unittest.main()
