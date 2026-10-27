"""Part A of the Macromolecules study: the controlled runs A2–A5 and E8 on the frozen knowledge base KF
(docs/exec-plans/active/macromolecules-study-plan.md, "Plan of record — 2026-10-18" and "Part A harness and
predictions"). No call is made here outside `run` and the A5 scoring it starts.

Every run goes through the shared driver (`driver.py`): a folder holds questions × arms, each question's arms answer in
turn and are then checked together by one Codex checker, resumably, with named failures and the token ledger. An
experiment is split into replicate and question-shard folders `r<replicate>-s<shard>`; a shard folder holds every arm
for its questions, dealt round robin from the experiment's fixed order, so a question's arms still answer in turn and
are checked together. Every arm answers on its own copy of its store.

- A2 `2026-10-kf-scaling` (Fig. 4a, 4c): test 1's 60 held-out questions in test 1's order; P (plain), K0, KF200, KF1,
  KF2 and KF (researcher, web on), MF1 and MF (web off, on KF1 and KF); three replicates.
- A3 `2026-10-kf-resampled` (Fig. 4c): the same questions on the 20 resampled stores of `stores.resample`, with K0 and
  KF as same-day anchors (22 arms).
- A4 `2026-10-kf-ladder` (Fig. 4b): 30 campaign first asks with findings in KF, each asked exactly, in other words and
  as a sibling (`ladder`); K0 and KF; two replicates.
- A5 (Fig. 5): four more replicates of the case studies, `2026-10-case-studies-r2` … `-r5` (`case_studies.py`), and five
  of E9 at the freeze, `2026-10-planted-kf-r1` … `-r5` (`planted.py`'s replicate functions), each scored blind once
  every one of its items is settled (`case_studies/score.py`; E9 with its own rubric); `2026-10-kf-a5` holds their
  layout, the report and the blind scoring of the 2026-10-13 E9 run (`score-e9-2026-10-13`, read-only on that run).
  A STOP file in a replicate's folder stops whichever of its parts is running.
- E8 `2026-10-kf-e8` (owner, 2026-10-18: runs): whether memory written by Codex serves another engine; test 1's 20 near
  questions in test 1's order; K0c and KFc, the researcher on Claude Code (web on) on copies of K0 and KF, checked by
  the same Codex checker; one replicate.

Every prepare and run refuses unless `oopc` is tag study-freeze-2 (`case_studies.frozen`), `PINS` hold (researcher
prompt, both models: Codex for research and checks, Claude Code for E8 and the blind scoring; graph release; KF), and
both the code under test and the harness's `studies/` are committed (`dirty`). Each prepared folder records the pins,
its stores' fingerprints and the harness's revision from its own repository (`pins.json`); each run appends the
revision it ran from and the Codex floor (`runs.jsonl`). `report` computes every estimator the predictions use
(`estimate.py`).

    python -B part_a.py prepare A2|A3|A4|A5|E8 [--shards N] [--into DIR]
    python -B part_a.py run FOLDER [--hours H]      # one folder per process; several run side by side
    python -B part_a.py status [--into DIR]
    python -B part_a.py report A2|A3|A4|A5|E8 [--into DIR]
    python -B part_a.py questions A2|A4|E8          # the questions in their order (A4: with the parents' findings)
    python -B part_a.py score-e9-2026-10-13 [--into DIR]   # a Claude Code session

`--into DIR` prepares (status and report read) the experiment folders under DIR instead of `.oopc/loop/harness/`:
a dry run on the real inputs. FOLDER is a path or a folder name under `.oopc/loop/harness/`.
"""
import argparse, collections, contextlib, json, random, sqlite3, statistics, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from campaign import make_questions  # noqa: E402
from case_studies import case_studies, score  # noqa: E402
from part_a import estimate, stores  # noqa: E402
from planted import planted  # noqa: E402
from scaling import scaling  # noqa: E402
from oopc import ask, engines, knowledge, reviewer  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, locked, now, read_json  # noqa: E402

PINS = {"tag": case_studies.TAG, "tagCommit": "1c06a7f", "promptVersion": "0b7bb1483235",
        "models": {engines.CODEX: "gpt-6.1-sol", engines.CLAUDE: "claude-opus-5-5"},
        "release": "oopc-6ad56d8b354d053bcc3cf3a1", "knowledgeSnapshot": "oopc-knowledge-db1fc22ca88a0c0b45b9218b",
        "kf": {"findings": 8899, "notes": 2195, "sha256": "efdf88117f1073b8"}}
ROOT = common.ROOT  # KF is its live store, read only through read-only copies
ABLATION = common.run_dir("2026-10-ablation")
HELDOUT = ABLATION / "heldout.json"
K0 = stores.K0  # test 1's frozen K0 store (150 findings), as it is
CAMPAIGN = common.run_dir("2026-10-campaign") / "questions.json"
DEV = common.run_dir("2026-10-recursive") / "dev.json"
HARNESS = Path(__file__).resolve().parent  # its repository's revision is the harness's, wherever ROOT points
STORE_ARMS = ("K0", "KF200", "KF1", "KF2", "KF")  # A2's researcher arms with web on, one per store size
EXPERIMENTS = {  # reference: every arm is paired against it; pairs: further paired comparisons the predictions use
    "A2": {"folder": "2026-10-kf-scaling", "replicates": 3, "reference": "K0",
           "pairs": [("KF", "P"), ("K0", "P"), ("MF", "KF"), ("MF", "MF1")], "split": ("KF2", "K0")},
    "A3": {"folder": "2026-10-kf-resampled", "replicates": 1, "reference": "K0", "pairs": []},
    "A4": {"folder": "2026-10-kf-ladder", "replicates": 2, "reference": "K0", "pairs": []},
    "E8": {"folder": "2026-10-kf-e8", "replicates": 1, "reference": "K0c", "pairs": []}}
CASE_STUDIES = ["2026-10-case-studies-r%d" % r for r in (2, 3, 4, 5)]
PLANTED = ["2026-10-planted-kf-r%d" % r for r in (1, 2, 3, 4, 5)]
A5 = "2026-10-kf-a5"
LADDER = {"seed": "oopc-part-a-ladder-2026-10-18", "parents": 30, "least": 3}
COUNTED = ("contradicted", "accessUncertain")
TRUE = ("complete", "resultGiven", "pass")


def folder(name, into=None):
    return Path(into).resolve() / name if into else common.run_dir(name)


# ----- pins and records -----

def pinned():
    """The pins as found, or SystemExit naming those that do not hold, or the code that is not committed (`dirty`).
    Reads KF only through a read-only fingerprint."""
    tag = case_studies.frozen()
    found = {"tagCommit": tag, "promptVersion": ask.prompt_version(),
             "models": {e: engines.ENGINES[e]["model"] for e in PINS["models"]},
             "release": read_json(ROOT / "releases/current.json")["release_id"], "kf": driver.fingerprint(ROOT)}
    wrong = {k: [PINS[k], v] for k, v in found.items() if not (v.startswith(PINS[k]) if k == "tagCommit" else v == PINS[k])}
    if wrong:
        raise SystemExit("Not the pinned %s: %s" % (", ".join(wrong), json.dumps(wrong)))
    changed = dirty()
    if changed:
        raise SystemExit("Uncommitted changes; commit them first: %s" % json.dumps(changed)[:1000])
    return dict(PINS, **found, code=str(common.CODE))


def _git(where, *args):
    return subprocess.run(["git", *args], cwd=where, text=True, capture_output=True).stdout.strip()


def dirty():
    """What is not committed: freeze-2's `oopc` and `config` (the code under test, `common.CODE`) and `studies/` of the
    harness's own repository (that of this file). Empty when both are clean."""
    found = {}
    code = _git(common.CODE, "status", "--porcelain", "--", "oopc", "config")
    if code:
        found["code"] = code.splitlines()[:20]
    top = _git(HARNESS, "rev-parse", "--show-toplevel")
    harness = _git(top, "status", "--porcelain", "--", "studies") if top else "not a git repository"
    if harness:
        found["harness"] = harness.splitlines()[:20]
    return found


def revision():
    """The harness's git revision, from its own repository (that of this file, not ROOT's: runs are launched from a
    worktree of the harness commit with OOPC_STUDY_ROOT at the main checkout), and whether its `studies/` is clean."""
    top = _git(HARNESS, "rev-parse", "--show-toplevel")
    return {"revision": _git(HARNESS, "rev-parse", "HEAD"), "path": top,
            "clean": bool(top) and not _git(top, "status", "--porcelain", "--", "studies")}


def record(path, kind, pins, **fields):
    """`path/pins.json`, written once: what the folder runs (`kind`), the pins, its stores and the harness revision."""
    target = Path(path) / "pins.json"
    if not target.exists():
        atomic_json(target, dict(pins, kind=kind, harness=revision(), at=now(), **fields), private=True)
    return read_json(target)


def arms(run, specs):
    """Driver arms from (name, source store root or None for plain, web, engine): researcher arms on copies in `run`;
    every arm is checked by the plan's Codex checker, whichever engine answers."""
    return [{"name": name, "kind": "plain", "engine": engine} if source is None else
            {"name": name, "kind": "researcher", "web": web, "engine": engine,
             "root": driver.workspace(run, name, releases=ROOT, store=source)} for name, source, web, engine in specs]


def copies(plan, specs):
    """Refuse unless every researcher arm's store is a copy identical to its source (KF's is the pinned one)."""
    want = {name: driver.fingerprint(source) for name, source, _, _ in specs if source is not None}
    if {name: plan["stores"].get(name) for name in want} != want:
        raise SystemExit("A store copy of %s differs from its source" % plan["name"])


# ----- questions -----

def heldout():
    """Test 1's 60 held-out questions in test 1's fixed order (`scaling.SEED`, as test 1 and E4 answered them)."""
    questions = read_json(HELDOUT)
    random.Random(scaling.SEED).shuffle(questions)
    return questions


def counts(root):
    """Findings per question id in the store of the workspace `root`, rejected ones left out; read-only."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    found = dict(db.execute("SELECT question_id, COUNT(*) FROM findings WHERE status != ? GROUP BY question_id",
                            (knowledge.UNSUPPORTED,)))
    db.close()
    return found


def candidates(campaign, found, avoid, least=LADDER["least"]):
    """The campaign first asks a ladder may start from: about one polymer, with at least `least` findings in the store
    (`found`, findings per question id), never revisited in the campaign (a revisit's findings are in the store too),
    whose polymer–property pair no other campaign first ask asked (a comparison naming the polymer counts), and not one
    of the pairs in `avoid` (the held-out and dev sets')."""
    first = [q for q in campaign if q.get("revisit") is None]
    revisited = {q.get("parent") for q in campaign if q.get("revisit")}
    asked = collections.Counter((m, q["property"]) for q in first for m in q["materials"])
    return sorted((q for q in first if len(q["materials"]) == 1 and q["taskId"] not in revisited
                   and asked[q["materials"][0], q["property"]] == 1 and found.get(q["taskId"], 0) >= least
                   and (q["materials"][0], q["property"]) not in avoid), key=lambda q: q["taskId"])


def ladder(campaign, found, avoid, parents=LADDER["parents"], least=LADDER["least"], seed=LADDER["seed"]):
    """The similarity ladder: `parents` of the `candidates`, drawn with `seed`, each asked exactly, in other words and
    as a sibling, worded as the campaign's revisits were (`make_questions.paraphrase`, `sibling`). A parent whose
    paraphrase or sibling is word for word a campaign question is passed over (for the store it would be an exact
    repeat). Returns 3 × `parents` questions in one seeded order, each with its rung as `stratum`."""
    rng = random.Random(seed)
    pool = candidates(campaign, found, avoid, least)
    rng.shuffle(pool)
    texts = {q["question"] for q in campaign}
    chosen = []
    for q in pool:
        if len(chosen) == parents:
            break
        sibling, kind = make_questions.sibling(q, rng)
        paraphrase = make_questions.paraphrase(q, rng)
        if not {sibling, paraphrase} & texts:
            chosen.append((q, paraphrase, sibling, kind))
    if len(chosen) < parents:
        raise ValueError("Only %d campaign first asks qualify" % len(chosen))
    questions = []
    for q, paraphrase, sibling, kind in chosen:
        for rung, text, asked in (("exact", q["question"], q["kind"]), ("paraphrase", paraphrase, q["kind"]),
                                  ("sibling", sibling, kind)):
            questions.append({"id": "a4-%s-%s" % (q["taskId"][:12], rung), "question": text, "stratum": rung,
                              "kind": asked, "material": q["materials"][0], "property": q["property"],
                              "parent": q["taskId"], "parentNumber": q["number"], "parentWave": q["wave"],
                              "parentKind": q["kind"], "parentFindings": found[q["taskId"]]})
    rng.shuffle(questions)
    return questions


def ladder_questions():
    avoid = {(q["material"], q["property"]) for q in read_json(HELDOUT) + read_json(DEV)}
    return ladder(read_json(CAMPAIGN), counts(ROOT), avoid, **LADDER)


# ----- prepare -----

def specs(experiment, store_folder):
    """Each experiment's arms in their base order, as (name, source, web, engine)."""
    codex, claude = engines.CODEX, engines.CLAUDE
    if experiment == "A2":
        return ([("P", None, True, codex), ("K0", K0, True, codex)] +
                [(n, store_folder / n, True, codex) for n in stores.CUTS] +
                [("KF", ROOT, True, codex), ("MF1", store_folder / "KF1", False, codex), ("MF", ROOT, False, codex)])
    if experiment == "A3":  # K0 and KF as same-day anchors of the scaling rows (decided 2026-10-18, before any run)
        return [("K0", K0, True, codex), ("KF", ROOT, True, codex)] + [
            (stores.name(z, s), store_folder / stores.name(z, s), True, codex) for s in stores.SEEDS for z in stores.SIZES]
    if experiment == "E8":  # memory written by Codex, read by the researcher on Claude Code
        return [("K0c", K0, True, claude), ("KFc", ROOT, True, claude)]
    return [("K0", K0, True, codex), ("KF", ROOT, True, codex)]


def questions_of(experiment):
    """A2 and A3: test 1's held-out questions in its order; E8: their near stratum; A4: the ladder."""
    if experiment == "A4":
        return ladder_questions()
    return [q for q in heldout() if experiment != "E8" or q["stratum"] == "near"]


def prepare(experiment, shards=1, into=None):
    """An experiment's store copies and run folders, each a driver plan fixed once written. Returns its layout."""
    if experiment == "A5":
        return prepare_a5(into)
    pins, spec = pinned(), EXPERIMENTS[experiment]
    base = folder(spec["folder"], into)
    layout = base / "experiment.json"
    if layout.exists() and read_json(layout)["shards"] != shards:
        raise SystemExit("%s was prepared with %d shards; a layout is fixed once written" % (experiment,
                                                                                         read_json(layout)["shards"]))
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    built = (stores.cuts(base / "stores", ROOT, K0, ROOT) if experiment == "A2" else
             stores.resample(base / "stores", ROOT, stores.SIZES, stores.SEEDS, ROOT) if experiment == "A3" else None)
    questions = questions_of(experiment)
    chosen = specs(experiment, base / "stores")
    runs = []
    for r in range(1, spec["replicates"] + 1):
        for s in range(1, shards + 1):
            run = base / ("r%d-s%d" % (r, s))
            plan = driver.prepare(run, "%s-r%d-s%d" % (experiment.lower(), r, s), questions[s - 1::shards],
                                  arms(run, chosen), engine=engines.CODEX, checker=engines.CODEX)
            copies(plan, chosen)
            record(run, "driver", pins, experiment=experiment, replicate=r, shard=s, shards=shards, stores=plan["stores"],
                   engines={a["name"]: a["engine"] for a in plan["arms"]}, checker=plan["checker"])
            runs.append(run.name)
    value = {"experiment": experiment, "replicates": spec["replicates"], "shards": shards, "folders": runs,
             "questions": len(questions), "arms": [a[0] for a in chosen],
             "answers": len(questions) * len(chosen) * spec["replicates"], "pins": pins, "at": now()}
    if experiment == "A2":
        value["cuts"] = {k: built[k] for k in ("stores", "checkAgainstK0", "changes")}
    elif experiment == "A3":
        value["resampled"] = {k: built[k] for k in ("questions", "noQuestion", "sizes", "seeds", "stores")}
    elif experiment == "A4":
        value["parents"] = sorted({(q["parent"], q["material"], q["property"], q["parentKind"], q["parentFindings"])
                                   for q in questions})
    if not layout.exists():
        atomic_json(layout, value, private=True)
    return read_json(layout)


def prepare_a5(into=None):
    """Four case-study replicates and five E9 replicates, each with fresh copies of KF."""
    pins = pinned()
    layout = {"experiment": "A5", "caseStudies": [], "planted": [], "pins": pins, "at": now()}
    for name in CASE_STUDIES:
        base = folder(name, into)
        case_studies.prepare(base)
        found = {s: read_json(base / s / "plan.json")["stores"] for s in case_studies.STUDIES}
        found["cs4-first"] = {"W": read_json(base / "cs4-first/plan.json")["store"]}
        kf = [fp for study in found.values() for arm, fp in study.items() if arm != "R0"]
        if any(fp != PINS["kf"] for fp in kf):
            raise SystemExit("A store copy in %s is not KF" % base)
        record(base, "case-studies", pins, experiment="A5", replicate=int(name.rsplit("r", 1)[1]), stores=found)
        layout["caseStudies"].append(name)
    for name in PLANTED:
        base = folder(name, into)
        plan = planted.prepare_replicate(base, source=ROOT, releases=ROOT)
        master = driver.fingerprint(base / "workspaces/planted")
        if plan["stores"] != {"C": PINS["kf"], "A1": master, "A2": master}:
            raise SystemExit("A store copy in %s is not KF or the planted store" % base)
        record(base, "planted", pins, experiment="A5", replicate=int(name.rsplit("r", 1)[1]), stores=plan["stores"],
               planted=master)
        layout["planted"].append(name)
    path = folder(A5, into) / "experiment.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        atomic_json(path, layout, private=True)
    return read_json(path)


# ----- run and status -----

def resolve(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() or path.exists() else common.run_dir(str(path))


def run(path, hours=36):
    """Run one prepared folder to its end (resumable), after checking the pins; logs the revision it ran from. A
    folder another process is running is refused."""
    path = resolve(path)
    if not (path / "pins.json").exists():
        raise SystemExit("%s is not a prepared Part A folder" % path)
    kind = read_json(path / "pins.json")["kind"]
    pinned()
    hold = contextlib.ExitStack()
    try:
        hold.enter_context(locked(path / "run.lock", blocking=False))
    except BlockingIOError:
        raise SystemExit("Another process is running %s" % path)
    log = path / "runs.jsonl"
    entry = {"startedAt": now(), "harness": revision(), "hours": hours, "codexFloor": common.FLOOR}
    state = {"status": "crashed"}
    with hold:
        return _run(path, kind, hours, log, entry, state)


def scored(state, path, settled, work, names, hours):
    """A replicate's blind scoring, after its answers: only once every item is answered and checked or failed for good
    (`settled`), in sessions whose Guard also stops at the replicate's STOP file. A group still to score stops the
    replicate (a rerun scores it); a group whose scoring failed twice is recorded and the replicate completes."""
    if state["status"] != "completed":
        return state
    if not settled:
        return dict(state, status="stopped", stopReason="items not settled")
    work(case_studies.guard(time.time() + hours * 3600, path, path))
    found = score.pending(path, names)
    state = dict(state, scoringFailed=found["failed"])
    if found["pending"]:
        state.update(status="stopped", stopReason="scoring incomplete", scoringPending=found["pending"])
    return state


def _run(path, kind, hours, log, entry, state):
    try:
        if kind == "driver":
            state = driver.run(path, hours=hours)
        elif kind == "case-studies":
            state = case_studies.run(hours=hours, base=path)
            state = scored(state, path, case_studies.settled(path), lambda guard: score.run(path, runner=guard),
                           list(score.RUBRIC), hours)
        else:
            state = planted.run_replicate(path, hours=hours, releases=ROOT)
            state = scored(state, path, planted.settled(path), lambda guard: planted.score_replicate(path, guard),
                           ["e9"], hours)
    finally:
        entry.update(finishedAt=now(), status=state.get("status"), stopReason=state.get("stopReason"))
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    return state


def score_record(into=None, hours=6):
    """Score the 2026-10-13 E9 run's 25 answers blind with E9's rubric (read-only on that run), as the comparison for
    the replicates at the freeze; results in `2026-10-kf-a5/e9-2026-10-13/scoring`. A Claude Code session."""
    pinned()
    out = folder(A5, into) / "e9-2026-10-13"
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    found = planted.score_record(out, case_studies.guard(time.time() + hours * 3600, out, out))
    return dict(found, report=score.report(out)["byArm"])


def _read(path):
    return read_json(path) if Path(path).exists() else None


def items(run):
    """A driver folder's plan and its items, as (question index, question, arm name, item)."""
    plan = read_json(Path(run) / "plan.json")
    for index, question in enumerate(plan["questions"]):
        for arm in plan["arms"]:
            yield index, question, arm["name"], _read(driver._path(run, index, arm["name"])) or {}


def progress(run):
    run = Path(run)
    if not (run / "plan.json").exists():
        return {"folder": str(run), "state": "not prepared"}
    rows = list(items(run))
    state = _read(run / "state.json") or {}
    return {"folder": str(run), "items": len(rows),
            "done": sum(driver._ok(i.get("answer")) and driver._ok(i.get("check")) for *_, i in rows),
            "failed": sum("error" in (i.get(p) or {}) for *_, i in rows for p in ("answer", "check")),
            "state": state.get("status", "not started"), "stopReason": state.get("stopReason")}


def status(into=None):
    rows = []
    for spec in EXPERIMENTS.values():
        rows += [progress(r) for r in sorted(folder(spec["folder"], into).glob("r*-s*"))]
    for name in CASE_STUDIES:
        base = folder(name, into)
        rows += [progress(base / s) for s in list(case_studies.STUDIES) + ["cs4-repeat"] if base.exists()]
        if (base / "cs4-first").exists():
            done = [_read(p) for p in (base / "cs4-first/items").glob("*.json")]
            rows.append({"folder": str(base / "cs4-first"), "items": len(case_studies.UNANSWERABLE),
                         "done": sum("check" in d for d in done), "final": sum(case_studies.final(d) for d in done)})
        if (base / "scoring").exists():
            rows.append(dict(score.pending(base, list(score.RUBRIC)), folder=str(base / "scoring")))
    for name in PLANTED:
        base = folder(name, into)
        rows += [progress(base / part) for part, _ in planted.REPLICATE if base.exists()]
        if (base / "review.json").exists():
            rows.append({"folder": str(base / "review.json"), "review": _read(base / "review.json")})
        if (base / "scoring").exists():
            rows.append(dict(score.pending(base, ["e9"]), folder=str(base / "scoring")))
    return rows


# ----- report -----

def asked(root):
    """The question ids a store's findings were saved under; read-only."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    found = {r[0] for r in db.execute("SELECT DISTINCT question_id FROM findings")}
    db.close()
    return found


def answers(run, experiment, replicate):
    """One row per question and arm of a driver folder: costs, citations, the check's measures, and whether the
    question's parent (the campaign question it was made from) left findings in the arm's store (`parentInStore`; E4
    found that what saves cost on a near question is its own topic in the store, not the store's size)."""
    rows = []
    plan = read_json(Path(run) / "plan.json")
    stores_asked = {a["name"]: asked(a["root"]) for a in plan["arms"] if a["kind"] == "researcher"}
    web = {a["name"]: a["web"] for a in plan["arms"]}
    for _, question, name, item in items(run):
        answer, check = item.get("answer") or {}, item.get("check") or {}
        got = reviewer.measures(check) if driver._ok(check) else None
        metrics = answer.get("metrics") or {}
        cited = [c for c in (answer.get("answer") or {}).get("citations") or [] if isinstance(c, str)]
        rows.append(dict({k: question.get(k) for k in ("id", "stratum", "kind")}, experiment=experiment,
                         replicate=replicate, folder=Path(run).name, arm=name, web=web[name],
                         storeFindings=(plan["stores"].get(name) or {}).get("findings"),
                         answered=driver._ok(item.get("answer")),
                         checked=bool(got), newTokens=metrics.get("newTokens"), webCalls=metrics.get("webCalls"),
                         seconds=metrics.get("seconds"), findingCitations=sum(c.startswith("finding:") for c in cited),
                         parentInStore=question["parent"] in stores_asked[name] if question.get("parent")
                         and name in stores_asked else None, **{k: (got or {}).get(k) for k in COUNTED + TRUE}))
    return rows


def summary(rows):
    """Per arm: answers, the check's measures (contradicted statements, complete, sourced result first; passes and
    access-uncertain statements second), answers citing saved findings or using no web call, median tokens and web."""
    value = {}
    for arm in dict.fromkeys(r["arm"] for r in rows):
        mine = [r for r in rows if r["arm"] == arm and r["answered"]]
        checked = [r for r in mine if r["checked"]]
        median = lambda key: (statistics.median(v) if (v := [r[key] for r in mine if r[key] is not None]) else None)
        value[arm] = {"answered": len(mine), "checked": len(checked),
                      **{k: sum(r[k] or 0 for r in checked) for k in COUNTED},
                      **{k: sum(r[k] is True for r in checked) for k in TRUE},
                      "citingFindings": sum(r["findingCitations"] > 0 for r in mine),
                      "noWeb": sum(r["webCalls"] == 0 for r in mine),
                      "medianNewTokens": median("newTokens"), "medianWebCalls": median("webCalls")}
    return value


def estimates(experiment, rows):
    """The estimators the predictions use beyond each arm's counts and its pairing with the reference
    (`estimate.py`): A2's further pairs (KF/P, K0/P, MF/KF, MF against MF1) and its KF2 parent split; A3's coverage
    model and its seed spread; and, for A2 and A3, Fig. 4c's within-question scaling slope and pass on store size by
    mixed logistic regression, on the researcher arms with web on."""
    spec, value = EXPERIMENTS[experiment], {}
    if experiment in ("A2", "A3"):
        scaling_rows = [r for r in rows if r["web"] and r["storeFindings"] and
                        (experiment == "A3" or r["arm"] in STORE_ARMS)]
        value["slope"] = estimate.slope(scaling_rows)
        value["passes"] = estimate.passes(scaling_rows)
    if experiment == "A2":
        near = [r for r in rows if r["stratum"] == "near"]
        value["split"] = dict(estimate.split(near, *spec["split"]), arms=list(spec["split"]))
        value["byReplicate"] = {  # KF/K0 per replicate and stratum: the range A3's anchors are read against
            stratum: {rep: estimate.paired([r for r in rows if r["replicate"] == rep and r["stratum"] == stratum],
                                           "KF", "K0")["tokens"]
                      for rep in sorted({r["replicate"] for r in rows})}
            for stratum in dict.fromkeys(r["stratum"] for r in rows)}
    if experiment == "A3":
        resampled = [r for r in rows if r["arm"] not in ("K0", "KF")]
        value["coverage"] = estimate.coverage(resampled)
        spread = collections.defaultdict(lambda: collections.defaultdict(list))  # stratum/size -> seed's store -> tokens
        for r in resampled:
            if r["answered"] and r["newTokens"]:
                spread["%s/%s" % (r["stratum"], r["arm"].split("-")[0])][r["arm"]].append(r["newTokens"])
        value["seedSpread"] = {key: sorted(statistics.median(v) for v in by_seed.values())
                               for key, by_seed in sorted(spread.items())}
    return value


def report(experiment, into=None):
    """Combine an experiment's replicate and shard folders: `rows.json` (one row per answer, for the figure scripts)
    and `report.json` (per stratum and overall: each arm's counts, every arm paired against the reference and the
    further pairs, then `estimates`)."""
    if experiment == "A5":
        return report_a5(into)
    spec = EXPERIMENTS[experiment]
    base = folder(spec["folder"], into)
    layout = read_json(base / "experiment.json")
    rows, states = [], {}
    for name in layout["folders"]:
        driver.report(base / name)
        rows += answers(base / name, experiment, int(name[1:].split("-")[0]))
        states[name] = progress(base / name)
    strata = list(dict.fromkeys(r["stratum"] for r in rows)) + ["all"]
    value = {"experiment": experiment, "reference": spec["reference"], "folders": states, "at": now(), "byStratum": {}}
    for stratum in strata:
        mine = [r for r in rows if stratum == "all" or r["stratum"] == stratum]
        arms_ = list(dict.fromkeys(r["arm"] for r in mine))
        value["byStratum"][stratum] = {
            "arms": summary(mine),
            "paired": {arm: estimate.paired(mine, arm, spec["reference"]) for arm in arms_ if arm != spec["reference"]},
            "pairs": {"%s/%s" % pair: estimate.paired(mine, *pair) for pair in spec["pairs"]}}
    value["estimates"] = estimates(experiment, rows)
    if experiment == "A3":
        sizes = layout["resampled"]["stores"]
        value["storeFindings"] = {name: fp["findings"] for name, fp in sizes.items()}
    atomic_json(base / "rows.json", rows, private=True)
    atomic_json(base / "report.json", value, private=True)
    atomic_bytes(base / "report.md", _markdown(value).encode("utf-8"), private=True)
    return value


def _markdown(value):
    lines = ["# %s" % value["experiment"], ""]
    for stratum, part in value["byStratum"].items():
        lines += ["## %s" % stratum, "", "| Arm | Answered | Contradicted | Complete | Sourced result | Passes | "
                  "Access-uncertain | Citing findings | No web | Median new tokens | Median web calls | Tokens vs %s |"
                  % (value["reference"] or "–"), "| --- |" + " ---: |" * 11]
        for arm, s in part["arms"].items():
            ratio = ((part.get("paired") or {}).get(arm) or {}).get("tokens")
            cells = [s["answered"], s["contradicted"], s["complete"], s["resultGiven"], s["pass"], s["accessUncertain"],
                     s["citingFindings"], s["noWeb"], s["medianNewTokens"], s["medianWebCalls"],
                     "%.2f (%.2f–%.2f)" % (ratio["median"], ratio["low"], ratio["high"]) if ratio else None]
            lines.append("| %s | %s |" % (arm, " | ".join("–" if c is None else str(c) for c in cells)))
        lines.append("")
    return "\n".join(lines)


def report_a5(into=None):
    """The case studies' five replicates (the 2026-10-16 run and r2–r5) and E9's five, each folder's own report,
    then summed per study (or plant) and arm."""
    value = {"at": now(), "caseStudies": {}, "planted": {}}
    for base in [case_studies.BASE] + [folder(n, into) for n in CASE_STUDIES]:
        if not base.exists():
            continue
        if base != case_studies.BASE:  # the 2026-10-16 run's reports are read as they are
            case_studies.report(base)
            if (base / "scoring").exists():
                score.report(base)
        web = collections.Counter()
        for study in list(case_studies.STUDIES) + ["cs4-repeat"]:
            if (base / study / "plan.json").exists():
                for _, _, name, i in items(base / study):
                    web["%s/%s" % (study, name)] += ((i.get("answer") or {}).get("metrics") or {}).get("webCalls") or 0
        value["caseStudies"][base.name] = {"report": _read(base / "report.json"), "webCalls": dict(web),
                                           "scoring": (_read(base / "scoring/report.json") or {}).get("byArm")}
    totals = collections.defaultdict(collections.Counter)
    for rep in value["caseStudies"].values():
        for study, got in (rep["report"] or {}).items():
            for arm, a in ((got.get("arms") or {}) if isinstance(got, dict) else {}).items():
                totals["%s/%s" % (study, arm)].update({k: a[k] for k in driver.COLUMNS[:-1]} | {"replicates": 1})
        for key, found in (rep["scoring"] or {}).items():
            totals["blind " + key].update(found)
    value["caseStudiesTotal"] = {k: dict(v) for k, v in sorted(totals.items())}
    plants = collections.defaultdict(collections.Counter)
    for name in PLANTED:
        base = folder(name, into)
        if not (base / "before/plan.json").exists():
            continue
        got = planted.report_replicate(base)
        value["planted"][name] = {"reviewerVerdicts": got["reviewerVerdicts"], "answers": got["answers"]}
        for row in got["answers"]:
            plants["%s/%s" % (row["case"], row["arm"])].update(
                {"answers": 1, "blindScored": row["blind"] is not None, **{k: bool(v) for k, v in (row["blind"] or {}).items()},
                 "citesPlanted": row["citesPlanted"], "contradicted": row["contradicted"],
                 "pass": row["verdict"] == "pass", "patternPlanted": row["plantedValue"], "patternTrue": row["trueValue"]})
        for case, verdict in (got["reviewerVerdicts"] or {}).items():
            plants["%s/review" % case].update({"skipped" if (verdict or {}).get("skipped") else
                                               (verdict or {}).get("status") or "missing": 1})
    value["plantedTotal"] = {k: dict(v) for k, v in sorted(plants.items())}
    record = folder(A5, into) / "e9-2026-10-13"  # the 2026-10-13 run scored blind with the same rubric
    if (record / "scoring/e9-key.json").exists():
        value["planted2026-10-13Blind"] = score.report(record)["byArm"]
    path = folder(A5, into) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(path, value, private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["prepare", "run", "status", "report", "questions", "score-e9-2026-10-13"])
    parser.add_argument("target", nargs="?", help="A2, A3, A4, A5 or E8; for run, the folder")
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--into", type=Path)
    parser.add_argument("--hours", type=float, default=36)
    args = parser.parse_args()
    if args.command == "prepare":
        out = prepare(args.target, args.shards, args.into)
        out.pop("pins", None)
    elif args.command == "run":
        out = run(args.target, args.hours)
    elif args.command == "status":
        out = status(args.into)
    elif args.command == "report":
        out = report(args.target, args.into)
    elif args.command == "score-e9-2026-10-13":
        out = score_record(args.into)
    else:
        out = questions_of(args.target)
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
