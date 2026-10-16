# Claude Code subscription connection

Research can run on either of two subscription engines: ChatGPT (Codex,
`gpt-6.1-sol`) or Claude Code (`claude-opus-5-5`). Choose one under **Settings →
Research engine** in the researcher application; the choice applies to new
questions. Both engines get the same researcher instructions, the same
`search_knowledge` tool and the same answer format (`oopc/engines.py`), so their
answers, findings and traces are stored alike, each with the engine and model
that produced it.

## Sign-in

**Connect Claude Code** starts the official `claude auth login --claudeai` flow.
Finish signing in on claude.ai; a **Continue to sign-in** link appears if no
browser window opens. Only the Claude CLI handles credentials. OOPC reads the
sanitized `claude auth status` summary and accepts only a first-party Claude
subscription login; API-key, console or third-party-provider billing is refused
before any model call. Worker processes receive an environment with every
`ANTHROPIC_*`, `CLAUDE_CODE_*`, `CLAUDE_AGENT_*` and OpenAI/Codex variable
removed, so a host application's session is never borrowed.

The CLI is resolved, at each call, from `OOPC_CLAUDE_BINARY`, then `claude` on
`PATH`, then `~/.local/bin/claude` or `~/.claude/local/claude`, then the newest
CLI bundled with the Claude desktop app.

## Worker confinement

Each call is a fresh `claude -p` process with `--restricted`,
`--strict-mcp-config` (only the `oopc` knowledge tool, when the call has it),
`--setting-sources local` in an empty temporary directory,
`--no-session-persistence`, `--disable-slash-commands`, `--permission-mode
dontAsk`, and `--json-schema` for the answer format. Built-in tools are limited
to WebSearch and WebFetch when the call permits web access; shell, file and
agent tools are always denied. Observed tool use is recorded as for Codex.

CLAUDE.md memory is loaded per setting source, and `--restricted` withholds
even the `local` source's memory, so workers load no `CLAUDE.md`,
`CLAUDE.local.md` or user memory. A sentinel check on CLI 2.1.281
(2026-09-25) confirmed this for project and local memory; user memory follows
the `user` source, which workers never load.

## Quota

`/usage` in print mode reports the subscription's session and weekly windows
without a model call; the report is parsed from its text (tech debt CL-2), so a
wording change makes quota unknown. Unknown quota does not block work: a session
that hits a limit fails with reason `quota`. Background work keeps a reserve,
30% for Codex and none for Claude Code (owner, 2026-09-29); questions you ask
keep none.

## Reviews

A finding is reviewed in a fresh session of the engine that wrote the answer,
which can open the sources that engine read; a retry after a failure uses the
other engine (see [the core loop](core-loop.md)).
