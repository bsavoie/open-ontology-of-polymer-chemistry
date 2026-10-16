# The core loop

Ask → answer → save → review → reuse, with an occasional measurement.

| Step | What happens | Module |
| --- | --- | --- |
| Ask | A question is queued and run by one background worker, oldest first. | `oopc/ask.py` |
| Answer | One researcher session with two knowledge tools and web search. | `oopc/ask.py`, `oopc/engines.py` |
| Save | Findings read in a source are added; figure readings, conversions and combined values wait for review; source notes are stored. | `oopc/knowledge.py` |
| Review | After the answer, its sources are captured and one reviewer session checks its waiting findings and a sample of its added ones. | `oopc/reviewer.py`, `oopc/sources.py` |
| Reuse | `search_knowledge` returns the most relevant saved findings; an answer cites them by id. | `oopc/knowledge.py` |
| Measure | On demand, the parity set compares the researcher with a plain session. | `oopc/parity.py`, `oopc/improve.py` |

## Ask and answer

A question you ask that names a polymer by a name the graph gives to two
unrelated polymers (PEI, PFA or PPO) is not queued: the app asks which one you
mean and adds its full name to the question. Research-queue questions have no
one to ask, so the researcher states its reading.

The researcher's instructions are `RESEARCHER` in `oopc/ask.py`, the only
prompt. It has one tool, traced with its exact results:

- `search_knowledge`: the most relevant saved findings for a query, then up to
  three source notes. When the query names a polymer (by any name the graph
  knows, also with a grade number after it, as in EVOH44), only findings about
  that polymer, its broader families or its narrower members are returned (a
  search for HDPE finds polyethylene-family findings, not LDPE ones); findings matching more of the other words come
  first, and ones matching only the polymer fill a short result up to ten.
  `limit` (10 to 25, default 10) is the total of these. Then come up to twelve
  other findings saved from the same sources, usually the method, specimen and
  conditions, so a source already read need not be opened again. Results are
  grouped as reviewed, added and needing checking, with short entries; a note
  keeps the URL its source was read at.

It uses the web only for what saved knowledge does not cover, within the
question's **depth**:

| Depth | Time limit | Web searches (about) | Sources (about) |
| --- | --- | --- | --- |
| Quick | 5 min | 6 | 4 |
| Standard | 10 min | 10 | 8 |
| Thorough | 20 min | 25 | 20 |

A source is one document; re-reading parts of it is free, and the researcher may
go two reads over to finish a source that answers the question. It spends at
most about two further searches on any one missing detail. The time limit is
enforced; the budget is an instruction.

The answer has three kinds of statement:

- **what a source reports**, cited in backticks right after the claim (a finding
  id or a source URL);
- **the researcher's own reasoning** (a comparison, calculation, scope limit, or
  a judgement that sources disagree or a value looks mislabelled), starting
  "Interpretation:" and citing its premises, never attributed to a paper;
- **textbook background**, starting "Background:", with no citation.

Conflicting sources are reported side by side with the reading given as an
Interpretation. The answer is read on its own: it gives each thing the question
asks for, or says it was not found, and never points to findings "below". The
answer also returns its citations, new **findings** (values
it read itself, one value each: a one-sentence statement, material, property by
its full name and abbreviation, value, unit, conditions as the source states
them, source, exact locator, the shortest verbatim span that shows the value
with its label or unit (under about 25 words, kept private), and how it got
the value: read in the text or a table, read off a figure, converted or
calculated, or combined from more than one place), one **source note** per source
read, including one that lacked what it looked for or could not be opened (with
the URL it actually read, when that differs), limitations and up to three open
questions. Notes on how it looked (a page that would not open, the copy it
read) go in the limitations, not the answer. A number seen only in a search
snippet is not reported as a result. Every value
the answer reports from a source it read is a finding, including method and
specimen details; besides these, the researcher saves the other values for the
same material or a closely related property in the passage it read (up to about
ten more per source), since reading them again later would cost a new session.

## Save

A finding needs a statement, a source and a locator or excerpt; malformed ones
are dropped and counted. Its graph polymer id is filled in from its material
or statement when they name one polymer (a member named beside its own family
gives the member); when they name none the graph knows (a trade or grade name
such as Viton), from the one polymer its question names; and when they name a
polymer by a name the graph gives to two (PEI, PFA), by the one of them the
question names. A finding that names several polymers (a blend) is not filed
under the question's.

A label that could be misread later is settled when the source is saved, never
stored as it was written (owner, 2026-10-14). The researcher writes each
material with the polymer's full name and the source's abbreviation, and says
what a sample code stands for. A name the graph gives to unrelated polymers
(PEI, PFA) that the finding does not settle is settled from the question and
what the answer says of the source, and written out ("Polyetherimide (PEI)
film"), with the original kept in the finding's detail. One the context cannot
settle is not added: it waits for review, and its reviewer writes the material
out from the source; if the reviewer cannot either, the finding is Needs
checking.
With the default review setting a finding the researcher read in the text or
a table is **added** at once on its judgement; one read off a figure, converted
or combined **needs checking** until reviewed (owner, 2026-10-14: the
researcher's own doubt flags caught one error in 1,868 while reviews cost 13–35%
of research tokens). With "review every finding first" every finding waits for
review. After the answer, a finding whose source has a DOI is filed under the
title Crossref gives for it (a typed title kept in its detail when it names
another work), so a misspelled title never reaches an answer. A fact already saved is not saved twice: same
source (a DOI and its doi.org URL are one source) and same numbers, and either
the same statement, the same property, value, unit and material, or the same
unit for a material one of them names more specifically. One judged
unsupported before is saved again only for review.

## Review

After the answer is delivered, one reviewer session checks the answer's
findings waiting for review together with a sample of its added ones (1 in 5 by default,
Settings → Spot checks). The answer never waits. The reviewer has web access
only and runs in a fresh session of the engine that wrote the answer, which can
open the sources that engine read (in the 2026-10 campaign Claude Code could
not open 41% of the sources Codex had cited). It is given first the passages
of each source's captured text around the finding's value, locator and
conditions (see **Captured sources** below), then opens the source itself (using
the URL the researcher read when given), reading the methods or experimental
section when a method or condition is at stake, and returns `supported`,
`unsupported` or `uncertain` with one sentence of reason. A source title that is
misspelled or names another work is unsupported. For a supported finding it
also quotes the span that shows the value, which fills a missing or bare
excerpt, and for a finding whose polymer name is ambiguous it writes the
material out. A Reviewed finding checked again for its label or excerpt keeps
its review unless the second reviewer finds it unsupported, which makes it
Needs checking. Each finding takes the
verdict. A waiting finding the reviewer skips becomes `uncertain`; a sampled one
it skips stays added. A review has five minutes and stops sooner when the
session writes nothing for 150 seconds (some sessions stalled after a web
action); a failed one is retried on another engine when there is one. Reviews of
one workspace take turns, so an answer is never reviewed twice at once.

## Captured sources

The engines' streams carry no source text (Codex records an opened page as its
line count; Claude Code's fetch returns a summary), so a check that depends on a
page opening that day is noisy: in the 2026-10 campaign 129 of 134 statements a
check could not confirm were source access. After an answer, before its review,
this machine fetches each cited source's open copy once, by plain HTTPS outside
the engines: the URL the researcher read it at, its URL, Europe PMC's full text
when the article is in PubMed Central, then its DOI. HTML and Europe PMC's XML
become text; a PDF does when `pdftotext` is installed. A page that refuses (an
HTTP error, a browser challenge) stays uncaptured and is tried again after a
week; nothing works around it. The text is kept privately under
`.oopc/loop/sources/` and never exported. Reviewers and checkers get the
passages around what they judge, not whole documents, and the checker records
for each statement whether it used the captured text, the live page or a
supplied record.

What researchers see: **Reviewed** (supported), **Added** (on the researcher's
judgement, never shown as reviewed), **Needs checking** (waiting, or the reviewer
could not confirm it: a lead) and **Rejected** (unsupported: hidden from searches,
kept with the reason). The rejected share of sampled added findings is the
measure of whether the researcher's judgement can be trusted.

## Failures

Every engine call returns a valid answer or fails with a named reason:
`timeout`, `crashed`, `rejected`, `invalid-output`, `interrupted`,
`not-signed-in`, `quota` (the subscription's usage limit) or `rate-limited`
(too many requests at once, while quota remains). A rate-limited session is
started once more after a two-minute pause within its time limit. A question
that crashed, was interrupted or returned no valid answer is retried once;
other failures stop, and the question can be retried from its page. A failed review is retried once by the loop, then left
failed; the operator page counts it as given up. Every attempt, with its
usage, is recorded in `.oopc/loop/calls/`.

## The background loop

`oopc loop tick` (or **Run the loop now**) reviews up to three answers still
waiting for review, then, if background research is on, asks one question from
the research queue. Background research is a number of questions a week
(Settings; 0, the default, turns it off). When it is on, your own answers' open
questions join the queue; research answers never queue more research. Background
work keeps a quota reserve (30% for Codex, 0% for Claude Code by the owner's
decision of 2026-09-29); your own questions have none. `oopc loop install` runs
the loop hourly with launchd.

## Measure

`oopc parity run --engine E [--checker C]` answers the eight fixed questions in
`benchmarks/parity.json` (four covered by saved findings, four new) two ways:
a **plain** web-only session (its answers frozen per engine and model) and the
**ontology** researcher (which saves nothing). Every run checks both arms again,
one right after the other, with one checker on sources captured once, so a
difference never comes from a page that opened one day and not another. The
checker judges each answer against the cited sources (a cited finding with what
it says, and any URL its source was read at), statement by statement: a
reported fact against its source, an Interpretation on its premises and
reasoning, Background on whether it is correct, a claim that a finding is Added
or Reviewed against its status, and a statement about what saved knowledge held
or what the session read against the researcher's recorded knowledge searches
and web actions (each page it opened and whether it opened), which the checker
is given. A missing secondary detail makes an answer uncertain; a missing main
result fails it. The checker also says separately whether the answer gave the
main result (`resultGiven`), since an honest "not found" can be complete. The
run records which prompt version it measured.

The report leads with the measures that do not depend on whether a source
opened: **contradicted statements** (unsupported for any reason but source
access), **complete answers** and **sourced results** (`resultGiven`). Passes,
statements left uncertain for source access, and the median and minimum cited
fractions come second. The guardrail (not a gate): at most one contradicted
statement more and one complete answer fewer than plain, at least 90% of
unlabelled answer parts cited (median), median token ratio at most 1.5, on at
least six checked pairs. Eight questions are descriptive: one or two either way
is noise. `oopc parity compare A B` puts two runs side by side, for example
before and after a change to `RESEARCHER`, which is made as a reviewed commit.
Add `--canaries` after changing the reviewer's instructions: wrong findings (a
changed number, an added condition, another paper's source, a misspelled title
word), which the reviewer must reject, beside true controls, one of them a value
whose method its source gives only outside the cited table. `oopc parity
recheck` fills in failed checks without answering again; a question with a
check to fill has both arms checked again.
`oopc improve summary` gives the week in numbers; the operator page shows both
under **Loop health**.

## Storage

Everything is private, under `.oopc/loop/`: `knowledge.sqlite` (findings, notes,
deposits, reviews), `questions/<id>/`, `research.json`, `settings.json`,
`log.jsonl`, `calls/`, `parity/`, `sources/` (captured source text) and
`crossref/` (DOI metadata). Traces are under `.oopc/runs/`. The retired
0.11 records stay where they were; `oopc import-legacy --apply` copied what was
useful into the new store once.

`oopc upkeep ACTION [--apply]` cleans the store once before a study freeze, for
defects left by waves written before a fix landed; it reports first and changes
the store only with `--apply`, after a copy under `.oopc/loop/backups/`.
`audit` gives the counts each target is judged by; `requeue` sends findings
their reviewer could not open back to review; `excerpts` sends findings whose
excerpt is missing or shows no label to review (Added ones at their spot check,
Reviewed ones to be checked again), whose reviewer quotes one from the source,
and withdraws excerpts it once picked from captured text by itself, a quarter
of which quoted another measurement; `disambiguate` settles ambiguous polymer names in stored findings from
their question, source title, notes and captured text, and sends the rest to
review; `titles` files every finding
under its DOI's Crossref title; `polymers` files findings without a polymer id
and narrows ones filed under a family to the member they name, listing the
rest for a person to judge, and never changes a polymer id a person approved; `duplicates` merges findings the current duplicate
rule would have merged into the best-reviewed one (a merged id still resolves
to it); `reviews --limit N` reviews what is waiting now.

`oopc knowledge --export FOLDER` writes a public snapshot of the knowledge:
`findings.jsonl` (each finding with its polymer id and name, source, locator,
status and review verdict with its reason), `notes.jsonl` (each source read, with
the URL it was read at) and `manifest.json` (counts, graph release, file hashes,
and an id that is a hash of the content). Questions, traces, verbatim excerpts
and researcher flags are left out; a local path anywhere stops the export, and
a snapshot is never written over an existing folder. The graph release and a
knowledge snapshot together are what a publication cites. `oopc knowledge
--import FOLDER` starts an empty workspace's store from a snapshot (checked
against its hashes, id and graph release), so a published study can be run again;
its findings have no excerpts.
