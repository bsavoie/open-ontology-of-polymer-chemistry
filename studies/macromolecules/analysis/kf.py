"""KF, the frozen knowledge base of Part A (study plan, "Plan of record — 2026-10-18"): its pins, the one frozen copy
every records analysis reads, and the pins block every KF output carries (experiment A1).

The live store `ROOT/.oopc/loop/knowledge.sqlite` is KF and must not change, not even its file, so no analysis opens it
through `oopc` (`knowledge.connect` and its callers open a store for writing and may run schema setup). `store()` makes
one copy, through `driver.workspace`'s read-only backup, at `analysis/kf/workspaces/KF`, and refuses to return a copy,
or to make one from a live store, whose `driver.fingerprint` (every field of every finding and note, hashed) is not
KF's. `meta()` names the snapshot, the fingerprint, the graph release, the prompt and code tag, the git revisions of the
analysis code that wrote an output and of the `oopc` code it imported, and the time.

The 2026-10-14/16 cleanup changed KF's findings after the campaign (Crossref titles, excerpts, re-reviews of access
failures, polymer ids and trade names) and recorded what it replaced in each finding's `detail`; `as_written` gives
the excerpt as the researcher saved it, for measures of what a prompt version produced (Fig. 4e).
"""
import datetime as dt, subprocess
from pathlib import Path

import common

SNAPSHOT_ID = "oopc-knowledge-db1fc22ca88a0c0b45b9218b"
FINGERPRINT = {"findings": 8899, "notes": 2195, "sha256": "efdf88117f1073b8"}
RELEASE_ID = "oopc-6ad56d8b354d053bcc3cf3a1"
PROMPT = "0b7bb1483235"
TAG = "study-freeze-2"
COUNTS = {"findings": 8899, "Reviewed": 5489, "Added": 3268, "Needs checking": 124, "Rejected": 18, "notes": 2195,
          "sources": 1679, "polymers": 157, "graphPolymers": 274}  # the snapshot manifest's counts
FOLDER = common.analysis_dir("kf")


def store(folder=FOLDER, live=None):
    """The frozen copy's knowledge.sqlite, made from the live store (`live`, a workspace root: ROOT) the first time.

    Raises SystemExit, writing nothing, if the live store or the copy is not KF, or if the live root's current graph
    release is not KF's."""
    import driver  # here, not at import: the default CODE (tag study-freeze) lacks what driver imports
    from oopc import knowledge
    from oopc.util import read_json
    live = Path(live or common.ROOT)
    copy = Path(folder) / "workspaces" / "KF"
    if not copy.exists():
        if driver.fingerprint(live) != FINGERPRINT:
            raise SystemExit("the live store is no longer KF (%s); nothing copied" % driver.fingerprint(live))
        if read_json(live / "releases/current.json")["release_id"] != RELEASE_ID:
            raise SystemExit("the live graph release is not %s; nothing copied" % RELEASE_ID)
        driver.workspace(folder, "KF", releases=live, store=live)
    found = driver.fingerprint(copy)
    if found != FINGERPRINT:
        raise SystemExit("the frozen copy is not KF (%s); nothing built" % found)
    return knowledge.database(copy)


def _git(folder, *args):
    try:
        return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def revision():
    """The analysis code's commit, with "-dirty" when `analysis/` has changes not committed."""
    head = _git(common.STUDY, "rev-parse", "--short=12", "HEAD")
    dirty = _git(common.STUDY / "analysis", "status", "--porcelain", "--", ".")
    return head and head + ("-dirty" if dirty else "")


def meta(builder):
    """The pins block of a KF output."""
    return {"store": "KF", "knowledgeSnapshot": SNAPSHOT_ID, "storeFingerprint": FINGERPRINT, "graphRelease": RELEASE_ID,
            "prompt": PROMPT, "codeTag": TAG, "oopcRevision": _git(common.CODE, "rev-parse", "--short=12", "HEAD"),
            "analysisRevision": revision(), "builder": builder,
            "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def as_written(excerpt, detail):
    """The excerpt as the researcher saved it: the cleanup kept a replaced or filled excerpt's original in
    `detail.excerptFrom.was` (on 2026-10-18 it equals K3's excerpt for all 3,888 such findings)."""
    return ((detail or {}).get("excerptFrom") or {}).get("was", excerpt)
