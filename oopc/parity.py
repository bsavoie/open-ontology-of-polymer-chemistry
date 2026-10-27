"""The parity set: the ontology researcher beside a plain web session, on fixed questions.

This is a guardrail, not a gate. Each run answers the questions in
`benchmarks/parity.json` two ways on one engine:

- **direct**: a plain session with web search only, as you would get from Claude
  Code or Codex yourself. Its answers are frozen per engine and model, because
  the scaffold changes, not the plain session; a new model gets a new plain
  baseline.
- **ontology**: the real researcher prompt and tools, in both turns (the answer,
  then the findings and sources by resuming the session). Its findings are *not*
  saved, so rerunning the set never changes the knowledge it measures. It
  records the seconds to the answer, the deposit's seconds and the new tokens of
  both turns.

Every run checks both arms again, one right after the other, with the same
checker, so a difference never comes from a source that opened one day and not
another; the sources both arms cite are captured first. The report leads with
the measures that do not depend on source access (contradicted statements,
complete answers, sourced results); passes come second. Runs are on demand
(`oopc parity run`) and record which version of the researcher's instructions
they measured; `oopc parity compare A B` puts two runs side by side. With
`--canaries` a run also reviews five **canaries** (real findings with a value,
a condition, the source or a title word deliberately changed; the reviewer
must reject them) beside two true controls, one whose method is stated only in
its source's methods section: worth doing when the reviewer's instructions
change. Results stay private under `.oopc/loop/parity/`.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from . import calls, engines, knowledge, reviewer
from .util import atomic_json, now, read_json, resolve_release

SET_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "parity.json"
DIRECT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer", "citations", "limitations"],
                 "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}},
                                "limitations": {"type": "array", "items": {"type": "string"}}}}
DIRECT_PROMPT = ("Answer this polymer-science question. Search the web and read sources as needed. Cite each source you "
                 "rely on by URL right after the claim, keep material, specimen, method and test conditions explicit, and "
                 "state limitations. Return answer (markdown), citations (the URLs) and limitations.\n\nQuestion:\n")
THRESHOLDS = {"maxExtraContradicted": 1, "maxCompleteDeficit": 1, "minCitedFraction": 0.9, "maxMedianTokenRatio": 1.5,
              "minChecked": 6}


def folder(root):
    return knowledge.folder(root) / "parity"


def load_set(path=SET_PATH):
    value = read_json(path)
    if value.get("format") != "oopc-parity-set-v1" or len(value.get("questions", [])) < 2:
        raise ValueError("Parity set is missing or malformed")
    return value


# ----- one arm -----

def _call(root, phase, owner, runner, engine, prompt, schema, **options):
    """One session, retried once on a transient failure, as everywhere else in the loop."""
    for attempt in (1, 2):
        try:
            return calls.invoke(root, phase, owner, runner, engine, prompt, schema, **options)
        except engines.EngineError as error:
            if options.get("persist"):
                engines.discard_session(engine, error.session_id)  # A failed first turn is never resumed.
            if attempt == 2 or not error.retryable:
                raise


def _metrics(result, deposit=None, deposit_failed=False):
    """An arm's time, tokens and lookups. For the researcher, `deposit` is its second turn (a result, or a failed turn's
    usage and seconds): `seconds` is then the time to the answer, `totalSeconds` adds the deposit, and `newTokens` are
    both turns' own. A failed deposit keeps the answer's tokens (its own, when unreported, are unmeasured) and marks the
    arm `depositFailed`: `improve.compare` does not compare such an arm on tokens, and says so."""
    from .task_progress import effort
    turns = [result] + ([deposit] if deposit is not None else [])
    value = effort(dict(result, observedTools=[t for turn in turns for t in turn.get("observedTools") or []]))
    usages = [turn.get("usage") or {} for turn in turns]
    total = sum((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0) for usage in usages)
    new = [calls.new_tokens(usage) for usage in usages]
    metrics = {"seconds": result.get("agentSeconds"), "tokens": total or None,
               "newTokens": None if None in new else sum(new),
               "webCalls": (value.get("webSearches") or 0) + (value.get("pagesRead") or 0),
               "knowledgeLookups": value.get("knowledgeLookups") or 0, "graphLookups": value.get("graphLookups") or 0}
    if deposit is not None:
        metrics.update(answerNewTokens=new[0], depositNewTokens=new[1], depositFailed=bool(deposit_failed),
                       depositSeconds=deposit.get("agentSeconds"))
        if new[1] is None:
            metrics["newTokens"] = new[0]
        metrics["totalSeconds"] = (round(result["agentSeconds"] + deposit["agentSeconds"], 2)
                                   if result.get("agentSeconds") is not None and deposit.get("agentSeconds") is not None
                                   else None)
    return metrics


def web_actions(result):
    """The session's web reading as its stream reported it: each search or page, and whether a page opened."""
    actions = []
    for tool in result.get("observedTools") or []:
        if isinstance(tool, dict) and tool.get("type") == "web_search" and tool.get("action"):
            actions.append({k: tool[k] for k in ("action", "query", "url", "outcome") if tool.get(k)})
    return actions


def answer_direct(root, question, engine, *, runner, timeout):
    result = _call(root, "parity-direct", question["id"], runner, engine, DIRECT_PROMPT + question["question"], DIRECT_SCHEMA, tools=None, web=True,
                   timeout=timeout)
    return {"answer": result["answer"], "metrics": _metrics(result), "engine": result["engine"], "at": now(),
            "webActions": web_actions(result)}


def answer_ontology(root, question, engine, *, runner, timeout, depth, web=True,
                    phases=("parity-ontology", "parity-deposit"), title=None, task=None, owner=None):
    """Both turns, as a question runs them: the answer, then the findings and sources by resuming the session (not
    saved). A failed second turn is recorded beside the answer, which is still checked. `phases` name the two turns in
    the call ledger and `owner` their owner there (default: the trace's run id); the Macromolecules study's researcher
    arm uses its own, with its own trace `title` and `task`."""
    from .ask import ANSWER_SCHEMA, deposit_turn, researcher_prompt, saved_session
    from .trace import TraceStore
    release = resolve_release(root)
    run = TraceStore(root).create(release, title or "Parity · " + question["id"] + " · " + question["question"][:60],
                                  capabilities={"external_source_access": web},
                                  task=task or {"parity": question["id"], "notice": "Parity arm; findings are not saved."})
    tools = knowledge.research_tools(root, release, run.path.name, "researcher")
    prompt = researcher_prompt(question["question"], depth)
    work, result, deposit, failed = engines.session_folder(run.path.name), None, None, None
    owner = owner or run.path.name
    try:
        try:
            result = _call(root, phases[0], owner, runner, engine, prompt, ANSWER_SCHEMA, tools=tools,
                           web=web, timeout=timeout, persist=True, folder=work)
        except engines.EngineError:
            run.finish("failed")
            raise
        try:
            deposit = deposit_turn(root, phases[1], owner, runner, saved_session(result, work),
                                   tools=tools, timeout=timeout, web=web)
        except engines.EngineError as error:
            failed = error
    finally:
        engines.discard_session(engine, (result or {}).get("sessionId"), work)
        if deposit and deposit.get("sessionId") not in (None, (result or {}).get("sessionId")):
            engines.discard_session(engine, deposit["sessionId"])
    run.finish("completed")
    answer = dict(result["answer"])
    if deposit:  # What the second turn wrote, kept with the answer; nothing is saved to the knowledge base.
        answer.update({key: deposit["answer"].get(key) or [] for key in ("findings", "sources")})
    second = deposit or {"usage": failed.usage, "agentSeconds": failed.seconds}
    entry = {"answer": answer, "metrics": _metrics(result, second, failed is not None), "engine": result["engine"],
             "model": result.get("model"), "callId": result.get("callId"), "at": now(), "runId": run.path.name,
             "webActions": web_actions(result) + web_actions(deposit or {})}
    if failed is not None:
        entry["depositError"] = failed.summary()
    return entry


def resolve_sources(root, citations):
    """Citations as sources a checker can open: a finding becomes its source with what it says (statement, value,
    conditions, locator, excerpt) and its status; graph evidence (cited by older answers) becomes its URL. A source
    a researcher read at another URL (an open copy) carries that readUrl."""
    from .graph import Graph
    graph, sources = None, []

    def with_lead(source):
        lead = knowledge.read_url(root, source.get("doi"), source.get("url"))
        return dict(source, readUrl=lead) if lead and lead != source.get("url") else source
    for citation in citations or []:
        if not isinstance(citation, str):
            continue
        if citation.startswith(("http://", "https://")):
            sources.append(with_lead({"url": citation}))
            continue
        found = knowledge.get(root, citation)
        if found and found.get("source"):
            # What the researcher saw of it too: its flag and its review's reason (memory ablation M3, 2026-10-13: a
            # statement about a finding's flag could not be checked without them).
            said = {k: found[k] for k in ("statement", "value", "unit", "conditions", "locator", "excerpt", "reviewFlag")
                    if found.get(k)}
            if (found.get("review") or {}).get("reason"):
                said["reviewReason"] = found["review"]["reason"]
            sources.append(with_lead(dict(found["source"], cited=citation, status=found.get("status"), **said)))
            continue
        if found and (found.get("url") or found.get("doi")):
            sources.append({k: found[k] for k in ("title", "url", "doi", "locator") if found.get(k)})
            continue
        try:
            graph = graph or Graph(resolve_release(root), verify=False)
            record = graph.get(citation)
            url = record.get("url") or record.get("contentUrl") or (
                "https://doi.org/" + record["doi"] if record.get("doi") else None)
            sources.append({k: v for k, v in {"title": record.get("citation") or record.get("label"), "url": url,
                                              "locator": record.get("locator"), "cited": citation}.items() if v})
        except (KeyError, ValueError):
            sources.append({"unresolved": citation})
    return sources


def session_record(root, run_id, web=None):
    """What a research session's searches of saved knowledge returned, from its trace, and its web actions (`web`, from
    `web_actions`): the evidence for statements such as "the saved findings did not include a value", "this part came
    from saved findings" or "the publisher page would not open"."""
    from .trace import TraceStore
    record = {"webActions": web} if web else {}
    if not run_id:
        return record or None
    try:
        run = TraceStore(root).run(run_id)
        events = run.events()["events"]
    except (ValueError, OSError, KeyError):
        return record or None
    searches = []
    for event in events:
        if event.get("operation") != "knowledge.search_knowledge" or event.get("status") != "ok":
            continue
        result = run.payload(event["payload_hash"]).get("result") or {}
        searches.append({"query": ((event.get("request") or {}).get("arguments") or {}).get("q"),
                         "findings": [{k: v for k, v in (("id", f["id"]), ("status", f.get("status")),
                                                         ("statement", (f.get("statement") or "")[:200]),
                                                         ("reviewFlag", f.get("reviewFlag"))) if v}
                                      for group in ("reviewed", "added", "unreviewed") for f in result.get(group, [])],
                         "notes": [{"id": n["id"], "title": (n.get("title") or "")[:160]} for n in result.get("notes", [])]})
    return dict(record, knowledgeSearches=searches)


CITATION = re.compile(r"`[^`]+`|\[[^\]]+\]\(https?://|https?://")
# The answer's own reasoning and textbook background are labelled, not cited to a paper; the checker judges them.
LABELLED = re.compile(r"\W*(Interpretation|Background)\W*:", re.I)


def cited_fraction(answer):
    """Share of substantive paragraphs or bullets that carry at least one citation.

    Paragraphs labelled "Interpretation:" or "Background:" are the answer's own reasoning or textbook
    knowledge, not claims about what a source reports, so they are not counted.

    A lead-in ending in a colon and a table belong with the part that follows them
    (a citation under a table is its caption), and a first-person note about the
    search ("I verified one study…") is not a claim about polymers."""
    text = answer.get("answer") or ""
    units, carried = [], ""
    for unit in re.split(r"\n\s*\n|\n\s*[-*] |\n\s*\d+[.)] ", text):
        unit = (carried + "\n" + unit).strip() if carried else unit.strip()
        if unit.endswith(":") or unit.rsplit("\n", 1)[-1].startswith("|"):
            carried = unit
            continue
        carried = ""
        units.append(unit)
    if carried:
        units.append(carried)
    units = [u for u in units if len(re.findall(r"[A-Za-z]{3,}", u)) >= 8 and not u.startswith("#")
             and not re.match(r"\W*(I|We)\b", u) and not LABELLED.match(u)]
    if not units:
        return None
    return round(sum(1 for u in units if CITATION.search(u)) / len(units), 3)


def check(root, question, answer, *, engine, runner, timeout, run_id=None, web=None):
    """`run_id` is the researcher's trace and `web` the session's web actions, so statements about what saved
    knowledge held or what the session read can be checked."""
    for attempt in (1, 2):
        try:
            value = reviewer.check_answer(question["question"], answer.get("answer", ""),
                                          resolve_sources(root, answer.get("citations")), engine=engine,
                                          runner=runner, timeout=timeout, root=root, owner=question["id"],
                                          session=session_record(root, run_id, web))
            return dict(value, citedFraction=cited_fraction(answer), at=now())
        except engines.EngineError as error:
            if attempt == 2 or not error.retryable:
                raise


# ----- canaries -----

METHOD = re.compile(r"\b(?:DSC|TGA|DMA|GPC|SEC|NMR|FTIR|XRD|SAXS|WAXS|ASTM|ISO)\b|rheomet|calorimet|tensile|"
                    r"heating rate|°C/min|K/min|mm/min", re.I)
IN_METHODS = re.compile(r"method|experimental|materials|characteri[sz]ation|procedure", re.I)


def _mistype(title):
    """The title with one letter dropped from its longest word ("vinylimidazole" to "vinyimidazole")."""
    words = re.findall(r"[A-Za-z]{7,}", title or "")
    if not words:
        return None
    word = max(words, key=len)
    return title.replace(word, word[:3] + word[4:], 1)


def make_canaries(root):
    """Wrong findings made from real reviewed ones (a number, a condition, the source, a title word), which the reviewer
    must reject, and true controls: one unchanged, and one whose method is stated only in its source's methods section
    (a reviewer that reads only the cited table wrongly rejects it)."""
    reviewed = [f for f in knowledge.recent(root, knowledge.SUPPORTED, 200)
                if f.get("source", {}).get("url") and re.search(r"\d", f.get("statement", ""))]
    reviewed = [knowledge.get(root, f["id"]) for f in reviewed]
    key = lambda f: knowledge.source_key(f["source"].get("doi"), f["source"].get("url"))

    def bump(f):
        """The finding with its value changed where its statement gives it, never a number in a name (PA11 became
        PA24 in the first canaries, which a reviewer could reject on the material alone)."""
        number = next(iter(re.findall(r"\d+(?:\.\d+)?", f.get("value") or "")), None)
        where = r"(?<![\w.])" + re.escape(number) + r"(?!\.?\d)" if number else None
        if not where or not re.search(where, f["statement"]):
            return None
        shifted = _shift(number)
        return {"statement": re.sub(where, shifted, f["statement"], count=1), "value": f["value"].replace(number, shifted, 1)}
    first = next((f for f in reviewed if bump(f)), None)
    # The wrong source is another paper's: three findings of one paper made a table row of the same paper the "other
    # source" in the first canaries.
    others = [f for f in reviewed if first and key(f) != key(first)]
    if not first or len(others) < 2:
        raise ValueError("Canaries need reviewed findings from at least two sources, one stating its value")
    second, third = others[0], others[1]
    view = lambda f, **changes: dict({k: f.get(k) for k in ("statement", "material", "property", "value", "unit",
                                                             "conditions", "source", "locator", "excerpt")}, **changes)
    items = [
        dict(view(first, excerpt="", **bump(first)),
             id="canary:value", expected="unsupported", made="changed the value where the statement gives it"),
        dict(view(second, statement=second["statement"] + " This was measured under vacuum at 150 °C.",
                  conditions="under vacuum at 150 °C", excerpt=""),
             id="canary:condition", expected="unsupported", made="added a test condition the source does not report"),
        dict(view(first, source=third["source"], locator=third.get("locator"), excerpt=""),
             id="canary:source", expected="unsupported", made="attached another paper's source"),
        dict(view(third), id="control:true", expected="supported", made="unchanged reviewed finding"),
    ]
    used = {first["id"], second["id"], third["id"]}
    titled = next((f for f in [f for f in reviewed if f["id"] not in used] + [f for f in reviewed if f["id"] in used]
                   if _mistype(f["source"].get("title"))), None)
    if titled:
        items.append(dict(view(titled, source=dict(titled["source"], title=_mistype(titled["source"]["title"])),
                               excerpt=""),
                          id="canary:title", expected="unsupported", made="dropped one letter from a word of the title"))
    methods = next((f for f in reviewed if METHOD.search(f.get("conditions") or "")
                    and not IN_METHODS.search(f.get("locator") or "") and re.search(r"table|fig", f.get("locator") or "", re.I)
                    and f["id"] not in used), None)
    if methods:
        items.append(dict(view(methods, excerpt=""), id="control:methods", expected="supported",
                          made="unchanged reviewed finding whose method is given outside the cited table or figure"))
    return items


def _shift(number):
    value = float(number)
    shifted = value * 1.5 + 7 if value else 11
    return ("%d" % round(shifted)) if "." not in number else ("%.*f" % (len(number.split(".")[1]), shifted))


def run_canaries(root, engine, *, runner, timeout=reviewer.REVIEW_SECONDS):
    items = make_canaries(root)
    reviewer.capture_sources(root, [i["source"] for i in items if i.get("source")])
    result = _call(root, "parity-canary", "canaries", runner, engine, reviewer.review_prompt(items, root),
                   reviewer.REVIEW_SCHEMA, tools=None, web=True, timeout=timeout, idle=reviewer.IDLE_SECONDS)
    verdicts = reviewer.parse_verdicts(result["answer"], {i["id"] for i in items})
    rows = [{"id": i["id"], "made": i["made"], "expected": i["expected"],
             "verdict": verdicts.get(i["id"], {}).get("verdict", "uncertain"),
             "reason": verdicts.get(i["id"], {}).get("reason", "")} for i in items]
    for row in rows:
        row["ok"] = row["verdict"] == row["expected"]  # A hedged "uncertain" does not catch a canary.
    wrong = [r for r in rows if r["expected"] == "unsupported"]
    return {"engine": result["engine"], "rows": rows, "caught": sum(r["ok"] for r in wrong),
            "accepted": sum(r["verdict"] == "supported" for r in wrong),  # A wrong finding let into the knowledge base.
            "canaries": sum(1 for r in rows if r["expected"] == "unsupported"),
            "controlSupported": all(r["ok"] for r in rows if r["expected"] == "supported"), "at": now()}


# ----- a run -----

def direct_folder(root, engine, model):
    """The frozen plain answers for one engine and model."""
    return folder(root) / "direct" / engine / model


def run(root, *, engine, checker=None, runner=None, only=None, canaries=False, progress=None):
    """Answer and check the whole set on one engine with the researcher's current instructions. Returns the report."""
    runner = runner or engines.run_session
    parity = load_set()
    depth = parity.get("depth", "standard")
    from .ask import DEPTHS, prompt_version
    timeout = DEPTHS[depth]["seconds"]
    checker = checker or engine
    stamp = now().replace(":", "").replace("-", "").split(".")[0]
    target = folder(root) / "runs" / (stamp + "-" + engine)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    model = engines.ENGINES[engine]["model"]
    meta = {"engine": engine, "model": model, "checker": checker, "prompt": prompt_version(), "depth": depth, "startedAt": now(),
            "set": parity["format"], "questions": [q["id"] for q in parity["questions"]]}
    atomic_json(target / "run.json", meta, private=True)
    say = progress or (lambda message: None)
    for question in parity["questions"]:
        if only == "covered" and not question["covered"] or only == "uncovered" and question["covered"]:
            continue
        frozen = direct_folder(root, engine, model) / (question["id"] + ".json")
        if frozen.exists():
            stored = read_json(frozen)
            # The plain answer is reused; its check is made again below, beside the researcher's.
            direct = {k: v for k, v in stored.items() if k not in ("check", "checker", "previousChecks")}
            direct["frozenAt"] = stored.get("at")
        else:
            say("direct " + question["id"])
            direct = _safely(lambda: answer_direct(root, question, engine, runner=runner, timeout=timeout))
            if "error" not in direct:
                atomic_json(frozen, direct, private=True)
        say("ontology " + question["id"])
        arm = _safely(lambda: answer_ontology(root, question, engine, runner=runner, timeout=timeout, depth=depth))
        # Both checks one right after the other, by one checker, on sources captured once.
        for name, entry in (("direct", direct), ("ontology", arm)):
            if "error" not in entry:
                say("check %s %s" % (name, question["id"]))
                entry["check"] = _safely(lambda: check(root, question, entry["answer"], engine=checker, runner=runner,
                                                        timeout=reviewer.REVIEW_SECONDS, run_id=entry.get("runId"),
                                                        web=entry.get("webActions")))
                entry["checker"] = checker
            atomic_json(target / ("%s-%s.json" % (question["id"], name)), entry, private=True)
    if canaries:
        say("canaries")
        atomic_json(target / "canaries.json", _safely(lambda: run_canaries(root, checker, runner=runner)), private=True)
    meta["finishedAt"] = now()
    atomic_json(target / "run.json", meta, private=True)
    report_value = report(root, target.name)
    atomic_json(target / "report.json", report_value, private=True)
    return report_value


def recheck(root, name=None, *, checker, runner=None, progress=None, all_checks=False):
    """Fill in a run's failed checks (or, with `all_checks`, redo every check), without answering anything again. A
    question with a check to fill has both arms checked again, one after the other, so they stay like for like."""
    runner = runner or engines.run_session
    names = runs(root)
    if not names:
        raise FileNotFoundError("No parity run yet")
    name = name or names[0]
    target = folder(root) / "runs" / name
    meta = read_json(target / "run.json")
    say = progress or (lambda message: None)
    for question in load_set()["questions"]:
        entries = {arm: read_json(target / ("%s-%s.json" % (question["id"], arm))) for arm in ("direct", "ontology")
                   if (target / ("%s-%s.json" % (question["id"], arm))).exists()}
        entries = {arm: entry for arm, entry in entries.items() if "error" not in entry}
        if not all_checks and all(entry.get("check") and "error" not in entry["check"] for entry in entries.values()):
            continue
        for arm, entry in entries.items():
            path = target / ("%s-%s.json" % (question["id"], arm))
            say("check " + arm + " " + question["id"])
            if entry.get("check"):
                entry.setdefault("previousChecks", []).append(entry["check"])
            entry["check"] = _safely(lambda: check(root, question, entry["answer"], engine=checker, runner=runner,
                                                    timeout=reviewer.REVIEW_SECONDS, run_id=entry.get("runId"),
                                                    web=entry.get("webActions")))
            entry["checker"] = checker
            atomic_json(path, entry, private=True)
    canaries = target / "canaries.json"
    if canaries.exists() and "error" in read_json(canaries):
        say("canaries")
        atomic_json(canaries, _safely(lambda: run_canaries(root, checker, runner=runner)), private=True)
    meta.setdefault("rechecks", []).append({"checker": checker, "at": now()})
    atomic_json(target / "run.json", meta, private=True)
    value = report(root, name)
    atomic_json(target / "report.json", value, private=True)
    return value


def _safely(work):
    try:
        return work()
    except engines.EngineError as error:
        return {"error": error.summary()}


# ----- reporting -----

def runs(root):
    base = folder(root) / "runs"
    return sorted((p.name for p in base.iterdir() if (p / "run.json").exists()), reverse=True) if base.exists() else []


def report(root, name=None):
    names = runs(root)
    if not names:
        return None
    name = name or names[0]
    target = folder(root) / "runs" / name
    meta = read_json(target / "run.json")
    parity = load_set()
    rows = []
    for question in parity["questions"]:
        arms = {}
        for arm in ("direct", "ontology"):
            path = target / (question["id"] + "-" + arm + ".json")
            if path.exists():
                value = read_json(path)
                arms[arm] = {"error": value.get("error"), "metrics": value.get("metrics"),
                             "depositError": value.get("depositError"),
                             "measures": reviewer.measures(value.get("check")),
                             "verdict": (value.get("check") or {}).get("verdict"),
                             "resultGiven": (value.get("check") or {}).get("resultGiven"),
                             "supportedFraction": (value.get("check") or {}).get("supportedFraction"),
                             # Recomputed from the stored answer, so a fix to the measure applies to every run.
                             "citedFraction": cited_fraction(value.get("answer") or {})
                             if (value.get("check") or {}).get("verdict") else None,
                             "checkError": (value.get("check") or {}).get("error"),
                             "statements": reviewer.normalize_check(value.get("check") or {}).get("statements", [])}
        if arms:
            ratio = None
            direct, onto = (arms.get("direct") or {}).get("metrics") or {}, (arms.get("ontology") or {}).get("metrics") or {}
            if direct.get("newTokens") and onto.get("newTokens") is not None and not onto.get("depositFailed"):
                ratio = round(onto["newTokens"] / direct["newTokens"], 3)
            rows.append({"id": question["id"], "covered": question["covered"], "question": question["question"],
                         "arms": arms, "tokenRatio": ratio})
    summary = {"all": _summarize(rows), "covered": _summarize([r for r in rows if r["covered"]]),
               "uncovered": _summarize([r for r in rows if not r["covered"]])}
    extra = {"canaries": read_json(target / "canaries.json")} if (target / "canaries.json").exists() else {}
    everything = summary["all"]
    checked = everything["checked"]
    guardrail = {
        "extraContradicted": everything["contradicted"]["ontology"] - everything["contradicted"]["direct"] if checked else None,
        "completeDeficit": everything["complete"]["direct"] - everything["complete"]["ontology"] if checked else None,
        "citedFraction": everything["medianCited"]["ontology"], "minCitedFraction": everything["minCited"]["ontology"],
        "medianTokenRatio": everything["medianTokenRatio"],
        # Secondary: passes move with whether a source opened during the check.
        "passDeficit": everything["passes"]["direct"] - everything["passes"]["ontology"] if checked else None}
    guardrail["checked"] = checked
    if checked < THRESHOLDS["minChecked"]:
        guardrail["holds"] = None  # Too few checked pairs to say either way; `oopc parity recheck` fills the gaps.
    else:
        guardrail["holds"] = (guardrail["extraContradicted"] <= THRESHOLDS["maxExtraContradicted"]
                              and guardrail["completeDeficit"] <= THRESHOLDS["maxCompleteDeficit"]
                              and (guardrail["citedFraction"] or 0) >= THRESHOLDS["minCitedFraction"]
                              and guardrail["medianTokenRatio"] is not None
                              and guardrail["medianTokenRatio"] <= THRESHOLDS["maxMedianTokenRatio"])
    return {"run": name, "meta": meta, "rows": rows, "summary": summary, "guardrail": guardrail,
            "thresholds": THRESHOLDS, **extra,
            "notice": "Eight questions are descriptive: a difference of one or two contradicted statements, complete "
                      "answers or passes is within noise. Read trends across runs, not single results."}


def _summarize(rows):
    checked = [r for r in rows if all((r["arms"].get(a) or {}).get("verdict") for a in ("direct", "ontology"))]
    median = lambda values: statistics.median(values) if values else None
    field = lambda arm, key: [r["arms"][arm][key] for r in checked if r["arms"][arm].get(key) is not None]
    metric = lambda arm, key: [(r["arms"].get(arm) or {}).get("metrics", {}).get(key) for r in rows
                               if ((r["arms"].get(arm) or {}).get("metrics") or {}).get(key) is not None]
    measure = lambda arm, key: [(r["arms"][arm].get("measures") or {}).get(key) for r in checked]
    totals = lambda arm: [t for t in (total_seconds((r["arms"].get(arm) or {}).get("metrics")) for r in rows)
                          if t is not None]
    # Checks before 2026-10-14 did not say whether an answer gave the result: unmeasured, not none given.
    given = lambda values: sum(v is True for v in values) if any(isinstance(v, bool) for v in values) else None
    return {"questions": len(rows), "checked": len(checked),
            # First the measures that do not depend on whether a source opened during the check.
            "contradicted": {a: sum(m or 0 for m in measure(a, "contradicted")) for a in ("direct", "ontology")},
            "complete": {a: sum(m is True for m in measure(a, "complete")) for a in ("direct", "ontology")},
            # A pass or a complete answer can be an honest "not found"; this counts answers that gave the result.
            "resultsGiven": {a: given([r["arms"][a].get("resultGiven") for r in checked]) for a in ("direct", "ontology")},
            "passes": {a: sum(r["arms"][a]["verdict"] == "pass" for r in checked) for a in ("direct", "ontology")},
            "accessUncertain": {a: sum(m or 0 for m in measure(a, "accessUncertain")) for a in ("direct", "ontology")},
            "medianSupported": {a: median(field(a, "supportedFraction")) for a in ("direct", "ontology")},
            "medianCited": {a: median(field(a, "citedFraction")) for a in ("direct", "ontology")},
            # The median hides the one answer that is not fully cited.
            "minCited": {a: min(field(a, "citedFraction"), default=None) for a in ("direct", "ontology")},
            "medianTokenRatio": median([r["tokenRatio"] for r in rows if r["tokenRatio"] is not None]),
            "medianTokens": {a: median(metric(a, "newTokens")) for a in ("direct", "ontology")},
            "medianTotalTokens": {a: median(metric(a, "tokens")) for a in ("direct", "ontology")},
            "medianNewTokens": {a: median(metric(a, "newTokens")) for a in ("direct", "ontology")},
            "medianWebCalls": {a: median(metric(a, "webCalls")) for a in ("direct", "ontology")},
            "medianSeconds": {a: median(metric(a, "seconds")) for a in ("direct", "ontology")},
            # The researcher's answer comes first and its findings after; runs before 2026-10-25 had one turn.
            "medianTotalSeconds": {a: median(totals(a)) for a in ("direct", "ontology")},
            "failures": {a: sum(1 for r in rows if (r["arms"].get(a) or {}).get("error")) for a in ("direct", "ontology")}}


def total_seconds(metrics):
    """An arm's seconds in total: the researcher's answer and its deposit, or the one turn of a plain session or of a
    run made before the researcher answered first."""
    metrics = metrics or {}
    return metrics["totalSeconds"] if metrics.get("totalSeconds") is not None else metrics.get("seconds")


def last_run_at(root):
    names = runs(root)
    if not names:
        return None
    meta = read_json(folder(root) / "runs" / names[0] / "run.json")
    return meta.get("finishedAt") or meta.get("startedAt")
