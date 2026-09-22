"""Per-agent operations routers, one module per agent-page tab.

Included before api/routers/registry.py so a path defined here takes
precedence over an older definition of the same path there."""
import importlib
import logging
import os

_MODULES = ["overview", "diagram", "governance", "tokenomics", "economics", "risk", "jobs", "integrate"]

# Parallel development: AR_TOLERANT_ROUTER_IMPORT=1 lets a dev server start
# while another module is mid-edit. Never set in production.
_tolerant = os.environ.get("AR_TOLERANT_ROUTER_IMPORT") == "1"

ROUTERS = []
for _name in _MODULES:
    try:
        ROUTERS.append(importlib.import_module(f"api.routers.ops.{_name}").router)
    except Exception:
        if not _tolerant:
            raise
        logging.getLogger(__name__).exception("ops router %s failed to import", _name)
