# Open Ontology of Polymer Chemistry

A polymer knowledge base that gets better as you use it. You ask a question; a
research agent answers from the findings earlier questions saved first and from
open sources for the rest, citing every reported fact and labelling its own
reasoning. What it reads is saved as source-qualified findings, filed under the
polymer the ontology names; a separate reviewer checks the values it read off a
figure, converted or combined, and a sample of the rest, against their sources.
That review also compares new findings with related saved ones and records
conflicts. Saved findings, marked Reviewed, Added or Needs checking, are what
the next question reads first. Optional reflection uses recorded searches to
improve how those findings are found.

The ontology's value is **provenance** (every reported fact traceable to a
saved finding with its review status, or to a source) and **cumulative
knowledge** (answers draw more on saved findings over time). It is not trying
to beat a plain Claude Code or Codex session today; matching one is a guardrail.

The seed preserves **274 polymer identities**, **245 canonical V3000 structures**
and **27,559 records** from a pinned snapshot of the
[Wiki of Open Polymer Data](https://github.com/bsavoie/wiki-of-open-polymer-data),
available as a [browsable wiki](https://bsavoie.github.io/wiki-of-open-polymer-data/)
and a public Git repository. Imported assertions keep **seed** status:
importing source-backed drafts is not a review.

This is **Open Ontology of Polymer Chemistry** (`oopc`), separate from the
reaction ontology and the Wiki of Open Polymer Data.

## The loop

1. **Ask** in the app. The researcher searches saved findings first and uses
   the web for gaps. A question outside the workspace's scope (a setting;
   polymer science by default) but connected to it is answered without saving
   its findings by default; one with no connection to it is not researched,
   and its page links to another assistant.
2. **Answer** with a citation for every reported fact; the researcher's own
   reasoning and textbook background are labelled as such.
3. **Save** in a background turn, after the answer is shown: the facts it read
   with their source, locator and excerpt, plus source notes. Findings read in
   the text or a table are added on its judgement; figure readings, conversions
   and combined values wait for review.
4. **Review**: a separate reviewer session checks the findings waiting for
   review and a sample of the added ones against their sources, and compares
   new findings with related saved ones. Conflicts keep the reviewer's reading
   and reason; by default the reviewer settles them.
5. **Reuse**: later questions find the most relevant saved findings first.
6. **Reflect** (optional, off by default): replay recorded searches and review
   changes to names, polymer ids, property terms and links that help find what
   those searches missed.
7. **Measure** on demand: compare quality and token use with a plain session
   on a small fixed parity set.

See [the core loop](docs/core-loop.md) for how each step works and what it
records, and the [tester guide](docs/tester-guide.md) for a walk-through.

## Review and conflicts

By default, a fresh reviewer session checks all findings waiting for review
and **one in five Added findings**. The owner can change the spot-check rate
or require every finding to be reviewed before use in Settings. The reviewer
checks the cited sources, using captured source passages when available, and
keeps a verdict and reason for each finding it checks. The answer is already
available while saving and review run in the background.

| Status | What it means |
| --- | --- |
| **Added** | Read directly in a source and saved on the researcher's judgement. |
| **Reviewed** | A separate reviewer checked it against its source and found it supported. |
| **Needs checking** | Waiting for review, or a review could not confirm it; a lead for further research. |
| **Rejected** | Judged unsupported; hidden from searches and retained with the reason. |

The same session compares each new finding with a small selection of related
saved findings: up to **eight per new finding** by default, chosen by polymer,
property, source and possible disagreement. It considers differences in grade,
specimen, processing and test conditions before calling values inconsistent,
and opens both sources for apparent conflicts. If nothing needs a source check,
a review runs only when the comparison screen detects a possible conflict.
The comparison depth can be changed or turned off in Settings.

Each conflict records both findings, the reviewer's reading and reason, and who
settled it. By default, the reviewer can reject a misread finding or return a
previously Reviewed one to Needs checking; unresolved conflicts stay open.
When both readings are supported but their sources disagree, both stay
available and linked so later answers can report them together. The owner can
choose **I settle conflicts** to leave settlement to a person in the Knowledge
tab or through `oopc conflicts`.

## Optional reflection

Reflection is **off by default**. It replays recorded knowledge searches to
find missed findings, unknown polymer names and property types repeatedly used
together. A curator proposes changes from four allowed kinds: names for
existing polymers, polymer ids for findings, property terms and links between
property terms. A separate reviewer checks each proposal against its sources.

Approved edits are tried on a private copy of the store by replaying past
searches. An edit is dropped if it loses more cited results than the number of
misses it fixes; a link must recover a missed connection between findings used
together.
The remaining edits take effect through the local overlay
`.oopc/loop/ontology.json`, which records their proposer, reviewer verdict,
reason and measured effect. They can be reverted. The wiki seed and graph
releases stay pinned.

The Macromolecules study's reflection run improved lookup recall from 0.90 to
0.92, with no measurable improvement in answers. See
[the reflection design](docs/core-loop.md#reflection-optional) for the procedure
and its limits.

```sh
python3 -m oopc reflect run --dry-run  # inspect search misses without engine calls
python3 -m oopc reflect run            # curate, review and apply once using your subscription
python3 -m oopc reflect status         # edits in force and recent runs
python3 -m oopc reflect revert EDIT_ID # undo an edit
```

`oopc reflect schedule 7` makes reflection due every seven days when the
background loop ticks; `oopc reflect schedule 0` turns it off. Run ticks with
`oopc loop tick`, or install the hourly macOS job with `oopc loop install`.

## Start locally

Requires git and Python 3.9 or later with SQLite FTS5; the reader and app have
no Python packages to install. Asking questions also needs a ChatGPT (Codex) or
Claude Code subscription, signed in through its own app or command-line tool
([Codex](docs/openai-connection.md), [Claude Code](docs/claude-connection.md)).

On a Mac, git and Python come with Apple's Command Line Tools: macOS offers to
install them the first time you run `git`, or run `xcode-select --install`.

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

On an Apple Silicon Mac, the OOPC app (a prototype) runs the same app with no
terminal: download `OOPC-VERSION-arm64.dmg` from the
[latest release](https://github.com/bsavoie/open-ontology-of-polymer-chemistry/releases/latest)
and drag OOPC to Applications. It is not signed by Apple, so allow it once
under System Settings → Privacy & Security → Open Anyway
([the Mac app](docs/installation.md#use-the-mac-app-prototype)). The portable
ZIP and the wheel are also described in [installation](docs/installation.md).
The same loop runs from the command line:

```sh
python3 -m oopc ask "How does annealing temperature affect the crystallinity of PLA films?"
python3 -m oopc loop tick          # review, research if enabled, reflect if due
python3 -m oopc knowledge          # counts by review status
python3 -m oopc conflicts          # open conflicts and the reviewer's reading
python3 -m oopc research "A gap worth researching later"
python3 -m oopc scope              # what the researcher answers; `oopc scope "TEXT" --redirect URL --save-outside no` changes it
python3 -m oopc parity run --engine codex   # on demand: compare with a plain session on the fixed set
python3 -m oopc parity compare RUN_A RUN_B  # two runs side by side, e.g. before and after a prompt change
python3 -m oopc improve summary    # the week in numbers
python3 -m oopc loop install       # optional: run the loop hourly (macOS launchd)
python3 -m oopc reflect schedule 7 # optional: reflect every 7 days through loop ticks (0 = off)
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

The wiki's [public repository](https://github.com/bsavoie/wiki-of-open-polymer-data)
is the upstream source; this repository bundles the v2 snapshot used to build
its seed. [`config/seed-lock.json`](config/seed-lock.json) pins those exact source
bytes by SHA-256. Updating the seed is an explicit migration; upstream wiki
changes and local reflection edits do not update it automatically. The adapter
is one-way and preserves WOP identities, article-local evidence, classification
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
