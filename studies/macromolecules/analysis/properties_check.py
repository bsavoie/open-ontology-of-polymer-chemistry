"""Agreement between the E3 property map and the blind second classification (study plan, Fig. 3c; E3).

Written 2026-10-13 when the study code moved to the repository: the agreement in
`.oopc/study/analysis/properties-check/agreement.json` was computed then without a saved script; this recomputes it
from the check's inputs and reproduces the recorded file exactly. Reads, read-only:

- `properties-check/input.json`: the 600 strings given to the blind classifier (300 most frequent, 300 random), with
  their finding counts and stratum;
- `properties-check/blind.json`: the blind session's class and confidence for each string, by number;
- `properties/map.json`: the map's class for each string;
- `vocabulary.json` (tracked beside build.py): each class's category and kind.

Agreement is the share of strings (and, "Weighted", of findings) on which the two classifications give the same class,
the same category, the same kind, and the same answer to "material property or not"; for all 600 strings, each
stratum, and the strings the blind session was and was not confident about. Also: the most common (map, blind) class
pairs among disagreements (25), the 30 disagreeing strings with the most findings (the key says 50, as recorded), and
class agreement among strings the map calls material properties.

    python properties_check.py           # recompute and compare with the recorded agreement.json
    python properties_check.py --write   # write agreement.json to the private folder
"""
import argparse, collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, analysis_dir  # noqa: E402

CHECK = analysis_dir("properties-check")
MAP = analysis_dir("properties") / "map.json"
VOCABULARY = STUDY / "analysis" / "properties" / "vocabulary.json"
PROPERTY = "material-property"


def agreement(rows, classes):
    """Shares of strings and of findings on which map and blind agree, by class, category, kind and property-or-not."""
    findings = sum(r["findings"] for r in rows)
    tests = {"sameClass": lambda m, b: m["id"] == b["id"],
             "sameCategory": lambda m, b: m["category"] == b["category"],
             "sameKind": lambda m, b: m["kind"] == b["kind"],
             "propertyVsNot": lambda m, b: (m["kind"] == PROPERTY) == (b["kind"] == PROPERTY)}
    value = {"strings": len(rows), "findings": findings}
    for name, same in tests.items():
        agree = [r for r in rows if same(classes[r["map"]], classes[r["blind"]])]
        value[name] = round(len(agree) / len(rows), 3)
        value[name + "Weighted"] = round(sum(r["findings"] for r in agree) / findings, 3)
    return value


def build():
    given = json.loads((CHECK / "input.json").read_text())
    blind = {item["n"]: item for item in json.loads((CHECK / "blind.json").read_text())["items"]}
    mapped = json.loads(MAP.read_text())
    classes = {c["id"]: c for c in json.loads(VOCABULARY.read_text())["classes"]}
    rows = [{"n": s["n"], "string": s["string"], "findings": s["findings"], "stratum": s["stratum"],
             "map": mapped[s["string"]]["class"], "blind": blind[s["n"]]["class"],
             "confident": blind[s["n"]]["confident"]} for s in given["strings"]]
    groups = {"all": rows,
              "top300": [r for r in rows if r["stratum"] == "top300"],
              "random300": [r for r in rows if r["stratum"] == "random300"],
              "confident": [r for r in rows if r["confident"]],
              "notConfident": [r for r in rows if not r["confident"]]}
    value = {name: agreement(group, classes) for name, group in groups.items()}
    disagreeing = [r for r in rows if r["map"] != r["blind"]]
    value["topDisagreements"] = [{"map": m, "blind": b, "strings": n} for (m, b), n in
                                 collections.Counter((r["map"], r["blind"]) for r in disagreeing).most_common(25)]
    value["disagreeingTop50"] = [{"string": r["string"], "findings": r["findings"], "map": r["map"], "blind": r["blind"]}
                                 for r in sorted(disagreeing, key=lambda r: -r["findings"])[:30]]
    properties = agreement([r for r in rows if classes[r["map"]]["kind"] == PROPERTY], classes)
    value["materialProperties"] = {k: properties[k] for k in ("strings", "sameClass", "sameClassWeighted")}
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write agreement.json to %s" % CHECK.name)
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False)
    recorded = CHECK / "agreement.json"
    if args.write:
        recorded.write_text(text)
        print("wrote", recorded.name)
    else:
        same = recorded.exists() and recorded.read_text() == text
        print(text)
        print("identical to the recorded agreement.json" if same else "differs from the recorded agreement.json")
        return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
