# Repository Working Agreements

- Keep the repository root directly installable with `omarchy plugin add`.
- Preserve the permanent plugin ID `io.github.camerontucker.anker-c200`.
- Use only Python's standard library; the optional camera controller is an
  external executable and must remain optional.
- Keep preview capture inactive while the panel is closed.
- Never open the physical camera while an `obs` process is running; use the OBS
  Virtual Camera in that state to avoid device contention.
- Keep OBS WebSocket traffic on loopback and never log its password.
- Validate with `./tests/run` before release.
