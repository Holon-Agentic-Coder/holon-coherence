from __future__ import annotations

import re
from importlib import resources

from holon_coherence.proxy.dashboard import render_dashboard_html


def test_render_dashboard_html() -> None:
    html = render_dashboard_html()
    assert "<!DOCTYPE html>" in html
    assert '<html lang="en">' in html
    assert "<style>" in html
    assert "<script>" in html
    assert "</html>" in html
    assert "Holon Coherence" in html
    assert "/holon/api/metrics" in html
    assert "tool-calls-pruned" in html
    assert "tokens-reduced" in html
    assert "cache-hit-rate" in html


def test_render_dashboard_html_loads_package_resource() -> None:
    resource = resources.files("holon_coherence.proxy").joinpath("dashboard.html")
    assert resource.is_file()
    assert render_dashboard_html() == resource.read_text(encoding="utf-8")


def test_dashboard_html_has_no_inline_comments() -> None:
    html = render_dashboard_html()
    assert "<!--" not in html
    assert "-->" not in html
    assert "/*" not in html
    assert "*/" not in html
    assert re.search(r"(?m)^\s*//", html) is None
