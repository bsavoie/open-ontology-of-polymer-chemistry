"""Part C's case studies: which withheld questions each case C1-C8 runs (`ontology-refinement-plan.md`, "Case studies:
where the ontology matters, and where it does not"). No engines.

    python -B studies/macromolecules/refinement/cases.py select [--refined ROOT] [--screen DIR] [--base ROOT]

Cases are chosen by mechanism only: the offline replay under the baseline workspace (KF, seed graph) and the refined
one (KF, release O, the annotated store copy and its overlay tables), and the screen's baseline arm `B` (driver items in
the shard folders `screen/s<k>`, the same format as Part A's). Only the `B` arm's items are read; the refined arm's
(`Oplus`) outcome never is. Questions come from the withheld sets (`questions/H.json`, `N.json`, `L.json`, each
question's text under `question`). For each question the replayed queries are its canonical query (material plus
property, else its text) and the queries B actually issued. Relevance is `mine.Miner.relevant`, judged once per
question for both arms' results: the question's polymers as either graph resolves them plus the polymer ids the
question file records, and a finding counts when it is relevant as either store files it (so a finding a refined
annotation files under another polymer still counts as relevant for the baseline).

The rules, as committed before the screen:

- C1 Unknown name: the question names a polymer the seed graph does not know (a material, else its text, resolves to
  no polymer on the baseline), the refined graph resolves it, and in replay the refined workspace returns relevant
  findings the baseline did not.
- C2 Linked sources: B's trace has a held-unreached hop that is reachable on the refined workspace through a source
  link: attributed to the `source-link` edit group when a group builder is given (`mine.Miner.classify`), else a
  reachable hop whose target source has a link in the refined store's `source_links`.
- C3 Family: the question's polymer is known to the seed, the refined graph's lineage of it is larger (an approved
  family link), and the refined workspace returns relevant findings, filed under a polymer only that larger lineage
  holds, that the baseline did not.
- C4 Property wording: the refined store has property terms, the refined workspace returns relevant findings the
  baseline did not, and the question words the property as those findings do not (no shared significant word); with a
  group builder, the `property-term` group alone must return some of them.
- C5 Accumulation alone: the baseline's canonical search returns relevant findings, and every replayed query returns
  exactly the same ids on both workspaces.
- C6 Nothing saved: the base store holds no finding relevant to the question under either ontology.
- C7 Ontology without knowledge: C1-C3's questions answered on K0 (O0 against B0): the first pick of C1, C2 and C3,
  reused, not drawn again.
- C8 Risk: for some replayed query, the refined call returns a finding filed under a polymer outside the question's
  lineage that the baseline's call did not, or no longer returns a relevant finding the baseline's call returned
  ("the first ten" is what a call returns, as everywhere in Part C: `mine.returned`).

Each case's qualifying questions are put in a fixed order (by set and id) and shuffled with the seed
`pins.SELECTION_SEED` (`oopc-refinement-cases-2026-10-21`) and the case's name; the first three not already picked by an
earlier case (in the order C1-C6, C8) are taken. `cases/selection.json` records each pick with its set, text and the
mechanism that qualified it, how many qualified, and every case with fewer than three (the plan writes the rest for the
purpose). `select` runs only on the code under test (`pins.frozen`); the command decides C2 and C4 edit group by edit
group (`overlay.root_for`).

For each case short of three (not C7), `select` also writes `cases/pairs.json`, what `questions.py write-C` writes the
missing questions from: {"cases": {case: [{"material", "property", "polymerIds", "replay", "ask"?}]}}, pairs of a
material and a property whose canonical replay shows the case's mechanism by the case's own rule (`pairs`). Candidates
come from what the refined ontology changes or leaves alone (`candidates`); C2's, which no trace of B's backs yet, is
shown by the canonical calls alone (`linked`); a pair a withheld question already asks is passed over.
"""
import argparse, collections, functools, json, random, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import mine, overlay, pins  # noqa: E402
from refinement.questions import SPARE  # noqa: E402  (pairs write-C offers a case beyond those it needs)
from oopc import knowledge  # noqa: E402
from oopc.util import atomic_json, read_json, resolve_release  # noqa: E402

CASES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")
DRAWN = ("C1", "C2", "C3", "C4", "C5", "C6", "C8")  # the order picks are made in; C7 reuses C1-C3's
PER_CASE = 3
SHOWN = 5  # finding ids shown in a reason
PAIRS_TRIED = 40  # candidate pairs a short case's rule is tried on, in seeded order
RULES = {
    "C1": "names a polymer the seed does not know; the refined graph resolves it; refined replay returns relevant "
          "findings the baseline did not",
    "C2": "B's trace has a held-unreached hop reachable on the refined workspace through a source link",
    "C3": "the refined graph's lineage of the question's polymer is larger, and refined replay returns relevant "
          "findings filed under a polymer only it holds",
    "C4": "property terms in the overlay; refined replay returns relevant findings the baseline did not, worded unlike "
          "the question's property",
    "C5": "the baseline's canonical search returns relevant findings and refined replay changes no result",
    "C6": "the base holds no relevant finding under either ontology",
    "C7": "C1-C3's questions, compared on K0 (O0 against B0)",
    "C8": "refined replay returns another polymer's finding the baseline did not, or no longer a relevant one",
}


def withheld_questions(folder=None):
    """The withheld questions by set, as `questions.py` writes them."""
    found = {}
    for name in pins.SETS:
        path = pins.set_path(name, folder)
        if path.exists():
            value = read_json(path)
            items = value.get("questions", []) if isinstance(value, dict) else value
            found[name] = [dict(q, set=q.get("set") or name) for q in items
                           if isinstance(q, dict) and q.get("question")]
    return found


def screen_answers(folders, arm=pins.B):
    """The baseline arm's answers in the screen's shard folders, by question id: no other arm's items are read."""
    found = {}
    for folder in folders:
        if (Path(folder) / "plan.json").exists():
            for record in mine.driver_answers(folder, origin="screen", arms=[arm], web=None):
                found[record["questionId"]] = record
    return found


def subject(question):
    """A withheld question as `mine.Miner.context` reads it."""
    materials = question.get("materials") or ([question["material"]] if question.get("material") else [])
    ids = question.get("polymerIds") or question.get("polymers") or []
    return {"id": question["id"], "question": question["question"], "materials": materials,
            "property": question.get("property"), "polymerIds": [i for i in ids if isinstance(i, str)]}


def canonical(question):
    """The canonical query: material plus property, else the question's text."""
    materials = question.get("materials") or ([question["material"]] if question.get("material") else [])
    if materials and question.get("property"):
        return " ".join([materials[0], question["property"]])
    return question["question"]


def evidence(miner, question, base, refined, answer=None, build=None):
    """The mechanism of one question: what each case's rule reads."""
    record = subject(question)
    queries = [(canonical(question), None)] + [(s["q"], s.get("limit")) for s in (answer or {}).get("steps", [])
                                               if mine.replayable(s)]
    queries = list(dict.fromkeys(queries))
    store_base, store_ref = miner.store_of(base), miner.store_of(refined)
    ctx_base, ctx_ref = miner.context(record, base), miner.context(record, refined)
    ctx = dict(ctx_ref, lineage=ctx_ref["lineage"] | ctx_base["lineage"], names=ctx_ref["names"] | ctx_base["names"])
    relevant = lambda fid: miner.relevant(fid, ctx, store_base) or miner.relevant(fid, ctx, store_ref)  # noqa: E731
    got = {"base": [], "refined": []}
    for q, limit in queries:
        got["base"].append(mine._replayed(base, q, limit))
        got["refined"].append(mine._replayed(refined, q, limit))
    found = {arm: {f for r in got[arm] for f in r["findings"] if relevant(f)} for arm in got}
    new = sorted(found["refined"] - found["base"])
    text = " ".join(record["materials"]) or record["question"]
    named = {"base": mine._ids(base, text, bool(not record["materials"])),
             "refined": mine._ids(refined, text, bool(not record["materials"]))}
    lineage = {"base": knowledge.lineage(str(Path(base).resolve()), set(named["base"])),
               "refined": knowledge.lineage(str(Path(refined).resolve()), set(named["refined"]))}
    value = {"id": question["id"], "set": question["set"], "queries": [q for q, _ in queries],
             "relevant": {arm: sorted(found[arm]) for arm in found}, "newRelevant": new}
    # C1: a polymer the seed does not know, resolved by the refined graph, with relevant findings only it returns.
    unknown = bool(ctx_base["unresolved"]) or not named["base"]
    value["C1"] = bool(unknown and named["refined"] and not ctx_ref["unresolved"] and new)
    # C2: a held-unreached hop of B's that a source link makes reachable.
    hops = []
    if answer:
        for hop in miner.classify(answer, refined, build):
            if hop.get("refined") != "reachable":
                continue
            keys = set(hop.get("target", {}).get("held") or []) | {
                miner.store.findings[f]["key"] for f in hop.get("newRelevant") or [] if f in miner.store.findings}
            linked = "source-link" in hop["groups"] if "groups" in hop else bool(keys & set(store_ref.linked))
            if linked:
                hops.append({"hop": hop["hop"], "kind": hop["kind"], "steps": hop["steps"], "target": sorted(keys)})
    value["C2"], value["linkedHops"] = bool(hops), hops
    # C3: a family link widens the known polymer's lineage, and what it adds is found.
    added = lineage["refined"] - lineage["base"]
    family = [f for f in new if (store_ref.findings.get(f) or {}).get("subject") in added]
    value["C3"], value["familyFindings"] = bool(named["base"] and added and family), family[:SHOWN]
    # C4: property terms join a wording the question does not use.
    worded = [f for f in new if not mine.property_words(ctx["property"])
              & mine.property_words((store_ref.findings.get(f) or {}).get("property"))]
    if worded and build is not None:
        alone = build(frozenset(["property-term"]))
        reached = {f for q, limit in queries for f in mine._replayed(alone, q, limit)["findings"]}
        worded = [f for f in worded if f in reached]
    value["C4"], value["wordedFindings"] = bool(store_ref.terms and worded), worded[:SHOWN]
    # C5: the seed already finds it, and the refined ontology changes nothing.
    value["C5"] = bool(any(relevant(f) for f in got["base"][0]["findings"])
                       and all(b["ids"] == r["ids"] for b, r in zip(got["base"], got["refined"])))
    # C6: nothing relevant is saved at all.
    value["C6"] = not any(relevant(f) for f in store_ref.findings)
    # C8: the refined call returns another polymer's finding the baseline's did not, or no longer a relevant one.
    risks = []
    for (q, _), b, r in zip(queries, got["base"], got["refined"]):
        first, then = b["findings"], r["findings"]
        for f in then:
            filed = (store_ref.findings.get(f) or {}).get("subject")
            if f not in first and filed and filed not in ctx["lineage"]:
                risks.append({"query": q, "entered": f, "filedUnder": filed})
        risks += [{"query": q, "left": f} for f in first if f not in then and relevant(f)]
    value["C8"], value["risks"] = bool(risks), risks[:SHOWN]
    return value


def _reason(case, row):
    reason = {"rule": RULES[case], "queries": row["queries"][:SHOWN]}
    if case in ("C1", "C3", "C4"):
        reason["newRelevant"] = row["newRelevant"][:SHOWN]
    reason.update({"C2": {"linkedHops": row["linkedHops"]}, "C3": {"familyFindings": row["familyFindings"]},
                   "C4": {"wordedFindings": row["wordedFindings"]}, "C5": {"relevant": row["relevant"]["base"][:SHOWN]},
                   "C8": {"risks": row["risks"]}}.get(case, {}))
    return reason


# ----- pairs for questions written for the purpose -----

def _graph(root):
    """A workspace graph's names (lower case) -> polymer ids, each name as written, and the polymers' labels."""
    groups = knowledge.polymer_aliases(str(root))
    spelled = {}
    for others in groups.values():
        for name in others:
            spelled.setdefault(name.lower(), name)
    return (knowledge._POLYMER_IDS.get(str(resolve_release(root)), {}), spelled,
            knowledge._graph_families(str(root))[2])


def _held(root):
    """The findings annotated to each property term in the store of `root` (read only; none without the tables)."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = db.execute("SELECT term, finding_id FROM finding_terms").fetchall() if "finding_terms" in tables else []
    finally:
        db.close()
    found = collections.defaultdict(set)
    for term, finding in rows:
        found[term].add(finding)
    return found


def candidates(miner, base, refined, case):
    """Pairs (material, property, polymer ids, the link for C2) that may show `case`'s mechanism, before its rule
    decides: materials from what the refined ontology changes (C1 a name only it knows; C2 the polymer of a finding
    from a linked source; C3 a polymer whose lineage grew; C4 a polymer with findings annotated to a property term,
    asked by the term's names; C8 a polymer whose search can change) or leaves alone (C5), or any polymer (C6); each
    asked for the property wordings of the findings filed under its refined lineage, then the store's commonest."""
    diff = mine.difference(miner, refined)
    ids_r, spelled, labels = _graph(refined)
    ids_b, _, labels_b = _graph(base)
    store = miner.store_of(refined)
    filed, everywhere = collections.defaultdict(collections.Counter), collections.Counter()
    for f in store.findings.values():
        if f["status"] != knowledge.UNSUPPORTED and f["property"]:
            everywhere[f["property"]] += 1
            if f["subject"]:
                filed[f["subject"]][f["property"]] += 1

    def wordings(polymers):
        under = sum((filed[p] for p in knowledge.lineage(str(refined), set(polymers))), collections.Counter())
        return list(dict.fromkeys([w for w, _ in under.most_common(3)] + [w for w, _ in everywhere.most_common(5)]))
    touched = set(diff["polymers"]) | {p for n in diff["names"] for p in ids_r.get(n, set()) | ids_b.get(n, set())}
    found = []
    if case == "C1":
        for name in diff["names"]:
            new = sorted(ids_r.get(name, set()))
            if new and not ids_b.get(name):
                found += [(spelled.get(name, name), w, new, None) for w in wordings(new)]
    elif case == "C2":
        for a, _, b in diff["links"]:
            for near, far in ((a, b), (b, a)):
                for fid in store.by_source.get(far, []):
                    f = store.findings[fid]
                    if f["subject"] in labels and f["status"] != knowledge.UNSUPPORTED and f["property"]:
                        found.append((labels[f["subject"]], f["property"], [f["subject"]], (near, far, fid)))
    elif case == "C3":
        for p in diff["lineage"]:
            grown = knowledge.lineage(str(refined), {p}) - knowledge.lineage(str(base), {p})
            if p in labels_b and grown:
                found += [(labels[p], w, [p], None) for w in wordings(grown)]
    elif case == "C4":
        for term in store.terms:
            names = mine._terms(term["names"])
            for subject in sorted({store.findings[f]["subject"] for f in _held(refined).get(term["term"], ())
                                   if f in store.findings and store.findings[f]["subject"] in labels}):
                found += [(labels[subject], n, [subject], None) for n in names]
    elif case in ("C5", "C6", "C8"):
        chosen = {"C5": sorted(set(labels) - touched), "C6": sorted(labels), "C8": sorted(touched & set(labels))}
        found += [(labels[p], w, [p], None) for p in chosen[case] for w in wordings([p])]
    return found


def linked(miner, base, refined, material, prop, link):
    """C2's replay for a pair: the canonical call on the base returns a finding from the near source of a link and not
    the far source's finding, which the refined call returns (freeze-3 follows the link). Without a screen answer,
    this stands for B's trace."""
    near, far, fid = link
    query = "%s %s" % (material, prop)
    got_b, got_r = mine.returned(base, query), mine.returned(refined, query)
    from_near = [f for f in got_b if (miner.store.findings.get(f) or {}).get("key") == near]
    if from_near and fid not in got_b and fid in got_r:
        return {"rule": RULES["C2"], "queries": [query], "linkedFrom": near, "linkedTo": far,
                "baseReturned": from_near[:SHOWN], "refinedReturned": [fid]}
    return None


ASK = {"C1": "name the material only by this name", "C4": "word the property exactly as given"}


def pairs(selection, questions, base, refined, *, miner, build=None, out=None, seed=pins.SELECTION_SEED):
    """`cases/pairs.json` for `questions.py write-C`: for each case short of three (not C7, which reuses C1-C3), pairs
    of a material and a property whose replay shows the case's mechanism, by the case's own rule (`evidence`; for C2,
    `linked`), as many as the case is short plus write-C's SPARE: {"cases": {case: [{"material", "property",
    "polymerIds", "replay", "ask"?}]}}. Candidates (`candidates`) are tried in an order seeded by the case's name, at
    most PAIRS_TRIED of them; a pair a withheld question already asks (the same polymers and property) is passed
    over."""
    asked = set()
    for q in (q for name in pins.SETS for q in questions.get(name, [])):
        for material in subject(q)["materials"] or [q["question"]]:
            asked.add((frozenset(mine._ids(refined, material, False)) or material.lower(),
                       mine._norm(q.get("property"))))
    value = {"seed": seed, "cases": {}}
    for case, short in sorted((selection.get("shortfalls") or {}).items()):
        if case == "C7" or not short:
            continue
        order = list(dict.fromkeys((m, p, tuple(ids), link)
                                   for m, p, ids, link in candidates(miner, base, refined, case)
                                   if (frozenset(ids), mine._norm(p)) not in asked))
        random.Random("%s:pairs:%s" % (seed, case)).shuffle(order)
        chosen = []
        for material, prop, ids, link in order[:PAIRS_TRIED]:
            if case == "C2":
                replay = linked(miner, base, refined, material, prop, link)
            else:
                question = {"id": "pair", "set": "C", "question": "%s %s" % (material, prop), "materials": [material],
                            "property": prop, "polymerIds": list(ids)}
                row = evidence(miner, question, base, refined, None, build)
                replay = _reason(case, row) if row[case] else None
            if replay:
                chosen.append(dict({"material": material, "property": prop, "polymerIds": list(ids),
                                    "replay": replay}, **({"ask": ASK[case]} if case in ASK else {})))
                if len(chosen) == short + SPARE:
                    break
        value["cases"][case] = chosen
    atomic_json(Path(out or pins.folder("cases")) / "pairs.json", value, private=True)
    return value


def select(questions, base, refined, *, answers=None, build=None, out=None, miner=None, seed=pins.SELECTION_SEED):
    """Pick PER_CASE questions per case by the rules above; write `cases/selection.json` (to `out`) and return it.

    `questions`: {set: [question]} (each with id and question). `answers`: B's normalized answers by question id
    (`screen_answers`). `build`: a callable from a frozenset of edit groups to a workspace root (`overlay.root_for`;
    without it C2 falls back to a reachable hop whose target has any link, and C4 is not tested group by group). The
    refined root is searched only by the code under test (`pins.frozen`)."""
    pins.frozen()
    answers = answers or {}
    miner = miner or mine.Miner(base)
    flat = sorted((q for name in pins.SETS for q in questions.get(name, [])),
                  key=lambda q: (pins.SETS.index(q["set"]), q["id"]))
    rows = {(q["set"], q["id"]): evidence(miner, q, base, refined, answers.get(q["id"]), build) for q in flat}
    texts = {(q["set"], q["id"]): q["question"] for q in flat}
    picked, used, qualifying = {}, set(), {}
    for case in DRAWN:
        order = [key for key in rows if rows[key][case]]
        qualifying[case] = len(order)
        random.Random("%s:%s" % (seed, case)).shuffle(order)
        picked[case] = []
        for key in order:
            if key in used:
                continue
            used.add(key)
            picked[case].append({"id": key[1], "set": key[0], "question": texts[key],
                                 "reason": _reason(case, rows[key])})
            if len(picked[case]) == PER_CASE:
                break
    picked["C7"] = [dict(picked[c][0], reason={"rule": RULES["C7"], "from": c}, reuses=c)
                    for c in ("C1", "C2", "C3") if picked[c]]
    qualifying["C7"] = len(picked["C7"])
    value = {"seed": seed, "rules": RULES, "cases": {c: picked[c] for c in CASES}, "qualifying": qualifying,
             "shortfalls": {c: PER_CASE - len(picked[c]) for c in CASES if len(picked[c]) < PER_CASE},
             "questions": {name: len(questions.get(name, [])) for name in pins.SETS},
             "screenAnswers": len(answers), "groupBuilder": build is not None,
             "inputs": {"base": driver.fingerprint(base), "refined": driver.fingerprint(refined),
                        "refinedLinks": len(miner.store_of(refined).links),
                        "refinedTerms": len(miner.store_of(refined).terms)},
             "meta": mine.meta()}
    out = Path(out) if out else pins.folder("cases")
    atomic_json(out / "selection.json", value, private=True)
    found = pairs(value, questions, base, refined, miner=miner, build=build, out=out, seed=seed)
    value["pairs"] = {case: len(offered) for case, offered in found["cases"].items()}
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("select",))
    parser.add_argument("--refined", help="the refined workspace root (default: the built KF-refined, release O)")
    parser.add_argument("--base", help="the baseline workspace root (default: mine's copy of KF)")
    parser.add_argument("--screen", help="the screen folder holding the shards s<k> (default: the run folder's)")
    args = parser.parse_args(argv)
    pins.frozen()
    base = Path(args.base) if args.base else mine.base_root(pins.folder("mine"))
    refined = Path(args.refined) if args.refined else pins.store("KF-refined")
    screen = Path(args.screen) if args.screen else pins.FOLDERS["screen"]
    folders = sorted(p for p in screen.glob("s*") if (p / "plan.json").exists()) if screen.exists() else []
    value = select(withheld_questions(), base, refined, answers=screen_answers(folders),
                   build=functools.lru_cache(maxsize=None)(overlay.root_for))  # each group root looked up once
    print(json.dumps({"qualifying": value["qualifying"], "shortfalls": value["shortfalls"],
                      "cases": {c: [p["id"] for p in v] for c, v in value["cases"].items()}}, indent=1))


if __name__ == "__main__":
    main()
