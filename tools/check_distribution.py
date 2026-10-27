"""Test a built wheel and sdist from an empty, offline temporary workspace.

Used by CI on Linux, macOS, and Windows. It never launches model workers.
"""
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ASSETS = {"web/index.html", "web/researcher.js", "web/researcher.css", "web/operator.html", "web/app.js", "web/style.css",
          "web/vendor/cytoscape.min.js", "web/vendor/cytoscape.LICENSE", "web/vendor/openchemlib.js", "web/vendor/openchemlib.LICENSE",
          "web/vendor/InterVariable.woff2", "web/vendor/InterVariable-Italic.woff2", "web/vendor/inter.LICENSE",
          "web/about.html", "web/about.css", "web/about.js"}
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + number for prefix in ("COM", "LPT") for number in "123456789¹²³"}


def allowed_runtime(path):
    return path in ASSETS or (path.startswith("schema/") and path.endswith(".json")) or ("/" not in path and path.endswith(".py"))


def archive_parts(name):
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith("/") or ".." in parts
            or any(character in name for character in '\\:<>"|?*')
            or any(ord(character) < 32 for character in name)
            or any(part.endswith((" ", ".")) or part.startswith(" ")
                   or part.split(".", 1)[0].upper() in WINDOWS_DEVICES for part in parts)):
        # Reject Win32 aliases even when validating on POSIX. Naming rules:
        # https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
        raise ValueError("Unsafe distribution member")
    return parts


def check_archives(directory):
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        for name in names:
            parts = archive_parts(name)
            if parts[0] == "oopc":
                if not allowed_runtime("/".join(parts[1:])):
                    raise ValueError("Unexpected wheel runtime member: " + name)
            elif not parts[0].endswith(".dist-info"):
                raise ValueError("Unexpected wheel member: " + name)
        for asset in ASSETS:
            if "oopc/"+asset not in names:
                raise ValueError("Missing bundled asset: " + asset)
        for license in ("LICENSE", "LICENSE-DATA", "LICENSE-CONTENT", "NOTICE"):
            if not any(name.endswith("/"+license) for name in names):
                raise ValueError("Missing distribution license: " + license)
    with tarfile.open(sources[0]) as archive:
        for member in archive.getmembers():
            parts = archive_parts(member.name)
            if not member.isfile():
                if not member.isdir():
                    raise ValueError("Source distribution cannot contain links")
                continue
            if len(parts) < 2:
                raise ValueError("Unsafe source member")
            relative = "/".join(parts[1:])
            if parts[1] == "oopc":
                if not allowed_runtime("/".join(parts[2:])):
                    raise ValueError("Unexpected source runtime member: " + relative)
            elif len(parts) == 2:
                if parts[1] not in {"README.md", "NOTICE", "LICENSE", "LICENSE-DATA", "LICENSE-CONTENT", "pyproject.toml", "CHANGELOG.md", "MANIFEST.in", "PKG-INFO", "setup.cfg"}:
                    raise ValueError("Unexpected source root member: " + relative)
            elif not parts[1].endswith(".egg-info"):
                raise ValueError("Source distribution contains non-code project folder: " + relative)
    return wheels[0], sources[0]


SMOKE = r'''
import json, threading
from pathlib import Path
from urllib.request import urlopen
import oopc
from oopc.graph import Graph
from oopc.mcp import MCP
from oopc.release import build_release, verify_release
from oopc.server import make_server
from oopc.trace import TraceStore, import_replay
from oopc.util import atomic_json
from oopc.vocabulary import get_ontology
root = Path.cwd()/"workspace"
release = build_release(root/"releases/fixture", [{"@id":"wop-000001", "@type":"PolymerConcept", "label":"Offline α polymer fixture", "status":"seed", "layer":"science"}], get_ontology(), {})
atomic_json(root/"releases/current.json", {"release_id":"fixture"})
assert "site-packages" in str(Path(oopc.__file__).resolve())
assert verify_release(release)["record_count"] == 1
mcp = MCP(root, release)
response = mcp.handle({"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":"search", "arguments":{"q":"polymer"}}})
assert not response["result"]["isError"]
assert len(response["result"]["structuredContent"]["records"]) == 1
invalid = mcp.handle({"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":"traverse", "arguments":{"start":"wop-000001", "predicate":"hasSynthesisRoute"}}})
assert invalid["result"]["isError"]
assert "describe_vocabulary" in invalid["result"]["content"][0]["text"]
failed = mcp.run.events()["events"][-1]
assert failed["status"] == "error" and failed["result_ids"] == [] and failed["paths"] == []
assert mcp.call("traverse", {"start":"wop-000001", "predicate":"hasProcess"})["paths"] == []
mcp.run.finish()
bundle = root/"replay.zip"
mcp.run.export(bundle)
replay_root = Path.cwd()/"replay-only"
result = import_replay(bundle, TraceStore(replay_root))
replay = TraceStore(replay_root).run(result["run_id"])
assert replay.events() == mcp.run.events()
# Exercise the core loop from the installed package without any model call:
# save findings (with a repeat), search them, and read settings and the queue.
from oopc import knowledge, loop
from oopc.ask import ANSWER_SCHEMA, DEPTHS, Questions
from oopc.engines import REASONS, classify_failure
assert set(DEPTHS) == {"quick", "standard", "thorough"} and "findings" in ANSWER_SCHEMA["properties"]
assert "quota" in REASONS and classify_failure(1, "", "You've hit your usage limit") == "quota"
finding = {"statement":"Offline α polymer reached 45% crystallinity.", "material":"α polymer film", "property":"crystallinity",
           "value":"45", "unit":"%", "conditions":"DSC, second heating", "subject":"wop-000001", "sourceTitle":"Fixture",
           "sourceUrl":"https://example.org/fixture", "sourceDoi":"", "locator":"Table 1", "excerpt":"45%",
           "needsReview":False, "reviewFlag":""}
saved = knowledge.deposit(root, "a"*32, {"findings":[finding, dict(finding)], "sources":[]}, engine="codex", spot_check_rate=0)
assert (saved["findings"], saved["duplicates"], saved["counts"]) == (1, 1, {"accepted": 1}), saved
assert [f["status"] for f in knowledge.search(root, "α crystallinity", compact=True)["added"]] == ["accepted"]
assert loop.settings(root) == loop.DEFAULT_SETTINGS and loop.settings(root)["researchPerWeek"] == 0
assert loop.add_research(root, "An offline research question about α polymers")["status"] == "waiting"
assert loop.status(root)["knowledge"]["findings"] == {"accepted": 1}
assert Questions(root).list()["tasks"] == []
for selected_root, selected_release in ((root, release), (replay_root, None)):
    server = make_server(selected_root, selected_release, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = "http://127.0.0.1:"+str(server.server_port)
        for path in ("/", "/researcher.js", "/researcher.css", "/operator.html", "/app.js",
                     "/vendor/cytoscape.min.js", "/vendor/openchemlib.js", "/api/runs", "/api/tasks/status", "/api/tasks",
                     "/api/knowledge", "/api/loop", "/api/settings"):
            with urlopen(base+path, timeout=5) as response:
                assert response.status == 200 and response.read()
        with urlopen(base+"/api/meta", timeout=5) as response:
            assert json.load(response)["replayOnly"] == (selected_release is None)
    finally:
        server.shutdown(); server.server_close(); worker.join()
print(json.dumps({"installed":str(Path(oopc.__file__).resolve()), "offline":True, "replayIdentical":True, "coreLoop":True}))
'''


def check_mcp_stdio(python, workspace, env):
    # Exercise the installed CLI over real binary pipes, deliberately putting
    # Python's text wrappers in a legacy encoding. UTF-8 mode and the runner's
    # native locale must not conceal a protocol encoding regression.
    launch = '''
import runpy, sys
sys.stdin.reconfigure(encoding="cp1252")
sys.stdout.reconfigure(encoding="cp1252")
sys.argv = ["oopc", "--root", sys.argv[1], "mcp"]
runpy.run_module("oopc", run_name="__main__")
'''
    request = {"jsonrpc":"2.0", "id":"search-α", "method":"tools/call",
               "params":{"name":"search", "arguments":{"q":"α"}}}
    get_record = {"jsonrpc":"2.0", "id":3, "method":"tools/call",
                  "params":{"name":"get_record", "arguments":{"id":"wop-000001"}}}
    data = (json.dumps(request, ensure_ascii=False) + "\n{invalid JSON}\n" +
            json.dumps(get_record) + "\n").encode("utf-8")
    process = subprocess.run(
        [str(python), "-I", "-c", launch, str(workspace/"workspace")],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=workspace, env=env, timeout=60)
    if process.returncode:
        raise RuntimeError("Installed MCP stdio failed: " +
                           process.stderr.decode("utf-8", errors="replace"))
    responses = [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]
    assert len(responses) == 3, responses
    assert responses[0]["id"] == "search-α"
    records = responses[0]["result"]["structuredContent"]["records"]
    assert len(records) == 1 and records[0]["label"] == "Offline α polymer fixture"
    assert responses[1]["error"]["code"] == -32700
    assert responses[2]["id"] == 3 and not responses[2]["result"]["isError"]
    assert responses[2]["result"]["structuredContent"]["label"] == "Offline α polymer fixture"


def check_installed(wheel, workspace, env):
    environment = workspace/"venv"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, cwd=workspace, env=env)
    python = environment/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True, cwd=workspace, env=env)
    subprocess.run([str(python), "-I", "-c", SMOKE], check=True, cwd=workspace, env=env)
    check_mcp_stdio(python, workspace, env)
    command = environment/("Scripts/oopc.exe" if os.name == "nt" else "bin/oopc")
    subprocess.run([str(command), "--root", str(workspace/"workspace"), "verify"], check=True, cwd=workspace, env=env, stdout=subprocess.DEVNULL)
    subprocess.run([str(command), "--root", str(workspace/"replay-only"), "run-list"], check=True, cwd=workspace, env=env, stdout=subprocess.DEVNULL)


def main(directory):
    wheel, source = check_archives(Path(directory).resolve())
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="oopc-installed-") as temporary:
        workspace = Path(temporary)
        wheel_workspace = workspace/"wheel-install"
        wheel_workspace.mkdir()
        check_installed(wheel, wheel_workspace, env)
        # Build only the reviewed source archive in an empty directory. Build
        # tooling is provisioned before this offline check; no dependencies may
        # be fetched here. Install its result into a second clean reader venv.
        source_workspace = workspace/"source-build"
        source_workspace.mkdir()
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                target = source_workspace.joinpath(*archive_parts(member.name))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as incoming:
                    target.write_bytes(incoming.read())
        source_root, = source_workspace.iterdir()
        built = workspace/"source-wheel"
        subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--wheel",
                        "--outdir", str(built), str(source_root)],
                       check=True, cwd=workspace, env=env)
        rebuilt_wheel, = built.glob("*.whl")
        rebuilt_workspace = workspace/"source-install"
        rebuilt_workspace.mkdir()
        check_installed(rebuilt_wheel, rebuilt_workspace, env)
    print("Offline wheel and source-build installations, graph, replay, UTF-8 MCP stdio and console entry points passed.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "dist")
