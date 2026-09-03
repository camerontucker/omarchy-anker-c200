# Security

Anker C200 Controls runs as unsandboxed user code inside `omarchy-shell` and
launches two local Python helpers with the user's privileges. Review the
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
- If no user-installed controller exists, the helper compiles the pinned source
  bundled in this repository with the system `cc` executable. It writes the
  executable atomically beneath `$XDG_CACHE_HOME/anker-c200`, fingerprints the
  source to rebuild after updates, uses no shell, and obtains no remote code.
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
