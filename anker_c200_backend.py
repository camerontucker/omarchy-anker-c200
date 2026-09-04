#!/usr/bin/python3 -I
"""Persistent, validated bridge between an Omarchy widget and anker-c200."""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import time
import subprocess
import sys
from pathlib import Path
if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from secure_io import UnsafeInput, directory, locked_directory, open_regular, read_fd, read_file, json_object, publish, write_file
from runtime_guard import run_bounded, sealed_executable

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "anker-c200" / "settings.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "anker-c200"
CACHE_STAMP = CACHE / "controller-v2.json"
VENDOR = ROOT / "vendor" / "anker-powerconf-c200-linux-tools"
CONTROLLER_SOURCES = (
    VENDOR / "src" / "c200_fov.c",
    VENDOR / "src" / "c200_vendor.c",
    VENDOR / "src" / "c200_controls.c",
    VENDOR / "src" / "c200_fov_cli.c",
)
SOURCE_HASHES = {
    "c200_controls.c": "9a9f9a1755e2dcc461a0255ce0e3133ba89638778750ccf8202be5c33dc05125",
    "c200_controls.h": "7ba9c62f6e2159c0800f22cfed2692e7934d887bad7d9bd9288a4f594ca595f7",
    "c200_fov.c": "9562b69ca3ef9c39be902681cf24b54445ee88b8e5d018e2f62f5190118df511",
    "c200_fov.h": "3a4b36db87ebaf690032ade23899eec1af97430fa2c1dcca07c556bdce1770ae",
    "c200_fov_cli.c": "d37ea648f86bec1e017a5f3fb14c4321ee22419059a7d512db1c7e44b7d6801e",
    "c200_vendor.c": "d1ccd0ca987c694599fa5af07be51a8dac24da361290d29d6a578fbb474f4788",
    "c200_vendor.h": "3f7a0db17f1ac68bb2e20bde5e476d8f30cf2410011aed11de615c08f3a7ac09",
}
CONTROL = "sealed bundled controller"
CONTROL_FD = None
CONTROLLER_SETUP_ERROR = ""
V4L2_CONTROL = "/usr/bin/v4l2-ctl"
DEVICE_GLOB = Path("/dev/v4l/by-id")

DEFAULTS = {
    "fov": "narrow",
    "horizontal_flip": False,
    "brightness": 50,
    "contrast": 50,
    "saturation": 54,
    "white_balance_automatic": False,
    "white_balance_temperature": 5500,
    "gamma": 400,
    "power_line_frequency": 2,
    "sharpness": 42,
    "focus_automatic_continuous": True,
    "zoom_absolute": 122,
}

RANGES = {
    "brightness": (0, 100),
    "contrast": (0, 100),
    "saturation": (0, 100),
    "white_balance_temperature": (2300, 6500),
    "gamma": (0, 800),
    "power_line_frequency": (0, 2),
    "sharpness": (0, 100),
    "zoom_absolute": (100, 400),
}
BOOLS = {"horizontal_flip", "white_balance_automatic", "focus_automatic_continuous"}


def device() -> Path | None:
    if not DEVICE_GLOB.exists():
        return None
    matches = [path for path in scan_entries(DEVICE_GLOB, 128)
               if path.name.startswith("usb-Anker_PowerConf_C200") and path.name.endswith("-video-index0")]
    matches.sort()
    return matches[0] if matches else None


def bounded_entries(entries, maximum, seconds=0.2):
    end = time.monotonic() + seconds
    count = 0
    iterator = iter(entries)
    while True:
        try:
            entry = next(iterator)
        except (StopIteration, FileNotFoundError, ProcessLookupError, PermissionError):
            return
        count += 1
        if count > maximum or time.monotonic() > end:
            raise UnsafeInput("process or device enumeration limit exceeded")
        yield entry


def process_name(process):
    fd = os.open(process / "comm", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        return read_fd(fd, 64).decode("utf-8", "replace").strip()
    finally:
        os.close(fd)


def scan_entries(path, maximum, seconds=0.2):
    # Path.iterdir()/glob may eagerly materialize scandir on newer Python.
    try:
        with os.scandir(path) as entries:
            for entry in bounded_entries(entries, maximum, seconds):
                yield Path(entry.path)
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return


def process_running(command: str) -> bool:
    """Check /proc directly so preview selection needs no extra utility."""
    try:
        processes = scan_entries("/proc", 8192)
    except OSError:
        return False
    for process in bounded_entries(processes, 8192):
        if not process.name.isdigit():
            continue
        try:
            if process_name(process) == command:
                return True
        except OSError:
            continue
    return False


def controller_available() -> bool:
    return CONTROL_FD is not None


def controller_sources():
    sources = {}
    for name, expected in SOURCE_HASHES.items():
        data = read_file(VENDOR / "src" / name, 262144)
        if hashlib.sha256(data).hexdigest() != expected:
            raise UnsafeInput("bundled controller source digest mismatch")
        sources[name] = data
    return sources


def controller_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(b"-O2 -Wall -Wextra -Werror -std=c11\0")
    for name, data in sorted(controller_sources().items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def ensure_controller() -> bool:
    """Only pinned sources, private cache, digest verification and sealed execution."""
    global CONTROL_FD, CONTROLLER_SETUP_ERROR
    if CONTROL_FD is not None:
        return True
    CONTROLLER_SETUP_ERROR = ""
    try:
        sources = controller_sources()
        fingerprint = controller_fingerprint()
        with locked_directory(CACHE) as parent:
            try:
                stamp_fd = open_regular(parent, CACHE_STAMP.name, 512, secret=True)
            except FileNotFoundError:
                stamp = {}
            else:
                try:
                    stamp = json_object(read_fd(stamp_fd, 512), 512)
                finally:
                    os.close(stamp_fd)
                if set(stamp) != {"source", "binary"} or any(
                    type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value)
                    for value in stamp.values()
                ):
                    raise UnsafeInput("invalid controller cache metadata")
            if stamp.get("source") == fingerprint:
                binary_fd = open_regular(parent, "controller-" + stamp["binary"], 2 * 1024 * 1024, secret=True)
                try:
                    data = read_fd(binary_fd, 2 * 1024 * 1024)
                finally:
                    os.close(binary_fd)
                if hashlib.sha256(data).hexdigest() != stamp["binary"]:
                    raise UnsafeInput("controller artifact digest mismatch")
            else:
                build_name = ".build-" + secrets.token_hex(16)
                os.mkdir(build_name, 0o700, dir_fd=parent)
                build = os.open(build_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    for name, content in sources.items():
                        publish(build, name, content, replace=False)
                    prefix = f"/proc/self/fd/{build}"
                    run_bounded(["/usr/bin/cc", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c11",
                                 f"-I{prefix}", *(f"{prefix}/{path.name}" for path in CONTROLLER_SOURCES),
                                 "-o", f"{prefix}/controller"], timeout=30, cap=16384, pass_fds=(build,))
                    binary_fd = open_regular(build, "controller", 2 * 1024 * 1024)
                    try:
                        data = read_fd(binary_fd, 2 * 1024 * 1024)
                    finally:
                        os.close(binary_fd)
                    digest = hashlib.sha256(data).hexdigest()
                    try:
                        publish(parent, "controller-" + digest, data, replace=False)
                    except FileExistsError:
                        existing = open_regular(parent, "controller-" + digest, 2 * 1024 * 1024, secret=True)
                        try:
                            if read_fd(existing, 2 * 1024 * 1024) != data:
                                raise UnsafeInput("controller cache collision")
                        finally:
                            os.close(existing)
                    publish(parent, CACHE_STAMP.name, json.dumps({"source": fingerprint, "binary": digest}).encode())
                finally:
                    for name in (*sources, "controller"):
                        try:
                            os.unlink(name, dir_fd=build)
                        except FileNotFoundError:
                            pass
                    os.close(build)
                    os.rmdir(build_name, dir_fd=parent)
            CONTROL_FD = sealed_executable(data)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        CONTROLLER_SETUP_ERROR = "bundled controller unavailable; check private cache and system compiler"
        return False


def control_value(name: str, raw: str):
    """Parse the human-readable value emitted by anker-c200 get."""
    if type(raw) is not str or len(raw) > 128:
        raise UnsafeInput("invalid control readback length")
    value = raw.strip()
    if name == "fov":
        match = re.search(r"\b(narrow|medium|wide)\b", value.lower())
        if match:
            return normalized(name, match.group(1))
        presets = {"65": "narrow", "78": "medium", "95": "wide"}
        return normalized(name, presets.get(value.split(maxsplit=1)[0], value))
    if name in BOOLS:
        lowered = value.lower()
        if lowered in {"on", "true", "1"}:
            return True
        if lowered in {"off", "false", "0"}:
            return False
        raise ValueError(f"unexpected {name} readback: {value}")
    match = re.match(r"^-?\d+", value)
    if not match:
        raise ValueError(f"unexpected {name} readback: {value}")
    return normalized(name, match.group(0))


def read_one(name: str, camera: Path):
    if not controller_available():
        raise FileNotFoundError(f"missing controller: {CONTROL}")
    result = run_bounded(
        [str(CONTROL), "--device", str(camera), "get", name],
        executable_fd=CONTROL_FD,
        timeout=2,
    )
    return control_value(name, result.stdout)


def read_actual(camera: Path) -> tuple[dict, dict]:
    actual = {}
    errors = {}
    if not controller_available():
        return actual, errors
    for name in DEFAULTS:
        try:
            actual[name] = read_one(name, camera)
        except (FileNotFoundError, ValueError, subprocess.SubprocessError) as exc:
            errors[name] = "control readback unavailable"
    return actual, errors


def driver_defaults(camera: Path) -> dict:
    """Return defaults that the V4L2 driver explicitly reports."""
    if not V4L2_CONTROL:
        return {}
    try:
        result = run_bounded(
            [V4L2_CONTROL, "--device", str(camera), "--list-ctrls"],
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    defaults = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_]+).*\bdefault=(-?\d+)\b", line)
        if not match or match.group(1) not in DEFAULTS:
            continue
        name, value = match.group(1), int(match.group(2))
        try:
            defaults[name] = normalized(name, str(value))
        except ValueError:
            continue
    return defaults


def camera_holders(camera: Path) -> list[dict]:
    """Find unexpected same-user processes holding the physical capture node."""
    try:
        target = str(camera.resolve(strict=True))
        processes = scan_entries("/proc", 8192, 0.3)
    except OSError:
        return []
    holders = []
    seen = set()
    end = time.monotonic() + 0.3
    fd_count = 0
    for process in bounded_entries(processes, 8192, 0.3):
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            name = process_name(process)
            links = scan_entries(process / "fd", 4096)
        except OSError:
            continue
        if name in {"obs", "quickshell"}:
            continue
        for link in bounded_entries(links, 4096):
            fd_count += 1
            if fd_count > 32768 or time.monotonic() > end:
                raise UnsafeInput("camera holder enumeration limit exceeded")
            try:
                held = os.readlink(link)
                if len(held) > 4096:
                    raise UnsafeInput("process link limit exceeded")
            except OSError:
                continue
            if held == target and (name, process.name) not in seen:
                holders.append({"name": name, "pid": int(process.name)})
                seen.add((name, process.name))
                if len(holders) > 16:
                    raise UnsafeInput("camera holder count limit exceeded")
                break
    return sorted(holders, key=lambda holder: (holder["name"], holder["pid"]))


def load() -> dict:
    values = dict(DEFAULTS)
    try:
        saved = json_object(read_file(CONFIG))
        for name, value in saved.items():
            if name not in DEFAULTS:
                continue  # legacy/removed controls never cross the hardware boundary
            if type(value) is not type(DEFAULTS[name]):
                raise UnsafeInput("invalid saved control type")
            values[name] = normalized(name, wire(value))
    except FileNotFoundError:
        pass
    return values


def save(values: dict) -> None:
    for name, value in values.items():
        if name not in DEFAULTS or type(value) is not type(DEFAULTS[name]):
            raise UnsafeInput("invalid settings schema")
        normalized(name, wire(value))
    write_file(CONFIG, (json.dumps(values, indent=2) + "\n").encode())


def normalized(name: str, raw: str):
    if type(raw) is not str or len(raw) > 32:
        raise ValueError("invalid control value")
    if name == "fov":
        value = raw.lower()
        if value not in {"narrow", "medium", "wide"}:
            raise ValueError("fov must be narrow, medium, or wide")
        return value
    if name in BOOLS:
        value = raw.lower()
        if value not in {"on", "off", "true", "false", "1", "0"}:
            raise ValueError(f"{name} must be on or off")
        return value in {"on", "true", "1"}
    if name in RANGES:
        value = int(raw)
        low, high = RANGES[name]
        if value < low or value > high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return value
    raise ValueError(f"unsupported control: {name}")


def wire(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def apply_one(name: str, value, camera: Path) -> None:
    if not controller_available():
        raise FileNotFoundError(f"missing controller: {CONTROL}")
    run_bounded(
        [str(CONTROL), "--device", str(camera), "set", name, wire(value)],
        executable_fd=CONTROL_FD,
        timeout=2,
    )


def verify_one(name: str, expected, camera: Path) -> None:
    actual = read_one(name, camera)
    if actual != expected:
        raise ValueError(f"{name} did not stick: requested {wire(expected)}, camera reports {wire(actual)}")


def apply_change(name: str, value, camera: Path, desired: dict) -> None:
    """Apply one control and restore dependent manual state when required."""
    apply_one(name, value, camera)
    verify_one(name, value, camera)
    if name == "white_balance_automatic" and value is False:
        manual_temperature = desired["white_balance_temperature"]
        apply_one("white_balance_temperature", manual_temperature, camera)
        verify_one("white_balance_temperature", manual_temperature, camera)


def apply_profile(camera: Path) -> list[str]:
    desired = load()
    failures = []
    for name, value in desired.items():
        if name == "white_balance_temperature" and desired["white_balance_automatic"]:
            continue
        try:
            apply_one(name, value, camera)
            verify_one(name, value, camera)
        except (FileNotFoundError, ValueError, subprocess.SubprocessError) as exc:
            failures.append("could not apply " + name)
    return failures


def status() -> dict:
    ensure_controller()
    desired = load()
    camera = device()
    actual = {}
    readback_errors = {}
    defaults = {}
    holders = []
    if camera is not None:
        actual, readback_errors = read_actual(camera)
        defaults = driver_defaults(camera)
        holders = camera_holders(camera)
    values = {**desired, **actual}
    inactive = set()
    if actual.get("white_balance_automatic") is True:
        inactive.add("white_balance_temperature")
    active_errors = {name: error for name, error in readback_errors.items() if name not in inactive}
    drift = [
        name
        for name, value in actual.items()
        if name not in inactive and desired.get(name) != value
    ]
    return {
        "connected": camera is not None,
        "controller_available": controller_available(),
        "controller_path": str(CONTROL) if controller_available() else "",
        "controller_setup_error": CONTROLLER_SETUP_ERROR,
        "obs_running": process_running("obs"),
        "device": str(camera or ""),
        "readback_available": bool(actual),
        "readback_errors": readback_errors,
        "profile": desired,
        "profile_drift": drift,
        "profile_applied": bool(actual) and not drift and not active_errors,
        "driver_defaults": defaults,
        "busy_processes": holders,
        **values,
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "state"
    camera = device()

    if command == "state":
        print(json.dumps(status(), separators=(",", ":")))
        return 0

    ensure_controller()

    if command == "read" and len(sys.argv) == 3:
        name = sys.argv[2]
        if name not in DEFAULTS:
            raise ValueError(f"unsupported control: {name}")
        if camera is None:
            raise FileNotFoundError("camera disconnected")
        print(json.dumps({name: read_one(name, camera)}, separators=(",", ":")))
        return 0

    if command == "set" and len(sys.argv) == 4:
        name = sys.argv[2]
        value = normalized(name, sys.argv[3])
        values = load()
        values[name] = value
        save(values)
        if camera is None:
            print("saved; camera disconnected")
            return 0
        if not controller_available():
            print(f"saved; {CONTROLLER_SETUP_ERROR or 'controller unavailable'}", file=sys.stderr)
            return 1
        apply_change(name, value, camera, values)
        print("ok")
        return 0

    if command == "apply":
        if camera is None:
            print("camera disconnected", file=sys.stderr)
            return 1
        if not controller_available():
            print(CONTROLLER_SETUP_ERROR or "controller unavailable", file=sys.stderr)
            return 1
        failures = apply_profile(camera)
        if failures:
            print("; ".join(failures), file=sys.stderr)
            return 1
        print("ok")
        return 0

    if command == "reset" and len(sys.argv) == 3:
        name = sys.argv[2]
        if camera is None:
            print("camera disconnected", file=sys.stderr)
            return 1
        defaults = driver_defaults(camera)
        if name not in defaults:
            print(f"no driver default is reported for {name}", file=sys.stderr)
            return 1
        value = defaults[name]
        values = load()
        values[name] = value
        save(values)
        apply_one(name, value, camera)
        verify_one(name, value, camera)
        print("ok")
        return 0

    print(
        "usage: anker_c200_backend.py state | read CONTROL | set CONTROL VALUE | reset CONTROL | apply",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    from runtime_guard import guarded_launch
    raise SystemExit(guarded_launch("backend", sys.argv[1:]))
