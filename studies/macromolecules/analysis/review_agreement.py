"""Do two reviewers agree? A sample of reviewed findings reviewed again in fresh sessions (P0-5).

The store's verdicts are the first review; this runs a second one with today's reviewer instructions and captured source
text, one session per question's group (as the loop reviews), and never changes a finding's status. Agreement counts
content verdicts only: a pair where either review could not read the source (the access pattern of `oopc upkeep`) says
nothing about judgement, and neither does Needs checking for a polymer name its reviewer could not settle. A Reviewed
finding a later review found unsupported (Needs checking) is compared with that later verdict. Pairs are also split by
whether the first review used today's reviewer instruction (from CURRENT: methods sections, captured text). The
pre-publication target is at least 95% agreement on content verdicts; the report also gives every pair but access ones
(`all`), as first defined.

The first reviews are pinned when the sample is drawn (`first.json`), so a later change to a finding's status (applying
a second review's verdict, say) cannot change the measured agreement. A sample drawn before pinning existed is pinned
once from a store backup taken before any such change.

    python -B review_agreement.py prepare [--size 100] [--root WORKSPACE]   # the sample, fixed by its seed
    python -B review_agreement.py pin --store BACKUP/knowledge.sqlite      # once, for a sample drawn unpinned
    python -B review_agreement.py run [--engine codex]                       # uses your subscription
    python -B review_agreement.py report
"""
import argparse, collections, json, random, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, analysis_dir  # noqa: E402
from oopc import calls, engines, knowledge, reviewer, upkeep  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

OUT = analysis_dir("review-agreement")
SEED = 20261014
CURRENT = "2026-10-14"  # the first day of reviews with the methods-section instruction and captured source text


def prepare(root=ROOT, size=100, out=OUT):
    """A stratified sample: half Reviewed, half Rejected or Needs checking for a reason other than access (as many as
    there are), drawn with a fixed seed; refuses to overwrite an existing sample."""
    if (Path(out) / "sample.json").exists():
        raise ValueError("A sample exists; delete it to draw another")
    rows = upkeep._rows(root, "status IN (?, ?, ?)", (knowledge.SUPPORTED, knowledge.UNSUPPORTED, knowledge.UNCERTAIN))
    rng = random.Random(SEED)
    doubted = sorted((r["id"] for r in rows if r["status"] != knowledge.SUPPORTED and not upkeep.access_uncertain(r)))
    supported = sorted(r["id"] for r in rows if r["status"] == knowledge.SUPPORTED)
    chosen = rng.sample(doubted, min(len(doubted), size // 2))
    chosen += rng.sample(supported, size - len(chosen))
    value = {"root": str(root), "seed": SEED, "drawnAt": now(), "ids": sorted(chosen)}
    atomic_json(Path(out) / "first.json", firsts(knowledge.database(root), value["ids"]), private=True)
    atomic_json(Path(out) / "sample.json", value, private=True)
    return value


def firsts(store, ids):
    """The first review of each sampled finding as the store records it: status, reason, time, and whether its status
    stands for an unsettled polymer name or a Reviewed finding a later review found unsupported."""
    db = sqlite3.connect(Path(store).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = {r[0]: r for r in db.execute("SELECT id, status, review_reason, reviewed_at, detail FROM findings")}
    finally:
        db.close()
    value = {}
    for identifier in ids:
        _, status, reason, reviewed, detail = rows[identifier]
        detail = json.loads(detail or "{}")
        value[identifier] = {"status": status, "reason": reason or "", "reviewedAt": reviewed or "",
                             "unsettledName": bool(detail.get("ambiguous")), "recheck": detail.get("recheck")}
    return {"pinnedAt": now(), "store": str(store), "findings": value}


def pin(store, out=OUT):
    """Pin the first reviews of a sample drawn before they were saved with it, from a store copy taken before any of
    its findings changed; never overwrites a pin."""
    if (Path(out) / "first.json").exists():
        raise ValueError("The first reviews are already pinned")
    value = firsts(store, read_json(Path(out) / "sample.json")["ids"])
    atomic_json(Path(out) / "first.json", value, private=True)
    return value


def run(engine="codex", runner=None, out=OUT):
    """Second reviews of the sample, one session per question; done groups are skipped on a rerun."""
    sample = read_json(Path(out) / "sample.json")
    root = Path(sample["root"])
    found = [knowledge.get(root, i) for i in sample["ids"]]
    groups = collections.defaultdict(list)
    for finding in found:
        groups[finding["questionId"]].append(finding)
    results = Path(out) / "reviews"
    for question, findings in sorted(groups.items()):
        path = results / (question[:12] + ".json")
        if path.exists() and "error" not in read_json(path):
            continue
        reviewer.capture_sources(root, [f.get("source") or {} for f in findings])
        try:
            result = calls.invoke(root, "study:review-agreement", question, runner or engines.run_session, engine,
                                  reviewer.review_prompt(findings, root), reviewer.REVIEW_SCHEMA, tools=None, web=True,
                                  timeout=reviewer.REVIEW_SECONDS, idle=reviewer.IDLE_SECONDS)
            value = {"engine": result["engine"], "at": now(),
                     "verdicts": reviewer.parse_verdicts(result["answer"], {f["id"] for f in findings})}
        except engines.EngineError as error:
            value = {"error": error.summary(), "at": now()}
        atomic_json(path, value, private=True)
    return report(out)


def report(out=OUT):
    sample = read_json(Path(out) / "sample.json")
    pinned = read_json(Path(out) / "first.json")["findings"]
    second = {}
    for path in sorted((Path(out) / "reviews").glob("*.json")):
        second.update(read_json(path).get("verdicts") or {})
    pairs = collections.Counter()
    for identifier in sample["ids"]:
        first, again = pinned[identifier], second.get(identifier)
        if not again:
            pairs["notReviewedAgain"] += 1
            continue
        status = first["status"]
        access = upkeep.ACCESS.search(first["reason"]) and status == knowledge.UNCERTAIN
        if access or (again["verdict"] == knowledge.UNCERTAIN and upkeep.ACCESS.search(again["reason"])):
            pairs["access"] += 1
            continue
        pairs.update({"allPairs": 1, "allAgree": status == again["verdict"]})
        if status == knowledge.UNCERTAIN and first["unsettledName"]:
            pairs["unsettledName"] += 1
            continue
        if status == knowledge.UNCERTAIN and first["recheck"] == knowledge.UNSUPPORTED:
            status = knowledge.UNSUPPORTED
        era = "current" if first["reviewedAt"] >= CURRENT else "earlier"
        agree = status == again["verdict"]
        pairs.update({"content": 1, "agree": agree, era + "Content": 1, era + "Agree": agree,
                      "%s→%s" % (status, again["verdict"]): 1})
    share = lambda agree, total: round(pairs[agree] / pairs[total], 3) if pairs[total] else None
    value = dict(pairs, sample=len(sample["ids"]), agreement=share("agree", "content"),
                 currentAgreement=share("currentAgree", "currentContent"),
                 earlierAgreement=share("earlierAgree", "earlierContent"), allAgreement=share("allAgree", "allPairs"),
                 target=0.95)
    atomic_json(Path(out) / "report.json", value, private=True)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=["prepare", "pin", "run", "report"])
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--store", help="pin: a store copy taken before any sampled finding changed")
    parser.add_argument("--engine", default="codex", choices=sorted(engines.ENGINES))
    args = parser.parse_args(argv)
    if args.action == "pin" and not args.store:
        parser.error("pin needs --store")
    value = (prepare(Path(args.root), args.size) if args.action == "prepare" else pin(args.store) if args.action == "pin"
             else run(args.engine) if args.action == "run" else report())
    print(json.dumps(value, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
