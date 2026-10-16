"""Secondary analysis (owner, 2026-10-13): the same 180 answers checked again, all arms alike, by a checker that is
given each researcher session's recorded knowledge searches (commit cd692b8). The primary checks stay as they were;
these go to results/<id>-<arm>-check2.json and are analysed with `python analyze.py --checks check2`.

Ran in `.oopc/loop/harness/2026-10-ablation/` (oopc then imported from the repository at cd692b8) and still reads and writes there; moved to the
repository on 2026-10-13 unchanged except imports and paths."""
import concurrent.futures, json, random, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, Guard, emit, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-ablation")
from ablation import ablation  # noqa: E402
from ablation.ablation import ARMS, SEED, engines, parity, reviewer, workspace  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402


def recheck(guard, question, arm):
    source = ablation.result_path(question, arm, "answer")
    target = ablation.result_path(question, arm, "check2")
    if ablation.done(target) or not ablation.done(source):
        return
    value = read_json(source)
    item = {"id": question["id"], "question": question["question"]}
    try:
        result = parity.check(workspace(arm), item, value["answer"], engine=engines.CODEX, runner=guard,
                              timeout=reviewer.REVIEW_SECONDS, run_id=value.get("runId"))
    except engines.EngineError as error:
        result = {"error": error.summary(), "at": now()}
    atomic_json(target, dict(result, arm=arm, questionId=question["id"]), private=True)


def main():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    atomic_json(BASE / "recheck.json", {"startedAt": now(), "revision": revision}, private=True)
    questions = json.loads((BASE / "heldout.json").read_text())
    random.Random(SEED).shuffle(questions)
    guard = Guard(time.time() + 12 * 3600, base=BASE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ARMS)) as pool:
        for number, question in enumerate(questions, 1):
            if guard.boundary() or not guard.eligible(engines.CODEX):
                break
            emit(BASE, "recheck-start", number=number, id=question["id"][:12])
            list(pool.map(lambda arm: recheck(guard, question, arm), ARMS))
    atomic_json(BASE / "recheck.json", dict(read_json(BASE / "recheck.json"), finishedAt=now(), done=number), private=True)
    emit(BASE, "recheck-finished", done=number)


if __name__ == "__main__":
    main()
