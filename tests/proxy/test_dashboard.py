"""Unit tests for telemetry dashboard rendering."""

from __future__ import annotations

from holon_coherence.proxy.dashboard import render_dashboard_html


def test_render_dashboard_html() -> None:
    html = render_dashboard_html()
    assert "<!DOCTYPE html>" in html
    assert "Holon Coherence" in html
    assert "/holon/api/metrics" in html
    assert "tool-calls-pruned" in html
    assert "tokens-reduced" in html
    assert "cache-hit-rate" in html
