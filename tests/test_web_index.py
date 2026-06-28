from __future__ import annotations

from pathlib import Path


def test_live_index_exposes_completed_run_inspection_links() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "formatRunLabel(run)" in html
    assert "updateRunLinks(token)" in html
    assert "tokenFromLocation()" in html
    assert "window.location.pathname.match" in html
    assert "^\\/(?:r|replay)\\/" in html
    assert 'href="/r/${encoded}"' in html
    assert "Replay saved SSE events" in html
    assert "Open NDJSON trace export" in html
    assert "runSelector.value = currentToken" in html


def test_live_index_uses_saved_replay_for_completed_runs() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "Saved Run Replay" in html
    assert "DF Screen Replay" in html
    assert "Recorded CopyScreen" in html
    assert "Source: DF CopyScreen text" in html
    assert "extractScreenText(record)" in html
    assert "drawDfScreenFrame" in html
    assert "snapshot.screenText" in html
    assert "Captured DFHack Map" in html
    assert "Captured DFHack Map Analysis" in html
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
    assert "replay-step-slider" in html
    assert "state_after_advance?.work" in html
    assert "if (isRunning)" in html
    assert "if (!isRunning)" in html
