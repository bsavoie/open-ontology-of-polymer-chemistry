"""Part C, steps 4 and 5 (docs/exec-plans/active/ontology-refinement-plan.md): check the approved edits, then build
release O and the store copies the arms answer on, each once, and fingerprint them.

    python -B studies/macromolecules/refinement/overlay.py check    # overlay/checks.json; builds nothing
    python -B studies/macromolecules/refinement/overlay.py seed     # overlay/seed-root alone (the empty overlay)
    python -B studies/macromolecules/refinement/overlay.py build    # checks, both releases, four stores, fingerprint.json
    python -B studies/macromolecules/refinement/overlay.py status

Inputs are `propose.py assemble`'s three files in `overlay/`; `overlay/excluded.json` ({"format":
"oopc-refinement-excluded-v1", "edits": {"e-004": "why"}}), when someone writes it, takes edits out of every check and
build that has not run yet (an edit the replay drops, or one a check refuses) and is recorded with them. `mine.py
effects` writes it for the edits that lose more than they fix, between `check` and `build`; `build` refuses unless
`mine/effects.json` measured every edit in force on the inputs in force now (`measured`).

Where the edits go:
- Graph edits (names, polymers, family links) are applied to a copy of the pinned wiki snapshot (`config/seed-lock.json`),
  which `oopc.seed.import_seed` and the release builder `oopc.cli.publish_records` then turn into records exactly as
  they built the pinned release. The snapshot holds a polymer's `abbreviations` and `alternateNames` as strings and its
  `tradeNames` as objects with a `name`; `relationships` hold both directions of a family link (`broader` on the
  member, `narrower` on the family); the import copies a polymer's other fields into its record and makes one claim per
  relationship, whose `broader` and `narrower` edges `knowledge._graph_families` reads, as `knowledge.polymer_aliases`
  reads the names. A new polymer is a snapshot polymer with an id from `pins.RESERVED`, status `candidate` and the
  overlay's provenance; every polymer an edit touches lists it in `refinementEdits`. The one change after the import:
  the claims of an overlay link get the edit as their basis, status `candidate` and the overlay's provenance (with the
  claim id recomputed as the import computes it), so no overlay link reads as wiki-authored.
- With an empty overlay the pinned snapshot is imported as it is and must give the pinned release, `pins.PINS["release"]`.
- Store edits go into store copies: `pins.TABLES` filled from the store overlay (a link's evidence is kept as JSON with
  its edit), `finding_terms` from A1's property map (`pins.PROPERTY_MAP`, keyed by `rules.normalize` of a finding's
  property string), and polymer ids: the approved annotation edits, then both halves of upkeep's polymer-id rule
  (`upkeep.file_under`, as `upkeep.polymers` runs it: file a finding with no polymer id; move one filed under a family to
  the member its text names) against the refined release, where it files them otherwise than against the seed release
  (the rest is upkeep's work, not the ontology's). A polymer id a person approved (`upkeep._approved`) is never changed.
  The store copies hold no questions, so the rule reads question texts from QUESTIONS_ROOT's store, read only.

Built once, never rebuilt (and never resumed over a part whose release manifest or `refinement.json` records other
inputs): `overlay/seed-root` and `overlay/release-root` (workspace-style roots with
`releases/current.json`, as `driver.workspace(..., releases=root)` expects) and `stores/workspaces/{KF, KF-refined, K0,
K0-refined}`, then `overlay/fingerprint.json`: `releases` (seed, refined), `stores` (each store's `driver.fingerprint`
plus `tables`, the hash of pins.TABLES, null without them; run.py reads this), `roots` (their folders), `builds` (each
store's build report), the edits built and excluded, and the overlays' hashes. `root_for(groups)` gives a root with
only some edit groups (the effect replay's group totals, the attribution of hops to groups), built once per combination
and content under `stores/` (listed in `stores/roots.json`). `edit_root(folder, edits)` gives the effect replay a root
with only some edits, built from scratch in a folder its caller deletes.
"""
import argparse, copy, hashlib, importlib.util, json, re, shutil, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402  (puts the code under test first on sys.path)
import driver  # noqa: E402
from refinement import pins  # noqa: E402
from oopc import knowledge, seed as seed_import, upkeep  # noqa: E402
from oopc.cli import publish_records  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, digest, locked, now, read_json, resolve_release  # noqa: E402

FORMATS = {"edits": "oopc-refinement-edits-v1", "graph": "oopc-refinement-graph-overlay-v1",
           "store": "oopc-refinement-store-overlay-v1", "checks": "oopc-refinement-checks-v1",
           "fingerprint": "oopc-refinement-fingerprint-v1", "excluded": "oopc-refinement-excluded-v1"}
# The overlay lists and the edit type each holds.
KEYS = {"names": "name", "polymers": "polymer", "familyLinks": "family-link", "sourceLinks": "source-link",
        "propertyTerms": "property-term", "annotations": "annotation"}
GRAPH_KEYS, STORE_KEYS = ("names", "polymers", "familyLinks"), ("sourceLinks", "propertyTerms", "annotations")
SEED_LOCK = common.ROOT / "config/seed-lock.json"
QUESTIONS_ROOT = common.ROOT  # its .oopc/loop/questions holds the question texts upkeep's rule reads (read only)
VOCABULARY = common.STUDY / "analysis/properties/vocabulary.json"  # A1's property classes
RULES = common.STUDY / "analysis/properties/rules.py"  # A1's normalization of property strings
NAME_LENGTH = (2, 60)  # knowledge.polymer_aliases reads names of this length only
BASES = {"KF": lambda: pins.KF, "K0": lambda: pins.K0}


def provenance(edit):
    return {"source": "Part C ontology refinement overlay (Macromolecules study, private)", "edit": edit,
            "verification": "Proposed by a curator session from the researcher's search traces and approved by an "
                            "independent reviewer session against its cited sources; not from the wiki, and not a "
                            "reviewed scientific claim."}


# ----- the seed and what search reads of it -----

def seed():
    """The pinned wiki snapshot: its path, checksum and content, refused unless it is the one the lock pins."""
    lock = read_json(SEED_LOCK)
    path = Path(common.ROOT) / lock["file"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != lock["sha256"]:
        raise SystemExit("The seed snapshot %s is not the one config/seed-lock.json pins" % path)
    return path, lock["sha256"], json.loads(raw)


def names_of(polymer):
    """A snapshot polymer's names as `knowledge.polymer_aliases` reads them from its record."""
    names = [polymer.get("canonicalName"), *(polymer.get("abbreviations") or []),
             *(polymer.get("alternateNames") or []),
             *(t.get("name") for t in polymer.get("tradeNames") or [] if isinstance(t, dict))]
    names = [n.strip() for n in names if isinstance(n, str) and NAME_LENGTH[0] <= len(n.strip()) <= NAME_LENGTH[1]]
    return names + [n for n in map(knowledge._without_generic_tail, names) if n and n not in names]


class Graph:
    """A snapshot's polymers as search reads them: names (lower case) to ids, and broader and narrower links."""

    def __init__(self, snapshot):
        self.labels, self.names, self.own, self.up, self.down = {}, {}, {}, {}, {}
        for polymer in snapshot["polymers"]:
            wid = polymer["wopId"]
            self.labels[wid] = polymer["canonicalName"]
            self.own[wid] = {n.lower() for n in names_of(polymer)}
            for name in self.own[wid]:
                self.names.setdefault(name, set()).add(wid)
            for link in polymer.get("relationships") or []:
                if link.get("kind") in ("broader", "narrower"):
                    (self.up if link["kind"] == "broader" else self.down).setdefault(wid, set()).add(link["wopId"])

    def ids(self, name):
        return set(self.names.get(name.strip().lower(), ()))

    def ancestors(self, wid):
        found, todo = set(), [wid]
        while todo:
            for parent in self.up.get(todo.pop(), ()):
                if parent not in found:
                    found.add(parent)
                    todo.append(parent)
        return found

    def lineage(self, ids):
        """As `knowledge.lineage`: the ids, every family above them and every member below them."""
        found = set(ids)
        for links in (self.up, self.down):
            todo = list(ids)
            while todo:
                for other in links.get(todo.pop(), ()):
                    if other not in found:
                        found.add(other)
                        todo.append(other)
        return found

    def unrelated(self, ids):
        """Pairs of the ids neither of which is in the other's lineage."""
        ids = sorted(ids)
        return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if b not in self.lineage({a})]

    def cycle(self):
        """A polymer on a cycle of broader links, or None."""
        state = {}
        for start in sorted(self.labels):
            stack = [(start, iter(sorted(self.up.get(start, ()))))]
            if state.get(start):
                continue
            state[start] = 1
            while stack:
                node, children = stack[-1]
                child = next(children, None)
                if child is None:
                    state[node] = 2
                    stack.pop()
                elif state.get(child) == 1:
                    return child
                elif not state.get(child):
                    state[child] = 1
                    stack.append((child, iter(sorted(self.up.get(child, ())))))
        return None


def variants(name):
    """A name as search would also read it (without a generic tail such as "family")."""
    name = name.strip()
    tail = knowledge._without_generic_tail(name)
    return [name] + ([tail] if tail else [])


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def refine(snapshot, graph):
    """A copy of the snapshot with the graph overlay applied, and the links it added ((subject, predicate, object) ->
    edit). A name a polymer already has in that field, or a link the snapshot already has, is left as it is.

    A new polymer is study-authored: status `candidate`, the overlay's provenance with its edit, and (after the import,
    `relabel`) the overlay's rights with no wiki attribution. A name or link added to an existing polymer stays in that
    wiki polymer's record, marked by the polymer's `refinementEdits` (each with its edit), and a trade name also by its
    own `refinementEdit`; the record's other fields, rights included, remain the wiki's."""
    snapshot = copy.deepcopy(snapshot)
    polymers = {p["wopId"]: p for p in snapshot["polymers"]}
    added = {}

    def mark(polymer, entry):
        polymer.setdefault("refinementEdits", []).append(entry)

    def link(narrower, broader, edit):
        down, up = polymers[narrower], polymers[broader]
        if {"kind": "broader", "wopId": broader} in down.get("relationships", []):
            return
        down.setdefault("relationships", []).append({"kind": "broader", "wopId": broader})
        up.setdefault("relationships", []).append({"kind": "narrower", "wopId": narrower})
        added[(narrower, "broader", broader)] = added[(broader, "narrower", narrower)] = edit
        mark(down, {"edit": edit, "broader": broader})
        mark(up, {"edit": edit, "narrower": narrower})

    for item in graph.get("polymers", []):
        polymer = {"type": "polymer_entry", "wopId": item["id"], "canonicalSlug": slug(item["label"]),
                   "canonicalName": item["label"], "alternateNames": list(item.get("alternateNames") or []),
                   "abbreviations": list(item.get("abbreviations") or []), "relationships": [], "sections": {},
                   "sources": [], "status": "candidate", "provenance": provenance(item["edit"]),
                   "history": [{"action": "refinement-overlay", "edit": item["edit"]}],
                   "refinementEdits": [{"edit": item["edit"], "type": "polymer"}]}
        snapshot["polymers"].append(polymer)
        polymers[item["id"]] = polymer
        for broader in item["broader"]:
            link(item["id"], broader, item["edit"])
    for item in graph.get("names", []):
        polymer, field, name = polymers[item["polymer"]], item["field"], item["name"]
        present = [t.get("name") if isinstance(t, dict) else t for t in polymer.get(field) or []]
        if name in present:
            continue
        polymer.setdefault(field, []).append({"name": name, "refinementEdit": item["edit"]} if field == "tradeNames"
                                             else name)
        mark(polymer, {"edit": item["edit"], "field": field, "name": name})
    for item in graph.get("familyLinks", []):
        link(item["narrower"], item["broader"], item["edit"])
    return snapshot, added


def relabel(records, added):
    """The claims of the links the overlay added carry their edit as basis, status `candidate` and the overlay's
    provenance; the claim id is recomputed as `import_seed` computes it. A polymer's `seedRelationships` keep the wiki's
    links only. A new polymer's record, to which the import gives the wiki's rights and attribution as to every polymer,
    gets the overlay's instead: study-authored under its edit, not wiki content, private, with no attribution."""
    for record in records:
        if record["@type"] == "PolymerConcept":
            record["seedRelationships"] = [r for r in record.get("seedRelationships") or []
                                           if (record["@id"], r.get("kind"), r.get("wopId")) not in added]
            edit = next((e["edit"] for e in record.get("refinementEdits") or [] if e.get("type") == "polymer"), None)
            if edit:
                basis = "study-authored: Part C ontology refinement overlay, edit %s; not wiki content" % edit
                record["rights"] = {"basis": basis, "edit": edit, "release": "private study overlay, not published"}
            continue
        key = (record.get("subject"), record.get("predicate"), record.get("object"))
        if record["@type"] != "Claim" or key not in added:
            continue
        edit = added[key]
        context = {"basis": "refinement edit %s (study overlay); not wiki-authored, not independently verified" % edit}
        record.update(context=context, status="candidate", provenance=provenance(edit),
                      history=[{"action": "refinement-overlay", "edit": edit}])
        record["@id"] = "claim:" + seed_import._digest(seed_import._json([*key, context, None]))[:32]
    records.sort(key=lambda r: r["@id"])


def _empty(graph):
    return not any((graph or {}).get(k) for k in GRAPH_KEYS)


def release(root, graph=None):
    """The graph release of the seed plus `graph` (a graph overlay; none for the empty overlay), built once into the
    workspace-style root `root` (`releases/<id>`, `releases/current.json`); returns its id. Built under a temporary name,
    so a half-built root is never taken for a finished one. A root already built is kept only when its release
    records the same seed and graph overlay (`refinement` in its manifest; none for the empty overlay)."""
    root = Path(root)
    if (root / "releases/current.json").exists():
        built = read_json(resolve_release(root) / "manifest.json").get("refinement")
        have = None if built is None else {k: built.get(k) for k in ("baseSeedSha256", "graphOverlaySha256")}
        want = None if _empty(graph) else {"baseSeedSha256": seed()[1], "graphOverlaySha256": digest(graph)}
        if have != want:
            raise SystemExit("%s was built from other graph edits than those in force now; it is never rebuilt over"
                             % root)
        return read_json(root / "releases/current.json")["release_id"]
    part = root.with_name(root.name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True, mode=0o700)
    path, sha, snapshot = seed()
    if _empty(graph):
        records, ontology, metadata = seed_import.import_seed(path, sha)
    else:
        refined, added = refine(snapshot, graph)
        atomic_bytes(part / "seed-refined.json", json.dumps(refined, ensure_ascii=False, sort_keys=True).encode(),
                     private=True)
        records, ontology, metadata = seed_import.import_seed(part / "seed-refined.json")
        relabel(records, added)
        metadata["refinement"] = {"baseSeedSha256": sha, "graphOverlaySha256": digest(graph),
                                  "edits": sorted({x["edit"] for k in GRAPH_KEYS for x in graph.get(k, [])})}
    target = publish_records(part, records, ontology, metadata)
    part.rename(root)
    return target.name


def verify(root, graph):
    """The built release gives search what the overlay says: each new name finds its polymer
    (`knowledge.polymer_ids`) and each new link joins its polymers (`knowledge.lineage`)."""
    wrong = []
    for item in graph.get("names", []):
        if item["polymer"] not in knowledge.polymer_ids(root, item["name"]):
            wrong.append("%s: %r does not find %s" % (item["edit"], item["name"], item["polymer"]))
    for item in graph.get("polymers", []):
        if item["id"] not in knowledge.polymer_ids(root, item["label"]):
            wrong.append("%s: %r does not find %s" % (item["edit"], item["label"], item["id"]))
        wrong += ["%s: %s is not in %s's lineage" % (item["edit"], b, item["id"]) for b in item["broader"]
                  if b not in knowledge.lineage(root, {item["id"]})]
    for item in graph.get("familyLinks", []):
        if item["broader"] not in knowledge.lineage(root, {item["narrower"]}):
            wrong.append("%s: %s is not in %s's lineage" % (item["edit"], item["broader"], item["narrower"]))
    if wrong:
        raise SystemExit("The refined release does not read as the overlay says: " + "; ".join(wrong[:10]))


# ----- the overlays and the checks -----

def overlays():
    """The approved edits in force (edits.json less excluded.json) and the graph and store overlays reduced to them."""
    folder = pins.folder("overlay")
    files = {"edits": folder / "edits.json", "graph": folder / "graph-overlay.json", "store": folder / "store-overlay.json"}
    for name, path in files.items():
        if not path.exists():
            raise SystemExit("%s is missing: run propose.py assemble first" % path.name)
    values = {name: read_json(path) for name, path in files.items()}
    for name, value in values.items():
        if value.get("format") != FORMATS[name]:
            raise SystemExit("%s is not %s" % (files[name].name, FORMATS[name]))
    excluded = read_json(folder / "excluded.json") if (folder / "excluded.json").exists() else {"edits": {}}
    if excluded.get("format", FORMATS["excluded"]) != FORMATS["excluded"]:
        raise SystemExit("excluded.json is not %s" % FORMATS["excluded"])
    excluded = dict(excluded.get("edits") or {})
    active = {k: v for k, v in values["edits"]["edits"].items() if k not in excluded}
    graph = {k: [x for x in values["graph"].get(k, []) if x.get("edit") not in excluded] for k in GRAPH_KEYS}
    store = {k: [x for x in values["store"].get(k, []) if x.get("edit") not in excluded] for k in STORE_KEYS}
    return active, graph, store, excluded


def holdings(root):
    """What a store holds, read only: its findings (id -> row) and its sources (source key -> a title)."""
    db = sqlite3.connect(knowledge.database(root).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        findings = {r["id"]: dict(r) for r in db.execute(
            "SELECT id, question_id, subject, material, statement, property, source_title, source_url, source_doi, "
            "detail FROM findings")}
        notes = db.execute("SELECT title, url, doi FROM notes").fetchall()
    finally:
        db.close()
    sources = {}
    for row in findings.values():
        sources.setdefault(knowledge.source_key(row["source_doi"], row["source_url"]), row["source_title"] or "")
    for row in notes:
        sources.setdefault(knowledge.source_key(row["doi"], row["url"]), row["title"] or "")
    sources.pop("", None)
    return {"findings": findings, "sources": sources}


def property_classes():
    return {c["id"]: c for c in read_json(VOCABULARY)["classes"]}


def reserved(wid):
    return bool(knowledge.WOP.match(wid or "")) and pins.RESERVED[0] <= wid <= pins.RESERVED[1]


def check(write=True):
    """The deterministic checks of the plan's step 4 on the edits in force; written to overlay/checks.json. A problem
    refuses every build; a warning (an edit that changes nothing) does not."""
    active, graph, store, excluded = overlays()
    problems, warnings = [], []

    def problem(name, edit, detail):
        problems.append({"check": name, "edit": edit, "detail": detail})

    path, sha, snapshot = seed()
    base = Graph(snapshot)
    kf = holdings(pins.KF)
    k0 = holdings(pins.K0) if knowledge.database(pins.K0).exists() else {"findings": {}}
    classes = property_classes()
    # Closed list, and the overlays hold each approved edit once, under its type.
    for eid, edit in sorted(active.items()):
        if edit.get("type") not in pins.TYPES:
            problem("closed-list", eid, "type %r is not on the closed list" % edit.get("type"))
        if (edit.get("reviewer") or {}).get("verdict") != "approved":
            problem("approved", eid, "not approved by its reviewer")
    seen = {}
    for key, kind in KEYS.items():
        for item in (graph if key in GRAPH_KEYS else store)[key]:
            eid = item.get("edit")
            seen[eid] = seen.get(eid, 0) + 1
            if eid not in active or active[eid].get("type") != kind:
                problem("closed-list", eid, "%s entry is not an approved %s edit" % (key, kind))
    for eid in sorted(set(active) - set(seen)):
        problem("closed-list", eid, "in edits.json but in neither overlay")
    for eid in sorted(e for e, n in seen.items() if n > 1):
        problem("closed-list", eid, "entered more than once in the overlays")
    # New polymers: reserved ids, a broader link to an existing polymer.
    new = {}
    for item in graph["polymers"]:
        if not reserved(item.get("id")) or item["id"] in base.labels or item["id"] in new:
            problem("reserved-ids", item["edit"], "%s is not a free id in %s..%s" % (item.get("id"), *pins.RESERVED))
        if not item.get("broader") or any(b not in base.labels for b in item["broader"]):
            problem("broader-link", item["edit"], "a new polymer needs broader links to existing polymers only")
        if not NAME_LENGTH[0] <= len((item.get("label") or "").strip()) <= NAME_LENGTH[1]:
            problem("fields", item["edit"], "label must be %d to %d characters" % NAME_LENGTH)
        new[item.get("id")] = item
    known = set(base.labels) | set(new)
    for item in graph["names"]:
        if item.get("polymer") not in known or item.get("field") not in pins.NAME_FIELDS:
            problem("fields", item["edit"], "unknown polymer or name field")
        elif not NAME_LENGTH[0] <= len((item.get("name") or "").strip()) <= NAME_LENGTH[1]:
            problem("fields", item["edit"], "a name must be %d to %d characters, or search ignores it" % NAME_LENGTH)
        elif item["name"].strip().lower() in base.own.get(item["polymer"], ()):
            warnings.append({"check": "no-op", "edit": item["edit"], "detail": "%r already names %s" % (
                item["name"], item["polymer"])})
    for item in graph["familyLinks"]:
        if item.get("narrower") not in base.labels or item.get("broader") not in base.labels:
            problem("fields", item["edit"], "a family link joins two existing polymers")
        elif item["broader"] in base.up.get(item["narrower"], ()):
            warnings.append({"check": "no-op", "edit": item["edit"], "detail": "the seed has this link"})
    for item in store["sourceLinks"]:
        if item.get("relation") not in pins.LINK_RELATIONS:
            problem("source-endpoints", item["edit"], "relation %r is not one of %s" % (
                item.get("relation"), ", ".join(pins.LINK_RELATIONS)))
        for end in ("a", "b"):
            if item.get(end) not in kf["sources"]:
                problem("source-endpoints", item["edit"], "%s %r is not a source the store holds" % (end, item.get(end)))
        if item.get("a") == item.get("b"):
            problem("source-endpoints", item["edit"], "a link joins two different sources")
    links = {(x["a"], x["relation"], x["b"]) for x in store["sourceLinks"]}
    for item in store["sourceLinks"]:
        if (item["b"], item["relation"], item["a"]) in links and item["a"] < item["b"]:
            problem("source-endpoints", item["edit"], "the same relation in both directions")
    for item in store["propertyTerms"]:
        names = item.get("names")
        if item.get("term") not in classes or not names or not all(isinstance(n, str) and n.strip() for n in names):
            problem("fields", item["edit"], "a property term is an A1 class with names")
    for item in store["annotations"]:
        row = kf["findings"].get(item.get("finding"))
        if row is None or item.get("subject") not in known:
            problem("fields", item["edit"], "unknown finding or polymer")
        elif row["subject"] == item["subject"]:
            warnings.append({"check": "no-op", "edit": item["edit"], "detail": "the finding is filed there already"})
        for held in (kf, k0):
            row = held["findings"].get(item.get("finding"))
            if row is not None and upkeep._approved(row):
                problem("approved-ids", item["edit"], "%s's polymer id was approved by a person" % item["finding"])
    # The refined graph (of the graph edits that passed the checks above): no cycles; no new name for two unrelated
    # polymers unless flagged ambiguous.
    bad = {p["edit"] for p in problems}
    sound = {k: [x for x in graph[k] if x["edit"] not in bad] for k in GRAPH_KEYS}
    sound["polymers"] = [p for p in sound["polymers"] if all(b in base.labels for b in p["broader"])]
    new_ids = {p["id"] for p in sound["polymers"]}
    sound["names"] = [n for n in sound["names"] if n["polymer"] in base.labels or n["polymer"] in new_ids]
    refined = Graph(refine(snapshot, sound)[0])
    on = refined.cycle()
    if on:
        problem("cycles", None, "broader links form a cycle through %s" % on)
    names = [(n["edit"], n["name"], bool((active.get(n["edit"], {}).get("edit") or {}).get("ambiguous")))
             for n in sound["names"]]
    names += [(p["edit"], name, False) for p in sound["polymers"]
              for name in [p["label"], *p.get("abbreviations", []), *p.get("alternateNames", [])]]
    for eid, name, flagged in names:
        for variant in variants(name):
            pairs = [] if on else refined.unrelated(refined.ids(variant))
            if pairs and not flagged:
                problem("ambiguous-names", eid, "%r would name unrelated polymers %s" % (
                    variant, ", ".join("%s and %s" % p for p in pairs[:3])))
    folder = pins.folder("overlay")
    value = {"format": FORMATS["checks"], "at": now(), "ok": not problems, "problems": problems, "warnings": warnings,
             "counts": {t: sum(e.get("type") == t for e in active.values()) for t in pins.TYPES},
             "excluded": excluded, "seedSha256": sha,
             "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                        (folder / "edits.json", folder / "graph-overlay.json", folder / "store-overlay.json",
                         folder / "excluded.json") if p.exists()}}
    if write:
        atomic_json(folder / "checks.json", value, private=True)
    return value


def checked():
    value = check()
    if not value["ok"]:
        raise SystemExit("The overlay checks failed (overlay/checks.json): %s" % "; ".join(
            "%s %s: %s" % (p["check"], p["edit"], p["detail"]) for p in value["problems"][:5]))
    return value


# ----- the stores -----

def _rules():
    spec = importlib.util.spec_from_file_location("refinement_property_rules", RULES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def term_of():
    """A finding's property string -> its A1 class, by A1's map of KF's property strings (None when not in it)."""
    rules, mapping = _rules(), read_json(pins.PROPERTY_MAP)
    return lambda text: (mapping.get(rules.normalize(text or "")) or {}).get("class")


def fill(ws, links, terms):
    """pins.TABLES in the store of `ws`, filled with the source links and property terms given, and every finding
    whose property string A1's map assigns to one of those terms."""
    names = {}
    for item in terms:
        names.setdefault(item["term"], [])
        names[item["term"]] += [n.strip() for n in item["names"] if n.strip() not in names[item["term"]]]
    db = sqlite3.connect(knowledge.database(ws))
    try:
        db.executescript(pins.TABLES)
        for item in links:
            evidence = json.dumps({"edit": item["edit"], "evidence": item.get("evidence"),
                                   "evidenceUrl": item.get("evidenceUrl")}, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO source_links VALUES (?,?,?,?)",
                       (item["a"], item["relation"], item["b"], evidence))
        for term, values in sorted(names.items()):
            db.execute("INSERT INTO property_terms VALUES (?,?)", (term, json.dumps(values, ensure_ascii=False)))
        unmapped = 0
        if names:
            term = term_of()
            for identifier, prop in db.execute("SELECT id, property FROM findings ORDER BY id").fetchall():
                value = term(prop)
                unmapped += value is None
                if value in names:
                    db.execute("INSERT OR IGNORE INTO finding_terms VALUES (?,?)", (identifier, value))
        db.commit()
        counts = {t: db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                  for t in ("source_links", "property_terms", "finding_terms")}
    finally:
        db.close()
    return dict(counts, findingsOutsideMap=unmapped)


def _question(qid):
    return upkeep._question_text(QUESTIONS_ROOT, qid)


def _filings(root, rows, subjects, approved):
    """upkeep.polymers' rule against the release of `root`, both halves: a finding with no polymer id is filed by
    `upkeep.file_under` (with its same-source peers), and a finding filed under a family is moved to the member of it
    that its own text names (polyethylene family to HDPE). As upkeep does, a finding the rule would file under a
    polymer outside its current one's members is left as it is (upkeep only lists it for a person). Left alone too: a
    polymer id a person approved (`approved`) and one an annotation edit has just set (where `subjects`, the ids now,
    differs from the row). Returns finding id -> (polymer id, rule), a move's rule ending "(narrowed from its family)",
    and the rules that filed nothing."""
    by_source = {}
    for identifier, row in rows.items():
        if identifier not in approved and subjects[identifier]:
            by_source.setdefault(knowledge.source_key(row["source_doi"], row["source_url"]), set()).add(
                subjects[identifier])
    filed, left = {}, {}
    for identifier, row in sorted(rows.items()):
        current = subjects[identifier]
        if identifier in approved or current != (row["subject"] or ""):
            continue
        peers = set() if current else by_source.get(knowledge.source_key(row["source_doi"], row["source_url"]), set())
        subject, rule = upkeep.file_under(root, row, _question(row["question_id"]), peers)
        if not current:
            if subject:
                filed[identifier] = (subject, rule)
            else:
                left[rule] = left.get(rule, 0) + 1
        elif subject and subject != current and current in knowledge._ancestors(root, subject):
            filed[identifier] = (subject, rule + " (narrowed from its family)")
    return filed, left


def annotate(ws, annotations, plain=None):
    """Polymer ids in the store of `ws`: the approved annotation edits, then upkeep's rule against the release of `ws`
    (`_filings`: both halves) for the findings the edits left alone. A polymer id a person approved is never changed.
    With `plain`, a root with the seed release, a filing the rule makes the same way against the seed graph is left
    out: it is upkeep's, not the ontology's (KF had upkeep's pass on 2026-10-14; K0 predates it), so a refined store
    differs from its baseline only by what the overlay changes."""
    rows = holdings(ws)["findings"]
    approved = {i for i, row in rows.items() if upkeep._approved(row)}
    before = {i: rows[i]["subject"] for i in approved}
    subjects = {i: row["subject"] or "" for i, row in rows.items()}
    changes, absent = {}, []
    for item in annotations:
        identifier = item["finding"]
        if identifier not in rows:
            absent.append(identifier)
            continue
        if identifier in approved:
            raise SystemExit("%s would change %s, whose polymer id a person approved" % (item["edit"], identifier))
        if subjects[identifier] != item["subject"]:
            changes[identifier] = (item["subject"], {"rule": "refinement annotation", "edit": item["edit"]})
            subjects[identifier] = item["subject"]
    filed, left = _filings(ws, rows, subjects, approved)
    same = set()
    if plain is not None:
        seed_filed, _ = _filings(plain, rows, {i: row["subject"] or "" for i, row in rows.items()}, approved)
        same = {i for i, (subject, _) in filed.items() if seed_filed.get(i, (None,))[0] == subject}
    filed = {i: value for i, value in filed.items() if i not in same}
    for identifier, (subject, rule) in filed.items():
        changes[identifier] = (subject, {"rule": "filed by " + rule, "pass": "refinement"})
    stamp = now()[:10]
    with knowledge.connect(ws) as db:
        for identifier, (subject, why) in sorted(changes.items()):
            db.execute("UPDATE findings SET subject=? WHERE id=?", (subject, identifier))
            knowledge._set_detail(db, identifier, polymerFrom=dict(why, was=rows[identifier]["subject"] or "", at=stamp))
            if why["rule"] == "refinement annotation":  # as upkeep.corrections, which reindexes what it changes
                knowledge._reindex(db, identifier)
    after = holdings(ws)["findings"]
    if any(after[i]["subject"] != subject for i, subject in before.items()):
        raise SystemExit("A polymer id a person approved changed in %s" % ws)
    report = {"edits": sum(w["rule"] == "refinement annotation" for _, w in changes.values()), "absentFindings": absent,
              "filedByRule": len(filed), "byRule": {}, "sameWithSeedGraph": sorted(same), "leftWithoutId": left,
              "approvedLeftAlone": len(approved)}
    for _, (_, rule) in filed.items():
        report["byRule"][rule] = report["byRule"].get(rule, 0) + 1
    return report


def table_hash(ws):
    """The three tables of pins.TABLES in the store of `ws`, counted and hashed (None when the store has none)."""
    db = sqlite3.connect(knowledge.database(ws).as_uri() + "?mode=ro", uri=True)
    try:
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = pins.TABLE_NAMES
        if not present & set(tables):
            return None
        rows = {t: db.execute("SELECT * FROM %s ORDER BY 1, 2" % t).fetchall() if t in present else None for t in tables}
    finally:
        db.close()
    return {**{t: (len(r) if r is not None else None) for t, r in rows.items()},
            "sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:16]}


def give(ws, groups, store, plain):
    """The store side of `groups` in the store of `ws`, from the store overlay `store`: pins.TABLES with the source
    links and property terms (`fill`), and polymer ids (`annotate`; `plain` is a root with the seed release). Returns
    what was done."""
    report = {}
    if {"source-link", "property-term"} & set(groups):
        report["tables"] = fill(ws, store["sourceLinks"] if "source-link" in groups else [],
                                store["propertyTerms"] if "property-term" in groups else [])
    if "name/family" in groups:
        report["annotations"] = annotate(ws, store["annotations"], plain)
    return report


def make_store(name, base, releases, groups=(), store=None, plain=None):
    """stores/workspaces/<name> (`pins.store`), made once with driver.workspace from the read-only store root `base`
    and the release of the root `releases`, then given the store side of `groups` from the store overlay `store`
    (`give`); built under a temporary name. Its build report is kept in it as refinement.json. `plain` is a root with
    the seed release. A store already built is kept only when its report records the same base, release, groups and
    store edits."""
    folder, final = pins.folder("stores"), pins.store(name)
    want = {"baseFingerprint": driver.fingerprint(base),
            "release": read_json(Path(releases) / "releases/current.json")["release_id"], "groups": list(groups),
            "edits": sorted({x["edit"] for k in STORE_KEYS for x in (store or {}).get(k, [])})}
    if final.exists():
        built = read_json(final / "refinement.json")
        if {k: built.get(k) for k in want} != want:
            raise SystemExit("%s was built from other inputs (%s) than those in force now; it is never rebuilt over"
                             % (final, ", ".join(k for k in want if built.get(k) != want[k])))
        return final
    building = name + ".building"
    shutil.rmtree(pins.store(building), ignore_errors=True)
    ws = driver.workspace(folder, building, releases=releases, store=base)
    report = dict(want, name=name, base=Path(base).name, builtAt=now())
    report.update(give(ws, groups, store, plain))
    atomic_json(ws / "refinement.json", report, private=True)
    ws.rename(final)
    return final


def describe(ws):
    """A store root's fingerprint: driver.fingerprint with the hash of pins.TABLES (`tables`, null without them)."""
    return dict(driver.fingerprint(ws), tables=table_hash(ws))


# ----- the build -----

def seed_root():
    """overlay/seed-root: the empty overlay's release, which must be the pinned release (the baseline arms use it)."""
    root = pins.folder("overlay") / "seed-root"
    release_id = release(root)
    if release_id != pins.PINS["release"]:
        shutil.rmtree(root)
        raise SystemExit("The empty overlay built %s, not the pinned release %s: the build is not reproducible here"
                         % (release_id, pins.PINS["release"]))
    return root


def graph_root(root, graph):
    """The refined release of `graph` in the root `root`, built once and read back through search's own readers."""
    release(root, graph)
    verify(root, graph)
    return root


def _kf():
    if driver.fingerprint(pins.KF) != pins.PINS["kf"]:
        raise SystemExit("%s is not KF (fingerprint %s)" % (pins.KF, driver.fingerprint(pins.KF)))


def measured(active, excluded, commit):
    """mine/effects.json (`mine.py effects`), refused unless it is complete, was measured on the inputs in force now
    (`mine.effect_inputs`: the overlay's files, the mined pool, the code), measured every edit in force, and every edit
    it dropped is excluded. Returns its SHA-256."""
    from refinement import mine
    path = pins.FOLDERS["mine"] / "effects.json"
    if not path.exists():
        raise SystemExit("mine/effects.json is missing: run mine.py effects (the drop step) first")
    value = read_json(path)
    problems = []
    if value.get("format") != mine.FORMATS["effects"] or not value.get("complete"):
        problems.append("it is not a complete measurement")
    elif value.get("inputs") != mine.effect_inputs(commit):
        problems.append("it was measured on other inputs than those in force now")
    else:
        problems += ["it did not measure %s" % e for e in sorted(set(active) - set(value["edits"]))]
        problems += ["%s, which it dropped, is not excluded" % e for e in value["dropped"] if e not in excluded]
    if problems:
        raise SystemExit("mine/effects.json does not cover this build: " + "; ".join(problems[:5]))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    """The freeze: checks, the drop step's effects (`measured`), overlay/seed-root (the pinned release),
    overlay/release-root (release O), the stores KF, KF-refined, K0 and K0-refined, then overlay/fingerprint.json. Each
    part is built once; a rerun finishes what an interrupted one left, never over a part built from other inputs, and
    never rebuilds. One build or root_for at a time (overlay/build.lock)."""
    with locked(pins.folder("overlay") / "build.lock"):
        return _build()


def _build():
    folder = pins.folder("overlay")
    if (folder / "fingerprint.json").exists():
        return read_json(folder / "fingerprint.json")
    commit = pins.frozen()
    checks = checked()
    _kf()
    active, graph, store, excluded = overlays()
    effects = measured(active, excluded, commit)
    plain, refined = seed_root(), graph_root(folder / "release-root", graph)
    stores = {}
    for name in ("KF", "K0"):
        base = BASES[name]()
        stores[name] = make_store(name, base, plain)
        stores[name + "-refined"] = make_store(name + "-refined", base, refined, tuple(pins.GROUPS), store, plain)
    value = {"format": FORMATS["fingerprint"], "at": now(), "code": commit, "checks": checks["inputs"],
             "effectsSha256": effects, "excluded": excluded, "edits": sorted(active),
             "releases": {"seed": read_json(plain / "releases/current.json")["release_id"],
                          "refined": read_json(refined / "releases/current.json")["release_id"]},
             "overlays": {"graph": digest(graph), "store": digest(store)},
             "stores": {name: describe(ws) for name, ws in stores.items()},
             "roots": {name: str(ws) for name, ws in stores.items()},
             "builds": {name: read_json(ws / "refinement.json") for name, ws in stores.items()}}
    atomic_json(folder / "fingerprint.json", value, private=True)
    common.emit(folder, "overlay-built", releases=value["releases"], edits=len(active))
    return value


def root_for(groups, base="KF"):
    """A workspace root whose store and release carry only the approved edits (in force) of `groups` (keys of
    pins.GROUPS): the refined release when "name/family" is among them, else the seed release; built once per
    combination and content under stores/, for the group totals of the edit-effect replay and the attribution of
    reachable hops to groups."""
    groups = tuple(sorted(set(groups)))
    if not set(groups) <= set(pins.GROUPS) or base not in BASES:
        raise ValueError("Groups are %s; bases %s" % (", ".join(pins.GROUPS), ", ".join(BASES)))
    with locked(pins.folder("overlay") / "build.lock"):
        return _root_for(groups, base)


def _root_for(groups, base):
    pins.frozen()
    checked()
    active, graph, store, excluded = overlays()
    kinds = {kind for group in groups for kind in pins.GROUPS[group]}
    graph = {k: graph[k] if KEYS[k] in kinds else [] for k in GRAPH_KEYS}
    store = {k: store[k] if KEYS[k] in kinds else [] for k in STORE_KEYS}
    content = digest({"graph": graph, "store": store})[:10]
    name = "%s+%s-%s" % (base, "+".join(g.replace("/", "-") for g in groups) or "none", content)
    folder = pins.folder("stores")
    plain = seed_root()
    releases = plain if _empty(graph) else graph_root(folder / ("graph-" + digest(graph)[:10]), graph)
    ws = make_store(name, BASES[base](), releases, groups, store, plain)
    roots = read_json(folder / "roots.json") if (folder / "roots.json").exists() else {}
    if name not in roots:
        roots[name] = {"root": str(ws), "groups": list(groups), "excluded": excluded, "fingerprint": describe(ws),
                       "build": read_json(ws / "refinement.json")}
        atomic_json(folder / "roots.json", roots, private=True)
    return ws


def edit_root(folder, edits, in_force=None, plain=None, base="KF"):
    """A workspace root carrying only the approved `edits` (ids in force), for the edit-effect replay (`mine.py
    effects`): a release of the seed plus their graph edits, built and read back as release O is (`graph_root`, in
    `folder/graph`; the seed release when they have none), and a copy of `base` given their store side as a refined
    store is (`give`: their source links or property terms, their polymer ids, and upkeep's rule against their
    release). Everything goes into `folder`, which the caller deletes once it has replayed; nothing is recorded under
    stores/. `in_force` is `overlays()`'s value and `plain` the seed root (`seed_root()`), both read once by a caller
    building many."""
    active, graph, store, _ = in_force or overlays()
    edits = set(edits)
    if edits - set(active):
        raise ValueError("Not approved edits in force: %s" % ", ".join(sorted(edits - set(active))))
    graph = {k: [x for x in graph[k] if x["edit"] in edits] for k in GRAPH_KEYS}
    store = {k: [x for x in store[k] if x["edit"] in edits] for k in STORE_KEYS}
    groups = [g for g, kinds in pins.GROUPS.items() if any(active[e]["type"] in kinds for e in edits)]
    plain = plain or seed_root()
    folder = Path(folder)
    releases = plain if _empty(graph) else graph_root(folder / "graph", graph)
    ws = driver.workspace(folder, "root", releases=releases, store=BASES[base]())
    give(ws, groups, store, plain)
    return ws


def status():
    folder = pins.FOLDERS["overlay"]
    value = {"checks": None, "seedRoot": None, "releaseRoot": None, "fingerprint": None, "stores": {}}
    if (folder / "checks.json").exists():
        checks = read_json(folder / "checks.json")
        value["checks"] = {k: checks[k] for k in ("at", "ok", "counts")} | {"problems": len(checks["problems"])}
    for key, name in (("seedRoot", "seed-root"), ("releaseRoot", "release-root")):
        if (folder / name / "releases/current.json").exists():
            value[key] = read_json(folder / name / "releases/current.json")["release_id"]
    if (folder / "fingerprint.json").exists():
        value["fingerprint"] = read_json(folder / "fingerprint.json")["at"]
    workspaces = pins.FOLDERS["stores"] / "workspaces"
    if workspaces.exists():
        value["stores"] = {p.name: driver.fingerprint(p) for p in sorted(workspaces.iterdir())
                           if p.is_dir() and (p / "refinement.json").exists()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["check", "seed", "build", "status"])
    args = parser.parse_args()
    if args.command == "check":
        value = check()
        print(json.dumps({k: value[k] for k in ("ok", "counts", "problems", "warnings")}, indent=1, ensure_ascii=False))
        raise SystemExit(0 if value["ok"] else 1)
    if args.command == "seed":
        with locked(pins.folder("overlay") / "build.lock"):
            root = seed_root()
        print(json.dumps({"seedRoot": str(root), "release": read_json(root / "releases/current.json")["release_id"]}))
    elif args.command == "build":
        value = build()
        print(json.dumps({"releases": value["releases"], "edits": len(value["edits"]), "stores": value["stores"]},
                         indent=1))
    else:
        print(json.dumps(status(), indent=1))


if __name__ == "__main__":
    main()
