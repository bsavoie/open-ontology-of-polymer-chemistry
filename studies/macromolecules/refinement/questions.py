"""Part C's withheld question sets H, N and L (docs/exec-plans/active/ontology-refinement-plan.md, "Withheld tasks"),
fixed and committed by hash before the curator proposes anything. No withheld question's trace enters mining.

- **H**: test 1's 60 held-out questions (`pins.HELDOUT`) with their strata (near, mid, far; 20 each), in Part A's order
  (`part_a.heldout()`), so H is comparable with Parts A and B.
- **N**: 60 new first asks from the campaign generator (`make_tasks._pools` and `_first_asks`, the bank's phrasings) with
  seed N_SEED, in test 2's mix of first-ask kinds scaled to 60 (N_MIX). Excluded: H's and the dev set's polymer–property
  pairs, a pair counting as theirs when its property shares a significant word with theirs (the restarts' rule,
  `make_tasks.restart_exclusions`), and their far polymers; and any draw whose text was asked before (`asked_before`:
  every question file and driver plan under `.oopc/loop/harness/`, which holds the campaign, Part A and Part B, and the
  live loop's questions), which is passed over for the next draw. Pairs asked before stay allowed: an ordinary day
  revisits topics. Each question keeps its polymer(s), property and kind; its stratum says what the campaign asked
  before (`n_stratum`).
- **L**: 60 targeted questions on (polymer id, A1 property class) pairs KF holds with at least LEAST non-rejected
  findings (`kf_pairs`: the polymer is a finding's `subject`, the class is A1's map of its `property`, material
  properties only), drawn with seed L_SEED and stratified by coverage (rank tertiles of findings per pair, `tertiles`),
  20 per group (QUOTA), each polymer at most once per group: "name" asks by a trade name or grade, with a page saying it
  is the polymer, that is none of the seed's names for any polymer and that no KF finding's material or statement uses
  as whole words (`used_in_kf`, read from pins.KF; full-text search would find those without the ontology; each question
  records the count, `nameUsedInKF`); "family" asks at family level, its places alternating (`slots`) between the
  seed's broader family of the polymer (drawn only from polymers that have one; today's search already joins a family to
  its members) and a family the seed does not link the polymer to, which the writer names with a page saying the
  polymer belongs to it (10 each: at random 16 of the first 20 family draws had a seed family, which would have left
  the unlinked case 4 questions); "value" asks for a value with its method and specimen, naming the polymer by a seed
  name. One Codex session per batch of BATCH pairs writes the questions from the pairs alone (WRITER, WRITER_SCHEMA;
  web on, to support a name with a page), phase PHASE, through `calls.invoke` and the study Guard; the harness checks
  each (`check`) and redraws a pair whose question the writer declined or that fails a check. Resumable: every draw and
  batch is saved under `L-work/`, and a rerun sends only what is not done.
- **C** (plan, "Case studies": a case with fewer than three qualifying withheld questions is filled with questions
  "written for the purpose before the case runs"): for each case short of three in `cases/selection.json`
  (`shortfalls`; not C7, whose questions are C1-C3's, answered on K0 too), one Codex session (C_WRITER, C_SCHEMA; no web;
  phase C_PHASE) writes a question for each pair `cases/pairs.json` offers it (`{"cases": {"C1": [{"material",
  "property", "polymerIds", "replay": what the replay shows qualifies it, "ask": optional, how to ask}]}}`, written from
  the replay by the selection step), at most SPARE more than it needs, from the case's mechanism (the selection's rule)
  and the pair alone; the first that pass `check_case`, as many as the case needs, are kept. A question keeps its pair's
  material and property, so its canonical query is the one the replay qualified. Resumable (`C-work/`).

Files, in `pins.folder("questions")` (private): `H.json`, `N.json`, `L.json` (each question: `id`, `set`, `question`
(its text, as every driver plan names it), `materials`, `polymerIds`, `property`, `kind`, `group`, `stratum`, and
the set's own fields), `hashes.json` (the SHA-256 of each file's canonical JSON, `oopc.util.digest`), `C.json` with its
own `case-hashes.json` (written after the screen, so not in `hashes.json`; it also holds the digests of the selection
and the pairs C was written from), and the records of how they were made (`N-build.json`, `L-work/`, `C-work/`). Each
file is fixed once written: building again must reproduce it.

**Commitments** (plan: the question sets are "committed by hash" before curation). The tracked file `commitments.json`
beside this module holds what is committed, entry by entry (ENTRIES): `questions` (the SHA-256 of `hashes.json` and of
each set file's bytes), `caseQuestions` (the same for `case-hashes.json` and `C.json`), and run.py's `overlay` and
`pool`. `commit` prints the question entries, or with `--write` writes them into the tracked file for a person to commit;
an entry committed with other content is never replaced. `fixed_questions` is what curation checks first.

    python -B studies/macromolecules/refinement/questions.py build      # H.json and N.json (no engine)
    python -B studies/macromolecules/refinement/questions.py write-L    # L.json (Codex sessions; resumable)
    python -B studies/macromolecules/refinement/questions.py hashes     # hashes.json, once all three exist
    python -B studies/macromolecules/refinement/questions.py commit [--write]  # commitments.json's question entries
    python -B studies/macromolecules/refinement/questions.py write-C    # C.json and case-hashes.json (Codex; resumable)
    python -B studies/macromolecules/refinement/questions.py status
"""
import argparse, collections, json, os, random, re, sqlite3, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import pins  # noqa: E402
from part_a import part_a  # noqa: E402
from recursive import make_tasks  # noqa: E402
from analysis.properties import rules  # noqa: E402
from oopc import calls, engines, knowledge  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, digest, now, read_json, resolve_release  # noqa: E402

HASHES = {"C": "case-hashes.json"}  # a set's hash file, when not hashes.json: C is fixed after the screen
COMMITMENTS = Path(__file__).resolve().parent / "commitments.json"  # tracked in git
COMMITTED = "oopc-refinement-commitments-v1"
ENTRIES = ("questions", "caseQuestions", "overlay", "pool")  # commitments.json's entries; run.py makes the last two
KINDS = ("property", "method", "effect", "assessment", "comparison")
# Test 2's first asks per round were 30 property, 15 method, 15 effect, 10 assessment, 10 comparison (80). Scaled to 60
# that is 22.5, 11.25, 11.25, 7.5, 7.5: the floors give 58, and the two left go to two of the three kinds tied at a
# remainder of .5. They go to assessment and comparison, whose rounding would otherwise be the largest relative error
# (7 of 7.5 against 22 of 22.5), which also keeps the mix's equal pairs (method = effect, assessment = comparison).
N_MIX = dict(property=22, method=11, effect=11, assessment=8, comparison=8)
N_SEED = "oopc-refinement-2026-10-21-N"
L_SEED = "oopc-refinement-2026-10-21-L"
LEAST = 3  # non-rejected findings a (polymer, class) pair needs to be drawn for L
GROUPS = ("name", "family", "value")
QUOTA = {"name": (7, 7, 6), "family": (7, 6, 7), "value": (6, 7, 7)}  # per coverage tertile; 20 each, 20 per tertile
BATCH = 10  # pairs per writer session
PHASE = "study:refinement:questions"
VOCABULARY = Path(rules.__file__).resolve().parent / "vocabulary.json"  # A1's classes, with their kinds
FILES = ("plan.json", "questions.json", "rounds.json", "dev.json", "heldout.json")  # where a run folder keeps questions
PRUNE = {".oopc", "workspaces", "items", "streams", "runs", "scoring", "releases"}  # never question files
URL = re.compile(r"https?://\S+\Z")


def path(name):
    return pins.folder("questions") / name


def norm(text):
    """A question's text for comparison: case and spacing ignored."""
    return " ".join((text or "").split()).lower()


def fixed(target, value):
    """Write `value` to `target` once; a later build must give the same content (compared by canonical hash)."""
    if Path(target).exists():
        if digest(read_json(target)) != digest(value):
            raise SystemExit("%s exists with other content; a question set is fixed once written" % target)
        return read_json(target)
    atomic_json(target, value, private=True)
    return value


def load(name, *, hashed=True):
    """A written set, checked against its hash file, `hashes.json` (C: `case-hashes.json`), refused if that is missing
    or differs, unless `hashed` is off."""
    value = read_json(path(name + ".json"))
    if hashed:
        hashes_file = HASHES.get(name, "hashes.json")
        if not path(hashes_file).exists():
            raise SystemExit("The question sets are not fixed by hash yet (questions.py %s)"
                             % ("write-C" if name in HASHES else "hashes"))
        if read_json(path(hashes_file))["sets"].get(name) != digest(value):
            raise SystemExit("%s.json differs from its hash in %s" % (name, hashes_file))
    return value


def _git(where, *args):
    return subprocess.run(["git", *args], cwd=where, text=True, capture_output=True).stdout.strip()


# ----- the seed graph -----

def seed_root():
    """The baseline graph's root: KF's workspace, whose release is the pinned seed release (read only)."""
    found = read_json(pins.KF / "releases/current.json")["release_id"]
    if found != pins.PINS["release"]:
        raise SystemExit("KF's graph release is %s, not the pinned %s" % (found, pins.PINS["release"]))
    return pins.KF


def resolved(root, text, strict=False):
    """The graph ids of the polymers `text` names, as search resolves them (`knowledge._query_parts`)."""
    polymers, _ = knowledge._query_parts(root, text, strict=strict)
    return set().union(*(p["ids"] for p in polymers)) if polymers else set()


def polymer_ids(root, names):
    return sorted(set().union(*(resolved(root, n) for n in names))) if names else []


def seed_names(root):
    """Each graph polymer's names as search knows them (lower case): label, canonical name, abbreviations, other names
    and trade names, with their generic-tail variants."""
    knowledge.polymer_aliases(root)
    names = collections.defaultdict(set)
    for name, ids in knowledge._POLYMER_IDS.get(str(resolve_release(root)), {}).items():
        for identifier in ids:
            names[identifier].add(name)
    return names


# ----- H -----

def build_h(root):
    """Test 1's held-out questions in Part A's order, each with its graph ids under the seed."""
    if Path(part_a.HELDOUT).resolve() != Path(pins.HELDOUT).resolve():
        raise SystemExit("Part A's held-out file is not pins.HELDOUT")
    return [dict(q, set="H", materials=[q["material"]], polymerIds=polymer_ids(root, [q["material"]]), group=q["kind"])
            for q in part_a.heldout()]


# ----- N -----

def texts(value):
    """Every question text in a question file or driver plan (any "question" string, at any depth)."""
    found = set()
    if isinstance(value, dict):
        if isinstance(value.get("question"), str):
            found.add(norm(value["question"]))
        for item in value.values():
            if isinstance(item, (dict, list)):
                found |= texts(item)
    elif isinstance(value, list):
        for item in value:
            found |= texts(item)
    return found


def asked_before(harness=None, live=None, skip=None):
    """The texts of every question asked before, by source: each question file and driver plan under the harness's run
    folders (the campaign, the 200-task run, tests 1 and 2, Part A's runs and case studies, Part B's restarts and their
    final evaluation) and the live loop's questions. Part C's own folder (`skip`) is left out."""
    harness = Path(harness or common.ROOT / ".oopc/loop/harness")
    live = Path(live or common.ROOT / ".oopc/loop/questions")
    skip = Path(skip or pins.BASE).resolve()
    found = collections.defaultdict(set)
    for top, dirs, files in os.walk(harness):
        here = Path(top)
        dirs[:] = sorted(d for d in dirs if d not in PRUNE and (here / d).resolve() != skip)
        for name in sorted(set(files) & set(FILES)):
            source = here.relative_to(harness).parts[0] if here != harness else name
            found[source] |= texts(read_json(here / name))
    for question in sorted(live.glob("*/question.json")):
        found["live-loop"] |= texts(read_json(question))
    return dict(found)


def exclusions(heldout, dev):
    """`blocked(material, property)`: a pair of H or the dev set, counted as theirs when the property is theirs or shares
    a significant word with it (as `make_tasks.restart_exclusions` screened the restarts), or a far polymer of theirs."""
    excluded = collections.defaultdict(set)
    for row in heldout + dev:
        excluded[row["material"]].add(row["property"])
    far = {row["material"] for row in heldout + dev if row["stratum"] == "far"}

    def blocked(material, prop):
        return material in far or any(p == prop or make_tasks._words(p) & make_tasks._words(prop)
                                      for p in excluded.get(material, ()))
    return blocked, far


def n_stratum(question, campaign):
    """What the campaign asked before: the same polymer and property (asked-pair: every polymer of a comparison with
    that property), the polymer with another property (asked-polymer), or neither (new-polymer)."""
    pairs = {(m, q["property"]) for q in campaign for m in q["materials"]}
    polymers = {m for q in campaign for m in q["materials"]}
    if all((m, question["property"]) in pairs for m in question["materials"]):
        return "asked-pair"
    return "asked-polymer" if set(question["materials"]) & polymers else "new-polymer"


def draw_n(heldout, dev, campaign, asked, seed=N_SEED, mix=N_MIX):
    """N's questions, drawn as test 2's rounds drew first asks (`make_tasks._pools`, `_first_asks`), one at a time so a
    draw whose text was asked before (`asked`, normalized texts) is passed over for the next. Returns the questions in
    one seeded order and the draws passed over."""
    rng = random.Random(seed)
    blocked, far = exclusions(heldout, dev)
    pairs, effects, groups = make_tasks._pools(rng, make_tasks._category(), blocked, far, screen_groups=True)
    seen, passed, rows = set(asked), [], []
    for kind in KINDS:
        for _ in range(mix[kind]):
            while True:
                [item] = make_tasks._first_asks(rng, {k: int(k == kind) for k in KINDS}, pairs, effects, groups, None)
                item.pop("round", None)
                if norm(item["question"]) not in seen:
                    break
                passed.append({"kind": kind, "question": item["question"]})
            seen.add(norm(item["question"]))
            rows.append(item)
    rng.shuffle(rows)
    for item in rows:
        item.update(id=make_tasks.task_id("N-" + item["question"], seed), set="N", group=item["kind"],
                    stratum=n_stratum(item, campaign), depth="standard")
    assert len({r["id"] for r in rows}) == len(rows) == sum(mix.values())
    assert not any(blocked(m, r["property"]) for r in rows for m in r["materials"]), "N asks an excluded pair"
    return rows, passed


def build(harness=None, live=None):
    """H.json and N.json (and N's build record); no engine."""
    root = seed_root()
    heldout, dev, campaign = read_json(pins.HELDOUT), read_json(pins.DEV), read_json(pins.CAMPAIGN)
    h = fixed(path("H.json"), build_h(root))
    sources = asked_before(harness, live)
    asked = set().union(*sources.values()) | texts(campaign) | texts(heldout) | texts(dev)
    rows, passed = draw_n(heldout, dev, campaign, asked)
    for row in rows:
        row["polymerIds"] = polymer_ids(root, row["materials"])
    n = fixed(path("N.json"), rows)
    atomic_json(path("N-build.json"), {
        "seed": N_SEED, "mix": N_MIX, "askedTexts": {k: len(v) for k, v in sorted(sources.items())},
        "askedDistinct": len(asked), "passedOver": passed,
        "excluded": {"pairs": len({(r["material"], r["property"]) for r in heldout + dev}),
                     "farPolymers": sorted({r["material"] for r in heldout + dev if r["stratum"] == "far"})},
        "seedRelease": pins.PINS["release"], "code": {"path": str(common.CODE), "revision": _git(common.CODE, "rev-parse",
                                                                                                  "HEAD")},
        "at": now()}, private=True)
    return {"H": summary(h), "N": summary(n)}


def summary(rows):
    return {"questions": len(rows), "byKind": dict(collections.Counter(r.get("kind") for r in rows)),
            "byStratum": dict(collections.Counter(r.get("stratum") for r in rows)),
            "byKindAndStratum": dict(collections.Counter("%s/%s" % (r.get("kind"), r.get("stratum")) for r in rows)),
            "withoutPolymerId": sum(not r.get("polymerIds") for r in rows)}


# ----- L: the pairs -----

def kf_pairs(root=None, mapping=None, vocabulary=None):
    """Non-rejected findings per (polymer id, A1 property class) in KF, material properties only; read-only, and refused
    unless KF and the map are KF's pinned fingerprint. Findings without a polymer id are left out."""
    root = Path(root or pins.KF)
    if driver.fingerprint(root) != pins.PINS["kf"]:
        raise SystemExit("%s is not KF (fingerprint %s)" % (root, driver.fingerprint(root)))
    meta = read_json(Path(pins.PROPERTY_MAP).parent / "meta.json")["meta"]
    if meta.get("storeFingerprint") != pins.PINS["kf"]:
        raise SystemExit("A1's property map was not built from KF")
    mapping = mapping or read_json(pins.PROPERTY_MAP)
    kinds = {c["id"]: c["kind"] for c in (vocabulary or read_json(VOCABULARY))["classes"]}
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    rows = db.execute("SELECT id, subject, property FROM findings WHERE status != ?", (knowledge.UNSUPPORTED,)).fetchall()
    db.close()
    pairs = collections.Counter()
    for _, subject, prop in rows:
        cls = (mapping.get(rules.normalize(prop)) or {}).get("class")
        if subject and kinds.get(cls) == "material-property":
            pairs[subject, cls] += 1
    return pairs


def tertiles(pairs, rng, least=LEAST):
    """The pairs with at least `least` findings in three rank tertiles of their finding counts (equal counts in a
    seeded random order, so a tie at a boundary is split at random), each tertile shuffled into its draw order."""
    eligible = [(p, c, n) for (p, c), n in sorted(pairs.items()) if n >= least]
    rng.shuffle(eligible)
    eligible.sort(key=lambda pair: pair[2])
    cuts = [len(eligible) * k // 3 for k in range(4)]
    parts = [eligible[cuts[k]:cuts[k + 1]] for k in range(3)]
    for part in parts:
        rng.shuffle(part)
    return parts


def slots():
    """The 60 places of L, in order, as (group, tertile, mode): each group's quota per tertile. The family places
    alternate between the seed's family of the polymer ("seed") and a family the seed does not link it to ("unlinked"),
    so each is asked 10 times, spread over the tertiles."""
    places = [(group, tertile) for group in GROUPS for tertile in (1, 2, 3) for _ in range(QUOTA[group][tertile - 1])]
    family = [i for i, (group, _) in enumerate(places) if group == "family"]
    mode = {i: ("seed", "unlinked")[k % 2] for k, i in enumerate(family)}
    return [(group, tertile, mode.get(i)) for i, (group, tertile) in enumerate(places)]


def plan_l(root=None):
    """L's fixed inputs: the tertiles (each in draw order) and their ranges."""
    rng = random.Random(L_SEED)
    parts = tertiles(kf_pairs(root), rng)
    ranges = [[min(n for *_, n in part), max(n for *_, n in part)] for part in parts]
    return {"seed": L_SEED, "least": LEAST, "quota": QUOTA, "tertiles": [
        {"tertile": k + 1, "pairs": [list(p) for p in part], "findings": ranges[k]} for k, part in enumerate(parts)]}


def next_draw(plan, draws, slot, up):
    """The pair slot `slot` takes next: the first of its tertile's pairs not drawn before, whose polymer its group has not
    drawn before (a polymer declined for a trade name would be declined again) and, for a "seed" family place, that has
    a broader family in the seed (`up`, the seed's broader links)."""
    group, tertile, mode = slots()[slot]
    taken = {(d["polymer"], d["class"]) for d in draws}
    polymers = {d["polymer"] for d in draws if d["group"] == group}
    for polymer, cls, n in plan["tertiles"][tertile - 1]["pairs"]:
        if (polymer, cls) not in taken and polymer not in polymers and (mode != "seed" or up.get(polymer)):
            return dict({"item": "a%03d" % (len(draws) + 1), "slot": slot, "group": group, "tertile": tertile,
                         "polymer": polymer, "class": cls, "findings": n}, **({"mode": mode} if mode else {}))
    raise SystemExit("Tertile %d has no pair left for group %s" % (tertile, group))


# ----- L: the writer -----

WRITER = """You write questions for a test of a polymer-science research assistant. Each item below gives a polymer (its
name, and the names a polymer ontology already uses for it, in lower case), a property class with its definition, and
the kind of question to write. Write one question per item as a polymer scientist would ask it: one or two sentences
asking for published values, without mentioning ontologies, databases, identifiers or this exercise. Ask about the
property class given, in ordinary words.

Kinds:
- "name": ask for a reported value of the property, naming the polymer ONLY by a commercial trade name or a specific
  commercial grade that is not among the names listed for it (for example a supplier's grade designation). Do not use
  the polymer's generic name, its abbreviation or any listed name anywhere in the question. `material` is that trade
  name or grade exactly as written in the question; `evidenceUrl` is a page (a supplier's data sheet or product page, a
  standard or a paper) stating that the name is this polymer. If you know no such name that a page supports, set
  `declined` to true and give the reason.
- "family": ask for reported values of the property at the level of the family listed under `family`, naming only that
  family and not the polymer itself. `material` is the family's name exactly as written in the question.
- "other-family": ask for reported values of the property at the level of a chemical family the polymer belongs to
  that is NOT among those listed under `notThese` (for example "aliphatic polyamides" for polyamide 6), naming only that
  family and not the polymer itself, nor any listed name. `material` is the family's name exactly as written in the
  question; `evidenceUrl` is a page stating that the polymer belongs to that family.
- "value": ask for a reported value of the property together with the test method and the specimen it was measured on
  (its form, preparation, grade or conditions), naming the polymer by one of its listed names. `material` is that name
  exactly as written in the question.

For every item return: `item`, the item's id; `question`; `material`; `property`, the property as worded in the
question; `evidenceUrl` (empty when the kind needs none); `declined` (false unless you cannot write the question) and
`reason` (empty unless you decline). You may search the web to confirm a trade name or a family. Return one entry per
item, in the order given.
"""
WRITER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["item", "question", "material", "property", "evidenceUrl", "declined", "reason"],
        "properties": {"item": {"type": "string"}, "question": {"type": "string"}, "material": {"type": "string"},
                       "property": {"type": "string"}, "evidenceUrl": {"type": "string"},
                       "declined": {"type": "boolean"}, "reason": {"type": "string"}}}}}}


def kf_texts():
    """Each KF finding's material and statement as search reads their words (`knowledge._words`), read only from
    pins.KF."""
    db = sqlite3.connect(knowledge.database(pins.KF).as_uri() + "?mode=ro", uri=True)
    rows = db.execute("SELECT material, statement FROM findings ORDER BY id").fetchall()
    db.close()
    return [(knowledge._words(material), knowledge._words(statement)) for material, statement in rows]


def used_in_kf(name, texts):
    """How many KF findings use `name` as whole words in their material or statement (case, spacing and punctuation
    ignored, as search reads words): full-text search would find those findings by the name alone."""
    phrase = knowledge._words(name)
    return sum(any(phrase in text for text in pair) for pair in texts) if phrase.strip() else 0


def context(root):
    """What the writer and the checks read from the seed graph, A1's vocabulary and KF's findings' words."""
    up, _, labels = knowledge._graph_families(root)
    classes = {c["id"]: c for c in read_json(VOCABULARY)["classes"]}
    return {"root": root, "up": up, "labels": labels, "names": seed_names(root), "classes": classes,
            "aliases": knowledge.polymer_aliases(root), "kf": kf_texts()}


def item_text(draw, ctx):
    """One pair as the writer sees it: the polymer and class alone, never a finding."""
    cls = ctx["classes"][draw["class"]]
    families = sorted(ctx["labels"].get(f, f) for f in ctx["up"].get(draw["polymer"], ()))
    unlinked = draw.get("mode") == "unlinked"
    value = {"item": draw["item"], "kind": "other-family" if unlinked else draw["group"],
             "polymer": ctx["labels"].get(draw["polymer"], draw["polymer"]),
             "namesAlreadyUsed": sorted(ctx["names"].get(draw["polymer"], ())),
             "property": {"label": cls["label"], "definition": cls.get("definition", "")}}
    if draw["group"] == "family":
        value["notThese" if unlinked else "family"] = families
    return value


def check(draw, written, ctx):
    """None when the written question passes the harness's checks for its kind, else the reason it is redrawn."""
    if written is None:
        return "not written"
    if written["declined"]:
        return "declined: " + written["reason"][:200]
    question, material = written["question"].strip(), written["material"].strip()
    if not 20 <= len(question) <= 700 or not material:
        return "no question or material"
    if material.lower() not in question.lower():
        return "the material is not in the question"
    pid, root = draw["polymer"], ctx["root"]
    named_loose, named = resolved(root, question), resolved(root, question, strict=True)
    if draw["group"] == "name":
        if norm(material) in {norm(n) for n in ctx["aliases"]}:
            return "the name is one of the seed's names"
        if named_loose & knowledge.lineage(root, {pid}):
            return "the question names the polymer or its family by a seed name"
        used = used_in_kf(material, ctx["kf"])
        if used:
            return "the name is used in %d KF %s material or statement" % (used, "finding's" if used == 1
                                                                             else "findings'")
        if not URL.match(written["evidenceUrl"].strip()):
            return "no evidence URL"
    elif draw["group"] == "family":
        if pid in named_loose or pid in resolved(root, material):
            return "the question names the polymer itself"
        if draw.get("mode") == "unlinked":
            if named_loose & knowledge.lineage(root, {pid}):
                return "the question names a family the seed links the polymer to"
            if not URL.match(written["evidenceUrl"].strip()):
                return "no evidence URL"
        elif not named & ctx["up"].get(pid, set()):
            return "the question does not name the seed's family"
    elif pid not in named:
        return "the question does not name the polymer by a seed name"
    return None


def l_question(draw, written, ctx, batch):
    """A written question that passed, as L stores it."""
    cls = ctx["classes"][draw["class"]]
    ids = {draw["polymer"]}
    extra = {}
    if draw["group"] == "name":
        extra = {"askedName": written["material"].strip(), "evidenceUrl": written["evidenceUrl"].strip(),
                 "nameUsedInKF": used_in_kf(written["material"], ctx["kf"])}  # 0: `check` redraws any other
    elif draw["group"] == "family":
        family = resolved(ctx["root"], written["material"])
        ids |= family
        extra = {"family": written["material"].strip(), "familyIds": sorted(family),
                 "familyInSeed": draw["mode"] == "seed", "evidenceUrl": written["evidenceUrl"].strip()}
    return dict({"id": make_tasks.task_id("L-%s-%s-%s" % (draw["group"], draw["polymer"], draw["class"]), L_SEED),
                 "set": "L", "question": written["question"].strip(), "materials": [written["material"].strip()],
                 "polymerIds": sorted(ids), "property": written["property"].strip() or cls["label"],
                 "propertyClass": draw["class"], "propertyLabel": cls["label"], "kind": draw["group"],
                 "group": draw["group"], "stratum": "tertile-%d" % draw["tertile"], "findings": draw["findings"],
                 "polymer": draw["polymer"], "polymerLabel": ctx["labels"].get(draw["polymer"], draw["polymer"]),
                 "writer": {"batch": batch["batch"], "item": draw["item"], "callId": batch["result"].get("callId")},
                 "depth": "standard"}, **extra)


def l_state(work):
    """Draws, batches and each draw's outcome, from the records alone."""
    draws = read_json(work / "draws.json") if (work / "draws.json").exists() else []
    batches = [read_json(p) for p in sorted((work / "batches").glob("*.json"))]
    outcome = {}
    for batch in batches:
        if driver._ok(batch.get("result")):
            outcome.update(batch.get("outcomes") or {})
    return draws, batches, outcome


def _outcomes(work, batch, draws, ctx):
    """Check a completed batch's questions and save what each check found."""
    batch["outcomes"] = {i: {"problem": check(draws[i], batch["result"]["written"].get(i), ctx)} for i in batch["items"]}
    atomic_json(work / "batches" / ("%03d.json" % batch["batch"]), batch, private=True)


def write_l(runner=None, hours=6, root=None):
    """Write L (resumable): draw a pair for every open place, send the drawn pairs not yet sent in batches of BATCH to
    one Codex session each, check what comes back, and redraw for the places whose question failed; L.json once all 60
    pass. Every session goes through `runner`, a Guard (by default `driver.Guard`, a deadline `hours` away)."""
    pins.frozen()
    folder, work = pins.folder("questions"), pins.folder("questions") / "L-work"
    (work / "batches").mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root or seed_root()
    plan = fixed(work / "plan.json", plan_l())
    ctx = context(root)
    guard = runner or driver.Guard(time.time() + hours * 3600, base=folder)
    try:
        while True:
            draws, batches, outcome = l_state(work)
            unchecked = [b for b in batches if driver._ok(b.get("result")) and "outcomes" not in b]
            for batch in unchecked:  # a run stopped between saving a batch's result and checking it
                _outcomes(work, batch, {d["item"]: d for d in draws}, ctx)
            if unchecked:
                continue
            open_batch = next((b for b in batches if not driver._ok(b.get("result"))), None)
            if open_batch is None:
                sent = {i for b in batches for i in b["items"]}
                pending = [d for d in draws if d["item"] not in sent]
                if not pending:
                    places = {d["slot"]: d for d in draws}  # each place's latest draw
                    redraw = [s for s in range(len(slots())) if s not in places or outcome.get(
                        places[s]["item"], {}).get("problem")]
                    if not redraw:
                        break
                    for slot in redraw:
                        draws.append(next_draw(plan, draws, slot, ctx["up"]))
                    atomic_json(work / "draws.json", draws, private=True)
                    continue
                open_batch = {"batch": len(batches) + 1, "items": [d["item"] for d in pending[:BATCH]]}
                atomic_json(work / "batches" / ("%03d.json" % open_batch["batch"]), open_batch, private=True)
            _send(folder, work, guard, open_batch, {d["item"]: d for d in draws}, ctx)
        draws, batches, outcome = l_state(work)
        by_item = {b_item: b for b in batches for b_item in b["items"]}
        latest = {d["slot"]: d for d in draws}
        rows = [l_question(latest[s], by_item[latest[s]["item"]]["result"]["written"][latest[s]["item"]], ctx,
                           by_item[latest[s]["item"]]) for s in range(len(slots()))]
        fixed(path("L.json"), rows)
        return {"status": "completed", "L": summary(rows)}
    except driver.Stop as stop:
        return {"status": "stopped", "stopReason": stop.args[0]}


def _send(folder, work, guard, batch, draws, ctx):
    """One writer session for one batch: tried once more after a timeout or a retryable failure (an answer that leaves out
    or repeats an item is `invalid-output`); quota, rate-limited, not-signed-in and the stop file stop the writing."""
    reason = driver._unavailable(guard, [engines.CODEX])
    if reason:
        raise driver.Stop(reason)
    items = [draws[i] for i in batch["items"]]
    prompt = WRITER + "\nItems:\n" + json.dumps([item_text(d, ctx) for d in items], ensure_ascii=False, indent=1)

    def work_():
        result = calls.invoke(folder, PHASE, "batch-%03d" % batch["batch"], guard, engines.CODEX, prompt, WRITER_SCHEMA,
                              tools=None, web=True, timeout=pins.SECONDS["writer"])
        written = {}
        for entry in result["answer"].get("questions") or []:
            if entry.get("item") in written:
                raise engines.EngineError("invalid-output", "item %s written twice" % entry["item"])
            written[entry.get("item")] = entry
        if set(written) != set(batch["items"]):
            raise engines.EngineError("invalid-output", "the answer does not give exactly the items asked for")
        return {"written": written, "callId": result.get("callId"), "model": result.get("model")}

    target = work / "batches" / ("%03d.json" % batch["batch"])
    batch.pop("result", None)  # a failed earlier attempt is tried again; its attempts stay recorded
    driver._attempts(folder, guard, target, batch, "result", work_)
    if driver._ok(batch.get("result")):
        _outcomes(work, batch, draws, ctx)
    else:
        raise driver.Stop("writer batch %d failed: %s" % (batch["batch"], batch["result"]["error"]["reason"]))


# ----- hashes and status -----

def hashes():
    """hashes.json: each set's SHA-256 (canonical JSON), written once all three exist; fixed once written."""
    missing = [s for s in pins.SETS if not path(s + ".json").exists()]
    if missing:
        raise SystemExit("Not written yet: %s" % ", ".join(missing))
    value = {"sets": {s: digest(read_json(path(s + ".json"))) for s in pins.SETS},
             "counts": {s: len(read_json(path(s + ".json"))) for s in pins.SETS}, "seeds": {"N": N_SEED, "L": L_SEED}}
    if path("hashes.json").exists():
        stored = read_json(path("hashes.json"))
        if {k: stored.get(k) for k in value} != value:
            raise SystemExit("hashes.json exists with other hashes; the sets are fixed once written")
        return stored
    atomic_json(path("hashes.json"), dict(value, at=now()), private=True)
    return read_json(path("hashes.json"))


# ----- commitments -----

def file_digest(target):
    """A private file's SHA-256 (of its bytes), or None when it does not exist."""
    target = Path(target)
    return digest(target.read_bytes()) if target.exists() else None


def commitments():
    """The tracked commitments.json: one entry per step's inputs (ENTRIES); an empty entry is not committed yet."""
    value = read_json(COMMITMENTS)
    if value.get("format") != COMMITTED or set(ENTRIES) - set(value):
        raise SystemExit("%s is not %s with the entries %s" % (COMMITMENTS, COMMITTED, ", ".join(ENTRIES)))
    return value


def commit(entries, write=False):
    """`entries` ({entry: value}) for commitments.json: returned to paste, or with `write` written into the tracked file
    in place, for a person to commit. An entry already committed with other content is refused: it stays as committed."""
    value = commitments()
    clash = sorted(k for k, entry in entries.items() if value.get(k) and value[k] != entry)
    if clash:
        raise SystemExit("commitments.json holds another %s entry; a committed entry is not replaced" % ", ".join(clash))
    if write and any(value.get(k) != entry for k, entry in entries.items()):
        value.update(entries)
        atomic_bytes(COMMITMENTS, (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode())
    return entries


def differs(key, found):
    """Why commitments.json's entry `key` is not `found` (what the private files give now), or None when it is."""
    committed = commitments().get(key)
    if not committed:
        return "commitments.json has no %s entry" % key
    if found is None:
        return "commitments.json has a %s entry, but its files are missing" % key
    if committed != found:
        return "%s: the private files differ from commitments.json (%s)" % (key, ", ".join(sorted(
            k for k in set(committed) | set(found) if committed.get(k) != found.get(k))))
    return None


def in_head(target):
    """Whether `target` is in its git repository's HEAD exactly as it is on disk."""
    target = Path(target).resolve()
    top = _git(target.parent, "rev-parse", "--show-toplevel")
    if not top:
        return False
    shown = subprocess.run(["git", "show", "HEAD:" + target.relative_to(Path(top).resolve()).as_posix()], cwd=top,
                           capture_output=True)
    return shown.returncode == 0 and shown.stdout == target.read_bytes()


def question_entry():
    """commitments.json's `questions` entry from the private files, refused unless the sets are fixed: hashes.json
    exists and covers H, N and L, and each set's file is its hash. It holds hashes.json's digest and each set file's."""
    if not path("hashes.json").exists():
        raise SystemExit("The question sets are not fixed by hash yet (questions.py hashes)")
    sets = read_json(path("hashes.json")).get("sets") or {}
    if sorted(sets) != sorted(pins.SETS):
        raise SystemExit("hashes.json covers %s, not H, N and L" % (", ".join(sorted(sets)) or "no set"))
    for name in pins.SETS:
        load(name)
    return {"hashes.json": file_digest(path("hashes.json")),
            "files": {name + ".json": file_digest(path(name + ".json")) for name in pins.SETS}}


def case_entry():
    """commitments.json's `caseQuestions` entry from the private files (C.json, refused unless it is its hash in
    case-hashes.json), or None before C.json is written."""
    if not path("C.json").exists():
        return None
    load("C")
    return {"case-hashes.json": file_digest(path("case-hashes.json")), "files": {"C.json": file_digest(path("C.json"))}}


def fixed_questions():
    """What curation checks before it starts (plan: the question sets are fixed, and committed by hash, before step 2):
    the sets fixed by hash (`question_entry`), as commitments.json's `questions` entry holds them, and commitments.json
    committed to git as it is. Returns hashes.json's digest."""
    entry = question_entry()
    problem = differs("questions", entry)
    if problem:
        raise SystemExit("Refused: %s (questions.py commit --write, then commit commitments.json)" % problem)
    if not in_head(COMMITMENTS):
        raise SystemExit("Refused: commitments.json is not committed to git as it is")
    return entry["hashes.json"]


def commit_questions(write=False):
    """The question entries for commitments.json: `questions`, and `caseQuestions` once C.json is written."""
    case = case_entry()
    return commit(dict({"questions": question_entry()}, **({"caseQuestions": case} if case else {})), write)


# ----- C: questions written for the case studies -----

C_SEED = "oopc-refinement-2026-10-21-C"
C_PHASE = "study:refinement:case-questions"
SPARE = 2  # pairs offered to a case's session beyond those it needs, in case a question fails its check
C_WRITER = """You write questions for case studies of a polymer-science research assistant that answers from saved
findings and the web. Each case tests one way saved knowledge is or is not reached; the case is described below so you
know what the questions are for, but never mention it. Each item gives a material and a property, and may say how to
ask. Write one question per item as a polymer scientist would ask it: one or two sentences asking for published values,
naming the material exactly as given and the property in exactly the words given, without mentioning ontologies,
databases, identifiers, case studies or this exercise.

For every item return: `item`, the item's id; `question`; `declined` (false unless you cannot write the question) and
`reason` (empty unless you decline). Return one entry per item, in the order given.
"""
C_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["item", "question", "declined", "reason"],
        "properties": {"item": {"type": "string"}, "question": {"type": "string"}, "declined": {"type": "boolean"},
                       "reason": {"type": "string"}}}}}}


def case_plan(selection, pairs):
    """What write-C asks, per case short of three in the selection (but C7): the case's rule, how many questions it
    needs, and the pairs offered for it (at most SPARE more), each with an item id."""
    plan = {}
    for case, short in sorted((selection.get("shortfalls") or {}).items()):
        if case == "C7" or not short:
            continue
        offered = ((pairs.get("cases") or {}).get(case) or [])[:short + SPARE]
        for pair in offered:
            if not (isinstance(pair, dict) and all(isinstance(pair.get(k), str) and pair[k].strip()
                                                   for k in ("material", "property")) and pair.get("replay")):
                raise SystemExit("cases/pairs.json: each %s pair needs a material, a property and what the replay "
                                 "shows (`replay`)" % case)
        plan[case] = {"rule": (selection.get("rules") or {}).get(case, ""), "needed": short,
                      "pairs": [dict(pair, item="%s-%d" % (case, k + 1)) for k, pair in enumerate(offered)]}
    return plan


def check_case(pair, written):
    """None when a written case question passes, else why it is not kept."""
    if written is None:
        return "not written"
    if written["declined"]:
        return "declined: " + written["reason"][:200]
    question = written["question"].strip()
    if not 20 <= len(question) <= 700:
        return "no question"
    for key in ("material", "property"):
        if norm(pair[key]) not in norm(question):
            return "the %s is not in the question as given" % key
    return None


def c_question(case, entry, pair, written, item):
    """A kept case question, as C.json stores it: the pair's material and property, so its canonical query is the one
    the replay qualified."""
    return {"id": make_tasks.task_id("C-%s-%s-%s" % (case, pair["material"].strip(), pair["property"].strip()), C_SEED),
            "set": "C", "question": written["question"].strip(), "materials": [pair["material"].strip()],
            "polymerIds": sorted(pair.get("polymerIds") or []), "property": pair["property"].strip(), "kind": case,
            "group": case, "stratum": "written", "case": case, "rule": entry["rule"],
            "pair": {k: v for k, v in pair.items() if k != "item"},
            "writer": {"item": pair["item"], "callId": item["result"].get("callId")}, "depth": "standard"}


def write_c(runner=None, hours=6):
    """C.json and case-hashes.json (resumable): one Codex session per case short of three withheld questions writes a
    question for each pair offered for it; the first that pass `check_case`, as many as the case needs, are kept, and a
    case left short is reported. The plan (`C-work/plan.json`) is fixed once written. Every session goes through
    `runner`, a Guard (by default `driver.Guard`, a deadline `hours` away)."""
    pins.frozen()
    folder, work = pins.folder("questions"), pins.folder("questions") / "C-work"
    work.mkdir(exist_ok=True, mode=0o700)
    chosen = pins.FOLDERS["cases"] / "selection.json"
    if not chosen.exists():
        raise SystemExit("No case selection yet (%s; cases.py select)" % chosen)
    offered = chosen.with_name("pairs.json")
    plan = fixed(work / "plan.json", {"selection": file_digest(chosen), "pairs": file_digest(offered),
                                      "cases": case_plan(read_json(chosen), read_json(offered) if offered.exists()
                                                         else {})})
    guard = runner or driver.Guard(time.time() + hours * 3600, base=folder)
    try:
        for case, entry in plan["cases"].items():
            target = work / (case + ".json")
            item = read_json(target) if target.exists() else {"case": case}
            if not entry["pairs"]:  # nothing offered: no session, and the case stays short
                continue
            if not driver._ok(item.get("result")):
                _send_case(folder, guard, target, item, entry)
            elif "outcomes" not in item:  # stopped between saving the answer and checking it
                _outcomes_case(target, item, entry)
    except driver.Stop as stop:
        return {"status": "stopped", "stopReason": stop.args[0]}
    rows, short = [], {}
    for case, entry in plan["cases"].items():
        item = read_json(work / (case + ".json")) if entry["pairs"] else {"outcomes": {}}
        kept = [p for p in entry["pairs"] if not item["outcomes"][p["item"]]["problem"]][:entry["needed"]]
        rows += [c_question(case, entry, p, item["result"]["written"][p["item"]], item) for p in kept]
        if len(kept) < entry["needed"]:
            short[case] = entry["needed"] - len(kept)
    fixed(path("C.json"), rows)
    fixed(path("case-hashes.json"), {"sets": {"C": digest(rows)}, "counts": {"C": len(rows)}, "seed": C_SEED,
                                     "selection": plan["selection"], "pairs": plan["pairs"]})
    return {"status": "completed", "C": summary(rows), "short": short}


def _outcomes_case(target, item, entry):
    item["outcomes"] = {p["item"]: {"problem": check_case(p, item["result"]["written"].get(p["item"]))}
                        for p in entry["pairs"]}
    atomic_json(target, item, private=True)


def _send_case(folder, guard, target, item, entry):
    """One session for one case, tried as L's writer sessions are; a failure that is not transient stops the writing."""
    reason = driver._unavailable(guard, [engines.CODEX])
    if reason:
        raise driver.Stop(reason)
    items = [dict({"item": p["item"], "material": p["material"].strip(), "property": p["property"].strip()},
                  **({"ask": p["ask"]} if p.get("ask") else {})) for p in entry["pairs"]]
    prompt = C_WRITER + "\nThe case: %s\n\nItems:\n%s" % (entry["rule"],
                                                          json.dumps(items, ensure_ascii=False, indent=1))
    fields = C_SCHEMA["properties"]["questions"]["items"]["properties"]

    def work_():
        result = calls.invoke(folder, C_PHASE, item["case"], guard, engines.CODEX, prompt, C_SCHEMA, tools=None,
                              web=False, timeout=pins.SECONDS["caseWriter"])
        written = {}
        for entry_ in result["answer"].get("questions") or []:
            if not isinstance(entry_, dict) or set(entry_) != set(fields) or not isinstance(entry_["declined"], bool) \
                    or not all(isinstance(entry_[k], str) for k in fields if k != "declined"):
                raise engines.EngineError("invalid-output", "an entry does not follow the schema")
            if entry_["item"] in written:
                raise engines.EngineError("invalid-output", "item %s written twice" % entry_["item"])
            written[entry_["item"]] = entry_
        if set(written) != {i["item"] for i in items}:
            raise engines.EngineError("invalid-output", "the answer does not give exactly the items asked for")
        return {"written": written, "callId": result.get("callId"), "model": result.get("model")}

    item.pop("result", None)  # a failed earlier attempt is tried again; its attempts stay recorded
    driver._attempts(folder, guard, target, item, "result", work_)
    if not driver._ok(item.get("result")):
        raise driver.Stop("case-question session %s failed: %s" % (item["case"], item["result"]["error"]["reason"]))
    _outcomes_case(target, item, entry)


def status():
    value = {}
    stored = read_json(path("hashes.json"))["sets"] if path("hashes.json").exists() else {}
    if path("case-hashes.json").exists():
        stored = dict(stored, **read_json(path("case-hashes.json"))["sets"])
    for name in pins.SETS + tuple(HASHES):
        if path(name + ".json").exists():
            rows = read_json(path(name + ".json"))
            value[name] = dict(summary(rows), hash=digest(rows), hashed=stored.get(name) == digest(rows))
    work = pins.folder("questions") / "L-work"
    if work.exists():
        draws, batches, outcome = l_state(work)
        problems = collections.Counter((v["problem"] or "passed").split(":")[0] for v in outcome.values())
        value["L-work"] = {"draws": len(draws), "batches": len(batches),
                           "batchesOpen": sum(not driver._ok(b.get("result")) for b in batches),
                           "failedAttempts": collections.Counter(a.get("reason") for b in batches
                                                                 for a in b.get("attempts", []) if a.get("reason")),
                           "outcomes": dict(problems)}
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["build", "write-L", "hashes", "commit", "write-C", "status"])
    parser.add_argument("--hours", type=float, default=6)
    parser.add_argument("--write", action="store_true", help="commit: write the entries into commitments.json")
    args = parser.parse_args()
    out = (build() if args.command == "build" else write_l(hours=args.hours) if args.command == "write-L"
           else hashes() if args.command == "hashes" else commit_questions(args.write) if args.command == "commit"
           else write_c(hours=args.hours) if args.command == "write-C" else status())
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
