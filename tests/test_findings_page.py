from __future__ import annotations

import json
from pathlib import Path


def test_findings_manifest_is_curated_versioned_and_gate_honest() -> None:
    manifest = json.loads(Path("web/static/findings-v1.json").read_text(encoding="utf-8"))

    assert manifest["version"] == "findings-v1"
    assert manifest["as_of"] == "2026-07-11"
    assert manifest["source_revision"] == "e8b6b64fb8f5ed6d05c3c3ef366ce84b3f98d5e9"
    assert len(manifest["findings"]) == 7
    assert len({item["id"] for item in manifest["findings"]}) == 7
    assert all(item["claim"] and item["evidence"] and item["caveat"] for item in manifest["findings"])
    assert all("docs/FINDINGS.md#" in item["source_url"] for item in manifest["findings"])
    assert all("/blob/main/" not in item["source_url"] for item in manifest["findings"])

    gates = {item["gate"]: item["status"] for item in manifest["gate_status"]}
    assert gates == {"G0-G4": "passed", "G5": "failed", "G6": "open", "G7": "open"}
    assert len(manifest["evidence_runs"]) == 5
    assert len({item["token"] for item in manifest["evidence_runs"]}) == 5
    assert [item["token"] for item in manifest["evidence_runs"] if item.get("lead")] == [
        "qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH"
    ]


def test_findings_page_uses_only_curated_claims_and_exact_replay_tokens() -> None:
    html = Path("web/findings.html").read_text(encoding="utf-8")

    assert "What agents reveal when the world keeps pushing back" in html
    assert "Agents can build real forts. The frontier is keeping them alive" in html
    assert "The corrections log became the research" in html
    assert "The worlds behind the claims" in html
    assert "FL.fetchJson('/static/findings-v1.json')" in html
    assert "FL.fetchJson(`/public/runs/${encodeURIComponent(entry.token)}`)" in html
    assert "FL.loadRunFrame" in html
    assert "settled.map" in html
    assert "await renderEvidence(records)" in html
    assert "frameGapCount" in html
    assert "Run metadata temporarily unavailable" in html
    assert 'id="findings-load-status" role="status" aria-live="polite"' in html
    assert "/public/worlds" not in html
    assert "/public/leaderboard" not in html
    assert "Map Inspect" in html and "Observer Map" in html


def test_core_fort_labs_pages_link_to_findings_route() -> None:
    for path in (
        "web/landing.html",
        "web/worlds.html",
        "web/results.html",
        "web/protocols.html",
        "web/findings.html",
        "web/index.html",
    ):
        html = Path(path).read_text(encoding="utf-8")
        assert 'href="/findings"' in html
        if 'id="fl-mobile-menu"' in html:
            mobile_menu = html.split('id="fl-mobile-menu"', 1)[1].split("</nav>", 1)[0]
            assert 'href="/live"' in mobile_menu
