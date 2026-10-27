"""Part C's overlay step offline (refinement/overlay.py), on a tiny seed and tiny KF and K0 stores in a temporary
folder: the empty overlay reproduces the pinned release; each check refuses what it should; the graph overlay reaches
search through the release (`knowledge.polymer_aliases`, `knowledge.lineage`), and a new polymer is the overlay's,
not the wiki's; the store copies carry the tables, property terms and polymer ids (both halves of upkeep's rule, less
what the seed graph alone would do), never changing one a person approved; everything is built once; and `root_for`
carries only the groups asked for. `World` is also the fixture of test_refinement_propose.py."""
import contextlib, hashlib, io, json, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import driver  # noqa: E402
from refinement import mine, overlay, pins, propose  # noqa: E402
from oopc import knowledge, seed as seed_import  # noqa: E402
from oopc.cli import publish_records  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, digest, read_json  # noqa: E402

APPROVED = {"rule": "approved correction", "by": "owner", "was": "", "at": "2026-10-14"}


def polymer(n, name, abbreviations=(), broader=(), narrower=(), trade=(), kind="polymer"):
    value = {"type": "polymer_entry", "wopId": "wop-%06d" % n, "canonicalSlug": overlay.slug(name),
             "canonicalName": name, "alternateNames": [], "abbreviations": list(abbreviations), "entryKind": kind,
             "relationships": [{"kind": "broader", "wopId": "wop-%06d" % b} for b in broader]
             + [{"kind": "narrower", "wopId": "wop-%06d" % b} for b in narrower], "sections": {}, "sources": []}
    if trade:
        value["tradeNames"] = [{"name": t, "scopeNote": "One polymer's trade name.", "sourceIds": []} for t in trade]
    return value


SNAPSHOT = {"schema": "wop-publication-snapshot-v2", "methodology": {}, "chemicalStructures": [], "aliases": [],
            "searchTerms": [], "polymers": [
                polymer(1, "Polyamide family", ["PA"], narrower=(2, 3), kind="family"),
                polymer(2, "Polyamide 6", ["PA6"], broader=(1,), trade=["Ultramid B"]),
                polymer(3, "Polyamide 66", [], broader=(1,)),
                polymer(4, "Polyetherimide", ["PEI"]),
                polymer(5, "Polyethyleneimine", ["PEI"]),
                polymer(6, "Polycarbonate", ["PC"]),
                polymer(7, "Polyester family", [], kind="family"),
                polymer(8, "Polylactide", ["PLA"])]}
ART, SI, OTHER = "doi:10.1000/art", "url:example.org/si", "doi:10.1000/other"
# id: (material, statement, property, subject, source doi, source url, question, approved)
FINDINGS = {
    "finding:f1": ("PA66 film", "PA66 film had a Tg of 50 C.", "glass transition temperature (Tg)", "", "10.1000/art", "", "q1", False),
    "finding:f2": ("PA66 resin", "PA66 resin had a Tg of 49 C.", "Tg", "", "", "https://example.org/b", "q1", True),
    "finding:f3": ("Lexan sheet", "Lexan sheet had a Tg of 147 C.", "Tg", "", "", "https://example.org/c", "q2", False),
    "finding:f4": ("PA6/66 copolymer fibre", "The fibre melted at 200 C.", "melting temperature (Tm)", "", "", "https://example.org/d", "q3", False),
    "finding:f5": ("sample A", "Sample A crystallized at 100 C.", "crystallization temperature", "", "", "https://example.org/e", "q4", False),
    "finding:f6": ("Polycarbonate", "Polycarbonate had a Tg of 145 C.", "Tg", "wop-000006", "", "https://example.org/f", "q5", True),
    "finding:f7": ("Polyamide 6", "PA6 had a tensile strength of 80 MPa.", "tensile strength", "wop-000002", "10.1000/art", "", "q6", False),
    "finding:f8": ("Polyamide 6", "PA6 was dried at 80 C before testing.", "drying temperature", "wop-000002", "", "https://example.org/si", "q6", False),
    "finding:f9": ("sample B", "Sample B had a Tg of 150 C.", "glass transition temperature", "", "", "https://example.org/g", "q7", False),
    # Filed under a family or another polymer: upkeep's rule moves a finding to the member its own text names.
    "finding:f10": ("PA66 fibre", "PA66 fibre melted at 260 C.", "melting temperature (Tm)", "wop-000001", "", "https://example.org/h", "q8", False),
    "finding:f11": ("Polyamide 6 yarn", "Polyamide 6 yarn melted at 220 C.", "melting temperature (Tm)", "wop-000001", "", "https://example.org/i", "q8", False),
    "finding:f12": ("PLA film", "PLA film had a tensile strength of 50 MPa.", "tensile strength", "wop-000006", "", "https://example.org/j", "q8", False),
    "finding:f13": ("PA66 film", "PA66 film had a tensile strength of 70 MPa.", "tensile strength", "wop-000001", "", "https://example.org/k", "q8", True),
}
QUESTIONS = {"q4": "What crystallization temperature has sample A?", "q7": "What is the Tg of polycarbonate?"}
PROPERTY_MAP = {"glass transition temperature (tg)": {"class": "glass-transition-temperature"},
                "tg": {"class": "glass-transition-temperature"},
                "glass transition temperature": {"class": "glass-transition-temperature"},
                "tensile strength": {"class": "tensile-strength"}}


def store(root, ids):
    with knowledge.connect(root) as db:
        for identifier in ids:
            material, statement, prop, subject, doi, url, question, approved = FINDINGS[identifier]
            detail = {"reviewMode": "researcher", "needsReview": False}
            if approved:
                detail["polymerFrom"] = dict(APPROVED, was=subject)
            knowledge._insert_finding(db, identifier, question, "research", knowledge.clean_finding({
                "statement": statement, "material": material, "property": prop, "value": "1", "unit": "C",
                "conditions": "", "subject": subject, "sourceTitle": "Paper " + identifier, "sourceDoi": doi,
                "sourceUrl": url, "locator": "Table 1", "excerpt": "1", "needsReview": False, "reviewFlag": ""}),
                status=knowledge.SUPPORTED, producer_engine="codex", created_at="2026-10-01T12:00:00+00:00",
                detail=detail)
        knowledge._insert_note(db, "note:n1", "q6", "research", {
            "title": "The other paper", "url": "", "doi": "10.1000/other", "locator": "p. 1", "excerpts": [],
            "supports": "polyamide 6 tensile strength", "conditions": "", "readUrl": ""},
            created_at="2026-10-01T12:00:00+00:00")


def edit(kind, value, sources=(("https://example.org/source", "quoted"),), misses=("m-001",), hops=()):
    """An approved edit as propose.assemble keeps it."""
    return {"type": kind, "edit": value, "proposer": {"engine": "claude-code", "model": "scripted", "batch": "batch-01"},
            "reviewer": {"engine": "codex", "model": "scripted", "verdict": "approved", "reason": "The source says so."},
            "misses": list(misses), "hops": list(hops), "sources": [{"url": u, "quote": q} for u, q in sources]}


EDITS = [  # every kind, each one that a check passes
    edit("name", {"polymer": "wop-000003", "field": "abbreviations", "name": "PA66", "ambiguous": False}),
    edit("name", {"polymer": "wop-000006", "field": "tradeNames", "name": "Lexan", "ambiguous": False}),
    edit("polymer", {"label": "Polyamide 6/66 copolymer", "abbreviations": ["PA6/66"], "alternateNames": [],
                     "broader": ["wop-000001"]}),
    edit("family-link", {"narrower": "wop-000008", "broader": "wop-000007"}),
    edit("annotation", {"finding": "finding:f5", "subject": "wop-000008"}, sources=()),
    edit("source-link", {"a": SI, "relation": "supplement-of", "b": ART},
         sources=(("https://example.org/si", "Supporting Information for: The article"),), misses=(), hops=("h-001",)),
    edit("property-term", {"term": "glass-transition-temperature", "names": ["Tg", "glass transition"]}, sources=()),
]


class World(unittest.TestCase):
    """A temporary study: the run folders, the pinned tiny seed and its release id, KF and K0, question texts and A1's
    map, with pins and overlay pointed at them and the code taken as frozen."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        quiet = contextlib.redirect_stdout(io.StringIO())  # emit prints every event
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        seed_file = self.tmp / "seed.json"
        seed_file.write_bytes(json.dumps(SNAPSHOT).encode())
        sha = hashlib.sha256(seed_file.read_bytes()).hexdigest()
        atomic_json(self.tmp / "seed-lock.json", {"file": str(seed_file), "sha256": sha})
        reference = publish_records(self.tmp / "reference", *seed_import.import_seed(seed_file, sha))
        self.kf, self.k0 = self.tmp / "KF", self.tmp / "K0"
        store(self.kf, sorted(FINDINGS))
        store(self.k0, ["finding:f1", "finding:f2", "finding:f3", "finding:f9"])
        for qid, text in QUESTIONS.items():
            atomic_json(self.tmp / "data/.oopc/loop/questions" / qid / "question.json", {"question": text})
        atomic_json(self.tmp / "map.json", PROPERTY_MAP)
        folders = {name: self.tmp / "run" / name for name in pins.FOLDERS}
        for patch in (mock.patch.object(pins, "FOLDERS", folders), mock.patch.object(pins, "KF", self.kf),
                      mock.patch.object(pins, "K0", self.k0), mock.patch.object(pins, "PROPERTY_MAP", self.tmp / "map.json"),
                      mock.patch.dict(pins.PINS, {"release": reference.name, "kf": driver.fingerprint(self.kf)}),
                      mock.patch.object(pins, "frozen", lambda: "test-commit"),
                      mock.patch.object(overlay, "SEED_LOCK", self.tmp / "seed-lock.json"),
                      mock.patch.object(overlay, "QUESTIONS_ROOT", self.tmp / "data")):
            patch.start()
            self.addCleanup(patch.stop)
        self.release_id = reference.name

    def write(self, approved, measured=True):
        for name, value in propose.overlay_files(approved).items():
            atomic_json(pins.folder("overlay") / name, value, private=True)
        if measured:
            self.measured()

    def measured(self, dropped=()):
        """mine/effects.json as the drop step writes it: every approved edit measured on the inputs in force now."""
        edits = read_json(pins.folder("overlay") / "edits.json")["edits"]
        atomic_json(pins.folder("mine") / "effects.json", {
            "format": mine.FORMATS["effects"], "complete": True, "inputs": mine.effect_inputs("test-commit"),
            "edits": {e: {"missesFixed": 1, "hopsReachable": 0, "resultsLost": 0} for e in edits},
            "dropped": list(dropped)}, private=True)

    def subjects(self, root):
        db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
        value = dict(db.execute("SELECT id, subject FROM findings"))
        db.close()
        return value


class Release(World):
    def test_empty_overlay_gives_the_pinned_release(self):
        root = overlay.seed_root()
        self.assertEqual(read_json(root / "releases/current.json")["release_id"], self.release_id)
        self.assertEqual(overlay.release(root), self.release_id)  # built once: the second call reads it back

    def test_a_release_other_than_the_pin_is_refused_and_not_kept(self):
        with mock.patch.dict(pins.PINS, {"release": "oopc-000000000000000000000000"}):
            with self.assertRaises(SystemExit):
                overlay.seed_root()
        self.assertFalse((pins.FOLDERS["overlay"] / "seed-root").exists())

    def test_the_seed_must_be_the_pinned_snapshot(self):
        lock = read_json(self.tmp / "seed-lock.json")
        atomic_json(self.tmp / "seed-lock.json", dict(lock, sha256="0" * 64))
        with self.assertRaises(SystemExit):
            overlay.seed()

    def test_the_overlay_reaches_search_through_the_release(self):
        self.write(EDITS)
        active, graph, store_overlay, _ = overlay.overlays()
        root = overlay.graph_root(self.tmp / "refined", graph)  # also verifies names and links through knowledge
        new = graph["polymers"][0]["id"]
        self.assertEqual(new, "wop-900001")
        self.assertEqual(knowledge.polymer_ids(root, "PA66"), {"wop-000003"})
        self.assertEqual(knowledge.polymer_ids(root, "lexan"), {"wop-000006"})
        self.assertEqual(knowledge.polymer_ids(root, "PA6/66"), {new})
        self.assertIn("PA66", knowledge.polymer_aliases(root)["polyamide 66"])
        self.assertIn("wop-000007", knowledge.lineage(root, {"wop-000008"}))
        self.assertIn(new, knowledge.lineage(root, {"wop-000001"}))
        self.assertNotIn("wop-000002", knowledge.lineage(root, {new}))  # a sibling, not family
        # Provenance: the new polymer and the overlay's links are candidates with the edit, never wiki-authored.
        db = sqlite3.connect(root / "releases" / read_json(root / "releases/current.json")["release_id"] / "graph.sqlite")
        records = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id, json FROM records")}
        edges = [json.loads(r[0]) for r in db.execute("SELECT json FROM edges WHERE predicate IN ('broader','narrower')")]
        db.close()
        self.assertEqual(records[new]["status"], "candidate")
        self.assertEqual(records[new]["provenance"]["edit"], "e-003")
        self.assertIn("not from the wiki", records[new]["provenance"]["verification"])
        # Its rights are the overlay's, with no wiki attribution; the import gives every other polymer the wiki's.
        self.assertEqual(records[new]["rights"]["edit"], "e-003")
        self.assertIn("not wiki content", records[new]["rights"]["basis"])
        self.assertNotIn("attribution", records[new]["rights"])
        self.assertNotIn("Wiki", json.dumps(records[new]))
        self.assertIn("attribution", records["wop-000003"]["rights"])
        # A name added to a wiki polymer is marked by its refinementEdits; seedRelationships keep the wiki's links only.
        self.assertEqual([e["edit"] for e in records["wop-000003"]["refinementEdits"]], ["e-001"])
        self.assertEqual(records["wop-000008"]["seedRelationships"], [])
        self.assertEqual([e["edit"] for e in records["wop-000008"]["refinementEdits"]], ["e-004"])
        self.assertEqual(records[new]["seedRelationships"], [])
        self.assertEqual(records["wop-000002"]["seedRelationships"], [{"kind": "broader", "wopId": "wop-000001"}])
        overlay_links = [e for e in edges if e["status"] == "candidate"]
        self.assertEqual(len(overlay_links), 4)  # two directions each of the new polymer's family and PLA's
        self.assertTrue(all("refinement edit" in e["context"]["basis"] for e in overlay_links))
        self.assertTrue(all("wiki-authored relationship" in e["context"]["basis"] for e in edges
                            if e["status"] == "seed"))
        with self.assertRaises(SystemExit):  # the overlay does not reach the pinned release
            overlay.verify(overlay.seed_root(), graph)


class Checks(World):
    def problems(self, approved):
        self.write(approved)
        value = overlay.check()
        self.assertEqual(read_json(pins.folder("overlay") / "checks.json")["ok"], value["ok"])
        return {(p["check"], p["edit"]) for p in value["problems"]}

    def test_every_kind_passes(self):
        self.write(EDITS)
        value = overlay.check()
        self.assertTrue(value["ok"], value["problems"])
        self.assertEqual(value["counts"], {t: (2 if t == "name" else 1) for t in pins.TYPES})

    def test_a_name_for_two_unrelated_polymers_unless_marked_ambiguous(self):
        pei = {"polymer": "wop-000006", "field": "abbreviations", "name": "PEI", "ambiguous": False}
        self.assertEqual(self.problems([edit("name", pei)]), {("ambiguous-names", "e-001")})
        for name in ("edits.json", "graph-overlay.json", "store-overlay.json"):
            (pins.folder("overlay") / name).unlink()
        self.assertEqual(self.problems([edit("name", dict(pei, ambiguous=True))]), set())
        # A family member may share its family's name: they are in each other's lineage.
        for name in ("edits.json", "graph-overlay.json", "store-overlay.json"):
            (pins.folder("overlay") / name).unlink()
        self.assertEqual(self.problems([edit("name", {"polymer": "wop-000002", "field": "alternateNames",
                                                      "name": "Polyamide", "ambiguous": False})]), set())

    def test_no_cycles(self):
        self.assertEqual(self.problems([edit("family-link", {"narrower": "wop-000001", "broader": "wop-000002"})]),
                         {("cycles", None)})

    def test_new_polymers_in_the_reserved_block_with_a_family(self):
        self.write([edit("polymer", {"label": "Polyamide 6/66 copolymer", "abbreviations": [], "alternateNames": [],
                                     "broader": []})])
        graph = read_json(pins.folder("overlay") / "graph-overlay.json")
        graph["polymers"][0]["id"] = "wop-000300"
        atomic_json(pins.folder("overlay") / "graph-overlay.json", graph)
        found = {(p["check"], p["edit"]) for p in overlay.check()["problems"]}
        self.assertEqual(found, {("reserved-ids", "e-001"), ("broader-link", "e-001")})

    def test_source_links_join_sources_the_store_holds_by_a_listed_relation(self):
        found = self.problems([edit("source-link", {"a": SI, "relation": "cites", "b": "doi:10.9/absent"})])
        self.assertEqual(found, {("source-endpoints", "e-001")})
        for name in ("edits.json", "graph-overlay.json", "store-overlay.json"):
            (pins.folder("overlay") / name).unlink()
        # A note's source counts as held.
        self.assertEqual(self.problems([edit("source-link", {"a": OTHER, "relation": "takes-value-from", "b": ART})]),
                         set())

    def test_approved_polymer_ids_are_never_changed(self):
        self.assertEqual(self.problems([edit("annotation", {"finding": "finding:f6", "subject": "wop-000004"})]),
                         {("approved-ids", "e-001")})

    def test_only_the_closed_list(self):
        self.write([EDITS[0]])
        edits = read_json(pins.folder("overlay") / "edits.json")
        edits["edits"]["e-002"] = dict(EDITS[0], type="finding", edit={"statement": "a new finding"})
        atomic_json(pins.folder("overlay") / "edits.json", edits)
        found = {(p["check"], p["edit"]) for p in overlay.check()["problems"]}
        self.assertEqual(found, {("closed-list", "e-002")})

    def test_a_failed_check_builds_nothing_and_exclusion_lets_the_rest_build(self):
        pei = edit("name", {"polymer": "wop-000006", "field": "abbreviations", "name": "PEI", "ambiguous": False})
        self.write(EDITS + [pei])
        with self.assertRaises(SystemExit):
            overlay.build()
        self.assertFalse((pins.FOLDERS["overlay"] / "seed-root").exists())
        self.assertFalse((pins.FOLDERS["stores"] / "workspaces").exists())
        atomic_json(pins.folder("overlay") / "excluded.json", {"format": overlay.FORMATS["excluded"],
                                                             "edits": {"e-008": "names two unrelated polymers"}})
        value = overlay.build()
        self.assertEqual(value["excluded"], {"e-008": "names two unrelated polymers"})
        self.assertNotIn("e-008", value["edits"])
        self.assertNotIn("wop-000006", knowledge.polymer_ids(pins.FOLDERS["overlay"] / "release-root", "PEI"))


class Build(World):
    def test_build_once(self):
        self.write(EDITS)
        value = overlay.build()
        folder, stores = pins.FOLDERS["overlay"], pins.FOLDERS["stores"] / "workspaces"
        self.assertEqual(value["releases"]["seed"], self.release_id)
        self.assertNotEqual(value["releases"]["refined"], self.release_id)
        self.assertEqual(sorted(value["stores"]), ["K0", "K0-refined", "KF", "KF-refined"])
        self.assertEqual(read_json(folder / "fingerprint.json"), json.loads(json.dumps(value)))
        # The baseline stores are untouched copies on the seed release, without the tables.
        self.assertEqual(value["stores"]["KF"], dict(driver.fingerprint(self.kf), tables=None))  # run.py reads this
        self.assertEqual(value["builds"]["KF"]["release"], self.release_id)
        self.assertEqual(value["roots"]["KF-refined"], str(stores / "KF-refined"))
        self.assertEqual(knowledge.polymer_ids(stores / "KF", "PA66"), set())
        # The refined store reads the refined release.
        refined = stores / "KF-refined"
        self.assertEqual(knowledge.polymer_ids(refined, "PA66"), {"wop-000003"})
        self.assertEqual(value["stores"]["KF-refined"]["tables"]["source_links"], 1)
        db = sqlite3.connect(knowledge.database(refined))
        link = db.execute("SELECT a, relation, b, evidence FROM source_links").fetchone()
        terms = dict(db.execute("SELECT term, names FROM property_terms"))
        tagged = sorted(r[0] for r in db.execute("SELECT finding_id FROM finding_terms"))
        db.close()
        self.assertEqual(link[:3], (SI, "supplement-of", ART))
        self.assertEqual(json.loads(link[3])["edit"], "e-006")
        self.assertEqual(json.loads(terms["glass-transition-temperature"]), ["Tg", "glass transition"])
        self.assertEqual(tagged, ["finding:f1", "finding:f2", "finding:f3", "finding:f6", "finding:f9"])
        # Polymer ids: the annotation edit, then upkeep's rule against the refined release; approved ones untouched.
        before, after = self.subjects(self.kf), self.subjects(refined)
        self.assertEqual(after["finding:f5"], "wop-000008")  # the annotation edit
        self.assertEqual(after["finding:f1"], "wop-000003")  # "PA66", a name the overlay added
        self.assertEqual(after["finding:f3"], "wop-000006")  # "Lexan", a trade name the overlay added
        self.assertEqual(after["finding:f4"], "wop-900001")  # the new polymer
        # Its question names polycarbonate: the rule files it so against the seed graph too, so that is upkeep's work,
        # not the ontology's, and is left out.
        self.assertEqual(after["finding:f9"], "")
        self.assertEqual(after["finding:f2"], "")  # a person approved it blank
        self.assertEqual(after["finding:f6"], before["finding:f6"])
        # The rule's other half: a finding filed under the family moves to the member its text names by a name the
        # overlay added ("PA66"); one the seed graph would move too is upkeep's, and left; one the rule would file
        # under a polymer outside its own's members is left (upkeep lists it for a person); an approved one is left.
        self.assertEqual(after["finding:f10"], "wop-000003")
        self.assertEqual((after["finding:f11"], after["finding:f12"], after["finding:f13"]),
                         ("wop-000001", "wop-000006", "wop-000001"))
        report = value["builds"]["KF-refined"]["annotations"]
        self.assertEqual((report["edits"], report["filedByRule"], report["sameWithSeedGraph"]),
                         (1, 4, ["finding:f11", "finding:f9"]))
        self.assertEqual(sum(n for rule, n in report["byRule"].items() if rule.endswith("(narrowed from its family)")), 1)
        db = sqlite3.connect(knowledge.database(refined).as_uri() + "?mode=ro", uri=True)
        detail = json.loads(db.execute("SELECT detail FROM findings WHERE id='finding:f1'").fetchone()[0])
        moved = json.loads(db.execute("SELECT detail FROM findings WHERE id='finding:f10'").fetchone()[0])
        db.close()
        self.assertEqual(detail["polymerFrom"]["pass"], "refinement")
        self.assertEqual(moved["polymerFrom"]["was"], "wop-000001")
        self.assertTrue(moved["polymerFrom"]["rule"].endswith("(narrowed from its family)"))
        # K0's copy: what it holds of the same edits.
        k0 = self.subjects(stores / "K0-refined")
        self.assertEqual([k0["finding:f%d" % n] for n in (1, 2, 3, 9)], ["wop-000003", "", "wop-000006", ""])
        self.assertEqual(value["builds"]["K0-refined"]["annotations"]["absentFindings"], ["finding:f5"])
        # Built once: a second build changes nothing and rebuilds nothing.
        marker = refined / "marker"
        marker.write_text("kept")
        inode = os.stat(knowledge.database(refined)).st_ino
        self.assertEqual(overlay.build(), value)
        os.unlink(folder / "fingerprint.json")  # even an interrupted build's finished parts are kept
        again = overlay.build()
        self.assertTrue(marker.exists())
        self.assertEqual(os.stat(knowledge.database(refined)).st_ino, inode)
        self.assertEqual(again["stores"], value["stores"])
        self.assertEqual(again["releases"], value["releases"])

    def test_the_build_needs_the_drop_steps_effects_on_the_inputs_in_force(self):
        self.write(EDITS, measured=False)
        with self.assertRaisesRegex(SystemExit, "effects.json is missing"):
            overlay.build()
        self.measured()
        atomic_json(pins.folder("mine") / "misses.json", [{"id": "m-1"}])  # mined again since
        with self.assertRaisesRegex(SystemExit, "other inputs"):
            overlay.build()
        self.measured(dropped=["e-002"])
        with self.assertRaisesRegex(SystemExit, "e-002, which it dropped, is not excluded"):
            overlay.build()
        atomic_json(pins.folder("overlay") / "excluded.json", {"format": overlay.FORMATS["excluded"],
                                                             "edits": {"e-002": "loses more than it fixes"}})
        value = overlay.build()
        self.assertNotIn("e-002", value["edits"])
        self.assertEqual(value["effectsSha256"], hashlib.sha256(
            (pins.folder("mine") / "effects.json").read_bytes()).hexdigest())

    def test_a_build_never_resumes_over_parts_built_from_other_inputs(self):
        self.write(EDITS)
        overlay.build()
        os.unlink(pins.folder("overlay") / "fingerprint.json")
        excluded = pins.folder("overlay") / "excluded.json"
        atomic_json(excluded, {"format": overlay.FORMATS["excluded"], "edits": {"e-006": "dropped"}})  # a store edit
        with self.assertRaisesRegex(SystemExit, "KF-refined was built from other inputs \\(edits\\)"):
            overlay.build()
        atomic_json(excluded, {"format": overlay.FORMATS["excluded"], "edits": {"e-001": "dropped"}})  # a graph edit
        with self.assertRaisesRegex(SystemExit, "release-root was built from other graph edits"):
            overlay.build()
        os.unlink(excluded)
        self.assertEqual(overlay.build()["edits"], sorted(read_json(pins.folder("overlay") / "edits.json")["edits"]))

    def test_an_edit_root_carries_that_edit_alone_and_records_nothing(self):
        self.write(EDITS)
        in_force, plain = overlay.overlays(), overlay.seed_root()
        name = overlay.edit_root(self.tmp / "e-001", ["e-001"], in_force=in_force, plain=plain)
        self.assertEqual(knowledge.polymer_ids(name, "PA66"), {"wop-000003"})  # its release has the name
        self.assertEqual(knowledge.polymer_ids(name, "lexan"), set())  # and no other edit's
        self.assertEqual(self.subjects(name)["finding:f1"], "wop-000003")  # upkeep's rule against it
        self.assertEqual(self.subjects(name)["finding:f3"], "")
        self.assertIsNone(overlay.table_hash(name))
        link = overlay.edit_root(self.tmp / "e-006", ["e-006"], in_force=in_force, plain=plain)
        self.assertEqual(read_json(link / "releases/current.json")["release_id"], self.release_id)
        self.assertEqual(overlay.table_hash(link)["source_links"], 1)
        self.assertEqual(self.subjects(link), self.subjects(self.kf))
        note = overlay.edit_root(self.tmp / "e-005", ["e-005"], in_force=in_force, plain=plain)
        self.assertEqual({k: v for k, v in self.subjects(note).items() if v != self.subjects(self.kf)[k]},
                         {"finding:f5": "wop-000008"})
        self.assertFalse((pins.FOLDERS["stores"]).exists())  # nothing recorded under stores/
        with self.assertRaises(ValueError):
            overlay.edit_root(self.tmp / "e-099", ["e-099"], in_force=in_force, plain=plain)

    def test_the_drop_step_measures_each_edit_alone_and_excludes_what_loses_more_than_it_fixes(self):
        self.write(EDITS, measured=False)
        release = next((self.tmp / "reference/releases").glob("oopc-*"))
        (self.kf / "releases").mkdir()
        (self.kf / "releases" / release.name).symlink_to(release, True)
        atomic_json(self.kf / "releases/current.json", {"release_id": release.name})  # KF as a workspace
        # The mined pool: one answer whose unfiltered search for an unknown name returned the PA66 findings it cites.
        answer = {"id": "loop/q9", "origin": "loop", "question": "What Tg has Lexan?", "questionId": "q9",
                  "materials": ["Lexan"], "property": "Tg", "steps": [
                      {"i": 0, "type": "store", "q": "Lexan Tg", "limit": 10, "status": "ok"}],
                  "cited": {"findings": ["finding:f1", "finding:f2"], "notes": [], "urls": []}, "reported": [],
                  "sources": []}
        miss = {"id": "m-lexan", "kind": "unresolved-name", "answer": "loop/q9", "origin": "loop", "scope": "query",
                "step": 0, "q": "Lexan Tg", "names": ["Lexan"]}
        out = pins.folder("mine")
        atomic_bytes(out / "answers.jsonl", (json.dumps(answer) + "\n").encode())
        atomic_json(out / "misses.json", [miss])
        atomic_json(out / "hops.json", [])
        with self.assertRaisesRegex(SystemExit, "pool.json is missing"):
            mine.run_effects()
        atomic_json(out / "pool.json", {"format": mine.FORMATS["pool"], "cutoff": mine.CUTOFF,
                                        "answers": [answer["id"]], "digest": digest([answer["id"]])})
        value = mine.run_effects()
        self.assertEqual(sorted(value["edits"]), ["e-%03d" % n for n in range(1, 8)])
        lexan = value["edits"]["e-002"]  # Lexan is now polycarbonate's: the search is filtered to it
        self.assertEqual((lexan["fixed"], lexan["resultsLost"], lexan["type"]), (["m-lexan"], 2, "name"))
        self.assertEqual(value["dropped"], ["e-002"])
        self.assertIn("loses 2 results and fixes 1 misses", read_json(pins.folder("overlay") / "excluded.json")[
            "edits"]["e-002"])
        self.assertEqual(value["edits"]["e-004"]["searches"]["replayed"], 0)  # PLA's family: nothing it can change
        self.assertEqual(set(value["groups"]), {"name/family", "source-link", "property-term", "all"})
        self.assertEqual(value["groups"]["all"]["resultsLost"], 0)  # Lexan's name is excluded from the totals
        self.assertFalse((out / "effects-roots").exists())  # every edit's root is deleted after its replay
        self.assertTrue(read_json(out / "effects.json")["complete"])
        with mock.patch.object(overlay, "edit_root", side_effect=AssertionError("built again")):
            self.assertEqual(mine.run_effects()["edits"], value["edits"])  # a rerun keeps what was measured
        self.assertNotIn("e-002", overlay.build()["edits"])
        atomic_json(out / "hops.json", [{"id": "h-new"}])
        with self.assertRaisesRegex(SystemExit, "other inputs"):
            mine.run_effects()

    def test_the_build_refuses_a_store_that_is_not_kf(self):
        self.write(EDITS)
        with mock.patch.dict(pins.PINS, {"kf": {"findings": 1, "notes": 0, "sha256": "0"}}):
            with self.assertRaises(SystemExit):
                overlay.build()

    def test_the_build_needs_the_frozen_code(self):
        self.write(EDITS)
        with mock.patch.object(pins, "frozen", mock.Mock(side_effect=SystemExit("not the tag"))):
            with self.assertRaises(SystemExit):
                overlay.build()
        self.assertFalse((pins.FOLDERS["overlay"] / "seed-root").exists())

    def test_root_for_carries_only_its_groups_and_is_built_once(self):
        self.write(EDITS)
        links = overlay.root_for(["source-link"])
        self.assertEqual(read_json(links / "releases/current.json")["release_id"], self.release_id)
        tables = overlay.table_hash(links)
        self.assertEqual((tables["source_links"], tables["property_terms"], tables["finding_terms"]), (1, 0, 0))
        self.assertEqual(self.subjects(links), self.subjects(self.kf))
        names = overlay.root_for(["name/family"])
        self.assertIsNone(overlay.table_hash(names))
        self.assertEqual(knowledge.polymer_ids(names, "PA66"), {"wop-000003"})
        self.assertEqual(self.subjects(names)["finding:f1"], "wop-000003")
        both = overlay.root_for(["property-term", "name/family"])
        self.assertEqual(overlay.table_hash(both)["source_links"], 0)
        self.assertEqual(overlay.table_hash(both)["finding_terms"], 5)
        self.assertEqual(overlay.root_for(["name/family", "property-term"]), both)  # once per combination
        self.assertEqual(sorted(read_json(pins.FOLDERS["stores"] / "roots.json")),
                         sorted(p.name for p in (links, names, both)))
        with self.assertRaises(ValueError):
            overlay.root_for(["annotation"])


if __name__ == "__main__":
    unittest.main()
