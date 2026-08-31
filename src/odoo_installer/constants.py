"""Static constants for odoo-installer.

Everything user-configurable lives in :mod:`odoo_installer.config` (M1); this module
holds only values that are fixed by the approved decisions in DEVELOPMENT.md.
"""

from __future__ import annotations

APP_NAME = "odoo-installer"

# Approved decision D2: Odoo 19.0 only.
ODOO_VERSION = "19.0"
DEFAULT_ODOO_IMAGE = f"odoo:{ODOO_VERSION}"
DEFAULT_PG_TAG = 17

# Approved decision D1: Docker only.
DEFAULT_HTTP_PORT = 8069
PORT_ALLOCATION_START = 8069
PORT_ALLOCATION_END = 8099  # inclusive; first free port in this range wins

# Alternate http port used for --stop-after-init runs (install/upgrade/test) inside the
# web container, so it never clashes with the serving process on 8069.
RUNNER_HTTP_PORT = 8071

# Scratch databases created by `test module` / `test suite` always use this prefix and
# are dropped after the run (DEVELOPMENT.md §7).
SCRATCH_DB_PREFIX = "oitest"
