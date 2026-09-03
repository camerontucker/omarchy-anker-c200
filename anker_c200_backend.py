#!/usr/bin/env python3
"""Persistent, validated bridge between an Omarchy widget and anker-c200."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "anker-c200" / "settings.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "anker-c200"
CACHE_CONTROL = CACHE / "bin" / "anker-c200"
CACHE_STAMP = CACHE / "controller-source.sha256"
VENDOR = ROOT / "vendor" / "anker-powerconf-c200-linux-tools"
CONTROLLER_SOURCES = (
    VENDOR / "src" / "c200_fov.c",
    VENDOR / "src" / "c200_vendor.c",
    VENDOR / "src" / "c200_controls.c",
    VENDOR / "src" / "c200_fov_cli.c",
)
CONTROLLER_HEADERS = tuple(sorted((VENDOR / "src").glob("*.h")))
CONTROL = Path(shutil.which("anker-c200") or HOME / ".local" / "bin" / "anker-c200")
CONTROLLER_SETUP_ERROR = ""
V4L2_CONTROL = shutil.which("v4l2-ctl")
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
    matches = sorted(DEVICE_GLOB.glob("usb-Anker_PowerConf_C200*-video-index0"))
    return matches[0] if matches else None


def process_running(command: str) -> bool:
    """Check /proc directly so preview selection needs no extra utility."""
    try:
        processes = Path("/proc").iterdir()
    except OSError:
        return False
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() == command:
                return True
        except OSError:
            continue
    return False


def controller_available() -> bool:
    return CONTROL.is_file() and os.access(CONTROL, os.X_OK)


def controller_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(b"-O2 -Wall -Wextra -Werror -std=c11\0")
    for path in (*CONTROLLER_SOURCES, *CONTROLLER_HEADERS):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def external_controller() -> Path | None:
    """Prefer a controller the user deliberately installed."""
    discovered = shutil.which("anker-c200")
    candidates = [Path(discovered)] if discovered else []
    candidates.append(HOME / ".local" / "bin" / "anker-c200")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def ensure_controller() -> bool:
    """Build the pinned, bundled controller locally when none is installed."""
    global CONTROL, CONTROLLER_SETUP_ERROR

    CONTROLLER_SETUP_ERROR = ""
    installed = external_controller()
    if installed is not None:
        CONTROL = installed
        return True

    try:
        fingerprint = controller_fingerprint()
        stamp = CACHE_STAMP.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        fingerprint = controller_fingerprint()
        stamp = ""
    if CACHE_CONTROL.is_file() and os.access(CACHE_CONTROL, os.X_OK) and stamp == fingerprint:
        CONTROL = CACHE_CONTROL
        return True

    compiler = shutil.which("cc")
    if not compiler:
        CONTROLLER_SETUP_ERROR = "controller setup needs the standard Omarchy C compiler (cc)"
        return False

    temporary = CACHE_CONTROL.with_name(f".{CACHE_CONTROL.name}.{os.getpid()}.tmp")
    try:
        CACHE_CONTROL.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                compiler,
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-std=c11",
                f"-I{VENDOR / 'src'}",
                *(str(path) for path in CONTROLLER_SOURCES),
                "-o",
                str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        temporary.chmod(0o755)
        temporary.replace(CACHE_CONTROL)
        CACHE_STAMP.write_text(fingerprint + "\n", encoding="utf-8")
        CONTROL = CACHE_CONTROL
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        CONTROLLER_SETUP_ERROR = f"could not build bundled controller: {detail.strip()[:240]}"
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def control_value(name: str, raw: str):
    """Parse the human-readable value emitted by anker-c200 get."""
    value = raw.strip()
    if name == "fov":
        match = re.search(r"\b(narrow|medium|wide)\b", value.lower())
        if match:
            return match.group(1)
        presets = {"65": "narrow", "78": "medium", "95": "wide"}
        return presets.get(value.split(maxsplit=1)[0], value)
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
    return int(match.group(0))


def read_one(name: str, camera: Path):
    if not controller_available():
        raise FileNotFoundError(f"missing controller: {CONTROL}")
    result = subprocess.run(
        [str(CONTROL), "--device", str(camera), "get", name],
        check=True,
        capture_output=True,
        text=True,
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
            errors[name] = str(exc)
    return actual, errors


def driver_defaults(camera: Path) -> dict:
    """Return defaults that the V4L2 driver explicitly reports."""
    if not V4L2_CONTROL:
        return {}
    try:
        result = subprocess.run(
            [V4L2_CONTROL, "--device", str(camera), "--list-ctrls"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except subprocess.SubprocessError:
        return {}
    defaults = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_]+).*\bdefault=(-?\d+)\b", line)
        if not match or match.group(1) not in DEFAULTS:
            continue
        name, value = match.group(1), int(match.group(2))
        defaults[name] = bool(value) if name in BOOLS else value
    return defaults


def camera_holders(camera: Path) -> list[dict]:
    """Find unexpected same-user processes holding the physical capture node."""
    try:
        target = str(camera.resolve(strict=True))
        processes = Path("/proc").iterdir()
    except OSError:
        return []
    holders = []
    seen = set()
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            name = (process / "comm").read_text().strip()
            links = (process / "fd").iterdir()
        except OSError:
            continue
        if name in {"obs", "quickshell"}:
            continue
        for link in links:
            try:
                held = os.readlink(link)
            except OSError:
                continue
            if held == target and (name, process.name) not in seen:
                holders.append({"name": name, "pid": int(process.name)})
                seen.add((name, process.name))
                break
    return sorted(holders, key=lambda holder: (holder["name"], holder["pid"]))


def load() -> dict:
    values = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG.read_text())
        values.update({name: value for name, value in saved.items() if name in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return values


def save(values: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2) + "\n")
    temporary.replace(CONFIG)


def normalized(name: str, raw: str):
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
    subprocess.run(
        [str(CONTROL), "--device", str(camera), "set", name, wire(value)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
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
            failures.append(str(exc))
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
    ensure_controller()
    camera = device()

    if command == "state":
        print(json.dumps(status(), separators=(",", ":")))
        return 0

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
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
