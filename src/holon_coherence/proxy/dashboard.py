from __future__ import annotations

from importlib import resources

__all__ = ["render_dashboard_html"]


def render_dashboard_html() -> str:
    return resources.files("holon_coherence.proxy").joinpath("dashboard.html").read_text(encoding="utf-8")
