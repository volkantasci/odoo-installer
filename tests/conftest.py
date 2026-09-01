"""Shared pytest fixtures and environment normalization.

CLI tests assert on plain-text substrings of rich-rendered output, so the test
process pins a plain-text rendering environment *before* app modules are imported:

- typer 0.27+ forces terminal mode when `GITHUB_ACTIONS`, `FORCE_COLOR` or
  `PY_COLORS` is set (`rich_utils.FORCE_TERMINAL`), and rich 15 then picks a color
  system from `TERM`/`COLORTERM` — `NO_COLOR` is not consulted on that path.
- With colors on, option names like `--version` are split into separately-styled
  spans (`--` + `version`), which breaks plain substring assertions.
- The app's `console.py` creates its rich `Console` at import time, so the
  environment must be normalized here (conftest imports before any test module),
  not in a fixture.

`TERM=dumb` makes rich drop colors while keeping the same text layout.
"""

from __future__ import annotations

import os

os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)
