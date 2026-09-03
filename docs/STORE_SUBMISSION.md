# Omarchy marketplace submission draft

This draft follows the marketplace's current
[submission guide](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md).
Do not create the issue until the repository is public at the URL below, the
owner reviews the final commit, confirms all five checklist statements, and
explicitly approves this title and body.

The checked boxes inside the issue-body template are the exact final format
required by the marketplace. They are not an ownership or publication
attestation until the owner completes the unchecked preflight items below.

## Issue title

```text
[Plugin]: Anker C200 Controls
```

## Issue body

```markdown
### Repository URL

https://github.com/camerontucker/omarchy-anker-c200

### Category

Hardware

### Tags

bar, quickshell, system

### Suggest a missing tag

webcam

### Maintainer notes

Anker C200 Controls puts a low-overhead camera preview and the Anker PowerConf C200's useful vendor and image controls in the Omarchy bar. It reads settings back from the hardware, verifies writes, reports saved-profile drift and unexpected camera owners, and offers camera-reported resets where available. When OBS is absent, the panel previews the physical camera directly. When OBS is running, it automatically previews the OBS Virtual Camera, shows the negotiated format and exact crop, and lets the user smoothly drag the shot beneath that crop or centre it without changing the output resolution. Framing uses one panel-scoped OBS connection with coalesced pointer updates rather than launching a helper for every movement.

The plugin requires Omarchy Quattro and an Anker PowerConf C200. Its preview uses the standard Qt Multimedia runtime and has no third-party Python dependencies. On first use it compiles a pinned, unmodified copy of the MIT-licensed anker-powerconf-c200-linux-tools source with Omarchy's system C compiler and caches the resulting controller beneath XDG_CACHE_HOME. It does not fetch build input or invoke a package manager; if compilation is unavailable it degrades to preview-only mode. OBS integration is optional, connects only to 127.0.0.1, and changes only the current scene's Anker/PowerConf crop after a direct user gesture.

Upstream roles, acknowledgements, and licenses for Omarchy, anker-powerconf-c200-linux-tools, Quickshell, and OBS Studio are documented in the root README and THIRD_PARTY_NOTICES.md. The pinned controller source and its MIT license are bundled; no third-party binary or library is bundled.

The plugin does not invoke a package manager, create services, modify OBS settings, request privilege escalation, or download and execute code. Its only first-run setup is compiling the bundled controller source into the user's cache. It has no telemetry or non-loopback network access. Capture is active only while the panel is open, and the camera object is destroyed when the panel closes.

### Submission checklist

- [x] The repository is public and contains installation and removal instructions.
- [x] I have documented the plugin license and any external dependencies.
- [x] I confirm that I own or have permission to submit this plugin and its preview assets.
- [x] The plugin does not overwrite user configuration without explicit consent.
- [x] I understand that approval is for listing and is not a security review.
```

After final approval, copy only the issue-body code block to a temporary file
and create the issue:

```bash
gh issue create \
  --repo omacom/omarchy-plugin-marketplace \
  --title "[Plugin]: Anker C200 Controls" \
  --body-file /tmp/omarchy-plugin-submission.md
```

## Final storefront preflight

- [x] Re-read the current official CLI/AI submission guide and preserve its six
  headings, category spelling, tags, and exact checklist text (2026-09-03).
- [x] Validate the source and installed plugin with `omarchy plugin validate`.
- [x] Run unit tests, Python compilation, and local QML lint against the Omarchy
  shell imports.
- [ ] Publish the repository at the exact root URL in the draft.
- [x] Add an authentic, privacy-safe root `preview.png` under 50 MB and 40
  megapixels, using the real plugin UI with a synthetic OBS meeting scene.
- [x] Add a second sanitized framing screenshot and document preview-asset
  provenance and redistribution.
- [x] Confirm README install, update, and removal commands match the final ID.
- [x] Credit the host platform, controller, shell runtime, and OBS integration;
  include the upstream MIT notice for the adapted Omarchy slider.
- [x] Pin and vendor the controller source and license; disclose its local
  first-run build in the README, security boundary, and submission notes.
- [x] Confirm `manifest.json`, `CHANGELOG.md`, and release tests carry version
  `1.2.0` and plugin ID `io.github.camerontucker.anker-c200`.
- [ ] Run `./tests/run` from a fresh clone of the final commit.
- [x] Confirm the permanent plugin ID is still absent from the marketplace
  registry (checked 2026-09-03).
- [ ] Review every checklist statement and approve the exact title and body
  before creating the submission issue.
