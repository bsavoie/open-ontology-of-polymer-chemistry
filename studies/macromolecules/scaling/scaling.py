"""Scaling with knowledge size and the memory-only arm (owner-approved 2026-10-13; Macromolecules study E4, E5).

Test 1's 60 held-out questions, answered read-only against snapshots of the grown store cut at the end of each stage:

- K200: the store when the 200-task observation ended (532 findings);
- K1, K2: the store when campaign waves 1 and 2 ended (2,170 and 5,021 findings);
- M1, M3: the researcher with web search disabled, on the K1 store and on K3 (8,905 findings): what memory alone carries.

Test 1's own K0 and K3 answers are checked again here (R0, R3), so every store size is judged by the same checker on
the same day. Code, prompt and model are the study freeze (tag `study-freeze`, run from its worktree), whose checker
is given the researcher's recorded knowledge searches. Nothing is saved to any store.

    python scaling.py prepare      # once: the frozen snapshot workspaces
    python scaling.py run          # resumable; a STOP file or the Codex floor stops it

Ran in `.oopc/loop/harness/2026-10-scaling/` and still reads and writes there; moved to the repository on 2026-10-13
unchanged except imports and paths (the freeze worktree is now common.CODE).
"""
import argparse, concurrent.futures, hashlib, json, os, random, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, ROOT, Guard, emit, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-scaling")
ABLATION = run_dir("2026-10-ablation")
from oopc import ask, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

sys.path[:] = [str(CODE)] + [p for p in sys.path if p != str(CODE)]
assert Path(engines.__file__).resolve().is_relative_to(CODE), "oopc must come from the study freeze"

SOURCE = ABLATION / "workspaces/K3"  # Test 1's frozen copy of the store adopted 2026-10-12.
CUTS = {  # Stage ends; every record made after its cut is left out.
    "K200": "2026-10-05T00:00:00",                  # 200-task observation (findings 2026-10-04), none until wave 1
    "K1": "2026-10-11T07:10:18.018363+00:00",      # campaign wave 1 finishedAt
    "K2": "2026-10-11T17:40:28.353310+00:00",      # campaign wave 2 finishedAt
    "check-K0": "2026-10-02T23:59:59",             # must reproduce test 1's K0 store: the cut method's own check
}
ANSWER_ARMS = ("K200", "K1", "K2", "M1", "M3")     # new answers
RECHECK_ARMS = ("K0", "K3")                         # test 1's answers, checked again
NO_WEB = {"M1", "M3"}
SEED = "oopc-ablation-2026-10-12"  # Test 1's question order.
WORKERS = 4
PREREGISTRATION = ROOT / "docs/exec-plans/active/self-improvement-test-plan.md"


def workspace(arm):
    return BASE / "workspaces" / arm


def _release_link(ws):
    (ws / ".oopc/loop").mkdir(parents=True, mode=0o700)
    (ws / "releases").mkdir()
    release = Path(os.path.realpath(ROOT / "releases" / json.loads((ROOT / "releases/current.json").read_text())["release_id"]))
    (ws / "releases" / release.name).symlink_to(release, target_is_directory=True)
    shutil.copy2(ROOT / "releases/current.json", ws / "releases/current.json")


def _copy_store(source_root, ws):
    src = sqlite3.connect(knowledge.database(source_root).as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(knowledge.database(ws))
    src.backup(dst)
    src.close()
    dst.close()
    knowledge.database(ws).chmod(0o600)


def cut(ws, at):
    """The store as it stood at `at`: later records dropped; a finding reviewed after `at` back to its state before
    review (waiting if flagged, else Added). Polymer ids stay as today's rules give them, as test 1 gave K0."""
    db = sqlite3.connect(knowledge.database(ws))
    db.row_factory = sqlite3.Row
    with db:
        db.execute("DELETE FROM findings WHERE created_at > ?", (at,))
        db.execute("DELETE FROM notes WHERE created_at > ?", (at,))
        db.execute("DELETE FROM deposits WHERE deposited_at > ?", (at,))
        db.execute("DELETE FROM reviews WHERE started_at > ?", (at,))
        db.execute("DELETE FROM source_access WHERE observed_at > ?", (at,))
        db.execute("DELETE FROM audit_state WHERE updated_at > ?", (at,))
        reopened = 0
        for row in db.execute("SELECT id, detail FROM findings WHERE COALESCE(reviewed_at,'') > ?", (at,)).fetchall():
            detail = json.loads(row["detail"]) if row["detail"] else {}
            status = knowledge.UNREVIEWED if detail.get("needsReview") else knowledge.ACCEPTED
            if "spotCheck" in detail:
                detail["spotCheck"] = "pending"
            detail.pop("recheckReason", None)
            db.execute("UPDATE findings SET status=?, review_reason='', reviewer_engine='', reviewed_at='', detail=? "
                       "WHERE id=?", (status, json.dumps(detail, ensure_ascii=False), row["id"]))
            reopened += 1
        db.execute("DELETE FROM findings_fts WHERE id NOT IN (SELECT id FROM findings)")
        db.execute("DELETE FROM notes_fts WHERE id NOT IN (SELECT id FROM notes)")
    db.execute("VACUUM")
    db.close()
    return reopened


def store_fingerprint(ws):
    db = sqlite3.connect(knowledge.database(ws).as_uri() + "?mode=ro", uri=True)
    rows = db.execute("SELECT id, status FROM findings ORDER BY id").fetchall()
    notes = db.execute("SELECT id FROM notes ORDER BY id").fetchall()
    db.close()
    digest = hashlib.sha256(json.dumps([rows, notes]).encode()).hexdigest()[:16]
    return {"findings": len(rows), "notes": len(notes), "sha256": digest}


def prepare():
    if (BASE / "workspaces").exists():
        raise SystemExit("The workspaces exist; they are frozen and never rebuilt.")
    built, reopened = {}, {}
    for name, at in CUTS.items():
        ws = BASE / "workspaces" / name
        _release_link(ws)
        _copy_store(SOURCE, ws)
        reopened[name] = cut(ws, at)
        built[name] = ws
    # The cut method reproduces test 1's K0 store (same findings, same statuses) or nothing runs.
    k0 = sqlite3.connect(knowledge.database(ABLATION / "workspaces/K0").as_uri() + "?mode=ro", uri=True)
    expected = k0.execute("SELECT id, status FROM findings ORDER BY id").fetchall()
    k0.close()
    got = sqlite3.connect(knowledge.database(built["check-K0"]).as_uri() + "?mode=ro", uri=True)
    reproduced = got.execute("SELECT id, status FROM findings ORDER BY id").fetchall()
    got.close()
    if reproduced != expected:
        raise SystemExit("Cutting K3 at 2026-10-02 does not reproduce K0 (%d vs %d findings)" % (len(reproduced), len(expected)))
    shutil.rmtree(built.pop("check-K0"))
    for arm, store in (("M1", "K1"), ("M3", None)):
        ws = workspace(arm)
        _release_link(ws)
        _copy_store(built[store] if store else SOURCE, ws)
    # Rechecks read test 1's stores and traces; their calls are recorded here, not in test 1's folders.
    for arm in RECHECK_ARMS:
        ws = workspace(arm)
        _release_link(ws)
        _copy_store(ABLATION / "workspaces" / arm, ws)
        (ws / ".oopc/runs").symlink_to(ABLATION / "workspaces" / arm / ".oopc/runs", target_is_directory=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "oopc"], cwd=CODE, text=True).strip()
    atomic_json(BASE / "baseline.json", dict(
        at=now(), revision=revision, coreClean=not dirty, promptVersion=ask.prompt_version(),
        model=engines.ENGINES[engines.CODEX]["model"], cuts=CUTS, reopenedAtCut=reopened,
        cutReproducesK0=True, preregistrationSha256=hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest(),
        stores={arm: store_fingerprint(workspace(arm)) for arm in ANSWER_ARMS + RECHECK_ARMS}), private=True)
    print(json.dumps(read_json(BASE / "baseline.json"), indent=1))


def result_path(question, arm, part):
    return BASE / "results" / ("%s-%s-%s.json" % (question["id"][:12], arm, part))


def done(path):
    return path.exists() and "error" not in read_json(path)


def answer(guard, question, arm):
    if arm in RECHECK_ARMS:
        return read_json(ABLATION / "results" / ("%s-%s-answer.json" % (question["id"][:12], arm)))
    path = result_path(question, arm, "answer")
    if done(path):
        return read_json(path)
    item = {"id": question["id"], "question": question["question"]}
    runner = guard
    if arm in NO_WEB:
        def runner(engine, prompt, schema, **options):
            return guard(engine, prompt, schema, **dict(options, web=False))
    try:
        value = parity.answer_ontology(workspace(arm), item, engines.CODEX, runner=runner,
                                       timeout=ask.DEPTHS[question["depth"]]["seconds"], depth=question["depth"])
    except engines.EngineError as error:
        value = {"error": error.summary(), "at": now()}
    atomic_json(path, dict(value, arm=arm, questionId=question["id"], web=arm not in NO_WEB), private=True)
    return value


def check(guard, question, arm, value):
    path = result_path(question, arm, "check")
    if done(path) or "error" in value:
        return
    item = {"id": question["id"], "question": question["question"]}
    try:
        result = parity.check(workspace(arm), item, value["answer"], engine=engines.CODEX, runner=guard,
                              timeout=reviewer.REVIEW_SECONDS, run_id=value.get("runId"))
    except engines.EngineError as error:
        result = {"error": error.summary(), "at": now()}
    atomic_json(path, dict(result, arm=arm, questionId=question["id"]), private=True)


def run():
    baseline = read_json(BASE / "baseline.json")
    if ask.prompt_version() != baseline["promptVersion"] or engines.ENGINES[engines.CODEX]["model"] != baseline["model"]:
        raise SystemExit("The prompt or model changed since prepare; the arms would not be comparable.")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip() != baseline["revision"]:
        raise SystemExit("The freeze worktree moved since prepare.")
    (BASE / "results").mkdir(exist_ok=True, mode=0o700)
    questions = json.loads((ABLATION / "heldout.json").read_text())
    random.Random(SEED).shuffle(questions)
    guard = Guard(time.time() + 36 * 3600, base=BASE)  # its streams and activity log live with this run
    state = {"startedAt": now(), "status": "running"}
    atomic_json(BASE / "state.json", state, private=True)
    arms = ANSWER_ARMS + RECHECK_ARMS
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for number, question in enumerate(questions, 1):
            stop = guard.boundary()
            if not stop and not guard.eligible(engines.CODEX):
                stop = "codex-not-eligible"  # Never switch engines inside the experiment.
            if stop:
                state.update(status="stopped", stopReason=stop)
                break
            emit(BASE, "question-start", number=number, stratum=question["stratum"], id=question["id"][:12])
            answers = dict(zip(arms, pool.map(lambda arm: answer(guard, question, arm), arms)))
            list(pool.map(lambda arm: check(guard, question, arm, answers[arm]), arms))
            state.update(done=number, updatedAt=now())
            atomic_json(BASE / "state.json", state, private=True)
        else:
            state.update(status="completed")
    state["finishedAt"] = now()
    atomic_json(BASE / "state.json", state, private=True)
    emit(BASE, "scaling-" + state["status"], **{k: v for k, v in state.items() if k in ("done", "stopReason")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    args = parser.parse_args()
    prepare() if args.command == "prepare" else run()
