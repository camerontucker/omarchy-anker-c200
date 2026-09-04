# Security

Anker C200 Controls runs as unsandboxed user code inside `omarchy-shell` and
launches supervised local Python helpers with the user's privileges. Review the
repository before enabling it. Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/camerontucker/omarchy-anker-c200/security/advisories/new)
and avoid public disclosure until the report has been triaged.

## Supported versions

Security fixes are made against the latest release on the `main` branch.

## System interactions

- Qt Multimedia opens the OBS Virtual Camera while OBS is running, or the
  physical Anker C200 when OBS is absent. Capture is active only while the
  panel is open.
- `anker_c200_backend.py` identifies the C200 through stable entries beneath
  `/dev/v4l/by-id`, reads exact process names from `/proc/*/comm` to detect OBS,
  checks same-user `/proc/*/fd` links for unexpected physical-camera owners,
  and invokes the `anker-c200` controller as an argument array.
- Only bundled source with pinned per-file SHA-256 digests may be compiled.
  `/usr/bin/cc`, Python, and optional V4L2 tooling are bound to opened,
  root-owned system executables; ambient PATH/controller overrides are ignored.
  Subprocess environments contain only an explicit allowlist. Build inputs are
  verified snapshots in a random private directory. Cache objects are published
  without replacement, with restrictive modes and digest-checked metadata.
  The validated controller bytes are copied to a sealed memfd and executed by
  descriptor, preventing a subsequent pathname replacement from changing code.
- Camera settings are range-checked before they are saved or sent to the
  controller. Writes are read back and mismatches are reported. The helper
  does not interpolate values into a shell command.
- `obs_control.py` implements an authenticated OBS WebSocket client using only
  the Python standard library. It connects only to `127.0.0.1`, authenticates
  from OBS's local configuration, and limits requests to the current scene's
  Anker/PowerConf item transform.
- OBS integration reads scene names, video geometry, output frame rate,
  virtual-camera state, and transform geometry. It changes only that scene
  item's crop values when the user drags the preview or chooses **Center**.
  One authenticated loopback connection remains open only while the panel is
  open and OBS is running, then closes with the panel.
- The plugin does not invoke a package manager, create services, modify OBS
  settings, request elevated privileges, or download and execute code.

## Local data and privacy

Camera preferences are written atomically beneath
`$XDG_CONFIG_HOME/anker-c200`. The OBS WebSocket password is read only when a
framing request needs authentication; it is not logged, copied, or stored by
the plugin.

The plugin has no telemetry, analytics, cloud API, account integration,
clipboard access, microphone capture, screen capture, or non-loopback network
client. Video frames remain in the local Qt/OBS camera pipeline and are not
written to disk by the plugin.

## Runtime boundaries and limits

- `secure_io.py` walks parents using directory descriptors and no-follow opens.
  Mutable files are opened nonblocking, checked as single-link regular files,
  and checked for owner, permissions and size before reading. OBS credentials
  have an 8 KiB limit and require mode 0600; settings have a 16 KiB limit.
  JSON rejects duplicate keys, nonfinite values, excessive depth/cardinality,
  and invalid control types/ranges. Unsafe inputs fail closed.
- Writes use private, random, exclusive mode-0600 files, fsync and
  descriptor-relative publication under a nonblocking private lock. Atomic
  settings replacement replaces the directory entry, never follows it.
  Immutable cache publication is atomic no-replace. Existing unsafe entries
  are rejected, not repaired through symlinks.
- `runtime_guard.py` owns a worker process group, captures producer bytes under
  a live cap, applies absolute deadlines, sends TERM then KILL, and reaps direct
  and adopted descendants. A separate short-lived guardian survives destruction
  or SIGKILL of the QML-owned launcher and cleans up after parent death.
  Backend operations have a 45-second total budget (including a 30-second first
  build); individual controller calls have two seconds and 16 KiB output.
- Framing permits one outstanding request, at most 1 KiB input, a 16 KiB
  response line, and an eight-second absolute request/startup deadline.
  Partial input lines also expire. Sessions are recycled after four hours or
  64 MiB cumulative output. OBS messages are capped at 128 KiB, 64 frames per
  request, and a four-second absolute socket-operation deadline, including
  pings/unmatched replies. EOF and constructor failures close sockets.
- `BoundedProcess.qml` uses capped raw chunks, not unlimited collectors or
  delimiter buffering. `Schema.js` validates types, numbers, strings, and
  collections before UI assignment. Dynamic labels are PlainText; the host
  hero receives markup-neutralized text for compatibility with older shells.
- Process enumeration has process/fd/count and elapsed-time budgets. At most
  16 unexpected camera holders and 64-character process names reach the UI.
- The explicit **Start OBS** action launches `/usr/bin/obs` with a clean desktop
  environment. OBS is a user application, not an owned helper, and intentionally
  remains open when this plugin closes.

The installed plugin code, root-owned system software, kernel, and the user's
private storage are the trust base. This is not isolation from another process
already able to rewrite this user's plugin or private cache and metadata.
The plugin rejects untrusted path redirection and malformed external inputs;
it cannot sandbox the whole unsandboxed Omarchy host or defend against root.
