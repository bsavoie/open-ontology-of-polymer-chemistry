"""Part C's pins, folders and shared formats (docs/exec-plans/active/ontology-refinement-plan.md; owner-approved
2026-10-21, Stage 1 only): a curator reads the researcher's traces on KF, proposes ontology edits from a closed list,
an independent reviewer approves them, and the refined ontology is tested on withheld tasks and case studies.

Every Part C script imports `common` first (it puts the code under test first on sys.path), then this module. What
more than one script reads is named here once: the inputs, the question sets, the edit list and its groups, the arms,
the seeds of the case studies and the sessions' time limits.

- Code under test: tag `study-freeze-3`, which is `study-freeze-2` plus two search changes only (source links;
  property terms), imported from the worktree `.oopc/study/freeze-3` (`OOPC_STUDY_CODE`). `frozen()` refuses anything
  else. With none of the TABLES in a store, freeze-3's search returns exactly what freeze-2's does.
- The base is KF, read only through `analysis/kf.py`'s frozen copy; K0 is test 1's 2026-10-01 store, as in A2-A4.
- The run folder is BASE, `ROOT/.oopc/loop/harness/2026-10-refinement/` (private), with one subfolder per step.
"""
import subprocess
from pathlib import Path

import common

TAG, BASE_TAG = "study-freeze-3", "study-freeze-2"
PINS = {"tag": TAG, "baseTag": BASE_TAG, "baseTagCommit": "1c06a7f", "promptVersion": "0b7bb1483235",
        "models": {"codex": "gpt-6.1-sol", "claude": "claude-opus-5-5"},
        "release": "oopc-6ad56d8b354d053bcc3cf3a1", "knowledgeSnapshot": "oopc-knowledge-db1fc22ca88a0c0b45b9218b",
        "kf": {"findings": 8899, "notes": 2195, "sha256": "efdf88117f1073b8"}}

BASE = common.run_dir("2026-10-refinement")
FOLDERS = {name: BASE / name for name in
           ("questions", "mine", "propose", "overlay", "stores", "lookup", "screen", "cases", "analysis")}
KF = common.analysis_dir("kf") / "workspaces/KF"  # made and checked by analysis/kf.py's store()
K0 = common.run_dir("2026-10-ablation") / "workspaces/K0"  # test 1's K0: 150 findings on 33 polymers
HELDOUT = common.run_dir("2026-10-ablation") / "heldout.json"  # H: test 1's 60 held-out questions
DEV = common.run_dir("2026-10-recursive") / "dev.json"  # test 2's 30 dev questions (pairs to avoid)
CAMPAIGN = common.run_dir("2026-10-campaign") / "questions.json"
PROPERTY_MAP = common.analysis_dir("properties-kf") / "map.json"  # A1's property map of KF (125 classes)
PART_A = {"A2": "2026-10-kf-scaling", "A3": "2026-10-kf-resampled", "A4": "2026-10-kf-ladder",
          "A5": "2026-10-kf-a5", "E8": "2026-10-kf-e8"}  # Part A's run folders on KF (and K0)
# What mining also reads, read only: the raw sessions of loop answers, the 200-task run's questions (their material)
# and the cached Crossref records.
LIVE_STREAMS = (common.run_dir("2026-10-campaign") / "streams", common.run_dir("2026-10-03-200") / "streams",
                *sorted((common.ROOT / ".oopc/loop/overnight").glob("*/streams")))
OBSERVATION = common.run_dir("2026-10-03-200") / "questions.json"
CROSSREF = common.ROOT / ".oopc/loop/crossref"

# The withheld question sets (plan, "Withheld tasks"), written by questions.py and fixed by questions/hashes.json.
SETS = ("H", "N", "L")

# The closed list of edits (plan, "The intervention").
GRAPH_EDITS = ("name", "polymer", "family-link")  # read by today's search, through the graph release
STORE_EDITS = ("annotation", "source-link", "property-term")  # in the store copy; the last two read only by freeze-3
TYPES = GRAPH_EDITS + STORE_EDITS
NAME_FIELDS = ("abbreviations", "alternateNames", "tradeNames")
LINK_RELATIONS = ("supplement-of", "version-of", "takes-value-from", "takes-method-from")
RESERVED = ("wop-900001", "wop-999999")  # ids of new polymers; the wiki's sequence is wop-000001 to wop-000274
# The edit groups and the types each holds: a group root carries some of them (`overlay.root_for`), and the effects
# and hops removed are attributed to them. A finding's polymer id goes with the names and families it is read through.
GROUPS = {"name/family": ("name", "polymer", "family-link", "annotation"), "source-link": ("source-link",),
          "property-term": ("property-term",)}

# The tables freeze-3's search reads when they exist; a store without them searches exactly as freeze-2.
# a and b are `knowledge.source_key(doi, url)` strings; a link is read in both directions.
TABLES = """
CREATE TABLE IF NOT EXISTS source_links (a TEXT NOT NULL, relation TEXT NOT NULL, b TEXT NOT NULL, evidence TEXT,
    PRIMARY KEY (a, relation, b));
CREATE TABLE IF NOT EXISTS property_terms (term TEXT PRIMARY KEY, names TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finding_terms (finding_id TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY (finding_id, term));
"""
TABLE_NAMES = ("source_links", "property_terms", "finding_terms")

# The arms (plan, "The screen" and "Case studies"): each arm's store (a root under stores/, `store`) and graph release
# root (under overlay/). The driver's names allow no "+", so O+ is `Oplus`.
ARMS = {"B0": ("K0", "seed-root"), "O0": ("K0-refined", "release-root"),
        "B": ("KF", "seed-root"), "Oplus": ("KF-refined", "release-root")}
LABELS = {"Oplus": "O+"}
B, OPLUS = "B", "Oplus"  # KF on the seed graph, and KF-refined on release O
SCREEN_ARMS, CASE_ARMS = ("B0", "B", "Oplus"), ("B0", "O0", "B", "Oplus")

# The case studies' seeds, committed before the screen: which qualifying questions each case takes (cases.py), and the
# order the picked questions are answered in (run.py).
SELECTION_SEED = "oopc-refinement-cases-2026-10-21"
CASES_SEED = "oopc-refinement-2026-10-21-cases"

# Each engine session's time limit, in seconds: the curator and the reviewer (propose.py; both open sources on the
# web), L's writer (questions.py; web on), the writer of the case studies' own questions (questions.py write-C; no
# web) and the blind relevance judge (lookup.py; no web).
SECONDS = {"curator": 3600, "review": 2400, "writer": 1800, "caseWriter": 900, "judge": 900}


def frozen():
    """The code under test is exactly TAG; returns its commit."""
    try:
        tag = subprocess.check_output(["git", "rev-parse", TAG + "^{commit}"], cwd=common.ROOT, text=True,
                                      stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        raise SystemExit("Tag %s does not exist yet: Part C runs only from it." % TAG)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.CODE, text=True).strip()
    if head != tag:
        raise SystemExit("The code under test (%s) is not %s; set OOPC_STUDY_CODE to a worktree at the tag." % (head, TAG))
    return tag


def folder(name):
    path = FOLDERS[name]
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def set_path(name, questions=None):
    """A withheld set's file, `questions/<name>.json` (`questions`: another questions folder)."""
    return Path(questions or FOLDERS["questions"]) / (name + ".json")


def store(name):
    """A store root the overlay step builds once (`overlay.make_store`, `root_for`): `stores/workspaces/<name>`, such as
    KF, KF-refined, K0 and K0-refined, which the arms copy."""
    return FOLDERS["stores"] / "workspaces" / name
