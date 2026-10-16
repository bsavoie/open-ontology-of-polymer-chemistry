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


def prepare():
    if (BASE / "workspaces").exists():
        raise SystemExit("The workspaces exist; they are never rebuilt.")
    (BASE / "workspaces").mkdir(mode=0o700)
    copy_store(SOURCE, workspace("C"))
    store = copy_store(SOURCE, workspace("planted"))
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


def report():
    store = workspace("planted")
    db = sqlite3.connect(knowledge.database(store).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    verdicts = {r["id"]: {"status": r["status"], "reason": r["review_reason"]}
                for r in db.execute("SELECT id, status, review_reason FROM findings WHERE question_id=?", (DEPOSIT,))}
    db.close()
    rows = []
    for plant in PLANTS:
        for arm, reps in ARMS.items():
            for rep in range(reps):
                a, c = result_path(plant, arm, rep, "answer"), result_path(plant, arm, rep, "check")
                if not a.exists() or "error" in read_json(a):
                    continue
                answer = read_json(a)
                text = (answer.get("answer") or {}).get("answer") or ""
                cited = [x for x in (answer.get("answer") or {}).get("citations") or [] if isinstance(x, str)]
                check = read_json(c) if c.exists() else {}
                statements = check.get("statements") or []
                rows.append(dict(case=plant["case"], arm=arm, rep=rep,
                                 plantedValue=bool(re.search(plant["planted"], text)),
                                 trueValue=bool(re.search(plant["true"], text)),
                                 citesPlanted=plant["id"] in cited, findingCitations=sum(x.startswith("finding:") for x in cited),
                                 webCalls=(answer.get("metrics") or {}).get("webCalls"),
                                 newTokens=(answer.get("metrics") or {}).get("newTokens"),
                                 verdict=check.get("verdict"),
                                 contradicted=sum(s.get("verdict") == "unsupported" and s.get("category") != "source-access"
                                                  for s in statements)))
    value = {"reviewerVerdicts": {p["case"]: verdicts.get(p["id"]) for p in PLANTS}, "answers": rows}
    atomic_json(BASE / "report.json", value, private=True)
    print(json.dumps(value["reviewerVerdicts"], indent=1, ensure_ascii=False))
    for r in rows:
        print(r)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run", "report"])
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": report}[args.command]()
