"""Part C's question sets offline, in a temporary folder with its own seed graph, KF store and property map: N drawn in
test 2's mix without H's or the dev set's pairs, their far polymers or any text asked before (the run folders' question
files and plans, Part C's own folder left out, and the live loop's questions); H in Part A's order; both fixed once
written; L's pairs (non-rejected, filed, material properties, at least three findings), their coverage tertiles and the
quota per group; the writer behind the study Guard (one session per batch, the pairs alone), the name check and the
redraws, its schema, a stop for quota resumed without asking a batch again, and the refusal to call an engine unless
the code is the tag; and the hashes."""
import collections, contextlib, io, json, random, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import pins, questions  # noqa: E402
from part_a import part_a  # noqa: E402
from recursive import make_tasks  # noqa: E402
from scaling import scaling  # noqa: E402
from oopc import calls, engines, knowledge  # noqa: E402
from oopc.release import build_release  # noqa: E402
from oopc.util import atomic_json, digest, read_json  # noqa: E402
from oopc.vocabulary import get_ontology  # noqa: E402

POLYMERS = [("wop-000001", "Polylactide", ["PLA"]), ("wop-000002", "Polycaprolactone", ["PCL"]),
            ("wop-000003", "Polystyrene", ["PS"]), ("wop-000004", "Polycarbonate", ["PC"]),
            ("wop-000005", "Poly(ethylene terephthalate)", ["PET"]), ("wop-000006", "Poly(methyl methacrylate)", ["PMMA"]),
            ("wop-000009", "Polyethylene family", ["PE"]), ("wop-000010", "High-density polyethylene", ["HDPE"]),
            ("wop-000011", "Low-density polyethylene", ["LDPE"]), ("wop-000012", "Polypropylene", ["PP"])]
FAMILIES = [("wop-000010", "wop-000009"), ("wop-000011", "wop-000009")]
TS, TG = "tensile strength", "glass transition temperature (Tg)"
COUNTS = {("wop-000001", TS): 3, ("wop-000002", TS): 3, ("wop-000003", TS): 4, ("wop-000004", TS): 4,
          ("wop-000005", TS): 5, ("wop-000010", TS): 5, ("wop-000011", TS): 6, ("wop-000012", TS): 6,
          ("wop-000006", TS): 7, ("wop-000001", TG): 7, ("wop-000002", TG): 8, ("wop-000003", TG): 8,
          ("wop-000010", TG): 3, ("wop-000011", TG): 3, ("wop-000012", TG): 4, ("wop-000004", TG): 2}
CLASS = {TS: "tensile-strength", TG: "glass-transition-temperature"}
OTHER = "heating rate"  # a test condition, not a material property
STATEMENT = "Specimen %d reached a value in study %s."

HELDOUT = [
    {"stratum": "near", "kind": "method", "material": "PET", "property": "oxygen permeability", "question":
     "How is oxygen permeability of PET measured?", "id": "h1", "depth": "standard"},
    {"stratum": "near", "kind": "property", "material": "PLA", "property": "tensile modulus and yield strength",
     "question": "Report a value of tensile modulus of PLA.", "id": "h2", "depth": "standard"},
    {"stratum": "mid", "kind": "property", "material": "PMMA", "property": "glass transition temperature (Tg)",
     "question": "Report a value of Tg of PMMA.", "id": "h3", "depth": "standard"},
    {"stratum": "mid", "kind": "method", "material": "polystyrene", "property": "water absorption", "question":
     "How is water absorption of polystyrene measured?", "id": "h4", "depth": "standard"},
    {"stratum": "far", "kind": "property", "material": "chlorinated polyethylene elastomer (CM)",
     "property": "Shore A hardness", "question": "Report a Shore A hardness of CM.", "id": "h5", "depth": "standard"},
    {"stratum": "far", "kind": "method", "material": "polyacetylene", "property": "conductivity", "question":
     "How is conductivity of polyacetylene measured?", "id": "h6", "depth": "standard"}]
DEV = [{"stratum": "near", "kind": "property", "material": "PA6", "property": "water absorption at saturation",
        "question": "Report the water absorption of PA6.", "id": "d1"},
       {"stratum": "far", "kind": "property", "material": "PEEK", "property": "tensile modulus",
        "question": "Report the tensile modulus of PEEK.", "id": "d2"}]
CAMPAIGN = [{"kind": "property", "materials": ["PET"], "property": "tensile modulus and tensile strength",
             "question": "What tensile modulus and tensile strength has been reported for PET?", "revisit": None,
             "taskId": "c1"},
            {"kind": "comparison", "materials": ["PA6", "PA66", "polyamide 12 (PA12)"], "property": "melting temperature",
             "question": "Compare melting temperature of PA6, PA66 and polyamide 12 (PA12).", "revisit": None,
             "taskId": "c2"}]


def seed(root):
    records = [{"@id": i, "@type": "PolymerConcept", "label": label, "abbreviations": abbreviations, "status": "seed",
                "layer": "science"} for i, label, abbreviations in POLYMERS]
    records += [{"@id": "claim:%s-%s-%s" % (s, p, o), "@type": "Claim", "label": "%s %s %s" % (s, p, o), "subject": s,
                 "predicate": p, "object": o, "context": {}, "evidence": [], "status": "seed", "layer": "science"}
                for member, family in FAMILIES for s, p, o in ((member, "broader", family), (family, "narrower", member))]
    path = build_release(root / "releases/fixture", records, get_ontology(), {})
    release_id = json.loads((path / "manifest.json").read_text())["release_id"]
    path.rename(root / "releases" / release_id)
    atomic_json(root / "releases/current.json", {"release_id": release_id})
    return release_id


def add(db, identifier, subject, prop, status=knowledge.SUPPORTED, material="specimen", statement=None):
    knowledge._insert_finding(db, identifier, "q-" + identifier, "research", knowledge.clean_finding({
        "statement": statement or STATEMENT % (len(identifier), identifier), "material": material, "property": prop,
        "value": "1",
        "unit": "MPa", "conditions": "", "subject": subject, "sourceTitle": "Paper", "sourceUrl":
        "https://example.org/" + identifier, "sourceDoi": "", "locator": "Table 1", "excerpt": "1 MPa",
        "needsReview": False, "reviewFlag": ""}), status=status, producer_engine="codex",
        created_at="2026-10-10T00:00:00+00:00")


def kf(root):
    with knowledge.connect(root) as db:
        for (subject, prop), n in COUNTS.items():
            for k in range(n):
                add(db, "finding:%s-%s-%d" % (subject, CLASS[prop], k), subject, prop)
        for k in range(3):  # rejected findings never count
            add(db, "finding:rejected-%d" % k, "wop-000005", TG, status=knowledge.UNSUPPORTED)
        for k in range(4):  # findings without a polymer id never count
            add(db, "finding:unfiled-%d" % k, "", TS)
        for k in range(5):  # a test condition is not a property to ask about
            add(db, "finding:condition-%d" % k, "wop-000001", OTHER)
        # A grade the store already uses (unfiled, so no pair counts it): full-text search finds it by name alone.
        add(db, "finding:zyx", "", TS, material="Zyx-3 film", statement="Zyx-3 film reached 40 MPa.")


class Fixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-refinement-questions-test-")
        self.addCleanup(folder.cleanup)
        self.top = Path(folder.name).resolve()
        self.harness, self.live = self.top / "harness", self.top / "live"
        base = self.harness / "2026-10-refinement"
        root = self.top / "KF"
        release = seed(root)
        kf(root)
        mapping = self.top / "properties-kf/map.json"
        atomic_json(mapping, {"tensile strength": {"class": "tensile-strength"},
                              "glass transition temperature (tg)": {"class": "glass-transition-temperature"},
                              "heating rate": {"class": "heating-cooling-rate"}})
        atomic_json(mapping.parent / "meta.json", {"meta": {"storeFingerprint": driver.fingerprint(root)}})
        files = {"HELDOUT": ("2026-10-ablation/heldout.json", HELDOUT), "DEV": ("2026-10-recursive/dev.json", DEV),
                 "CAMPAIGN": ("2026-10-campaign/questions.json", CAMPAIGN)}
        for name, (where, rows) in files.items():
            atomic_json(self.harness / where, rows)
        patches = [mock.patch.object(pins, "BASE", base),
                   mock.patch.dict(pins.FOLDERS, {k: base / k for k in pins.FOLDERS}),
                   mock.patch.object(pins, "KF", root), mock.patch.object(pins, "PROPERTY_MAP", mapping),
                   mock.patch.dict(pins.PINS, release=release, kf=driver.fingerprint(root)),
                   mock.patch.object(pins, "frozen", lambda: "3" * 40),
                   mock.patch.object(part_a, "HELDOUT", self.harness / files["HELDOUT"][0])]
        patches += [mock.patch.object(pins, name, self.harness / where) for name, (where, _) in files.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.root = root
        quiet = contextlib.redirect_stdout(io.StringIO())  # the Guard and emit print every event
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)


class N(Fixture):
    def test_n_is_drawn_in_test_2s_mix_without_held_out_or_dev_pairs_far_polymers_or_texts_asked_before(self):
        rows, passed = questions.draw_n(HELDOUT, DEV, CAMPAIGN, set())
        test2 = {k: v for k, v in make_tasks.ROUNDS[1].items() if k != "revisits"}
        self.assertEqual(sum(questions.N_MIX.values()), 60)
        self.assertTrue(all(abs(questions.N_MIX[k] - test2[k] * 60 / 80) <= 0.5 for k in test2))
        self.assertEqual(collections.Counter(r["kind"] for r in rows), questions.N_MIX)
        self.assertEqual((len({r["id"] for r in rows}), passed), (60, []))
        for r in rows:
            self.assertEqual((r["set"], r["group"], r["depth"]), ("N", r["kind"], "standard"))
            self.assertTrue(r["materials"] and r["property"] and r["question"])
            self.assertFalse({"PEEK", "polyacetylene", "chlorinated polyethylene elastomer (CM)"} & set(r["materials"]))
            words = make_tasks._words(r["property"])
            self.assertFalse("PET" in r["materials"] and words & make_tasks._words("oxygen permeability"), r)
            self.assertFalse("PA6" in r["materials"] and words & make_tasks._words("water absorption at saturation"), r)
        self.assertEqual(questions.draw_n(HELDOUT, DEV, CAMPAIGN, set())[0], rows)  # deterministic
        asked = {questions.norm(r["question"]) for r in rows[:5]}
        again, passed = questions.draw_n(HELDOUT, DEV, CAMPAIGN, asked)
        self.assertFalse(asked & {questions.norm(r["question"]) for r in again})
        self.assertTrue(passed and all(questions.norm(p["question"]) in asked for p in passed))
        self.assertEqual(collections.Counter(r["kind"] for r in again), questions.N_MIX)

    def test_a_question_is_classed_by_what_the_campaign_asked_before(self):
        stratum = lambda materials, prop: questions.n_stratum({"materials": materials, "property": prop}, CAMPAIGN)
        self.assertEqual(stratum(["PET"], "tensile modulus and tensile strength"), "asked-pair")
        self.assertEqual(stratum(["PA6", "PA66"], "melting temperature"), "asked-pair")
        self.assertEqual(stratum(["PET"], "notched impact strength"), "asked-polymer")
        self.assertEqual(stratum(["PA6", "PBT"], "melting temperature"), "asked-polymer")
        self.assertEqual(stratum(["PBT"], "melting temperature"), "new-polymer")

    def test_texts_asked_before_come_from_run_folders_and_the_live_loop_but_not_part_cs_own_folder(self):
        for where, text in (("2026-10-kf-scaling/r1-s1/plan.json", "Asked in Part A?"),
                            ("2026-10-restarts/R1/rounds.json", "Asked in Part B?"),
                            ("2026-10-refinement/screen/s1/plan.json", "Part C's own?"),
                            ("2026-10-kf-scaling/r1-s1/workspaces/KF/plan.json", "Inside a workspace?")):
            atomic_json(self.harness / where, {"questions": [{"id": "x", "question": text}]})
        atomic_json(self.live / "abc/question.json", {"id": "abc", "question": "Asked  by the LOOP?"})
        found = questions.asked_before(self.harness, self.live)
        self.assertEqual(found["2026-10-kf-scaling"], {"asked in part a?"})
        self.assertEqual(found["2026-10-restarts"], {"asked in part b?"})
        self.assertEqual(found["live-loop"], {"asked by the loop?"})
        self.assertIn("how is oxygen permeability of pet measured?", found["2026-10-ablation"])
        self.assertNotIn("2026-10-refinement", found)
        self.assertNotIn("inside a workspace?", set().union(*found.values()))

    def test_build_writes_h_in_part_as_order_and_n_with_polymer_ids_and_both_are_fixed_once_written(self):
        first, _ = questions.draw_n(HELDOUT, DEV, CAMPAIGN, questions.texts(CAMPAIGN) | questions.texts(HELDOUT)
                                    | questions.texts(DEV))
        atomic_json(self.live / "abc/question.json", {"question": first[0]["question"]})
        value = questions.build(self.harness, self.live)
        h, n = read_json(questions.path("H.json")), read_json(questions.path("N.json"))
        order = list(HELDOUT)
        random.Random(scaling.SEED).shuffle(order)
        self.assertEqual([q["id"] for q in h], [q["id"] for q in order])
        by_id = {q["id"]: q for q in h}
        self.assertEqual((by_id["h1"]["polymerIds"], by_id["h1"]["materials"], by_id["h1"]["set"]),
                         (["wop-000005"], ["PET"], "H"))
        self.assertEqual(by_id["h4"]["polymerIds"], ["wop-000003"])
        self.assertEqual(by_id["h6"]["polymerIds"], [])  # the seed does not know it
        self.assertEqual(value["H"]["byStratum"], {"near": 2, "mid": 2, "far": 2})
        self.assertNotIn(first[0]["question"], {q["question"] for q in n})  # asked by the live loop
        self.assertEqual(len(n), 60)
        self.assertTrue(all(q["polymerIds"] == questions.polymer_ids(self.root, q["materials"]) for q in n))
        self.assertTrue(any(q["polymerIds"] for q in n) and not all(q["polymerIds"] for q in n))
        record = read_json(questions.path("N-build.json"))
        self.assertEqual((record["askedTexts"]["live-loop"], record["seed"]), (1, questions.N_SEED))
        self.assertEqual(questions.build(self.harness, self.live)["N"], value["N"])  # the same again
        n[0]["question"] += " Cite tables."
        atomic_json(questions.path("N.json"), n)
        with self.assertRaisesRegex(SystemExit, "fixed once written"):
            questions.build(self.harness, self.live)


class Writer:
    """The question writer by schema: for a "name" item it first gives a seed name, then declines, then writes a trade
    name; a "family" item names its listed family or, with none, "aliphatic polyesters" with a page; a "value" item
    names the polymer. `fail` maps call numbers to a failure, or "omit" (an item left out)."""

    def __init__(self, fail=None):
        self.calls, self.prompts, self.names, self.fail = 0, [], 0, fail or {}

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        assert schema is questions.WRITER_SCHEMA and engine == engines.CODEX and web and tools is None
        self.calls += 1
        self.prompts.append(prompt)
        failure = self.fail.get(self.calls)
        if failure and failure != "omit":
            raise engines.EngineError(failure, "scripted " + failure)
        out = []
        for item in json.loads(prompt.split("\nItems:\n", 1)[1]):
            prop = item["property"]["label"].lower()
            entry = {"item": item["item"], "property": prop, "evidenceUrl": "", "declined": False, "reason": ""}
            if item["kind"] == "name":
                self.names += 1
                material = item["namesAlreadyUsed"][0] if self.names == 1 else "Zyx-%d" % self.names
                entry.update(material=material, question="What %s has been reported for %s resin?" % (prop, material),
                             evidenceUrl="https://example.org/datasheet")
                if self.names == 2:
                    entry.update(declined=True, reason="no trade name known")
            elif item["kind"] == "family":
                material = item["family"][0]
                entry.update(material=material, question="What %s values are reported for %s polymers?" % (prop, material))
            elif item["kind"] == "other-family":
                assert "family" not in item
                entry.update(material="aliphatic polyesters", evidenceUrl="https://example.org/family",
                             question="What %s values are reported for aliphatic polyesters?" % prop)
            else:
                material = item["polymer"]
                entry.update(material=material, question="Report a published %s of %s, with its test method and the "
                                                         "specimen." % (prop, material))
            out.append(entry)
        if failure == "omit":
            out = out[1:]
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": {"questions": out},
                "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 1.0}


class L(Fixture):
    QUOTA = {"name": (1, 1, 0), "family": (0, 1, 1), "value": (1, 0, 1)}

    def setUp(self):
        super().setUp()
        for patch in (mock.patch.object(questions, "QUOTA", self.QUOTA), mock.patch.object(questions, "BATCH", 2)):
            patch.start()
            self.addCleanup(patch.stop)

    def guard(self, writer, quota=80):
        folder = pins.folder("questions")
        return driver.Guard(time.time() + 3600, read_quota=lambda e: {"remainingPercent": quota}, run_session=writer,
                            signed=lambda e: True, base=folder)

    def test_pairs_count_filed_non_rejected_material_property_findings_in_coverage_tertiles(self):
        pairs = questions.kf_pairs()
        self.assertEqual(pairs, {(s, CLASS[p]): n for (s, p), n in COUNTS.items()})
        parts = questions.tertiles(pairs, random.Random(questions.L_SEED))
        self.assertEqual([len(p) for p in parts], [5, 5, 5])  # (wop-000004, Tg) has only 2 findings
        counts = [sorted(n for *_, n in part) for part in parts]
        self.assertEqual(counts, [[3, 3, 3, 3, 4], [4, 4, 5, 5, 6], [6, 7, 7, 8, 8]])
        self.assertEqual(questions.tertiles(pairs, random.Random(questions.L_SEED)), parts)
        self.assertEqual(len(questions.slots()), 6)
        with mock.patch.dict(pins.PINS, kf={"findings": 1, "notes": 0, "sha256": "0"}), \
                self.assertRaisesRegex(SystemExit, "is not KF"):
            questions.kf_pairs()

    def test_the_writer_writes_from_the_pairs_alone_and_a_failed_check_redraws_the_pair(self):
        writer = Writer()
        state = questions.write_l(runner=self.guard(writer))
        self.assertEqual(state["status"], "completed", state)
        rows = read_json(questions.path("L.json"))
        self.assertEqual([(r["group"], r["stratum"], r.get("familyInSeed")) for r in rows],
                         [(g, "tertile-%d" % t, None if m is None else m == "seed") for g, t, m in questions.slots()])
        self.assertEqual([m for _, _, m in questions.slots()], [None] * 2 + ["seed", "unlinked"] + [None] * 2)
        work = pins.folder("questions") / "L-work"
        draws = read_json(work / "draws.json")
        self.assertEqual((len(draws), writer.calls), (9, 5))  # name places redrawn three times, two items a session
        outcomes = {i: o["problem"] for p in sorted((work / "batches").glob("*.json"))
                    for i, o in read_json(p)["outcomes"].items()}
        self.assertEqual(outcomes["a001"], "the name is one of the seed's names")
        self.assertEqual(outcomes["a002"], "declined: no trade name known")
        self.assertEqual(outcomes["a007"], "the name is used in 1 KF finding's material or statement")  # "Zyx-3"
        self.assertEqual([d["slot"] for d in draws[6:]], [0, 1, 0])
        self.assertNotEqual((draws[6]["polymer"], draws[6]["class"]), (draws[0]["polymer"], draws[0]["class"]))
        self.assertEqual(sorted(r["askedName"] for r in rows if r["group"] == "name"), ["Zyx-4", "Zyx-5"])
        self.assertEqual({r["nameUsedInKF"] for r in rows if r["group"] == "name"}, {0})
        aliases = knowledge.polymer_aliases(self.root)
        plan = read_json(work / "plan.json")
        for row in rows:
            for key in ("id", "set", "question", "materials", "polymerIds", "property", "propertyClass", "kind",
                        "group", "stratum", "findings", "polymer"):
                self.assertIn(key, row)
            self.assertEqual((row["set"], row["kind"]), ("L", row["group"]))
            self.assertIn(row["polymer"], row["polymerIds"])
            tertile = int(row["stratum"][-1])
            self.assertIn([row["polymer"], row["propertyClass"], row["findings"]],
                          plan["tertiles"][tertile - 1]["pairs"])
            if row["group"] == "name":
                self.assertNotIn(row["askedName"].lower(), aliases)
                self.assertTrue(row["evidenceUrl"].startswith("https://"))
            if row["group"] == "family" and row["familyInSeed"]:  # drawn from polymers the seed files in a family
                self.assertEqual((row["polymer"] in ("wop-000010", "wop-000011"), row["familyIds"]),
                                 (True, ["wop-000009"]))
            if row["group"] == "family" and not row["familyInSeed"]:
                self.assertEqual((row["family"], row["evidenceUrl"]),
                                 ("aliphatic polyesters", "https://example.org/family"))
        self.assertEqual(len({r["id"] for r in rows}), 6)
        self.assertTrue(all("Specimen" not in p and "finding:" not in p for p in writer.prompts))  # no finding shown
        self.assertEqual({r["phase"] for r in calls.records(pins.folder("questions"))}, {questions.PHASE})
        first = read_json(work / "batches/001.json")
        atomic_json(work / "batches/001.json", {k: v for k, v in first.items() if k != "outcomes"})  # stopped there
        again = Writer()
        self.assertEqual(questions.write_l(runner=self.guard(again))["status"], "completed")
        self.assertEqual((again.calls, read_json(work / "batches/001.json")["outcomes"]), (0, first["outcomes"]))

    def test_the_checks_of_each_kind(self):
        ctx = questions.context(self.root)
        draw = lambda group, polymer, mode=None: dict({"group": group, "polymer": polymer},
                                                      **({"mode": mode} if mode else {}))
        written = lambda question, material, url="": {"question": question, "material": material, "evidenceUrl": url,
                                                      "declined": False, "reason": "", "property": "tensile strength"}
        check = lambda group, polymer, *args, mode=None: questions.check(draw(group, polymer, mode), written(*args), ctx)
        url = "https://example.org/x"
        self.assertIsNone(check("name", "wop-000001", "What tensile strength has Zyx 3001D?", "Zyx 3001D", url))
        self.assertEqual(check("name", "wop-000001", "What tensile strength has Zyx 3001D PLA?", "Zyx 3001D", url),
                         "the question names the polymer or its family by a seed name")
        self.assertEqual(check("name", "wop-000001", "What tensile strength has Zyx 3001D?", "Zyx 3001D"),
                         "no evidence URL")
        self.assertEqual(check("name", "wop-000001", "What tensile strength has Polycaprolactone?", "Polycaprolactone",
                               url), "the name is one of the seed's names")
        self.assertEqual(check("name", "wop-000001", "What tensile strength has Zyx?", "Lexan", url),
                         "the material is not in the question")
        self.assertEqual(check("name", "wop-000001", "What tensile strength has ZYX 3 resin?", "ZYX 3", url),
                         "the name is used in 1 KF finding's material or statement")  # as whole words, any case
        self.assertIsNone(check("name", "wop-000001", "What tensile strength has Zyx-30 resin?", "Zyx-30", url))
        self.assertIsNone(check("family", "wop-000010", "What tensile strengths has the polyethylene family?",
                                "polyethylene family", mode="seed"))
        self.assertEqual(check("family", "wop-000010", "What tensile strengths have polyolefins?", "polyolefins", url,
                               mode="seed"), "the question does not name the seed's family")
        self.assertEqual(check("family", "wop-000010", "What tensile strengths has HDPE in the PE family?", "PE family",
                               mode="seed"), "the question names the polymer itself")
        self.assertIsNone(check("family", "wop-000010", "What tensile strengths have polyolefins?", "polyolefins", url,
                                mode="unlinked"))
        self.assertEqual(check("family", "wop-000010", "What tensile strengths has the polyethylene family?",
                               "polyethylene family", url, mode="unlinked"),
                         "the question names a family the seed links the polymer to")
        self.assertIsNone(check("family", "wop-000001", "What tensile strengths have aliphatic polyesters?",
                                "aliphatic polyesters", url, mode="unlinked"))
        self.assertEqual(check("family", "wop-000001", "What tensile strengths have aliphatic polyesters?",
                               "aliphatic polyesters", mode="unlinked"), "no evidence URL")
        self.assertIsNone(check("value", "wop-000003", "Report a tensile strength of PS with its method and specimen.",
                                "PS"))
        self.assertEqual(check("value", "wop-000003", "Report a tensile strength of ps foam with its specimen.", "ps"),
                         "the question does not name the polymer by a seed name")
        self.assertEqual(questions.check(draw("value", "wop-000003"), None, ctx), "not written")

    def test_a_quota_stop_is_resumed_without_asking_a_batch_again_and_a_left_out_item_is_tried_again(self):
        writer = Writer(fail={2: "omit", 4: "quota"})
        state = questions.write_l(runner=self.guard(writer))
        self.assertEqual((state["status"], state["stopReason"]), ("stopped", "quota"))
        batches = [read_json(p) for p in sorted((pins.folder("questions") / "L-work/batches").glob("*.json"))]
        self.assertEqual([a.get("reason") for a in batches[1]["attempts"]], ["invalid-output", None])
        self.assertTrue(driver._ok(batches[1]["result"]))
        self.assertEqual([a.get("reason") for a in batches[2]["attempts"]], ["quota"])
        self.assertFalse(questions.path("L.json").exists())
        writer = Writer()
        writer.names = 2  # the first two name items were answered in the first run
        self.assertEqual(questions.write_l(runner=self.guard(writer))["status"], "completed")
        self.assertEqual(writer.calls, 3)  # batch 3 again, the redraws, then a redraw of the name KF uses
        self.assertEqual(questions.status()["L-work"]["batchesOpen"], 0)

    def test_no_writer_session_unless_the_code_is_the_tag_or_while_codex_is_below_its_floor(self):
        writer = Writer()
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("Tag study-freeze-3 does not exist yet")):
            with self.assertRaisesRegex(SystemExit, "study-freeze-3"):
                questions.write_l(runner=self.guard(writer))
        self.assertEqual(questions.write_l(runner=self.guard(writer, quota=1))["stopReason"], "quota")
        self.assertEqual(writer.calls, 0)


class Hashes(Fixture):
    def test_hashes_are_written_once_all_three_sets_exist_and_a_changed_set_is_refused(self):
        rows = {name: [{"id": name.lower() + "1", "set": name, "question": "Q %s?" % name}] for name in pins.SETS}
        for name in ("H", "N"):
            atomic_json(questions.path(name + ".json"), rows[name])
        with self.assertRaisesRegex(SystemExit, "Not written yet: L"):
            questions.hashes()
        with self.assertRaisesRegex(SystemExit, "not fixed by hash"):
            questions.load("H")
        atomic_json(questions.path("L.json"), rows["L"])
        value = questions.hashes()
        self.assertEqual(value["sets"], {name: digest(rows[name]) for name in pins.SETS})
        self.assertEqual(questions.load("N"), rows["N"])
        self.assertEqual(questions.hashes()["sets"], value["sets"])
        atomic_json(questions.path("N.json"), [dict(rows["N"][0], question="Changed?")])
        with self.assertRaisesRegex(SystemExit, "N.json differs from its hash"):
            questions.load("N")
        with self.assertRaisesRegex(SystemExit, "other hashes"):
            questions.hashes()
        self.assertEqual(questions.status()["N"]["hashed"], False)


class Commitments(Fixture):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(questions, "COMMITMENTS", self.top / "commitments.json")
        patch.start()
        self.addCleanup(patch.stop)
        atomic_json(questions.COMMITMENTS, dict({k: {} for k in questions.ENTRIES}, format=questions.COMMITTED))
        for name in pins.SETS:
            atomic_json(questions.path(name + ".json"), [{"id": name.lower() + "1", "set": name, "question": "Q?"}])
        questions.hashes()

    def test_the_tracked_file_has_every_entry_and_an_entry_is_printed_written_once_and_never_replaced(self):
        tracked = read_json(Path(questions.__file__).with_name("commitments.json"))  # filled as the study runs
        self.assertEqual((tracked["format"], set(tracked) - {"format"}), (questions.COMMITTED, set(questions.ENTRIES)))
        entry = questions.question_entry()
        self.assertEqual(entry, {"hashes.json": questions.file_digest(questions.path("hashes.json")),
                                 "files": {n + ".json": questions.file_digest(questions.path(n + ".json"))
                                           for n in pins.SETS}})
        self.assertEqual(questions.commit_questions(), {"questions": entry})  # printed only
        self.assertEqual(questions.differs("questions", entry), "commitments.json has no questions entry")
        questions.commit_questions(write=True)
        self.assertIsNone(questions.differs("questions", entry))
        self.assertEqual(questions.COMMITMENTS.read_text().splitlines()[0], "{")  # one key a line, for review in git
        with self.assertRaisesRegex(SystemExit, "holds another questions entry"):
            questions.commit({"questions": dict(entry, files={})}, write=True)
        self.assertEqual(questions.commitments()["questions"], entry)

    def test_in_head_is_true_only_for_a_file_committed_as_it_is(self):
        repo = self.top / "repo"
        repo.mkdir()
        target = repo / "commitments.json"
        target.write_text("{}\n")
        self.assertFalse(questions.in_head(target))  # not a repository yet
        git = lambda *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c",  # noqa
                                            "commit.gpgsign=false", *args], cwd=repo, capture_output=True, check=True)
        git("init", "-q")
        self.assertFalse(questions.in_head(target))  # not committed
        git("add", "commitments.json")
        git("commit", "-q", "-m", "commitments")
        self.assertTrue(questions.in_head(target))
        target.write_text('{"questions": {}}\n')
        self.assertFalse(questions.in_head(target))  # changed since


PAIRS = {"C1": [{"material": "Zyx-3", "property": "tensile strength", "polymerIds": ["wop-000001"],
                 "replay": {"refined": ["finding:a"]}},
                {"material": "Ingeo 3251D", "property": "tensile strength", "polymerIds": ["wop-000001"],
                 "replay": {"refined": ["finding:b"]}},
                {"material": "Ingeo 2003D", "property": "tensile strength", "polymerIds": ["wop-000001"],
                 "replay": {"refined": ["finding:c"]}}],
         "C2": [{"material": "PCL film", "property": "tensile strength", "polymerIds": ["wop-000002"],
                 "replay": {"linkedHops": ["h-1"]}, "ask": "a value with its test method and specimen"}],
         "C7": [{"material": "PLA", "property": "tensile strength", "replay": {"x": 1}}]}
SELECTION = {"rules": {"C1": "names a polymer the seed does not know", "C2": "a hop reachable through a source link",
                       "C4": "property terms", "C7": "C1-C3 on K0"},
             "shortfalls": {"C1": 2, "C2": 3, "C4": 3, "C7": 1}, "cases": {}}


class CaseWriter:
    """The case-question writer by schema: it declines the first C1 item, leaves the material out of the second's
    question, and writes the rest. `fail` maps call numbers to a failure, or "extra" (an entry off the schema)."""

    def __init__(self, fail=None):
        self.calls, self.prompts, self.fail = 0, [], fail or {}

    def __call__(self, engine, prompt, schema, *, tools=None, web=True, timeout=600, progress=None, idle=None):
        assert schema is questions.C_SCHEMA and engine == engines.CODEX and not web and tools is None
        self.calls += 1
        self.prompts.append(prompt)
        failure = self.fail.get(self.calls)
        if failure and failure != "extra":
            raise engines.EngineError(failure, "scripted " + failure)
        out = []
        for item in json.loads(prompt.split("\nItems:\n", 1)[1]):
            text = "What %s has been reported for %s?" % (item["property"], item["material"])
            entry = {"item": item["item"], "question": text, "declined": False, "reason": ""}
            if item["item"] == "C1-1":
                entry.update(declined=True, reason="no source")
            elif item["item"] == "C1-2":
                entry["question"] = "What %s has been reported for this grade?" % item["property"]
            if failure == "extra":
                entry["material"] = item["material"]
            out.append(entry)
        return {"engine": engine, "model": "scripted", "sessionId": "s", "answer": {"questions": out},
                "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10},
                "observedTools": [], "agentSeconds": 1.0}


class CaseQuestions(Fixture):
    def setUp(self):
        super().setUp()
        atomic_json(pins.FOLDERS["cases"] / "selection.json", SELECTION)
        atomic_json(pins.FOLDERS["cases"] / "pairs.json", {"cases": PAIRS})

    def guard(self, writer, quota=80):
        return driver.Guard(time.time() + 3600, read_quota=lambda e: {"remainingPercent": quota}, run_session=writer,
                            signed=lambda e: True, base=pins.folder("questions"))

    def test_one_session_per_short_case_writes_from_the_mechanism_and_the_pairs_and_the_first_that_pass_are_kept(self):
        writer = CaseWriter()
        state = questions.write_c(runner=self.guard(writer))
        self.assertEqual((state["status"], state["short"]), ("completed", {"C1": 1, "C2": 2, "C4": 3}))
        self.assertEqual(writer.calls, 2)  # C1 and C2; C4 has no pair offered, and C7's questions are C1-C3's
        self.assertIn("The case: names a polymer the seed does not know", writer.prompts[0])
        items = json.loads(writer.prompts[1].split("\nItems:\n", 1)[1])
        self.assertEqual(items, [{"item": "C2-1", "material": "PCL film", "property": "tensile strength",
                                  "ask": "a value with its test method and specimen"}])
        self.assertTrue(all("finding:" not in p and "replay" not in p for p in writer.prompts))  # the pairs alone
        self.assertEqual({r["phase"] for r in calls.records(pins.folder("questions"))}, {questions.C_PHASE})
        outcomes = read_json(pins.folder("questions") / "C-work/C1.json")["outcomes"]
        self.assertEqual({k: v["problem"] for k, v in outcomes.items()},
                         {"C1-1": "declined: no source", "C1-2": "the material is not in the question as given",
                          "C1-3": None})
        rows = questions.load("C")
        self.assertEqual([(r["case"], r["materials"], r["property"], r["set"]) for r in rows],
                         [("C1", ["Ingeo 2003D"], "tensile strength", "C"),
                          ("C2", ["PCL film"], "tensile strength", "C")])
        self.assertEqual(rows[1]["pair"]["replay"], {"linkedHops": ["h-1"]})
        self.assertEqual((rows[0]["rule"], rows[0]["polymerIds"]), (SELECTION["rules"]["C1"], ["wop-000001"]))
        self.assertEqual(read_json(questions.path("case-hashes.json"))["sets"], {"C": digest(rows)})
        self.assertEqual(questions.write_c(runner=self.guard(writer))["C"], state["C"])  # done: nothing asked again
        self.assertEqual(writer.calls, 2)
        atomic_json(pins.FOLDERS["cases"] / "pairs.json", {"cases": dict(PAIRS, C2=[])})
        with self.assertRaisesRegex(SystemExit, "fixed once written"):  # the plan is fixed once written
            questions.write_c(runner=self.guard(writer))

    def test_a_quota_stop_resumes_without_asking_a_finished_case_and_an_answer_off_the_schema_is_tried_again(self):
        writer = CaseWriter(fail={1: "extra", 3: "quota"})
        state = questions.write_c(runner=self.guard(writer))
        self.assertEqual((state["status"], state["stopReason"]), ("stopped", "quota"))
        first = read_json(pins.folder("questions") / "C-work/C1.json")
        self.assertEqual([a.get("reason") for a in first["attempts"]], ["invalid-output", None])
        self.assertFalse(questions.path("C.json").exists())
        writer = CaseWriter()
        self.assertEqual(questions.write_c(runner=self.guard(writer))["status"], "completed")
        self.assertEqual(writer.calls, 1)  # C2 only

    def test_no_session_unless_the_code_is_the_tag_and_pairs_need_what_the_replay_shows(self):
        writer = CaseWriter()
        with mock.patch.object(pins, "frozen", side_effect=SystemExit("Tag study-freeze-3 does not exist yet")):
            with self.assertRaisesRegex(SystemExit, "study-freeze-3"):
                questions.write_c(runner=self.guard(writer))
        bad = dict(PAIRS, C2=[{"material": "PCL film", "property": "tensile strength"}])
        atomic_json(pins.FOLDERS["cases"] / "pairs.json", {"cases": bad})
        with self.assertRaisesRegex(SystemExit, "what the replay shows"):
            questions.write_c(runner=self.guard(writer))
        self.assertEqual(writer.calls, 0)


if __name__ == "__main__":
    unittest.main()
