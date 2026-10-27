"""Part C's driver plans: the pilot, the screen and the case studies (docs/exec-plans/active/ontology-refinement-plan.md,
"The screen" and "Case studies"). No engine is called outside `pilot`, `run-screen` and `run-cases`.

Every arm is the researcher on Codex (`gpt-6.1-sol`) with the code's own prompt (no `prompt` override), web on, depth
standard, answering on its own copy of its store (`driver.workspace`), checked by the Codex checker; a question's arms
answer in turn and are checked together (`driver.run`). The arms (`pins.ARMS`; the driver's names allow no "+", so O+
is `Oplus`):

| Arm | Store (its root as `overlay/fingerprint.json` records it) | Graph release root (`pins.folder("overlay")/…`) |
| --- | --- | --- |
| B0 | K0 | seed-root (the seed) |
| O0 | K0-refined | release-root (release O) |
| B | KF | seed-root |
| Oplus (O+) | KF-refined | release-root |

The stores are where overlay.py's build made them (`stores/workspaces/<name>`), read from the `roots` that its
`overlay/fingerprint.json` records with each store's fingerprint and table hash (`stores`) and the two releases
(`releases`); `built` refuses a fingerprint.json that lacks any of them.

- **Pilot** (`pins.BASE/pilot`): the first question of each set in the screen's order, on the screen's arms, for a check
  by hand. `run-screen` refuses until a person has checked it and created `pilot/CHECKED`.
- **Screen** (`pins.folder("screen")`): H, N and L (fixed by `questions/hashes.json`) in one order (SCREEN_SEED), arms
  B0, B, Oplus, in shard folders `s<k>` (questions k, k + shards, …; the shard count is fixed once prepared), so several
  can run side by side.
- **Cases** (`pins.folder("cases")/r1` … `r5`): the questions of `cases/selection.json` (per case C1–C8 a list of
  {question id, set, reason}, each a question of H, N or L) and of `questions/C.json` (written for the cases short of
  three, each with its case; fixed by its hash and committed, and refused for a selection other than the one it was
  written for); a question picked for several cases, as C7 takes C1–C3's, is answered once and carries every case it
  serves (a written C1–C3 question also serves C7 when C7 took none from its case). Arms B0, O0, B, Oplus, five
  replicates with fresh copies, as Part A's A5.

**Commitments** (plan: the overlays and stores are "fingerprinted and committed" before any withheld task is answered).
`commit` gives the `overlay` entry of the tracked `refinement/commitments.json` (the SHA-256 of `overlay/edits.json`,
`excluded.json` (null when there is none), `graph-overlay.json` and `store-overlay.json`; the seed release and release O;
each store's fingerprint with its table hash, `overlay.describe`) and the `pool` entry (the SHA-256 of
`mine/pool.json`, the derivation pool), from the private files, refused unless those agree with
`overlay/fingerprint.json`; it prints them, or with `--write` writes them into the tracked file for a person to commit
(`questions.commit`; a committed entry is never replaced).

Refusals (`pinned`, `check_arms`), before preparing and before running: the code under test is tag study-freeze-3
(`pins.frozen`); the researcher prompt and both models are the pins; the code under test and the harness's `studies/`
are committed (`part_a.dirty`); every entry of commitments.json (questions, overlay, pool, and the case questions once
C.json exists) is there and agrees with the private files; every arm's store (its source and its copy) has the
fingerprint and the table hash (`overlay.table_hash`) `overlay/fingerprint.json` records for its store, KF's is KF's
pin and K0's is test 1's K0 (`pins.K0`); the three tables (`pins.TABLES`) are absent from K0 and KF and present in
K0-refined and KF-refined; the seed arms answer on the pinned seed release and the refined arms on release O, each the
release fingerprint.json records; and the refined ontology changes something (release O differs from the seed, or
KF-refined differs from KF in its findings or holds rows in the three tables: approved edits may all be store edits).
Each prepared folder records the pins and its stores (`pins.json`); each run appends the revision it ran from
(`runs.jsonl`) and holds a lock, so one folder runs in one process. A STOP file in a folder stops its run at a
boundary; a rerun resumes it.

    python -B studies/macromolecules/refinement/run.py commit [--write]
    python -B studies/macromolecules/refinement/run.py pilot [--hours H]
    python -B studies/macromolecules/refinement/run.py prepare-screen [--shards N]
    python -B studies/macromolecules/refinement/run.py run-screen [--shard K] [--hours H]
    python -B studies/macromolecules/refinement/run.py prepare-cases
    python -B studies/macromolecules/refinement/run.py run-cases --replicate R [--hours H]
    python -B studies/macromolecules/refinement/run.py status
"""
import argparse, contextlib, json, random, re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import overlay, pins, questions  # noqa: E402
from part_a import part_a  # noqa: E402
from oopc import ask, engines, knowledge  # noqa: E402
from oopc.util import atomic_json, locked, now, read_json, resolve_release  # noqa: E402

SCREEN_SEED = "oopc-refinement-2026-10-21-screen"
REPLICATES = 5
REFINED = {store for store, root in pins.ARMS.values() if root == "release-root"}  # the stores with the three tables
ENGINE_OF = {"codex": engines.CODEX, "claude": engines.CLAUDE}  # pins.PINS["models"] keys -> engine ids
STORES = tuple(dict.fromkeys(store for store, _ in pins.ARMS.values()))
FINGERPRINT = ("findings", "notes", "sha256")  # driver.fingerprint's fields; overlay.describe adds `tables`
OVERLAY_FILES = ("edits.json", "excluded.json", "graph-overlay.json", "store-overlay.json")


# ----- stores, releases and the checks -----

def built():
    """`overlay/fingerprint.json` as overlay.py's build writes it, refused unless it records every store's fingerprint
    with its table hash (`stores`, `overlay.describe`), its root (`roots`) and both releases (`releases`)."""
    target = pins.folder("overlay") / "fingerprint.json"
    if not target.exists():
        raise SystemExit("No recorded stores (%s); overlay.py build writes them" % target)
    value = read_json(target)
    stores, roots = value.get("stores") or {}, value.get("roots") or {}
    missing = [name for name in STORES if not isinstance(stores.get(name), dict) or "tables" not in stores[name]
               or set(FINGERPRINT) - set(stores[name]) or not roots.get(name)]
    if missing or set((value.get("releases") or {})) != {"seed", "refined"}:
        raise SystemExit("overlay/fingerprint.json does not record the fingerprint, table hash and root of %s and both "
                         "releases" % (", ".join(missing) or "every store"))
    return value


def store_root(arm):
    """The arm's store, where the build made it."""
    return Path(built()["roots"][pins.ARMS[arm][0]])


def release_root(arm):
    return pins.folder("overlay") / pins.ARMS[arm][1]


def recorded():
    """The stores as `overlay/fingerprint.json` records them, by name: `driver.fingerprint`'s fields and `tables`."""
    return {name: dict(built()["stores"][name]) for name in STORES}


def tables(root):
    """Which of the three tables the store of the workspace `root` has; read-only."""
    from oopc import knowledge
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.close()
    return {t for t in pins.TABLE_NAMES if t in names}


def overlay_rows(root):
    """Rows in the three tables of the store of the workspace `root` (0 when it has none or does not exist); read-only."""
    from oopc import knowledge
    if not knowledge.database(root).exists():
        return 0
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    count = sum(db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in pins.TABLE_NAMES if t in names)
    db.close()
    return count


def release_id(root):
    return resolve_release(root).name


def check_arms(roots, graph=True):
    """Refuse (SystemExit naming every problem) unless each arm's store `roots[arm]` (a workspace root: a copy, or the
    source itself) has its store's recorded fingerprint and table hash, carries the three tables exactly when its store
    is refined, and (`graph`; not for the source stores) links the graph release of its kind: the pinned seed for seed
    arms, release O for refined ones, each the release fingerprint.json records. The refined ontology must change
    something: release O, KF-refined's findings or its tables."""
    value, problems = built(), []
    fingerprints = recorded()
    seed = release_id(pins.folder("overlay") / "seed-root")
    refined = release_id(pins.folder("overlay") / "release-root")
    if seed != pins.PINS["release"]:
        problems.append("the seed root's release is %s, not the pinned %s" % (seed, pins.PINS["release"]))
    if {"seed": seed, "refined": refined} != value["releases"]:
        problems.append("the release roots hold %s and %s, not the recorded %s and %s" % (
            seed, refined, value["releases"]["seed"], value["releases"]["refined"]))
    base = lambda name: {k: fingerprints[name][k] for k in FINGERPRINT}  # noqa: E731
    if refined == seed and base("KF-refined") == base("KF") and not overlay_rows(value["roots"]["KF-refined"]):
        problems.append("the refined ontology changes nothing: release O is the seed release and KF-refined is KF")
    if base("KF") != pins.PINS["kf"]:
        problems.append("the recorded KF is not KF's pin")
    if base("K0") != driver.fingerprint(pins.K0):
        problems.append("the recorded K0 is not test 1's K0 (%s)" % pins.K0)
    for arm, root in roots.items():
        store, kind = pins.ARMS[arm]
        if not knowledge.database(root).exists():
            problems.append("arm %s: no store at %s" % (arm, root))
            continue
        found = overlay.describe(root)
        if {k: found[k] for k in FINGERPRINT} != base(store):
            problems.append("arm %s: the store at %s is not the recorded %s" % (arm, root, store))
        if found["tables"] != fingerprints[store]["tables"]:
            problems.append("arm %s: the tables of the store at %s are not the recorded %s's (%s, not %s)" % (
                arm, root, store, found["tables"], fingerprints[store]["tables"]))
        present = tables(root) if (Path(root) / ".oopc/loop/knowledge.sqlite").exists() else set()
        if store in REFINED and present != set(pins.TABLE_NAMES):
            problems.append("arm %s: store %s lacks %s" % (arm, store, sorted(set(pins.TABLE_NAMES) - present)))
        if store not in REFINED and present:
            problems.append("arm %s: store %s has %s" % (arm, store, sorted(present)))
        if not graph:
            continue
        try:
            found = release_id(root)
        except (ValueError, OSError, KeyError):
            found = None
        want = refined if kind == "release-root" else seed
        if found != want:
            problems.append("arm %s: graph release %s, not %s" % (arm, found, want))
    if problems:
        raise SystemExit("Refused: " + "; ".join(problems))


def pinned():
    """The pins as found, or SystemExit: the code under test is study-freeze-3, the prompt and models are the pins, the
    code under test and the harness are committed, and so is every input the commitments name (`committed`)."""
    tag = pins.frozen()
    found = {"promptVersion": ask.prompt_version(),
             "models": {k: engines.ENGINES[ENGINE_OF[k]]["model"] for k in pins.PINS["models"]}}
    wrong = {k: [pins.PINS[k], v] for k, v in found.items() if pins.PINS[k] != v}
    if wrong:
        raise SystemExit("Not the pinned %s: %s" % (", ".join(wrong), json.dumps(wrong)))
    changed = part_a.dirty()
    if changed:
        raise SystemExit("Uncommitted changes; commit them first: %s" % json.dumps(changed)[:1000])
    return dict(pins.PINS, tagCommit=tag, code=str(common.CODE), commitments=committed())


# ----- commitments -----

def overlay_entry():
    """commitments.json's `overlay` entry from the private files as they are now: the overlay files' SHA-256 (null for
    one that does not exist, as excluded.json may not), both releases, and each store's fingerprint with its table hash
    (`overlay.describe`), each store read at its recorded root."""
    value, folder = built(), pins.folder("overlay")
    absent = [name for name in STORES if not knowledge.database(value["roots"][name]).exists()]
    if absent:
        raise SystemExit("No store at the recorded root of %s" % ", ".join(absent))
    return {"files": {name: questions.file_digest(folder / name) for name in OVERLAY_FILES},
            "releases": {"seed": release_id(folder / "seed-root"), "refined": release_id(folder / "release-root")},
            "stores": {name: overlay.describe(value["roots"][name]) for name in STORES}}


def pool_entry():
    """commitments.json's `pool` entry: the SHA-256 of the derivation pool, `mine/pool.json`."""
    target = pins.FOLDERS["mine"] / "pool.json"
    if not target.exists():
        raise SystemExit("%s is missing: mine.py writes the derivation pool" % target)
    return {"mine/pool.json": questions.file_digest(target)}


def commit(write=False):
    """The `overlay` and `pool` entries for commitments.json, printed or (`write`) written in place (`questions.commit`),
    refused unless the releases and stores are still what the build recorded in `overlay/fingerprint.json`."""
    entry, value = overlay_entry(), built()
    if entry["releases"] != value["releases"] or entry["stores"] != {name: value["stores"][name] for name in STORES}:
        raise SystemExit("The releases or stores are not what overlay/fingerprint.json records; nothing is committed")
    return questions.commit({"overlay": entry, "pool": pool_entry()}, write)


def committed():
    """Every entry of commitments.json against the private files, or SystemExit naming each that is missing or
    differs: the question sets, the overlay and stores, the derivation pool, and the case questions once C.json exists
    (or once they are committed). Returns the entries."""
    found = {"questions": questions.question_entry(), "overlay": overlay_entry(), "pool": pool_entry()}
    case = questions.case_entry()
    if case is not None or questions.commitments().get("caseQuestions"):
        found["caseQuestions"] = case
    problems = [p for p in (questions.differs(k, v) for k, v in found.items()) if p]
    if problems:
        raise SystemExit("Refused: " + "; ".join(problems) + " (questions.py commit and run.py commit, --write, then "
                         "commit commitments.json)")
    return found


def arms(folder, names):
    """Driver arms in their base order, each on its own copy of its store in `folder`, after the sources are checked."""
    check_arms({name: store_root(name) for name in names}, graph=False)
    value = [{"name": name, "kind": "researcher", "web": True, "depth": "standard", "engine": engines.CODEX,
              "root": driver.workspace(folder, name, releases=release_root(name), store=store_root(name))}
             for name in names]
    check_arms({a["name"]: a["root"] for a in value})
    return value


def plan_arms(folder):
    """A prepared folder's arms as {name: root}, from its plan."""
    return {a["name"]: a["root"] for a in read_json(Path(folder) / "plan.json")["arms"]}


def record(folder, kind, pins_found, **fields):
    """`folder/pins.json`, written once: what the folder runs, the pins, its stores and the harness revision."""
    target = Path(folder) / "pins.json"
    if not target.exists():
        atomic_json(target, dict(pins_found, kind=kind, harness=part_a.revision(), at=now(), **fields), private=True)
    return read_json(target)


def prepare_folder(folder, name, chosen, names, pins_found, kind, **fields):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    plan = driver.prepare(folder, name, chosen, arms(folder, names), engine=engines.CODEX, checker=engines.CODEX)
    stores = {store: {k: value[k] for k in FINGERPRINT} for store, value in recorded().items()}  # the plan's form
    if any(plan["stores"][arm] != stores[pins.ARMS[arm][0]] for arm in names):
        raise SystemExit("A store copy of %s differs from its source" % name)
    record(folder, kind, pins_found, stores=plan["stores"], arms={a: list(pins.ARMS[a]) for a in names}, **fields)
    return plan


# ----- questions -----

def screen_order():
    """H (Part A's order), N and L (file order), shuffled into one order with SCREEN_SEED; refused unless each set is
    the one fixed by `questions/hashes.json`."""
    order = [q for name in pins.SETS for q in questions.load(name)]
    if len({q["id"] for q in order}) != len(order):
        raise SystemExit("Question ids repeat across the sets")
    random.Random(SCREEN_SEED).shuffle(order)
    return order


def pilot_questions():
    order = screen_order()
    return [next(q for q in order if q["set"] == name) for name in pins.SETS]


def selection():
    """The case studies' questions: each picked question once, with every case it serves and why, in one seeded
    order. A selection entry names a question of H, N or L by its id (`id`, `questionId`, or `question` when that is an
    id); the questions written for the purpose come from `questions/C.json` (checked against its hash), each serving its
    own case, and a written C1-C3 question also serves C7 when C7 took no question from that case (`reuses`)."""
    value = read_json(pins.folder("cases") / "selection.json")
    cases = {k: v for k, v in value.get("cases", value).items() if re.fullmatch(r"C\d+", k) and isinstance(v, list)}
    if not cases:
        raise SystemExit("cases/selection.json names no case C1-C8")
    known = {q["id"]: q for name in pins.SETS for q in questions.load(name)}
    short = sorted(c for c, n in (value.get("shortfalls") or {}).items() if n and c != "C7")
    if short and not questions.path("C.json").exists():
        raise SystemExit("Cases %s are short of three questions: write them first (questions.py write-C)"
                         % ", ".join(short))
    written = questions.load("C") if questions.path("C.json").exists() else []
    if written and read_json(questions.path("case-hashes.json")).get("selection") != questions.file_digest(
            pins.folder("cases") / "selection.json"):
        raise SystemExit("questions/C.json was written for another cases/selection.json")
    chosen = {}

    def pick(case, question, reason):
        item = chosen.setdefault(question["id"], dict(question, cases=[], caseReasons={}))
        if case not in item["cases"]:
            item["cases"].append(case)
        item["caseReasons"][case] = reason

    for case in sorted(cases):
        for entry in cases[case]:
            identifier = entry.get("id") or entry.get("questionId") or (
                entry.get("question") if entry.get("question") in known else None)
            if identifier not in known:
                raise SystemExit("Case %s: %r is not a question of H, N or L; a question written for the purpose comes "
                                 "from questions/C.json (questions.py write-C)" % (case, entry))
            pick(case, known[identifier], entry.get("reason"))
    reused = {entry.get("reuses") for entry in cases.get("C7", [])}
    for question in written:
        pick(question["case"], question, {"rule": question["rule"], "written": True})
        if question["case"] in ("C1", "C2", "C3") and question["case"] not in reused:
            reused.add(question["case"])
            pick("C7", question, {"rule": "C1-C3's questions, compared on K0 (O0 against B0)", "from": question["case"],
                                  "written": True})
    order = sorted(chosen.values(), key=lambda q: q["id"])
    random.Random(pins.CASES_SEED).shuffle(order)
    return order


# ----- prepare and run -----

def prepare_pilot():
    pins_found = pinned()
    folder = pins.BASE / "pilot"
    return prepare_folder(folder, "refinement-pilot", pilot_questions(), pins.SCREEN_ARMS, pins_found, "pilot")


def prepare_screen(shards=1):
    """The screen's shard folders, each a driver plan fixed once written. Returns the layout."""
    pins_found = pinned()
    base = pins.folder("screen")
    layout = base / "experiment.json"
    if layout.exists() and read_json(layout)["shards"] != shards:
        raise SystemExit("The screen was prepared with %d shards; a layout is fixed once written"
                         % read_json(layout)["shards"])
    order = screen_order()
    folders = []
    for s in range(1, shards + 1):
        folder = base / ("s%d" % s)
        prepare_folder(folder, "refinement-screen-s%d" % s, order[s - 1::shards], pins.SCREEN_ARMS, pins_found,
                       "screen", shard=s, shards=shards)
        folders.append(folder.name)
    if not layout.exists():
        atomic_json(layout, {"shards": shards, "folders": folders, "arms": list(pins.SCREEN_ARMS),
                             "labels": pins.LABELS, "questions": len(order), "order": [q["id"] for q in order],
                             "hashes": read_json(questions.path("hashes.json"))["sets"], "at": now()},
                    private=True)
    return read_json(layout)


def prepare_cases():
    """Five replicate folders of the case studies, each a driver plan with fresh store copies."""
    pins_found = pinned()
    chosen = selection()
    base = pins.folder("cases")
    for r in range(1, REPLICATES + 1):
        prepare_folder(base / ("r%d" % r), "refinement-cases-r%d" % r, chosen, pins.CASE_ARMS, pins_found, "cases",
                       replicate=r)
    layout = {"replicates": REPLICATES, "folders": ["r%d" % r for r in range(1, REPLICATES + 1)],
              "arms": list(pins.CASE_ARMS), "labels": pins.LABELS, "questions": len(chosen), "byCase": {}}
    for q in chosen:
        for case in q["cases"]:
            layout["byCase"].setdefault(case, []).append(q["id"])
    if not (base / "experiment.json").exists():
        atomic_json(base / "experiment.json", dict(layout, at=now()), private=True)
    return read_json(base / "experiment.json")


def run_folder(folder, hours=36, runner=None):
    """Run one prepared folder to its end (resumable) after the checks; logs the revision it ran from. A folder another
    process is running is refused."""
    folder = Path(folder)
    if not (folder / "pins.json").exists():
        raise SystemExit("%s is not a prepared Part C folder" % folder)
    pinned()
    check_arms({name: store_root(name) for name in plan_arms(folder)}, graph=False)
    check_arms(plan_arms(folder))
    hold = contextlib.ExitStack()
    try:
        hold.enter_context(locked(folder / "run.lock", blocking=False))
    except BlockingIOError:
        raise SystemExit("Another process is running %s" % folder)
    entry = {"startedAt": now(), "harness": part_a.revision(), "hours": hours, "codexFloor": common.FLOOR}
    state = {"status": "crashed"}
    with hold:
        try:
            state = driver.run(folder, runner=runner, hours=hours)
        finally:
            entry.update(finishedAt=now(), status=state.get("status"), stopReason=state.get("stopReason"))
            with open(folder / "runs.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    return state


def pilot(hours=6, runner=None):
    prepare_pilot()
    return run_folder(pins.BASE / "pilot", hours, runner)


def run_screen(shard=1, hours=36, runner=None):
    if not (pins.BASE / "pilot/CHECKED").exists():
        raise SystemExit("The pilot has not been checked by hand: check %s and create pilot/CHECKED"
                         % (pins.BASE / "pilot"))
    return run_folder(pins.folder("screen") / ("s%d" % shard), hours, runner)


def run_cases(replicate, hours=36, runner=None):
    return run_folder(pins.folder("cases") / ("r%d" % replicate), hours, runner)


def status():
    rows = [part_a.progress(pins.BASE / "pilot")]
    for base in (pins.folder("screen"), pins.folder("cases")):
        rows += [part_a.progress(f) for f in sorted(base.iterdir()) if f.is_dir() and (f / "plan.json").exists()]
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["commit", "pilot", "prepare-screen", "run-screen", "prepare-cases",
                                            "run-cases", "status"])
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--replicate", type=int, choices=range(1, REPLICATES + 1))
    parser.add_argument("--hours", type=float, help="the run's deadline (default 6 for the pilot, else 36)")
    parser.add_argument("--write", action="store_true", help="commit: write the entries into commitments.json")
    args = parser.parse_args()
    if args.command == "run-cases" and not args.replicate:
        parser.error("run-cases needs --replicate")
    args.hours = args.hours or (6 if args.command == "pilot" else 36)
    out = (commit(args.write) if args.command == "commit" else pilot(args.hours) if args.command == "pilot"
           else prepare_screen(args.shards)
           if args.command == "prepare-screen" else run_screen(args.shard, args.hours) if args.command == "run-screen"
           else prepare_cases() if args.command == "prepare-cases" else run_cases(args.replicate, args.hours)
           if args.command == "run-cases" else status())
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
