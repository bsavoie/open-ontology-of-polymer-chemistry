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


def prepare():
    tag = frozen()
    for name, study in STUDIES.items():
        folder = BASE / name
        driver.prepare(folder, name, [{"id": i, "question": q} for i, q in study["questions"]],
                       arms_for(folder, study["arms"]))
    first = BASE / "cs4-first"
    first.mkdir(parents=True, exist_ok=True, mode=0o700)
    loop_ws = driver.workspace(first, "W", releases=ROOT, store=ROOT)
    plan = {"name": "cs4-first", "tag": tag, "promptVersion": ask.prompt_version(), "createdAt": now(),
            "questions": [{"id": i, "question": q} for i, q, _ in UNANSWERABLE], "store": driver.fingerprint(loop_ws),
            "checker": engines.CODEX}
    if not (first / "plan.json").exists():
        atomic_json(first / "plan.json", plan, private=True)
    atomic_json(BASE / "prepared.json", {"tag": tag, "at": now()}, private=True)


def first_asks(guard):
    """cs4's first askings through the normal loop: answered, saved and reviewed in the copy W, then checked."""
    first = BASE / "cs4-first"
    plan, ws = read_json(first / "plan.json"), first / "workspaces" / "W"
    service = ask.Questions(ws, runner=guard, reviews=True)
    ids = {q["id"]: hashlib.md5(("oopc-cs4-" + q["id"]).encode()).hexdigest() for q in plan["questions"]}
    for q in plan["questions"]:
        path = ask.folder(ws) / ids[q["id"]] / "question.json"
        if not path.exists() or read_json(path).get("status") not in ("completed", "failed"):
            service.submit(dict(question=q["question"], depth="standard", runtime=engines.CODEX, origin="research",
                                taskId=ids[q["id"]], authorizeSubscription=True))
    service.wait(reviews=True)
    arm = {"name": "W", "root": str(ws), "engine": engines.CODEX}
    for q in plan["questions"]:
        out = first / "items" / (q["id"] + ".json")
        if out.exists() and "check" in read_json(out):
            continue
        state = read_json(ask.folder(ws) / ids[q["id"]] / "question.json")
        if state.get("status") != "completed":
            atomic_json(out, {"question": q, "state": state.get("status"), "error": state.get("error")}, private=True)
            continue
        result = read_json(ask.folder(ws) / ids[q["id"]] / "result.json")
        answered = {"answer": result["answer"], "runId": state.get("runId"), "metrics": parity._metrics(result),
                    "webActions": parity.web_actions(result)}
        checked = driver.check(plan, arm, q, answered, guard)
        atomic_json(out, {"question": q, "answer": answered, "check": checked, "deposit": knowledge.deposit_summary(
            ws, ids[q["id"]]), "at": now()}, private=True)
    return all("check" in read_json(first / "items" / (q["id"] + ".json")) for q in plan["questions"])


def run(hours=36):
    frozen()
    for name in STUDIES:
        state = driver.run(BASE / name, hours=hours)
        if state["status"] != "completed":
            return state
    first = BASE / "cs4-first"
    guard = driver.Guard(time.time() + hours * 3600, base=first)
    if not first_asks(guard):
        return {"status": "stopped", "stopReason": "cs4 first askings incomplete"}
    repeat = BASE / "cs4-repeat"
    arms = [researcher(repeat, "R", first / "workspaces" / "W"), {"name": "P", "kind": "plain"}]
    driver.prepare(repeat, "cs4-repeat", [{"id": i, "question": again} for i, _, again in UNANSWERABLE], arms)
    return driver.run(repeat, hours=hours)


def report():
    value = {}
    for name in list(STUDIES) + ["cs4-repeat"]:
        if (BASE / name / "plan.json").exists():
            value[name] = driver.report(BASE / name)
    items = sorted((BASE / "cs4-first" / "items").glob("*.json")) if (BASE / "cs4-first" / "items").exists() else []
    value["cs4-first"] = [{"id": read_json(p)["question"]["id"], "metrics": (read_json(p).get("answer") or {}).get("metrics"),
                           "verdict": (read_json(p).get("check") or {}).get("verdict"),
                           "resultGiven": (read_json(p).get("check") or {}).get("resultGiven"),
                           "deposit": read_json(p).get("deposit")} for p in items]
    atomic_json(BASE / "report.json", value, private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run", "report"])
    command = parser.parse_args().command
    print(json.dumps({"prepare": prepare, "run": run, "report": report}[command](), indent=1, default=str)[:4000])
