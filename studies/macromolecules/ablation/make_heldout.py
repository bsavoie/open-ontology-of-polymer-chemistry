"""Held-out questions for the memory ablation (owner-approved 2026-10-12): 60 standard-depth questions never asked.

- near (20): the polymer and property of a campaign question that left findings, asked from another angle;
- mid (20): a polymer the campaign asked about at least three times, with a property it never asked about;
- far (20): a polymer with no saved finding at all (the control: memory cannot help).

New phrasings, so no question repeats an earlier one word for word. Deterministic.

Ran in `.oopc/loop/harness/2026-10-ablation/`, where it wrote heldout.json (and still does); moved to the repository on
2026-10-13 unchanged except imports and paths.
"""
import hashlib, importlib.util, json, random, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, STUDY, run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-ablation")
CAMPAIGN = run_dir("2026-10-campaign")
from oopc import knowledge  # noqa: E402

spec = importlib.util.spec_from_file_location("bank", STUDY / "campaign" / "make_questions.py")
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)
SEED = "oopc-ablation-2026-10-12"
PHRASES = {
    "property": "Report a published value of {p} for {m}, with the specimen, method and conditions it was measured under.",
    "method": "Which method and test conditions does an open primary study use to measure {p} of {m}, and what value does it obtain?",
}
FAR = [  # (polymer as asked, property, kind): no finding in the store names it or its family or members, not even in
         # passing (PIB, agarose, PSS and CSM were replaced: they appear inside other materials' findings).
    ("poly(vinyl acetate) (PVAc)", "glass transition temperature (Tg)", "property"),
    ("polyisocyanurate (PIR) foam", "thermal conductivity", "property"),
    ("ethylene-acrylic elastomer (AEM)", "tensile strength retained after heat aging", "property"),
    ("ethylene-octene elastomer (POE)", "melting temperature and crystallinity by DSC", "method"),
    ("fluorosilicone rubber (FVMQ)", "volume swell in fuel", "property"),
    ("ethylene-acrylic acid copolymer (EAA)", "melting temperature", "property"),
    ("polyamide-imide (PAI)", "glass transition temperature", "method"),
    ("poly(cyclohexylenedimethylene terephthalate) (PCT)", "melting and crystallization temperatures", "property"),
    ("styrene-maleic anhydride copolymer (SMA)", "glass transition temperature", "property"),
    ("poly(vinyl formal) (PVFM)", "tensile strength", "property"),
    ("cellulose acetate propionate (CAP)", "tensile properties of cast films", "method"),
    ("cellulose nitrate", "thermal decomposition temperature by TGA", "property"),
    ("silk fibroin", "tensile strength of regenerated films", "property"),
    ("hydroxyethyl cellulose (HEC)", "solution viscosity at a stated concentration", "method"),
    ("poly(diallyl phthalate) (PDAP)", "heat deflection temperature", "property"),
    ("polyurea", "tensile strength and elongation at break", "property"),
    ("epichlorohydrin-ethylene oxide rubber (ECO)", "volume swell in oil or fuel", "property"),
    ("phthalonitrile resin", "glass transition temperature by DMA", "method"),
    ("hydroxypropyl cellulose (HPC)", "cloud point in water", "method"),
    ("chlorinated polyethylene elastomer (CM)", "Shore A hardness and tensile strength", "property"),
]


def task_id(name):
    return hashlib.md5((SEED + "-" + name).encode()).hexdigest()


def main():
    rng = random.Random(SEED)
    campaign = json.loads((CAMPAIGN / "questions.json").read_text())
    asked = {q["question"].strip() for q in campaign}
    asked |= {q["question"].strip() for q in json.loads((run_dir("2026-10-03-200") / "questions.json").read_text())}
    db = sqlite3.connect(knowledge.database(ROOT))
    deposits = dict(db.execute("SELECT question_id, findings FROM deposits"))
    single = [q for q in campaign if len(q["materials"]) == 1 and not q["revisit"] and q["kind"] in
              ("property", "method", "assessment", "effect")]
    pairs = {(q["materials"][0], q["property"]) for q in campaign if len(q["materials"]) == 1}
    counts = {}
    for q in campaign:
        for m in q["materials"]:
            counts[m] = counts.get(m, 0) + 1
    category = dict(bank.OLD)
    for name, members in bank.NEW.items():
        category.update({m: name for m in members})

    rows, used = [], set()
    # near: a campaign pair that left at least three findings, asked from the other angle.
    candidates = [q for q in single if (deposits.get(q["taskId"]) or 0) >= 3 and q["materials"][0] in category]
    rng.shuffle(candidates)
    for q in candidates:
        m = q["materials"][0]
        if m in used or len([r for r in rows if r["stratum"] == "near"]) == 20:
            continue
        kind = "method" if q["kind"] == "property" else "property"
        rows.append(dict(stratum="near", kind=kind, material=m, property=q["property"], parent=q["taskId"],
                         parentNumber=q["number"], question=PHRASES[kind].format(p=q["property"], m=m)))
        used.add(m)
    # mid: a polymer asked about at least three times, with a property of its category never asked for it.
    polymers = [m for m, n in counts.items() if n >= 3 and m in category and m not in used]
    rng.shuffle(polymers)
    for m in polymers:
        if len([r for r in rows if r["stratum"] == "mid"]) == 20:
            break
        fresh = [p for p in bank.CATEGORIES[category[m]][0] if (m, p) not in pairs]
        if not fresh:
            continue
        p = rng.choice(fresh)
        kind = "property" if len([r for r in rows if r["stratum"] == "mid"]) % 5 < 3 else "method"
        rows.append(dict(stratum="mid", kind=kind, material=m, property=p, question=PHRASES[kind].format(p=p, m=m)))
        used.add(m)
    for m, p, kind in FAR:
        rows.append(dict(stratum="far", kind=kind, material=m, property=p, question=PHRASES[kind].format(p=p, m=m)))
    assert [sum(r["stratum"] == s for r in rows) for s in ("near", "mid", "far")] == [20, 20, 20], "strata incomplete"
    assert not {r["question"] for r in rows} & asked, "a held-out question was asked before"
    for r in rows:  # The campaign's bare "PEI" meant polyetherimide; say so (the graph also has polyethyleneimine).
        r["question"] = r["question"].replace(" of PEI,", " of polyetherimide (PEI),").replace(" for PEI,", " for polyetherimide (PEI),")
        r.update(id=task_id(r["question"]), depth="standard")
    assert not {r["question"] for r in rows} & asked, "a held-out question was asked before"
    path = BASE / "heldout.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    path.chmod(0o600)
    return rows


if __name__ == "__main__":
    for r in main():
        print(r["stratum"], r["kind"], "|", r["question"][:130])
