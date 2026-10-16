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
repository on 2026-10-13 unchanged except imports and paths (the freeze worktree is now common.CODE).
"""
import hashlib, importlib.util, json, random, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-recursive")
CAMPAIGN = run_dir("2026-10-campaign")
ABLATION = run_dir("2026-10-ablation")
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


def task_id(name):
    return hashlib.md5((SEED + "-" + name).encode()).hexdigest()


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


def round_tasks(rng, campaign, heldout, dev):
    category = dict(bank.OLD)
    for name, members in bank.NEW.items():
        category.update({m: name for m in members})
    blocked_pairs = {(r["material"], r["property"]) for r in heldout + dev}
    far = {r["material"] for r in heldout + dev if r["stratum"] == "far"}
    used_pairs = {(q["materials"][0], q["property"]) for q in campaign if len(q["materials"]) == 1}
    used_effects = {(q["materials"][0], q.get("factor"), q["property"]) for q in campaign if q["kind"] == "effect"}
    used_groups = {(tuple(q["materials"]), q["property"]) for q in campaign if q["kind"] == "comparison"}
    pairs = [(m, p) for m, c in category.items() for p in bank.CATEGORIES[c][0]
             if (m, p) not in used_pairs | blocked_pairs and m not in far]
    effects = [(m, f, bank.CATEGORIES[c][0][i]) for m, c in category.items() if m not in far
               for f, fits in bank.CATEGORIES[c][1].items() for i in fits
               if (m, f, bank.CATEGORIES[c][0][i]) not in used_effects and (m, bank.CATEGORIES[c][0][i]) not in blocked_pairs]
    groups = [(tuple(ms), p) for ms, props in bank.COMPARISONS for p in props
              if (tuple(ms), p) not in used_groups and not set(ms) & far]
    # The campaign used 83 of the bank's 84 comparison groups; new ones compare three polymers of one category on one
    # of that category's properties, as the bank's did.
    members = {}
    for m, c in sorted(category.items()):
        if m not in far:
            members.setdefault(c, []).append(m)
    seen = {frozenset(ms) for ms, _ in used_groups} | {frozenset(ms) for ms, _ in groups}
    while len(groups) < 40:
        c = rng.choice(sorted(c for c, ms in members.items() if len(ms) >= 3))
        ms, p = tuple(sorted(rng.sample(members[c], 3))), rng.choice(bank.CATEGORIES[c][0])
        if frozenset(ms) not in seen and not any((m, p) in blocked_pairs for m in ms):
            seen.add(frozenset(ms))
            groups.append((ms, p))
    for pool in (pairs, effects, groups):
        rng.shuffle(pool)
    earlier = [dict(q) for q in campaign if not q["revisit"] and q["kind"] != "old" and not set(q["materials"]) & far
               and (q["materials"][0], q["property"]) not in blocked_pairs]  # held-out and dev pairs stay unasked
    rows, number = [], 0
    for rnd, plan in ROUNDS.items():
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
        # Revisits: half of an earlier round's tasks (none before round 2), the rest of the campaign's.
        previous = [t for t in rows if not t["revisit"]]
        parents = (rng.sample(previous, plan["revisits"] // 2) if previous else [])
        parents += rng.sample([q for q in earlier if q["taskId"] not in {p["taskId"] for p in parents}],
                              plan["revisits"] - len(parents))
        for index, parent in enumerate(parents):
            kind = ("exact", "paraphrase", "sibling")[index % 3]
            if kind == "exact":
                question, asked = parent["question"], parent["kind"]
            elif kind == "paraphrase":
                question, asked = bank.paraphrase(parent, rng), parent["kind"]
            else:
                question, asked = bank.sibling(parent, rng)
            tasks.append(dict(kind=asked, revisit=kind, materials=parent["materials"], property=parent["property"],
                              question=question, parent=parent["taskId"], parentRound=parent.get("round", 0), round=rnd))
        rng.shuffle(tasks)
        checks = set(rng.sample(range(len(tasks)), CHECKS_PER_ROUND))
        for index, task in enumerate(tasks):
            number += 1
            task.update(number=number, taskId=task_id(str(number)), depth="standard", checkSample=index in checks,
                        wave=rnd, categories=sorted({category[m] for m in task["materials"] if m in category}))
            task.setdefault("revisit", None)
            rows.append(task)
    asked = {q["question"].strip() for q in campaign} | {r["question"] for r in heldout + dev}
    assert not {r["question"] for r in rows if not r["revisit"]} & asked, "a round task was asked before"
    assert not any(set(r["materials"]) & far for r in rows), "a round task names a far polymer"
    assert not any((r["materials"][0], r["property"]) in blocked_pairs for r in rows if len(r["materials"]) == 1)
    assert len({r["taskId"] for r in rows}) == 300
    return rows


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


if __name__ == "__main__":
    import collections
    dev, rounds = main()
    for r in dev:
        print("dev", r["stratum"], r["findingsFound"], "|", r["question"][:120])
    for rnd in ROUNDS:
        part = [t for t in rounds if t["round"] == rnd]
        print("round", rnd, len(part), dict(collections.Counter(t["kind"] for t in part)),
              dict(collections.Counter(t["revisit"] for t in part if t["revisit"])),
              "checks", sum(t["checkSample"] for t in part), "polymers", len({m for t in part for m in t["materials"]}))
