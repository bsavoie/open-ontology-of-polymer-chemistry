# Inspecting the ontology, evidence graph, and task trajectories

The inspector is a local browser application distributed with the Python package. Start it with `oopc inspect` and open the printed localhost URL. JavaScript, CSS, Cytoscape.js and OpenChemLib are bundled; exploring a release needs no internet connection, model, account, or graph server.

The printed URL opens the **researcher application**, which presents only what a polymer researcher needs. The full **developer inspector** (graph layers, ontology definitions, task replay and instrumentation) is served at `/operator.html`. The researcher application does not link to it.

## Researcher application

- **Ask** runs a question through the engine selected under **Settings**, ChatGPT (Codex) or Claude Code. While it runs, the page shows live activity: knowledge lookups, web searches, pages read and sites, the latest action and elapsed time. The answer page shows the answer with numbered citations, one plain provenance status (findings waiting for review, reviewed with their counts, or nothing new to review), the cited sources, **What this answer added** (each saved finding with its review status and the reviewer's reason), **Worth researching later** (open questions that can be added to the research queue) and how the answer was found, including reviewed findings reused and tokens. Missing counts are omitted, never shown as zero. A failed question states its reason and can be retried.
- **Polymers** lists every polymer concept. A polymer page shows its drawn structure, its sections in recorded order with numbered sources, synthesis routes, **Findings from questions** about that polymer with their review status, related polymers and the full source list. Imported seed records read *Imported draft · not yet independently reviewed*. Structures are drawn from the canonical V3000 molfile; repeat-unit brackets are placed only when the drawn atoms match the molfile coordinates.
- **Knowledge** shows the loop in numbers (answered, saved, reviewed, reused), a **Run the loop now** action, every finding filtered as Reviewed, Added, Needs checking or Rejected with the reviewer's reason, and the research queue. See [the core loop](core-loop.md).
- **History** lists your questions, including earlier ones imported from 0.11.

Browsing performs read-only requests and creates no agent trace events.

# Developer inspector (`/operator.html`)

**Loop health** (top right) shows the latest parity run (run on demand with `oopc parity run`) beside the plain session, and this week's numbers: answers, reuse, answers needing no web, tokens, reviews waiting or given up, same-engine reviews, the rejected share of sampled added findings, and the checking share of tokens. Below them is the optional ontology reflection (`oopc reflect`): whether it is scheduled, each edit in force with who proposed and approved it and the misses it fixed and results it lost in the replay, and recent runs.

## Knowledge graph

Search for a material, document, concept, or assertion. The left column holds results and filters, the center shows a bounded graph neighborhood, and the right column preserves the selected record's evidence and scientific context.

- Select a node or directed relationship to inspect its canonical record.
- Double-click a node, or choose **Expand neighborhood**, to add its adjacent records.
- Use **Table** for keyboard-accessible records and relationships. Multiple assertions retain separate rows and identities.
- Filter by type, evidence status, relationship, layer, property, process, application, environment, or source. An empty result remains empty; no substitute connections are inferred.
- Use **View definition** to inspect the ontology term behind a record or assertion.
- Open the release label to inspect the pinned seed checksum and compare available releases. Comparisons never change either release.

Source links open external websites only when deliberately selected. These links are separate from the offline interface.

## Ontology

The ontology view lists entity classes and relationship definitions. Each definition exposes its status, allowed subject/object types, required contextual qualifiers, examples, counterexamples, mappings, and available history. **View instances** applies that definition as a graph search filter. The graph representation uses only explicitly declared domain/range relationships.

## Task replay

Select a recorded run in **Task replay**. The timeline contains a separate lane for each agent. Select an event, step backward/forward, drag the scrubber, or play at the selected speed. **Follow live** checks events and run metadata once per second while the page is visible, so completion appears even when it adds no access event. Pausing the viewer never pauses or changes the task.

**Cumulative access** shows records returned through the selected event. Uncheck it to inspect just that event. A cumulative graph does not claim that every earlier payload remains in the model's current context. **Proposed changes** overlays candidates without altering the pinned graph release.

The evidence panel includes the original request, filters, graph/index versions, result identifiers, explicit traversals, pagination/truncation status, and captured payload. A missing payload or incomplete adapter capability is explicitly labeled. **Task & deliverables** exposes the task specification, artifacts, citations, review findings, and proposed changes. Citation buttons jump to the associated evidence and access event when one was recorded.

The distinctions are deliberate:

| Observation | Meaning |
| --- | --- |
| Returned | An operation returned a record. |
| Delivery confirmed | An adapter confirmed delivery into a model request. |
| Traversed | An operation explicitly followed identified graph edges. |
| Cited | A deliverable referenced evidence. |
| Reviewer-supported | A review recorded support for a claim. |
| Reuse-tested | A later evaluation tested task-specific reuse. |

Independent searches can leave disconnected regions. Repeated access remains in the event history. An edge returned by search is not styled as traversed unless an explicit traversal is recorded. Graph browsing and replay only issue read requests and never create agent trace events.

## Execution, evaluation and useful evidence

The run list and task panel report execution state separately from task review.
A completed run can have a failed or unscorable evaluation. Passing individual
claim findings do not establish that the answer completed the task. An unscorable
reviewer's reported verdict is shown as unqualified, not as a passing task score.

The task panel counts relationships returned, relationships explicitly traversed,
and recipes actually returned, delivered or cited. Calling a run `graph-memory`
does not establish recipe use. Older traces without experiment metadata show that
gap; the inspector does not infer current baseline membership from titles or dates.

A node-only view means no relationship records are present in the selected view.
Its records can still support an answer. Use citations, exact payloads and review
findings to assess their usefulness. Separate searches can return disconnected
evidence, and a returned relationship need not have been traversed. Partial record
fragments have their own identifiers and visible incomplete-content notices.

New publication-ingestion tasks have a separate **Assigned publication** outcome.
The coordinator records whether the exact paper was inspected with accepted
additions, inspected with no additions justified, or left unavailable/incomplete.
Its frozen specification is visible alongside the raw reviewer findings. An
individual claim may pass even when inspection of the assigned paper is incomplete.
An accepted addition is still a private candidate until publication gates pass.

The inspection receipt is a separate coordinator artifact. Its source references
do not create new access, delivery, traversal, citation or support events. Replay
preserves the receipt and original review independently. Older tasks receive no
retrospective completion credit; a missing receipt stays visibly missing. These
are isolated-agent inspection findings, not expert validation or proof of later
task improvement.

## Accessibility and local behavior

All record and relationship actions have a table alternative. Use `/` to focus search and Escape to close dialogs. Light and dark theme preferences are stored locally. The interface reflows for narrow screens; supporting evidence remains available below the graph. Reduced-motion preferences are respected by avoiding animated graph layouts.

Task traces stay in local run storage and are not automatically included in public ontology releases. Replay bundles must be explicitly exported through the project tooling. Capture gaps remain visible in the exported replay.

If a writer exits after committing an event but before updating its JSONL journal or run metadata, the reader derives counters, agent identities, and delivery capabilities from the committed SQLite events. Export reconstructs the complete journal from those same events without changing their identifiers or payloads. Task completion is never inferred from inactivity.

## Maintaining the bundled assets

End users do not need Node.js. Maintainers can reproduce the bundled graph dependency with:

```sh
npm ci --ignore-scripts
npm run vendor
npm run check
```

Cytoscape.js is pinned to 3.34.3 and OpenChemLib JS to 9.25.0. Their MIT and BSD 3-Clause licenses are included beside the bundles in `oopc/web/vendor/`. OpenChemLib is loaded only when a structure is drawn. The client accepts only HTTP(S) external links, escapes record content before inserting it into markup, and renders artifacts as text rather than executing embedded HTML.

## Dense neighborhoods and assertions as entities

Each expansion requests at most 150 relationships. **More connections** shows
the loaded count and total for each unfinished neighborhood; choose a record
and **Load next 150** to continue in either graph or table view. Changing filters
starts a new view. Parallel assertions retain separate identifiers and qualifiers.
Inspector pagination does not change agent traversal or append access events.

An assertion can itself be the subject of a provenance or memory relationship.
In that case the inspector shows its record as an assertion node as well as its
directed assertion edge. Both open the same canonical record. No scientific
connection between the two visual representations is invented.

Imported replays preserve the recorded outcome. A snapshot of an active run is
a checkpoint with no live worker attached. Older imports that lost their outcome
show that uncertainty. Live follow is disabled for all imported snapshots;
stepping, scrubbing, citations and exact recorded payloads remain available.
