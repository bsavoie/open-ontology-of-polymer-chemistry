"""Part A's store copies (macromolecules-study-plan.md, "Plan of record — 2026-10-18"), made from KF without a research
call. Every store is a workspace root built once: a read-only copy of its source changed in a scratch folder and only
then renamed into place, so a store that exists is complete, and it is never rebuilt.

- Cuts (A2): KF as it stood at the end of the 200-task run and of campaign waves 1 and 2 (KF200, KF1, KF2), with
  scaling's rule (`scaling.cut`): records made after the cut dropped, a finding reviewed after it returned to its state
  before review, polymer ids as KF gives them. KF also keeps what that rule needs and K3 did not have: merges (6, made
  2026-10-14) are undone, and a finding the store cleanup of 2026-10-14/16 reviewed again returns to its latest review
  made by the cut, which the cleanup kept in `previousReviews`. Excerpts, titles and polymer ids stay as the cleanup
  left them. The same cut at 2026-10-02 is compared with test 1's K0 (ids, statuses, polymer ids) and reported, not
  gated on.
- Resampled stores (A3): nested random subsets of KF's questions (100, 200, 400 and 800 of the 953 questions that left a
  finding or a note) under five seeded orderings; for one ordering the 100 are the first 100 of the 200, and so on.
  A store keeps its questions' findings and notes and what hangs on them: deposits, reviews, audit state and source
  access by question, merges by the finding merged into, full-text rows by finding or note. Records without a question
  (the 2026-09-27 import of the old store, filed under "legacy": 13 findings, 54 notes) are in every store, as they are
  in every cut, and do not count as a question. A question's deposit without findings or notes (121 in KF) is never
  drawn and is dropped. Statuses stay as KF has them.

    python -B stores.py cuts OUT                     # KF200, KF1, KF2 and the 2026-10-02 check against K0, into OUT
    python -B stores.py resample OUT [--sizes ...] [--seeds ...]

Both read KF only through read-only copies and write only under OUT.
"""
import argparse, collections, contextlib, json, random, shutil, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common, driver and scaling
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from scaling import scaling  # noqa: E402
from oopc import knowledge  # noqa: E402
from oopc.util import atomic_json, now  # noqa: E402

CUTS = {"KF200": scaling.CUTS["K200"], "KF1": scaling.CUTS["K1"], "KF2": scaling.CUTS["K2"]}
CHECK = scaling.CUTS["check-K0"]  # 2026-10-02: KF cut here is compared with test 1's K0
K0 = common.run_dir("2026-10-ablation") / "workspaces/K0"
SIZES = (100, 200, 400, 800)
SEEDS = (1, 2, 3, 4, 5)
SEED = "oopc-part-a-resample-2026-10-18-%d"
NO_QUESTION = ("legacy",)  # records without a question: the 2026-09-27 import of the old store
BY_QUESTION = ("findings", "notes", "deposits", "reviews", "audit_state", "source_access")


def built(folder, name, source, change=None, releases=None):
    """The store `folder/name`, built once: a copy of the store of the workspace root `source` (with a link to the graph
    release under `releases`, default common.ROOT) changed by `change(workspace)`, then renamed into place."""
    final = Path(folder) / name
    if final.exists():
        return final
    scratch = Path(folder) / ".build"
    shutil.rmtree(scratch / "workspaces" / name, ignore_errors=True)
    ws = driver.workspace(scratch, name, releases=releases or common.ROOT, store=source)
    if change:
        change(ws)
    ws.rename(final)
    for empty in (scratch / "workspaces", scratch):
        with contextlib.suppress(OSError):
            empty.rmdir()
    return final


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def cut(ws, at):
    """KF in the workspace `ws` as it stood at `at` (see the module's notes): merges after `at` undone, then
    `scaling.cut`, then each finding re-reviewed after `at` given back its latest review made by `at`. Returns counts."""
    db = sqlite3.connect(knowledge.database(ws))
    db.row_factory = sqlite3.Row
    restored, earlier = 0, {}
    with db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(findings)")]
        merges = db.execute("SELECT id, row FROM merged WHERE merged_at > ?", (at,)).fetchall() if "merged" in _tables(db) else []
        for merge in merges:
            old = json.loads(merge["row"])
            if (old.get("created_at") or "") <= at and not db.execute("SELECT 1 FROM findings WHERE id=?", (old["id"],)).fetchone():
                db.execute("INSERT INTO findings (%s) VALUES (%s)" % (",".join(columns), ",".join("?" * len(columns))),
                           [old.get(c) for c in columns])
                text = knowledge._finding_text(dict(old, sourceTitle=old.get("source_title")))
                db.execute("INSERT INTO findings_fts VALUES (?,?)", (old["id"], text))
                restored += 1
            db.execute("DELETE FROM merged WHERE id=?", (merge["id"],))
        for row in db.execute("SELECT id, detail FROM findings WHERE COALESCE(reviewed_at,'') > ?", (at,)):
            before = [r for r in (json.loads(row["detail"] or "{}").get("previousReviews") or [])
                      if r.get("verdict") in knowledge.VERDICTS and "" < (r.get("reviewedAt") or "") <= at]
            if before:
                earlier[row["id"]] = before
    db.close()
    reopened = scaling.cut(ws, at)
    db = sqlite3.connect(knowledge.database(ws))
    with db:
        for identifier, before in earlier.items():
            last = max(before, key=lambda r: r["reviewedAt"])
            detail = json.loads(db.execute("SELECT detail FROM findings WHERE id=?", (identifier,)).fetchone()[0] or "{}")
            detail["previousReviews"] = [r for r in before if r is not last]
            if not detail["previousReviews"]:
                detail.pop("previousReviews")
            if "spotCheck" in detail:
                detail["spotCheck"] = last["verdict"]
            db.execute("UPDATE findings SET status=?, review_reason=?, reviewer_engine=?, reviewed_at=?, detail=? WHERE id=?",
                       (last["verdict"], last.get("reason") or "", last.get("engine") or "", last["reviewedAt"],
                        json.dumps(detail, ensure_ascii=False), identifier))
    db.close()
    return {"mergesUndone": restored, "reopened": reopened - len(earlier), "earlierReviewKept": len(earlier)}


def _rows(root):
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    findings = {r[0]: r[1:] for r in db.execute("SELECT id, status, COALESCE(subject,'') FROM findings")}
    notes = {r[0] for r in db.execute("SELECT id FROM notes")}
    db.close()
    return findings, notes


def compare(store, reference):
    """How close the store at `store` is to the one at `reference`: findings and notes by id, statuses and polymer ids
    of the findings both have, and which status pairs differ (reference → store)."""
    (a, notes_a), (b, notes_b) = _rows(store), _rows(reference)
    both = sorted(set(a) & set(b))
    return {"findings": [len(a), len(b)], "onlyStore": sorted(set(a) - set(b)), "onlyReference": sorted(set(b) - set(a)),
            "sameStatus": sum(a[i][0] == b[i][0] for i in both), "sameSubject": sum(a[i][1] == b[i][1] for i in both),
            "statusChanges": dict(collections.Counter("%s -> %s" % (b[i][0], a[i][0]) for i in both if a[i][0] != b[i][0])),
            "notes": [len(notes_a), len(notes_b)], "sameNotes": notes_a == notes_b,
            "statuses": statuses(store), "referenceStatuses": statuses(reference)}


def cuts(folder, source, reference=K0, releases=None):
    """KF200, KF1 and KF2 in `folder`, and the same cut at 2026-10-02 compared with `reference` (test 1's K0), recorded
    in `folder/cuts.json` with each store's counts and fingerprint. The check store is removed once compared."""
    folder = Path(folder)
    record = folder / "cuts.json"
    if record.exists():
        return json.loads(record.read_text())
    counts = {}
    for store, at in dict(CUTS, **{"check-K0": CHECK}).items():
        built(folder, store, source, lambda ws, store=store, at=at: counts.__setitem__(store, cut(ws, at)), releases)
    value = {"at": now(), "cuts": CUTS, "check": CHECK, "changes": counts,
             "stores": {store: dict(driver.fingerprint(folder / store), statuses=statuses(folder / store)) for store in CUTS},
             "checkAgainstK0": compare(folder / "check-K0", reference) if knowledge.database(reference).exists() else None}
    shutil.rmtree(folder / "check-K0")
    atomic_json(record, value, private=True)
    return value


def statuses(root):
    return dict(collections.Counter(status for status, _ in _rows(root)[0].values()))


def questions(source):
    """KF's questions: each id that a finding or note was saved under, except records without a question."""
    db = sqlite3.connect(knowledge.database(source).as_uri() + "?mode=ro", uri=True)
    found = {r[0] for r in db.execute("SELECT question_id FROM findings UNION SELECT question_id FROM notes")}
    db.close()
    return sorted(found - set(NO_QUESTION))


def ordering(qs, seed):
    """One seeded random ordering of the questions; a store of N questions keeps the first N."""
    order = sorted(qs)
    random.Random(SEED % seed).shuffle(order)
    return order


def subset(ws, keep):
    """Keep in the store at `ws` only the records of the questions `keep` and the records without a question."""
    db = sqlite3.connect(knowledge.database(ws))
    with db:
        db.execute("CREATE TEMP TABLE keep (q TEXT PRIMARY KEY)")
        db.executemany("INSERT OR IGNORE INTO keep VALUES (?)", [(q,) for q in list(keep) + list(NO_QUESTION)])
        tables = _tables(db)
        for table in BY_QUESTION:
            if table in tables:
                db.execute("DELETE FROM %s WHERE question_id NOT IN (SELECT q FROM keep)" % table)
        if "merged" in tables:
            db.execute("DELETE FROM merged WHERE into_id NOT IN (SELECT id FROM findings)")
        db.execute("DELETE FROM findings_fts WHERE id NOT IN (SELECT id FROM findings)")
        db.execute("DELETE FROM notes_fts WHERE id NOT IN (SELECT id FROM notes)")
    db.execute("VACUUM")
    db.close()


def name(size, seed):
    return "R%d-s%d" % (size, seed)


def resample(folder, source, sizes=SIZES, seeds=SEEDS, releases=None):
    """The resampled stores `R<size>-s<seed>` in `folder`, with each ordering and store recorded in
    `folder/resample.json`. A seed gives the same store every time."""
    folder, qs = Path(folder), questions(source)
    if max(sizes) > len(qs):
        raise ValueError("The store has %d questions, fewer than %d" % (len(qs), max(sizes)))
    orders = {seed: ordering(qs, seed) for seed in seeds}
    for seed in seeds:
        for size in sizes:
            built(folder, name(size, seed), source, lambda ws, keep=orders[seed][:size]: subset(ws, keep), releases)
    value = {"at": now(), "questions": len(qs), "noQuestion": list(NO_QUESTION), "sizes": list(sizes), "seeds": list(seeds),
             "orderings": {str(s): orders[s] for s in seeds},
             "stores": {name(z, s): driver.fingerprint(folder / name(z, s)) for s in seeds for z in sizes}}
    atomic_json(folder / "resample.json", value, private=True)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["cuts", "resample"])
    parser.add_argument("out", type=Path)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    parser.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(common.ROOT.resolve() / ".oopc/loop"):
        raise SystemExit("Write dry runs outside the live store's folder.")
    if args.command == "cuts":
        value = cuts(args.out, common.ROOT)
    else:
        value = resample(args.out, common.ROOT, args.sizes, args.seeds)
        value.pop("orderings")
    print(json.dumps(value, indent=1)[:6000])
