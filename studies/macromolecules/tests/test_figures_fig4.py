"""The assembled Figure 4 (figures/fig4.py), offline: every input it reads built in a temporary folder from the
synthetic records of the panel scripts' own tests (A2, A3 and E8's reports through part_a/a2a3e8_results.py, A4's items
through part_a/a4_results.py, A1's loop outputs, Part B's final results), then the figure drawn from them: its files,
pins and manifest entry (the others kept), a caption whose numbers are the inputs', five panel letters, the four
crossing comparisons, nothing drawn off the page or below 5.5 pt. Inputs not pinned to KF, or Part B's results without
pins, are refused. When the real results are present (OOPC_STUDY_ROOT naming the main checkout), the caption is checked
against them and the drawn texts for collisions. No store, engine or network is touched and nothing is written under
.oopc/.

    python -B -m unittest discover -s studies/macromolecules/tests -p "test_figures_fig4.py"
"""
import itertools, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
STUDY = TESTS.parent
sys.path.insert(0, str(STUDY))
sys.path.insert(0, str(STUDY / "figures"))
sys.path.insert(0, str(TESTS))
try:
    import matplotlib.text  # noqa: E402
    import style as S  # noqa: E402  (imports common and analysis.kf)
    import fig4  # noqa: E402
except ImportError as error:  # matplotlib or numpy missing
    raise unittest.SkipTest("figure scripts need matplotlib and numpy: %s" % error)
from analysis import kf  # noqa: E402
from part_a import a2a3e8_results, a4_results  # noqa: E402
import test_figures as records_test  # noqa: E402  (A1's synthetic outputs)
import test_figures_a2 as a2_test  # noqa: E402  (A2, A3 and E8's synthetic reports)
import test_figures_a4 as a4_test  # noqa: E402  (A4's synthetic items)
import test_figures_restarts_final as part_b_test  # noqa: E402  (Part B's synthetic results)

REAL = [S.common.analysis_dir(name) for name in fig4.KF_INPUTS + [fig4.fig_b.INPUT]]


def part_b():
    """Part B's synthetic results with the fields Figure 4's caption reads beyond Part B's own figure."""
    value = part_b_test.synthetic()
    value["meta"]["pins"]["questions"] = 60
    value["meta"]["strata"] = {"near": 20, "mid": 20, "far": 20}
    value["rechecks"] = {"answers": 40, "agree": {"contradicted": 39, "complete": 40, "resultGiven": 40, "pass": 37}}
    for i, entry in enumerate(value["crossing"].values()):
        entry["quality"] = {"all": {"arm": {"contradicted": i, "resultGiven": 280 + i},
                                    "reference": {"contradicted": 0, "resultGiven": 290}}}
    for name, arm in value["arms"].items():
        arm["all"]["answers"] = 60
    return value


def inputs(folder):
    """Every input of Figure 4 under `folder`/analysis, built as the panel scripts' tests build theirs."""
    folder = Path(folder)
    analysis = folder / "analysis"
    records_test.synthetic(analysis)  # loop-kf/reuse.json, trajectory.json (and A1's other outputs)
    root = folder / "harness-a2"
    a2_test.write(root, "A2", a2_test.a2_rows())
    a2_test.write(root, "A3", a2_test.a3_rows())
    a2_test.write(root, "E8", a2_test.e8_rows())
    a2a3e8_results.write(a2a3e8_results.build(root), analysis / "a2a3e8")
    root = folder / "harness-a4"  # A4 reads A2's held-out arms from a folder of the same name as A2's
    a4_test.records(root)
    a4_test.revisits(analysis)
    a4_results.write(a4_results.build(root, analysis), analysis / "a4")
    path = analysis / fig4.fig_b.INPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(part_b()), encoding="utf-8")
    return analysis


def drawn_texts(fig):
    """(text, window extent) of every non-empty text the figure actually draws (not ticks outside the view)."""
    drawn, original = [], matplotlib.text.Text.draw

    def record(self, renderer):
        original(self, renderer)
        if self.get_visible() and self.get_text().strip():
            drawn.append((self, self.get_window_extent(renderer)))
    with mock.patch.object(matplotlib.text.Text, "draw", record):
        fig.canvas.draw()
    return drawn


class Layout:
    def check_layout(self, fig):
        texts = drawn_texts(fig)
        width, height = fig.get_size_inches()
        self.assertEqual(width, S.DOUBLE)
        self.assertLessEqual(height, 9.0)
        box = fig.get_tightbbox(fig.canvas.get_renderer())  # inches
        self.assertGreaterEqual(box.x0, -0.01)
        self.assertGreaterEqual(box.y0, -0.01)
        self.assertLessEqual(box.x1, width + 0.01, "something is drawn off the right edge")
        self.assertLessEqual(box.y1, height + 0.01, "something is drawn off the top")
        self.assertEqual([t.get_text() for t, _ in texts if t.get_fontsize() < S.TINY - 1e-9], [])
        letters = sorted(t.get_text() for t, _ in texts
                         if t.get_fontsize() == S.LETTER and t.get_fontweight() == "bold")
        self.assertEqual(letters, list("abcde"))
        strings = {t.get_text() for t, _ in texts}
        for _, name, arms in fig4.CROSSING:
            self.assertIn(name, strings)
            self.assertIn(arms, strings)
        self.assertNotIn(fig4.fig_b.COMPARISONS[4][1], strings)  # knowledge under P5 stays in Part B's figure
        return texts


class Synthetic(Layout, unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-fig4-test-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.analysis = inputs(self.folder)
        self.out = self.folder / "figures"
        self.out.mkdir()
        (self.out / "manifest.json").write_text(json.dumps({"about": "kept", "figures": {"fig3": {"pins": {}}}}))

    def test_drawn_with_pins_manifest_and_a_caption_from_the_inputs(self):
        entry = fig4.render(self.analysis, self.out)
        self.assertEqual(entry["assembled"]["files"], ["fig4.pdf", "fig4.svg", "fig4.png"])
        for name in entry["assembled"]["files"]:
            self.assertGreater((self.out / name).stat().st_size, 1000, name)
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(set(manifest["figures"]), {"fig3", "fig4"})  # the other entries kept
        self.assertNotIn("/Users/", json.dumps(manifest))
        self.assertEqual([p["panel"] for p in entry["panels"]], list("abcde"))
        pinned = entry["pins"]
        self.assertEqual(pinned["knowledgeSnapshot"], kf.SNAPSHOT_ID)
        self.assertEqual(pinned["figureScript"], "studies/macromolecules/figures/fig4.py")
        self.assertEqual(pinned["partB"]["harness"], "fbd85f9ac679")
        self.assertEqual(pinned["records"]["a2a3e8"]["A2"]["harnessRevisions"], ["abc1234"])
        self.assertEqual(pinned["records"]["a4"]["A4"]["folders"], ["r1-s1", "r2-s1"])
        from PIL import Image
        with Image.open(self.out / "fig4.png") as image:
            self.assertEqual(image.size, (round(S.DOUBLE * S.DPI), round(fig4.SIZE[1] * S.DPI)))
            self.assertIn(kf.SNAPSHOT_ID, image.info.get("Pins", ""))

        data = fig4.load(self.analysis)
        a2 = data["kf"][fig4.fig4ac.INPUT]["A2"]
        part = data["b"]
        text = entry["assembled"]["caption"]
        self.assertTrue(text.startswith("Figure 4. "))
        self.assertIn("near %s" % fig4.ci(a2["byStratum"]["near"]["paired"]["KF"]["tokens"]), text)
        knowledge = part["crossing"]["knowledge"]["pooled"]
        self.assertIn("knowledge alone (P0·S5 vs E0) %s, near %s" % (
            fig4.ci(knowledge["all"]["tokens"]), fig4.ci(knowledge["near"]["tokens"])), text)
        self.assertIn("web calls %s" % fig4.diff(knowledge["all"]["webCalls"]), text)
        self.assertIn("(%d of 25 kept)" % sum(len(v) for v in part_b_test.ADOPTED.values()), text)
        self.assertIn("changed 3 pass verdicts and 1 contradicted counts", text)
        self.assertIn("Contradicted statements in the 300 answers of each comparison", text)
        self.assertIn("10%, 20%, 35%, 45% and 60% after 0, 1, 2–3, 4–6 and 7+ earlier questions", text)
        self.assertIn("the web-off MF1 1 and MF 0", text)  # 4c's contradicted row, now in the caption

    def test_layout(self):
        fig = fig4.draw(fig4.load(self.analysis))
        self.check_layout(fig)

    def test_inputs_not_pinned_are_refused(self):
        path = self.analysis / "loop-kf/reuse.json"
        value = json.loads(path.read_text())
        value["meta"]["knowledgeSnapshot"] = "oopc-knowledge-other"
        path.write_text(json.dumps(value))
        with self.assertRaises(SystemExit):
            fig4.render(self.analysis, self.out)
        self.assertFalse((self.out / "fig4.png").exists())

    def test_part_b_without_pins_is_refused(self):
        path = self.analysis / fig4.fig_b.INPUT
        value = json.loads(path.read_text())
        value["meta"]["pins"]["restarts"].pop("R3")
        path.write_text(json.dumps(value))
        with self.assertRaises(SystemExit):
            fig4.render(self.analysis, self.out)


@unittest.skipUnless(all(path.exists() for path in REAL), "the real results are not here")
class RealData(Layout, unittest.TestCase):
    """The figure and caption from the real results (read only), drawn in memory."""

    def test_caption_and_layout_from_the_real_results(self):
        data = fig4.load()
        parts = fig4.captions(data)
        v = data["kf"][fig4.fig4ac.INPUT]
        a2, e8 = v["A2"], v["E8"]
        near = a2["byStratum"]["near"]["paired"]["KF"]
        self.assertIn("near %s, time %s" % (fig4.ci(near["tokens"]), fig4.ci(near["seconds"])), parts["a"])
        self.assertIn("KFc/K0c %s" % fig4.ci(e8["byStratum"]["near"]["paired"]["KFc"]["tokens"]), parts["a"])
        exact = data["kf"][fig4.fig4b.INPUT]["A4"]["byRung"]["exact"]["paired"]["tokens"]
        self.assertIn("exact %s" % fig4.ci(exact), parts["b"])
        self.assertIn("near %s" % fig4.ci(a2["estimates"]["slope"]["near"], 3), parts["c"])
        reuse = data["kf"]["loop-kf/reuse.json"]["totals"]
        self.assertIn("%s%% returned at least once" % S.pct(reuse["everReturnedShare"]), parts["d"])
        cross = data["b"]["crossing"]
        for key, name, arms in fig4.CROSSING:
            pooled = cross[key]["pooled"]
            self.assertIn("(%s) %s, near %s" % (
                arms, fig4.ci(pooled["all"]["tokens"]), fig4.ci(pooled["near"]["tokens"])), parts["e"])
        texts = self.check_layout(fig4.draw(data))
        overlaps = []
        for (t1, b1), (t2, b2) in itertools.combinations(texts, 2):
            if b1.overlaps(b2):
                area = (min(b1.x1, b2.x1) - max(b1.x0, b2.x0)) * (min(b1.y1, b2.y1) - max(b1.y0, b2.y0))
                if area > 2:  # square pixels at 100 dpi: a touch, not a collision
                    overlaps.append((t1.get_text(), t2.get_text(), area))
        self.assertEqual(overlaps, [])


if __name__ == "__main__":
    unittest.main()
