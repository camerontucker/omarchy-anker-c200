"""Linux descriptor-relative file access for small, user-owned plugin data."""

import contextlib
import fcntl
import json
import math
import os
import secrets
import stat
from pathlib import Path


class UnsafeInput(RuntimeError):
    """Fail closed without reflecting potentially sensitive input in errors."""


def json_object(raw, limit=16384):
    if len(raw) > limit:
        raise UnsafeInput("JSON byte limit exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise UnsafeInput("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(UnsafeInput("nonfinite JSON")))
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise UnsafeInput("invalid JSON") from exc
    budget = [0]
    def check(item, depth=0):
        budget[0] += 1
        if depth > 8 or budget[0] > 4096:
            raise UnsafeInput("JSON structure limit exceeded")
        if isinstance(item, dict):
            if len(item) > 128:
                raise UnsafeInput("JSON object limit exceeded")
            for key, child in item.items():
                if len(key) > 128:
                    raise UnsafeInput("JSON key limit exceeded")
                check(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 128:
                raise UnsafeInput("JSON array limit exceeded")
            for child in item:
                check(child, depth + 1)
        elif isinstance(item, str) and len(item) > 1024:
            raise UnsafeInput("JSON string limit exceeded")
        elif isinstance(item, float) and not math.isfinite(item):
            raise UnsafeInput("nonfinite JSON number")
    check(value)
    if not isinstance(value, dict):
        raise UnsafeInput("JSON object required")
    return value


@contextlib.contextmanager
def directory(path, create=False, private=False):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or len(str(path)) > 4096:
        raise UnsafeInput("absolute safe directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in path.parts[1:]:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                            os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            # Root-owned sticky directories permit safe private test/temp roots.
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not sticky_root):
                raise UnsafeInput("unsafe directory ownership or permissions")
        if private:
            info = os.fstat(fd)
            if info.st_uid != os.getuid():
                raise UnsafeInput("private directory must belong to this user")
            os.fchmod(fd, 0o700)
        yield fd
    finally:
        os.close(fd)


def open_regular(parent, name, limit, *, secret=False, system=False):
    if not name or "/" in name or name in {".", ".."}:
        raise UnsafeInput("invalid leaf name")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        info = os.fstat(fd)
        owner = 0 if system else os.getuid()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or
                info.st_mode & (0o077 if secret else 0o022) or (not system and info.st_nlink != 1) or
                info.st_size > limit):
            raise UnsafeInput("unsafe file type, ownership, mode, links, or size")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_fd(fd, limit):
    chunks = []
    size = 0
    while True:
        chunk = os.read(fd, min(65536, limit + 1 - size))
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise UnsafeInput("file byte limit exceeded")
        chunks.append(chunk)


def read_file(path, limit=16384, *, secret=False):
    path = Path(path)
    with directory(path.parent) as parent:
        fd = open_regular(parent, path.name, limit, secret=secret)
        try:
            return read_fd(fd, limit)
        finally:
            os.close(fd)


@contextlib.contextmanager
def locked_directory(path):
    with directory(path, create=True, private=True) as parent:
        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                       os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            info = os.fstat(lock)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_mode & 0o077 or info.st_nlink != 1):
                raise UnsafeInput("unsafe lock file")
            # Never block a GUI request waiting for another owner.
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield parent
        finally:
            os.close(lock)


def publish(parent, name, data, *, replace=True):
    """Publish under a held private directory lock; never follow the destination.

    Existing destinations must be safe regular files. Replacement renames the
    entry itself, never writes through it. Immutable cache objects use an atomic
    no-replace hard-link publication instead of a check-then-create sequence.
    """
    if "/" in name or name in {"", ".", ".."}:
        raise UnsafeInput("invalid publication name")
    if replace:
        try:
            old = open_regular(parent, name, 2 * 1024 * 1024)
        except FileNotFoundError:
            pass
        else:
            os.close(old)
    temporary = ".new-" + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                 os.O_CLOEXEC, 0o600, dir_fd=parent)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        if replace:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def write_file(path, data):
    if len(data) > 16384:
        raise UnsafeInput("settings byte limit exceeded")
    path = Path(path)
    with locked_directory(path.parent) as parent:
        publish(parent, path.name, data)
