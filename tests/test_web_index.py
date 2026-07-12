from __future__ import annotations

from pathlib import Path


def test_live_index_exposes_completed_run_inspection_links() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "formatRunLabel(run)" in html
    assert "updateRunLinks(token, runScopes)" in html
    assert "tokenFromLocation()" in html
    assert "window.location.pathname.match" in html
    assert "^\\/(?:r|replay)\\/" in html
    assert 'href="/r/${encoded}"' in html
    assert "Replay saved SSE events" in html
    assert "Open NDJSON trace export" in html
    assert "runSelector.value = currentToken" in html


def test_replay_uses_fort_labs_run_workspace() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    css = Path("web/static/replay-labs.css").read_text(encoding="utf-8")

    assert "/static/fort-labs.css" in html
    assert "/static/replay-labs.css" in html
    assert 'class="replay-workspace"' in html
    assert "Inside a recorded world" in html
    assert "Follow the agent from plan to action to a changing fortress" in html
    assert "Decision trace" in html
    assert "How the run unfolded" in html
    assert "The shape of this run" in html
    assert "runHeading.textContent" in html
    assert "protocolBadge.textContent" in html
    assert "grid-template-columns: minmax(0, 1fr) 290px" in css
    assert "@media (max-width: 640px)" in css
    assert "#game-canvas" in css and "height: auto" in css
    assert "max: 100" not in html
    assert "suggestedMin: 0" in html
    assert "if (!presetToken) setInterval(loadRuns, 5000)" in html
    assert "`/public/runs/${encodeURIComponent(presetToken)}`" in html
    assert "const runs = presetToken ? [payload] : payload" in html


def test_live_index_uses_saved_replay_for_completed_runs() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "Saved Run Replay" in html
    assert "DF Screen Replay" in html
    assert "Recorded CopyScreen" in html
    assert "Source: DF CopyScreen text" in html
    assert "No Recorded DF Screen Frame" in html
    assert "the replay will not substitute the derived DFHack map" in html
    assert "extractScreenText(record)" in html
    assert "drawDfScreenFrame" in html
    assert "drawMissingDfScreenFrame" in html
    assert "snapshot.screenText" in html
    assert "Derived DFHack Map Inspection" in html
    assert "replayEvidenceView === 'map'" in html
    assert "Not a DF screen / not gameplay proof" in html
    assert "Derived Trace Replay" in html
    assert "map_snapshot?.ok" in html
    assert "drawCapturedMapSnapshot" in html
    assert "df.global.world.map" in html
    assert "extractGameplayProof(record)" in html
    assert "gameplayProof: extractGameplayProof(record)" in html
    assert "drawChangedTileHighlights" in html
    assert "Proof: ${proof.changed_tile_count ?? 0} changed tiles" in html
    assert "Scored by real play" in html
    assert "Current VM Screen" in html
    assert "renderSavedRunReplay" in html
    assert "setReplayRecords(records)" in html
    assert "setReplayEvidenceView" in html
    assert "replay-step-slider" in html
    assert "state_after_advance?.work" in html
    assert "if (canWatchLive)" in html
    assert "runScopes.includes('live')" in html
    assert "if (!canWatchLive)" in html
    assert "runScopes.includes('replay') && runScopes.includes('export')" in html
    assert "canLoadVisualReplay ? loadTraceData(token) : Promise.resolve([])" in html
    assert "Replay and export scopes are required" in html


def test_replay_exposes_spectator_only_observer_map() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert 'id="replay-view-observer"' in html
    assert 'id="observer-level-select"' in html
    assert "function buildObserverState" in html
    assert "function drawObserverMap" in html
    assert "Derived spectator evidence" in html
    assert "not passed to the evaluated model" in html
    assert "verified tile changes" in html
    assert "executionStatus: executionRejected ? 'rejected' : executionAccepted ? 'accepted' : 'unknown'" in html
    assert "White: execution result not recorded" in html
    assert "record.execute?.accepted !== false" not in html


def test_replay_distinguishes_frozen_liquid_from_stable_floor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "case 'frozen_liquid':" in html
    assert "'i': { fill: '#74c2d6', glyph: 'i' }" in html
    assert "i=ice" in html
    assert "Stable floor:" in html
    assert "Ice:" in html


def test_replay_distinguishes_other_occupied_buildings_from_floor() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "'o': { fill: '#694b7d', glyph: 'o' }" in html
    assert "o=occupied" in html


def test_replay_screen_offers_graphical_tileset_toggle() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    # toggle exists and defaults to the graphical re-skin
    assert 'id="replay-glyph-graphical"' in html
    assert 'id="replay-glyph-ascii"' in html
    assert "let replayGlyphMode = 'graphical'" in html
    assert "setReplayGlyphMode" in html
    assert "for ASCII purists" in html

    # graphical mode maps recorded CP437 characters to bundled tileset sprites
    assert "/static/tilesets/oddball-16x16.png" in html
    assert "Oddball 16x16 tileset by HexaBlu (CC BY 4.0)" in html
    assert "GRAPHICAL_CHAR_TILES" in html
    assert "cp437CodeForChar" in html
    assert "drawDfScreenTiles" in html

    # pure re-skin of the same recorded evidence, and the raw-text path plus
    # a graceful fallback both survive
    assert "same recorded text, re-skinned" in html
    assert "gameCtx.fillText(char, textX + col * charW, y)" in html
    assert "Graphical tileset unavailable" in html

    # Both mode controls expose the current selection to assistive technology.
    assert html.count('aria-pressed="true"') >= 2
    assert "replayViewObserver.setAttribute('aria-pressed'" in html
    assert "replayGlyphAscii.setAttribute('aria-pressed'" in html


def test_graphical_tileset_asset_is_bundled_with_attribution() -> None:
    import struct

    png = Path("web/static/tilesets/oddball-16x16.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (256, 256)  # 16x16 grid of 16x16 CP437 tiles

    attribution = Path("web/static/tilesets/README.md").read_text(encoding="utf-8")
    assert "HexaBlu" in attribution
    assert "CC BY 4.0" in attribution


def test_static_assets_are_served() -> None:
    from fastapi.testclient import TestClient

    from fort_gym.bench.api.server import app

    client = TestClient(app)
    response = client.get("/static/tilesets/oddball-16x16.png")
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_replay_keeps_server_rendered_social_title() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "document.querySelector('meta[property=\"og:title\"]')" in html
    assert "document.title = socialTitle?.content" in html


def test_replay_ticks_show_labeled_delta_and_monotonic_total() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    # per-step tick deltas must be labeled as deltas and paired with the
    # monotonic in-run total, never shown as a bare oscillating number
    assert "function formatReplayTicks(record)" in html
    assert "run_elapsed_ticks" in html
    assert "this step (total " in html
    assert html.count("formatReplayTicks(snapshot.record)") == 2
    assert "`Ticks: ${snapshot.record.tick_advance?.ticks_advanced" not in html
