#!/usr/bin/python3
"""Bounded Linux process supervisor; the only QML helper entry point."""

import ctypes
import fcntl
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

# -I excludes cwd/PYTHONPATH; only this reviewed plugin directory is added.
ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from secure_io import UnsafeInput, directory, open_regular, read_fd

IN_WORKER = False
MAX_OUTPUT = 32768
MAX_LINE = 16384
MAX_REQUEST = 1024
REQUEST_SECONDS = 8
BACKEND_SECONDS = 45
PYTHON = "/usr/bin/python3"


def environment():
    # No LD_*, PYTHON*, CC/GCC_*, shell startup or ambient executable search.
    result = {"PATH": "/usr/bin", "LANG": "C", "LC_ALL": "C", "HOME": str(Path.home())}
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def trusted_executable(path):
    if path not in {PYTHON, "/usr/bin/cc", "/usr/bin/v4l2-ctl", "/usr/bin/obs"}:
        raise UnsafeInput("executable is not allowlisted")
    # Package-manager symlinks are allowed only within the root-owned /usr tree.
    resolved = Path(path).resolve(strict=True)
    if not str(resolved).startswith("/usr/"):
        raise UnsafeInput("executable outside trusted system tree")
    with directory(resolved.parent) as parent:
        fd = open_regular(parent, resolved.name, 256 * 1024 * 1024, system=True)
    if not os.fstat(fd).st_mode & 0o111:
        os.close(fd)
        raise UnsafeInput("system file is not executable")
    return fd


def sealed_executable(data):
    if not data.startswith(b"\x7fELF") or len(data) > 2 * 1024 * 1024:
        raise UnsafeInput("invalid controller artifact")
    fd = os.memfd_create("anker-controller", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, data)
        os.fchmod(fd, 0o500)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                    fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        return fd
    except BaseException:
        os.close(fd)
        raise


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise UnsafeInput("cannot establish child reaper")


def cleanup_group(process):
    # Group remains owned even when the leader has exited and pipes stay open.
    for sig, grace in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        end = time.monotonic() + grace
        while time.monotonic() < end:
            process.poll()
            try:
                pid, _ = os.waitpid(-process.pid, os.WNOHANG)
            except ChildProcessError:
                break
            if not pid:
                time.sleep(0.01)
        if sig == signal.SIGKILL:
            process.wait(timeout=1)


def spawn(arguments, executable_fd, *, stdin=subprocess.DEVNULL, pass_fds=(), group=True):
    return subprocess.Popen(arguments, executable=f"/proc/self/fd/{executable_fd}",
                            pass_fds=tuple(set((executable_fd, *pass_fds))),
                            stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=environment(), start_new_session=group, close_fds=True)


def run_bounded(arguments, *, timeout=2, cap=16384, executable_fd=None, pass_fds=()):
    """Cap bytes during capture, not after communicate(); one absolute deadline.

    Workers and their compiler/controller children share the supervisor-owned
    process group. Standalone callers own a fresh group. Limit failures propagate
    to the worker boundary, whose supervisor tears down the entire group.
    """
    owned = executable_fd is None
    fd = trusted_executable(arguments[0]) if owned else executable_fd
    if not IN_WORKER:
        subreaper()
    process = None
    streams = [bytearray(), bytearray()]
    end = time.monotonic() + timeout
    try:
        process = spawn(arguments, fd, pass_fds=pass_fds, group=not IN_WORKER)
        with selectors.DefaultSelector() as selector:
            for index, pipe in enumerate((process.stdout, process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
            while selector.get_map() or process.poll() is None:
                if time.monotonic() >= end:
                    raise UnsafeInput("producer deadline exceeded")
                for key, _ in selector.select(min(0.05, max(0, end - time.monotonic()))):
                    data = os.read(key.fd, min(4096, cap + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        if sum(map(len, streams)) + len(data) > cap:
                            raise UnsafeInput("producer output limit exceeded")
                        streams[key.data].extend(data)
        result = subprocess.CompletedProcess(arguments, process.returncode,
                                             streams[0].decode("utf-8", "strict"),
                                             streams[1].decode("utf-8", "strict"))
        if process.returncode:
            # Never reflect arbitrary stderr/credentials into an exception/UI.
            raise subprocess.CalledProcessError(process.returncode, arguments[0])
        return result
    finally:
        if process is not None:
            if IN_WORKER:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=1)
            else:
                cleanup_group(process)
            process.stdout.close()
            process.stderr.close()
        if owned:
            os.close(fd)


def write_bounded(fd, data, timeout=1):
    end = time.monotonic() + timeout
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        while data:
            if time.monotonic() >= end:
                raise UnsafeInput("consumer write deadline exceeded")
            if selector.select(min(0.05, end - time.monotonic())):
                try:
                    data = data[os.write(fd, data):]
                except BlockingIOError:
                    pass


def supervise(kind, arguments, expected_parent=None):
    if kind not in {"backend", "obs"} or len(arguments) > 6 or any(len(x) > 128 for x in arguments):
        raise UnsafeInput("invalid helper invocation")
    streaming = kind == "obs" and arguments == ["serve"]
    subreaper()
    cancelled = [False]
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda *_: cancelled.__setitem__(0, True))
    parent = os.getppid() if expected_parent is None else expected_parent
    fd = trusted_executable(PYTHON)
    process = None
    started = time.monotonic()
    deadline = started + (REQUEST_SECONDS if streaming else BACKEND_SECONDS)
    pending = streaming
    partial_deadline = None
    incoming = bytearray()
    output = bytearray()
    total = 0
    errors = 0
    try:
        process = spawn([PYTHON, "-I", "-S", "-B", str(ROOT / "runtime_guard.py"),
                         "--worker", kind, *arguments], fd,
                        stdin=subprocess.PIPE if streaming else subprocess.DEVNULL)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "out")
            selector.register(process.stderr, selectors.EVENT_READ, "err")
            if streaming:
                selector.register(sys.stdin.fileno(), selectors.EVENT_READ, "in")
            while True:
                now = time.monotonic()
                if cancelled[0] or os.getppid() != parent:
                    return 1
                if (now - started > 4 * 3600 or (deadline is not None and now > deadline) or
                        (partial_deadline is not None and now > partial_deadline)):
                    raise UnsafeInput("helper request deadline exceeded")
                for key, _ in selector.select(0.05):
                    data = os.read(key.fd, 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        if key.data == "in":
                            return 0
                        continue
                    if key.data == "err":
                        errors += len(data)
                        if errors > 4096:
                            raise UnsafeInput("helper error output limit exceeded")
                        # Worker errors are deliberately not forwarded verbatim.
                    elif key.data == "in":
                        if not incoming:
                            partial_deadline = now + REQUEST_SECONDS
                        incoming.extend(data)
                        if len(incoming) > MAX_REQUEST:
                            raise UnsafeInput("framing request byte limit exceeded")
                        if b"\n" in incoming:
                            if pending or incoming.count(b"\n") != 1 or not incoming.endswith(b"\n"):
                                raise UnsafeInput("only one framing request may be outstanding")
                            write_bounded(process.stdin.fileno(), bytes(incoming))
                            incoming.clear()
                            partial_deadline = None
                            pending = True
                            deadline = now + REQUEST_SECONDS
                    else:
                        total += len(data)
                        if total > (64 * 1024 * 1024 if streaming else MAX_OUTPUT):
                            raise UnsafeInput("helper output limit exceeded")
                        output.extend(data)
                        if len(output) > MAX_LINE:
                            raise UnsafeInput("helper line limit exceeded")
                        if streaming and b"\n" in output:
                            if not pending or output.count(b"\n") != 1 or not output.endswith(b"\n"):
                                raise UnsafeInput("unexpected framing response")
                            write_bounded(sys.stdout.fileno(), bytes(output))
                            output.clear()
                            pending = False
                            deadline = None
                if process.poll() is not None:
                    # Drain only until both output pipes close, bounded by deadline.
                    if not any(key.data in {"out", "err"} for key in selector.get_map().values()):
                        if not streaming:
                            write_bounded(sys.stdout.fileno(), bytes(output))
                        if process.returncode:
                            write_bounded(sys.stderr.fileno(), b"Camera helper rejected unsafe input or failed.\n")
                        return process.returncode
                    if deadline is None:
                        deadline = now + 1
    finally:
        if process is not None:
            cleanup_group(process)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        os.close(fd)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def guarded_launch(kind, arguments):
    """Keep the reaper alive if QProcess destroys/SIGKILLs its direct child.

    The launcher is the QML-owned PID. Its guardian notices launcher death (also
    during startup), then TERM/KILLs and reaps the worker group before exiting.
    No service or detached long-lived process is installed.
    """
    launcher = os.getpid()
    guardian = os.fork()
    if guardian == 0:
        try:
            code = supervise(kind, arguments, expected_parent=launcher)
        except (UnsafeInput, OSError, ValueError, subprocess.SubprocessError):
            try:
                os.write(2, b"Camera helper rejected unsafe input or exceeded a safety limit.\n")
            except OSError:
                pass
            code = 1
        os._exit(code)
    def stop(*_):
        try:
            os.kill(guardian, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    _, status = os.waitpid(guardian, 0)
    return os.waitstatus_to_exitcode(status)


def main():
    global IN_WORKER
    args = sys.argv[1:]
    if args and args[0] == "--worker":
        IN_WORKER = True
        kind = args[1]
        sys.argv = [kind, *args[2:]]
        if kind == "backend":
            import anker_c200_backend as helper
        elif kind == "obs":
            import obs_control as helper
        else:
            raise UnsafeInput("invalid worker")
        return helper.main()
    return guarded_launch(args[0], args[1:]) if args else 2


if __name__ == "__main__":
    sys.modules["runtime_guard"] = sys.modules[__name__]
    try:
        raise SystemExit(main())
    except (UnsafeInput, OSError, ValueError, subprocess.SubprocessError):
        # Fixed, bounded diagnostics; no producer output or credential contents.
        os.write(2, b"Camera helper rejected unsafe input or exceeded a safety limit.\n")
        raise SystemExit(1)
