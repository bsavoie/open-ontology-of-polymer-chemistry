# Open Ontology of Polymer Chemistry instructions

This is the polymer ontology (`oopc`), a separate project from the reaction
ontology and the source polymer wiki. Preserve each project's history and data;
do not transfer reaction benchmark cases, thresholds or scientific judgments
into this project.

## Scope: one core loop

The project is one loop, described in `docs/core-loop.md`:

1. **Ask**: the researcher searches saved knowledge first and uses the web for
   gaps.
2. **Answer**: every reported fact carries a citation; the researcher's own
   reasoning and textbook background are labelled as such.
3. **Deposit**: findings and source notes are saved; the researcher adds the
   ones it read directly and sends figure readings, conversions and combined
   values for review.
4. **Review**: after the answer, one reviewer call checks its findings waiting
   for review and a sample of its added ones against their sources.
5. **Reuse**: the most relevant reviewed and added findings are what the next
   question reads first.
6. **Reflect** (optional, off by default): every few days the recorded searches
   are replayed; a curator proposes names, polymer ids and property terms for
   what they missed, a reviewer checks each against its sources, and the edits
   that do not lose more than they fix go into a local overlay the owner can
   revert. The owner asked for it to ship as an option on 2026-10-29, though the
   study's run of it (Part C) showed no end-to-end gain.
7. **Measure**: on demand, a small fixed parity set tracks quality and tokens
   against a direct session.

Parity with an unscaffolded Claude Code or Codex session is a guardrail, not the
goal; the ontology's value is provenance and cumulative knowledge. Judge any
proposed work by whether it serves this loop, and remember that complexity has a
cost: prefer removing a mechanism to adding one. The researcher's instructions
are one prompt in code (`oopc/ask.py`), changed by a reviewed commit and compared
with `oopc parity compare`. Do not add evaluation gates,
qualification panels, calibration stages, versioned protocol successors or
publication machinery without the owner's explicit approval. The retired gates
live at tag `v0.11.6`; their recorded data stays on disk under `.oopc/` and is
not read by `main` except through the one-time importer.

## Knowledge and provenance

Preserve stable WOP identities and read the wiki seed only. Canonical JSON-LD
records and their pinned source snapshot are authoring inputs; SQLite, RDF and
browser pages are derived projections. Never mark imported seed prose or
relationships as independently reviewed.

Reflection edits live only in the local overlay `.oopc/loop/ontology.json`,
each with its proposer and its reviewer's verdict and reason; they never change
the wiki seed or a graph release, and its curator can propose only from its
closed list of edits.

Every finding keeps who vouched for it. By the owner's default (2026-09-28), a
finding the researcher read directly in its cited source is **added** on the
researcher's judgement and labelled as such; by the owner's decision of
2026-10-14, one it read off a figure, converted or combined goes to a separate
reviewer first. The owner can require review of every finding. Only a
separate reviewer session that checked the finding against its cited open
source can mark it **reviewed**; keep that verdict and reason with it. Never
present an added finding as reviewed. Source access and permission to
redistribute are different things. Research workers cannot edit vocabulary,
review policy or code.

## Privacy and traces

Questions, traces, source excerpts, credentials and local paths stay in private
storage under `.oopc/` and never enter a public release. Record actual
tool-return payloads and explicit traversals; never infer a path between
successive searches. Browsing the app does not create agent trace events.

## Engines and failures

Codex and Claude Code are both subscription engines (`oopc/engines.py`). Use
whichever engines are signed in, within quota, and never gate work on one
engine. Every call either returns a valid response or fails with a named reason
(`timeout`, `crashed`, `rejected`, `invalid-output`, `interrupted`,
`not-signed-in`, `quota`, `rate-limited`). Transient failures retry once, then surface as
failed. There is no "unknown outcome" state. Tests never reach this machine's
engines: engine use is disabled under `unittest` unless
`OOPC_ALLOW_HOST_ENGINES=1`.

## Routing and checks

`docs/context-map.md` maps concerns to files; plans and debt are in
`docs/exec-plans/` (development records, not shipped). The researcher app
(`oopc/web/index.html`, `researcher.js`) shows what a researcher needs;
developer detail belongs on the unlinked `/operator.html` (`app.js`).

Run `python tools/run_tests.py --tier fast` after individual code changes and
`python tools/run_tests.py` before merging. Before pushing, run the suite from a
fresh clone, including once with no engines signed in
(`env -i HOME=<empty dir> PATH=/usr/bin:/bin`), as CI has none. CI minutes are
capped by a small budget, so batch pushes and release at most once a week;
never mark a push that carries code `[skip ci]` (it skips CI for every commit
in it). Publish to the public repository only with `tools/publish_public.py`:
one commit per version, never this repository's history. A failed release must
preserve the last validated release. Never reset the source wiki checkout.

## Several sessions at once

Several agent sessions often work on this repository together. Do code work in
a worktree of your own (`git worktree add`), not the shared checkout. Stage only
your own hunks, never a whole file someone else also edits. A plan under
`docs/exec-plans/active/` belongs to the session that runs it; another session
proposes changes to that session rather than editing the plan. Never move or remove
`.oopc/study/freeze` while a study runs from it, and check what other sessions
are running before starting engine-heavy work.
