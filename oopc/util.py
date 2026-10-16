"""Small, deterministic serialization and local storage helpers."""
import contextlib
import errno
import functools
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_bytes(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="." + path.name + "-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            if private:
                fchmod = getattr(os, "fchmod", None)
                if callable(fchmod):
                    fchmod(handle.fileno(), 0o600)
                else:
                    # Python <3.13 on Windows lacks fchmod. chmod keeps the
                    # file writable; Windows access control comes from its
                    # inherited ACL, not these POSIX owner permission bits.
                    os.chmod(temp, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def atomic_json(path, value, private=False):
    atomic_bytes(path, canonical(value) + b"\n", private=private)


@contextlib.contextmanager
def _windows_locked(handle, blocking=True, backend=None, deadline=None, describe=None):
    """Lock byte zero; Windows LK_LOCK itself stops after ten attempts."""
    if backend is None:
        import msvcrt as backend
    if os.fstat(handle.fileno()).st_size == 0:
        handle.write(b"\0")
        handle.flush()
    contention = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
    while True:
        handle.seek(0)
        try:
            backend.locking(handle.fileno(), backend.LK_NBLCK, 1)
            break
        except OSError as error:
            if error.errno not in contention:
                raise
            if not blocking:
                raise BlockingIOError(error.errno, "Another process holds the local lock") from error
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(describe() if describe else "Timed out waiting for the local lock") from error
            # Match blocking POSIX flock semantics without the CRT's implicit
            # ten-second expiry. KeyboardInterrupt can still stop the wait.
            time.sleep(0.05)
    try:
        yield
    finally:
        handle.seek(0)
        backend.locking(handle.fileno(), backend.LK_UNLCK, 1)


@functools.lru_cache(maxsize=256)
def _resolved(absolute_root):
    return Path(absolute_root).resolve()


def canonical_root(root):
    """Resolve a workspace root once per process (TD-16).

    Where the root lives is fixed for a process, and the directories above it are
    outside private storage, so they are not re-walked on every call. Callers still
    check the root directory itself and everything below it on each use.
    """
    return _resolved(str(Path(root).absolute()))


def workspace_chain(path):
    """`path` and its ancestors up to the workspace root, which holds `.oopc` (TD-16).

    Symlink and real-directory checks protect private storage, so they stop at the
    workspace root (the parent of the outermost `.oopc` component) instead of
    re-checking operating-system directories above it on every call. Callers that
    need the root itself validated still get it, since it is included. A path with
    no `.oopc` component keeps every ancestor, as before.
    """
    path = Path(path)
    chain = (path, *path.parents)
    marks = [index for index, item in enumerate(chain) if item.name == ".oopc"]
    return chain[:marks[-1] + 2] if marks else chain


def read_bounded(path, limit, *, message="Local file must be a bounded regular file", oversize=None,
                 overflow=None, error=ValueError, single_link=True, private=False):
    """Read at most `limit` bytes from a local regular file without following links (TD-18).

    The shared hardened read: O_NOFOLLOW refuses a final symlink, O_NONBLOCK keeps
    a FIFO swapped in for the file from blocking, and fstat on the open descriptor
    requires a regular file within `limit`, with exactly one hard link unless
    `single_link` is false, and owner-only permissions when `private` is true.
    Callers keep their own path containment, parent checks and decoding, and
    choose the exception type and messages so their contracts are unchanged:
    `message` for shape, `oversize` for a stat size over the limit (default
    `message`) and `overflow` for bytes read past it (default `oversize`).
    OSError from opening (missing file, symlink) propagates unchanged.
    """
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or (single_link and info.st_nlink != 1)
                or (private and os.name != "nt" and info.st_mode & 0o077)):
            raise error(message)
        if info.st_size > limit:
            raise error(oversize or message)
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, min(1 << 20, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > limit:
            raise error(overflow or oversize or message)
        return b"".join(chunks)
    finally:
        os.close(fd)


def private_sqlite(path):
    """Create or tighten a private SQLite database before connecting (TD-22).

    `sqlite3.connect` creates files with the process umask (usually 0644), and
    SQLite gives -wal and -shm files the database file's permissions. Private
    operational databases are therefore created owner-only, and existing ones
    are tightened. Returns the path as a string for `sqlite3.connect`.
    """
    path = Path(path)
    if os.name != "nt":
        os.close(os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600))
        for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            try:
                info = os.lstat(candidate)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_mode & 0o077:
                os.chmod(candidate, info.st_mode & 0o700)
    return str(path)


# SQLite 3.51.0 (macOS 26's and anaconda's in 2026-10) can deadlock inside its unix file layer when threads of one
# process open and close the same WAL database at once; 3.51.2 fixed it (CL-7). Opening and closing take turns.
_SQLITE_TURNS = threading.Lock()


def sqlite_open(target, **options):
    """`sqlite3.connect`, never at the same moment as another thread's open or close."""
    import sqlite3
    with _SQLITE_TURNS:
        return sqlite3.connect(target, **options)


def sqlite_close(connection):
    with _SQLITE_TURNS:
        connection.close()


# In-process holders of each lock file, reported when a bounded wait times out.
_LOCK_HOLDERS = {}


@contextlib.contextmanager
def locked(path, blocking=True, timeout=None):
    """Process lock for local trace writers on POSIX and Windows.

    With `timeout` (seconds), a blocking wait that outlasts it raises
    TimeoutError naming the lock and any timed holder in this process, instead
    of waiting indefinitely. Without it, blocking waits are unbounded and the
    lock behaves exactly as before (no clock reads or holder records).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.absolute())
    deadline = time.monotonic() + timeout if blocking and timeout is not None else None

    def describe():
        holder = _LOCK_HOLDERS.get(key)
        where = (f"held in this process by thread {holder[0]!r} for {time.monotonic() - holder[1]:.1f}s"
                 if holder else "held by another process")
        return f"Timed out after {timeout}s waiting for local lock {path} ({where})"

    # Lock files are created owner-only, like the private state they guard.
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), "a+b") as handle:
        if os.name == "nt":
            with _windows_locked(handle, blocking, deadline=deadline, describe=describe):
                if timeout is not None:
                    _LOCK_HOLDERS[key] = (threading.current_thread().name, time.monotonic())
                try:
                    yield
                finally:
                    if timeout is not None:
                        _LOCK_HOLDERS.pop(key, None)
        else:
            import fcntl
            if deadline is None:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            else:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(describe()) from None
                        time.sleep(0.02)
            if timeout is not None:
                _LOCK_HOLDERS[key] = (threading.current_thread().name, time.monotonic())
            try:
                yield
            finally:
                if timeout is not None:
                    _LOCK_HOLDERS.pop(key, None)
                fcntl.flock(handle, fcntl.LOCK_UN)


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,160}", value) or ".." in value:
        raise ValueError("Invalid local identifier")
    return value


def walk_records(value):
    if isinstance(value, dict):
        if isinstance(value.get("@id"), str) and "@type" in value:
            yield value
        for child in value.values():
            yield from walk_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_records(child)


def resolve_release(root, selected=None):
    root = Path(root).resolve()
    if selected:
        path = Path(selected)
        if path.is_dir() and (path / "manifest.json").exists():
            return path.resolve()
        path = root / "releases" / safe_name(selected)
        if path.is_dir():
            return path
        raise ValueError("Release not found: " + str(selected))
    current = root / "releases" / "current.json"
    if current.exists():
        return resolve_release(root, read_json(current)["release_id"])
    choices = sorted(p for p in (root / "releases").glob("*") if p.is_dir() and (p / "manifest.json").exists())
    if len(choices) == 1:
        return choices[0]
    raise ValueError("Select a release or import a seed first")
