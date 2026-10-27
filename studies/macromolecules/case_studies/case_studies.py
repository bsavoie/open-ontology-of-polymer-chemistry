"""The paper's four case studies (owner, 2026-10-15), pre-registered in
docs/exec-plans/active/macromolecules-study-plan.md ("Case studies"). They run only from tag `study-freeze-2` (the
pre-publication plan's phase 4), each researcher arm on a copy of the main store as it stands at that tag.

- cs1-conditions: Tg of three polymers whose saved findings span DSC and DMA; researcher (R) and plain session (P).
- cs2-conflicts: oxygen permeability of three polymers with many disagreeing saved values; R and P.
- cs3-screening: two rankings of polymers by oxygen permeability; R, the researcher on an empty store (R0), and P.
- cs4-unanswerable: three questions expected to have no answer in open sources, first asked through the normal loop
  on a store copy (answers saved and reviewed, so failed searches leave notes), then asked again in other words on
  that store (R) and by a plain session (P).

    python -B case_studies.py prepare    # plans and workspaces, fixed once written
    python -B case_studies.py run        # resumable; a STOP file in a study's folder stops it at a boundary
    python -B case_studies.py report

They ran once, on 2026-10-16, in `2026-10-case-studies` (BASE). Part A's replicates (`part_a/part_a.py prepare A5`) run
the same studies in their own folders, passed as `base`, each with fresh copies of the store.
"""
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common and driver
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from oopc import ask, engines, knowledge, parity  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

ROOT = common.ROOT
BASE = common.run_dir("2026-10-case-studies")
TAG = "study-freeze-2"

TG = ("What glass transition temperature has been reported for {m}, and how much do the reported values depend on "
      "the measurement method (DSC or DMA) and its conditions?")
OP = ("Published oxygen permeability values for {m} differ. What values are reported, under which conditions (film "
      "thickness, temperature, humidity, crystallinity), and what explains the differences?")
RANK = ("Rank {ms} by oxygen permeability, using published measurements. Give each value with its units, "
        "temperature and humidity, and say which comparisons are like for like.")
STUDIES = {
    "cs1-conditions": {"arms": ("R", "P"), "questions": [
        ("tpu", TG.format(m="thermoplastic polyurethane (TPU) elastomers")),
        ("fkm", TG.format(m="FKM fluoroelastomers")),
        ("pva", TG.format(m="poly(vinyl alcohol) (PVA)"))]},
    "cs2-conflicts": {"arms": ("R", "P"), "questions": [
        ("pvdc", OP.format(m="poly(vinylidene chloride) (PVDC) films")),
        ("phbv", OP.format(m="poly(3-hydroxybutyrate-co-3-hydroxyvalerate) (PHBV) films")),
        ("ppc", OP.format(m="poly(propylene carbonate) (PPC) films"))]},
    "cs3-screening": {"arms": ("R", "R0", "P"), "questions": [
        ("barrier", RANK.format(ms="poly(vinylidene chloride) (PVDC), polyamide 6, poly(ethylene terephthalate) (PET), "
                                   "isotactic polypropylene and polycaprolactone (PCL)")),
        ("biodegradable", RANK.format(ms="the biodegradable polymers PHBV, poly(butylene succinate) (PBS), "
                                         "polycaprolactone (PCL) and poly(propylene carbonate) (PPC)"))]},
}
UNANSWERABLE = [  # (id, first asking, asked again in other words)
    ("novoloid", "What oxygen permeability has been reported for novoloid (Kynol) fibers?",
     "Find a published measurement of the oxygen permeability of novoloid fiber (Kynol), with its conditions."),
    ("pox-loi", "What limiting oxygen index has been reported for poly(2-ethyl-2-oxazoline) (PEtOx)?",
     "Report a published limiting oxygen index (LOI) for poly(2-ethyl-2-oxazoline), with the test standard."),
    ("fepm-creep", "What creep compliance has been reported for tetrafluoroethylene-propylene elastomer (FEPM) after "
                   "1,000 h at 200 °C?",
     "Find a published long-term creep measurement of FEPM (Aflas) at 200 °C over about 1,000 h."),
]


def frozen():
    """The code under test is exactly the tag the case studies were pre-registered to run from."""
    try:
        tag = subprocess.check_output(["git", "rev-parse", TAG + "^{commit}"], cwd=ROOT, text=True,
                                      stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        raise SystemExit("Tag %s does not exist yet: the case studies run only from it." % TAG)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.CODE, text=True).strip()
    if head != tag:
        raise SystemExit("The code under test (%s) is not %s; set OOPC_STUDY_CODE to a worktree at the tag." % (head, TAG))
    return tag


def researcher(folder, name, store):
    return {"name": name, "kind": "researcher", "root": driver.workspace(folder, name, releases=ROOT, store=store)}


def arms_for(folder, names):
    arms = []
    for name in names:
        if name == "P":
            arms.append({"name": "P", "kind": "plain"})
        elif name == "R0":  # an empty store: no findings, no notes
            arms.append(researcher(folder, "R0", None))
        else:
            arms.append(researcher(folder, name, ROOT))
    return arms


def prepare(base=None):
    tag, base = frozen(), Path(base or BASE)
    for name, study in STUDIES.items():
        folder = base / name
        driver.prepare(folder, name, [{"id": i, "question": q} for i, q in study["questions"]],
                       arms_for(folder, study["arms"]))
    first = base / "cs4-first"
    first.mkdir(parents=True, exist_ok=True, mode=0o700)
    loop_ws = driver.workspace(first, "W", releases=ROOT, store=ROOT)
    plan = {"name": "cs4-first", "tag": tag, "promptVersion": ask.prompt_version(), "createdAt": now(),
            "questions": [{"id": i, "question": q} for i, q, _ in UNANSWERABLE], "store": driver.fingerprint(loop_ws),
            "checker": engines.CODEX}
    if not (first / "plan.json").exists():
        atomic_json(first / "plan.json", plan, private=True)
    atomic_json(base / "prepared.json", {"tag": tag, "at": now()}, private=True)


TRANSIENT = ("quota", "rate-limited", "not-signed-in", "interrupted")  # a call failed this way stays to do


def guard(deadline, base, home):
    """driver.Guard for sessions recorded in `base` that also stops at the STOP file of `home`, the replicate's folder,
    so one STOP there stops whichever of its studies is running (as `recursive/restart.py`'s Guard does)."""
    value = driver.Guard(deadline, base=base)
    own = value.boundary
    value.boundary = lambda: "owner-stop" if (Path(home) / "STOP").exists() else own()
    return value


def final(item):
    """A cs4 first asking's record needs nothing more: checked, or its question or check failed for good (for a reason
    that is not transient; a check after its second attempt)."""
    if "check" in item:
        return True
    if "checkError" in item:
        return item["checkError"]["reason"] not in TRANSIENT and item.get("checkAttempts", 1) >= 2
    return item.get("state") == "failed" and (item.get("error") or {}).get("reason") not in TRANSIENT


def first_asks(guard, base=None):
    """cs4's first askings through the normal loop: answered, saved and reviewed (on Codex, as pinned) in the copy W,
    then checked. A first asking left running by a stopped process is recovered; one that failed for a transient reason
    is asked again on a fresh trace run, as `recursive/restart.py`'s `retry` does (the app's retry would reuse the
    failed attempt's finished run); one that failed for another reason is recorded with its reason and is final, and so
    is a check that failed twice for a reason that is not transient. True when every first asking is final."""
    first = Path(base or BASE) / "cs4-first"
    plan, ws = read_json(first / "plan.json"), first / "workspaces" / "W"
    service = ask.Questions(ws, runner=guard, reviews=True, review_engine=engines.CODEX)
    service.recover()
    ids = {q["id"]: hashlib.md5(("oopc-cs4-" + q["id"]).encode()).hexdigest() for q in plan["questions"]}
    for q in plan["questions"]:
        path = ask.folder(ws) / ids[q["id"]] / "question.json"
        state = read_json(path) if path.exists() else None
        if state is None:
            service.submit(dict(question=q["question"], depth="standard", runtime=engines.CODEX, origin="research",
                                taskId=ids[q["id"]], authorizeSubscription=True))
        elif state.get("status") == "failed" and (state.get("error") or {}).get("reason") in TRANSIENT:
            if state.get("runId"):
                state.setdefault("failedRuns", []).append(state.pop("runId"))
                atomic_json(path, state, private=True)
            service.retry(ids[q["id"]])
    service.wait(reviews=True)
    arm = {"name": "W", "root": str(ws), "engine": engines.CODEX}
    for q in plan["questions"]:
        out = first / "items" / (q["id"] + ".json")
        old = read_json(out) if out.exists() else {}
        if final(old):
            continue
        state = read_json(ask.folder(ws) / ids[q["id"]] / "question.json")
        if state.get("status") != "completed":
            atomic_json(out, {"question": q, "state": state.get("status"), "error": state.get("error")}, private=True)
            continue
        result = read_json(ask.folder(ws) / ids[q["id"]] / "result.json")
        answered = {"answer": result["answer"], "runId": state.get("runId"), "metrics": parity._metrics(result),
                    "webActions": parity.web_actions(result)}
        value = {"question": q, "answer": answered, "deposit": knowledge.deposit_summary(ws, ids[q["id"]]), "at": now()}
        try:
            value["check"] = driver.check(plan, arm, q, answered, guard)
        except engines.EngineError as error:
            counted = error.reason not in TRANSIENT
            value.update(checkError=error.summary(), checkAttempts=old.get("checkAttempts", 0) + counted)
        atomic_json(out, value, private=True)
    return all(final(read_json(first / "items" / (q["id"] + ".json"))) for q in plan["questions"])


def settled(base=None):
    """Every item of the replicate in `base` is done or failed for good, so its blind scoring may start: each driver
    item answered and checked, or failed after its retry as the driver reports it, and each first asking final."""
    base = Path(base or BASE)
    for name in list(STUDIES) + ["cs4-repeat"]:
        if not study_settled(base / name):
            return False
    first = base / "cs4-first"
    return all((first / "items" / (q["id"] + ".json")).exists() and final(read_json(first / "items" / (q["id"] + ".json")))
               for q in read_json(first / "plan.json")["questions"])


def study_settled(folder):
    """Every (question, arm) item of a driver folder has an answer that failed, or an answer and a check (done or
    failed); the driver writes a failure there only after its retry."""
    if not (Path(folder) / "plan.json").exists():
        return False
    plan = read_json(Path(folder) / "plan.json")
    items = [driver._item(folder, i, q, a["name"]) for i, q in enumerate(plan["questions"]) for a in plan["arms"]]
    return all(i.get("answer") and ("error" in i["answer"] or i.get("check")) for i in items)


def run(hours=36, base=None):
    """The replicate in `base` to its end, resumably. A STOP file in `base` or in a study's folder stops it."""
    frozen()
    base = Path(base or BASE)
    deadline = time.time() + hours * 3600
    for name in STUDIES:
        state = driver.run(base / name, runner=guard(deadline, base / name, base))
        if state["status"] != "completed":
            return state
    first = base / "cs4-first"
    if not first_asks(guard(deadline, first, base), base):
        return {"status": "stopped", "stopReason": "owner-stop" if (base / "STOP").exists() else
                "cs4 first askings incomplete"}
    repeat = base / "cs4-repeat"
    arms = [researcher(repeat, "R", first / "workspaces" / "W"), {"name": "P", "kind": "plain"}]
    driver.prepare(repeat, "cs4-repeat", [{"id": i, "question": again} for i, _, again in UNANSWERABLE], arms)
    return driver.run(repeat, runner=guard(deadline, repeat, base))


def report(base=None):
    value, base = {}, Path(base or BASE)
    for name in list(STUDIES) + ["cs4-repeat"]:
        if (base / name / "plan.json").exists():
            value[name] = driver.report(base / name)
    items = sorted((base / "cs4-first" / "items").glob("*.json")) if (base / "cs4-first" / "items").exists() else []
    value["cs4-first"] = [{"id": read_json(p)["question"]["id"], "metrics": (read_json(p).get("answer") or {}).get("metrics"),
                           "verdict": (read_json(p).get("check") or {}).get("verdict"),
                           "resultGiven": (read_json(p).get("check") or {}).get("resultGiven"),
                           "deposit": read_json(p).get("deposit")} for p in items]
    atomic_json(base / "report.json", value, private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run", "report"])
    command = parser.parse_args().command
    print(json.dumps({"prepare": prepare, "run": run, "report": report}[command](), indent=1, default=str)[:4000])
