# Vendored upstream

- Project: [anker-powerconf-c200-linux-tools](https://github.com/erans/anker-powerconf-c200-linux-tools)
- Author: Eran Sandler
- License: MIT (see `LICENSE` in this directory)
- Commit: `1912f8690802346557f6bc1d1024e31dec1c7273`
- Vendored files: the four CLI source files and three headers under `src/`

These files are copied without modification. The plugin compiles them locally
with the system C compiler on first use and stores only the resulting executable
under `$XDG_CACHE_HOME/anker-c200`.
