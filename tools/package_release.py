"""Build a reproducible offline ZIP from reviewed, explicitly named public files.

No recursive folder admission: adding a file to a public package is a separate
change to config/public-files.json. Private state and symlinks fail closed.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oopc import __version__
from oopc.release import verify_release
from oopc.util import atomic_bytes, canonical, resolve_release, safe_name


def _safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid public member path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in (".", "..") or p.startswith(".") for p in path.parts):
        raise ValueError("Unsafe public member path: " + value)
    return path


def _public_bytes(root, relative):
    relative = _safe_relative(relative)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Public package members cannot be symlinks: " + str(relative))
    if not path.is_file() or root.resolve() not in path.resolve().parents:
        raise ValueError("Missing or unsafe public member: " + str(relative))
    return path.read_bytes()


def collect_members(root, release=None):
    root = Path(root).resolve()
    selection = json.loads(_public_bytes(root, "config/public-files.json"))
    paths = selection.get("files")
    if selection.get("format") != "oopc-public-files-v1" or not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("Invalid public file allowlist")
    if len(paths) != len(set(paths)) or "config/public-files.json" not in paths:
        raise ValueError("Public file allowlist must be unique and include itself")
    members = {}
    for name in paths:
        path = _safe_relative(name)
        if path.parts[0] in ("private", "artifacts", "releases", "dist", "node_modules"):
            raise ValueError("Private or generated path is not a public authoring input: " + name)
        members[name] = _public_bytes(root, name)
    release = Path(release).resolve() if release else resolve_release(root).resolve()
    # Verify before reading any selected release member. A linked release root is
    # permitted; symlinked files and subdirectories inside it are not.
    manifest = verify_release(release)
    release_id = safe_name(manifest["release_id"])
    for name in sorted(set(manifest["files"]) | {"manifest.json"}):
        members["releases/" + release_id + "/" + str(_safe_relative(name))] = _public_bytes(release, name)
    members["releases/current.json"] = canonical({"release_id": release_id}) + b"\n"
    return members, manifest


def build_bundle(root, release=None, output=None):
    root = Path(root).resolve()
    members, manifest = collect_members(root, release)
    name = "open-ontology-of-polymer-chemistry-" + safe_name(__version__)
    checksums = {path: hashlib.sha256(data).hexdigest() for path, data in members.items()}
    members["BUNDLE-MANIFEST.json"] = json.dumps({"name": name, "release_id": manifest["release_id"],
        "privateTracesIncluded": False, "files": checksums}, sort_keys=True, indent=2).encode() + b"\n"
    output = Path(output) if output else root / "dist"
    output.mkdir(parents=True, exist_ok=True)
    target = output / (name + ".zip")
    # Build in memory, so a failed read/validation cannot replace a prior bundle.
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, data in sorted(members.items()):
            info = zipfile.ZipInfo(name + "/" + path, date_time=(2026, 9, 10, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    atomic_bytes(target, data)
    atomic_bytes(target.with_suffix(".zip.sha256"), (digest + "  " + target.name + "\n").encode())
    return {"path": str(target), "bytes": len(data), "sha256": digest,
            "release_id": manifest["release_id"], "files": len(members)}


if __name__ == "__main__":
    print(json.dumps(build_bundle(ROOT)))
