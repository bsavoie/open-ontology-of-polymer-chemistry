# The core loop

Ask → answer → save → review → reuse, with an optional reflection and an occasional measurement.

| Step | What happens | Module |
| --- | --- | --- |
| Ask | A question is queued and run by one background worker, oldest first. | `oopc/ask.py` |
| Answer | One researcher session with two knowledge tools and web search; its first turn answers. | `oopc/ask.py`, `oopc/engines.py` |
| Save | Its second turn writes what it read. Findings read in a source are added; figure readings, conversions and combined values wait for review; source notes are stored. | `oopc/ask.py`, `oopc/knowledge.py` |
| Review | After the answer, its sources are captured and one reviewer session checks its waiting findings and a sample of its added ones, and compares its new findings with the most related saved ones. | `oopc/reviewer.py`, `oopc/consistency.py`, `oopc/sources.py` |
| Reuse | `search_knowledge` returns the most relevant saved findings; an answer cites them by id. | `oopc/knowledge.py` |
| Reflect (optional, off by default) | Every few days the recorded searches are replayed; reviewed names, polymer ids, property terms and links between terms used together fix what they missed. | `oopc/reflect.py` |
| Measure | On demand, the parity set compares the researcher with a plain session. | `oopc/parity.py`, `oopc/improve.py` |

## Ask and answer

A question you ask that names a polymer by a name the graph gives to two
unrelated polymers (PEI, PFA or PPO) is not queued: the app asks which one you
mean and adds its full name to the question. Research-queue questions have no
one to ask, so the researcher states its reading.

### Scope

The researcher answers within the workspace's **scope**, a setting (Settings →
Scope, or `oopc scope`) that its instructions name as its field; empty, the
default, it is polymer science and engineering, so the same harness can serve
another research area by changing one setting. The owner would rather answer a
marginal question than turn away one that matters (2026-11-06), so the
researcher sorts each question into three kinds and, when unsure, takes the
more inclusive one:

- **About the field, or adjacent to it** (the chemistry, physics or methods
  that work in the field draws on): answered and saved as usual.
- **Outside the field but connected to it, however marginally**: answered as
  usual, with one sentence saying what it asks about (`outOfScope`). By
  default its findings are not saved: there is no second turn, review or
  research queue, its session is deleted at once, reflection does not mine it,
  and its page says it was not saved (`depositState` `skipped`). The
  `saveOutsideScope` setting (Settings → Scope, or `oopc scope --save-outside
  yes`) saves them as in-scope answers are. `oopc improve summary [--days N]`
  counts what the scope held back: questions declined (`outOfScope`) and
  answers whose findings were not saved (`notSavedOutsideScope`).
- **With no connection to the field at all**: not researched. The first turn
  returns only that sentence and the question is completed with no second
  turn, deposit, review or research queue. Its page says it was outside the
  scope and links to another interface: the `redirectUrl` setting, or by
  default the chat of the engine that ran it (chatgpt.com or claude.ai). A
  follow-up can continue a conversation past a declined question, and is told
  it was not answered. Reuse and the week's summary do not count it as an
  answer.

A question is declined only when its first turn returns no answer, so an
answer always stands. The scope is part of the prompt, so a changed scope is a
changed prompt version. The rest of the instructions, the harness's name and
its knowledge base still speak of polymers: under another scope, Codex in
particular still answers some polymer questions (2026-11-06), so a harness for
another area renames those too.

The researcher's instructions are `RESEARCHER` (the answer) and `DEPOSIT` (the
findings) in `oopc/ask.py`, one prompt in two parts. It has one tool, traced
with its exact results:

- `search_knowledge`: the most relevant saved findings for a query, then up to
  three source notes. When the query names a polymer (by any name the graph
  knows or a reflection added, also with a grade number after it, as in EVOH44), only findings about
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
  "Interpretation:" and citing its premises, never attributed to a paper; each
  unit conversion's factor is derived from the units' definitions one step at a
  time, with the running value written after each step, and a ranking or
  comparison uses only values converted to one unit, its stated order checked
  against them (CL-24, 2026-11-06: conversions had slipped by factors of 10 and
  1,000, and the answer check does not catch such slips);
- **textbook background**, starting "Background:", with no citation.

Conflicting sources are reported side by side with the reading given as an
Interpretation. The answer is read on its own: it gives each thing the question
asks for, or says it was not found, and never points to findings "below". The
answer also returns its citations, limitations and up to three open questions.
Notes on how it looked (a page that would not open, the copy it read) go in the
limitations, not the answer. A number seen only in a search snippet is not
reported as a result.

The session has two turns, so the answer does not wait for what is saved from
it (2026-10-25: writing the findings was about two-thirds of the researcher's
output, and its answers took 2.3 times as long as a plain session's). The first
turn returns the answer, and the question is marked answered and shown. Then,
in the background, a second turn resumes the same session, with the same
schema, tool and web settings so the engine reuses its cached prompt, and
without searching or reading anything more. It returns new **findings** (values
it read itself, one value each: a one-sentence statement, material, property by
its full name and abbreviation, value, unit, conditions as the source states
them, source, exact locator, the shortest verbatim span that shows the value
with its label or unit (under about 25 words, kept private), and how it got
the value: read in the text or a table, read off a figure, converted or
calculated, or combined from more than one place) and one **source note** per
source read, including one that lacked what it looked for or could not be
opened (with the URL it actually read, when that differs). Every value the
answer reports from a source it read is a finding, including method and
specimen details; besides these, the researcher saves the other values for the
same material or a closely related property in the passage it read (up to about
ten more per source), since reading them again later would cost a new session.

While the second turn runs, the answer's **What this answer saved** section says
its findings are being saved; once they are, it lists them under the source they
were read in, with each source's note, the facts already saved by earlier
questions, and how many are added, waiting for review or reviewed. A second turn
that crashed, was interrupted or returned no valid answer is tried once more;
if it fails again, or fails for another reason, the findings are not saved and
the reason is shown beside the answer, which stands. The engines save a session under the user's home folder, outside
`.oopc/`, only so it can be resumed: it is deleted when the second turn ends,
whatever its outcome. Codex's index of the session (its threads, turns and
items) is kept in the session's own private folder, never in `~/.codex`, and
deleted with it; such sessions make no Codex memories. A deposit whose process
stopped (the app, an interrupted `oopc ask`, a killed tick) is settled by the
next app start, task list or loop tick: the second turn is tried once more if
the engine still has the session, else the findings are not saved
(`interrupted`); a deposit whose second turn had already finished is saved from
its result.

### Follow-up questions

A question can follow an answered one, continuing its conversation; only the
latest answer in a conversation can be followed, so a conversation is one line
of questions. A follow-up is a question of its own: a new session (on whichever
engine is chosen then), its own depth and time limit, and its own two turns,
deposit and review, so what it finds is saved and checked like any answer. The
engine session of the answer before it is not kept to be resumed.

It waits until the answer it follows has saved its findings and finished the
review that runs right after (on either engine, at most 30 minutes; nothing is
waited for when the process doing it has stopped), so it can read them in saved
knowledge with their verdicts and does not save them again. Then its first turn
carries `FOLLOW_UP` (in `oopc/ask.py`) and the conversation so far between the
instructions and the question: each earlier question and answer, and up to 25
findings each answer cited or saved with their status now, a verdict reached
since included (a Rejected one with its reviewer's reason). The earlier answers
are context, not sources: a fact repeated from them is cited by the finding or
URL they cited, and a finding since rejected, or a new source that contradicts
an earlier answer, is said plainly. Past 30,000 characters the oldest answers
are left out first (their questions stay; their findings can still be
searched), then the last one is shortened. What a follow-up was told is kept as
`conversation.txt` beside its question, and its prompt version includes
`FOLLOW_UP`. A question asked on its own never carries it, so its prompt, and
the parity set's, is unchanged.

A follow-up's findings are filed by the whole conversation's questions ("its
melting point" after a question on PLA files under polylactide), and a polymer
name the conversation already settled (PEI written out as polyetherimide) is
not asked about again. In the app, an answer's page shows its whole
conversation and ends with a box for a follow-up to the latest answer; History
and Recent list a conversation once. `oopc ask --follow QUESTION_ID` asks one
from the command line.

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
another work), so a misspelled title never reaches an answer. A source is one
document: its DOI, else its address without the parameters that only change the
view, language or version; a parameter that names the document (a data sheet's
`FILENAME`, an EPA `Dockey`, CiteSeerX's `doi`) is kept (`source_key`, CL-23).
A fact already saved is not saved twice: same
source (a DOI and its doi.org URL are one source), same unit and same numbers,
and either the same statement, the same property, value, unit and material, or
the same unit for a material one of them names more specifically. The same
numbers in another unit (6.00 GPa and 6.00 MPa) are two readings, one of them
wrong, so both are kept and compared, and so are opposite outcomes in words
("reported insoluble in acetone" and "reported soluble in acetone"). One judged
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
excerpt (search reads the new excerpt from then on), and for a finding whose
polymer name is ambiguous it writes the material out. A Reviewed finding
checked again for its label or excerpt keeps its review unless the second
reviewer finds it unsupported, which makes it
Needs checking. Each finding takes the
verdict. A waiting finding the reviewer skips becomes `uncertain`; a sampled one
it skips stays added. A review has five minutes and stops sooner when the
session writes nothing for 150 seconds (some sessions stalled after a web
action); a failed one is retried on another engine when there is one. Reviews of
one workspace take turns, so an answer is never reviewed twice at once.

### Consistency with saved knowledge

The owner asked on 2026-11-05 for new findings to be checked against what is
already saved. Comparing each with every saved finding would cost too much, so
the same review compares each with a small tranche, chosen without an engine
(`oopc/consistency.py`): the saved findings filed under its polymer, its
families or members (or, unfiled, naming its material), and every other finding
from its source, never its own answer's or a rejected one; unfiled findings that
name its material and property are candidates too. Each candidate needs
the same polymer and a related property (the same property term, the same words,
one's words the other's abbreviation, as Tg and "Glass transition temperature
(Tg)", three in five words or more in common, or one named in the other's
statement; "tensile strength at break" and "tensile yield strength" are two
properties) and is scored on how likely and how
telling a conflict would be: the same polymer, the same property, the same grade
or specimen (shared material words), a shared source (two readings of one
document), values in comparable units, and values in **tension**, weighted by
status (reviewed first). The screen looks for qualitative inconsistency, not
measurement uncertainty (owner, 2026-11-05): for materials described alike at
test temperatures within 20 degrees of each other or not given (temperatures
further apart may explain a difference), ranges more than a quarter apart, or
temperatures more than 20 degrees apart whatever their unit; or outcomes in
words of one property that are opposite (one negates the other, as "could not
be melt-spun" and "melt-spun" or insoluble and soluble, or a short list of
opposites such as brittle and ductile, amorphous and crystalline, transparent
and opaque, pass and fail); or one source, material, property and conditions
read as values that cannot be one number or as opposite outcomes. A value with
an uncertainty (55.3 ± 0.2 is 55.1–55.5), in scientific notation (6.88 × 10⁻¹⁰)
or followed by % or its own unit is read; a bound (<5, ≥80, at least 2) is in
tension only with a value beyond it by more than the gap; a cell with several
values is not compared. A test temperature is read from the conditions (23 °C,
296 K, room temperature), never a rate (10 °C/min), and is unknown when they
give several. The **depth** (Settings → Compare
new findings with saved ones: Off, Narrow 3, Standard 8 by default, Broad 20) is
how many each new finding is compared with, at most three from one source. The
answer's budget of saved findings in the prompt (five times the depth, at least
one per new finding, at most 100) is shared out a pair at a time, each new
finding's most telling first, so every new finding is compared; each saved
finding is given once. On an unchanged store the ranking gives the same tranche.
A finding saved while property terms are in force is annotated to them at once,
so it is compared, and found by links, through them.

After a deposit the tranche is screened: an answer with a pair in tension
joins the review queue even with nothing else to review; one with related
findings but no tension is compared only in a review that runs anyway (most
answers have one: about eight findings at a 1-in-5 spot check); deposits made
before 2026-11-05 or with the depth at Off are never compared. The reviewer gets
each new finding with the short ids (s1, s2, ...) of the saved findings it is
compared with, and each saved finding once with its status, one finding a line:
its statement, value, unit and conditions, its material and property only when
the statement does not say them, and its source as a DOI or URL. A pair in
tension keeps its sources' titles, locators and longer fields, with captured
passages, since those sources are the ones likely to be opened. (In the first
trial the comparison was three quarters of a review prompt; this form is about
half its size.) It judges them by what
they state: a stated difference in grade, composition, processing, specimen,
method, rate, temperature or humidity makes different values consistent only
when it plausibly accounts for the difference in size and direction (a
transition between two temperatures, say); differences within measurement and
rounding are no conflict; values far apart under nearly identical conditions,
or opposite outcomes a few tens of degrees apart with nothing between them to
explain it, cannot both be right. It opens both sources only for a pair that
cannot both be right, and returns only conflicts: the new finding
misstates its source (`new-misread`), the saved one does (`saved-misread`), both
read their sources right and the sources disagree (`sources-disagree`), or it
cannot tell (`unresolved`), each with one sentence.

Every conflict is kept in the store with the pair, the reading, its reason and
who settled it. By default (Settings → **The reviewer settles conflicts**) the
reading takes effect: a misread finding is Rejected, except that a Reviewed one
becomes Needs checking (as a second review's unsupported verdict makes it, once
per review however many conflicts name it) and a new finding the same review
found supported is not rejected (the conflict stays open); findings whose sources
disagree both stay, linked. A rejected finding's pending spot check or recheck is
called off, so a later review cannot undo the decision, and a conflict whose
finding was merged into a duplicate follows it. With **I settle
conflicts** nothing changes status: both findings are linked and the conflict
waits in the Knowledge tab with the reviewer's reading, where a person settles
it as the new one wrong, the saved one wrong (either is then Rejected, with
`person` as who judged it), the sources disagree (both stay, linked) or no
conflict (unlinked); `oopc conflicts` lists them and `oopc conflicts settle ID
RESOLUTION` settles one. Nothing a person does marks a finding Reviewed. A
search lists `conflictsWith` on a finding linked to others still in force, and
the researcher reports both with their sources.

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
questions join the queue; research answers never queue more research. Then, if
reflection is on, it runs once every `reflectEveryDays` days (below). Background
work keeps a quota reserve (30% for Codex, 0% for Claude Code by the owner's
decision of 2026-09-29); your own questions have none. `oopc loop install` runs
the loop hourly with launchd.

## Reflection (optional)

The owner asked on 2026-10-29 for the ontology refinement the Macromolecules
study tested (Part C) to ship as an optional, scheduled step, though it did not
change answers measurably there: run once on the frozen store, its 148 edits
raised lookup recall from 0.90 to 0.92. It is off by default:
`oopc reflect schedule DAYS` runs it from the loop's tick every DAYS days (the
setting `reflectEveryDays`; 0 turns it off), and `oopc reflect run` runs it
once now. `oopc reflect run --dry-run` mines and prints the dossier a curator
would read, without an engine and without writing anything.

A run has five steps:

1. **Mine** (no engine). Every `search_knowledge` call recorded in the answers
   finished since the last run is replayed on the store as it is now, and
   misses are collected: a finding the answer saved again that none of its
   searches returns; a search or question naming a polymer the graph does not
   know (so the search could not filter by polymer), and a finding without a
   polymer id that names no polymer the graph knows (by its candidate names,
   else by its material when that is short enough to be a name: a longer
   description, "alternating copolymer derived from ...", no name could fix, and
   companies such as BASF are never names); a cited finding that the
   answer's first search for its polymer did not return; and a search that
   returned nothing, followed by a web search for the same polymer and
   property. They are grouped by unknown name, else polymer and property, and
   the 40 groups with the most misses make the dossier. Separately, **co-use**
   (owner, 2026-11-05: findings of two kinds used together should be linked):
   two findings of different property types (a property term, or the property
   as worded) on related polymers, both cited by one answer, the second not
   returned by the first search that returned the first. A test condition saved
   as a finding of its own ("DSC heating rate", "film conditioning
   temperature") is no property used together and never counts: in the 1,066
   answers of 2026-10 such pairs were two thirds of these misses (711 → 241,
   and the pairs cited together in two answers or more 163 → 41). Pairs of types cited
   together in at least two answers and searched for separately in at least one
   make the dossier's co-use part (up to 15 groups, each with both sides'
   wordings and examples). Replaying those answers found 92% of such pairs
   returned together already; the rest scatter over thousands of wordings, which
   is why a link joins property terms, not wordings.
2. **Propose.** One curator session (the preferred engine, web only) reads the
   dossier and the graph's polymers and proposes edits from a closed list: a
   name for an existing polymer (with a source that quotes it), a finding's
   polymer id, a property term (the names and symbols of one property), or a
   link between two property terms used together (companion results of one
   test, or properties reported side by side; never a property and a test
   condition), each term in force or proposed in the same list. Each cites the
   misses it answers, and the curator does not annotate a finding its own
   proposed name files (in the 2026-11-05 trial 22 of 38 proposals were such
   annotations). An edit that breaks a rule (no quote with the name, a name that
   also means an unrelated polymer and is not marked ambiguous, a polymer id a
   person approved, an edit reverted before) is refused before review.
3. **Review.** A fresh reviewer session, on the other engine when it is signed
   in, opens each edit's sources and approves or rejects it with one sentence of
   reason.
4. **Drop.** Each approved edit is applied alone to a private copy of the
   store, and the past searches it could change are replayed with and without
   it. An edit that loses more results the answers cited than it fixes misses is
   dropped (in the study this caught long aliases and broad terms crowding out
   relevant findings). A miss counts as fixed only if the store as it stands
   still misses it and the copy with the edit does not. Links are measured after
   the run's other edits apply, so their terms exist; a link only adds results,
   so one that fixes no co-use miss is dropped too, and the results it adds per
   search are recorded. A term is worth little alone (its use is the links it
   makes possible), so a term dropped alone that an approved link needs is
   measured again with that link, and the two are kept or dropped together
   (each edit records the other in `with`). Replaying the 2026-11-05 trial's run
   this way kept its Tg term and Tg–Tm link (six misses fixed, the one result the
   term lost alone still lost), which the term-first measure had stranded.
5. **Apply.** The rest take effect. Search reads the overlay's names beside the
   graph's; a polymer id is set on its finding, and a new name files the unfiled
   findings that use it (by the same rule a deposit files a finding); property
   terms fill `property_terms` and `finding_terms`, from which a query naming one
   of a term's names also finds findings written with the others; links fill
   `term_links`, from which a query naming a polymer and one linked term also
   gets up to five findings of the other about that polymer, its families or
   members (those from sources it already returned first), after the same-source
   findings. With no edit in force, search returns exactly what it did before.

Every edit is kept in `.oopc/loop/ontology.json` with who proposed it, the
reviewer's verdict and reason, what the replay measured and the findings it
refiled. `oopc reflect revert ID` undoes one: its names stop being read and each
finding it refiled goes back to its earlier polymer id and the record of who set
it (unless something refiled it since); a term that leaves force takes the
links that join it with it; an edit once reverted is never proposed
again. A refiled finding is indexed for search again from its current text, both
when an edit is applied and when it is reverted. The wiki seed
and the graph releases never change: an edit worth keeping for everyone goes
into the wiki and a new seed, as before. Both sessions are recorded in the calls
ledger and fail with a named reason, a transient failure tried once more; a run
that fails is recorded and the loop waits its days before the next. The
operator page's **Loop health** shows the edits in force and recent runs.

## Measure

`oopc parity run --engine E [--checker C]` answers the eight fixed questions in
`benchmarks/parity.json` (four covered by saved findings, four new) two ways:
a **plain** web-only session (its answers frozen per engine and model) and the
**ontology** researcher (both turns; it saves nothing). The researcher's time is
recorded to its answer and in total, and its tokens are both turns'. Every run checks both arms again,
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
before and after a change to `RESEARCHER` or `DEPOSIT`, which is made as a
reviewed commit; the median seconds to the answer and in total are shown beside
its measures and do not decide whether the change is recommended. A question
whose researcher arm failed to write its findings in either run is left out of
the token comparison, and the comparison says how many there were.
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
deposits, reviews, conflicts), `questions/<id>/` (a follow-up's with the conversation it
was told), `research.json`, `settings.json`,
`log.jsonl`, `calls/`, `parity/`, `sources/` (captured source text),
`crossref/` (DOI metadata), `ontology.json` (the reflection's edits) and
`reflect/` (each reflection run's record, misses and dossier). Traces are under `.oopc/runs/`. The retired
0.11 records stay where they were; `oopc import-legacy --apply` copied what was
useful into the new store once.

Several processes share one store at once: the app, `oopc ask`, the loop's
tick, and questions run in parallel (owner, 2026-11-05). `knowledge.sqlite`
runs in WAL mode, so a reader never waits for a writer, and a write that
depends on what it read (a deposit's duplicate check, a review's verdicts, a
conflict's settlement) takes the store's write lock before it reads; two
answers saving one fact at once save it once. A review first claims its
answer in the store, so the same answer is never reviewed by two sessions,
while reviews of different answers run side by side; `review.lock` is held
only while a review reads its findings and while it records its verdicts,
never through the engine session, so reflection's edits and upkeep wait
seconds, not minutes. One question's `question.json` is changed by one
process at a time (a lock file beside it), and so is `settings.json`.
`parallelQuestions` (1 by default, at most 8) sets how many questions run at
once and how many sessions each engine runs at once; parallel sessions share
each subscription's limits, and a follow-up still waits for the answer before
it. Only the process holding `questions/drain.lock` runs questions, so a
question it finds running when it starts was left by one that stopped, and is
retried once. Run upkeep with no questions running. WAL needs a local disk:
never put `.oopc/` on a network share.

Several people can share one host (owner, 2026-11-05). `oopc people add NAME`
adds a person (the first is the owner) with a password, kept only as a salted
hash in `people.json`; with nobody added the app works as before. Once people
exist, the app asks each to sign in (a cookie for 12 hours; every instance of
the app on the host shares the sign-ins, kept as token hashes in
`sessions.json`, so one sign-in serves them all and survives a restart), and:

- each person sees only their own questions, answers, conversations and
  traces; findings, the review queue, conflicts and reflection's edits are
  shared, and a finding shows who saved it;
- each person's questions, findings and reviews run on their own Codex or
  Claude account, signed in from the app's settings into an engine folder of
  their own (`people/<id>/codex` and `claude`, as `CODEX_HOME` and
  `CLAUDE_CONFIG_DIR`); the owner keeps the host's own sign-ins, and each person
  has their own engine slots. A person the owner sets to use the host's
  sign-ins instead (`oopc people add NAME --host-engines`, or `oopc people
  engines NAME host|own`) runs on the host's folder and shares its slots, and
  cannot connect or cancel its sign-ins. People who share one account must
  share the folder too: a copy of a sign-in in each folder ends the others at
  its first token refresh (Codex: "your refresh token was already used");
- only the owner changes settings, runs the loop, queues background research
  or opens the operator's views; settlements, setting changes and reverts
  record who made them;
- reflection mines everyone's answers (owner, 2026-11-05), but reads another
  person's answer without its question: only its searches and the findings it
  cited, which are shared anyway, so their question never reaches the curator
  on the owner's engine; the edits it makes serve everyone.

The app listens only on this computer, so everyone uses it from the host
itself. The host's operating-system user can read every file under `.oopc/`,
other people's engine sign-ins included: one host is for people who trust
whoever runs it.

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
to it); `index` indexes findings and notes for search again where their search
text differs from their stored text (before 2026-10-29 a reviewer's excerpt,
some of these passes and a note's Crossref title changed a record without it);
`reviews --limit N` reviews what is waiting now.

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
