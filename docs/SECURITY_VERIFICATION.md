# Runtime hardening verification — 1.2.1

This fixes the runtime findings against `1552926e1b896177cd6db3a188553008777f37d8`.
It is a scoped remediation record, not a general security certification.

## Boundaries changed

| Reviewed path | Enforcement now |
| --- | --- |
| QML process collectors and lifecycle | Fixed isolated Python entry point, clean environment, `BoundedProcess.qml` raw-chunk caps, supervised requests, guardian on launcher destruction/death |
| Compiler/controller selection and build | No external controller overrides; root-owned system executable descriptors, pinned source snapshots, private builds, bounded capture, cache digest checks and sealed executable memfd |
| Settings/cache/OBS credentials | Descriptor-relative no-follow parent traversal; nonblocking regular-file checks; owner/mode/link/byte limits; strict JSON; random exclusive private publication and no-replace immutable cache objects |
| OBS framing | Absolute deadlines including drip/ping/unmatched traffic; frame/message limits; EOF handling; socket cleanup; one bounded outstanding framing request |
| Process discovery and display | Streaming scandir count/time budgets before materialization; bounded holder collections; validated UI schemas and PlainText/markup-neutralized display |

## Verification

`./tests/run` passes locally: 41 tests, Python compilation, bundled C controller
build with warnings treated as errors, Omarchy validation, QML lint, and
`git diff --check`. The test runner also exercises real Quickshell consumer
behavior when installed; that one test is skipped on CI hosts without Quickshell.

Focused adversarial tests in `tests/test_security.py` cover:

- FIFO, symlink, hard-link, unsafe-parent, mode and byte-limit rejection;
  descriptor-relative publication after a parent pathname swap; no-replace
  publication preserving existing data.
- Duplicate/deep/nonfinite/wrong-type/out-of-range JSON and credentials.
- Unterminated output floods, byte trickles, hard deadlines, descendant-held
  pipes, ignoring TERM, launcher TERM/SIGKILL, and descendant reaping.
- Ambient executable/environment overrides; immutable sealed execution after
  the cache pathname is tampered with; rejection on subsequent digest mismatch.
- OBS handshake EOF, frame floods, byte drip, invalid geometry and framing
  arguments, and authenticated loopback framing with private test credentials.
- Streaming process enumeration before allocation, malicious UI data, and a
  real QML consumer handling normal output and rejecting an unterminated flood.

An independent candidate review found that Python 3.14's `Path.iterdir()` eagerly
materialized entries before the initial guard. This was replaced with streaming
`os.scandir()`; the regression test confirms only nine entries are consumed for
an eight-entry budget. No other concrete finding was reported in that review.

Live Omarchy smoke checks confirmed current-code loading, connected hardware
readback through the sealed controller, direct-preview camera acquisition and
release on close, and no remaining helper processes. No camera preference or
OBS configuration changes were required. The previous installed plugin was
backed up before deployment.

## Limits of these checks

Native OBS was not running during the live smoke test. Authentication, discovery
and crop behavior were exercised against a controlled loopback OBS-protocol
server, not a live Zoom/Teams meeting. The root-owned OS and the user's private
plugin/cache storage remain trusted; see `SECURITY.md`. Marketplace approval
must refer to the newly published exact commit, not the superseded baseline.
