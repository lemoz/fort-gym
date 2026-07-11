from __future__ import annotations

import inspect
from pathlib import Path


def test_landing_page_is_results_first_fort_eval_surface() -> None:
    html = Path("web/landing.html").read_text(encoding="utf-8")

    assert "<span>FORT</span> LABS" in html
    assert "FORT-EVAL" in html
    assert "Can an AI build a civilization that" in html
    assert 'id="hero-canvas"' in html
    assert "Source: recorded DF CopyScreen" in html
    assert "Results belong to protocols" in html
    assert "Easy" in html and "Hard" in html and "Discovery" in html
    assert "Observer Map" in html
    assert "Observer view / derived evidence" in html
    assert "never silently passed to evaluated models" in html
    assert "No frozen Fort-Eval cohort has been published yet" in html
    assert "'/public/overview'" in html
    assert "/preview" in html
    assert "/export/trace" not in html
    assert 'href="/live"' in html
    assert "Failures receive the same permanent replay" in html


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
