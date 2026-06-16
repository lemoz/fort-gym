from __future__ import annotations

from pathlib import Path


def test_live_index_exposes_completed_run_inspection_links() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "formatRunLabel(run)" in html
    assert "updateRunLinks(token)" in html
    assert "Replay saved SSE events" in html
    assert "Open NDJSON trace export" in html
    assert "runSelector.value = currentToken" in html


def test_live_index_uses_saved_replay_for_completed_runs() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "Saved Run Replay" in html
    assert "Current VM Screen" in html
    assert "renderSavedRunReplay" in html
    assert "setReplayRecords(records)" in html
    assert "replay-step-slider" in html
    assert "state_after_advance?.work" in html
    assert "if (isRunning)" in html
    assert "if (!isRunning)" in html
