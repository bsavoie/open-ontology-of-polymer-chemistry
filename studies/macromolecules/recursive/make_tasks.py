"""Questions for test 2, the recursive test (owner-approved 2026-10-13). Deterministic; private.

- dev.json (30): the set each proposed prompt change is judged on: 10 near, 10 mid and 10 far, built like test 1's
  held-out set (near: a campaign polymer and property that left findings, from another angle; mid: a polymer asked
  about at least three times with a property never asked for it; far: a polymer no saved finding is about), and
  disjoint from it in polymers.
- rounds.json (3 x 100): new tasks through the normal loop, mixed as in the campaign (30 property, 15 method,
  15 effect, 10 assessment, 10 comparison, 20 revisits: exact, paraphrase, sibling of a campaign task or an earlier
  round's). No round task asks a held-out or dev polymer-property pair, and none names a held-out or dev far polymer,
  so the strata keep their meaning as the store grows.

Ran in `.oopc/loop/harness/2026-10-recursive/`, where it wrote dev.json and rounds.json (and still does); moved to the
repository on 2026-10-13 unchanged except imports and paths (the freeze worktree is now common.CODE). On 2026-10-18 the
round draw was split into helpers, unchanged in what it draws (test_recursive.py regenerates both files byte for byte),
so the five fresh restarts (`docs/exec-plans/active/restart-study-plan.md`) draw their tasks the same way:

- `--restart N` writes restart N's rounds.json (5 x 100, seed `oopc-restart-2026-10-18-R<N>`) into its folder
  (`.oopc/loop/harness/2026-10-restarts/R<N>/`, or `--out`): per round 30 property, 15 method, 15 effect,
  10 assessment, 10 comparison and 20 revisits of the restart's own earlier tasks (in round 1, of round 1's first asks,
  each placed after its parent), 12 sampled for a whole-answer check. Four first asks a round are the campaign
  questions test 1's near held-out questions were drawn from (owner, 2026-10-18), counted under their own kinds. A
  restart starts empty, so campaign questions are not otherwise excluded; what is excluded, and this exception, is
  decided in one place, `restart_exclusions`.

    python make_tasks.py                      # test 2's dev.json and rounds.json, as they ran
    python make_tasks.py --restart 3 [--out FOLDER]
"""
import argparse, hashlib, importlib.util, json, random, re, sqlite3, sys, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-recursive")
CAMPAIGN = run_dir("2026-10-campaign")
ABLATION = run_dir("2026-10-ablation")
RESTARTS = run_dir("2026-10-restarts")
from oopc import knowledge  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bank = _load("bank", STUDY / "campaign" / "make_questions.py")
heldout_maker = _load("heldout_maker", STUDY / "ablation" / "make_heldout.py")
SEED = "oopc-recursive-2026-10-13"
STORE = ABLATION / "workspaces/K3"  # the store test 2 starts from
ROUNDS = {r: dict(property=30, method=15, effect=15, assessment=10, comparison=10, revisits=20) for r in (1, 2, 3)}
CHECKS_PER_ROUND = 12
DEV_FAR = [  # no saved finding names these, their families or members (checked below with the researcher's search)
    ("alkyd resin", "glass transition temperature of a cured film", "property"),
    ("polyacetylene", "electrical conductivity after doping", "property"),
    ("polysulfide rubber", "volume swell in fuel", "method"),
    ("tetrafluoroethylene-propylene elastomer (FEPM)", "tensile strength and elongation at break", "property"),
    ("perfluoroelastomer (FFKM)", "compression set at elevated temperature", "property"),
    ("carrageenan", "gel strength or gelation temperature", "method"),
    ("poly(p-phenylene vinylene) (PPV)", "optical absorption maximum or band gap", "property"),
    ("trans-1,4-polyisoprene (gutta-percha)", "melting temperature and crystallinity by DSC", "method"),
    ("novoloid fiber", "limiting oxygen index", "property"),
    ("polyoxadiazole fiber", "thermal decomposition temperature by TGA", "method"),
]


def task_id(name, seed=SEED):
    return hashlib.md5((seed + "-" + name).encode()).hexdigest()


def found(question):
    result = knowledge.search(STORE, question, limit=25, compact=True)
    return sum(len(result[g]) for g in ("reviewed", "added", "unreviewed"))


def dev_set(rng, campaign, heldout):
    phrases = heldout_maker.PHRASES
    db = sqlite3.connect(knowledge.database(STORE).as_uri() + "?mode=ro", uri=True)
    deposits = dict(db.execute("SELECT question_id, findings FROM deposits"))
    db.close()
    category = dict(bank.OLD)
    for name, members in bank.NEW.items():
        category.update({m: name for m in members})
    taken = {h["material"] for h in heldout}
    pairs = {(q["materials"][0], q["property"]) for q in campaign if len(q["materials"]) == 1}
    counts = {}
    for q in campaign:
        for m in q["materials"]:
            counts[m] = counts.get(m, 0) + 1
    rows = []
    single = [q for q in campaign if len(q["materials"]) == 1 and not q["revisit"] and q["kind"] in
              ("property", "method", "assessment", "effect") and (deposits.get(q["taskId"]) or 0) >= 3
              and q["materials"][0] in category and q["materials"][0] not in taken]
    rng.shuffle(single)
    for q in single:
        m = q["materials"][0]
        if m in taken or sum(r["stratum"] == "near" for r in rows) == 10:
            continue
        kind = "method" if q["kind"] == "property" else "property"
        rows.append(dict(stratum="near", kind=kind, material=m, property=q["property"], parent=q["taskId"],
                         question=phrases[kind].format(p=q["property"], m=m)))
        taken.add(m)
    polymers = [m for m, n in counts.items() if n >= 3 and m in category and m not in taken]
    rng.shuffle(polymers)
    for m in polymers:
        if sum(r["stratum"] == "mid" for r in rows) == 10:
            break
        fresh = [p for p in bank.CATEGORIES[category[m]][0] if (m, p) not in pairs]
        if not fresh:
            continue
        p = rng.choice(fresh)
        kind = "property" if sum(r["stratum"] == "mid" for r in rows) % 5 < 3 else "method"
        rows.append(dict(stratum="mid", kind=kind, material=m, property=p, question=phrases[kind].format(p=p, m=m)))
        taken.add(m)
    for m, p, kind in DEV_FAR:
        rows.append(dict(stratum="far", kind=kind, material=m, property=p, question=phrases[kind].format(p=p, m=m)))
    for r in rows:
        r["question"] = r["question"].replace(" of PEI,", " of polyetherimide (PEI),").replace(" for PEI,", " for polyetherimide (PEI),")
        r.update(id=task_id("dev-" + r["question"]), depth="standard", findingsFound=found(r["question"]))
    assert [sum(r["stratum"] == s for r in rows) for s in ("near", "mid", "far")] == [10, 10, 10], "dev strata incomplete"
    assert all(r["findingsFound"] == 0 for r in rows if r["stratum"] == "far"), \
        [(r["material"], r["findingsFound"]) for r in rows if r["stratum"] == "far" and r["findingsFound"]]
    assert all(r["findingsFound"] > 0 for r in rows if r["stratum"] == "near")
    return rows


def _category():
    category = dict(bank.OLD)
    for name, members in bank.NEW.items():
        category.update({m: name for m in members})
    return category


def _pools(rng, category, blocked, far, used_pairs=frozenset(), used_effects=frozenset(), used_groups=frozenset(),
           groups_needed=40, screen_groups=False):
    """The shuffled pools first asks are drawn from: polymer-property pairs, effects and comparison groups that are not
    `blocked(material, property)`, used before, or about a `far` polymer. The bank's comparison groups are screened
    with `blocked` only when `screen_groups` (test 2 drew one of them; a restart can draw them all); new groups, made
    until there are `groups_needed`, compare three polymers of one category on one of that category's properties, as
    the bank's do."""
    pairs = [(m, p) for m, c in category.items() for p in bank.CATEGORIES[c][0]
             if (m, p) not in used_pairs and not blocked(m, p) and m not in far]
    effects = [(m, f, bank.CATEGORIES[c][0][i]) for m, c in category.items() if m not in far
               for f, fits in bank.CATEGORIES[c][1].items() for i in fits
               if (m, f, bank.CATEGORIES[c][0][i]) not in used_effects and not blocked(m, bank.CATEGORIES[c][0][i])]
    groups = [(tuple(ms), p) for ms, props in bank.COMPARISONS for p in props
              if (tuple(ms), p) not in used_groups and not set(ms) & far
              and not (screen_groups and any(blocked(m, p) for m in ms))]
    # The campaign used 83 of the bank's 84 comparison groups; new ones compare three polymers of one category on one
    # of that category's properties, as the bank's did.
    members = {}
    for m, c in sorted(category.items()):
        if m not in far:
            members.setdefault(c, []).append(m)
    seen = {frozenset(ms) for ms, _ in used_groups} | {frozenset(ms) for ms, _ in groups}
    while len(groups) < groups_needed:
        c = rng.choice(sorted(c for c, ms in members.items() if len(ms) >= 3))
        ms, p = tuple(sorted(rng.sample(members[c], 3))), rng.choice(bank.CATEGORIES[c][0])
        if frozenset(ms) not in seen and not any(blocked(m, p) for m in ms):
            seen.add(frozenset(ms))
            groups.append((ms, p))
    for pool in (pairs, effects, groups):
        rng.shuffle(pool)
    return pairs, effects, groups


def _first_asks(rng, plan, pairs, effects, groups, rnd):
    """One round's first asks, drawn from the pools in the campaign's mix and phrasings."""
    tasks = []
    for kind in ("property", "method", "effect", "assessment", "comparison"):
        for _ in range(plan[kind]):
            variant = rng.randrange(3)
            if kind in ("property", "method"):
                m, p = pairs.pop()
                item = dict(kind=kind, materials=[m], property=p, variant=variant,
                            question=bank.PHRASES[kind][variant].format(p=p, m=m))
            elif kind == "assessment":
                m, p = pairs.pop()
                form = rng.choice(["assessment-grades", "assessment-method"])
                item = dict(kind=kind, form=form, materials=[m], property=p, variant=variant % 2,
                            question=bank.PHRASES[form][variant % 2].format(p=p, m=m))
            elif kind == "effect":
                m, f, p = effects.pop()
                pairs[:] = [x for x in pairs if x != (m, p)]
                item = dict(kind=kind, materials=[m], property=p, factor=f, variant=variant,
                            question=bank.PHRASES[kind][variant].format(p=p, m=m, f=f))
            else:
                ms, p = groups.pop()
                item = dict(kind=kind, materials=list(ms), property=p, variant=variant % 2,
                            question=bank.PHRASES[kind][variant % 2].format(p=p, ms=bank.joined(list(ms))))
            if rng.random() < 0.25:
                item["question"] += rng.choice(bank.TAILS)
            tasks.append(dict(item, round=rnd))
    return tasks


def _revisit(rng, parent, index, rnd):
    """The index-th revisit of a round: exact, paraphrase and sibling in turn."""
    kind = ("exact", "paraphrase", "sibling")[index % 3]
    if kind == "exact":
        question, asked = parent["question"], parent["kind"]
    elif kind == "paraphrase":
        question, asked = bank.paraphrase(parent, rng), parent["kind"]
    else:
        question, asked = bank.sibling(parent, rng)
    return dict(kind=asked, revisit=kind, materials=parent["materials"], property=parent["property"],
                question=question, parent=parent.get("taskId"), parentRound=parent.get("round", 0), round=rnd)


def _number(rng, tasks, rows, number, category, rnd, seed=SEED):
    """Number a round's ordered tasks after `number`, sample its whole-answer checks and append them to `rows`."""
    checks = set(rng.sample(range(len(tasks)), CHECKS_PER_ROUND))
    for index, task in enumerate(tasks):
        number += 1
        task.update(number=number, taskId=task_id(str(number), seed), depth="standard", checkSample=index in checks,
                    wave=rnd, categories=sorted({category[m] for m in task["materials"] if m in category}))
        task.setdefault("revisit", None)
        rows.append(task)
    return number


def round_tasks(rng, campaign, heldout, dev):
    category = _category()
    blocked_pairs = {(r["material"], r["property"]) for r in heldout + dev}
    far = {r["material"] for r in heldout + dev if r["stratum"] == "far"}
    used_pairs = {(q["materials"][0], q["property"]) for q in campaign if len(q["materials"]) == 1}
    used_effects = {(q["materials"][0], q.get("factor"), q["property"]) for q in campaign if q["kind"] == "effect"}
    used_groups = {(tuple(q["materials"]), q["property"]) for q in campaign if q["kind"] == "comparison"}
    pairs, effects, groups = _pools(rng, category, lambda m, p: (m, p) in blocked_pairs, far, used_pairs, used_effects,
                                    used_groups)
    earlier = [dict(q) for q in campaign if not q["revisit"] and q["kind"] != "old" and not set(q["materials"]) & far
               and (q["materials"][0], q["property"]) not in blocked_pairs]  # held-out and dev pairs stay unasked
    rows, number = [], 0
    for rnd, plan in ROUNDS.items():
        tasks = _first_asks(rng, plan, pairs, effects, groups, rnd)
        # Revisits: half of an earlier round's tasks (none before round 2), the rest of the campaign's.
        previous = [t for t in rows if not t["revisit"]]
        parents = (rng.sample(previous, plan["revisits"] // 2) if previous else [])
        parents += rng.sample([q for q in earlier if q["taskId"] not in {p["taskId"] for p in parents}],
                              plan["revisits"] - len(parents))
        tasks += [_revisit(rng, parent, index, rnd) for index, parent in enumerate(parents)]
        rng.shuffle(tasks)
        number = _number(rng, tasks, rows, number, category, rnd)
    asked = {q["question"].strip() for q in campaign} | {r["question"] for r in heldout + dev}
    assert not {r["question"] for r in rows if not r["revisit"]} & asked, "a round task was asked before"
    assert not any(set(r["materials"]) & far for r in rows), "a round task names a far polymer"
    assert not any((r["materials"][0], r["property"]) in blocked_pairs for r in rows if len(r["materials"]) == 1)
    assert len({r["taskId"] for r in rows}) == 300
    return rows


# ----- the five fresh restarts (2026-10-18) -----

RESTART_SEED = "oopc-restart-2026-10-18-R%d"
RESTART_ROUNDS = 5
RESTART_PLAN = dict(property=30, method=15, effect=15, assessment=10, comparison=10, revisits=20)
# Words that do not make two property names the same property ("glass transition temperature" and "melting temperature").
GENERIC = {"and", "the", "for", "from", "with", "its", "temperature", "temperatures", "strength", "properties", "property",
           "stated", "dsc", "dma", "tga", "waxd"}


def _words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in GENERIC}


def restart_exclusions(heldout, dev, campaign):
    """What every restart's tasks avoid, and the one exception, decided here and nowhere else (the owner may change it
    before the restarts start).

    - No task asks a held-out or dev polymer-property pair, and none names a held-out or dev far polymer, as in test 2.
      A pair counts as asked when the task's property is the excluded one or shares a significant word with it: the
      bank's comparison groups name properties in their own words ("compression set" of butyl rubber is a held-out
      pair; a comparison of PBO's "thermal decomposition temperature" is too, and "tensile strength" of HIPS overlaps
      its held-out "tensile modulus and yield strength").
    - Near parents (owner, 2026-10-18, before any run): the 20 campaign questions test 1's near held-out questions were
      drawn from are first asks of every restart, with their own text and kind, so a restart's store can come to cover
      the near questions' topics; their pairs are lifted for them, and for their exact and reworded revisits, only. The
      dev set's near parents stay excluded.
    - No task asks a held-out question's text, or a held-out pair from the held-out question's own angle (its kind).
      A near parent's sibling would ask exactly that angle, so a near parent is never revisited as a sibling.

    Returns `asks(material, property)`, true for an excluded ask; `angle(material, property, kind)`, true for a
    held-out pair from its held-out question's angle; the far polymers; and the near parents, each a campaign question
    with `nearParentOf`, the id of the held-out question drawn from it."""
    excluded = {}
    for row in heldout + dev:
        excluded.setdefault(row["material"], set()).add(row["property"])
    far = {row["material"] for row in heldout + dev if row["stratum"] == "far"}
    by_id = {q["taskId"]: q for q in campaign}
    parents = [dict(by_id[row["parent"]], nearParentOf=row["id"]) for row in heldout if row["stratum"] == "near"]
    assert all(p["materials"] == [row["material"]] and p["property"] == row["property"]
               for p, row in zip(parents, [r for r in heldout if r["stratum"] == "near"])), "a near parent's pair"
    same = lambda p, q: p == q or bool(_words(p) & _words(q))

    def asks(material, prop):
        return material in far or any(same(p, prop) for p in excluded.get(material, ()))

    def angle(material, prop, kind):
        return any(r["material"] == material and r["kind"] == kind and same(r["property"], prop) for r in heldout)
    return types.SimpleNamespace(asks=asks, angle=angle, far=far, parents=parents)


def _near_ask(parent, rnd):
    """A near parent as a restart's first ask: the campaign question's own text, kind and pair."""
    item = {k: parent[k] for k in ("kind", "form", "materials", "property", "factor", "variant", "question") if k in parent}
    return dict(item, nearParentOf=parent["nearParentOf"], campaignTask=parent["taskId"], round=rnd)


def restart_tasks(n, heldout, dev, campaign, rounds=RESTART_ROUNDS, seed=None):
    """Restart n's tasks, `rounds` x 100, drawn like test 2's rounds with the restart's own seed, the near parents
    spread over the rounds by that seed (4 a round), each counted in its round's mix under its own kind. Round 1's
    revisits ask round 1's own first asks again, each placed somewhere after its parent; later rounds' revisits ask
    first asks of the restart's earlier rounds."""
    seed = seed or RESTART_SEED % n
    rng, category, plan = random.Random(seed), _category(), RESTART_PLAN
    ex = restart_exclusions(heldout, dev, campaign)
    pairs, effects, groups = _pools(rng, category, ex.asks, ex.far, groups_needed=rounds * plan["comparison"],
                                    screen_groups=True)
    near = list(ex.parents)
    rng.shuffle(near)
    rows, number = [], 0
    for rnd in range(1, rounds + 1):
        mine = [_near_ask(p, rnd) for i, p in enumerate(near) if i % rounds == rnd - 1]
        quota = dict(plan, **{k: plan[k] - sum(m["kind"] == k for m in mine) for k in ("property", "method", "effect",
                                                                                      "assessment")})
        assert min(quota.values()) >= 0, "round %d cannot absorb its near parents" % rnd
        firsts = _first_asks(rng, quota, pairs, effects, groups, rnd) + mine
        rng.shuffle(firsts)
        parents = rng.sample(firsts if rnd == 1 else [t for t in rows if not t["revisit"]], plan["revisits"])
        for i in range(2, len(parents), 3):  # sibling slots: never a near parent (see restart_exclusions)
            if parents[i].get("nearParentOf"):
                j = next(j for j in range(len(parents)) if j % 3 != 2 and not parents[j].get("nearParentOf"))
                parents[i], parents[j] = parents[j], parents[i]
        revisits = [_revisit(rng, parent, index, rnd) for index, parent in enumerate(parents)]
        if rnd == 1:
            tasks = firsts[:]
            for revisit, parent in zip(revisits, parents):
                at = next(i for i, task in enumerate(tasks) if task is parent)
                tasks.insert(rng.randint(at + 1, len(tasks)), revisit)
        else:
            tasks = firsts + revisits
            rng.shuffle(tasks)
        number = _number(rng, tasks, rows, number, category, rnd, seed)
        for revisit, parent in zip(revisits, parents):  # round 1's parents are numbered only now
            revisit["parent"] = parent["taskId"]
    firsts = [r["question"] for r in rows if not r["revisit"]]
    assert len(rows) == rounds * 100 and len({r["taskId"] for r in rows}) == len(rows), "task count or ids"
    for rnd in range(1, rounds + 1):
        part = [r for r in rows if r["round"] == rnd]
        assert [sum(r["kind"] == k and not r["revisit"] for r in part) for k in plan if k != "revisits"] == \
            [plan[k] for k in plan if k != "revisits"], "round %d mix" % rnd
        assert sum(bool(r["revisit"]) for r in part) == plan["revisits"] and \
            sum(r["checkSample"] for r in part) == CHECKS_PER_ROUND, "round %d revisits or checks" % rnd
        assert sum(bool(r.get("nearParentOf")) for r in part) == len(near) // rounds, "round %d near parents" % rnd
    index = {r["taskId"]: r for r in rows}
    assert all(index[r["parent"]]["number"] < r["number"] and not index[r["parent"]]["revisit"]
               and (index[r["parent"]]["round"] < r["round"] or r["round"] == 1) for r in rows if r["revisit"]), \
        "a revisit before its parent, or of a later round's task"
    assert sorted(r["nearParentOf"] for r in rows if r.get("nearParentOf")) == sorted(p["nearParentOf"] for p in near)
    assert len(set(firsts)) == len(firsts), "a first ask repeats"
    texts = {r["question"] for r in heldout + dev}
    texts |= {q["question"] for q in campaign if q["taskId"] in {r["parent"] for r in dev if r["stratum"] == "near"}}
    assert not any(r["question"] in texts for r in rows), "a task asks a held-out or dev question or a dev near parent"
    assert not any(set(r["materials"]) & ex.far for r in rows), "a task names a far polymer"
    for r in rows:
        origin = index[r["parent"]] if r["revisit"] else r
        assert not any(ex.asks(m, r["property"]) for m in r["materials"]) or (
            origin.get("nearParentOf") and r["kind"] == origin["kind"] and r["revisit"] in (None, "exact", "paraphrase")), \
            "task %d asks an excluded pair" % r["number"]
        assert not (len(r["materials"]) == 1 and ex.angle(r["materials"][0], r["property"], r["kind"])), \
            "task %d asks a held-out pair from its held-out question's angle" % r["number"]
    return rows


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1))
    path.chmod(0o600)


def main():
    rng = random.Random(SEED)
    campaign = json.loads((CAMPAIGN / "questions.json").read_text())
    heldout = json.loads((ABLATION / "heldout.json").read_text())
    dev = dev_set(rng, campaign, heldout)
    rounds = round_tasks(rng, campaign, heldout, dev)
    for name, value in (("dev.json", dev), ("rounds.json", rounds)):
        path = BASE / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1))
        path.chmod(0o600)
    return dev, rounds


def main_restart(n, out=None):
    """Restart n's rounds.json, from test 1's held-out questions, test 2's dev set and the campaign's questions as
    recorded."""
    heldout = json.loads((ABLATION / "heldout.json").read_text())
    dev = json.loads((BASE / "dev.json").read_text())
    campaign = json.loads((CAMPAIGN / "questions.json").read_text())
    rows = restart_tasks(n, heldout, dev, campaign)
    write(Path(out or RESTARTS / ("R%d" % n)) / "rounds.json", rows)
    return rows


if __name__ == "__main__":
    import collections
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", type=int, choices=range(1, 6), help="Write restart N's tasks instead of test 2's")
    parser.add_argument("--out", help="The folder for a restart's rounds.json (default its run folder)")
    args = parser.parse_args()
    if args.restart:
        rounds, plan = main_restart(args.restart, args.out), range(1, RESTART_ROUNDS + 1)
    else:
        dev, rounds = main()
        plan = ROUNDS
        for r in dev:
            print("dev", r["stratum"], r["findingsFound"], "|", r["question"][:120])
    for rnd in plan:
        part = [t for t in rounds if t["round"] == rnd]
        print("round", rnd, len(part), dict(collections.Counter(t["kind"] for t in part)),
              dict(collections.Counter(t["revisit"] for t in part if t["revisit"])),
              "checks", sum(t["checkSample"] for t in part), "polymers", len({m for t in part for m in t["materials"]}))
