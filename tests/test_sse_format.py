from __future__ import annotations

from fort_gym.bench.api.sse import sse_event


def test_sse_event_formatting() -> None:
    payload = {"ok": 1}
    frame = sse_event("state", payload)

    assert frame.startswith("event: state\n")
    assert "data: {\"ok\": 1}" in frame
    assert frame.endswith("\n\n")
    assert frame.count("\n\n") == 1
