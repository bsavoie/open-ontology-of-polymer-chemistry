"""Build the Mac app and its disk image (an unsigned Apple Silicon prototype).

The app is the Swift launcher in packaging/macos/, a pinned standalone Python
with the oopc package installed in it, and one verified graph release. It runs
`oopc inspect` on loopback with its workspace under
~/Library/Application Support/OOPC and opens the default browser. Nothing under
.oopc/ enters the bundle. The app is built from committed code only: the build
refuses uncommitted changes to what it bundles and records the commit in the
bundle (Info.plist `OOPCSourceCommit`, Resources/build.json). The bundle is signed ad hoc only, so a downloaded copy
opens through System Settings -> Privacy & Security -> Open Anyway.

    python3.13 tools/build_macos_app.py             # current release -> build/macos/
    python3.13 tools/build_macos_app.py --release releases/oopc-...

The builder needs Python 3.11 or later (the app bundles its own). Build locally
on a Mac: macOS runners cost ten times the CI minutes.
"""
import sys

if sys.version_info < (3, 11):  # tomllib and tarfile's extraction filters; the Mac's own python3 is 3.9.
    raise SystemExit("The Mac app builder needs Python 3.11 or later; this is Python %d.%d. Install one from "
                     "python.org or with `brew install python@3.13`, then run `python3.13 tools/build_macos_app.py`."
                     % sys.version_info[:2])

import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oopc import __version__
from oopc.release import verify_release
from oopc.util import resolve_release

APP = "OOPC"
BUNDLE_ID = "org.oopc.app"
MINIMUM_MACOS = "11.0"
# python-build-standalone, pinned by digest; bump both together.
PYTHON = {"url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/"
                 "cpython-3.13.16%2B20261009-aarch64-apple-darwin-install_only_stripped.tar.gz",
          "sha256": "11785155d0f70e634178219c20925d8f20be00a3da4684fc4f5019dd15602ef7",
          "version": "3.13"}
# Parts of the standalone Python the app never uses (Tk, IDLE, pip, headers).
TRIM = ["bin/idle3*", "bin/pip*", "bin/pydoc3*", "bin/python3*-config", "include", "share", "lib/pkgconfig",
        "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*", "lib/libtcl*", "lib/libtk*",
        "lib/python{v}/idlelib", "lib/python{v}/tkinter", "lib/python{v}/turtledemo", "lib/python{v}/turtle.py",
        "lib/python{v}/ensurepip", "lib/python{v}/site-packages/pip*", "lib/python{v}/lib-dynload/_tkinter*"]
LICENSES = ["LICENSE", "LICENSE-DATA", "LICENSE-CONTENT", "NOTICE"]
READ_ME = """OOPC {version} (prototype for Apple Silicon Macs)

1. Drag OOPC to Applications.
2. Open it. This prototype is not signed by Apple, so macOS blocks the first
   open: go to System Settings -> Privacy & Security, find the line about OOPC
   and choose Open Anyway.
3. The app opens in your browser. Click the OOPC icon in the Dock to open it
   again; quit OOPC to stop it.

Asking questions needs a signed-in Claude Code or ChatGPT (Codex)
subscription; connect one under Settings. Browsing works without one.
Your questions and findings stay on this Mac, in
~/Library/Application Support/OOPC.
"""


# What the app is built from: its package, launcher, builder, packaging metadata and licenses.
SOURCES = ["oopc", "packaging", "tools/build_macos_app.py", "pyproject.toml"] + LICENSES


def run(*command, **options):
    return subprocess.run([str(part) for part in command], check=True, **options)


def source_commit(root=ROOT):
    """The commit the app is built from; refuses uncommitted changes to what it bundles, so a build is always the
    code of one commit."""
    git = ["git", "-C", str(root)]
    changed = subprocess.run(git + ["status", "--porcelain", "--"] + SOURCES, capture_output=True, text=True,
                             check=True).stdout.strip()
    if changed:
        raise SystemExit("Commit these first; the app is built from committed code only:\n" + changed)
    return subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def fetch_python(cache):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / PYTHON["url"].rsplit("/", 1)[1].replace("%2B", "+")
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != PYTHON["sha256"]:
        partial = target.with_name(target.name + ".part")
        with urllib.request.urlopen(PYTHON["url"], timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        if digest != PYTHON["sha256"]:
            partial.unlink()
            raise SystemExit("Python download digest mismatch: " + digest)
        partial.rename(target)
    return target


def install_python(archive, resources):
    with tarfile.open(archive) as bundle:
        bundle.extractall(resources, filter="data")
    python = resources / "python"
    for pattern in TRIM:
        for path in python.glob(pattern.format(v=PYTHON["version"])):
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    return python


def install_package(site):
    """The files the wheel ships, from pyproject's package data."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    data = config["tool"]["setuptools"]["package-data"]["oopc"]
    source = ROOT / "oopc"
    members = {p for p in source.rglob("*.py") if "__pycache__" not in p.parts}
    for pattern in data:
        members.update(p for p in source.glob(pattern) if p.is_file())
    for path in sorted(members):
        target = site / "oopc" / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return len(members)


def install_release(release, resources):
    manifest = verify_release(release)
    release_id = manifest["release_id"]
    target = resources / "releases"
    target.mkdir()
    run("cp", "-cR", release, target / release_id)  # An APFS clone where it can be.
    (target / "current.json").write_text(json.dumps({"release_id": release_id}) + "\n")
    return release_id


def write_info(contents, commit):
    info = {"OOPCSourceCommit": commit,
        "CFBundleName": APP, "CFBundleDisplayName": APP, "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP, "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
        "CFBundleGetInfoString": "Open Ontology of Polymer Chemistry " + __version__,
        "NSHumanReadableCopyright": "Open Ontology of Polymer Chemistry. Apache-2.0; see Resources/licenses.",
        "LSMinimumSystemVersion": MINIMUM_MACOS, "LSArchitecturePriority": ["arm64"],
        "LSApplicationCategoryType": "public.app-category.education", "NSHighResolutionCapable": True}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))


def macho(path):
    with path.open("rb") as handle:
        return handle.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


def sign_ad_hoc(app):
    """Every Mach-O, then the bundle: an unsigned arm64 app reads as damaged, not unverified."""
    for path in sorted(p for p in app.rglob("*") if p.is_file() and not p.is_symlink() and macho(p)):
        run("codesign", "--force", "--sign", "-", "--timestamp=none", path, capture_output=True)
    run("codesign", "--force", "--sign", "-", "--timestamp=none", app)
    run("codesign", "--verify", "--deep", "--strict", app)


def smoke_test(python, resources):
    check = ("import sqlite3, oopc.server, oopc.engines, oopc.ask, oopc.loop\n"
             "sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)')\n"
             "from oopc.release import verify_release\n"
             "import json, sys; r = sys.argv[1] + '/releases/'\n"
             "print(verify_release(r + json.load(open(r + 'current.json'))['release_id'])['release_id'])\n")
    return run(python / "bin" / "python3", "-I", "-c", check, resources, capture_output=True, text=True,
               cwd="/").stdout.strip()


def build_dmg(app, out):
    stage = out / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    run("cp", "-cR", app, stage)  # An APFS clone; no second copy of the release.
    (stage / "Applications").symlink_to("/Applications")
    (stage / "Read Me First.txt").write_text(READ_ME.format(version=__version__))
    image = out / (APP + "-" + __version__ + "-arm64.dmg")
    run("hdiutil", "create", "-volname", APP, "-srcfolder", stage, "-format", "ULMO", "-ov", image, capture_output=True)
    shutil.rmtree(stage)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", help="Release directory or ID (default: the current release)")
    parser.add_argument("--out", default=str(ROOT / "build" / "macos"), help="Output directory")
    parser.add_argument("--no-dmg", action="store_true", help="Build the app only")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("Build the Mac app on macOS (it needs swiftc, codesign and hdiutil).")
    out = Path(args.out).resolve()
    commit = source_commit()
    release = resolve_release(ROOT, args.release)
    app = out / (APP + ".app")
    shutil.rmtree(app, ignore_errors=True)
    contents = app / "Contents"
    resources = contents / "Resources"
    (contents / "MacOS").mkdir(parents=True)
    resources.mkdir()

    python = install_python(fetch_python(out / "cache"), resources)
    site = python / "lib" / ("python" + PYTHON["version"]) / "site-packages"
    files = install_package(site)
    # Precompiled and never rechecked, so no process writes __pycache__ into the bundle.
    run(python / "bin" / "python3", "-I", "-m", "compileall", "-q", "-f", "-j", "0", "--invalidation-mode", "unchecked-hash",
        python / "lib", capture_output=True, cwd="/")
    release_id = install_release(release, resources)
    (resources / "licenses").mkdir()
    for name in LICENSES:
        shutil.copy2(ROOT / name, resources / "licenses" / name)
    run("xcrun", "swiftc", "-O", "-swift-version", "5", "-target", "arm64-apple-macos" + MINIMUM_MACOS,
        ROOT / "packaging" / "macos" / "OOPC.swift", "-o", contents / "MacOS" / APP)
    write_info(contents, commit)
    (resources / "build.json").write_text(json.dumps({"version": __version__, "commit": commit, "release": release_id,
                                                      "python": PYTHON["url"].rsplit("/", 1)[1].replace("%2B", "+")},
                                                     indent=2) + "\n")
    if smoke_test(python, resources) != release_id:
        raise SystemExit("The bundled Python could not verify the bundled release")
    sign_ad_hoc(app)
    summary = {"app": str(app), "version": __version__, "commit": commit, "release": release_id, "package_files": files,
               "python": PYTHON["url"].rsplit("/", 1)[1].replace("%2B", "+")}
    if not args.no_dmg:
        image = build_dmg(app, out)
        summary.update(dmg=str(image), dmg_bytes=image.stat().st_size,
                       dmg_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
