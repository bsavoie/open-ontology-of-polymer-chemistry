"""Part C's offline lookup measure (docs/exec-plans/active/ontology-refinement-plan.md, "Measures", lookup): for each
withheld question, what saved knowledge the searches reach under the seed graph on KF (arm B) and under the refined
ontology on KF-refined (arm Oplus, O+), judged blind.

- **Queries.** The canonical query, each asked material plus the property ("Call search_knowledge first using the
  material name and requested property as the query core", the researcher's prompt), searched at the tool's default
  limit (LIMIT, 10), and, once the screen has answered the question, every `search_knowledge` call the screen's B arm
  made, with its query and limit as recorded (its driver item's run, read from the trace's events, `recorded_calls`;
  limit 10 when the call gave none, as the tool reads it).
- **What a search returns** (`returned`). Each call runs exactly as the researcher's tool runs it (`knowledge.search(
  root, q, limit, compact=True)`) on each arm's own copy of its store in the lookup folder (`roots`, checked as the
  run's arms are), and every finding it returns counts: its matches and the same-source and linked findings after them
  (notes are not findings). "The first ten" of the plan are these: a finding counts as returned for recall and losses
  when the canonical query's call at limit 10, or an issued call as recorded, returns it. Mining uses the same
  definition (`mine.py`).
- **Judge.** The pool is everything any of these calls returned on either arm, and everything the same queries return
  at limit POOL (25) on either arm (calls made only to widen the pool: the plan's "pooled first 25 results"); one Codex
  session per question (JUDGE, JUDGE_SCHEMA; no web, no tools; phase PHASE) marks each pooled finding relevant or not,
  the findings shuffled and numbered (JUDGE_SEED) and shown without ids, so the judge never sees which arm returned
  which. A pool that grows (the screen's queries arrive later) has only its new findings judged, in a further session.
- **Measures** (`measures`), per question and per set of queries (canonical, issued, all): recall (relevant findings
  an arm's calls returned over those queries, over the relevant findings in the question's pool); results lost
  (relevant findings B's call returned for a query that O+'s call for the same query and limit did not) and,
  conversely, gained; wrong-polymer results (returned findings whose `subject` in the refined store is outside the asked
  polymers' lineage under the refined graph; findings without a subject are counted apart, as unfiled).
- **Hops removed** (`hop_rows`, in `report`, once the screen has run): B's avoidable hops whose target the refined
  search returns at the earlier step. Each question's B answer (the screen's driver item, normalized as mining
  normalizes an answer) has its hops classed on B's copy of KF by `mine.Miner.classify`; its held-unreached web and
  store hops are split into reachable or not on O+'s copy of KF-refined, and each reachable one is attributed to the
  edit groups that reach it alone (`overlay.root_for` per group). Per question in `hops.json`, summed per set and
  stratum in the report.

Resumable: searches are saved per question (`searches/`), each judge session with its attempts (`judge/`), all under
`pins.folder("lookup")`.

    python -B studies/macromolecules/refinement/lookup.py judge [--canonical-only] [--hours H]
    python -B studies/macromolecules/refinement/lookup.py report
"""
import argparse, collections, functools, json, random, sqlite3, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import cases, mine, overlay, pins, questions, run  # noqa: E402
from oopc import calls, engines, knowledge  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, now, read_json  # noqa: E402

ARMS = (pins.B, pins.OPLUS)  # the baseline (KF, seed graph) and the refined ontology (KF-refined, release O)
LIMIT, POOL = 10, 25  # search_knowledge's default limit; the limit of the calls that only widen the judge's pool
SCOPES = ("canonical", "issued", "all")
PHASE = "study:refinement:judge"
JUDGE_SEED = "oopc-refinement-2026-10-21-judge"

JUDGE = """You judge which saved findings are relevant to a question about polymers. A finding is relevant when an answer
to the question could cite it for what the question asks: it is about the polymer the question asks about (for a
question about a family, any member of the family; for a comparison, any of the polymers compared) and it reports the
property asked for, or the method, specimen or conditions of a reported value of that property. A finding about
another polymer or another property is not relevant, however close. Judge each finding on its own; the order of the
list means nothing.

Return one judgement for every finding number: `number`, `relevant` (true or false) and `reason` (a few words).
"""
JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["judgements"],
    "properties": {"judgements": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["number", "relevant", "reason"],
        "properties": {"number": {"type": "integer"}, "relevant": {"type": "boolean"}, "reason": {"type": "string"}}}}}}
FIELDS = ("statement", "material", "property", "value", "unit", "conditions", "source_title")


def folder():
    return pins.folder("lookup")


def roots():
    """Each arm's own copy of its store in the lookup folder (made once), checked as the run's arms are."""
    run.check_arms({arm: run.store_root(arm) for arm in ARMS}, graph=False)
    made = {arm: driver.workspace(folder(), arm, releases=run.release_root(arm), store=run.store_root(arm))
            for arm in ARMS}
    run.check_arms(made)
    return made


def withheld():
    return [q for name in pins.SETS for q in questions.load(name)]


# ----- queries and searches -----

def canonical(question):
    return list(dict.fromkeys(("%s %s" % (m, question["property"])).strip() for m in question["materials"]))


def recorded_calls(root, run_id):
    """A run's `search_knowledge` calls as its trace records them, in order: [query, limit] (LIMIT when the call gave
    none, as the tool reads it). Read from the trace's files, never through `TraceStore`, which opens the run for
    writing."""
    events = Path(root) / ".oopc/runs" / str(run_id) / "events.jsonl"
    if not run_id or not events.exists():
        return []
    found = []
    for line in events.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("operation") == "knowledge.search_knowledge" and event.get("status") == "ok":
            args = (event.get("request") or {}).get("arguments") or {}
            if isinstance(args.get("q"), str) and args["q"].strip():
                found.append([args["q"], args.get("limit", LIMIT)])
    return found


def issued():
    """The calls the screen's B arm made, by question id ([query, limit] each), from its driver items and run traces; a
    question whose B answer is not there yet is absent, and one whose B answer failed has none (a rerun of the screen
    that answers it adds its calls, and the judge then judges only what they add)."""
    base = pins.folder("screen")
    found = {}
    layout = base / "experiment.json"
    for name in (read_json(layout)["folders"] if layout.exists() else []):
        plan = read_json(base / name / "plan.json")
        root = next(a["root"] for a in plan["arms"] if a["name"] == "B")
        for index, question in enumerate(plan["questions"]):
            answer = driver._item(base / name, index, question, "B").get("answer") or {}
            if driver._ok(answer) and answer.get("runId"):
                found[question["id"]] = recorded_calls(root, answer["runId"])
            elif "error" in answer:
                found[question["id"]] = []
    return found


def returned(root, query, limit=LIMIT):
    """Every finding id `search_knowledge` returns for (query, limit), in the order it returns them: its matches, then
    the same-source and linked findings (notes are not findings)."""
    result = knowledge.search(root, query, limit, compact=True)
    return [f["id"] for group in mine.GROUPED for f in result.get(group, [])]


def searches(question, made, issued_calls=None):
    """The question's saved searches, with any call not searched yet run on both arms: its canonical queries at LIMIT,
    then the B arm's `issued_calls` as recorded ([query, limit]); a call both canonical and issued is kept once, with
    both origins. Each holds what each arm's call returns (`returned`) and what the same query returns at POOL
    (`pooled`, for the judge's pool only)."""
    target = folder() / "searches" / (question["id"] + ".json")
    stored = read_json(target) if target.exists() else {"question": question["id"], "queries": []}
    by_call = {(s["q"], s["limit"]): s for s in stored["queries"]}
    changed = False
    wanted = [((q, LIMIT), "canonical") for q in canonical(question)]
    wanted += [((q, limit), "issued") for q, limit in issued_calls or []]
    for (query, limit), origin in wanted:
        if (query, limit) not in by_call:
            by_call[query, limit] = {"q": query, "limit": limit, "origins": [],
                                     "returned": {arm: returned(made[arm], query, limit) for arm in ARMS},
                                     "pooled": {arm: returned(made[arm], query, POOL) for arm in ARMS}}
            stored["queries"].append(by_call[query, limit])
            changed = True
        if origin not in by_call[query, limit]["origins"]:
            by_call[query, limit]["origins"].append(origin)
            changed = True
    if issued_calls is not None and not stored.get("issuedRead"):
        stored["issuedRead"] = changed = True  # the screen's B answer has been read (it may have made no call)
    if changed:
        atomic_json(target, stored, private=True)
    return stored


def pool(stored):
    """The question's pool: whatever any of its calls returned on either arm, and the wider POOL calls' findings."""
    return list(dict.fromkeys(i for s in stored["queries"] for part in ("returned", "pooled") for arm in ARMS
                              for i in s[part][arm]))


# ----- the judge -----

def issued_callsof(question_id):
    return [read_json(p) for p in sorted((folder() / "judge" / question_id).glob("call-*.json"))]


def verdicts(question_id):
    """Every pooled finding judged so far: id -> relevant."""
    found = {}
    for call in issued_callsof(question_id):
        if driver._ok(call.get("result")):
            found.update(call["result"]["relevant"])
    return found


def findings(root, ids):
    """The judged findings' text (from the B arm's copy; findings' content is the same in both stores)."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = {r["id"]: r for r in db.execute("SELECT id, %s FROM findings WHERE id IN (%s)"
                                           % (", ".join(FIELDS), ",".join("?" * len(ids))), list(ids))}
    db.close()
    return rows


def meaning(question, labels):
    names = ", ".join(question["materials"])
    known = sorted({labels.get(i, i) for i in question.get("polymerIds") or []})
    return "%s%s" % (names, "; in the polymer ontology: " + ", ".join(known) if known else "")


def judge_prompt(question, rows, labels):
    """The judge's prompt: the question, what it is about, and the findings numbered in the order given, without ids."""
    lines = []
    for number, row in enumerate(rows, 1):
        value = " ".join(x for x in (row["value"], row["unit"]) if x)
        parts = [row["statement"], "material: " + (row["material"] or ""), "property: " + (row["property"] or "")]
        parts += ["value: " + value] if value else []
        parts += ["conditions: " + row["conditions"][:400]] if row["conditions"] else []
        parts += ["source: " + row["source_title"][:200]] if row["source_title"] else []
        lines.append("%d. %s" % (number, " | ".join(p.replace("\n", " ") for p in parts)))
    return (JUDGE + "\nQuestion: " + question["question"] + "\nThe question is about: " + meaning(question, labels)
            + "\n\nFindings:\n" + "\n".join(lines) + "\n")


def judge_question(guard, question, stored, made, labels):
    """Judge the question's pooled findings not judged yet, in one session (a failed one is tried again first)."""
    open_call = next((c for c in issued_callsof(question["id"]) if not driver._ok(c.get("result"))), None)
    if open_call is None:
        done = verdicts(question["id"])
        new = sorted(i for i in pool(stored) if i not in done)  # sorted first: the order owes nothing to the arms
        if not new:
            return None
        number = len(issued_callsof(question["id"])) + 1
        random.Random("%s-%s-%d" % (JUDGE_SEED, question["id"], number)).shuffle(new)
        open_call = {"question": question["id"], "call": number, "findings": new}
    target = folder() / "judge" / question["id"] / ("call-%d.json" % open_call["call"])
    open_call.pop("result", None)
    atomic_json(target, open_call, private=True)
    reason = driver._unavailable(guard, [engines.CODEX])
    if reason:
        raise driver.Stop(reason)
    rows = findings(made["B"], open_call["findings"])
    if set(rows) != set(open_call["findings"]):
        raise SystemExit("A pooled finding is missing from the store copy: %s" % question["id"])
    prompt = judge_prompt(question, [rows[i] for i in open_call["findings"]], labels)

    def work():
        result = calls.invoke(folder(), PHASE, question["id"], guard, engines.CODEX, prompt, JUDGE_SCHEMA, tools=None,
                              web=False, timeout=pins.SECONDS["judge"])
        got = result["answer"].get("judgements") or []
        numbers = [j.get("number") for j in got]
        if sorted(numbers) != list(range(1, len(open_call["findings"]) + 1)):
            raise engines.EngineError("invalid-output", "the judgements do not number each finding once")
        by_number = {j["number"]: j for j in got}
        ids = open_call["findings"]
        return {"relevant": {ids[n - 1]: bool(by_number[n]["relevant"]) for n in by_number},
                "reasons": {ids[n - 1]: by_number[n].get("reason", "")[:300] for n in by_number},
                "callId": result.get("callId"), "model": result.get("model")}
    driver._attempts(folder(), guard, target, open_call, "result", work)
    return open_call


def judge(runner=None, hours=12, canonical_only=False):
    """Search and judge every withheld question (resumable). A question the screen's B arm has not answered yet waits,
    unless `canonical_only`: then its canonical queries are judged now and the issued ones later. Every session goes
    through `runner`, a Guard (by default `driver.Guard`, a deadline `hours` away)."""
    pins.frozen()
    made = roots()
    labels = knowledge._graph_families(made["Oplus"])[2]
    found = issued()
    guard = runner or driver.Guard(time.time() + hours * 3600, base=folder())
    state = {"status": "running", "startedAt": now(), "waiting": 0, "judged": 0, "failed": 0}
    try:
        for question in withheld():
            queries = found.get(question["id"])
            if queries is None and not canonical_only:
                state["waiting"] += 1
                continue
            stored = searches(question, made, queries)
            done = judge_question(guard, question, stored, made, labels)
            if done is not None:
                state["judged" if driver._ok(done.get("result")) else "failed"] += 1
        state.update(status="completed")
    except driver.Stop as stop:
        state.update(status="stopped", stopReason=stop.args[0])
    state["finishedAt"] = now()
    atomic_json(folder() / "state.json", state, private=True)
    return state


# ----- measures and report -----

def asked_lineage(question, root):
    """The asked polymers and everything above and below them in the refined graph, or None when the refined graph
    knows none of them: the question's own ids and the polymers its materials name there."""
    ids = set(question.get("polymerIds") or []) | set().union(*(questions.resolved(root, m)
                                                                 for m in question["materials"]))
    return knowledge.lineage(root, ids) if ids else None


def measures(stored, relevant, subjects, lineage):
    """One question's lookup measures from its saved searches, the judge's verdicts (id -> relevant), the findings'
    subjects in the refined store and the asked polymers' lineage (None: unknown)."""
    every = pool(stored)
    good = {i for i in every if relevant.get(i)}
    value = {"pool": len(every), "judged": sum(i in relevant for i in every), "relevant": len(good),
             "queries": len(stored["queries"])}
    for scope in SCOPES:
        chosen = [s for s in stored["queries"] if scope == "all" or scope in s["origins"]]
        if not chosen:
            value[scope] = None
            continue
        got = {arm: set().union(*(set(s["returned"][arm]) for s in chosen)) for arm in ARMS}
        lost = set().union(*((set(s["returned"]["B"]) - set(s["returned"]["Oplus"])) & good for s in chosen))
        gained = set().union(*((set(s["returned"]["Oplus"]) - set(s["returned"]["B"])) & good for s in chosen))
        part = {"queries": len(chosen), "lost": sorted(lost), "gained": sorted(gained)}
        for arm in ARMS:
            found = got[arm] & good
            part[arm] = {"returned": len(got[arm]), "relevantFound": len(found),
                         "recall": len(found) / len(good) if good else None,
                         "unfiled": sum(not subjects.get(i) for i in got[arm]),
                         "wrongPolymer": None if lineage is None else
                         sorted(i for i in got[arm] if subjects.get(i) and subjects[i] not in lineage)}
        value[scope] = part
    return value


def subjects_of(root, ids):
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    found = dict(db.execute("SELECT id, subject FROM findings WHERE id IN (%s)" % ",".join("?" * len(ids)), list(ids)))
    db.close()
    return found


def rows():
    """One row per withheld question whose pooled findings are all judged."""
    made = roots()
    value = []
    for question in withheld():
        target = folder() / "searches" / (question["id"] + ".json")
        if not target.exists():
            continue
        stored = read_json(target)
        relevant = verdicts(question["id"])
        every = pool(stored)
        if any(i not in relevant for i in every):
            continue
        got = measures(stored, relevant, subjects_of(made["Oplus"], every) if every else {},
                       asked_lineage(question, made["Oplus"]))
        value.append(dict({k: question.get(k) for k in ("id", "set", "kind", "group", "stratum")},
                          issuedRead=stored.get("issuedRead", False), **got))
    return value


def aggregate(chosen):
    """Per scope: questions, mean and pooled recall per arm, lost and gained relevant results with lost as a share of
    B's relevant returned results, and wrong-polymer and unfiled returned results per arm."""
    value = {"questions": len(chosen)}
    for scope in SCOPES:
        parts = [r[scope] for r in chosen if r.get(scope)]
        if not parts:
            continue
        with_relevant = [(r, r[scope]) for r in chosen if r.get(scope) and r["relevant"]]
        part = {"questions": len(parts), "withRelevant": len(with_relevant),
                "lost": sum(len(p["lost"]) for p in parts), "gained": sum(len(p["gained"]) for p in parts)}
        for arm in ARMS:
            recalls = [p[arm]["recall"] for _, p in with_relevant]
            judged = [p[arm]["wrongPolymer"] for p in parts if p[arm]["wrongPolymer"] is not None]
            part[arm] = {"meanRecall": statistics.mean(recalls) if recalls else None,
                         "pooledRecall": (sum(p[arm]["relevantFound"] for _, p in with_relevant)
                                          / sum(r["relevant"] for r, _ in with_relevant)) if with_relevant else None,
                         "relevantFound": sum(p[arm]["relevantFound"] for p in parts),
                         "returned": sum(p[arm]["returned"] for p in parts),
                         "wrongPolymer": sum(len(w) for w in judged), "polymerKnown": len(judged),
                         "unfiled": sum(p[arm]["unfiled"] for p in parts)}
        b = part["B"]["relevantFound"]
        part["lostShare"] = part["lost"] / b if b else None
        value[scope] = part
    return value


# ----- hops removed -----

def screen_answers():
    """The screen's B answers by question id, normalized as mining normalizes an answer (`cases.screen_answers`: its
    steps in order, each store search joined to its trace event); no other arm's items are read."""
    base = pins.FOLDERS["screen"]
    layout = base / "experiment.json"
    return cases.screen_answers([base / name for name in read_json(layout)["folders"]] if layout.exists() else [])


def hop_rows(made=None, build=None, answers=None):
    """Hops removed (plan, "Measures": B's avoidable hops whose target the refined search returns at the earlier step),
    one row per withheld question the screen's B arm answered: its hops classed on B's copy of KF (the seed graph) by
    `mine.Miner.classify`, with the question file's polymer ids; its held-unreached web and store hops split into
    reachable or not on O+'s copy of KF-refined (release O), and each reachable one attributed to the edit groups that
    reach it alone (`overlay.root_for` per group, `build`; "joint" if none does)."""
    pins.frozen()  # the refined root is searched only by the code under test
    made = made or roots()
    build = functools.lru_cache(maxsize=None)(build or overlay.root_for)  # each group's root is looked up once
    answers = screen_answers() if answers is None else answers
    miner, value = mine.Miner(made[pins.B]), []
    for question in withheld():
        if question["id"] not in answers:
            continue
        answer = dict(answers[question["id"]], polymerIds=question.get("polymerIds") or [])
        hops = miner.classify(answer, made[pins.OPLUS], build)
        held = [h for h in hops if h["class"] == "held-unreached"]
        row = dict({k: question.get(k) for k in ("id", "set", "kind", "group", "stratum")}, answer=answer["id"],
                   hops=len(hops), byClass=dict(collections.Counter("%s:%s" % (h["kind"], h["class"]) for h in hops)),
                   byGroup=dict(collections.Counter(g for h in held for g in h.get("groups") or [])),
                   heldUnreached=[{k: h.get(k) for k in ("id", "kind", "steps", "refined", "groups")} for h in held])
        for kind in ("web", "store"):
            row[kind] = {"heldUnreached": sum(h["kind"] == kind for h in held),
                         "reachable": sum(h["kind"] == kind and h["refined"] == "reachable" for h in held)}
        value.append(row)
    return value


def hop_totals(chosen):
    """Summed over questions: held-unreached web and store hops, how many the refined ontology makes reachable (and
    their share), and the reachable ones by edit group."""
    value = {"questions": len(chosen), "byGroup": dict(sum((collections.Counter(r["byGroup"]) for r in chosen),
                                                           collections.Counter()))}
    for kind in ("web", "store", "all"):
        held = sum(r[k]["heldUnreached"] for r in chosen for k in (("web", "store") if kind == "all" else (kind,)))
        reached = sum(r[k]["reachable"] for r in chosen for k in (("web", "store") if kind == "all" else (kind,)))
        value[kind] = {"heldUnreached": held, "reachable": reached, "share": reached / held if held else None}
    return value


# ----- report -----

def subsets(found):
    """Rows by group: all, each set, and each stratum within a set (each group within L)."""
    groups = collections.OrderedDict(all=found)
    for name in pins.SETS:
        chosen = [r for r in found if r["set"] == name]
        groups[name] = chosen
        key = "group" if name == "L" else "stratum"
        for sub in dict.fromkeys(r[key] for r in chosen):
            groups["%s/%s" % (name, sub)] = [r for r in chosen if r[key] == sub]
    return groups


def report(build=None):
    """rows.json (one row per judged question), hops.json (one row per question the screen's B arm answered) and
    report.json and report.md: every measure per set, per stratum within a set and per L group, and overall, and the
    hops removed (`hop_rows`) the same way."""
    found, hopped = rows(), hop_rows(build=build)
    value = {"at": now(), "questions": len(withheld()), "judged": len(found), "limit": LIMIT, "poolLimit": POOL,
             "arms": {arm: pins.LABELS.get(arm, arm) for arm in ARMS},
             "groups": {name: aggregate(chosen) for name, chosen in subsets(found).items()},
             "hopsRemoved": {name: hop_totals(chosen) for name, chosen in subsets(hopped).items()}}
    atomic_json(folder() / "rows.json", found, private=True)
    atomic_json(folder() / "hops.json", hopped, private=True)
    atomic_json(folder() / "report.json", value, private=True)
    atomic_bytes(folder() / "report.md", markdown(value).encode("utf-8"), private=True)
    return value


def markdown(value):
    fmt = lambda x: "–" if x is None else "%.2f" % x if isinstance(x, float) else str(x)
    lines = ["# Lookup: B (KF, seed graph) against O+ (KF-refined, release O)", "",
             "%d of %d withheld questions judged. Recall counts the relevant findings an arm's searches return (the "
             "canonical query at limit %d, the issued calls as recorded; same-source and linked findings included) "
             "over the relevant findings in the question's pool (everything either arm returned, and the same queries "
             "at limit %d). Lost: relevant, returned by B's call and not by O+'s for the same query and limit; the "
             "share is of B's relevant returned results." % (
                 value["judged"], value["questions"], value["limit"], value["poolLimit"]), ""]
    for scope in SCOPES:
        lines += ["## %s queries" % scope, "", "| Group | Questions | Recall B (mean) | Recall O+ (mean) | Recall B "
                  "(pooled) | Recall O+ (pooled) | Lost | Lost share | Gained | Wrong polymer B | Wrong polymer O+ |",
                  "| --- |" + " ---: |" * 10]
        for name, got in value["groups"].items():
            part = got.get(scope)
            if not part:
                continue
            cells = [part["questions"], part["B"]["meanRecall"], part["Oplus"]["meanRecall"], part["B"]["pooledRecall"],
                     part["Oplus"]["pooledRecall"], part["lost"], part["lostShare"], part["gained"],
                     part["B"]["wrongPolymer"], part["Oplus"]["wrongPolymer"]]
            lines.append("| %s | %s |" % (name, " | ".join(fmt(c) for c in cells)))
        lines.append("")
    lines += ["## Hops removed", "", "B's held-unreached hops (a page or store search reaching a saved finding no "
              "earlier search returned on KF) and how many of them O+'s search returns at an earlier step; reachable "
              "ones by the edit group that reaches them alone.", "",
              "| Group | Questions | Web held | Web reachable | Store held | Store reachable | Share | By edit group |",
              "| --- |" + " ---: |" * 6 + " --- |"]
    for name, got in value.get("hopsRemoved", {}).items():
        cells = [got["questions"], got["web"]["heldUnreached"], got["web"]["reachable"], got["store"]["heldUnreached"],
                 got["store"]["reachable"], got["all"]["share"]]
        groups = ", ".join("%s %d" % item for item in sorted(got["byGroup"].items())) or "–"
        lines.append("| %s | %s | %s |" % (name, " | ".join(fmt(c) for c in cells), groups))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["judge", "report"])
    parser.add_argument("--canonical-only", action="store_true",
                        help="judge the canonical queries of questions the screen has not answered yet")
    parser.add_argument("--hours", type=float, default=12)
    args = parser.parse_args()
    out = judge(hours=args.hours, canonical_only=args.canonical_only) if args.command == "judge" else report()
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:20000])
