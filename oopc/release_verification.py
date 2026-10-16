"""Short-lived reuse of checked data, never of private authority.

The first read still validates every release checksum. Every reuse checks the
complete file/path fingerprint, including ctime and inode, and returns copies.
Callers end the scope (or clear it) across writes and external model execution.
There is no persistent cache and no cached permission, quota or journal result.
Captured representations reuse only deterministic reconstruction after their
current private objects have each passed byte, checksum and path checks.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import stat
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path, PosixPath

MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_RELEASE_SNAPSHOTS = 2
MAX_CORPUS_SLICES = 32
MAX_REPRESENTATIONS = 128
MAX_ARCHIVE_OBJECTS = 128
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_FINGERPRINT_LAYOUT_FILES = 1024
MAX_FINGERPRINT_LAYOUT_PATHS = 4096
MAX_FINGERPRINT_LAYOUT_BYTES = 2 * 1024 * 1024
MAX_PRIVATE_READ_BYTES = 256 * 1024 * 1024
MAX_VERIFIED_RESULTS = 256
_ACTIVE = ContextVar("oopc_release_verification", default=None)


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return os.getpid(), threading.get_ident(), id(task) if task is not None else None


@dataclass
class _State:
    owner: tuple
    snapshots: dict = field(default_factory=OrderedDict)
    snapshot_bytes: int = 0
    active: bool = True
    representations: set = field(default_factory=set)
    archive_objects: dict = field(default_factory=dict)
    archive_bytes: int = 0
    # TD-16: private files verified once per operation, keyed by path and identity.
    private_reads: dict = field(default_factory=dict)
    private_read_bytes: int = 0
    checked_directories: set = field(default_factory=set)
    canonical_by_bytes: dict = field(default_factory=dict)
    # Pure verification results, each with the identities of every private file
    # it read; reuse re-checks them all (see reuse_verified).
    verified_results: dict = field(default_factory=dict)
    read_logs: list = field(default_factory=list)


@dataclass
class _Snapshot:
    path: Path
    fingerprint: tuple
    records: list
    ontology: dict
    manifest: dict
    source_bytes: int
    corpora: dict = field(default_factory=dict)
    layout: object = None


@dataclass(frozen=True)
class _FingerprintLayout:
    root: str
    manifest_names: tuple
    visits: tuple
    files: tuple
    parents: tuple
    metadata_bytes: int


def _state():
    value = _ACTIVE.get()
    return value if value is not None and value.active and value.owner == _owner() else None


@contextmanager
def release_verification_scope():
    """Reuse checked data within this thread/task; nested scopes share it."""
    if _state() is not None:
        yield
        return
    state = _State(_owner())
    token = _ACTIVE.set(state)
    try:
        yield
    finally:
        _clear_snapshots(state)
        state.representations.clear()
        state.archive_objects.clear()
        state.archive_bytes = 0
        _clear_private_reads(state)
        state.active = False
        _ACTIVE.reset(token)


def with_verified_reads(operation):
    """Share checked data during one operation; preserve its public signature."""
    @wraps(operation)
    def scoped(*args, **kwargs):
        with release_verification_scope():
            return operation(*args, **kwargs)
    return scoped


def clear_release_verification_cache():
    """Drop snapshots and pure reconstructions at mutation/model boundaries."""
    value = _state()
    if value is not None:
        _clear_snapshots(value)
        value.representations.clear()
        value.archive_objects.clear()
        value.archive_bytes = 0
        _clear_private_reads(value)


def _clear_private_reads(state):
    state.verified_results.clear()
    state.private_reads.clear()
    state.private_read_bytes = 0
    state.checked_directories.clear()
    state.canonical_by_bytes.clear()


def private_file_identity(path):
    info = os.lstat(path)
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def record_private_read(state, path, identity):
    """Tell every enclosing reuse_verified computation which file it depended on."""
    for log in state.read_logs:
        log[str(path)] = identity


def reuse_verified(key, compute):
    """Reuse a pure verification result within one operation.

    The result is kept with the identity (device, inode, mode, links, size, mtime,
    ctime) of every private file read while computing it. Each reuse lstat-checks
    all of them, as a fresh read would, and recomputes on any change. Failures
    are never kept, and like every reuse here it ends with the operation or at
    the next write or model boundary. Only computations that read their inputs
    through the private reader may use this.
    """
    state = _state()
    if state is None:
        return compute()
    cached = state.verified_results.get(key)
    if cached is not None:
        value, reads = cached
        try:
            unchanged = all(private_file_identity(path) == identity for path, identity in reads)
        except OSError:
            unchanged = False
        if unchanged:
            for log in state.read_logs:
                log.update(reads)
            return copy.deepcopy(value)
        del state.verified_results[key]
    log = {}
    state.read_logs.append(log)
    try:
        value = compute()
    finally:
        # Logs nest strictly; compare by identity, since equal dicts are not the same log.
        index = next(i for i in range(len(state.read_logs) - 1, -1, -1) if state.read_logs[i] is log)
        del state.read_logs[index]
    for outer in state.read_logs:
        outer.update(log)
    if state.active and len(state.verified_results) < MAX_VERIFIED_RESULTS:
        state.verified_results[key] = (copy.deepcopy(value), tuple(sorted(log.items())))
    return value


def verified_read_scope():
    """The active operation's state for reusing verified private reads, else None."""
    return _state()


def _clear_snapshots(state):
    state.snapshots.clear()
    state.snapshot_bytes = 0


def _source_bytes(manifest):
    sizes = [manifest["files"][name]["bytes"] for name in ("records.jsonl", "ontology.json")]
    if any(type(size) is not int or size < 0 for size in sizes):
        raise ValueError("Invalid release source byte count")
    return sum(sizes)


def _reserve_snapshot(state, size):
    """Evict before loading, under one aggregate source-byte/entry limit."""
    if size > MAX_SOURCE_BYTES or MAX_RELEASE_SNAPSHOTS < 1:
        _clear_snapshots(state)
        return
    while state.snapshots and (len(state.snapshots) >= MAX_RELEASE_SNAPSHOTS
                              or state.snapshot_bytes + size > MAX_SOURCE_BYTES):
        _, oldest = state.snapshots.popitem(last=False)
        state.snapshot_bytes -= oldest.source_bytes


def _checked_archive_object(path, identity, loader):
    """Reuse checked bytes/JSON after fresh file and ancestor identity checks.

    The caller still checks its private directory contract on every access;
    loader enforces file safety, byte limits, checksum and canonical encoding.
    No reviewer judgment or mutable authority is stored here.
    """
    state = _state()
    if state is None:
        return loader()[0]
    path = Path(path).absolute()
    key = (str(path), identity)
    previous = state.archive_objects.get(key)
    try:
        before = _object_fingerprint(path)
    except (OSError, ValueError):
        if previous is not None:
            state.archive_bytes -= state.archive_objects.pop(key)[2]
        return loader()[0]  # Preserve the reader's normal unsafe/missing-file error.
    if previous is not None:
        if previous[0] == before:
            return copy.deepcopy(previous[1])
        state.archive_bytes -= state.archive_objects.pop(key)[2]
    value, size = loader()
    try:
        unchanged = before == _object_fingerprint(path)
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        raise ReleaseVerificationError("Source archive object changed during checksum verification")
    if size <= MAX_ARCHIVE_BYTES and MAX_ARCHIVE_OBJECTS > 0:
        if (len(state.archive_objects) >= MAX_ARCHIVE_OBJECTS
                or state.archive_bytes + size > MAX_ARCHIVE_BYTES):
            state.archive_objects.clear()
            state.archive_bytes = 0
        state.archive_objects[key] = (before, value, size)
        state.archive_bytes += size
    return copy.deepcopy(value)


def _checked_representation(folder, identity, verify):
    """Reuse a pure reconstruction, only after the caller checked all bytes.

    Identity binds the exact capture, wire, XML, projection and descriptor.
    Every invocation must follow fresh checks of those objects and their paths;
    this set is neither a source-rights grant nor a scientific review receipt.
    """
    state = _state()
    key = (str(Path(folder).absolute()), identity)
    if state is not None and key in state.representations:
        return
    verify()
    if state is not None:
        if len(state.representations) >= MAX_REPRESENTATIONS:
            state.representations.clear()
        state.representations.add(key)


class ReleaseVerificationError(ValueError):
    """A changing public release is an operational failure, not source evidence."""


def _identity(path, *, content):
    info = path.lstat()
    # Directory links count child directories, including unrelated siblings of
    # this release. File and symlink link counts still protect their identity.
    links = None if not content and stat.S_ISDIR(info.st_mode) else info.st_nlink
    values = (info.st_dev, info.st_ino, info.st_mode, links,
              info.st_uid, info.st_gid)
    if content:
        values += (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if stat.S_ISLNK(info.st_mode):
        values += (os.readlink(path),)
    return values


def _object_fingerprint(path):
    resolved = path.resolve(strict=True)
    files = {path, resolved}
    parents = set(path.parents) | set(resolved.parents)
    return (tuple((str(file), _identity(file, content=True)) for file in sorted(files)),
            tuple((str(parent), _identity(parent, content=False)) for parent in sorted(parents)))


def _fingerprint(path, manifest):
    """Track files plus lexical/resolved ancestors, including symlink identity.

    Parent directory timestamps and child-directory link counts are excluded:
    unrelated directory entries are not release inputs. Identity, type,
    ownership and symlink changes are checked.
    Each listed file and the manifest retain the full timestamp/size signature.
    """
    names = set(manifest["files"]) | {"manifest.json"}
    files, resolved_parents, immediate_parents = set(), {}, {}
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe release fingerprint path: " + name)
        file = path / relative
        if stat.S_ISLNK(file.lstat().st_mode):
            resolved = file.resolve(strict=True)
        else:
            parent = file.parent
            if parent not in resolved_parents:
                resolved_parents[parent] = parent.resolve(strict=True)
            resolved = resolved_parents[parent] / file.name
        files.update((file, resolved))
        for item in (file, resolved):
            parent = item.parent
            if parent != item:
                immediate_parents.setdefault(parent, None)
    # Build each shared ancestor chain once in this call. Every file and
    # ancestor still receives the same fresh identity check below. Preserve
    # encounter order for the spelling of equal case-insensitive paths.
    parents = set()
    for parent in immediate_parents:
        parents.add(parent)
        parents.update(parent.parents)
    return (tuple((str(file), _identity(file, content=True)) for file in sorted(files)),
            tuple((str(parent), _identity(parent, content=False)) for parent in sorted(parents)))


def _fingerprint_layout(path, manifest):
    """Bounded lexical structure only; unsupported layouts keep the old path."""
    if (os.name != "posix" or type(path) is not PosixPath
            or path.anchor != "/" or ".." in path.parts
            or len(path.parts) > MAX_FINGERPRINT_LAYOUT_PATHS):
        return None
    entries = manifest.get("files")
    if type(entries) is not dict or len(entries) > MAX_FINGERPRINT_LAYOUT_FILES:
        return None
    root = str(path)
    metadata_bytes = 512 + 16 * len(root) + 64 * len(path.parts)
    if metadata_bytes > MAX_FINGERPRINT_LAYOUT_BYTES:
        return None
    aliases = set()
    for name in entries:
        if type(name) is not str:
            return None
        metadata_bytes += 128 + 16 * len(name)
        if (metadata_bytes > MAX_FINGERPRINT_LAYOUT_BYTES
                or len(path.parts) + name.count("/") + 1 > MAX_FINGERPRINT_LAYOUT_PATHS):
            return None
        # Exclude spelling aliases and Windows-specific forms rather than
        # changing the original Path/set representative or error semantics.
        if (not name or "\\" in name or ":" in name
                or any(part in ("", ".", "..") for part in name.split("/"))):
            return None
        alias = name.casefold()
        if alias in aliases or (alias == "manifest.json" and name != "manifest.json"):
            return None
        aliases.add(alias)
    names = set(entries) | {"manifest.json"}
    if len(names) > MAX_FINGERPRINT_LAYOUT_FILES:
        return None
    files, parents, visits = {}, {}, []

    def retain(item, collection):
        nonlocal metadata_bytes
        if len(files) + len(parents) >= MAX_FINGERPRINT_LAYOUT_PATHS:
            return False
        spelling = str(item)
        # Conservative allowance for Path components, spelling, container
        # entries and visit references; count every expanded ancestor too.
        size = 512 + 16 * len(spelling) + 64 * len(item.parts)
        if metadata_bytes + size > MAX_FINGERPRINT_LAYOUT_BYTES:
            return False
        metadata_bytes += size
        collection[item] = (spelling, item)
        return True

    for name in names:  # Preserve the oracle's file-check encounter order.
        file = path / name
        if not retain(file, files):
            return None
        parent = file.parent
        ancestor = parent
        while ancestor not in parents:
            if not retain(ancestor, parents):
                return None
            above = ancestor.parent
            if above == ancestor:
                break
            ancestor = above
        visits.append((file, parents[parent][1]))
    return _FingerprintLayout(root, tuple(entries), tuple(visits),
                              tuple(files[item] for item in sorted(files)),
                              tuple(parents[item] for item in sorted(parents)),
                              metadata_bytes)


def _fingerprint_with_layout(path, manifest, layout):
    """Reuse path construction, never lstat, resolution or identity answers."""
    if (layout is None or os.name != "posix" or type(path) is not PosixPath or str(path) != layout.root
            or type(manifest.get("files")) is not dict
            or len(manifest["files"]) != len(layout.manifest_names)
            or tuple(manifest["files"]) != layout.manifest_names):
        return _fingerprint(path, manifest)
    resolved_parents = set()
    for file, parent in layout.visits:
        if stat.S_ISLNK(file.lstat().st_mode):
            raise ReleaseVerificationError("Release path changed during fingerprint reuse")
        if parent not in resolved_parents:
            if str(parent.resolve(strict=True)) != str(parent):
                raise ReleaseVerificationError("Release path changed during fingerprint reuse")
            resolved_parents.add(parent)
    return (tuple((name, _identity(file, content=True)) for name, file in layout.files),
            tuple((name, _identity(parent, content=False)) for name, parent in layout.parents))


def _verified_snapshot(path, loader):
    """Internal borrowed snapshot; only pure selectors may see its mutable data."""
    state = _state()
    if state is None:
        return None
    # Keep lexical '..': collapsing it before the filesystem follows a symlink
    # can select a different, otherwise valid release than the original caller.
    path = Path(path).absolute()
    old = state.snapshots.get(path)
    if old is not None:
        try:
            if _fingerprint_with_layout(path, old.manifest, old.layout) == old.fingerprint:
                state.snapshots.move_to_end(path)
                return old
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # A changed fingerprint invalidates checked data before revalidation.
        _clear_snapshots(state)
        old = None
    try:
        advertised = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        before = _fingerprint(path, advertised)
        _reserve_snapshot(state, _source_bytes(advertised))
        records, ontology, manifest = loader(path)
        after = _fingerprint(path, manifest)
        if before != after or advertised != manifest:
            raise ReleaseVerificationError("Release changed during checksum verification")
        size = _source_bytes(manifest)
    except BaseException:
        # Preserve fail-closed behavior even if a different cached release was
        # valid: failed reads never leave formerly trusted snapshots reusable.
        _clear_snapshots(state)
        raise
    value = _Snapshot(path, after, records, ontology, manifest, size)
    if size <= MAX_SOURCE_BYTES and MAX_RELEASE_SNAPSHOTS > 0:
        layout = _fingerprint_layout(path, manifest)
        if (layout is not None
                and tuple(name for name, _ in layout.files) == tuple(name for name, _ in after[0])
                and tuple(name for name, _ in layout.parents) == tuple(name for name, _ in after[1])):
            value.layout = layout
        state.snapshots[path] = value
        state.snapshot_bytes += size
    return value


def _cached_corpus(path, key, builder, loader):
    """Run a pure corpus selector on checked records; copy only its bounded output."""
    snapshot = _verified_snapshot(path, loader)
    if snapshot is None:
        return None
    if key not in snapshot.corpora:
        value = builder(snapshot.records, snapshot.ontology, snapshot.manifest)
        state = _state()
        if (state is None or state.snapshots.get(snapshot.path) is not snapshot
                or MAX_CORPUS_SLICES < 1):
            return copy.deepcopy(value)
        if sum(len(item.corpora) for item in state.snapshots.values()) >= MAX_CORPUS_SLICES:
            for item in state.snapshots.values():
                item.corpora.clear()
        snapshot.corpora[key] = value
    return copy.deepcopy(snapshot.corpora[key])
