"""The figure scripts (figures/fig3.py, fig4_records.py, fig5.py): every panel drawn from small synthetic inputs in a
temporary folder, with the pins in each file and a caption whose numbers are the inputs'; inputs not built on KF, and
revisit medians that disagree with their summary, are refused. Fig. 5's input is built by part_a/a5_results.py from
small synthetic A5 records, so the test runs both. When A1's real outputs are present (OOPC_STUDY_ROOT naming the
main checkout), both figures are also rendered from them into a temporary folder and their captions checked against
the panel index. Nothing is written under .oopc/."""
import csv, json, sys, tempfile, unittest
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY / "figures"))
try:
    import style as S  # noqa: E402  (imports common and analysis.kf)
    import fig3, fig4_records  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
from analysis import kf  # noqa: E402

STATUSES = ["Reviewed", "Added", "Needs checking", "Rejected"]
META = {"store": "KF", "knowledgeSnapshot": kf.SNAPSHOT_ID, "storeFingerprint": kf.FINGERPRINT,
        "graphRelease": kf.RELEASE_ID, "prompt": kf.PROMPT, "codeTag": kf.TAG, "analysisRevision": "abc123def456",
        "builder": "test", "builtAt": "2026-10-19T00:00:00+00:00"}
CLASSES = ["commodity thermoplastic", "elastomer", "thermoset"]


def write(folder, name, value):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if name.endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(value[0]))
            writer.writeheader()
            writer.writerows(value)
    else:
        path.write_text(json.dumps(dict(meta=META, **value)), encoding="utf-8")


def synthetic(folder):
    """A1's outputs for a store of 56 findings over 12 answers in three stages, 9 polymers in 3 classes."""
    points, total = [], dict.fromkeys(STATUSES, 0)
    for a in range(13):
        if a:
            total["Reviewed"] += 3
            total["Added"] += 1 + (a % 2)
            total["Needs checking"] += a == 5
            total["Rejected"] += a == 9
        points.append({"answer": a, "findings": dict(total, total=sum(total.values())), "notes": 2 * a + 3,
                       "sources": a + 2, "polymers": min(a, 8) + 1})
    runs = [{"run": "imported (0.11 records)", "answers": 0, "firstAnswer": 0, "lastAnswer": 0,
             "endState": {"findings": points[0]["findings"]}}]
    for name, first, last in (("200-task run", 1, 4), ("wave 1", 5, 8), ("wave 3", 9, 12)):
        runs.append({"run": name, "answers": last - first + 1, "firstAnswer": first, "lastAnswer": last,
                     "endState": {"findings": points[last]["findings"]}})
    write(folder, "dataset-kf/growth.json", {
        "answers": {"withDepositRow": 12}, "points": points, "byRun": runs,
        "markers": [{"kind": "prompt version", "answer": 5, "promptVersion": "aaaaaaaaaaaa"},
                    {"kind": "prompt version", "answer": 9, "promptVersion": "bbbbbbbbbbbb"},
                    {"kind": "model change", "answer": 9, "label": "m1 → m2"}]})
    polymers = [{"id": "wop-%06d" % i, "label": "Polymer %d" % i, "class": CLASSES[i % 3],
                 "findings": [0, 40, 3, 0, 12, 1, 7, 0, 25][i]} for i in range(9)]
    write(folder, "dataset-kf/coverage.json", {
        "classOrder": CLASSES, "polymers": polymers,
        "summary": {"polymers": 9, "withFindings": 6, "atLeast10": 3, "atLeast50": 0, "findingsWithoutPolymerId": 2,
                    "shareWithoutPolymerId": 0.0333},
        "classes": [{"class": k, "polymers": 3, "withFindings": sum(p["findings"] > 0 for p in polymers
                                                                     if p["class"] == k)} for k in CLASSES]})
    write(folder, "dataset-kf/sources.json", {
        "byType": [{"name": "journal article", "sources": 30, "yieldedFindings": 18},
                   {"name": "patent", "sources": 5, "yieldedFindings": 4},
                   {"name": "technical data sheet/manufacturer", "sources": 4, "yieldedFindings": 1}],
        "publicationYear": [{"year": y, "sources": 2 + y % 3, "yieldedFindings": 1 + y % 2} for y in range(2005, 2026)],
        "summary": {"sources": 39, "yieldedFindings": 23, "readWithoutFindings": 16, "sourcesWithYear": 30,
                    "yearRange": [2005, 2025], "medianYear": 2017}})
    write(folder, "dataset-kf/completeness.json", {
        "findings": 60, "fields": {k: {"share": s} for k, s in (("conditions", 0.95), ("locator", 1.0), (
            "excerpt", 0.9), ("unit", 0.8), ("numericValue", 0.85), ("polymerId", 0.967))},
        "spotChecksOfAdded": {"campaign": {"supported": {"total": 17}, "uncertain": {"total": 2},
                                           "unsupported": {"total": 1}}},
        "flaggedOutcomes": {"campaign": {"Reviewed": 9, "Added": 0, "Needs checking": 1, "Rejected": 1}}})
    write(folder, "properties-kf/meta.json", {})
    rows, classes = [], []
    for i, (k, cat, kind, n) in enumerate([(CLASSES[0], "mechanical", "material-property", 20),
                                           (CLASSES[0], "thermal-transitions", "material-property", 5),
                                           (CLASSES[1], "mechanical", "material-property", 3),
                                           (CLASSES[1], "test-conditions", "test-condition", 8),
                                           (CLASSES[2], "specimen-preparation", "specimen-or-preparation", 9),
                                           (CLASSES[2], "optical", "material-property", 1),
                                           (CLASSES[2], "method-instrument", "method-or-instrument", 12)]):
        rows.append({"subject": "wop-%06d" % i, "polymer_class": k, "property_class": cat + "-x", "category": cat,
                     "kind": kind, "findings": n})
        classes += [{"finding_id": "f%d-%d" % (i, j), "kind": kind, "property_class": cat + "-x"} for j in range(n)]
    classes += [{"finding_id": "g1", "kind": "other", "property_class": "unclassified"},
                {"finding_id": "g2", "kind": "test-condition", "property_class": "test-temperature"}]
    write(folder, "properties-kf/findings_by_subject_class.csv", rows)
    write(folder, "properties-kf/finding_classes.csv", classes)
    tg = [("wop-000001", 1, "DSC", "Reviewed", -40), ("wop-000001", 1, "DMA", "Added", -30),
          ("wop-000001", 1, "DSC", "Reviewed", -42), ("wop-000004", 2, "other", "Reviewed", 60),
          ("wop-000004", 2, "none", "Needs checking", 70), ("wop-000004", 2, "DSC", "Rejected", 65)]
    write(folder, "tg-landscape/tg_landscape.csv", [
        {"polymer_rank": rank, "polymer_id": p, "property": "Tg", "finding_id": "t%d" % i, "status": s, "value_c": v,
         "method": m} for i, (p, rank, m, s, v) in enumerate(tg)] + [
        {"polymer_rank": 2, "polymer_id": "wop-000004", "property": "Tm", "finding_id": "tm", "status": "Reviewed",
         "value_c": 220, "method": "DSC"}])
    write(folder, "tg-landscape/tg_landscape.json", {
        "polymers": [{"id": "wop-000001", "label": "Polymer 1", "medianTg": -40},
                     {"id": "wop-000004", "label": "Polymer 4", "medianTg": 65}],
        "dmaAboveDsc": {"polymers": 1, "dmaAbove": 1, "medianDifference": 11.0},
        "tgMethodSplit": {"DSC": 3, "DMA": 1, "other": 1, "none": 1}, "tgWithReadableValue": 6})
    pairs, summary = [], {}
    for rung, tokens, web in (("exact", [0.5, 0.6, 0.7, 2.4, 0.4], [0.0, 0.2, 0.3, None, 1.1]),
                              ("paraphrase", [0.8, 0.9, 0.7], [0.5, 0.6, 0.4]),
                              ("sibling", [0.3, 0.6, 0.5, 0.4], [0.0, 0.0, 0.2, 0.1])):
        pairs += [{"run": "campaign", "type": rung, "tokenRatio": t, "webRatio": w} for t, w in zip(tokens, web)]
        summary[rung] = {"pairs": len(tokens), "medianTokenRatio": round(sorted(tokens)[len(tokens) // 2], 3)
                         if len(tokens) % 2 else round(sum(sorted(tokens)[len(tokens) // 2 - 1:][:2]) / 2, 3)}
        known = sorted(w for w in web if w is not None)
        summary[rung]["medianWebRatio"] = round(known[len(known) // 2], 3) if len(known) % 2 else round(
            sum(known[len(known) // 2 - 1:][:2]) / 2, 3)
    pairs.append({"run": "run200", "type": "exact", "tokenRatio": 9.0, "webRatio": 9.0})
    write(folder, "loop-kf/revisits.json", {"pairs": pairs, "summary": {"campaignByType": summary}})
    write(folder, "loop-kf/reuse.json", {
        "ccdfReturnedSessions": {"points": [{"k": k, "findings": 60 // (k + 1), "share": (60 // (k + 1)) / 60}
                                            for k in range(8)]},
        "ccdfCitedAnswers": {"points": [{"k": k, "findings": max(0, 30 - 12 * k), "share": max(0, 30 - 12 * k) / 60}
                                        for k in range(4)]},
        "totals": {"findings": 60, "everReturnedShare": 0.5, "everCitedShare": 0.3, "citationsOfFindings": 41},
        "firstCitationLag": {"answers": {"median": 4}},
        "doseResponse": {"primary": {"bins": [{"bin": b, "firstAsks": 20, "citingFinding": c}
                                              for b, c in (("0", 2), ("1", 4), ("2-3", 7), ("4-6", 9), ("7+", 12))]}}})
    stage = {"promptVersions": {}, "models": {}, "answers": 10, "answersWithoutWeb": 0,
             "flagged": {"researcherFlaggedShare": 0.0}, "excerpts": {"emptyShare": 0.0}, "reviewPerResearchToken": 0}
    stages = {}
    for i, (s, prompt, model) in enumerate((("run200", "p1p1p1p1p1p1", "m1"), ("wave1", "p2p2p2p2p2p2", "m1"),
                                            ("wave2", "p3p3p3p3p3p3", "m1"), ("wave3", "p4p4p4p4p4p4", "m2"))):
        stages[s] = dict(stage, promptVersions={prompt: 10}, models={model: 10}, answersWithoutWeb=i,
                         flagged={"researcherFlaggedShare": [0.2, 0.5, 0.08, 0.13][i]},
                         excerpts={"emptyShare": [0.0, 0.25, 0.005, 0.06][i]},
                         reviewPerResearchToken=[0.2, 0.35, 0.13, 0.32][i])
    write(folder, "loop-kf/trajectory.json", {"stages": stages})


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-figures-test-")
        self.addCleanup(folder.cleanup)
        self.inputs, self.out = Path(folder.name) / "analysis", Path(folder.name) / "figures"
        synthetic(self.inputs)

    def test_figure_3_every_panel_with_pins_and_captions_from_the_data(self):
        entry = fig3.render(self.inputs, self.out)
        self.assertEqual([p["panel"] for p in entry["panels"]], ["3a", "3b", "3c", "3d", "3e", "3f"])
        for name in [f for p in entry["panels"] for f in p["files"]] + entry["assembled"]["files"]:
            self.assertGreater((self.out / name).stat().st_size, 1000, name)
        pdf = (self.out / "fig3d.pdf").read_bytes()
        self.assertIn(kf.SNAPSHOT_ID.encode(), pdf)
        self.assertIn(b"abc123def456", pdf)  # the input's analysis revision
        self.assertIn(kf.SNAPSHOT_ID, (self.out / "fig3d.svg").read_text())
        captions = {p["panel"]: p["caption"] for p in entry["panels"]}
        self.assertIn("56 findings", captions["3a"])
        self.assertIn("aaaaaaaaaaaa at 5", captions["3a"])
        self.assertIn("6 have findings", captions["3b"])
        self.assertIn("the 3 without findings", captions["3b"])
        self.assertIn("the 58 findings with a polymer id", captions["3c"])
        self.assertIn("2 polymers", captions["3d"])
        self.assertIn("Rejected 1", captions["3d"])  # drawn, and marked beyond its colour
        self.assertIn("DMA's median is above DSC's in 1, median difference +11.0", captions["3d"])
        self.assertIn("39 distinct sources", captions["3e"])
        self.assertIn("17 supported, 2 uncertain, 1 rejected", captions["3f"])
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["figures"]["fig3"]["pins"]["knowledgeSnapshot"], kf.SNAPSHOT_ID)

    def test_figure_4_records_panels_and_one_manifest_for_both(self):
        fig3.render(self.inputs, self.out)
        entry = fig4_records.render(self.inputs, self.out)
        captions = {p["panel"]: p["caption"] for p in entry["panels"]}
        self.assertIn("exact 0.60", captions["4b"])  # the campaign pairs only, not the 200-task repeat
        self.assertIn("1 ratios above 2", captions["4b"])
        self.assertIn("7+ 60% (12 of 20)", captions["4d"])
        self.assertIn("0 of 10 → 1 of 10 → 2 of 10 → 3 of 10", captions["4e"])
        self.assertIn("model m1 then m2", captions["4e"])
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(sorted(manifest["figures"]), ["fig3", "fig4_records"])
        self.assertTrue((self.out / "fig4_records.pdf").exists())

    def test_inputs_not_built_on_kf_are_refused(self):
        path = self.inputs / "loop-kf/reuse.json"
        value = json.loads(path.read_text())
        value["meta"]["knowledgeSnapshot"] = "oopc-knowledge-other"
        path.write_text(json.dumps(value))
        with self.assertRaises(SystemExit):
            fig4_records.render(self.inputs, self.out)
        self.assertFalse(self.out.exists())

    def test_revisit_medians_must_match_their_summary(self):
        path = self.inputs / "loop-kf/revisits.json"
        value = json.loads(path.read_text())
        value["summary"]["campaignByType"]["sibling"]["medianTokenRatio"] = 0.9
        path.write_text(json.dumps(value))
        with self.assertRaises(SystemExit):
            fig4_records.render(self.inputs, self.out)


def a5_records(root):
    """A5's records, small: five case-study replicates (cs1–cs4 with blind scores) and one E9 replicate, plus the
    2026-10-13 E9 run and its blind scores, laid out as the harness writes them under `root`."""
    def answer(tokens, web, cited=()):
        return {"answer": {"answer": "text", "citations": list(cited)},
                "metrics": {"newTokens": tokens, "webCalls": web}}

    def check(contradicted=0, uncertain=0, complete=True, result=True, verdict=None):
        statements = [{"kind": "inference", "category": "inference", "verdict": "unsupported"}] * contradicted
        statements += [{"kind": "source-fact", "category": "source-access", "verdict": "uncertain"}] * uncertain
        statements.append({"kind": "completeness", "category": "none",
                           "verdict": "supported" if complete else "unsupported"})
        return {"verdict": verdict or ("pass" if not contradicted and not uncertain else "fail"),
                "statements": statements, "resultGiven": result}

    studies = {"cs1-conditions": (["tpu", "fkm", "pva"], ["R", "P"]), "cs2-conflicts": (["pvdc", "phbv", "ppc"],
               ["R", "P"]), "cs3-screening": (["barrier", "biodegradable"], ["R", "R0", "P"]),
               "cs4-repeat": (["fepm-creep", "novoloid", "pox-loi"], ["R", "P"])}

    def blind(group, arm, i, rep):
        if group == "cs1-conditions":
            values = 6 if arm == "R" else 4
            return {"tgValues": values, "withMethod": values - 1, "withConditions": values - 2,
                    "bothDscAndDma": arm == "R" or i == 0, "uncitedValues": 1 if arm == "R" else 5}
        if group == "cs2-conflicts":
            return {"sourcedValues": 7 if arm == "R" else 9, "withConditions": 6 if arm == "R" else 8,
                    "explainsDifferences": True, "explanationLabelled": arm == "R", "uncitedValues": int(arm == "P")}
        if group == "cs3-screening":
            asked = 5 - i
            return {"polymersAsked": asked, "polymersRanked": asked, "likeForLikeStated": True, "uncitedValues": 2,
                    "rankedWithSourcedValue": asked - (arm == "R0") * 2 - (arm == "R" and rep == 2 and i == 0)}
        return {"saysNotFound": True, "givesValueAsReported": False, "offersLeads": True, "uncitedValues": 0}

    for rep, name in [(1, "2026-10-case-studies")] + [(r, "2026-10-case-studies-r%d" % r) for r in range(2, 6)]:
        base = Path(root) / name
        keys = {}
        for study, (questions, arms) in studies.items():
            group = "cs4" if study == "cs4-repeat" else study
            write(base / study, "plan.json", {"questions": [{"id": q, "question": q} for q in questions],
                                              "arms": [{"name": a} for a in arms], "promptVersion": "p",
                                              "models": {"codex": "m"}, "stores": {}})
            for i, q in enumerate(questions):
                for a in arms:
                    slip = 2 if (study, a, rep, i) == ("cs3-screening", "R", 2, 1) else 0
                    write(base / study, "items/%04d-%s.json" % (i, a), {"answer": answer(
                        40000 + 10000 * (a != "R") + 20000 * (a == "R0") + 1000 * i, 5 + 4 * (a != "R")),
                        "check": check(contradicted=slip, uncertain=int(a == "P")), "attempts": [{}]})
                    keys.setdefault(group, []).append((a, q, blind(group, a, i, rep)))
        write(base / "cs4-first", "plan.json", {"questions": [{"id": q, "question": q}
                                                              for q in studies["cs4-repeat"][0]]})
        for i, q in enumerate(studies["cs4-repeat"][0]):
            write(base / "cs4-first", "items/%s.json" % q, {"answer": answer(40000 + 2000 * i, 4),
                  "check": check(result=False), "deposit": {"findings": 0, "notes": i, "reviewStatus": "x"}})
            keys["cs4"].append(("first", q, blind("cs4", "first", i, rep)))
        for group, entries in keys.items():
            codes = {"%s-%02d" % (group, n): e for n, e in enumerate(entries, 1)}
            write(base / "scoring", "%s-key.json" % group, {"key": {c: {"arm": a, "question": q}
                                                                     for c, (a, q, _) in codes.items()}})
            write(base / "scoring", "%s.json" % group, {"engine": "claude-code", "model": "m", "attempts": 1,
                                                        "scores": [dict(b, code=c) for c, (_, _, b) in codes.items()]})
    cases = ["gross", "unit", "phase", "conditions", "subtle"]
    plants = [{"case": c, "id": "finding:%d" % i, "planted": "PLANTED", "true": "TRUE"} for i, c in enumerate(cases)]
    write(Path(root) / "2026-10-planted", "baseline.json", {"plants": plants})
    old_key, old_scores = {}, []
    for p in plants:
        for arm, reps in (("C", 1), ("A", 2), ("B", 2)):
            for r in range(reps):
                presents = arm == "A" and p["case"] in ("gross", "subtle")
                write(Path(root) / "2026-10-planted", "results/%s-%s%d-answer.json" % (p["case"], arm, r),
                      answer(30000, 2, [p["id"]]))
                write(Path(root) / "2026-10-planted", "results/%s-%s%d-check.json" % (p["case"], arm, r),
                      check(contradicted=int(presents)))
                code = "e9-%02d" % (len(old_key) + 1)
                old_key[code] = {"answer": "%s%d" % (arm, r + 1), "arm": arm, "question": p["case"]}
                old_scores.append({"code": code, "presentsPlanted": presents, "givesSource": not presents,
                                   "flagsPlanted": False})
    write(Path(root) / "2026-10-planted", "report.json", {"reviewerVerdicts": {
        c: {"status": "uncertain" if c in ("gross", "phase") else "unsupported"} for c in cases}})
    write(Path(root) / "2026-10-kf-a5/e9-2026-10-13/scoring", "e9-key.json", {"key": old_key})
    write(Path(root) / "2026-10-kf-a5/e9-2026-10-13/scoring", "e9.json", {"scores": old_scores})
    base, key, scores = Path(root) / "2026-10-planted-kf-r1", {}, []
    for part, names in (("before", ("C", "A1", "A2")), ("after", ("B1", "B2"))):
        write(base / part, "plan.json", {"questions": [{"id": "e9-" + c} for c in cases], "promptVersion": "p"})
        for i, p in enumerate(plants):
            for name in names:
                cited = [p["id"]] if name[0] in "CA" else []
                write(base / part, "items/%04d-%s.json" % (i, name), {"answer": answer(20000, 2, cited),
                      "check": check(contradicted=int(name[0] == "A" and p["case"] == "gross"))})
                code = "e9-%02d" % (len(key) + 1)
                key[code] = {"answer": name if name[1:] else name + "1", "arm": name[0], "question": p["case"]}
                scores.append({"code": code, "presentsPlanted": False, "flagsPlanted": name[0] == "A",
                               "givesSource": name[0] == "C" or (name[0] == "B" and p["case"] != "gross")})
    write(base, "review.json", {"verdicts": {c: {"status": "unsupported", "reason": "r"} for c in cases},
                                "skipped": [], "failures": []})
    write(base / "scoring", "e9-key.json", {"key": key})
    write(base / "scoring", "e9.json", {"engine": "claude-code", "model": "m", "attempts": 1, "scores": scores})


class A5Tests(unittest.TestCase):
    """A5's results from small synthetic records (part_a/a5_results.py), then Figure 5 drawn from them."""

    def test_results_from_records_then_figure_5(self):
        sys.path.insert(0, str(STUDY / "part_a"))
        import a5_results, fig5  # noqa: E402
        with tempfile.TemporaryDirectory(prefix="oopc-a5-test-") as folder:
            root = Path(folder) / "harness"
            a5_records(root)
            value = a5_results.build(root)
            cs, e9 = value["caseStudies"], value["e9"]
            self.assertEqual(cs["replicates"], [1, 2, 3, 4, 5])
            r2 = cs["byReplicate"]["cs3-screening"]["R"][1]
            self.assertEqual((r2["contradicted"], r2["answersContradicted"], r2["complete"]), (2, 1, 2))
            self.assertEqual(cs["byReplicate"]["cs1-conditions"]["P"][0]["accessUncertain"], 3)
            self.assertEqual(cs["overall"]["cs1-conditions"]["R"]["blind"]["uncitedValues"], 15)
            verdicts = {p["id"]: p["verdict"] for p in value["predictions"]}
            self.assertEqual(verdicts["cs1-a"], "met")
            self.assertEqual(verdicts["cs2-b"], "not met")  # P gave more values in every replicate
            self.assertEqual(verdicts["cs3-a"], "partly met")  # one polymer short in r2
            self.assertEqual(verdicts["cs3-b"], "met")
            self.assertEqual(verdicts["cs-all"], "not met")  # 2 contradicted statements in one cell
            self.assertEqual(verdicts["e9-b"], "met")
            self.assertEqual(verdicts["e9-g"], "moot")
            self.assertEqual(e9["overall"]["A"]["citesPlanted"], 10)
            self.assertEqual(e9["overall"]["B"]["byCase"]["gross"]["givesSource"], 0)
            self.assertEqual(e9["record20261013"]["counts"]["A"]["presentsPlanted"], 4)
            self.assertEqual(value["crossChecks"]["mismatches"][0]["what"], "no report.json")  # none written here
            out = a5_results.write(value, Path(folder) / "analysis/a5")
            self.assertIn("**cs3-a, partly met.**", (out / "results.md").read_text())
            entry = fig5.render(Path(folder) / "analysis", Path(folder) / "figures")
        captions = {p["panel"]: p["caption"] for p in entry["panels"]}
        self.assertEqual(list(captions), ["5a", "5b", "5c", "5d", "5e"])
        self.assertIn("R gave 90 sourced values (75 with a method, 60 also with a condition) and 15 uncited",
                      captions["5a"])
        self.assertIn("labelled as interpretation (filled square) in R 15 and P 0", captions["5b"])
        self.assertIn("per replicate R 9/8/9/9/9, R0 5/5/5/5/5, P 9/9/9/9/9", captions["5c"])
        self.assertIn("45 of 45 answers said no published value was found", captions["5d"])
        self.assertIn("Before review no answer presented a planted value (0 of 10; 2026-10-13 4 of 10)", captions["5e"])
        self.assertIn("rejected 5 of the 5 plants at the freeze (2026-10-13: 3 rejected, 2 uncertain)", captions["5e"])
        self.assertEqual(entry["pins"]["knowledgeSnapshot"], kf.SNAPSHOT_ID)


@unittest.skipUnless(S.common.analysis_dir("figures-kf/panels.json").exists(), "A1's outputs are not here")
class RealDataTests(unittest.TestCase):
    """Both figures from A1's outputs (read only) into a temporary folder, captions checked against the panel index."""

    def test_captions_agree_with_the_panel_index(self):
        panels = json.loads(S.common.analysis_dir("figures-kf/panels.json").read_text())["panels"]
        with tempfile.TemporaryDirectory(prefix="oopc-figures-real-") as out:
            three = {p["panel"]: p["caption"] for p in fig3.render(None, out)["panels"]}
            four = {p["panel"]: p["caption"] for p in fig4_records.render(None, out)["panels"]}
        a, b, d = panels["3a"]["KF"], panels["3b"]["KF"], panels["3d"]["KF"]
        self.assertIn("{:,} findings".format(a["findings"]["total"]), three["3a"])
        self.assertIn("%d have findings" % b["withFindings"], three["3b"])
        self.assertIn("for the %d polymers" % d["polymers"], three["3d"])
        self.assertIn("DMA's median is above DSC's in %d" % d["dmaAboveDsc"]["dmaAbove"], three["3d"])
        self.assertIn("{:,} that yielded findings".format(panels["3e"]["KF"]["yieldedFindings"]), three["3e"])
        for rung in ("exact", "paraphrase", "sibling"):
            self.assertIn("%s %.2f" % (rung, panels["4b"]["KF"][rung]["medianTokenRatio"]), four["4b"])
        self.assertIn("{:,} citations".format(panels["4d"]["KF"]["citationsOfFindings"]), four["4d"])


if __name__ == "__main__":
    unittest.main()
