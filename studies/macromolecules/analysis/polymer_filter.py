"""How many findings saved for a single-polymer question a search naming that polymer keeps (CL-15, P1-9).

On 2026-10-12 this figure rose from 87.9% to 98.9% on 7,179 findings, computed with inline scripts that were not
saved; this is that computation, so it can run again on any store (reconstructed 2026-10-14; it gives 98.9% on the
store of that day). Read-only.

- Questions: campaign tasks with one material (`.oopc/loop/harness/2026-10-campaign/questions.json`, `materials`),
  or with `--from-questions`, every question in the store's workspace whose text names exactly one polymer.
- The polymer: what the knowledge search makes of that material (`knowledge._query_parts`); a material naming no
  polymer the graph knows has nothing to filter and is left out.
- Kept: a finding of the question (any status) passes the search's polymer filter alone (no ranking or limit): its
  statement or material names the polymer, or it is filed under the polymer, one of its families or members
  ("lineage"); "exact" counts only the polymer itself, as before 2026-10-12.

    python -B polymer_filter.py [--store PATH] [--from-questions]
"""
import argparse, collections, json, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, run_dir  # noqa: E402
from oopc import knowledge  # noqa: E402

CAMPAIGN = run_dir("2026-10-campaign") / "questions.json"


def campaign_tasks(path=CAMPAIGN):
    return [(t["taskId"], t["materials"][0]) for t in json.loads(Path(path).read_text()) if len(t["materials"]) == 1]


def question_tasks(root):
    """Every question of a workspace whose text names one polymer, with that text as its material."""
    found = []
    for path in sorted((knowledge.folder(root) / "questions").glob("*/question.json")):
        item = json.loads(path.read_text())
        if knowledge.question_subject(root, item.get("question", "")):
            found.append((item["id"], item["question"]))
    return found


def measure(root, store, tasks):
    """Counts of findings kept by name or exact id, and by name or lineage, over `tasks` [(question id, material)]."""
    db = sqlite3.connect("file:" + str(store) + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    counts = collections.Counter()
    try:
        for question, material in tasks:
            polymers, _ = knowledge._query_parts(root, material)
            rows = db.execute("SELECT statement, material, subject FROM findings WHERE question_id=?", (question,)).fetchall()
            if not polymers:
                counts["leftOut"] += len(rows)
                continue
            for polymer in polymers:
                polymer["lineage"] = knowledge.lineage(root, polymer["ids"])
            for row in rows:
                topic = knowledge._words((row["statement"] or "") + " " + (row["material"] or ""))
                named = any(knowledge._mentions(topic, n) for p in polymers for n in p["names"])
                counts["findings"] += 1
                counts["exact"] += named or any(row["subject"] and row["subject"] in p["ids"] for p in polymers)
                counts["lineage"] += named or any(row["subject"] and row["subject"] in p["lineage"] for p in polymers)
    finally:
        db.close()
    share = lambda n: round(n / counts["findings"], 4) if counts["findings"] else None
    return {"questions": len(tasks), "findings": counts["findings"], "leftOut": counts["leftOut"],
            "keptExact": counts["exact"], "keptLineage": counts["lineage"],
            "shareExact": share(counts["exact"]), "shareLineage": share(counts["lineage"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--store", default=str(knowledge.database(ROOT)))
    parser.add_argument("--from-questions", action="store_true", help="questions from the workspace, not the campaign")
    args = parser.parse_args(argv)
    tasks = question_tasks(ROOT) if args.from_questions else campaign_tasks()
    print(json.dumps(dict(measure(ROOT, args.store, tasks), store=args.store), indent=1))


if __name__ == "__main__":
    main()
