"""Internal dispatch resolver to preserve patch compatibility on holon_coherence.cli."""

from __future__ import annotations

import sys
from typing import Any


def get_cli() -> Any:
    """Return holon_coherence.cli if loaded, falling back to holon_coherence.commands."""
    return sys.modules.get("holon_coherence.cli") or sys.modules.get("holon_coherence.commands")
