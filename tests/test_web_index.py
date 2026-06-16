from __future__ import annotations

from pathlib import Path


def test_live_index_exposes_completed_run_inspection_links() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")

    assert "formatRunLabel(run)" in html
    assert "updateRunLinks(token)" in html
    assert "Replay saved SSE events" in html
    assert "Open NDJSON trace export" in html
    assert "runSelector.value = currentToken" in html
