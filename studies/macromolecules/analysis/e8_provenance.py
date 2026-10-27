#!/usr/bin/env python3
"""E8: are the contradicted statements "a source could not be read" a logging artefact? From the records only: no
engine call, no network, nothing under the run folders written.

In E8 (`2026-10-kf-e8/r1-s1`: K0c and KFc, the researcher on Claude Code, checked by the Codex checker) five
contradicted statements of category "provenance" say a source could not be read, and the checker contradicted each
because the session's recorded web actions list that source as opened. The checker sees what `parity.session_record`
gives it: the web actions `parity.web_actions` takes from the session's tools, whose `outcome` freeze-2's stream
parsers set (`engines.parse_claude_stream`, `engines.parse_codex_stream`):

- Claude Code: a WebFetch is "refused" when its tool result is flagged as an error or its first 200 characters match
  `engines.REFUSED_PAGE` (an HTTP 403/404, "request failed", a browser check); anything else is "opened". WebFetch
  returns a summary written by a model from the page, not the page, so a PDF whose text streams are compressed, a
  cross-host redirect notice or a "document not found" page all come back as text that does not start with an error
  phrase, and are recorded "opened".
- Codex: an open is "opened" only when the page reports more than one line ("Total lines: N") and its title is not an
  error page. Codex extracts a PDF's text itself. Its stream holds a page's title and length, not its text.

What this reads: each E8 item (`items/*.json`: the answer, its recorded `webActions`, the check's statements), the raw
Claude Code stream of each answer (`streams/*-claude-code.jsonl`, matched to the item by its web actions as freeze-2's
parser reads them, ties broken by time), every WebFetch's input and returned text, and, as the comparison, A2's Codex
K0 and KF answers on the same 20 near questions (`2026-10-kf-scaling/r*-s*`) with their raw Codex streams.

Each WebFetch the record calls "opened" is put in one class by what it returned (the class rules are regular
expressions on the start of the returned text, listed in CLASSES; every fetch's class and opening text are in
results.json for audit): a redirect notice (no document), unreadable (a PDF's raw compressed or encrypted bytes, or a
file with no text layer: only metadata readable), an error page ("document not found"), readable but with a table only
as an image, or readable. For Codex, each "opened" page is checked for an error-like title and for its length.

Writes `.oopc/study/analysis/e8-provenance/results.json` and `results.md`.

    OOPC_STUDY_ROOT=<main checkout> OOPC_STUDY_CODE=<main checkout>/.oopc/study/freeze-2 \
        python -B studies/macromolecules/analysis/e8_provenance.py [--out DIR]
"""
import argparse, collections, datetime as dt, json, os, re, statistics, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
import common  # noqa: E402  (puts the code under test first on sys.path)
from oopc import engines, parity  # noqa: E402

FREEZE2 = common.ROOT / ".oopc/study/freeze-2"
E8 = common.run_dir("2026-10-kf-e8") / "r1-s1"
A2 = common.run_dir("2026-10-kf-scaling")
OUT = common.analysis_dir("e8-provenance")
ARMS = ("K0c", "KFc")
CODEX_ARMS = ("K0", "KF")  # A2's Codex arms E8 is set beside (a2a3e8_results.py)
UNREADABLE_CLAIM = re.compile(r"could not (?:be )?(?:read|open|parse)|couldn't (?:read|open)|unreadable|not readable|"
                              r"could not be (?:read|parsed|opened)|were readable", re.I)
CLASSES = (  # (class, pattern on the first 600 characters of a WebFetch's returned text), first match wins
    ("redirect notice", re.compile(r"^\s*REDIRECT DETECTED")),
    ("unreadable", re.compile(r"raw (?:binary|pdf|compressed|byte)|compressed (?:pdf )?(?:stream|binary|data|pdf|image)|"
                              r"flatedecode|can(?:'|no)t decode|couldn't decode|binary (?:of a pdf|content|data)|"
                              r"pdf file dump|isn't readable text|not readable text|no (?:extractable|readable) text|"
                              r"text layer is missing|encrypt", re.I)),
    ("error page", re.compile(r"dokument nicht gefunden|document not found|page not found|access denied|"
                              r"browser verification|verification message|enable javascript|log in to|login page|"
                              r"paywall|subscription required|only the abstract|abstract only", re.I)),
    ("readable, a table only as an image", re.compile(r"table image|only (?:in|as) an image|image-based", re.I)),
)
ERROR_TITLE = re.compile(r"sign in|log ?in|access|denied|error|not found|\b40[34]\b|subscribe|robot|captcha|cookie|"
                         r"verif|just a moment|attention required|redirect", re.I)
PAYWALLED = ("link.springer.com", "onlinelibrary.wiley.com", "sciencedirect.com", "tandfonline.com", "pubs.acs.org",
             "journals.sagepub.com", "nature.com", "iopscience.iop.org")
# The five statements, the sentence of the answer each was drawn from, and the sources it names (URL substrings).
CASES = (
    {"item": "0007-K0c", "statement": "Neither the Oyama article nor its repository copies were readable during the session.",
     "said": "Neither the paywalled article nor its repository copies were readable",
     "sources": ("ynu.repo.nii.ac.jp", "objectstorage.ap-tokyo-1", "liris.cnrs.fr", "nature.com/articles/s41428")},
    {"item": "0007-K0c", "statement": "The microcapsule PDF was unreadable during the session.",
     "said": "but its copy was also unreadable", "sources": ("sites.usc.edu",)},
    {"item": "0009-K0c", "statement": "The researcher could not read those datasheets.",
     "said": "I could not read those datasheets", "sources": ("topas.com",)},
    {"item": "0010-KFc", "statement": "The researcher could not open the Arkema sheets.",
     "said": "I could not open those sheets", "sources": ("hpp.arkema.com",),
     "alsoCited": ("materialdatacenter.com",)},  # the checker also cited this database page, opened and readable
    {"item": "0016-K0c", "statement": ("Neither the Tangram PDF nor the LyondellBasell pipe brochure could be read; they "
                                       "were search-snippet-only leads."),
     "said": "Neither PDF could be read", "sources": ("tangram.co.uk", "pb-1-pipe-brochure")},
)
NO_CONTENT = ("redirect notice", "unreadable", "error page")


def jread(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def when(text):
    return dt.datetime.fromisoformat(text)


def classify(text):
    head = (text or "")[:600]
    return next((name for name, pattern in CLASSES if pattern.search(head)), "readable")


# ----- Claude Code streams -----

def claude_fetches(path):
    """A Claude Code stream's WebFetch calls in order: url, prompt, error flag, returned text, and the outcome freeze-2
    recorded for it."""
    text = path.read_text(encoding="utf-8", errors="replace")
    _, _, tools = engines.parse_claude_stream(text)
    outcome = {t["id"]: t.get("outcome") for t in tools}
    uses, results = {}, {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) and isinstance(event.get("message"), dict) else {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "WebFetch":
                uses[block["id"]] = block.get("input") or {}
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in uses:
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
                results[block["tool_use_id"]] = (block.get("is_error") is True, str(content or ""))
    fetches = []
    for tid, given in uses.items():
        error, returned = results.get(tid, (None, ""))
        recorded = outcome.get(tid)
        fetches.append({"url": given.get("url"), "prompt": (given.get("prompt") or "")[:300], "isError": error,
                        "recorded": recorded, "returned": classify(returned) if recorded == "opened" else
                        ("error (HTTP or browser check)" if recorded == "refused" else "no result"),
                        "text": re.sub(r"\s+", " ", returned[:600])})
    return tools, fetches


def match(items, streams, tools_of, end_of, ledger_end):
    """Each item's stream: the one whose web actions (as freeze-2 parses them) equal the item's, nearest in time."""
    found = {}
    for name, item in items.items():
        web = item["answer"].get("webActions") or []
        candidates = [s for s in streams if parity.web_actions({"observedTools": tools_of[s]}) == web]
        if candidates:
            found[name] = min(candidates, key=lambda s: abs(end_of[s] - ledger_end[name]))
    return found


def e8_items():
    items = {p.stem: jread(p) for p in sorted((E8 / "items").glob("*.json"))}
    ends = {}
    for name, item in items.items():
        arm = name.split("-", 1)[1]
        call = jread(E8 / "workspaces" / arm / ".oopc/loop/calls" / (item["answer"]["callId"] + ".json"))
        ends[name] = when(call["finishedAt"]).timestamp()
    return items, ends


def contradicted(check):
    return [s for s in (check or {}).get("statements") or []
            if isinstance(s, dict) and s.get("verdict") == "unsupported" and s.get("category") != "source-access"]


def e8():
    items, ends = e8_items()
    streams = sorted((E8 / "streams").glob("*-claude-code.jsonl"))
    parsed = {s: claude_fetches(s) for s in streams}
    matched = match(items, streams, {s: parsed[s][0] for s in streams}, {s: s.stat().st_mtime for s in streams}, ends)
    per_answer, all_fetches = {}, []
    for name, stream in sorted(matched.items()):
        fetches = parsed[stream][1]
        recorded = [a for a in items[name]["answer"].get("webActions") or [] if a.get("action") == "open"]
        if [f["recorded"] for f in fetches] != [a.get("outcome") for a in recorded]:
            raise SystemExit("The stream of %s does not give the outcomes its record holds" % name)
        for f in fetches:
            all_fetches.append(dict(f, item=name, arm=name.split("-", 1)[1], stream=stream.name))
        per_answer[name] = {"stream": stream.name, "fetches": len(fetches),
                            "recordedOpened": sum(f["recorded"] == "opened" for f in fetches),
                            "openedNoContent": sum(f["recorded"] == "opened" and f["returned"] in NO_CONTENT
                                                   for f in fetches)}
    # the contradicted statements, and the provenance ones about reading a source
    statements = []
    for name, item in items.items():
        for s in contradicted(item.get("check")):
            statements.append({"item": name, "arm": name.split("-", 1)[1], "kind": s.get("kind"),
                               "category": s.get("category"), "statement": s.get("statement"), "reason": s.get("reason"),
                               "aboutReading": s.get("category") == "provenance"
                               and bool(UNREADABLE_CLAIM.search(s.get("statement") or ""))})
    cases = []
    for case in CASES:
        item = items[case["item"]]
        text = item["answer"]["answer"].get("answer") or ""
        hit = next((s for s in statements if s["item"] == case["item"] and s["statement"] == case["statement"]), None)
        if hit is None or case["said"] not in text:
            raise SystemExit("Case %s is not as the records hold it" % case["item"])
        named = [f for f in all_fetches if f["item"] == case["item"]
                 and any(src in (f["url"] or "") for src in case["sources"])]
        record = [a for a in item["answer"]["webActions"] if a.get("action") == "open"
                  and any(src in (a.get("url") or "") for src in case["sources"])]
        sentence = next((part.strip() for part in re.split(r"(?<=[.!?])\s+|\n", text) if case["said"] in part), "")
        content = [f for f in named if f["returned"] not in NO_CONTENT and f["recorded"] == "opened"]
        also = [f for f in all_fetches if f["item"] == case["item"]
                and any(src in (f["url"] or "") for src in case.get("alsoCited", ()))]
        if not named:
            verdict = "cannot tell"
        elif all(f["returned"] in NO_CONTENT or f["recorded"] == "refused" for f in named):
            verdict = "the answer was right; the record misleads the checker"
        else:
            verdict = "see readable fetches"
        cases.append({"item": case["item"], "statement": case["statement"], "answerSaid": sentence,
                      "limitations": item["answer"]["answer"].get("limitations"),
                      "checkerReason": hit["reason"],
                      "record": [{"url": a.get("url"), "outcome": a.get("outcome")} for a in record],
                      "fetches": [{k: f[k] for k in ("url", "recorded", "isError", "returned", "text")} for f in named],
                      "readableFetchesOfNamedSources": [f["url"] for f in content],
                      "otherFetchesTheCheckerCited": [{k: f[k] for k in ("url", "recorded", "returned", "text")}
                                                      for f in also], "verdict": verdict})
    opened = [f for f in all_fetches if f["recorded"] == "opened"]
    pdf = [f for f in all_fetches if re.search(r"\.pdf\b|/pdf\b|download", f["url"] or "", re.I)]
    by_arm = {arm: {"answers": sum(1 for n in per_answer if n.endswith(arm)),
                    "answersWithAFetch": sum(1 for n, v in per_answer.items() if n.endswith(arm) and v["fetches"]),
                    "answersWithOpenedNoContent": sum(1 for n, v in per_answer.items()
                                                      if n.endswith(arm) and v["openedNoContent"]),
                    "fetches": sum(f["arm"] == arm for f in all_fetches),
                    "recordedOpened": sum(f["arm"] == arm and f["recorded"] == "opened" for f in all_fetches),
                    "openedNoContent": sum(f["arm"] == arm and f["recorded"] == "opened" and f["returned"] in NO_CONTENT
                                           for f in all_fetches)} for arm in ARMS}
    return {"answers": len(items), "statements": sum(len((i.get("check") or {}).get("statements") or [])
                                                     for i in items.values()),
            "matchedStreams": len(matched), "fetches": len(all_fetches),
            "recorded": dict(collections.Counter(f["recorded"] for f in all_fetches)),
            "openedReturned": dict(collections.Counter(f["returned"] for f in opened)),
            "openedNoContent": sum(f["returned"] in NO_CONTENT for f in opened),
            "refusedReturned": dict(collections.Counter(f["text"][:40] for f in all_fetches if f["recorded"] == "refused")),
            "pdfFetches": len(pdf), "pdfOpenedUnreadable": sum(f["recorded"] == "opened" and f["returned"] == "unreadable"
                                                                for f in pdf),
            "byArm": by_arm, "answersWithOpenedNoContent": sum(1 for v in per_answer.values() if v["openedNoContent"]),
            "perAnswer": per_answer,
            "contradicted": {"total": len(statements),
                             "byArm": dict(collections.Counter(s["arm"] for s in statements)),
                             "byKind": dict(collections.Counter("%s/%s" % (s["kind"], s["category"]) for s in statements)),
                             "provenance": [s for s in statements if s["category"] == "provenance"],
                             "aboutReading": sum(s["aboutReading"] for s in statements)},
            "cases": cases, "fetchList": all_fetches}


# ----- A2's Codex answers on the same questions -----

def codex_pages(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    _, _, tools = engines.parse_codex_stream(text)
    pages = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") if isinstance(event, dict) and isinstance(event.get("item"), dict) else None
        if not (event.get("type") == "item.completed" and item and item.get("type") == "web_search"):
            continue
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        kind = engines.CODEX_ACTIONS.get(action.get("type"), "other")
        if kind not in ("open", "find"):
            continue
        results = [r for r in item.get("results") or [] if isinstance(r, dict)]
        first = results[0] if results else {}
        lines = re.match(r"Total lines: (\d+)", str(first.get("snippet") or ""))
        pages.append({"action": kind, "url": action.get("url"), "recorded": engines._codex_web_outcome(item, kind),
                      "title": first.get("title"), "lines": int(lines.group(1)) if lines else None})
    return tools, pages


def a2_codex(question_ids):
    answers, with_open, pages, unmatched, statements, checked = 0, 0, [], [], collections.Counter(), 0
    for run in sorted(A2.glob("r*-s*")):
        plan = jread(run / "plan.json")
        streams = sorted((run / "streams").glob("*-codex.jsonl"))
        parsed = {s: codex_pages(s) for s in streams}
        ends = {s: s.stat().st_mtime for s in streams}
        for index, question in enumerate(plan["questions"]):
            if question["id"] not in question_ids:
                continue
            for arm in CODEX_ARMS:
                item = jread(run / "items" / ("%04d-%s.json" % (index, arm)))
                answers += 1
                checked += len((item.get("check") or {}).get("statements") or [])
                for s in contradicted(item.get("check")):
                    statements["%s/%s" % (s.get("kind"), s.get("category"))] += 1
                web = item["answer"].get("webActions") or []
                if not any(a.get("action") in ("open", "find") for a in web):
                    continue  # no page opened: nothing to match
                with_open += 1
                call = jread(run / "workspaces" / arm / ".oopc/loop/calls" / (item["answer"]["callId"] + ".json"))
                end = when(call["finishedAt"]).timestamp()
                candidates = [s for s in streams if parity.web_actions({"observedTools": parsed[s][0]}) == web]
                if not candidates:
                    unmatched.append("%s/%04d-%s" % (run.name, index, arm))
                    continue
                stream = min(candidates, key=lambda s: abs(ends[s] - end))
                pages += [dict(p, item="%s/%04d-%s" % (run.name, index, arm)) for p in parsed[stream][1]]
    opened = [p for p in pages if p["recorded"] == "opened"]
    lines = [p["lines"] for p in opened if p["lines"] is not None]
    pdf = [p for p in pages if re.search(r"\.pdf\b|/pdf\b|download", p["url"] or "", re.I)]
    return {"answers": answers, "statements": checked, "answersWithAnOpen": with_open, "unmatched": unmatched, "pages": len(pages),
            "answersWithOpenedNoDocument": len({p["item"] for p in pages if p["recorded"] == "opened"
                                                and (ERROR_TITLE.search(p["title"] or "") or (p["lines"] or 0) <= 5)}),
            "recorded": dict(collections.Counter(p["recorded"] for p in pages)),
            "openedErrorTitle": [p for p in opened if ERROR_TITLE.search(p["title"] or "")],
            "openedAtMost5Lines": sum(1 for n in lines if n <= 5), "openedMedianLines": statistics.median(lines) if lines else None,
            "openedOnPaywalledPublishers": sum(any(d in (p["url"] or "") for d in PAYWALLED) for p in opened),
            "pdfPages": len(pdf), "pdfOpened": sum(p["recorded"] == "opened" for p in pdf),
            "pdfOpenedMedianLines": statistics.median([p["lines"] for p in pdf if p["recorded"] == "opened" and p["lines"]])
            if any(p["recorded"] == "opened" and p["lines"] for p in pdf) else None,
            "contradicted": dict(statements)}


def revision():
    try:
        head = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=common.STUDY, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(Path(__file__).resolve())], cwd=common.STUDY,
                               capture_output=True, text=True, check=True).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def build():
    if Path(engines.__file__).resolve().parents[1] != FREEZE2.resolve():
        raise SystemExit("Run with OOPC_STUDY_CODE=%s: E8's records were parsed by its code" % FREEZE2)
    value = e8()
    ids = {jread(p)["question"] for p in (E8 / "items").glob("*.json")}
    value["codex"] = a2_codex(ids)
    value["meta"] = {"builder": "studies/macromolecules/analysis/e8_provenance.py", "analysisRevision": revision(),
                     "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "code": str(FREEZE2)}
    return value


# ----- markdown -----

PARAGRAPH = (
    "E8's checker contradicted {total} statements in the Claude Code answers (K0c {k0c_all}, KFc {kfc_all}; "
    "{e8_statements} statements checked) against none in A2's Codex K0 and KF answers to the same 20 questions "
    "({codex_answers} answers, {codex_statements} statements checked). Five of the {total} are the answer's own report "
    "that a source could not be read, and they are an artefact of how freeze-2 records Claude Code's fetches, not "
    "errors of the answers: in each case the raw stream shows that every fetch of the named source returned a PDF's "
    "compressed or encrypted bytes that WebFetch's reader could not decode, or a redirect notice, and the parser records "
    "such a fetch as \"opened\" because it marks a WebFetch refused only for an error flag or an error phrase in its "
    "first 200 characters. Told the source was opened, the checker contradicted accurate statements. The same "
    "mislabelling covers {opened_bad} of the {opened} fetches recorded as opened in the 40 E8 answers, in "
    "{answers_bad} answers ({pdf_bad} of the {pdf} PDF fetches returned unreadable bytes); in the Codex answers no "
    "page recorded as opened had an error-like title or fewer than six lines, since Codex extracts a PDF's text and a "
    "one-line page counts as refused, though its streams keep only a page's title and length. The paper can therefore "
    "report E8's contradicted statements as {kept} (K0c {k0c}, KFc {kfc}) once these five are set aside, still well "
    "above Codex's 0 even per statement checked. Of those {kept}, the checker's own categories put {inferences} as the "
    "researcher's inferences, {source_contradicted} as statements a cited source contradicts, {attribution} as "
    "attributions, {background} as background, {bibliography} as bibliographic details, {inference_contradicted} as an "
    "inference a source contradicts and {other_provenance} as a real provenance error (a claim that the saved findings "
    "had all been reviewed when one was only added), consistent with the earlier reading of 19 inferences and 13 "
    "uncited background statements or attributions among the 47 (the five are provenance statements, outside both). The paper should not "
    "present the five as false claims of failed access, and should note that a Claude Code session's record of what "
    "it opened overstates what it read.")


def paragraph(e):
    """What the paper can claim, with the numbers of this build."""
    by_arm, kinds = e["contradicted"]["byArm"], e["contradicted"]["byKind"]
    k0c = by_arm.get("K0c", 0) - sum(1 for x in e["cases"] if x["item"].endswith("K0c"))
    kfc = by_arm.get("KFc", 0) - sum(1 for x in e["cases"] if x["item"].endswith("KFc"))
    return PARAGRAPH.format(total=e["contradicted"]["total"], k0c_all=by_arm.get("K0c", 0),
                            kfc_all=by_arm.get("KFc", 0), e8_statements=e["statements"],
                            codex_answers=e["codex"]["answers"], codex_statements=e["codex"]["statements"],
                            opened_bad=e["openedNoContent"], opened=e["recorded"].get("opened", 0),
                            pdf_bad=e["pdfOpenedUnreadable"], pdf=e["pdfFetches"],
                            answers_bad=e["answersWithOpenedNoContent"], kept=k0c + kfc, k0c=k0c, kfc=kfc,
                            inferences=kinds.get("inference/inference", 0),
                            source_contradicted=kinds.get("source-fact/contradiction", 0),
                            attribution=kinds.get("source-fact/attribution", 0),
                            background=sum(v for k, v in kinds.items() if k.startswith("background/")),
                            bibliography=kinds.get("source-fact/bibliography", 0),
                            inference_contradicted=kinds.get("inference/contradiction", 0),
                            other_provenance=kinds.get("provenance/provenance", 0) - len(e["cases"]))


def markdown(v):
    e, c = v, v["codex"]
    lines = ["# E8: contradicted \"could not read\" statements and the web-action record", "",
             "Drawn from the records only by `%s` (revision %s) on %s; no engine call. E8 `2026-10-kf-e8/r1-s1` "
             "(K0c and KFc: the researcher on Claude Code, checked by Codex); comparison: A2's Codex K0 and KF answers "
             "to the same 20 near questions, three replicates. Stream parsers: freeze-2 (`%s`)." % (
                 v["meta"]["builder"], v["meta"]["analysisRevision"], v["meta"]["builtAt"], v["meta"]["code"]), "",
             "## How a fetch's outcome is recorded", "",
             "- Claude Code (`engines.parse_claude_stream`): a WebFetch is `refused` when its tool result is flagged "
             "as an error or its first 200 characters match `REFUSED_PAGE` (HTTP 403/404, \"request failed\", a "
             "browser check); otherwise `opened`. WebFetch returns a model's summary of the fetched page, so a PDF "
             "whose text it cannot decode, a cross-host redirect notice (\"REDIRECT DETECTED\", not followed) and a "
             "\"document not found\" page come back as ordinary text and are recorded `opened`.",
             "- Codex (`engines.parse_codex_stream`): an open is `opened` only when the page reports more than one "
             "line (\"Total lines: N\") and its title is not an error page; Codex extracts a PDF's text itself. The "
             "stream keeps only a page's title and length.",
             "- The checker receives these outcomes as the session's `webActions` (`parity.session_record`) and is "
             "told to use them for statements about what the session read.", "",
             "## The five statements", ""]
    for i, case in enumerate(e["cases"], 1):
        lines += ["%d. **%s**: \"%s\"" % (i, case["item"], case["statement"]),
                  "   - The answer said: \"%s\"" % case["answerSaid"],
                  "   - The checker: %s" % case["checkerReason"],
                  "   - The record: %s." % "; ".join("%s %s" % (a["url"][:90], a["outcome"]) for a in case["record"]),
                  "   - What each fetch returned: %s." % "; ".join(
                      "%s (recorded %s): %s, \"%s\"" % (f["url"][:80], f["recorded"], f["returned"], f["text"][:150])
                      for f in case["fetches"]),
                  "   - Verdict: %s." % case["verdict"]]
        if case["readableFetchesOfNamedSources"]:
            lines.append("   - Readable fetches of a named source: %s." % ", ".join(case["readableFetchesOfNamedSources"]))
        if case["otherFetchesTheCheckerCited"]:
            lines.append("   - Also cited by the checker, a page that is not one of the sheets the answer meant: %s." %
                         "; ".join("%s (recorded %s): %s, \"%s\"" % (f["url"][:80], f["recorded"], f["returned"],
                                                                     f["text"][:150])
                                   for f in case["otherFetchesTheCheckerCited"]))
    lines += ["", "The sixth provenance statement contradicted in E8 (%s) is of another kind: \"%s\" (%s)." % tuple(
        next(((s["item"], s["statement"], s["reason"]) for s in e["contradicted"]["provenance"] if not s["aboutReading"]),
             ("none", "", ""))), "",
        "## How often a fetch recorded as opened returned no document", "",
        "| | Answers | Answers with a fetch | Fetches | Recorded opened | Opened but no document | Answers with one |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for arm, a in e["byArm"].items():
        lines.append("| %s (Claude Code) | %d | %d | %d | %d | %d | %d |" % (
            arm, a["answers"], a["answersWithAFetch"], a["fetches"], a["recordedOpened"], a["openedNoContent"],
            a["answersWithOpenedNoContent"]))
    lines += ["", "E8, %d answers, %d WebFetch calls (recorded %s). Of the %d recorded opened, what came back: %s. "
              "Recorded refused: %s. PDF fetches: %d, of which %d were recorded opened but returned unreadable bytes." % (
                  e["answers"], e["fetches"], ", ".join("%s %d" % kv for kv in sorted(e["recorded"].items())),
                  e["recorded"].get("opened", 0), ", ".join("%s %d" % kv for kv in sorted(e["openedReturned"].items(),
                                                                                        key=lambda kv: -kv[1])),
                  ", ".join("\"%s\" %d" % kv for kv in sorted(e["refusedReturned"].items(), key=lambda kv: -kv[1])),
                  e["pdfFetches"], e["pdfOpenedUnreadable"]), "",
              "A2's Codex K0 and KF, %d answers to the same questions (%d opened a page, %d of them matched to their "
              "stream%s): %d page opens or finds, recorded %s. Of those recorded opened: %d with an error-like title, "
              "%d of 5 lines or fewer, median %s lines; %d on publisher article pages where the stream cannot show "
              "whether the full text or only an abstract came back. PDF opens: %d, %d recorded opened (median %s "
              "lines of extracted text). Contradicted statements in these Codex answers: %s." % (
                  c["answers"], c["answersWithAnOpen"], c["answersWithAnOpen"] - len(c["unmatched"]),
                  "; unmatched: %s" % ", ".join(c["unmatched"]) if c["unmatched"] else "",
                  c["pages"], ", ".join("%s %d" % kv for kv in sorted(c["recorded"].items())),
                  len(c["openedErrorTitle"]), c["openedAtMost5Lines"], c["openedMedianLines"],
                  c["openedOnPaywalledPublishers"], c["pdfPages"], c["pdfOpened"], c["pdfOpenedMedianLines"],
                  ", ".join("%s %d" % kv for kv in sorted(c["contradicted"].items())) or "none"), "",
              "E8's contradicted statements: %d (%s); by kind/category: %s." % (
                  e["contradicted"]["total"], ", ".join("%s %d" % kv for kv in sorted(e["contradicted"]["byArm"].items())),
                  ", ".join("%s %d" % kv for kv in sorted(e["contradicted"]["byKind"].items()))), "",
              "## What the paper can claim", ""]
    lines.append(paragraph(e))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    value = build()
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, text in (("results.json", json.dumps(value, indent=1, ensure_ascii=False, default=str) + "\n"),
                       ("results.md", markdown(value))):
        (args.out / name).write_text(text, encoding="utf-8")
        os.chmod(args.out / name, 0o600)
    print(json.dumps({k: value[k] for k in ("answers", "matchedStreams", "fetches", "recorded", "openedReturned",
                                            "answersWithOpenedNoContent")}, indent=1))
    print(json.dumps([{k: c[k] for k in ("item", "verdict")} for c in value["cases"]], indent=1))


if __name__ == "__main__":
    main()
