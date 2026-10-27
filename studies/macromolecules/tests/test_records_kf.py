"""The records analyses on KF (experiment A1), offline: the frozen copy and its fingerprint, the cleanup's upkeep deposits
and as-written excerpts, the Tg landscape's value reading and method groups, and the blind check recomputed on a
map; then, when the private records and KF's frozen copy are present, the KF builds into temporary folders."""
import json, os, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))  # studies/macromolecules, for common
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from analysis import dataset_build, kf, properties_check, tg_landscape  # noqa: E402
from analysis.properties.build import method_group  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402


def finding(n, value="60"):
    return {"statement": "PLA grade %d had a Tg of %s °C." % (n, value), "material": "PLA grade %d" % n,
            "property": "glass transition temperature (Tg)", "value": value, "unit": "°C", "conditions": "DSC",
            "subject": "", "sourceTitle": "Paper", "sourceUrl": "https://example.org/p%d" % n, "sourceDoi": "",
            "locator": "Table 1", "excerpt": "Tg %s °C" % value, "derivation": "read"}


class Workspace(unittest.TestCase):
    """A graph release and a store of two answers in a temporary folder."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-records-kf-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve() / "live"
        build_release(self.root / "releases/fixture", [{"@id": "wop-000001", "@type": "PolymerConcept",
                      "label": "Polylactide", "abbreviations": ["PLA"], "status": "seed", "layer": "science"}],
                      get_ontology(), {})
        self.release = json.loads((self.root / "releases/fixture/manifest.json").read_text())["release_id"]
        (self.root / "releases/fixture").rename(self.root / "releases" / self.release)
        atomic_json(self.root / "releases/current.json", {"release_id": self.release})
        for question, numbers in (("a" * 32, (1, 2)), ("b" * 32, (3,))):
            knowledge.deposit(self.root, question, {"findings": [finding(n) for n in numbers], "sources": []},
                              engine="codex", spot_check_rate=0)
        self.folder = Path(folder.name).resolve() / "kf"


class FrozenCopyTests(Workspace):
    def test_the_copy_is_made_once_and_refused_once_it_differs(self):
        pins = driver.fingerprint(self.root)
        with mock.patch.object(kf, "FINGERPRINT", pins), mock.patch.object(kf, "RELEASE_ID", self.release):
            path = kf.store(self.folder, self.root)
            self.assertEqual(driver.fingerprint(path.parents[2]), pins)
            self.assertEqual(kf.store(self.folder, self.root), path)  # made once
            db = sqlite3.connect(path)
            db.execute("UPDATE findings SET value='61' WHERE id LIKE '%-1'")
            db.commit()
            db.close()
            with self.assertRaises(SystemExit):
                kf.store(self.folder, self.root)

    def test_a_live_store_that_is_not_kf_is_not_copied(self):
        with self.assertRaises(SystemExit):
            kf.store(self.folder, self.root)  # the pinned fingerprint is KF's, not this store's
        self.assertFalse(self.folder.exists())


class UpkeepDepositTests(Workspace):
    def test_findings_of_an_upkeep_deposit_stay_with_the_import(self):
        with knowledge.connect(self.root) as db:
            db.execute("UPDATE deposits SET origin='upkeep' WHERE question_id=?", ("a" * 32,))
        with mock.patch.object(dataset_build, "STORE", knowledge.database(self.root)):
            findings, notes, deposits, _ = dataset_build.load_store()
        growth = dataset_build.build_growth(findings, notes, deposits, {}, {}, {})
        self.assertEqual([d["question_id"] for d in deposits], ["b" * 32])
        self.assertEqual([p["newFindings"] for p in growth["points"]], [2, 1])


class ReadingTests(unittest.TestCase):
    def test_as_written_gives_the_excerpt_the_cleanup_replaced(self):
        self.assertEqual(kf.as_written("Table 2: Tg 57.3 °C", {"excerptFrom": {"reviewer": "codex", "was": ""}}), "")
        self.assertEqual(kf.as_written("Tg 57.3 °C", {"needsReview": False}), "Tg 57.3 °C")

    def test_values_are_read_as_one_temperature_or_say_why_not(self):
        cases = {("−20", "°C"): (-20.0, "number"), ("449 ±7", "K"): (175.85, "uncertainty (from K)"),
                 ("∼70", "°C"): (70.0, "approximate number"), ("approximately −50", "°C"): (-50.0, "approximate number"),
                 ("about 494 ± 1", "K"): (220.85, "approximate uncertainty (from K)"), ("156–191", "°C"): (None, "range"),
                 ("179.4 and 171.1", "°C"): (None, "several values"), (">220", "°C"): (None, "bound"),
                 ("Not detected", ""): (None, "not observed"), ("180+5", "K"): (None, "unparsed"),
                 ("70", "MPa"): (None, "unit not °C or K")}
        for (value, unit), expected in cases.items():
            got = tg_landscape.celsius(value, unit)
            self.assertEqual((got[0], got[3]), expected, value)
        self.assertEqual(tg_landscape.celsius("315–345", "K")[1:3], (41.85, 71.85))  # a range keeps its ends

    def test_the_method_is_read_from_the_property_then_the_conditions(self):
        cases = [(("glass transition temperature (Tg), DMS E″ peak", "DSC at 10 K/min"), ("DMA", "property")),
                 (("glass transition temperature (Tg)", "As printed; ASTM D7426, inflection point."), ("DSC", "conditions")),
                 (("Tg", "20 °C/min; ISO 11357-1,-2"), ("DSC", "conditions")),
                 (("Tg", "TMDSC TOPEM; reversing heat flow"), ("DSC", "conditions")),
                 (("Tg", "ISO 6721-5; 1 Hz"), ("DMA", "conditions")),
                 (("Tg, storage-modulus step", ""), ("DMA", "property")),
                 (("Tg", "DMA tan δ; tensile mode; first heating at 2 °C/min."), ("DMA", "conditions")),
                 (("Tg", "Combined table; Methods describe DMA sweeps for Tg, so this is not verified as a DSC Tg."),
                  ("DMA", "conditions")),
                 (("Tg", "First heating; 10 K/min; half-step evaluation"), ("none", "")),
                 (("Tg", "DTA at 20 °C/min."), ("other", "conditions")),
                 (("Tg", "DSC midpoint and DMA tan δ peak both given"), ("DSC and DMA", "conditions"))]
        for (prop, conditions), expected in cases:
            self.assertEqual(tg_landscape.method(prop, conditions), expected, conditions)

    def test_only_strings_naming_a_tg_value_are_tg_findings(self):
        named = [s for s in ("glass transition temperature (Tg)", "soft-segment Tg", "loss-factor peak temperature "
                             "(tan δ maximum)", "Tg correction", "ΔTg", "glass transition temperature accuracy")
                 if tg_landscape.is_value_of("Tg", s)]
        self.assertEqual(named, ["glass transition temperature (Tg)", "soft-segment Tg"])

    def test_method_groups_follow_the_property_maps_tg_split(self):
        self.assertEqual([method_group(*m) for m in (("DSC", "DMA"), (None, "DMA; tan δ peak"), ("TMA", None),
                                                     (None, None))], ["DSC", "DMA", "other", "none"])

    def test_query_strings_tell_sources_apart_only_in_the_second_count(self):
        url = "https://citeseerx.ist.psu.edu/document?doi=%s&type=pdf"
        findings = [{"source_doi": "", "source_url": url % "a1"}, {"source_doi": "10.1/X", "source_url": ""}]
        notes = [{"doi": "", "url": url % "b2"}, {"doi": "", "url": "https://example.org/p#section-2"}]
        self.assertEqual(dataset_build.keeping_query(findings, notes),
                         {"sources": 4, "yieldedFindings": 2, "readWithoutFindings": 2})
        self.assertEqual(len({dataset_build.source_key(f["source_doi"], f["source_url"]) for f in findings} |
                             {dataset_build.source_key(n["doi"], n["url"]) for n in notes}), 3)


class BlindCheckTests(unittest.TestCase):
    def test_agreement_on_a_map_keeps_the_strings_it_holds_and_recounts_them(self):
        with tempfile.TemporaryDirectory(prefix="oopc-records-kf-check-") as name:
            folder = Path(name)
            strings = [("tensile strength", 10, "top300"), ("test temperature", 5, "random300"),
                       ("gone", 3, "random300")]
            (folder / "input.json").write_text(json.dumps({"strings": [
                {"n": i, "string": s, "findings": n, "stratum": stratum} for i, (s, n, stratum) in enumerate(strings)]}))
            (folder / "blind.json").write_text(json.dumps({"items": [
                {"n": 0, "class": "tensile-strength", "confident": True},
                {"n": 1, "class": "tensile-strength", "confident": False},
                {"n": 2, "class": "tensile-strength", "confident": True}]}))
            (folder / "map.json").write_text(json.dumps({
                "tensile strength": {"class": "tensile-strength", "findings": 12},
                "test temperature": {"class": "test-temperature", "findings": 4},
                "new string": {"class": "unclassified", "findings": 4}}))
            with mock.patch.object(properties_check, "CHECK", folder):
                value = properties_check.build(folder / "map.json", recount=True)
                cover = properties_check.coverage(folder / "map.json")
        self.assertEqual((value["all"]["strings"], value["all"]["findings"]), (2, 16))
        self.assertEqual((value["all"]["sameClass"], value["all"]["sameClassWeighted"]), (0.5, 0.75))
        self.assertEqual((cover["stringsInMap"], cover["findingsInMap"], cover["shareOfMapFindings"]), (2, 16, 0.8))


@unittest.skipUnless((kf.FOLDER / "workspaces/KF").exists() and (common.analysis_dir("loop") / "trajectory.json").exists(),
                     "KF's frozen copy or K3's records analyses are absent")
class KfBuildTests(unittest.TestCase):
    """The KF builds, from the frozen copy, into temporary folders; nothing is written under .oopc/."""

    def build(self, script, out, *extra):
        subprocess.run([sys.executable, "-B", str(STUDY / "analysis" / script), "--kf", "--out", str(out), *extra],
                       check=True, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def test_kf_builds_reproduce_what_the_store_does_not_change(self):
        with tempfile.TemporaryDirectory(prefix="oopc-records-kf-build-") as name:
            out = Path(name)
            self.build("dataset_build.py", out / "dataset", "--offline")
            self.build("properties/build.py", out / "properties")
            self.build("loop_build.py", out / "loop")
            summary = (out / "dataset/SUMMARY.md").read_text()
            growth = json.loads((out / "dataset/growth.json").read_text())
            meta = json.loads((out / "properties/meta.json").read_text())
            loop = {n: json.loads((out / "loop" / n).read_text()) for n in ("revisits.json", "trajectory.json", "curve.json")}
        k3 = {n: json.loads((common.analysis_dir("loop") / n).read_text()) for n in ("revisits.json", "trajectory.json")}
        self.assertIn("Every expected total is reproduced exactly", summary)
        self.assertEqual((growth["meta"]["knowledgeSnapshot"], growth["meta"]["storeFingerprint"]),
                         (kf.SNAPSHOT_ID, kf.FINGERPRINT))
        self.assertEqual(growth["points"][-1]["answer"], 1063)  # the cleanup's upkeep deposits are not answers
        self.assertEqual(meta["unassigned"]["nonEmpty"]["strings"], 0)
        self.assertEqual(loop["revisits.json"]["summary"]["campaignByType"], k3["revisits.json"]["summary"]["campaignByType"])
        for stage in ("wave1", "wave2", "wave3"):  # excerpts as written: what each prompt produced is K3's
            self.assertEqual(loop["trajectory.json"]["stages"][stage]["excerpts"], k3["trajectory.json"]["stages"][stage]["excerpts"])
        self.assertTrue(loop["curve.json"]["campaign"]["matchesReportJson"])


if __name__ == "__main__":
    unittest.main()
