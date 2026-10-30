# Context map

Where each concern lives, for orientation before a change. The loop itself is
described in [the core loop](core-loop.md); invariants are in [AGENTS.md](../AGENTS.md).

## The core loop

| Concern | Files |
| --- | --- |
| Questions: queue, the researcher prompt (the only one, in two parts: the answer, then its findings) and schema, retries, the background deposit turn and review | `oopc/ask.py` |
| Findings, notes, search, the review queue, the researcher's knowledge tools and the public knowledge snapshot | `oopc/knowledge.py` |
| The reviewer prompt, the review of an answer's findings, whole-answer checks and their measures | `oopc/reviewer.py` |
| Captured source text (fetched once after an answer) and Crossref metadata for DOIs | `oopc/sources.py` |
| Background loop (review, research queue), settings, launchd job | `oopc/loop.py` |
| Optional reflection (`oopc reflect`): replaying recorded searches for misses, the curator and reviewer sessions, the drop step, the ontology overlay and revert | `oopc/reflect.py` |
| Parity set, run on demand: plain session beside the researcher, canaries | `oopc/parity.py`, `benchmarks/parity.json` |
| Weekly summary and comparing two parity runs | `oopc/improve.py` |
| Ledger of engine calls and their usage | `oopc/calls.py` |
| One-time import from the retired 0.11 store | `oopc/legacy_import.py` |
| One-off store cleanups before a study freeze (`oopc upkeep`) | `oopc/upkeep.py` |

## Engines and sign-in

| Concern | Files |
| --- | --- |
| Running a Codex or Claude Code session, saving, resuming and deleting one, failure reasons, MCP hosting, quota, Claude sign-in | `oopc/engines.py` |
| Codex (ChatGPT) sign-in through the app server | `oopc/openai_account.py` |
| Live progress counts for a running question | `oopc/task_progress.py` |
| Docs | [claude-connection](claude-connection.md), [openai-connection](openai-connection.md) |

## Graph, releases and traces

| Concern | Files |
| --- | --- |
| Seed import, release build and verification | `oopc/seed.py`, `oopc/release.py`, `oopc/release_verification.py`, `oopc/validation.py`, `oopc/vocabulary.py`, `oopc/units.py` |
| Instrumented graph reader | `oopc/graph.py` |
| Trace store, replay export/import | `oopc/trace.py`, `oopc/otel.py` |
| MCP server for external agents | `oopc/mcp.py` |
| Docs | [model](model.md), [agents](agents.md) |

## Browser applications (`oopc/web/`)

| Surface | Files | Audience |
| --- | --- | --- |
| Researcher app (home, `/`): Ask, Polymers, Knowledge, History, Settings | `index.html`, `researcher.js`, `researcher.css` | Polymer researchers |
| About page (`/about.html`, linked from the top bar): an animated figure of the two loops (accumulation round the ring, expansion across the polymers), live counts and the status labels | `about.html`, `about.js`, `about.css` | Students and new researchers |
| Developer inspector (`/operator.html`, unlinked from the app): graph, ontology, task replay, loop health | `operator.html`, `app.js`, `style.css` | Maintainers |
| Bundled libraries | `vendor/cytoscape.*`, `vendor/openchemlib.*` | — |

The Mac app (a prototype) wraps the same server: the launcher
`packaging/macos/OOPC.swift` and its build, `tools/build_macos_app.py` (see
[installation](installation.md)).

`oopc/server.py` serves both on loopback only. Writes (asking, retrying, the
research queue, loop runs, sign-in, engine choice) need the same origin and the
per-server CSRF token. See [inspector](inspector.md).

## Tests

`tools/run_tests.py` runs one process per test file in parallel. The loop is
covered end to end with a scripted engine in `tests/test_core_loop.py`, the reflection in
`tests/test_reflect.py`; engine
sessions with fake binaries in `tests/test_engines.py`; the importer in
`tests/test_legacy_import.py`; browser helpers in `tests/*.test.cjs`
(`npm run check`). Tests never reach this machine's engines.

## Plans

Active and completed plans and the debt tracker are in `exec-plans/`
(development records, not shipped).

## Studies

`studies/macromolecules/` holds the code of the Macromolecules study: the
campaign, the self-improvement tests, the scaling and planted-findings runs and
the analyses behind the figures. Its outputs stay private under `.oopc/`; its
offline tests are separate from `tools/run_tests.py`
(`python -B -m unittest discover -s studies/macromolecules/tests`).
