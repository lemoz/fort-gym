from __future__ import annotations

import inspect
from pathlib import Path


def test_landing_page_exists_with_lab_positioning() -> None:
    html = Path("web/landing.html").read_text(encoding="utf-8")

    assert "environment lab" in html
    assert "instruments" in html
    # every capability card carries a gate-backed claim and an evidence link
    for tag in (
        "SPATIAL REASONING",
        "LONG-HORIZON PLANNING",
        "INCENTIVE ROBUSTNESS",
        "MEMORY UTILITY",
        "GENERALIZATION",
        "RELIABILITY",
    ):
        assert tag in html
    # evidence links: real replay tokens and repo docs, never fabricated stats
    assert 'href="/r/qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH"' in html
    assert "docs/WDSLL.md" in html
    assert 'href="/live"' in html
    # honesty footer: claims are auditable
    assert "backed by a" in html and "public run" in html


def test_root_serves_landing_and_live_serves_viewer() -> None:
    from fort_gym.bench.api import server

    assert 'return _html_file_response("landing.html")' in inspect.getsource(
        server.serve_landing
    )
    assert 'return _html_file_response("index.html")' in inspect.getsource(
        server.serve_index
    )
    # evidence permalinks unchanged
    assert 'return _html_file_response("index.html")' in inspect.getsource(
        server.serve_short_visual_replay
    )


def test_run_shares_are_permanent_evidence() -> None:
    """Public benchmark runs are citable evidence: their auto-created share
    tokens must never expire (WDSLL replay links rotted after 24h before
    this)."""
    from fort_gym.bench.api import server

    source = inspect.getsource(server.create_run)
    assert "ttl_seconds=None" in source
