"""Memory ablation (owner-approved 2026-10-12): the held-out questions answered three ways at the same moment, read-only.

- P:  a plain web session (no knowledge, no instructions beyond parity's direct prompt);
- K0: the researcher with the store as it was before the 1,000-question base (2026-10-01, 150 findings);
- K3: the researcher with the store after it (a frozen copy of 2026-10-12, 8,905 findings).

Same engine and model (Codex), same researcher prompt, same depth. The three arms of a question run concurrently and
are checked concurrently right after, so web and source-access drift hit them alike. Nothing is saved to any store.

    python ablation.py prepare      # once: the three frozen workspaces
    python ablation.py run          # resumable; STOP file or the Codex floor stops it

Ran in `.oopc/loop/harness/2026-10-ablation/` (oopc then imported from the repository at 735beef) and still reads and writes there; moved to the
repository on 2026-10-13 unchanged except imports and paths.
"""
import argparse, concurrent.futures, json, os, random, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, ROOT, Guard, emit, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-ablation")
from oopc import ask, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

ARMS = ("P", "K0", "K3")
K0_STORE = ROOT / ".oopc/loop/backups/2026-10-12-before-campaign-adoption/knowledge.sqlite"
SEED = "oopc-ablation-2026-10-12"


def workspace(arm):
    return BASE / "workspaces" / arm


def prepare():
    if (BASE / "workspaces").exists():
        raise SystemExit("The workspaces exist; they are frozen and never rebuilt.")
    for arm in ARMS:
        ws = workspace(arm)
        (ws / ".oopc/loop").mkdir(parents=True, mode=0o700)
        (ws / "releases").mkdir()
        release = Path(os.path.realpath(ROOT / "releases" / json.loads((ROOT / "releases/current.json").read_text())["release_id"]))
        (ws / "releases" / release.name).symlink_to(release, target_is_directory=True)
        shutil.copy2(ROOT / "releases/current.json", ws / "releases/current.json")
    for arm, source in (("K0", K0_STORE), ("K3", knowledge.database(ROOT))):
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(knowledge.database(workspace(arm)))
        src.backup(dst)
        src.close()
        dst.close()
        knowledge.database(workspace(arm)).chmod(0o600)
    # K0 gets the polymer ids today's rules would give it, so the arms differ only in what they know.
    filled = 0
    with knowledge.connect(workspace("K0")) as db:
        for row in db.execute("SELECT id, question_id, material, statement FROM findings WHERE COALESCE(subject,'')=''").fetchall():
            path = ROOT / ".oopc/loop/questions" / row["question_id"] / "question.json"
            question = read_json(path)["question"] if path.exists() else ""
            subject = (knowledge.infer_subject(ROOT, {"material": row["material"], "statement": row["statement"]})
                       or knowledge.question_subject(ROOT, question))
            if subject:
                db.execute("UPDATE findings SET subject=? WHERE id=?", (subject, row["id"]))
                filled += 1
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "oopc"], cwd=CODE, text=True).strip()
    atomic_json(BASE / "baseline.json", dict(
        at=now(), revision=revision, coreClean=not dirty, promptVersion=ask.prompt_version(),
        model=engines.ENGINES[engines.CODEX]["model"], k0SubjectsFilled=filled,
        knowledge={arm: knowledge.summary(workspace(arm)) for arm in ("K0", "K3")}), private=True)
    print(json.dumps(read_json(BASE / "baseline.json"), indent=1)[:1500])


def result_path(question, arm, part):
    return BASE / "results" / ("%s-%s-%s.json" % (question["id"][:12], arm, part))


def done(path):
    return path.exists() and "error" not in read_json(path)


def answer(guard, question, arm):
    path = result_path(question, arm, "answer")
    if done(path):
        return read_json(path)
    item = {"id": question["id"], "question": question["question"]}
    timeout = ask.DEPTHS[question["depth"]]["seconds"]
    try:
        if arm == "P":
            value = parity.answer_direct(workspace(arm), item, engines.CODEX, runner=guard, timeout=timeout)
        else:
            value = parity.answer_ontology(workspace(arm), item, engines.CODEX, runner=guard, timeout=timeout,
                                           depth=question["depth"])
    except engines.EngineError as error:
        value = {"error": error.summary(), "at": now()}
    atomic_json(path, dict(value, arm=arm, questionId=question["id"]), private=True)
    return value


def check(guard, question, arm, value):
    path = result_path(question, arm, "check")
    if done(path) or "error" in value:
        return
    item = {"id": question["id"], "question": question["question"]}
    try:
        result = parity.check(workspace(arm), item, value["answer"], engine=engines.CODEX, runner=guard,
                              timeout=reviewer.REVIEW_SECONDS)
    except engines.EngineError as error:
        result = {"error": error.summary(), "at": now()}
    atomic_json(path, dict(result, arm=arm, questionId=question["id"]), private=True)


def run():
    baseline = read_json(BASE / "baseline.json")
    if ask.prompt_version() != baseline["promptVersion"] or engines.ENGINES[engines.CODEX]["model"] != baseline["model"]:
        raise SystemExit("The prompt or model changed since prepare; the arms would not be comparable.")
    (BASE / "results").mkdir(exist_ok=True, mode=0o700)
    questions = json.loads((BASE / "heldout.json").read_text())
    random.Random(SEED).shuffle(questions)
    guard = Guard(time.time() + 36 * 3600, base=BASE)  # its streams and activity log live with this test
    state = {"startedAt": now(), "status": "running"}
    atomic_json(BASE / "state.json", state, private=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ARMS)) as pool:
        for number, question in enumerate(questions, 1):
            stop = guard.boundary()
            if not stop and not guard.eligible(engines.CODEX):
                stop = "codex-not-eligible"  # Never switch engines inside the experiment.
            if stop:
                state.update(status="stopped", stopReason=stop)
                break
            emit(BASE, "question-start", number=number, stratum=question["stratum"], id=question["id"][:12])
            answers = dict(zip(ARMS, pool.map(lambda arm: answer(guard, question, arm), ARMS)))
            list(pool.map(lambda arm: check(guard, question, arm, answers[arm]), ARMS))
            state.update(done=number, updatedAt=now())
            atomic_json(BASE / "state.json", state, private=True)
        else:
            state.update(status="completed")
    state["finishedAt"] = now()
    atomic_json(BASE / "state.json", state, private=True)
    emit(BASE, "ablation-" + state["status"], **{k: v for k, v in state.items() if k in ("done", "stopReason")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    args = parser.parse_args()
    prepare() if args.command == "prepare" else run()
