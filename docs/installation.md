# Install, inspect, and connect an agent

The portable ZIP is the complete offline distribution: Python code, a verified
seed release, ontology definitions, local browser assets and the parity question
set. The Python wheel contains the
library, command-line program, schemas, browser assets, and licenses; it does
not contain a graph release, private questions or traces, or source PDFs.

## Use the portable ZIP

Install Python 3.9 or newer with SQLite FTS5, extract the ZIP, and open a terminal
in the extracted directory. No Python package installation or internet access is
needed for these commands:

```sh
python3 -m oopc verify
python3 -m oopc search polyethylene --type PolymerConcept --limit 5
python3 -m oopc inspect --open
```

On Windows, use `py -3` in place of `python3` if that is how Python was installed.
Open the printed local address. It opens the researcher application; the
developer inspector is at `/operator.html` on the same address. Asking questions
additionally needs a signed-in subscription engine, Codex or Claude Code (see
[OpenAI connection](openai-connection.md) and [Claude connection](claude-connection.md));
browsing does not. Keep that terminal running while using the
inspector. A different local port can be selected with `inspect --port 8768`.
The inspector binds to loopback, serves its own JavaScript, rejects foreign
browser origins, and exposes read operations. It does not publish graph changes
or append agent-access events when a person explores the graph.

The ZIP's `.sha256` sidecar checks the complete download.
`BUNDLE-MANIFEST.json` identifies every admitted member and its checksum;
`verify` checks the selected graph release's own immutable manifest.
Keep the extracted directory writable when recording tasks or importing replays.
Private operational files are created under its `.oopc` directory.

On Windows, keep that workspace under your own user profile with an access
control list (ACL) restricted to the intended users. The application does not
provision Windows ACLs: Python's `chmod` changes the read-only flag there, not
owner-only access. On POSIX hosts, private writes request owner-only permission
bits. Neither setting protects an intentionally shared or synchronized folder
from its other authorized users. [Python file-permission documentation](https://docs.python.org/3/library/os.html#os.chmod).

The distribution CI exercises Linux, macOS, and Windows. The current local
release check was run on macOS; adding Windows CI is not a claim that a Windows
run has already passed.

## Use the Mac app (prototype)

`OOPC-VERSION-arm64.dmg` holds an app for Apple Silicon Macs (macOS 11 or
later) that needs no Python or terminal. Drag **OOPC** to Applications and open
it; the researcher app opens in the default browser. Clicking the Dock icon
opens it again; quitting OOPC stops the server and any running question. The
app's menu also shows the data folder and the log.

The prototype is signed ad hoc, not by an Apple developer, so macOS blocks the
first open: open System Settings → Privacy & Security and choose **Open
Anyway** for OOPC. Questions, findings and traces are kept in
`~/Library/Application Support/OOPC` (the workspace: `releases/` and the
private `.oopc/`, with the app's log at `.oopc/app.log`); replacing the app
keeps them. A newer app copies its release there the first time it runs and
makes it the current one.

The app looks for Claude Code and Codex on the login shell's `PATH` (Finder
starts apps with a bare one), in `~/.local/bin`, Homebrew's folders and inside
the Claude, ChatGPT and Codex desktop apps. Sign in under Settings as usual.

To build it on a Mac with the Xcode command-line tools:

```sh
python3 tools/build_macos_app.py --release releases/RELEASE_ID   # -> build/macos/OOPC.app and the .dmg
```

The script downloads a pinned [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
Python and checks its digest, installs the package files the wheel ships into
it, copies and verifies one release, compiles `packaging/macos/OOPC.swift`, signs
everything ad hoc and makes a compressed disk image. The bundle is a real Python
interpreter rather than a frozen program because engine sessions start
`sys.executable` for the knowledge tools and the hourly loop job. Nothing under
`.oopc/` enters the bundle. Build locally: macOS CI runners cost ten times the
minutes. Distributing beyond a few testers needs a Developer ID signature and
notarization instead of the ad hoc one.

## Install the library or wheel

The package can also be installed into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /path/to/open_ontology_of_polymer_chemistry-VERSION-py3-none-any.whl
.venv/bin/oopc --root /path/to/extracted-portable-release verify
```

On Windows, virtual-environment programs are in `.venv\Scripts`. Installing the
wheel has no runtime dependencies. An offline wheel installation can add
`--no-index --no-deps`. Building a wheel from source requires the build tools
listed in `pyproject.toml`; use a prepared build environment or obtain those
build dependencies before going offline.

`--root` is the data/workspace directory and comes **before** the command. The
current working directory is used when it is omitted. Installing the library
does not select or download a graph automatically. From a source checkout,
create the pinned seed with `python3 -m oopc import-seed data/wiki-snapshot-v2.json`.
Use the prebuilt portable release when you want to avoid rebuilding it.

## Connect your own agent

Python agents can import `Graph` and `TraceStore`, as shown in
[the agent guide](agents.md). Any agent can use the same operations through the
CLI or dependency-free MCP stdio server. Configure your MCP client to launch:

```text
command: /absolute/path/to/python
arguments: -m oopc --root /absolute/path/to/extracted-portable-release mcp
```

The interpreter must have the installed package, or the process working
directory must be the extracted distribution. Add `--run RUN_ID --agent NAME`
after `mcp` to join a run created by your adapter. Search and assertion
results expose pagination; keep increasing `offset` by the returned `limit`
while `truncated` is true. An offset is not limited to the first 500 records.
Traversal expansion is deliberately bounded and returns explicit paths.

MCP records actual graph access. It does not claim that the client delivered a
payload to a model. Your adapter can confirm delivery using the Python or CLI
recording hooks. Attach final claims and their citations, then finish the run
through those hooks. A graph return, citation, and source-supported claim have
different meanings; the inspector preserves those distinctions.

## Inspect a replay without its original graph

Import an explicitly shared replay into a writable directory and open its local
inspector. An installed wheel can be launched from any directory:

```sh
oopc --root /path/to/replay-workspace import-replay /path/to/task-replay.zip
oopc --root /path/to/replay-workspace inspect --replay-only --open
```

The replay includes the accessed graph subset, pinned vocabulary, exact returned
payloads, and event history. The replay-only view does not need the full original
release. Omitted source content and unobserved agent accesses remain visible
gaps. Import validates checksums and event relationships before storing the run.
Replay bundles may contain private task text and are separate from public graph
releases.

## Asking questions and the loop

Offline reading and inspection need no account or model. Asking questions uses
your own signed-in ChatGPT (Codex) or Claude Code subscription; the answers,
findings, reviews and traces stay under `.oopc/` in the workspace. The
background loop runs only when you start it from the Knowledge page, with
`oopc loop tick`, or after `oopc loop install` (hourly, macOS launchd). See
[the core loop](core-loop.md).

## Build a reviewed distribution

Maintainers register every public ZIP input in `config/public-files.json`.
Adding a new file under a project directory does not automatically publish it.
The packager rejects symlinked members and unsafe paths, verifies the selected
release first, and replaces a prior download only after building a complete ZIP.
Run `python3 tools/package_release.py` from a checkout with a verified current
release. Python wheels and source distributions intentionally omit the data and
private operational state; distribute the portable ZIP for the complete seed.
