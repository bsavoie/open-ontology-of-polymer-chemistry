# Open Ontology of Polymer Chemistry

A polymer knowledge base that gets better as you use it. You ask a question; a
research agent answers from the findings earlier questions saved first and from
open sources for the rest, citing every reported fact and labelling its own
reasoning. What it reads is saved as source-qualified findings, filed under the
polymer the ontology names; a separate reviewer checks the values it read off a
figure, converted or combined, and a sample of the rest, against their sources. Saved findings, marked Reviewed,
Added or Needs checking, are what the next question reads first.

The ontology's value is **provenance** (every reported fact traceable to a
saved finding with its review status, or to a source) and **cumulative
knowledge** (answers draw more on saved findings over time). It is not trying
to beat a plain Claude Code or Codex session today; matching one is a guardrail.

The seed preserves **274 polymer identities**, **245 canonical V3000 structures**
and **27,559 records** from the Wiki of Open Polymer Data. Imported assertions
keep **seed** status: importing source-backed drafts is not a review.

This is **Open Ontology of Polymer Chemistry** (`oopc`), separate from the
reaction ontology and the Wiki of Open Polymer Data.

## The loop

1. **Ask** in the app. The researcher searches saved findings first and uses
   the web for gaps.
2. **Answer** with a citation for every reported fact; the researcher's own
   reasoning and textbook background are labelled as such.
3. **Save** the facts it read with their source, locator and excerpt: added on
   its judgement when read in the text or a table, sent for review when read off
   a figure, converted or combined.
4. **Review**: after the answer, one reviewer call checks the findings waiting
   for review and a sample of the added ones against their sources.
5. **Reuse**: later questions find the most relevant saved findings first.

See [the core loop](docs/core-loop.md) for how each step works and what it
records, and the [tester guide](docs/tester-guide.md) for a walk-through.

## Start locally

Requires git and Python 3.9 or later with SQLite FTS5; the reader and app have
no Python packages to install. Asking questions also needs a ChatGPT (Codex) or
Claude Code subscription, signed in through its own app or command-line tool
([Codex](docs/openai-connection.md), [Claude Code](docs/claude-connection.md)).

```sh
git clone https://github.com/bsavoie/open-ontology-of-polymer-chemistry.git
cd open-ontology-of-polymer-chemistry
python3 -m oopc import-seed data/wiki-snapshot-v2.json   # once: builds the seed release in releases/
python3 -m oopc inspect --open
```

Keep the terminal running. The app opens at `http://127.0.0.1:8765`: **Ask**,
**Polymers**, **Knowledge** and **History**, with engine sign-in under
Settings. To type `oopc` in place of `python3 -m oopc`, install the clone into
a virtual environment and run it from the clone (or set `OOPC_ROOT` to it):

```sh
python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install .
oopc inspect --open
```

The portable ZIP, the wheel and the Mac app prototype are described in
[installation](docs/installation.md). The same loop runs from the command line:

```sh
python3 -m oopc ask "How does annealing temperature affect the crystallinity of PLA films?"
python3 -m oopc loop tick          # review waiting answers, then one queued research question
python3 -m oopc knowledge          # counts by review status
python3 -m oopc research "A gap worth researching later"
python3 -m oopc parity run --engine codex   # on demand: compare with a plain session on the fixed set
python3 -m oopc parity compare RUN_A RUN_B  # two runs side by side, e.g. before and after a prompt change
python3 -m oopc improve summary    # the week in numbers
python3 -m oopc loop install       # optional: run the loop hourly (macOS launchd)
```

Everything you ask, the answers, findings and traces stay under `.oopc/` on
this computer and never enter a public graph release. A knowledge snapshot you
export carries findings and source notes, with no questions, traces or excerpts:

```sh
python3 -m oopc knowledge --export snapshot/   # findings, source notes, manifest named by a content hash
python3 -m oopc knowledge --import snapshot/   # start an empty workspace from a snapshot
```

## Connect your own agent

Use the Python library, CLI or the dependency-free MCP server. They share the
same instrumented graph-access layer.

```python
from oopc.graph import Graph
from oopc.trace import TraceStore
from oopc.util import resolve_release

release = resolve_release(".")
run = TraceStore(".").create(release, "My polymer research task")
graph = Graph(release, trace=run, agent_id="my-agent")
results = graph.search("polyethylene", type="PolymerConcept", limit=5)
paths = graph.traverse("wop-000001", predicate="narrower", direction="out")
run.artifact({"title": "Answer", "claims": [{
    "id": "answer-1", "text": "Polyethylene's seed record was retrieved.",
    "citations": ["wop-000001"]
}]}, agent_id="my-agent")
run.finish()
```

Start MCP with `python3 -m oopc mcp`. See [the agent integration guide](docs/agents.md)
and [the runnable example](examples/reader_agent.py). **Returned**,
**traversed**, **cited** and **reviewed** are separate observations; browsing
the app never becomes an agent trajectory.

## Replay and share

```sh
python3 -m oopc run-list
python3 -m oopc export-replay RUN_ID task-replay.zip
python3 -m oopc import-replay task-replay.zip
python3 -m oopc export-otel RUN_ID spans.json
```

A replay carries its pinned vocabulary, observed records, exact payloads, event
sequence, artifacts and checksums, and works without the original release. The
developer inspector at `/operator.html` replays any run. Inspect task text and
third-party content rights before sharing a replay.

## Data and interoperability

`config/seed-lock.json` pins the exact wiki v2 source bytes. The adapter is
one-way and preserves WOP identities, article-local evidence, classification
axes, section text, routes and V3000 data. Each content-addressed release
contains canonical JSON-LD records, a small vocabulary and context, JSON schemas,
SHACL shapes, SQLite/FTS5, RDF N-Triples and generated Markdown; SQLite and
Markdown are projections, not authoring inputs. See [the model contract](docs/model.md).

## Development

```sh
python3 tools/run_tests.py            # parallel; --tier fast for a quick check
npm run check                         # browser assets
python3 -m oopc verify
```

Tests never reach this machine's engines. Node is only needed to maintain and
test browser assets. The milestone evaluation machinery of 0.11 (reviewer
qualification panels, calibrations, tranches, audits) was retired; it remains
at tag `v0.11.6`, and its recorded data stays on disk.

Code: **Apache-2.0**. Original structured data: **CC0-1.0**. Original prose and
diagrams: **CC BY 4.0**. Imported wiki content retains its attribution, and linked
publications retain their own rights. See [NOTICE](NOTICE), [LICENSE](LICENSE),
[LICENSE-DATA](LICENSE-DATA) and [LICENSE-CONTENT](LICENSE-CONTENT).
