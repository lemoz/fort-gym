from __future__ import annotations

import inspect
from pathlib import Path


def test_landing_page_is_gameplay_first_fort_labs_surface() -> None:
    html = Path("web/landing.html").read_text(encoding="utf-8")

    assert "<span>FORT</span> LABS" in html
    assert "Fort-Eval" in html
    assert "/static/fort-labs.css" in html
    assert "/static/fort-labs.js" in html
    assert "Worlds on record" in html
    assert "Can an AI build a civilization that" in html
    assert "Dwarf Fortress gives long-horizon agents a living world" in html
    assert "See what each model builds when the world keeps moving" in html
    assert "Every published result opens into its replay evidence" in html
    assert "The next great benchmark is a world" in html
    assert "Easy" in html and "Hard" in html and "Discovery" in html
    assert "Spectator view · the agent plays from its declared interface" in html
    assert "The first experimental cohort is being assembled" in html
    assert "/public/worlds?limit=24" in html
    assert "/public/overview?recent_limit=24" in html
    assert "FL.loadRunFrame" in html
    assert "/export/trace" not in html
    assert 'href="/worlds"' in html
    assert 'href="/results"' in html
    assert 'href="/protocols"' in html
    assert 'href="/findings"' in html
    assert "Results belong to protocols" not in html
    assert "A run is a trace, not a claim" not in html


def test_worlds_page_uses_real_public_run_evidence() -> None:
    html = Path("web/worlds.html").read_text(encoding="utf-8")

    assert "Every world leaves a trace" in html
    assert "Browse the fortresses agents built" in html
    assert "/public/worlds" in html
    assert "FL.loadRunFrame" in html
    assert "IntersectionObserver" in html
    assert "No recorded worlds match these filters" in html
    assert "Open run" in html


def test_shared_fort_labs_assets_define_truthful_media_states() -> None:
    css = Path("web/static/fort-labs.css").read_text(encoding="utf-8")
    js = Path("web/static/fort-labs.js").read_text(encoding="utf-8")

    assert "--acid: #d9f45b" in css
    assert "--cyan: #68d9d0" in css
    assert "44px" in css
    assert "function renderScreenText" in js
    assert "function renderScreenTiles" in js
    assert "function renderUnavailable" in js
    assert "No frame was recorded for this moment" in js
    assert "/preview" in js
    assert "/screenshot" not in js
    assert "/export/trace" not in js
    assert "aria-hidden" in js
    assert "button.focus()" in js


def test_results_page_uses_protocol_scoped_data_without_embedded_cohort_rows() -> None:
    html = Path("web/results.html").read_text(encoding="utf-8")

    assert "See what each model builds when the world keeps moving" in html
    assert "/public/results?evaluation_protocol=fort-eval-easy-p1-g7-v3" in html
    assert "payload.comparison_groups" in html
    assert "P1 fixed seed" in html
    assert "row.public_label || row.model" in html
    assert "row.task_verdict" in html
    assert "/public/leaderboard" not in html
    assert "/public/worlds?limit=3" not in html
    assert "The score archive keeps its original context" in html
    assert "selected directly from the protocol field above" in html
    assert "Every score tells a story you can replay" in html
    assert "GPT-5" not in html
    assert "Claude" not in html
    assert "Gemini" not in html


def test_protocol_pages_render_only_public_catalog_data() -> None:
    html = Path("web/protocols.html").read_text(encoding="utf-8")

    assert "The world through the agent’s eyes" in html
    assert "One protocol. The same challenge for every model" in html
    assert "FL.fetchJson('/public/protocols')" in html
    assert "/public/protocols/${encodeURIComponent(slug)}" in html
    assert "protocol.result_status" in html
    assert "protocol.observer_firewall" in html
    assert "protocol.comparability_fields" in html
    assert 'href="/protocols/fort-eval-easy-p1-g7-v5">Easy</a>' in html
    assert "GPT-5" not in html
    assert "Claude" not in html
    assert "Gemini" not in html


def test_replay_viewer_requires_live_scope_before_live_mode() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "Array.isArray(run.scopes)" in html
    assert "runScopes.includes('live')" in html
    assert "if (canWatchLive)" in html


def test_root_serves_landing_and_public_entrypoints() -> None:
    from fort_gym.bench.api import server

    assert 'return _html_file_response("landing.html")' in inspect.getsource(
        server.serve_landing
    )
    assert 'return _html_file_response("index.html")' in inspect.getsource(
        server.serve_index
    )
    assert '_html_with_social_meta("index.html", metadata)' in inspect.getsource(
        server.serve_short_visual_replay
    )
    assert 'return _html_file_response("worlds.html")' in inspect.getsource(
        server.serve_worlds
    )
    assert 'return _html_file_response("results.html")' in inspect.getsource(
        server.serve_results
    )
    assert 'return _html_file_response("findings.html")' in inspect.getsource(
        server.serve_findings
    )
    assert 'return _html_file_response("protocols.html")' in inspect.getsource(
        server.serve_protocols
    )


def test_public_pages_and_shared_assets_are_served() -> None:
    from fastapi.testclient import TestClient

    from fort_gym.bench.api import server

    client = TestClient(server.app)
    assert client.get("/").status_code == 200
    assert client.get("/worlds").status_code == 200
    assert client.get("/results").status_code == 200
    assert client.get("/findings").status_code == 200
    assert client.get("/protocols").status_code == 200
    assert client.get("/protocols/fort-eval-easy-v1").status_code == 200
    assert client.get("/static/fort-labs.css").status_code == 200
    assert client.get("/static/fort-labs.js").status_code == 200
    assert client.get("/static/findings-v1.json").status_code == 200
    assert client.get("/favicon.ico").status_code == 200
    assert client.get("/favicon.ico").headers["content-type"] == "image/png"


def test_run_shares_are_permanent_evidence() -> None:
    """Public benchmark runs are citable evidence: their auto-created share
    tokens must never expire (WDSLL replay links rotted after 24h before
    this)."""
    from fort_gym.bench.api import server

    source = inspect.getsource(server.create_run)
    assert "ttl_seconds=None" in source
