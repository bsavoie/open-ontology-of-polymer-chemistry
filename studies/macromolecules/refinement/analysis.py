#!/usr/bin/env python3
"""Part C's analysis (docs/exec-plans/active/ontology-refinement-plan.md, "Measures", "Figure" and "Predictions"), from
the records only: no engine call. It reads the run folder `pins.BASE` (`.oopc/loop/harness/2026-10-refinement/`) read
only, opening the stores only with sqlite's immutable read-only mode and the graph releases through `oopc`'s read-only
graph readers, and writes JSON and a short markdown under `ROOT/.oopc/study/analysis/refinement/` (private).

    python -B studies/macromolecules/refinement/analysis.py build|screen|lookup|cases|all [--base DIR] [--out DIR]

- **build** (`build.json`): edits proposed, refused by the screening, approved and rejected by the reviewer, assembled
  (an edit approved in two batches is one edit), dropped by the derivation-pool replay and in force, by type; source
  links by relation and names by field; the misses and hops mined, by class (`mine/summary.json`); and the derivation
  pool's replay of the edits in force per edit group and per type (`mine/effects.json`): misses fixed by kind, hops
  made reachable, results lost. These effects are **in-sample**: the edits were proposed from that same pool.
- **screen** (`screen.json`): 180 withheld questions (H, N, L) on B0 (K0, seed graph), B (KF, seed graph) and O+
  (`Oplus`: KF-refined, release O), one answer each. Overall, per set, per stratum within H and N and per group within
  L (`lookup.subsets`), per arm: contradicted statements, complete answers, results given, wrong-polymer citations,
  passes, access-uncertain statements, answers citing a saved finding, web calls (mean), knowledge lookups (mean),
  new tokens (median) and time (median seconds). Paired per question, O+ against B (the ontology effect) and B against
  B0 (accumulation), with Part A's estimators (`part_a/estimate.paired`: the median paired token ratio, the mean
  paired web-call difference, the ratio of mean web calls and the difference in the share with a result, each with a
  bootstrap 95% interval over questions, 2,000 draws, seed 7), plus the same interval for the time ratio, the web
  ratio and the mean paired differences in contradicted statements, complete answers, passes, answers citing a saved
  finding, knowledge lookups and wrong-polymer citations. Then the **attribution**: per question the accumulation
  effect log(B/B0) and the ontology effect log(O+/B), for web steps (web calls + 1, so that an answer with no web call
  has a ratio) and for new tokens; the median of each effect with its interval; the share of questions where
  |ontology effect| exceeds |accumulation effect| (and the reverse; ties apart); Figure panel a's points (one per
  question, with its set, stratum and the case studies it serves). And Figure panel b: B's hops by class per set and
  stratum, from the hop rows `lookup.py report` writes (`lookup/hops.json`, `lookup.hop_rows`: mining's classes on
  B's copy of KF, a held-unreached hop split into reachable or not on O+'s copy of KF-refined).
- **lookup** (`lookup.json`): the offline measure as `lookup.py report` computed it (`lookup/report.json`), read and
  laid out by set: recall in the returned results (mean over questions with a relevant finding, and pooled), results
  lost (and their share of B's relevant returned results), results gained, wrong-polymer results, and hops removed.
  Nothing here recomputes them.
- **cases** (`cases.json`): the case studies C1-C8, five replicates on B0, O0, B and O+: per case and per question,
  per arm the mean and spread (standard deviation, range) over replicates of web steps (web calls), new tokens,
  knowledge lookups, contradicted statements, complete answers and results given; the paired O+/B and O0/B0 ratios of
  tokens and of web steps (+1) per replicate (same day), pooled over replicates as Part A pools them (geometric mean of
  tokens, mean web calls) and their spread over replicates; and per case the median over its questions (Figure panel
  c's data: web steps per answer per arm with the spread over replicates). C7 is C1's questions on the K0 arms (O0
  against B0; the one question `cases/experiment.json` lists under C7 is also given). C2 and C3 have no question: no
  source-link or family-link edit was proposed and approved, so they are reported as such.
- **all** (`results.json`): the four parts and each pre-registered prediction (plan, "Predictions"), its rule as
  written, the numbers and a verdict: met when every judged part holds, not met when none does, partly met otherwise;
  a part whose records are not there yet is pending (and so is the verdict), and one the study cannot test (C2, C3) is
  said to be so and judged on nothing.

A wrong-polymer citation is a cited saved finding whose `subject` in the answering arm's own store copy is outside the
asked polymers' lineage in that arm's graph (`lookup.asked_lineage`: the question's polymer ids and the polymers its
materials name there, with every family above and member below); a finding without a subject is unfiled, not wrong;
when the arm's graph knows none of the asked polymers, the answer is not judged. Everything is descriptive: one answer
per question and arm in the screen.
"""
import argparse, collections, datetime as dt, hashlib, json, math, random, re, sqlite3, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
from ablation import analyze  # noqa: E402  (test 1's paired ratio and difference with their intervals)
from part_a import estimate  # noqa: E402  (Part A's paired estimators)
from refinement import lookup, pins, questions  # noqa: E402

OUT = common.analysis_dir("refinement")
ARMS, CASE_ARMS = pins.SCREEN_ARMS, pins.CASE_ARMS  # B0, B, Oplus; B0, O0, B, Oplus
COMPARE = {"ontology": (pins.OPLUS, pins.B), "accumulation": (pins.B, "B0")}  # arm against reference
CASE_COMPARE = {"O+/B": (pins.OPLUS, pins.B), "O0/B0": ("O0", "B0")}
CASES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")
NO_EDIT = {"C2": ("source-link",), "C3": ("family-link",)}  # the edit type each needs; none is in force
DRAWS, SEED = estimate.DRAWS, estimate.SEED
MEASURES = ("contradicted", "complete", "resultGiven", "pass", "accessUncertain", "statements")
DIFFS = ("contradicted", "complete", "pass", "citing", "knowledgeLookups", "wrongPolymer", "wrongPolymerAnswer")
WEB = ("new-knowledge", "unsaved-detail", "reached-now", "held-unreached", "failed", "repeat", "unused", "search-only")
STORE = ("held-unreached", "new-polymer", "repeat", "other")
# The plan's grouping of hop classes (Procedure 1.3 and the clarifications of 2026-10-22). Prediction 1 names the first
# two as limited by accumulation; the clarifications add "reached now" there.
LIMITED = {"accumulation": ("new-knowledge", "unsaved-detail"), "reached now": ("reached-now",),
           "ontology (held, unreached)": ("held-unreached",),
           "neither": ("failed", "repeat", "unused", "search-only")}


# ----------------------------------------------------------------------------------------------- reading

def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def maybe(path):
    return jread(path) if Path(path).exists() else None


def ok(value):
    return isinstance(value, dict) and "error" not in value


def label(arm):
    return pins.LABELS.get(arm, arm)


def finding_citations(answer):
    """The saved findings an answer cites: its `citations` and the backticked ids in its text."""
    body = (answer or {}).get("answer") or {}
    listed = {c for c in body.get("citations") or [] if isinstance(c, str) and c.startswith("finding:")}
    text = body.get("answer") if isinstance(body.get("answer"), str) else ""
    return sorted(listed | set(re.findall(r"`(finding:[^`\s]+)`", text)))


class Polymers:
    """What a wrong-polymer citation needs from an arm's workspace: its findings' subjects (sqlite, immutable and read
    only) and the asked polymers' lineage in its graph (`lookup.asked_lineage`, through the graph's read-only
    readers)."""

    def __init__(self):
        self.subjects = {}

    def subject(self, root, ids):
        """{id: subject} for the ids the workspace's store holds (an id it does not hold is absent), or None when the
        workspace has no store."""
        path = Path(root) / ".oopc/loop/knowledge.sqlite"
        key = str(path)
        if key not in self.subjects:
            if not path.exists():
                self.subjects[key] = None
            else:
                db = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
                try:
                    self.subjects[key] = dict(db.execute("SELECT id, subject FROM findings"))
                finally:
                    db.close()
        found = self.subjects[key]
        return None if found is None else {i: found[i] for i in ids if i in found}

    def lineage(self, question, root):
        if not (Path(root) / "releases").exists():
            return None
        return lookup.asked_lineage(question, str(Path(root)))


def answer_row(question, arm, item, root=None, polymers=None, **extra):
    """One answer: its question's set and stratum, what it cost, what its check found (the check's `measures`) and what
    it cites; with `polymers`, its wrong-polymer citations on its own workspace `root`."""
    answer, check = item.get("answer") or {}, item.get("check") or {}
    metrics = answer.get("metrics") or {}
    measures = check.get("measures") if ok(check) and isinstance(check.get("measures"), dict) else None
    cited = finding_citations(answer) if ok(answer) else []
    row = dict({k: question.get(k) for k in ("id", "set", "stratum", "group", "kind")}, arm=arm, **extra,
               answered=ok(answer) and bool(answer.get("answer")), checked=measures is not None,
               newTokens=metrics.get("newTokens"), webCalls=metrics.get("webCalls"),
               knowledgeLookups=metrics.get("knowledgeLookups"), seconds=metrics.get("seconds"),
               findingCitations=len(cited), citing=bool(cited))
    for key in MEASURES:
        value = (measures or {}).get(key)
        row[key] = (value is True) if key in ("complete", "resultGiven", "pass") and measures is not None else value
    row.update(wrongPolymer=None, wrongPolymerAnswer=None, wrongPolymerIds=[], unfiledCitations=None,
               citationsNotInStore=None, familyNotInGraph=question.get("familyInSeed") is False)
    if polymers is not None and root is not None and row["answered"]:
        subjects = polymers.subject(root, cited)
        lineage = polymers.lineage(question, root)
        if subjects is not None:
            row["unfiledCitations"] = sum(i in subjects and not subjects[i] for i in cited)
            row["citationsNotInStore"] = sum(i not in subjects for i in cited)
            if lineage is not None:
                wrong = sorted(i for i in cited if subjects.get(i) and subjects[i] not in lineage)
                row.update(wrongPolymer=len(wrong), wrongPolymerAnswer=bool(wrong), wrongPolymerIds=wrong)
    return row


def folder_records(folder):
    """A driver folder's provenance: its state, the harness revision it was prepared from and the runs it logged."""
    folder = Path(folder)
    found, state = maybe(folder / "pins.json") or {}, maybe(folder / "state.json") or {}
    runs = [json.loads(line) for line in (folder / "runs.jsonl").read_text().splitlines() if line.strip()] \
        if (folder / "runs.jsonl").exists() else []
    return {"state": state.get("status"), "failedItems": state.get("failedItems"),
            "preparedBy": ((found.get("harness") or {}).get("revision") or "")[:12] or None,
            "harnessClean": (found.get("harness") or {}).get("clean"),
            "runRevisions": sorted({(r.get("harness") or {}).get("revision", "")[:12] for r in runs} - {""}),
            "ranFrom": min((r["startedAt"] for r in runs if r.get("startedAt")), default=None),
            "ranTo": max((r["finishedAt"] for r in runs if r.get("finishedAt")), default=None),
            "tag": found.get("tag"), "tagCommit": (found.get("tagCommit") or "")[:12] or None,
            "promptVersion": found.get("promptVersion"), "stores": found.get("stores")}


def driver_rows(folder, polymers=None, **extra):
    """One row per question and arm of a driver folder (`plan.json`, `items/NNNN-<arm>.json`), each arm's wrong-polymer
    citations read on its own workspace `workspaces/<arm>` (with `polymers`)."""
    folder = Path(folder)
    plan, rows = jread(folder / "plan.json"), []
    names = [a["name"] for a in plan["arms"]]
    for index, question in enumerate(plan["questions"]):
        for arm in names:
            item = maybe(folder / "items" / ("%04d-%s.json" % (index, arm))) or {}
            rows.append(answer_row(question, arm, item, folder / "workspaces" / arm, polymers,
                                   folder=folder.name, cases=list(question.get("cases") or []),
                                   written=bool(question.get("pair") or question.get("case")), **extra))
    return rows


# ----------------------------------------------------------------------------------------------- statistics

def r3(value):
    return None if value is None else round(value, 3)


def median(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return statistics.median(values) if values else None


def mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return statistics.mean(values) if values else None


def _draws(values, function):
    rng = random.Random(SEED)
    found = [function(rng.choices(values, k=len(values))) for _ in range(DRAWS)]
    return sorted(x for x in found if x is not None)


def log_median_ci(logs):
    """The median of paired log ratios as a ratio, with its bootstrap 95% interval over questions (as
    `analyze.ratio_ci`, from the logs themselves)."""
    logs = [x for x in logs if x is not None]
    if len(logs) < 3:
        return None
    draws = _draws(logs, statistics.median)
    return {"n": len(logs), "median": round(math.exp(statistics.median(logs)), 3),
            "low": round(math.exp(draws[int(0.025 * len(draws))]), 3),
            "high": round(math.exp(draws[int(0.975 * len(draws))]), 3)}


def share_ci(flags):
    """A share of questions with its bootstrap 95% interval."""
    flags = [bool(f) for f in flags if f is not None]
    if len(flags) < 3:
        return None
    draws = _draws(flags, lambda s: sum(s) / len(s))
    return {"n": len(flags), "share": round(sum(flags) / len(flags), 3), "low": round(draws[int(0.025 * len(draws))], 3),
            "high": round(draws[int(0.975 * len(draws))], 3)}


def ratio_of_means_ci(pairs):
    """Mean of the first over mean of the second (a4_results.web_ratio), with its bootstrap 95% interval."""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    if len(pairs) < 3:
        return None

    def ratio(sample):
        below = sum(b for _, b in sample)
        return sum(a for a, _ in sample) / below if below else None
    if ratio(pairs) is None:
        return None
    draws = _draws(pairs, ratio)
    return {"n": len(pairs), "ratio": round(ratio(pairs), 3), "low": round(draws[int(0.025 * len(draws))], 3),
            "high": round(draws[int(0.975 * len(draws))], 3)}


def per_question(rows):
    """{question id: {arm: row}} over answered rows (one answer per question and arm)."""
    by = collections.OrderedDict()
    for r in rows:
        if r["answered"]:
            by.setdefault(r["id"], {})[r["arm"]] = r
    return by


def numeric(row, key):
    value = row.get(key)
    return float(value) if isinstance(value, bool) else value


def arm_summary(rows, arms):
    """Per arm: the check's measures first (contradicted statements, complete answers, results given), wrong-polymer
    citations, then passes and access-uncertain statements, answers citing a saved finding, web calls, knowledge
    lookups, new tokens and time."""
    value = {}
    for arm in arms:
        mine = [r for r in rows if r["arm"] == arm and r["answered"]]
        checked = [r for r in mine if r["checked"]]
        judged = [r for r in mine if r["wrongPolymer"] is not None]
        web = [r["webCalls"] for r in mine if r["webCalls"] is not None]
        lookups = [r["knowledgeLookups"] for r in mine if r["knowledgeLookups"] is not None]
        value[arm] = {
            "label": label(arm), "questions": len({r["id"] for r in rows if r["arm"] == arm}), "answered": len(mine),
            "checked": len(checked), "contradicted": sum(r["contradicted"] or 0 for r in checked),
            "answersContradicted": sum(bool(r["contradicted"]) for r in checked),
            **{k: sum(r[k] is True for r in checked) for k in ("complete", "resultGiven", "pass")},
            "accessUncertain": sum(r["accessUncertain"] or 0 for r in checked),
            "wrongPolymer": {"citations": sum(r["wrongPolymer"] for r in judged),
                             "answers": sum(bool(r["wrongPolymer"]) for r in judged), "judged": len(judged),
                             "citationsFamilyNotInGraph": sum(r["wrongPolymer"] for r in judged
                                                              if r["familyNotInGraph"]),
                             "unfiledCitations": sum(r["unfiledCitations"] or 0 for r in mine),
                             "citationsNotInStore": sum(r["citationsNotInStore"] or 0 for r in mine)},
            "citingFindings": sum(r["citing"] for r in mine), "findingCitations": sum(r["findingCitations"] for r in mine),
            "noWeb": sum(w == 0 for w in web), "meanWebCalls": r3(mean(web)), "webCalls": sum(web),
            "meanKnowledgeLookups": r3(mean(lookups)), "medianKnowledgeLookups": median(lookups),
            "medianNewTokens": median(r["newTokens"] for r in mine),
            "medianSeconds": r3(median(r["seconds"] for r in mine))}
    return value


def paired(rows, arm, reference):
    """`arm` against `reference`, paired per question: Part A's `estimate.paired` (token ratio, web-call difference,
    web ratio, result-given difference), the time ratio, the web ratio's interval, and the mean paired difference (with
    the two arms' totals over the same questions) of the other measures."""
    value = estimate.paired(rows, arm, reference)
    both = [{a: {k: numeric(r, k) for k in r} for a, r in q.items()} for q in per_question(rows).values()
            if q.get(arm) and q.get(reference)]
    value["questions"] = len(both)
    value["seconds"] = analyze.ratio_ci(both, arm, reference, "seconds")
    value["webRatioInterval"] = ratio_of_means_ci([(q[arm]["webCalls"], q[reference]["webCalls"]) for q in both])
    for key in DIFFS:
        kept = [q for q in both if q[arm].get(key) is not None and q[reference].get(key) is not None]
        found = analyze.diff_ci(kept, arm, reference, key)
        value[key] = dict(found or {"n": len(kept)}, totals={arm: sum(q[arm][key] for q in kept),
                                                             reference: sum(q[reference][key] for q in kept)})
    return value


# ----------------------------------------------------------------------------------------------- attribution

def effect(a, b, plus=0):
    if a is None or b is None or a + plus <= 0 or b + plus <= 0:
        return None
    return math.log((a + plus) / (b + plus))


def points(rows, serves=None):
    """Figure panel a: one point per question with all three screen arms answered, its accumulation effect log(B/B0)
    and ontology effect log(O+/B), for web steps (web calls + 1) and new tokens."""
    serves, found = serves or {}, []
    for qid, arms in per_question(rows).items():
        if not all(a in arms for a in ARMS):
            continue
        first = arms[pins.B]
        web = {a: arms[a]["webCalls"] for a in ARMS}
        tokens = {a: arms[a]["newTokens"] for a in ARMS}
        found.append({
            "id": qid, **{k: first.get(k) for k in ("set", "stratum", "group", "kind")},
            "webCalls": {label(a): web[a] for a in ARMS}, "newTokens": {label(a): tokens[a] for a in ARMS},
            "accumulation": {"web": r3(effect(web[pins.B], web["B0"], 1)),
                             "tokens": r3(effect(tokens[pins.B], tokens["B0"]))},
            "ontology": {"web": r3(effect(web[pins.OPLUS], web[pins.B], 1)),
                         "tokens": r3(effect(tokens[pins.OPLUS], tokens[pins.B]))},
            "cases": serves.get(qid, [])})
    return found


def attribution(found):
    """Over a group's points, per measure: the median accumulation and ontology effects as ratios (with intervals),
    and how often each is the larger in absolute value (ties apart), with the share's interval."""
    value = {"questions": len(found)}
    for measure in ("web", "tokens"):
        usable = [p for p in found if p["accumulation"][measure] is not None and p["ontology"][measure] is not None]
        acc = [p["accumulation"][measure] for p in usable]
        ont = [p["ontology"][measure] for p in usable]
        onto = [abs(o) > abs(a) for a, o in zip(acc, ont)]
        accum = [abs(a) > abs(o) for a, o in zip(acc, ont)]
        value[measure] = {
            "questions": len(usable), "ontologyLarger": sum(onto), "accumulationLarger": sum(accum),
            "ties": len(usable) - sum(onto) - sum(accum),
            "shareOntologyLarger": share_ci(onto), "shareAccumulationLarger": share_ci(accum),
            "accumulation": log_median_ci(acc), "ontology": log_median_ci(ont),
            "medianAbsolute": {"accumulation": r3(median([abs(x) for x in acc])),
                               "ontology": r3(median([abs(x) for x in ont]))}}
    return value


# ----------------------------------------------------------------------------------------------- hops (panel b)

def hop_groups(hop_rows):
    """Figure panel b: B's hops by mining's class, summed per set and stratum (`lookup.subsets`), the plan's grouping
    of them, and the answers with a hop the ontology could remove at all (held, unreached by earlier searches)."""
    value = {}
    for name, chosen in lookup.subsets(hop_rows).items():
        counts = sum((collections.Counter(r.get("byClass") or {}) for r in chosen), collections.Counter())
        web = {c: counts.get("web:" + c, 0) for c in WEB}
        store = {c: counts.get("store:" + c, 0) for c in STORE}
        total_web, total_store = sum(web.values()), sum(store.values())
        reach = {k: sum((r.get(k) or {}).get("reachable", 0) for r in chosen) for k in ("web", "store")}
        grouped = {g: sum(web[c] for c in cs) for g, cs in LIMITED.items()}
        value[name] = {
            "answers": len(chosen), "web": web, "store": store, "webHops": total_web, "storeHops": total_store,
            "webOpens": total_web - web["search-only"],
            "grouped": grouped, "groupedShare": {g: r3(n / total_web) if total_web else None for g, n in grouped.items()},
            "heldUnreached": {"web": web["held-unreached"], "store": store["held-unreached"],
                              "webReachableOnO+": reach["web"], "storeReachableOnO+": reach["store"],
                              "byGroup": dict(sum((collections.Counter(r.get("byGroup") or {}) for r in chosen),
                                                  collections.Counter()))},
            "answersWithHeldUnreached": {
                "web": sum((r.get("web") or {}).get("heldUnreached", 0) > 0 for r in chosen),
                "webOrStore": sum(((r.get("web") or {}).get("heldUnreached", 0)
                                   + (r.get("store") or {}).get("heldUnreached", 0)) > 0 for r in chosen),
                "webReachableOnO+": sum((r.get("web") or {}).get("reachable", 0) > 0 for r in chosen)}}
    return value


# ----------------------------------------------------------------------------------------------- the parts

def meta(base, part):
    """Pins, the commitments' digest, the analysis code's and the code under test's revisions, and the time."""
    def git(where, *args):
        try:
            return subprocess.run(["git", *args], cwd=where, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    here = Path(__file__).resolve().parent
    head = git(here, "rev-parse", "--short=12", "HEAD")
    dirty = git(here, "status", "--porcelain", "--", str(here.parent))
    commitments = questions.COMMITMENTS
    return {"part": part, "pins": pins.PINS, "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "analysisRevision": head and head + ("-dirty" if dirty else ""),
            "codeUnderTest": git(common.CODE, "rev-parse", "--short=12", "HEAD"),
            "commitments": {"file": "studies/macromolecules/refinement/commitments.json",
                            "sha256": hashlib.sha256(commitments.read_bytes()).hexdigest()
                            if commitments.exists() else None},
            "runFolder": ".oopc/loop/harness/%s" % Path(base).name}


def build_part(base):
    """The build: proposals, the screening, the review, the assembly, the drop step and the edits in force, by type;
    the mined misses and hops; the derivation pool's replay per group and per type (in-sample)."""
    base = Path(base)
    raw, screened, refused = collections.Counter(), collections.Counter(), collections.Counter()
    approved, rejected, batches = collections.Counter(), collections.Counter(), []
    for path in sorted((base / "propose/curator").glob("batch-*.json")):
        item = jread(path)
        answer = (item.get("curator") or {}).get("answer") or {}
        raw.update(e.get("type") for e in answer.get("edits") or [])
        edits, refusals = item.get("edits") or [], item.get("refused") or []
        screened.update(e["type"] for e in edits)
        refused.update(e.get("type") for e in refusals)
        review = maybe(base / "propose/review" / path.name) or {}
        verdicts = {v["id"]: v["verdict"] for v in ((review.get("review") or {}).get("answer") or {}).get("verdicts", [])}
        approved.update(e["type"] for e in edits if verdicts.get("p%02d" % e["index"]) == "approved")
        rejected.update(e["type"] for e in edits if verdicts.get("p%02d" % e["index"]) == "rejected")
        batches.append({"batch": path.stem, "proposed": len(answer.get("edits") or []), "screened": len(edits),
                        "refused": len(refusals), "reviewed": bool(verdicts),
                        "approved": sum(v == "approved" for v in verdicts.values())})
    edits = (maybe(base / "overlay/edits.json") or {}).get("edits") or {}
    effects = maybe(base / "mine/effects.json") or {}
    dropped = list(effects.get("dropped") or list(((maybe(base / "overlay/excluded.json") or {}).get("edits") or {})))
    in_force = {e: v for e, v in edits.items() if e not in dropped}
    by_type = lambda chosen: dict(collections.Counter(v["type"] for v in chosen))  # noqa: E731
    per_edit = effects.get("edits") or {}

    def sums(ids):
        chosen = [per_edit[e] for e in ids if e in per_edit]
        return {"edits": len(chosen), "missesFixed": sum(x.get("missesFixed", 0) for x in chosen),
                "hopsReachable": sum(x.get("hopsReachable", 0) for x in chosen),
                "resultsLost": sum(x.get("resultsLost", 0) for x in chosen),
                "byKind": dict(sum((collections.Counter(x.get("byKind") or {}) for x in chosen), collections.Counter())),
                "byHop": dict(sum((collections.Counter(x.get("byHop") or {}) for x in chosen), collections.Counter()))}
    groups = {name: {k: g.get(k) for k in ("missesFixed", "byKind", "hopsReachable", "byHop", "resultsLost",
                                           "changes", "searches")}
              for name, g in (effects.get("groups") or {}).items()}
    summary = maybe(base / "mine/summary.json") or {}
    return {
        "inSample": "The effects below are the derivation pool's replay of edits proposed from that same pool: "
                    "in-sample, not a test.",
        "batches": batches,
        "edits": {"proposed": dict(raw), "proposedTotal": sum(raw.values()), "screened": dict(screened),
                  "refusedByScreening": dict(refused), "refusedTotal": sum(refused.values()),
                  "approvedByReviewer": dict(approved), "approvedTotal": sum(approved.values()),
                  "rejectedByReviewer": dict(rejected), "rejectedTotal": sum(rejected.values()),
                  "assembled": by_type(edits.values()), "assembledTotal": len(edits),
                  "dropped": by_type(edits[e] for e in dropped if e in edits), "droppedTotal": len(dropped),
                  "inForce": by_type(in_force.values()), "inForceTotal": len(in_force),
                  "sourceLinksByRelation": dict(collections.Counter(
                      v["edit"].get("relation") for v in in_force.values() if v["type"] == "source-link")),
                  "namesByField": dict(collections.Counter(
                      v["edit"].get("field") for v in in_force.values() if v["type"] == "name")),
                  "annotationsInForce": sum(v["type"] == "annotation" for v in in_force.values()),
                  "propertyTermsInForce": len({v["edit"].get("term") for v in in_force.values()
                                               if v["type"] == "property-term"})},
        "droppedEdits": [{"edit": e, "type": (per_edit.get(e) or edits.get(e) or {}).get("type"),
                          **{k: (per_edit.get(e) or {}).get(k) for k in ("missesFixed", "hopsReachable", "resultsLost")}}
                         for e in dropped],
        "mined": {"pool": (summary.get("pool") or {}).get("answers"), "replayCheck": summary.get("replayCheck"),
                  "misses": summary.get("misses"), "hops": summary.get("hops"),
                  "dossier": summary.get("dossier")},
        "effects": {"complete": effects.get("complete"), "groups": groups,
                    "byType": {t: sums([e for e, v in in_force.items() if v["type"] == t]) for t in pins.TYPES
                               if any(v["type"] == t for v in in_force.values())},
                    "inForce": sums(list(in_force))}}


def screen_part(base, polymers=None):
    """The screen's rows and every comparison, the attribution and Figure panels a and b."""
    base = Path(base)
    layout = jread(base / "screen/experiment.json")
    polymers = Polymers() if polymers is None else polymers
    rows, records = [], {}
    for name in layout["folders"]:
        rows += driver_rows(base / "screen" / name, polymers)
        records[name] = folder_records(base / "screen" / name)
    serves = collections.defaultdict(list)
    selection = maybe(base / "cases/experiment.json") or {}
    for case, ids in (selection.get("byCase") or {}).items():
        for qid in ids:
            serves[qid].append(case)
    found = points(rows, serves)
    groups = {}
    for name, chosen in lookup.subsets(rows).items():
        ids = {r["id"] for r in chosen}
        groups[name] = {"questions": len(ids), "arms": arm_summary(chosen, ARMS),
                        "paired": {k: paired(chosen, *pair) for k, pair in COMPARE.items()},
                        "attribution": attribution([p for p in found if p["id"] in ids])}
    hops = maybe(base / "lookup/hops.json")
    complete = {"expected": layout["questions"] * len(layout["arms"]), "rows": len(rows),
                "answered": sum(r["answered"] for r in rows), "checked": sum(r["checked"] for r in rows),
                "folders": records}
    return {"arms": {a: label(a) for a in ARMS}, "complete": complete, "groups": groups, "points": found,
            "hops": ({"status": "complete", "source": "lookup/hops.json (lookup.py report)", "rows": len(hops),
                      "groups": hop_groups(hops)} if hops is not None else
                     {"status": "pending", "why": "lookup/hops.json is not there yet: lookup.py report writes it"}),
            "rows": [{k: v for k, v in r.items() if k not in ("written",)} for r in rows]}


def lookup_part(base):
    """`lookup.py report`'s measures by set, as it wrote them (`lookup/report.json`)."""
    base = Path(base) / "lookup"
    report, rows = maybe(base / "report.json"), maybe(base / "rows.json")
    done = (base / "judge.done").read_text(encoding="utf-8").strip() if (base / "judge.done").exists() else None
    if report is None:
        return {"status": "pending", "why": "lookup/report.json is not there yet: lookup.py report writes it",
                "judgeDone": done}
    judge_complete = bool(done and "exit 0" in done)
    status = "complete" if judge_complete and report.get("judged") == report.get("questions") else "partial"
    by = {}
    for name, got in (report.get("groups") or {}).items():
        part = {"questions": got.get("questions")}
        for scope in lookup.SCOPES:
            s = got.get(scope)
            if not s:
                continue
            part[scope] = {"questions": s["questions"], "withRelevant": s["withRelevant"],
                           **{label(arm): {k: s[arm][k] for k in ("meanRecall", "pooledRecall", "relevantFound",
                                                                  "returned", "wrongPolymer", "polymerKnown", "unfiled")}
                              for arm in lookup.ARMS},
                           "recallGain": r3(s[pins.OPLUS]["meanRecall"] - s[pins.B]["meanRecall"])
                           if s[pins.OPLUS]["meanRecall"] is not None and s[pins.B]["meanRecall"] is not None else None,
                           "lost": s["lost"], "lostShare": s["lostShare"], "gained": s["gained"]}
        by[name] = part
    return {"status": status, "judgeDone": done, "reportAt": report.get("at"), "questions": report.get("questions"),
            "judged": report.get("judged"), "issuedRead": sum(bool(r.get("issuedRead")) for r in rows or []),
            "limit": report.get("limit"), "poolLimit": report.get("poolLimit"), "groups": by,
            "hopsRemoved": report.get("hopsRemoved")}


def spread(values):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {"n": len(values), "mean": r3(statistics.mean(values)),
            "sd": r3(statistics.stdev(values)) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}


def geometric(values):
    values = [v for v in values if v]
    return math.exp(statistics.mean(map(math.log, values))) if values else None


def case_question(rows, arms, compare):
    """One case question over its replicates: per arm, the spread of each measure; per comparison, the ratio per
    replicate (same day) and pooled over replicates (geometric mean of tokens; mean web calls + 1)."""
    by_arm = {a: [r for r in rows if r["arm"] == a and r["answered"]] for a in arms}
    value = {"arms": {}, "paired": {}}
    for arm, mine in by_arm.items():
        checked = [r for r in mine if r["checked"]]
        value["arms"][label(arm)] = {
            "answers": len(mine), "webCalls": spread([r["webCalls"] for r in mine]),
            "newTokens": dict(spread([r["newTokens"] for r in mine]) or {},
                              geometricMean=r3(geometric([r["newTokens"] for r in mine]))),
            "knowledgeLookups": spread([r["knowledgeLookups"] for r in mine]),
            "contradicted": spread([r["contradicted"] for r in checked]),
            **{k: {"answers": sum(r[k] is True for r in checked), "of": len(checked)}
               for k in ("complete", "resultGiven", "pass")},
            "citing": {"answers": sum(r["citing"] for r in mine), "of": len(mine)},
            "seconds": spread([r["seconds"] for r in mine])}
    for name, (arm, reference) in compare.items():
        reps = {}
        for r in by_arm[arm]:
            other = next((x for x in by_arm[reference] if x["replicate"] == r["replicate"]), None)
            if other is not None:
                reps[r["replicate"]] = {"tokens": r3(math.exp(effect(r["newTokens"], other["newTokens"])))
                                        if effect(r["newTokens"], other["newTokens"]) is not None else None,
                                        "web": r3(math.exp(effect(r["webCalls"], other["webCalls"], 1)))
                                        if effect(r["webCalls"], other["webCalls"], 1) is not None else None}
        tokens = effect(geometric([r["newTokens"] for r in by_arm[arm]]),
                        geometric([r["newTokens"] for r in by_arm[reference]]))
        web = effect(mean([r["webCalls"] for r in by_arm[arm]]), mean([r["webCalls"] for r in by_arm[reference]]), 1)
        value["paired"][name] = {
            "replicates": {str(k): v for k, v in sorted(reps.items())},
            "pooled": {"tokens": r3(math.exp(tokens)) if tokens is not None else None,
                       "web": r3(math.exp(web)) if web is not None else None},
            "range": {m: [min(x), max(x)] if (x := [v[m] for v in reps.values() if v[m] is not None]) else None
                      for m in ("tokens", "web")}}
    return value


def case_summary(rows, ids, arms, compare, replicates):
    """A case over its questions: per question (`case_question`); per arm the web steps per answer and its spread over
    replicates (the case's mean per replicate); per comparison the median over questions of the pooled ratios, and of
    each replicate's ratios (its range over replicates)."""
    mine = [r for r in rows if r["id"] in ids and r["arm"] in arms]
    per = {qid: case_question([r for r in mine if r["id"] == qid], arms, compare) for qid in ids}
    value = {"questions": list(ids), "perQuestion": per, "arms": {}, "paired": {}}
    for arm in arms:
        answered = [r for r in mine if r["arm"] == arm and r["answered"]]
        checked = [r for r in answered if r["checked"]]
        by_rep = [mean([r["webCalls"] for r in answered if r["replicate"] == k]) for k in replicates]
        value["arms"][label(arm)] = {
            "answers": len(answered), "webCalls": spread([r["webCalls"] for r in answered]),
            "webCallsByReplicate": {"means": [r3(x) for x in by_rep], **(spread(by_rep) or {})},
            "newTokens": {"median": median(r["newTokens"] for r in answered),
                          "geometricMean": r3(geometric([r["newTokens"] for r in answered]))},
            "knowledgeLookups": spread([r["knowledgeLookups"] for r in answered]),
            "contradicted": sum(r["contradicted"] or 0 for r in checked),
            **{k: {"answers": sum(r[k] is True for r in checked), "of": len(checked)}
               for k in ("complete", "resultGiven", "pass")},
            "citing": {"answers": sum(r["citing"] for r in answered), "of": len(answered)}}
    for name in compare:
        pooled = {m: median(per[q]["paired"][name]["pooled"][m] for q in ids) for m in ("tokens", "web")}
        by_rep = {m: [median((per[q]["paired"][name]["replicates"].get(str(k)) or {}).get(m) for q in ids)
                      for k in replicates] for m in ("tokens", "web")}
        value["paired"][name] = {"medianPooled": pooled,
                                 "byReplicate": {m: [r3(x) if x is not None else None for x in v]
                                                 for m, v in by_rep.items()},
                                 "range": {m: [min(x), max(x)] if (x := [y for y in v if y is not None]) else None
                                           for m, v in by_rep.items()}}
    return value


def cases_part(base, edits_in_force=None):
    """The case studies from their replicate folders; C2 and C3 reported as having no qualifying edit."""
    base = Path(base)
    layout = maybe(base / "cases/experiment.json")
    if layout is None:
        return {"status": "pending", "why": "cases/experiment.json is not there yet"}
    selection = maybe(base / "cases/selection.json") or {}
    rows, records = [], {}
    replicates = [int(name[1:]) for name in layout["folders"]]
    for name in layout["folders"]:
        folder = base / "cases" / name
        if (folder / "plan.json").exists():
            rows += driver_rows(folder, None, replicate=int(name[1:]))
        records[name] = folder_records(folder)
    by_case = layout.get("byCase") or {}
    in_force = edits_in_force or {}
    value = {"arms": {a: label(a) for a in CASE_ARMS}, "replicates": len(replicates),
             "complete": {"expected": layout["questions"] * len(layout["arms"]) * len(replicates), "rows": len(rows),
                          "answered": sum(r["answered"] for r in rows), "checked": sum(r["checked"] for r in rows),
                          "folders": records},
             "qualifying": selection.get("qualifying"), "shortfalls": selection.get("shortfalls"), "cases": {}}
    value["status"] = ("complete" if all(f["state"] == "completed" for f in records.values())
                       and value["complete"]["answered"] == value["complete"]["expected"] else "partial")
    for case in CASES:
        ids, arms = list(by_case.get(case) or []), CASE_ARMS
        if case == "C7":
            designated, ids, arms = ids, list(by_case.get("C1") or []), ("B0", "O0")
            if not ids:
                value["cases"][case] = {"status": "no question", "designated": designated}
                continue
            got = case_summary(rows, ids, arms, {"O0/B0": CASE_COMPARE["O0/B0"]}, replicates)
            got["designated"] = designated
            got["rule"] = "C1's questions answered on K0: O0 against B0"
        elif case in NO_EDIT and not ids:
            value["cases"][case] = {
                "status": "no qualifying edit",
                "why": "no %s edit was proposed and approved (edits in force: %s)" % (
                    " or ".join(NO_EDIT[case]), ", ".join("%s %d" % (t, in_force.get(t, 0)) for t in NO_EDIT[case])),
                "qualifying": (selection.get("qualifying") or {}).get(case)}
            continue
        elif not ids:
            value["cases"][case] = {"status": "no question"}
            continue
        else:
            got = case_summary(rows, ids, CASE_ARMS, CASE_COMPARE, replicates)
        mine = [r for r in rows if r["id"] in ids and r["arm"] in arms]
        got["status"] = "complete" if mine and all(r["answered"] and r["checked"] for r in mine) and len(mine) == len(
            ids) * len(arms) * len(replicates) else "partial"
        got["origins"] = {qid: next(("written" if r["written"] else r["set"]) for r in mine if r["id"] == qid)
                          if any(r["id"] == qid for r in mine) else None for qid in ids}
        value["cases"][case] = got
    return value


# ----------------------------------------------------------------------------------------------- predictions

def part(text, met, numbers):
    return {"part": text, "met": met, "numbers": numbers}


PENDING, UNTESTABLE = "pending", "not testable"


def verdict(parts):
    """Met when every judged part holds, not met when none does, partly met otherwise; pending while a part waits for
    its records."""
    flags = [p["met"] for p in parts if isinstance(p["met"], bool)]
    waiting = [p for p in parts if p["met"] == PENDING]
    found = "not judged" if not flags else "met" if all(flags) else "not met" if not any(flags) else "partly met"
    return "pending (so far %s)" % found if waiting else found


def num(x, places=2):
    return "–" if x is None else ("%.*f" % (places, x)).replace("-", "−")


def pct(x):
    return "–" if x is None else "%.1f%%" % (100 * x)


def ci(v, places=2):
    if not v or "low" not in v:
        return "–"
    centre = v.get("median", v.get("mean", v.get("ratio", v.get("share"))))
    return "%s (%s%s%s)" % (num(centre, places), num(v["low"], places), " to " if v["low"] < 0 else "–",
                            num(v["high"], places))


def within(x, low=0.9, high=1.1):
    return x is not None and low <= x <= high


def predictions(value):
    out = []

    def add(pid, rule, parts, note=None):
        out.append({"id": pid, "rule": rule, "parts": parts, "verdict": verdict(parts), "note": note})

    screen, lookups, cases = value.get("screen"), value.get("lookup") or {}, value.get("cases") or {}
    hops = (screen or {}).get("hops") or {}
    groups = (screen or {}).get("groups") or {}

    # ---- 1 hops
    rule1 = ("Most of B's hops on KF are limited by accumulation (new knowledge or unsaved detail). At most about 15% "
             "are avoidable by the ontology, and they occur in fewer than a quarter of answers.")
    if hops.get("status") == "complete":
        h = hops["groups"]["all"]
        n, grouped = h["webHops"], h["grouped"]
        acc = grouped["accumulation"] / n if n else None
        avoid = h["heldUnreached"]["web"] / n if n else None
        answers = h["answersWithHeldUnreached"]["web"] / h["answers"] if h["answers"] else None
        both = h["webHops"] + h["storeHops"]
        both_avoid = (h["heldUnreached"]["web"] + h["heldUnreached"]["store"]) / both if both else None
        add("P1", rule1, [
            part("Most of B's web hops limited by accumulation (new knowledge or unsaved detail)",
                 acc is not None and acc > 0.5,
                 "%d new knowledge + %d unsaved detail of %d web hops (%s); with reached-now %s; of the %d hops that "
                 "opened a page or ended in a search (failed opens excluded), %s" % (
                     h["web"]["new-knowledge"], h["web"]["unsaved-detail"], n, pct(acc),
                     pct((grouped["accumulation"] + grouped["reached now"]) / n if n else None),
                     n - h["web"]["failed"],
                     pct(grouped["accumulation"] / (n - h["web"]["failed"]) if n - h["web"]["failed"] else None))),
            part("At most about 15% avoidable by the ontology (held but unreached by earlier searches)",
                 avoid is not None and round(avoid, 2) <= 0.15,
                 "%d of %d web hops (%s); of them %d reachable on O+; with store hops %d of %d (%s)" % (
                     h["heldUnreached"]["web"], n, pct(avoid), h["heldUnreached"]["webReachableOnO+"],
                     h["heldUnreached"]["web"] + h["heldUnreached"]["store"], both, pct(both_avoid))),
            part("In fewer than a quarter of answers", answers is not None and answers < 0.25,
                 "%d of %d B answers with an avoidable web hop (%s); with store hops %d (%s)" % (
                     h["answersWithHeldUnreached"]["web"], h["answers"], pct(answers),
                     h["answersWithHeldUnreached"]["webOrStore"],
                     pct(h["answersWithHeldUnreached"]["webOrStore"] / h["answers"] if h["answers"] else None)))],
            note="Hop classes are mining's (`mine.Miner.classify`) on B's copy of KF; 'avoidable by the ontology' is "
                 "the held-unreached class (a held finding no earlier store search returned), the most any name, "
                 "family or link edit could remove; how many of them release O's search returns earlier is given "
                 "beside it.")
    else:
        add("P1", rule1, [part("B's hop classes on the withheld set", PENDING, hops.get("why", "screen not read"))])

    # ---- 2 lookup
    rule2 = ("O+'s recall in the first ten is at least B's, with the gain concentrated in L. Lost results are at most "
             "2% of B's relevant results.")
    if lookups.get("status") in ("complete", "partial") and ((lookups["groups"].get("all") or {}).get("all")):
        g = lookups["groups"]
        a = g["all"]["all"]
        gains = {s: ((g.get(s) or {}).get("all") or {}).get("recallGain") for s in pins.SETS}
        parts2 = [
            part("O+'s recall at least B's (mean over questions with a relevant finding; canonical and issued calls)",
                 a["O+"]["meanRecall"] is not None and a["B"]["meanRecall"] is not None
                 and a["O+"]["meanRecall"] >= a["B"]["meanRecall"],
                 "B %s, O+ %s (pooled B %s, O+ %s), %d questions" % (
                     num(a["B"]["meanRecall"], 3), num(a["O+"]["meanRecall"], 3), num(a["B"]["pooledRecall"], 3),
                     num(a["O+"]["pooledRecall"], 3), a["withRelevant"])),
            part("The gain concentrated in L (L's recall gain above 0 and above H's and N's)",
                 gains["L"] is not None and gains["L"] > 0 and all(gains["L"] > (gains[s] or 0) for s in ("H", "N")),
                 "recall gain O+ − B: %s; relevant results gained %s" % (
                     ", ".join("%s %s" % (s, num(gains[s], 3)) for s in pins.SETS),
                     ", ".join("%s %s" % (s, ((g.get(s) or {}).get("all") or {}).get("gained")) for s in pins.SETS))),
            part("Lost results at most 2% of B's relevant results", a.get("lostShare") is not None
                 and a["lostShare"] <= 0.02,
                 "%s lost of %s relevant results B returned (%s)" % (a.get("lost"), a["B"]["relevantFound"],
                                                                     pct(a.get("lostShare"))))]
        if lookups["status"] == "partial":
            parts2.append(part("The judge has judged every question", PENDING, "%s of %s judged; judge.done: %s" % (
                lookups["judged"], lookups["questions"], lookups["judgeDone"])))
        add("P2", rule2, parts2)
    else:
        add("P2", rule2, [part("The offline lookup measure", PENDING, lookups.get("why", "no judged question yet"))])

    # ---- 3 no regression on H and N
    rule3 = ("On H and N, O+ makes no more contradicted statements and no more wrong-polymer citations than B, and "
             "gives no fewer complete answers or results.")
    if screen:
        hn = [r for r in screen["rows"] if r["set"] in ("H", "N")]
        arms = arm_summary(hn, (pins.B, pins.OPLUS))
        wrong = paired(hn, pins.OPLUS, pins.B)["wrongPolymer"]["totals"]
        each = {s: groups[s]["arms"] for s in ("H", "N")}
        sets = lambda key, f=lambda a: a: "; ".join("%s B %s, O+ %s" % (  # noqa: E731
            s, f(each[s][pins.B][key]), f(each[s][pins.OPLUS][key])) for s in ("H", "N"))
        b, o = arms[pins.B], arms[pins.OPLUS]
        add("P3", rule3, [
            part("Contradicted statements: O+ no more than B", o["contradicted"] <= b["contradicted"],
                 "H and N: B %d, O+ %d (%s)" % (b["contradicted"], o["contradicted"], sets("contradicted"))),
            part("Wrong-polymer citations: O+ no more than B (questions judged on both arms)",
                 wrong[pins.OPLUS] <= wrong[pins.B],
                 "B %d, O+ %d on the questions both arms' graphs know; every judged answer: B %d of %d answers, O+ %d "
                 "of %d (%s)" % (wrong[pins.B], wrong[pins.OPLUS], b["wrongPolymer"]["citations"],
                                 b["wrongPolymer"]["judged"], o["wrongPolymer"]["citations"],
                                 o["wrongPolymer"]["judged"], sets("wrongPolymer", lambda w: w["citations"]))),
            part("Complete answers: O+ no fewer than B", o["complete"] >= b["complete"],
                 "B %d, O+ %d of %d (%s)" % (b["complete"], o["complete"], b["checked"], sets("complete"))),
            part("Results given: O+ no fewer than B", o["resultGiven"] >= b["resultGiven"],
                 "B %d, O+ %d of %d (%s)" % (b["resultGiven"], o["resultGiven"], b["checked"], sets("resultGiven")))],
            note="Judged on H and N together (120 questions); the numbers per set are given beside.")
    else:
        add("P3", rule3, [part("The screen", PENDING, "not read")])

    # ---- 4 cost
    rule4 = ("In C1–C3, and on L, O+ uses fewer web steps than B and cites saved findings more often. In C2, O+ needs "
             "at least a third fewer hops. On H and N overall, the paired token ratio O+/B lies within 0.9–1.1.")
    parts4 = []
    for case in ("C1", "C2", "C3"):
        c = (cases.get("cases") or {}).get(case)
        if cases.get("status") == "pending" or c is None:
            parts4.append(part("%s: fewer web steps and more citing" % case, PENDING, cases.get("why", "cases not read")))
        elif c.get("status") in ("no qualifying edit", "no question"):
            parts4.append(part("%s: fewer web steps and more citing" % case, UNTESTABLE, c.get("why", c["status"])))
        elif c["status"] != "complete":
            parts4.append(part("%s: fewer web steps and more citing" % case, PENDING, "partial: B %d, O+ %d answers" % (
                c["arms"]["B"]["answers"], c["arms"]["O+"]["answers"])))
        else:
            b, o = c["arms"]["B"], c["arms"]["O+"]
            parts4.append(part("%s: O+ fewer web steps than B" % case, o["webCalls"]["mean"] < b["webCalls"]["mean"],
                               "web calls per answer B %s, O+ %s (%d and %d answers)" % (
                                   num(b["webCalls"]["mean"]), num(o["webCalls"]["mean"]), b["answers"],
                                   o["answers"])))
            parts4.append(part("%s: O+ cites saved findings more often than B" % case,
                               o["citing"]["answers"] / o["citing"]["of"] > b["citing"]["answers"] / b["citing"]["of"],
                               "answers citing B %d of %d, O+ %d of %d" % (b["citing"]["answers"], b["citing"]["of"],
                                                                           o["citing"]["answers"], o["citing"]["of"])))
    if screen:
        lb = groups["L"]["arms"]
        lp = groups["L"]["paired"]["ontology"]
        parts4.append(part("L: O+ fewer web steps than B", lb[pins.OPLUS]["meanWebCalls"] < lb[pins.B]["meanWebCalls"],
                           "web calls per answer B %s, O+ %s; O+ − B %s; ratio of means %s" % (
                               num(lb[pins.B]["meanWebCalls"]), num(lb[pins.OPLUS]["meanWebCalls"]),
                               ci(lp["webCalls"]), ci(lp["webRatioInterval"]))))
        parts4.append(part("L: O+ cites saved findings more often than B",
                           lb[pins.OPLUS]["citingFindings"] > lb[pins.B]["citingFindings"],
                           "answers citing B %d, O+ %d of 60; O+ − B share %s" % (
                               lb[pins.B]["citingFindings"], lb[pins.OPLUS]["citingFindings"], ci(lp["citing"]))))
    c2 = (cases.get("cases") or {}).get("C2") or {}
    parts4.append(part("C2: O+ at least a third fewer hops", UNTESTABLE if c2.get("status") in (
        "no qualifying edit", "no question") else PENDING, c2.get("why") or c2.get("status") or "cases not read"))
    if screen:
        hn = [r for r in screen["rows"] if r["set"] in ("H", "N")]
        t = paired(hn, pins.OPLUS, pins.B)["tokens"]
        parts4.append(part("H and N overall: paired token ratio O+/B within 0.9–1.1", within(t and t["median"]),
                           "O+/B %s on %d questions; H %s, N %s" % (
                               ci(t), t["n"] if t else 0, ci(groups["H"]["paired"]["ontology"]["tokens"]),
                               ci(groups["N"]["paired"]["ontology"]["tokens"]))))
    add("P4", rule4, parts4, note="C2 and C3 cannot be tested: no source-link or family-link edit was proposed and "
                                  "approved. Web steps in the cases are web calls per answer.")

    # ---- 5 attribution
    rule5 = ("For most questions, the accumulation effect is larger than the ontology effect. The ontology effect is "
             "about zero without knowledge: in C7, O0/B0 lies within 0.9–1.1. It is also about zero in C5 and C6.")
    parts5 = []
    if screen:
        at = groups["all"]["attribution"]
        for measure, name in (("web", "web steps (web calls + 1)"), ("tokens", "new tokens")):
            m = at[measure]
            share = (m["shareAccumulationLarger"] or {}).get("share")
            parts5.append(part("Most questions: |accumulation effect| larger than |ontology effect|, %s" % name,
                               share is not None and share > 0.5,
                               "accumulation larger %d, ontology larger %d, ties %d of %d questions (%s; ontology "
                               "larger %s); median accumulation ratio %s, median ontology ratio %s" % (
                                   m["accumulationLarger"], m["ontologyLarger"], m["ties"], m["questions"],
                                   ci(m["shareAccumulationLarger"]), ci(m["shareOntologyLarger"]),
                                   ci(m["accumulation"]), ci(m["ontology"]))))
    for case, name in (("C7", "O0/B0"), ("C5", "O+/B"), ("C6", "O+/B")):
        c = (cases.get("cases") or {}).get(case)
        if cases.get("status") == "pending" or c is None:
            parts5.append(part("%s: %s within 0.9–1.1" % (case, name), PENDING, cases.get("why", "cases not read")))
            continue
        if c.get("status") in ("no question", "no qualifying edit"):
            parts5.append(part("%s: %s within 0.9–1.1" % (case, name), UNTESTABLE, c["status"]))
            continue
        if c["status"] != "complete":
            parts5.append(part("%s: %s within 0.9–1.1" % (case, name), PENDING, "partial: %s answers" % ", ".join(
                "%s %d" % (a, v["answers"]) for a, v in c["arms"].items())))
            continue
        p = c["paired"][name]
        for measure, what in (("tokens", "tokens"), ("web", "web steps (+1)")):
            x = p["medianPooled"][measure]
            parts5.append(part("%s: %s within 0.9–1.1, %s" % (case, name, what), within(x),
                               "median over its %d questions of the ratio pooled over replicates %s; per replicate %s" % (
                                   len(c["questions"]), num(x), ", ".join(num(y) for y in p["byReplicate"][measure]))))
    add("P5", rule5, parts5, note="C7 is C1's questions on K0 (O0 against B0). A ratio is the median over the case's "
                                  "questions of each question's ratio of its replicates pooled (geometric mean of "
                                  "tokens, mean web calls + 1).")
    return out


# ----------------------------------------------------------------------------------------------- markdown

def k(v):
    return "–" if v is None else "%.1fk" % (v / 1e3)


def build_markdown(b):
    e = b["edits"]
    types = [t for t in pins.TYPES if any((e[x] or {}).get(t) for x in ("proposed", "assembled", "refusedByScreening"))]
    lines = ["## The build", "", "Edits by type, from the curator's proposals to those in force:", "",
             "| Stage | %s | Total |" % " | ".join(types), "| --- |" + " ---: |" * (len(types) + 1)]
    for name, key, total in (("Proposed", "proposed", "proposedTotal"),
                             ("Refused by the screening", "refusedByScreening", "refusedTotal"),
                             ("Approved by the reviewer", "approvedByReviewer", "approvedTotal"),
                             ("Rejected by the reviewer", "rejectedByReviewer", "rejectedTotal"),
                             ("Assembled (one per distinct edit)", "assembled", "assembledTotal"),
                             ("Dropped by the derivation-pool replay", "dropped", "droppedTotal"),
                             ("In force", "inForce", "inForceTotal")):
        lines.append("| %s | %s | %d |" % (name, " | ".join(str((e[key] or {}).get(t, 0)) for t in types), e[total]))
    m = b["mined"]
    fields = lambda d: ", ".join("%s %d" % kv for kv in sorted(d.items())) or "none"  # noqa: E731
    lines += ["", "Names in force by field: %s; source links by relation: %s; annotations in force: %d; distinct property "
              "terms in force: %d." % (fields(e["namesByField"]), fields(e["sourceLinksByRelation"]),
                                       e["annotationsInForce"], e["propertyTermsInForce"]), "",
        "Mined from the derivation pool (%s answers): misses %s; web hops %s; store hops %s." % (
            m["pool"], json.dumps((m["misses"] or {}).get("byKind")),
            json.dumps(((m["hops"] or {}).get("web") or {}).get("byClass")),
            json.dumps(((m["hops"] or {}).get("store") or {}).get("byClass"))), "",
        "**In-sample.** %s" % b["inSample"], "",
        "| Group | Misses fixed | By kind | Hops made reachable | By kind | Results lost |",
        "| --- | ---: | --- | ---: | --- | ---: |"]
    for name, g in b["effects"]["groups"].items():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (name, g["missesFixed"], json.dumps(g["byKind"]),
                                                       g["hopsReachable"], json.dumps(g["byHop"]), g["resultsLost"]))
    lines += ["", "Dropped: %s." % ", ".join("%s (%s; fixes %s, reachable %s, loses %s)" % (
        d["edit"], d["type"], d["missesFixed"], d["hopsReachable"], d["resultsLost"]) for d in b["droppedEdits"]), ""]
    return lines


def screen_markdown(s):
    c = s["complete"]
    lines = ["## The screen", "", "%d of %d answers in the rows, %d answered, %d checked. One answer per question and "
             "arm; intervals are bootstrap 95%% over questions (2,000 draws, seed 7). Web steps in the attribution are "
             "web calls + 1, so that an answer with no web call has a ratio." % (
                 c["rows"], c["expected"], c["answered"], c["checked"]), ""]
    head = ("| Group | Arm | Contradicted | Complete | Result | Wrong-polymer citations (of them in a family the graph "
            "lacks; answers/judged) | Passes | Citing | Web calls | Lookups | Median tokens | Median s |")
    lines += [head, "| --- | --- |" + " ---: |" * 10]
    for name, g in s["groups"].items():
        for arm, a in g["arms"].items():
            w = a["wrongPolymer"]
            lines.append("| %s (%d) | %s | %d | %d | %d | %d (%d; %d/%d) | %d | %d | %s | %s | %s | %s |" % (
                name, g["questions"], a["label"], a["contradicted"], a["complete"], a["resultGiven"],
                w["citations"], w["citationsFamilyNotInGraph"], w["answers"], w["judged"], a["pass"],
                a["citingFindings"], num(a["meanWebCalls"]), num(a["meanKnowledgeLookups"]), k(a["medianNewTokens"]),
                num(a["medianSeconds"], 0)))
    lines += ["", "| Group | Pair | Tokens | Time | Web-call difference | Web ratio | Result | Complete | Contradicted | "
              "Citing | Wrong-polymer |", "| --- | --- |" + " ---: |" * 9]
    for name, g in s["groups"].items():
        for pair, p in g["paired"].items():
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                name, {"ontology": "O+/B", "accumulation": "B/B0"}[pair], ci(p["tokens"]), ci(p["seconds"]),
                ci(p["webCalls"], 1), ci(p["webRatioInterval"]), ci(p["resultGiven"]), ci(p["complete"]),
                ci(p["contradicted"]), ci(p["citing"]), ci(p["wrongPolymer"])))
    lines += ["", "### Attribution (Figure panel a)", "",
              "| Group | Measure | Questions | Accumulation larger | Ontology larger | Ties | Share ontology larger | "
              "Median B/B0 | Median O+/B |", "| --- | --- |" + " ---: |" * 7]
    for name, g in s["groups"].items():
        for measure in ("web", "tokens"):
            m = g["attribution"][measure]
            lines.append("| %s | %s | %d | %d | %d | %d | %s | %s | %s |" % (
                name, measure, m["questions"], m["accumulationLarger"], m["ontologyLarger"], m["ties"],
                ci(m["shareOntologyLarger"]), ci(m["accumulation"]), ci(m["ontology"])))
    lines += ["", "### B's hops by class (Figure panel b)", ""]
    if s["hops"]["status"] != "complete":
        lines.append("Pending: %s." % s["hops"]["why"])
    else:
        lines += ["| Group | Answers | Web hops | %s | Store held-unreached | Reachable on O+ (web/store) | Answers with "
                  "a held-unreached web hop |" % " | ".join(WEB), "| --- |" + " ---: |" * (len(WEB) + 5)]
        for name, h in s["hops"]["groups"].items():
            lines.append("| %s | %d | %d | %s | %d | %d/%d | %d |" % (
                name, h["answers"], h["webHops"], " | ".join(str(h["web"][c]) for c in WEB), h["store"]["held-unreached"],
                h["heldUnreached"]["webReachableOnO+"], h["heldUnreached"]["storeReachableOnO+"],
                h["answersWithHeldUnreached"]["web"]))
    return lines + [""]


def lookup_markdown(v):
    lines = ["## Lookup (offline; `lookup.py report`)", ""]
    if v["status"] == "pending":
        return lines + ["Pending: %s." % v["why"], ""]
    lines += ["%s: %s of %s questions judged; report written %s; judge.done: %s." % (
        v["status"], v["judged"], v["questions"], v["reportAt"], v["judgeDone"]), "",
        "| Group | Scope | Questions (with relevant) | Recall B | Recall O+ | Gain | Pooled B | Pooled O+ | Lost | "
        "Lost share | Gained | Wrong-polymer B | Wrong-polymer O+ |", "| --- | --- |" + " ---: |" * 11]
    for name, g in v["groups"].items():
        for scope in lookup.SCOPES:
            s = g.get(scope)
            if s:
                lines.append("| %s | %s | %d (%d) | %s | %s | %s | %s | %s | %d | %s | %d | %s | %s |" % (
                    name, scope, s["questions"], s["withRelevant"], num(s["B"]["meanRecall"], 3),
                    num(s["O+"]["meanRecall"], 3), num(s["recallGain"], 3), num(s["B"]["pooledRecall"], 3),
                    num(s["O+"]["pooledRecall"], 3), s["lost"], pct(s["lostShare"]), s["gained"],
                    s["B"]["wrongPolymer"], s["O+"]["wrongPolymer"]))
    return lines + [""]


def cases_markdown(v):
    lines = ["## Case studies", ""]
    if v.get("status") == "pending" and "cases" not in v:
        return lines + ["Pending: %s." % v["why"], ""]
    c = v["complete"]
    lines += ["%s: %d of %d answers, %d checked; %d replicates." % (v["status"], c["answered"], c["expected"],
                                                                   c["checked"], v["replicates"]), "",
              "| Case | Status | Questions | Web calls per answer (replicate range) B0 / O0 / B / O+ | Tokens O+/B | "
              "Web O+/B | Tokens O0/B0 | Web O0/B0 |", "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |"]
    for case, got in v["cases"].items():
        if "arms" not in got:
            lines.append("| %s | %s | 0 | %s | – | – | – | – |" % (case, got["status"], got.get("why", "")))
            continue
        arms = " / ".join("%s (%s–%s)" % (num(a["webCalls"]["mean"] if a["webCalls"] else None),
                                          num(a["webCallsByReplicate"].get("min")),
                                          num(a["webCallsByReplicate"].get("max")))
                          if a["answers"] else "–" for a in got["arms"].values())
        cell = lambda name, m: num((got["paired"].get(name) or {}).get("medianPooled", {}).get(m))  # noqa: E731
        lines.append("| %s | %s | %d | %s | %s | %s | %s | %s |" % (
            case, got["status"], len(got["questions"]), arms, cell("O+/B", "tokens"), cell("O+/B", "web"),
            cell("O0/B0", "tokens"), cell("O0/B0", "web")))
    return lines + [""]


def predictions_markdown(found):
    lines = ["## The predictions", ""]
    for p in found:
        lines.append("- **%s, %s.** %s" % (p["id"], p["verdict"], p["rule"]))
        for q in p["parts"]:
            word = q["met"] if isinstance(q["met"], str) else "met" if q["met"] else "not met"
            lines.append("  - %s: %s (%s)." % (q["part"], word, q["numbers"]))
        if p.get("note"):
            lines.append("  - Note: %s" % p["note"])
    return lines + [""]


def markdown(value):
    m = value["meta"]
    lines = ["# Part C: ontology refinement (%s)" % m["part"], "",
             "From the records only (`studies/macromolecules/refinement/analysis.py`, revision %s, %s); code under "
             "test %s (`%s`), prompt `%s`, commitments.json sha256 %s. Descriptive throughout." % (
                 m["analysisRevision"], m["builtAt"], m["codeUnderTest"], m["pins"]["tag"], m["pins"]["promptVersion"],
                 (m["commitments"]["sha256"] or "–")[:16]), ""]
    if "build" in value:
        lines += build_markdown(value["build"])
    if "screen" in value:
        lines += screen_markdown(value["screen"])
    if "lookup" in value:
        lines += lookup_markdown(value["lookup"])
    if "cases" in value:
        lines += cases_markdown(value["cases"])
    if "predictions" in value:
        lines += predictions_markdown(value["predictions"])
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- writing

def write(name, value, out=None, base=None):
    out = Path(out or OUT)
    if base is not None and Path(base).resolve() in [out.resolve(), *out.resolve().parents]:
        raise SystemExit("refusing to write into the run folder")
    text = json.dumps(value, ensure_ascii=False, indent=1, default=str)
    if "/Users/" in text or str(common.ROOT) in text:
        raise SystemExit("refusing to write a local path into the results")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / (name + ".json")).write_text(text + "\n", encoding="utf-8")
    (out / (name + ".md")).write_text(markdown(value), encoding="utf-8")
    return out / (name + ".json")


def in_force(base):
    edits = (maybe(Path(base) / "overlay/edits.json") or {}).get("edits") or {}
    dropped = set((maybe(Path(base) / "mine/effects.json") or {}).get("dropped") or [])
    return dict(collections.Counter(v["type"] for e, v in edits.items() if e not in dropped))


def run(command, base=None, out=None, polymers=None):
    base = Path(base or pins.BASE)
    value = {"meta": meta(base, command)}
    if command in ("build", "all"):
        value["build"] = build_part(base)
    if command in ("screen", "all"):
        value["screen"] = screen_part(base, polymers)
    if command in ("lookup", "all"):
        value["lookup"] = lookup_part(base)
    if command in ("cases", "all"):
        value["cases"] = cases_part(base, in_force(base))
    if command == "all":
        value["predictions"] = predictions(value)
    write("results" if command == "all" else command, value, out, base)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("build", "screen", "lookup", "cases", "all"))
    parser.add_argument("--base", type=Path, help="the run folder (default: pins.BASE)")
    parser.add_argument("--out", type=Path, help="where to write (default: analysis/refinement/)")
    args = parser.parse_args(argv)
    value = run(args.command, args.base, args.out)
    for p in value.get("predictions", []):
        print("%-3s %-28s %s" % (p["id"], p["verdict"], " | ".join(
            "%s: %s" % (q["met"] if isinstance(q["met"], str) else "ok" if q["met"] else "NO", q["numbers"][:160])
            for q in p["parts"])))
    print("wrote", Path(args.out or OUT) / (("results" if args.command == "all" else args.command) + ".json"))


if __name__ == "__main__":
    main()
