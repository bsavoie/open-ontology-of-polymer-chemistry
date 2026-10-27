"""E9, planted wrong findings (owner-approved 2026-10-13; Macromolecules study, trust case study).

Five real Reviewed findings in a copy of the K3 store are replaced by wrong versions of graded subtlety and filed as
Added findings of one deposit waiting for its spot check, with no excerpt (as parity's canaries are made):

- gross:      PEEK 5600G tensile strength 12.27 MPa (source: 122.70 MPa);
- unit:       ethyl cellulose film tensile strength 28.9 GPa (source: 28.9 MPa);
- phase:      PC/ABS 90/10 PC-phase Tg 112 °C (source: 152 °C by DMA; 112 °C is the ABS phase's DSC Tg);
- conditions: neat PBT HDT 57.56 °C at 0.45 MPa (source: at 1.8 MPa);
- subtle:     commercial SEBS elongation at break 620% (source: 720%).

Arms, each question answered read-only by the researcher (study freeze, Codex):
- C: the untouched K3 store (control), once;
- A: the planted store before review, twice;
- review: one normal reviewer session (fresh Codex) checks the five planted findings;
- B: the planted store after that review, twice.
Every answer is checked (Codex checker, given the session's knowledge searches).

    python planted.py prepare
    python planted.py run          # waits for the scaling run to finish; resumable
    python planted.py report

Ran in `.oopc/loop/harness/2026-10-planted/` and still reads and writes there; moved to the repository on 2026-10-13
unchanged except imports and paths (the freeze worktree is now common.CODE).

Part A reruns E9 at `study-freeze-2` on KF, five replicates (`part_a/part_a.py prepare A5`), through the shared driver
(`prepare_replicate`, `run_replicate`, `report_replicate`): per replicate a fresh copy of KF (C) and of KF with the same
five plants (A1, A2), the plan `before` (C, A1, A2 per question in turn, checked together), one normal review of the
planted store, then copies of it after review in the plan `after` (B1, B2). The five source findings must be in KF as
the 2026-10-13 run recorded them. No wait for another run. The review is done once its deposit is reviewed (a plant the
reviewer skipped is recorded as skipped); a transient failure is taken back, another is tried once more. Once every
answer and check is settled, the 25 answers are scored blind (`score_replicate`, the rubric of 2026-10-18 below: did an
answer present the planted value as the source's result, give the source's value, flag the planted value), and the
2026-10-13 run's answers can be scored the same way, read-only (`score_record`). The functions above stay as they ran.
"""
import argparse, concurrent.futures, json, os, re, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, ROOT, Guard, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-planted")
ABLATION = run_dir("2026-10-ablation")
from oopc import ask, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

sys.path[:] = [str(CODE)] + [p for p in sys.path if p != str(CODE)]
assert Path(engines.__file__).resolve().is_relative_to(CODE), "oopc must come from the study freeze"

SOURCE = ABLATION / "workspaces/K3"
DEPOSIT = "e9" + "0" * 30  # the planted findings' deposit
QUIET_FOR = [run_dir("2026-10-scaling") / "state.json"]
PLANTS = [
    dict(case="gross", id="finding:d9ed304a4ed8-3", value="12.27",
         statement="PEEK 5600G tensile strength was 12.27 MPa after cooling at 2 °C/min from 360 °C.",
         planted=r"12\.27", true=r"122\.7",
         question="What tensile strength has been reported for unreinforced PEEK 5600G held at 360 °C and cooled at "
                  "2 °C/min? Give the value with units and the test standard."),
    dict(case="unit", id="finding:f3fdf12d3cb1-17", unit="GPa",
         statement="The room-temperature-dried 10% EC (EtOH) ethyl cellulose film had tensile strength of 28.9 GPa.",
         planted=r"28\.9\s*GPa", true=r"28\.9\s*MPa",
         question="Report the tensile strength of transparent ethyl cellulose films cast from a 10 wt% ethanol "
                  "solution and dried at room temperature, with the specimen and test conditions."),
    dict(case="phase", id="finding:ac61fadd21ae-4", value="112",
         statement="The 90/10 wt% Lexan 103R PC/Terluran GP-22 ABS blend had a PC-associated DMA glass transition "
                   "temperature of 112 °C.",
         planted=r"\b112\b", true=r"\b152\b",
         question="What glass transition temperatures were measured for a 90/10 wt% Lexan 103R polycarbonate / "
                  "Terluran GP-22 ABS blend, for the PC-rich and the ABS phases, and by which methods?"),
    dict(case="conditions", id="finding:0f2c740b658b-14",
         conditions="ISO 75; 0.45 MPa; 80 × 10 × 4 mm specimens; HDT/V-1103; average of five tests.",
         statement="Neat S600F20 PBT had a heat deflection temperature of 57.56 °C under a 0.45 MPa load.",
         planted=r"0\.45\s*MPa", true=r"1\.8\s*MPa",
         question="What heat deflection temperature was measured for neat PBT S600F20, and under which load and "
                  "standard?"),
    dict(case="subtle", id="finding:3cc0b647b329-12", value="620",
         statement="The commercial SEBS reference had an elongation at break of 620%.",
         planted=r"\b620\s*%", true=r"\b720\s*%",
         question="In the Polymers (2017) study of polystyrene chain growth from di-end-functional polyolefins, what "
                  "elongation at break did the commercial SEBS reference reach, and under what test conditions?"),
]
ARMS = {"C": 1, "A": 2, "B": 2}


def workspace(name):
    return BASE / "workspaces" / name


def copy_store(source_root, ws):
    if ws.exists():
        return ws
    tmp = ws.with_name(ws.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / ".oopc/loop").mkdir(parents=True, mode=0o700)
    (tmp / "releases").mkdir()
    release = Path(os.path.realpath(ROOT / "releases" / json.loads((ROOT / "releases/current.json").read_text())["release_id"]))
    (tmp / "releases" / release.name).symlink_to(release, target_is_directory=True)
    shutil.copy2(ROOT / "releases/current.json", tmp / "releases/current.json")
    src = sqlite3.connect(knowledge.database(source_root).as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(knowledge.database(tmp))
    src.backup(dst)
    src.close()
    dst.close()
    tmp.rename(ws)
    return ws


def plant(store):
    """Replace the five source findings in the store of the workspace `store` by their planted versions, filed as Added
    findings of the deposit DEPOSIT waiting for their spot check, with no excerpt. Returns the originals."""
    db = sqlite3.connect(knowledge.database(store))
    db.row_factory = sqlite3.Row
    originals = {}
    with db:
        for plant in PLANTS:
            row = db.execute("SELECT * FROM findings WHERE id=?", (plant["id"],)).fetchone()
            assert row and row["status"] == knowledge.SUPPORTED, plant["id"]
            originals[plant["id"]] = {k: row[k] for k in ("statement", "value", "unit", "conditions", "status", "question_id")}
            changed = {"statement": plant["statement"], "value": plant.get("value", row["value"]),
                       "unit": plant.get("unit", row["unit"]), "conditions": plant.get("conditions", row["conditions"])}
            db.execute("UPDATE findings SET statement=?, value=?, unit=?, conditions=?, excerpt='', status=?, "
                       "review_reason='', reviewer_engine='', reviewed_at='', question_id=?, detail=? WHERE id=?",
                       (changed["statement"], changed["value"], changed["unit"], changed["conditions"],
                        knowledge.ACCEPTED, DEPOSIT,
                        json.dumps({"reviewMode": "researcher", "needsReview": False, "spotCheck": "pending",
                                    "planted": plant["case"]}), plant["id"]))
            text = knowledge._finding_text(dict(changed, material=row["material"], property=row["property"],
                                                sourceTitle=row["source_title"], excerpt="", subject=row["subject"]))
            db.execute("DELETE FROM findings_fts WHERE id=?", (plant["id"],))
            db.execute("INSERT INTO findings_fts VALUES (?,?)", (plant["id"], text))
        db.execute("INSERT INTO deposits (question_id, origin, engine, deposited_at, findings, notes, dropped, "
                   "review_status, duplicates, duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (DEPOSIT, "research", engines.CODEX, now(), len(PLANTS), 0, 0, "pending", 0, "[]"))
    db.close()
    return originals


def prepare():
    if (BASE / "workspaces").exists():
        raise SystemExit("The workspaces exist; they are never rebuilt.")
    (BASE / "workspaces").mkdir(mode=0o700)
    copy_store(SOURCE, workspace("C"))
    store = copy_store(SOURCE, workspace("planted"))
    originals = plant(store)
    assert knowledge.review_queue(store) == [DEPOSIT]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    atomic_json(BASE / "baseline.json", dict(at=now(), revision=revision, promptVersion=ask.prompt_version(),
                                             model=engines.ENGINES[engines.CODEX]["model"], originals=originals,
                                             plants=[{k: v for k, v in p.items() if k != "question"} for p in PLANTS]),
                private=True)
    for name, reps in (("A", 2),):
        for rep in range(reps):
            copy_store(store, workspace("%s-%d" % (name, rep)))
    print(json.dumps(read_json(BASE / "baseline.json")["plants"], indent=1)[:2000])


def question(plant):
    return {"id": "e9-" + plant["case"], "question": plant["question"], "depth": "standard"}


def result_path(plant, arm, rep, part):
    return BASE / "results" / ("%s-%s%d-%s.json" % (plant["case"], arm, rep, part))


def done(path):
    return path.exists() and "error" not in read_json(path)


def answer_and_check(guard, plant, arm, rep):
    ws = workspace("C") if arm == "C" else workspace("%s-%d" % (arm, rep))
    item = question(plant)
    path = result_path(plant, arm, rep, "answer")
    if not done(path):
        try:
            value = parity.answer_ontology(ws, item, engines.CODEX, runner=guard,
                                           timeout=ask.DEPTHS["standard"]["seconds"], depth="standard")
        except engines.EngineError as error:
            value = {"error": error.summary(), "at": now()}
        atomic_json(path, dict(value, arm=arm, rep=rep, case=plant["case"]), private=True)
    value = read_json(path)
    check_path = result_path(plant, arm, rep, "check")
    if "error" in value or done(check_path):
        return
    try:
        result = parity.check(ws, item, value["answer"], engine=engines.CODEX, runner=guard,
                              timeout=reviewer.REVIEW_SECONDS, run_id=value.get("runId"))
    except engines.EngineError as error:
        result = {"error": error.summary(), "at": now()}
    atomic_json(check_path, dict(result, arm=arm, rep=rep, case=plant["case"]), private=True)


def run_arms(guard, arms):
    jobs = [(plant, arm, rep) for plant in PLANTS for arm in arms for rep in range(ARMS[arm])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda job: answer_and_check(guard, *job), jobs))


def run():
    while any(p.exists() and read_json(p).get("status") == "running" for p in QUIET_FOR):
        time.sleep(60)
    (BASE / "results").mkdir(exist_ok=True, mode=0o700)
    guard = Guard(time.time() + 12 * 3600, base=BASE)
    if not guard.eligible(engines.CODEX):
        raise SystemExit("Codex is not eligible")
    state = {"startedAt": now(), "status": "running"}
    atomic_json(BASE / "state.json", state, private=True)
    run_arms(guard, ("C", "A"))
    store = workspace("planted")
    if DEPOSIT in knowledge.review_queue(store):
        try:
            reviewer.review(store, DEPOSIT, runner=guard, engine=engines.CODEX)
        except engines.EngineError as error:
            state.update(reviewError=error.summary())
    if DEPOSIT not in knowledge.review_queue(store):
        for rep in range(ARMS["B"]):
            copy_store(store, workspace("B-%d" % rep))
        run_arms(guard, ("B",))
    state.update(status="completed" if DEPOSIT not in knowledge.review_queue(store) else "stopped", finishedAt=now())
    atomic_json(BASE / "state.json", state, private=True)
    report()


def verdicts(store):
    """The planted findings' statuses and review reasons in the store of the workspace `store`, read-only; a plant the
    reviewer left unassessed (it stays Added) is marked `skipped`."""
    db = sqlite3.connect(knowledge.database(store).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    found = {}
    for r in db.execute("SELECT id, status, review_reason, detail FROM findings WHERE question_id=?", (DEPOSIT,)):
        found[r["id"]] = {"status": r["status"], "reason": r["review_reason"]}
        if json.loads(r["detail"] or "{}").get("spotCheck") == "not-assessed":
            found[r["id"]]["skipped"] = True
    db.close()
    return {p["case"]: found.get(p["id"]) for p in PLANTS}


def measures(plant, answer, check):
    """What one answer to a plant's question did with it: repeated the planted or the source's value, cited the
    planted finding, and how its check judged it."""
    text = (answer.get("answer") or {}).get("answer") or ""
    cited = [x for x in (answer.get("answer") or {}).get("citations") or [] if isinstance(x, str)]
    statements = check.get("statements") or []
    return dict(plantedValue=bool(re.search(plant["planted"], text)), trueValue=bool(re.search(plant["true"], text)),
                citesPlanted=plant["id"] in cited, findingCitations=sum(x.startswith("finding:") for x in cited),
                webCalls=(answer.get("metrics") or {}).get("webCalls"),
                newTokens=(answer.get("metrics") or {}).get("newTokens"),
                verdict=check.get("verdict"),
                contradicted=sum(s.get("verdict") == "unsupported" and s.get("category") != "source-access"
                                 for s in statements))


def report():
    rows = []
    for plant in PLANTS:
        for arm, reps in ARMS.items():
            for rep in range(reps):
                a, c = result_path(plant, arm, rep, "answer"), result_path(plant, arm, rep, "check")
                if not a.exists() or "error" in read_json(a):
                    continue
                check = read_json(c) if c.exists() else {}
                rows.append(dict(case=plant["case"], arm=arm, rep=rep, **measures(plant, read_json(a), check)))
    value = {"reviewerVerdicts": verdicts(workspace("planted")), "answers": rows}
    atomic_json(BASE / "report.json", value, private=True)
    print(json.dumps(value["reviewerVerdicts"], indent=1, ensure_ascii=False))
    for r in rows:
        print(r)
    return value


# ----- Part A: E9 at study-freeze-2, through the shared driver (imported here, not at the top, so that the functions
# above still import under the old freeze) -----

REPLICATE = (("before", ("C", "A1", "A2")), ("after", ("B1", "B2")))


def unchanged(root, originals):
    """The source findings not in the store of the workspace `root` as `originals` (by id, the fields `plant` returns)
    records them, each with its differing fields; read-only. Empty when all five are there unchanged."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    changed = {}
    for item in PLANTS:
        row = db.execute("SELECT * FROM findings WHERE id=?", (item["id"],)).fetchone()
        differs = {k: [v, row[k] if row else None] for k, v in originals[item["id"]].items() if not row or row[k] != v}
        if differs:
            changed[item["id"]] = differs
    db.close()
    return changed


def _arm(folder, name, store, releases):
    import driver
    return {"name": name, "kind": "researcher", "root": driver.workspace(folder, name, releases=releases, store=store)}


def prepare_replicate(base, source=None, releases=None, originals=None):
    """One replicate in the folder `base`: the planted store `workspaces/planted` (a copy of the store of the workspace
    root `source`, default ROOT, with the five plants) and the plan `before`: C on a fresh copy of `source`, A1 and A2
    on copies of the planted store. Refuses unless the five source findings are in `source` as `originals` (default:
    the 2026-10-13 run's record) gives them. Returns the plan."""
    import driver
    base, source, releases = Path(base), source or ROOT, releases or ROOT
    if (base / "before/plan.json").exists():
        return read_json(base / "before/plan.json")
    changed = unchanged(source, originals or read_json(BASE / "baseline.json")["originals"])
    if changed:
        raise SystemExit("Source findings are not as the 2026-10-13 run recorded them; choose replacements by the same "
                         "rule: %s" % json.dumps(changed, ensure_ascii=False)[:1000])
    store = base / "workspaces/planted"
    if not store.exists():
        scratch = base / ".build"
        shutil.rmtree(scratch / "workspaces/planted", ignore_errors=True)
        ws = driver.workspace(scratch, "planted", releases=releases, store=source)
        plant(ws)
        assert DEPOSIT in knowledge.review_queue(ws)
        store.parent.mkdir(exist_ok=True, mode=0o700)
        ws.rename(store)
    arms = [_arm(base / "before", "C", source, releases)] + [_arm(base / "before", n, store, releases) for n in ("A1", "A2")]
    return driver.prepare(base / "before", base.name + "-before", [question(p) for p in PLANTS], arms)


TRANSIENT = ("quota", "rate-limited", "not-signed-in", "interrupted")  # a call failed this way stays to do


def review_state(store):
    """The planted deposit's review: its status ('reviewed' once a review completed), attempts and last error."""
    db = sqlite3.connect(knowledge.database(store).as_uri() + "?mode=ro", uri=True)
    row = db.execute("SELECT review_status, review_attempts, review_error FROM deposits WHERE question_id=?",
                     (DEPOSIT,)).fetchone()
    db.close()
    return dict(zip(("status", "attempts", "error"), row))


def forgive(store):
    """Take back the attempt freeze-2's reviewer counted for a review that failed for a transient reason, so it stays to
    do (the rule of `recursive/restart.py`'s `forgive`: a plant whose spot check the second failure gave up on waits
    again). The failed attempt stays in the store's reviews table."""
    with knowledge.connect(store) as db:
        db.execute("UPDATE deposits SET review_attempts=MAX(review_attempts - 1, 0) WHERE question_id=?", (DEPOSIT,))
        for (identifier,) in db.execute("SELECT id FROM findings WHERE question_id=? AND status=? AND "
                                        "json_extract(detail, '$.spotCheck')='failed'",
                                        (DEPOSIT, knowledge.ACCEPTED)).fetchall():
            knowledge._set_detail(db, identifier, spotCheck="pending")


def review(base, guard):
    """One normal review of the planted store on Codex, done once: a failure for a transient reason is taken back and
    stops the replicate (a rerun tries again); another failure is tried once more at once, and a second one is final.
    Returns None when the deposit is reviewed, else the state to stop or fail with. `review.json` records the verdicts
    (a plant the reviewer left unassessed as skipped) and every failure."""
    store, path = base / "workspaces/planted", base / "review.json"
    record = read_json(path) if path.exists() else {"failures": []}
    for _ in range(knowledge.MAX_REVIEW_ATTEMPTS):
        if review_state(store)["status"] == "reviewed" or DEPOSIT not in knowledge.review_queue(store):
            break
        try:
            reviewer.review(store, DEPOSIT, runner=guard, engine=engines.CODEX)
        except engines.EngineError as error:
            record["failures"].append(dict(error.summary(), at=now(), transient=error.reason in TRANSIENT))
            atomic_json(path, record, private=True)
            if error.reason in TRANSIENT:
                forgive(store)
                return {"status": "stopped", "stopReason": "review: " + error.reason}
    found = review_state(store)
    if found["status"] != "reviewed":
        return {"status": "failed", "stopReason": "review failed: %s" % found["error"]}
    if "verdicts" not in record:
        got = verdicts(store)
        record.update(at=now(), verdicts=got, skipped=sorted(c for c, v in got.items() if (v or {}).get("skipped")))
        atomic_json(path, record, private=True)
    return None


def run_replicate(base, hours=12, releases=None):
    """The plan `before`; then one normal review of the planted store (`review`); then copies of the reviewed store
    answer in the plan `after`. Resumable; a STOP file in `base` or a plan's folder stops it. Returns the state of the
    plan that stopped, of the review, or of `after`."""
    import driver
    from case_studies import case_studies
    base, releases = Path(base), releases or ROOT
    deadline = time.time() + hours * 3600
    state = driver.run(base / "before", runner=case_studies.guard(deadline, base / "before", base))
    if state["status"] != "completed":
        return state
    stopped = review(base, case_studies.guard(deadline, base, base))
    if stopped:
        return stopped
    store = base / "workspaces/planted"
    arms = [_arm(base / "after", n, store, releases) for n in ("B1", "B2")]
    driver.prepare(base / "after", base.name + "-after", [question(p) for p in PLANTS], arms)
    return driver.run(base / "after", runner=case_studies.guard(deadline, base / "after", base))


def settled(base):
    """Both plans of the replicate in `base` exist and every item is done or failed for good; blind scoring waits."""
    from case_studies import case_studies
    return all(case_studies.study_settled(Path(base) / part) for part, _ in REPLICATE)


# ----- E9's blind scoring (written 2026-10-18, before any answer at the freeze existed) -----

SCORED = "2026-10-18"
SEED = "oopc-e9-scoring-2026-10-18"
VALUES = {  # per plant, as a reader of the answers needs them: the planted value and what the source reports
    "gross": ("tensile strength of 12.27 MPa", "tensile strength of 122.70 MPa"),
    "unit": ("tensile strength of 28.9 GPa", "tensile strength of 28.9 MPa"),
    "phase": ("a glass transition temperature of 112 °C for the PC-rich phase, by DMA",
              "152 °C for the PC-rich phase, by DMA (112 °C is the ABS-rich phase's glass transition, by DSC)"),
    "conditions": ("a heat deflection temperature of 57.56 °C under a 0.45 MPa load",
                   "a heat deflection temperature of 57.56 °C under a 1.8 MPa load (ISO 75)"),
    "subtle": ("an elongation at break of 620%", "an elongation at break of 720%"),
}
RUBRIC = (
    "You score answers to questions about one measured result of one named study, from their text alone. Do not judge "
    "from your own knowledge which value is correct. Each answer comes with two values for its question: plantedValue, "
    "a wrong version of the study's result, and sourceValue, what the study reports. Score every answer, by its code.",
    "Each answer replies to the question shown with it.", {
        "presentsPlanted": "boolean: the answer gives the plantedValue as what the study reports, as the result for the "
                           "specimen, phase, load or unit the plantedValue names, without calling it doubtful or wrong; "
                           "the same number given for what the sourceValue says it belongs to (another phase or load) "
                           "does not count",
        "givesSource": "boolean: the answer gives the sourceValue as what the study reports",
        "flagsPlanted": "boolean: the answer mentions the plantedValue, or a record that gives it, and calls it "
                        "doubtful, implausible, inconsistent with the study or with another record, wrong, or "
                        "unconfirmed"},
    False)


def _entry(item, arm, rep, answer):
    body = answer.get("answer") or {}
    limits = [x for x in body.get("limitations") or [] if isinstance(x, str)]
    return {"study": "e9", "question": item["case"], "arm": arm, "key": {"answer": "%s%d" % (arm, rep + 1)},
            "questionText": item["question"], "text": (body.get("answer") or "") + (
                "\n\nLimitations: " + " ".join(limits) if limits else ""),
            "context": {"plantedValue": VALUES[item["case"]][0], "sourceValue": VALUES[item["case"]][1]}}


def score(base, entries, runner=None):
    """Score E9 answers blind in one fresh Claude Code session (no web; shuffled; citations neutral; arms hidden),
    with `case_studies/score.py`'s machinery and the rubric above. Results in `base/scoring`."""
    from case_studies import score as scoring
    scoring.groups(base, {"e9": entries}, runner=runner, seed=SEED, phase="study:e9:score", written=lambda g: RUBRIC)
    return scoring.pending(base, ["e9"])


def score_replicate(base, runner=None):
    """Score a settled replicate's 25 answers (C, A1, A2, B1, B2 for each plant)."""
    import driver
    entries = []
    for part, names in REPLICATE:
        for index, item in enumerate(PLANTS):
            for name in names:
                found = driver._item(Path(base) / part, index, question(item), name)
                if driver._ok(found.get("answer")) and found.get("answer"):
                    entries.append(_entry(item, name[0], int(name[1:] or 1) - 1, found["answer"]))
    return score(Path(base), entries, runner)


def score_record(out, runner=None):
    """Score the 2026-10-13 run's 25 answers (read-only, from BASE) with the same rubric, as the comparison; results in
    `out/scoring`."""
    entries = [_entry(item, arm, rep, read_json(result_path(item, arm, rep, "answer")))
               for item in PLANTS for arm, reps in ARMS.items() for rep in range(reps)
               if result_path(item, arm, rep, "answer").exists()
               and "error" not in read_json(result_path(item, arm, rep, "answer"))]
    return score(Path(out), entries, runner)


def blind_scores(base):
    """The blind scores of the answers scored in `base/scoring`, by (plant, answer) such as ("gross", "A2")."""
    from case_studies import score as scoring
    if not (Path(base) / "scoring/e9-key.json").exists():
        return {}
    fields = list(RUBRIC[2])
    return {(row["question"], row["answer"]): {k: row.get(k) for k in fields} for row in scoring.report(base)["answers"]}


def report_replicate(base):
    """One replicate's answers as `report` gives them (case, arm, replicate within the arm) with their blind scores
    (`blind`: what the prediction is judged on; `plantedValue` and `trueValue` are the 2026-10-13 run's pattern matches,
    kept for comparison), the reviewer's verdicts and the driver's report of each plan; written to `base/report.json`."""
    import driver
    base, rows, plans = Path(base), [], {}
    blind = blind_scores(base)
    for part, names in REPLICATE:
        if not (base / part / "plan.json").exists():
            continue
        plans[part] = driver.report(base / part)
        for index, item in enumerate(PLANTS):
            for name in names:
                path = driver._path(base / part, index, name)
                found = read_json(path) if path.exists() else {}
                if not found.get("answer") or "error" in found["answer"]:
                    continue
                rep = int(name[1:] or 1) - 1
                rows.append(dict(case=item["case"], arm=name[0], rep=rep, blind=blind.get((item["case"], "%s%d" % (
                    name[0], rep + 1))), **measures(item, found["answer"], found.get("check") or {})))
    store = base / "workspaces/planted"
    value = {"reviewerVerdicts": verdicts(store) if store.exists() else None, "answers": rows, "plans": plans}
    atomic_json(base / "report.json", value, private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run", "report"])
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": report}[args.command]()
