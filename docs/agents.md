# Agent integration and trace contract

Start a run with `TraceStore(root).create(release, title, capabilities, task)`.
Bind all graph readers to it: `Graph(release, trace=run, agent_id="worker-a")`.
The run rejects a reader bound to another graph release. Concurrent workers
share the same run with distinct agent IDs; the append-only sequence is serialized
under a file lock and indexed locally in SQLite.

Operations are `describe`, `search`, `get`, `claims`, `evidence`, `traverse`, and
`recipes`. Every call records its arguments, outcome, duration, agent, sequence,
release/index versions, ordered record IDs and exact payload checksum. Only
`traverse` records followed edges and direction. Failed operations and repeated
access remain separate events. Literal text search is parameterized.

Relationship filters require exact IDs declared by the run's pinned vocabulary.
Inspect `describe_vocabulary` (Python: `graph.describe()`) before choosing a
predicate. For example, `hasProcess` is declared in the seed vocabulary;
`hasSynthesisRoute` is not an alias. Unknown names produce a failed access event
with no returned records or traversed edges. A declared relationship with no
matching assertions still returns a successful empty result. Omit the filter
to retrieve any eligible relationship.

All returned dictionaries from an instrumented reader include `_access.run_id`
and `_access.event_id`. After an adapter actually passes a payload to a model
request, it may record:

```python
run.delivery(results["_access"]["event_id"],
             [r["@id"] for r in results["records"]],
             model_call_id="request-123", representation="content",
             agent_id="worker-a")
```

Use `representation="summary"` or `"reference"` when that is what was delivered.
A confirmation cannot invent IDs absent from the access event. The recorder
does not claim to observe a model's attention or hidden reasoning. An adapter
should report its own capabilities truthfully; direct SQLite, file and web
access remains unobserved unless separately integrated.

Final artifacts use claim-level citations:

```json
{
  "title": "Evidence assessment",
  "answer": "A concise source-qualified answer.",
  "claims": [{
    "id": "answer-1",
    "text": "A particular claim at the documented scope.",
    "citations": ["evidence:wop-000001:source-id"]
  }]
}
```

Use actual returned identifiers. The inspector links a claim to evidence and
the associated access events. It shows unobserved citations as gaps, preserving
the difference between citation and support. Independent reviews use
`run.artifact(..., kind="review")` with `findings` containing `claimId`, `verdict`
and `citations`. Reuse labels require measured evaluation receipts. Final artifacts
cannot silently add records to the observed evidence graph.

## MCP and CLI

MCP runs over line-delimited JSON-RPC on standard input/output. It implements
`initialize`, `ping`, `tools/list` and `tools/call`. Supported protocol profile:
2025-06-18. Logs never go to standard output.

```json
{
  "mcpServers": {
    "polymer-ontology": {
      "command": "python3",
      "args": ["-m", "oopc", "--root", "/path/to/companion", "mcp"],
      "env": {"PYTHONPATH": "/path/to/companion"}
    }
  }
}
```

The tools are `describe_vocabulary`, `search`, `get_record`, `get_claims`,
`get_evidence`, `traverse` and `attach_artifact`. None of them can change the
graph. Run lifecycle, confirmed delivery, final artifacts and replay export are
also available through CLI commands. The app's own researcher uses only
`search_knowledge` over saved findings, with the graph's
polymer names behind its search (see [the core loop](core-loop.md)).

## Local storage and sharing

`.oopc/runs/RUN_ID/` contains run metadata, immutable vocabulary, JSONL events,
SQLite indexes and content-addressed payloads. The SQLite transaction is the
durable event index; the JSONL journal is repaired from it after an interrupted
append. Private operational files are excluded from public graph releases.

Replay bundles validate checksums, paths, event sequence, record identities,
payload consistency and release identity before atomic import. Imported replay
is immutable. The graph at event N includes only records observed by that point;
later retrievals or publication cannot rewrite history. Human exploration uses
an uninstrumented reader.

The optional `export-otel` command writes an OTLP JSON span projection with stable
trace/span links. It excludes query and evidence bodies from span attributes and
does not transmit anything. Exact evidence remains in the local replay payloads.
