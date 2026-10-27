#!/usr/bin/env python3
"""The index of Figures 3a–f, 4b (records part), 4d and 4e on KF, and Table 1 (experiment A1). No engine calls.

Run after the KF builds (`dataset_build.py --kf`, `properties/build.py --kf`, `properties_check.py --kf`,
`tg_landscape.py`, `loop_build.py --kf`). Reads their outputs and K3's (`dataset/`, `loop/`, `properties/`,
`properties-check/`, built 2026-10-13), all read-only, and writes, each with KF's pins (`kf.meta`):

- `figures-kf/panels.json`: for each panel, the files and keys a figure script reads, and its headline numbers on KF
  beside the same numbers recomputed from K3's outputs by the same code (`headline`), so a difference is the store's,
  not the arithmetic's; `definitions` says what each count that can be read two ways counts.
- `table1/table1.json`: the seed (the graph release's record counts), the knowledge base at the freeze (findings by
  status, notes, sources, polymers, reviews by engine), the questions by kind and stage, the engines, models and
  prompt versions of each stage, and new tokens by phase from the ledgers: the 200-task run's call list, the
  campaign's call ledger (calls owned by campaign tasks), and the main store's ledger for the reviews of the
  2026-10-14/16 cleanup that set KF's statuses.

    python -B figure_data.py
"""
import collections, csv, json, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, analysis_dir, run_dir  # noqa: E402
from analysis import kf  # noqa: E402
from analysis.properties.build import method_group  # noqa: E402
from oopc.calls import new_tokens  # noqa: E402  (pure)

KF_FOLDERS = {"dataset": "dataset-kf", "loop": "loop-kf", "properties": "properties-kf", "check": "properties-check-kf",
              "tg": "tg-landscape"}
K3_FOLDERS = {"dataset": "dataset", "loop": "loop", "properties": "properties", "check": "properties-check"}
CAMPAIGN, RUN200 = run_dir("2026-10-campaign"), run_dir("2026-10-03-200")
MAIN_LEDGER = ROOT / ".oopc/loop/calls"
CLEANUP_FROM = "2026-10-13"  # the main store's review calls from this day on are the cleanup's (the freeze: 10-16)
STAGES = ["run200", "wave1", "wave2", "wave3"]


def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def share(part, whole, digits=4):
    return round(part / whole, digits) if whole else None


# ----------------------------------------------------------------------------------------------- panels

def properties(folder):
    """Fig. 3c and the Tg method split of 3d, from a property map's map.json and per-finding table."""
    mapped = jread(folder / "map.json")
    found = rows(folder / "finding_classes.csv")
    total = len(found)
    kinds = collections.Counter(r["kind"] for r in found)
    per_class = collections.Counter(r["property_class"] for r in found if r["kind"] == "material-property")
    by = collections.Counter()
    for m in mapped.values():
        by[m["assignedBy"]] += m["findings"]
    unassigned = {s: m["findings"] for s, m in mapped.items() if m["class"] == "unclassified"}
    pairs = [r for r in rows(folder / "findings_by_subject_class.csv") if r["kind"] == "material-property"]
    return {"findings": total, "strings": len(mapped),
            "materialPropertyClassesWithFindings": len(per_class),
            "atLeast10": sum(n >= 10 for n in per_class.values()), "atLeast50": sum(n >= 50 for n in per_class.values()),
            "materialPropertyPairs": len(pairs), "polymersWithMaterialProperties": len({r["subject"] for r in pairs}),
            "findingsByKind": dict(kinds.most_common()),
            "materialPropertyShare": share(kinds["material-property"], total),
            "ruleAssignedShare": share(by["rule"], total), "manualAssignedShare": share(by["model"], total),
            "unassigned": {"strings": len(unassigned), "findings": sum(unassigned.values()),
                           "nonEmptyStrings": sum(1 for s in unassigned if s),
                           "nonEmptyFindings": sum(n for s, n in unassigned.items() if s)},
            "tgMethodSplit": dict(collections.Counter(method_group(r["method"], r["method_in_conditions"]) for r in found
                                                      if r["property_class"] == "glass-transition-temperature"))}


def headline(folders):
    """The headline numbers of each panel from one store's outputs (folder names under analysis/)."""
    d = {k: analysis_dir(v) for k, v in folders.items()}
    growth, coverage = jread(d["dataset"] / "growth.json"), jread(d["dataset"] / "coverage.json")
    sources, completeness = jread(d["dataset"] / "sources.json"), jread(d["dataset"] / "completeness.json")
    reuse, revisits = jread(d["loop"] / "reuse.json"), jread(d["loop"] / "revisits.json")
    trajectory, check = jread(d["loop"] / "trajectory.json"), jread(d["check"] / "agreement.json")
    end, cs, ss = growth["points"][-1], coverage["summary"], sources["summary"]
    classes = sorted(coverage["classes"], key=lambda c: (c["withFindings"] / c["polymers"], c["class"]))
    spot = completeness["spotChecksOfAdded"]
    out = {
        "3a": {"answers": end["answer"], "findings": end["findings"], "notes": end["notes"], "sources": end["sources"],
               "sourcesWithDoi": end["sourcesWithDoi"], "polymers": end["polymers"],
               "answersByDefinition": {"withDepositRow": end["answer"],
                                       "savedFindingOrNote": sum(1 for p in growth["points"][1:]
                                                                 if p["newFindings"] or p["newNotes"]),
                                       "savedFinding": sum(1 for p in growth["points"][1:] if p["newFindings"])},
               "segmentEnds": [{"label": SEGMENTS.get(r["run"], r["run"]), "run": r["run"],
                                "findings": r["endState"]["findings"]["total"]} for r in growth["byRun"]]},
        "3b": {k: cs[k] for k in ("polymers", "withFindings", "atLeast10", "atLeast50", "findingsWithoutPolymerId",
                                  "shareWithoutPolymerId", "top10ShareOfFindingsWithId")} | {
            "top10ShareOfAllFindings": share(sum(sorted((p["findings"] for p in coverage["polymers"]), reverse=True)[:10]),
                                             end["findings"]["total"]),
            "leastCoveredClasses": [{k: c[k] for k in ("class", "polymers", "withFindings")} for c in classes[:3]]},
        "3c": dict(properties(d["properties"]), blindCheck={
            "sameClass": check["all"]["sameClass"], "sameClassWeighted": check["all"]["sameClassWeighted"],
            "propertyVsNot": check["all"]["propertyVsNot"], "materialProperties": check["materialProperties"],
            "coverage": check.get("coverage")}),
        "3e": {k: ss[k] for k in ("sources", "withDoi", "yieldedFindings", "readWithoutFindings", "hostsOfCitedUrls",
                                  "medianYear", "crossref", "doiTitleCheck")} | {
            "keepingQueryString": {k: v for k, v in (ss.get("keepingQueryString") or {}).items() if k != "about"} or None,
            "byType": {t["name"]: {"sources": t["sources"], "findings": t["findings"]} for t in sources["byType"]},
            "topPublishers": {p["name"]: p["sources"] for p in sources["byPublisher"][:5]},
            "openAccessShareOfDoiSources": sources["openAccess"]["withDoi"]["share"],
            "doiProblems": len(sources["doiProblems"]["rows"])},
        "3f": {"fields": {k: completeness["fields"][k]["share"] for k in ("conditions", "locator", "excerpt", "unit",
                                                                           "numericValue", "polymerId")},
               "statusMix": {k: v["count"] for k, v in completeness["statusMix"].items()},
               "spotChecksCampaign": {k: v["total"] for k, v in spot["campaign"].items()},
               "spotChecksAll": {k: v["total"] for k, v in spot["all"].items()},
               "flaggedCampaign": completeness["flaggedOutcomes"]["campaign"],
               "needsCheckingAccessProblems": completeness["reviewReasons"]["Needs checking"]["accessProblems"]},
        "4b": {k: {m: v[m] for m in ("pairs", "medianTokenRatio", "medianWebRatio", "noWeb", "citingFindings")}
               for k, v in revisits["summary"]["campaignByType"].items()} | {
            "run200Repeats": {m: revisits["summary"]["run200Repeats"][m] for m in ("pairs", "medianTokenRatio",
                                                                                 "totalsWebRatio")}},
        "4d": {"findings": reuse["totals"]["findings"], "everReturnedShare": reuse["totals"]["everReturnedShare"],
               "everCitedShare": reuse["totals"]["everCitedShare"],
               "citationsOfFindings": reuse["totals"]["citationsOfFindings"],
               "medianLagToFirstCitation": reuse["firstCitationLag"]["answers"]["median"],
               "findingShareOfCitations": {"campaign800Answers": reuse["findingShareOfCitations"]["campaign"]["records"],
                                           "all1092Answers": reuse["findingShareOfCitations"]["wholeHistory"]},
               "doseResponse": {b["bin"]: b["share"] for b in reuse["doseResponse"]["primary"]["bins"]},
               "byStatus": {k: {"findings": v["findings"], "everCited": v["everCited"]}
                            for k, v in reuse["byStatus"].items()}},
        "4e": {s: {"researcherFlaggedShare": v["flagged"]["researcherFlaggedShare"],
                   "emptyExcerptShare": v["excerpts"]["emptyShare"], "reviewPerResearchToken": v["reviewPerResearchToken"],
                   "revisitTokenRatioExact": v["revisitMedianTokenRatio"]["exact"],
                   "answersWithoutWeb": v["answersWithoutWeb"], "answersCitingFindings": v["answersCitingFindings"],
                   "findings": v["findings"]} for s, v in trajectory["stages"].items()},
    }
    out["3d"] = {"tgMethodSplitMapRule": out["3c"].pop("tgMethodSplit")}
    if "tg" in d:
        tg = jread(d["tg"] / "tg_landscape.json")
        out["3d"] = dict({k: tg[k] for k in ("tgMethodSplit", "tgMethodFrom", "tgFindings", "tgWithReadableValue",
                                             "tmMethodSplit", "rows", "parse")},
                         polymers=len(tg["polymers"]), withoutReadableValue=len(tg["withoutReadableValue"]),
                         notTgOrTmValues=len(tg["notTgOrTmValues"]),
                         dmaAboveDsc={k: v for k, v in tg["dmaAboveDsc"].items() if k != "byPolymer"}, **out["3d"])
    return out


SEGMENTS = {"imported (0.11 records)": "imported seed: the 0.11 records (origin import, created 2026-09-27)",
            "before the 200-task run": "before the 200-task run: the 2026-10-02 store",
            "200-task run": "end of the 200-task run", "wave 1": "end of campaign wave 1",
            "wave 2": "end of campaign wave 2", "wave 3": "end of campaign wave 3: the whole store"}
DEFINITIONS = {
    "answersByDefinition": "withDepositRow: research and ask questions with a deposit row (the growth curve's answers); "
                           "savedFindingOrNote: those of them whose findings or source notes are in the store; "
                           "savedFinding: those with a finding",
    "segmentEnds": "findings in the store after each segment of the growth curve (findings of its answers, final "
                   "presence); the first two are the imported seed and the store as it stood on 2026-10-02",
    "top10ShareOfFindingsWithId": "the 10 best-covered polymers' findings over findings with a polymer id; "
                                  "top10ShareOfAllFindings uses all findings as the denominator",
    "sources": "distinct sources by the store's own key (oopc.knowledge.source_key), which drops a URL's query string "
               "and fragment and so joins documents told apart only by their query (5 CiteSeerX papers, 2 Ensinger data "
               "sheets, 2 EPA NEPIS documents, and a Plexiglas page and its PDF); keepingQueryString gives the counts "
               "with the query string kept",
    "findingShareOfCitations": "finding ids among all citations: campaign800Answers over the 800 campaign answers (the "
                               "plan's 0.632), all1092Answers over every completed answer",
    "tgMethodSplit": "Fig. 3d's rule (tg_landscape.json rules): Tg findings with one readable temperature, the method "
                     "read from the property string, else the conditions; tgMethodSplitMapRule is the property map's "
                     "cruder split over every finding of its Tg class (DSC wins when either text names DSC or a "
                     "heating run), the only one K3's outputs allow",
}
FILES = {
    "3a": ["dataset-kf/growth.json: points (one per answer; 0 = import), byRun, markers"],
    "3b": ["dataset-kf/coverage.json: polymers (every graph polymer, with class and counts), classes"],
    "3c": ["properties-kf/findings_by_subject_class.csv (heatmap input)", "properties-kf/finding_classes.csv",
           "properties-kf/map.json", "properties-kf/meta.json", "properties-check-kf/agreement.json"],
    "3d": ["tg-landscape/tg_landscape.csv: one row per finding", "tg-landscape/tg_landscape.json: polymers in order"],
    "3e": ["dataset-kf/sources.json: rows, byType, byPublisher, publicationYear, openAccess, doiProblems"],
    "3f": ["dataset-kf/completeness.json: fields, statusMix, spotChecksOfAdded, flaggedOutcomes, reviewReasons"],
    "4b": ["loop-kf/revisits.json: summary.campaignByType, pairs (records part only)"],
    "4d": ["loop-kf/reuse.json: ccdfReturnedSessions, ccdfCitedAnswers, byStatus, firstCitationLag, doseResponse, "
           "findingShareOfCitations"],
    "4e": ["loop-kf/trajectory.json: stages", "loop-kf/curve.json: campaign and history blocks"],
}


# ----------------------------------------------------------------------------------------------- Table 1

def ledger(records):
    """New tokens and calls by phase over call records (dicts with phase, and newTokens or usage)."""
    tokens, calls = collections.Counter(), collections.Counter()
    for c in records:
        tokens[c.get("phase")] += c["newTokens"] if c.get("newTokens") is not None else (new_tokens(c.get("usage")) or 0)
        calls[c.get("phase")] += 1
    return {p: {"calls": calls[p], "newTokens": tokens[p]} for p in sorted(calls)}


def table1(store):
    graph = jread(ROOT / "releases" / kf.RELEASE_ID / "manifest.json")
    growth = jread(analysis_dir("dataset-kf") / "growth.json")
    sources = jread(analysis_dir("dataset-kf") / "sources.json")["summary"]
    coverage = jread(analysis_dir("dataset-kf") / "coverage.json")["summary"]
    trajectory = jread(analysis_dir("loop-kf") / "trajectory.json")
    db = sqlite3.connect(Path(store).resolve().as_uri() + "?mode=ro", uri=True)
    status = dict(db.execute("SELECT status, COUNT(*) FROM findings GROUP BY status"))
    notes = db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    reviews = [dict(zip(("engine", "status", "day"), r)) for r in
               db.execute("SELECT engine, status, substr(started_at, 1, 10) FROM reviews")]
    db.close()
    campaign = jread(CAMPAIGN / "questions.json")
    run200 = jread(RUN200 / "questions.json")
    owners = {t["taskId"] for t in campaign}
    calls = [jread(p) for p in sorted((CAMPAIGN / "workspace/.oopc/loop/calls").glob("*.json"))]
    main = [jread(p) for p in sorted(MAIN_LEDGER.glob("*.json"))]
    cleanup = [c for c in main if c.get("phase") == "review" and (c.get("startedAt") or "") >= CLEANUP_FROM]
    labels = {"supported": "Reviewed", "accepted": "Added", "uncertain": "Needs checking", "unsupported": "Rejected"}
    return {
        "seed": {"graphRelease": kf.RELEASE_ID, "records": graph["record_count"], "byType": graph["counts"],
                 "seedCounts": graph["seed_counts"], "seedSnapshotSha256": graph["seed_snapshot_sha256"]},
        "knowledge": {"snapshot": kf.SNAPSHOT_ID, "findings": sum(status.values()),
                      "byStatus": {labels[k]: status.get(k, 0) for k in labels}, "notes": notes,
                      "sources": sources["sources"], "sourcesWithDoi": sources["withDoi"],
                      "sourcesYieldingFindings": sources["yieldedFindings"],
                      "sourcesKeepingQueryString": sources["keepingQueryString"],
                      "polymersWithFindings": coverage["withFindings"], "graphPolymers": coverage["polymers"],
                      "findingsWithoutPolymerId": coverage["findingsWithoutPolymerId"],
                      "answers": growth["answers"],
                      "definitions": {k: DEFINITIONS[k] for k in ("sources", "answersByDefinition")},
                      "reviews": {"calls": len(reviews),
                                  "byEngine": dict(collections.Counter(r["engine"] for r in reviews).most_common()),
                                  "byStatus": dict(collections.Counter(r["status"] for r in reviews).most_common()),
                                  "cleanup": sum(r["day"] >= CLEANUP_FROM for r in reviews)}},
        "questions": {
            "answersByStage": trajectory["meta"]["answersByStage"], "completedAnswers": trajectory["meta"]["answers"],
            "campaignFirstAsksByKind": dict(collections.Counter(t["kind"] for t in campaign if not t.get("revisit"))
                                            .most_common()),
            "campaignRevisitsByType": dict(collections.Counter(t["revisit"] for t in campaign if t.get("revisit"))
                                           .most_common()),
            "run200": {"distinct": sum(not t.get("parent") for t in run200),
                       "exactRepeats": sum(bool(t.get("parent")) for t in run200)}},
        "enginesModelsPrompts": {
            "byRun": {r["run"]: {"answers": r["answers"], "engines": r["engines"], "promptVersions": r["promptVersions"]}
                      for r in growth["byRun"]},
            "promptLineage": [m["promptVersion"] for m in growth["markers"] if m["kind"] == "prompt version"],
            "partA": {"prompt": kf.PROMPT, "codeTag": kf.TAG, "research": "codex gpt-6.1-sol",
                      "reviewAndChecks": "codex gpt-6.1-sol", "improverAndBlindScoring": "claude-code claude-opus-5-5"}},
        "tokens": {
            "about": "new tokens (uncached input + output) by phase. run200: the 200-task run's call list; campaign: the "
                     "campaign ledger's calls owned by campaign tasks (answer-check includes the Codex rechecks; the "
                     "campaign report counts first checks only); cleanup: review calls in the main store's ledger from "
                     "%s to the freeze, which re-reviewed findings and set KF's statuses. The answers before the "
                     "200-task run have no ledger here." % CLEANUP_FROM,
            "run200": ledger(jread(RUN200 / "calls.json")),
            "campaign": ledger(c for c in calls if c.get("owner") in owners),
            "campaignReport": jread(CAMPAIGN / "report.json")["summary"]["cost"]["phases"],
            "cleanup": ledger(cleanup),
            "reviewPerResearchTokenByStage": {s: trajectory["stages"][s]["reviewPerResearchToken"] for s in STAGES}},
    }


def main():
    store = kf.store()
    kf_numbers, k3_numbers = headline(KF_FOLDERS), headline(K3_FOLDERS)
    panels = {p: {"files": FILES[p], "KF": kf_numbers[p], "K3": k3_numbers.get(p)} for p in FILES}
    for name, folder, value in (("panels.json", "figures-kf", {"definitions": DEFINITIONS, "panels": panels}),
                                ("table1.json", "table1", table1(store))):
        out = analysis_dir(folder)
        out.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"meta": kf.meta("figure_data.py"), **value}, ensure_ascii=False, indent=1)
        if "/Users/" in text:
            raise SystemExit("refusing to write a local path into " + name)
        (out / name).write_text(text + "\n", encoding="utf-8")
        print("wrote", folder + "/" + name)


if __name__ == "__main__":
    main()
