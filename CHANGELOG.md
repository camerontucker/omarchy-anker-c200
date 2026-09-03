# Changelog

## 1.2.0 — 2026-09-03

- Show the C200's live chosen temperature while auto white balance is enabled,
  exclude that inactive manual control from profile drift, and restore the
  saved manual temperature when auto mode is disabled.
- Make auto white balance and continuous autofocus switches invert their
  caller-owned value correctly and block repeat clicks during verified writes.
- Keep one panel-scoped OBS WebSocket connection for framing and coalesce drag
  updates at near-frame cadence instead of launching a process per pointer step.
- Bundle the pinned MIT-licensed Anker controller source and build it locally
  into the user cache on first use, eliminating the separate controller install.
- Remove the unreliable HDR toggle and exclude legacy HDR preferences from
  profile application and drift reporting.
- Move hardware zoom directly below the preview, keep released values stable
  while hardware readback catches up, and reserve the mouse wheel for panel
  scrolling instead of changing hovered sliders.
- Keep drag gestures captured by the preview instead of letting the scroll pane
  steal them, and map a full preview gesture to the entire available OBS crop.
- Add explicit upstream acknowledgements and third-party license notices for
  Omarchy, anker-powerconf-c200-linux-tools, Quickshell, and OBS Studio.
- Read every supported control back from the camera instead of presenting
  saved preferences as live hardware state.
- Verify writes, expose profile drift, and reapply the saved meeting profile
  once after OBS takes ownership of the camera.
- Report unexpected processes holding the physical camera.
- Show direct/OBS preview mode, input and output resolution, frame rate,
  virtual-camera state, and exact OBS crop values.
- Add per-control reset actions for defaults reported by the V4L2 driver.
- Add middle-click refresh, right-click profile apply, and a Start OBS action.
- Destroy the Qt capture session when the panel closes so the camera device is
  released immediately.
- Add marketplace artwork, CI, QML runtime checks, and expanded release tests.

## 1.1.0 — 2026-09-03

- Add a lightweight live preview of the OBS Virtual Camera.
- Fall back to a direct Anker C200 preview when OBS is not running.
- Add live drag-to-reframe and one-click centring for an existing OBS crop.
- Keep the preview inactive while the panel is closed.
- Expose the correct implicit bar-widget dimensions so the camera icon is
  visible in Omarchy's bar.
- Detect a missing optional controller and degrade safely to preview-only mode.
- Read the OBS WebSocket port from its local configuration and keep all OBS
  traffic on loopback.

## 1.0.0 — 2026-09-03

- Add persistent Anker PowerConf C200 controls for FOV, HDR, image tuning,
  autofocus, and hardware zoom.
- Add camera reconnect handling and automatic setting reapplication.
