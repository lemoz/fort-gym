from __future__ import annotations

import json

from fort_gym.bench import cli


class _FakeResponse:
    status = 200
    headers = {"content-type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return b'{"status":"ok"}'


def test_check_public_endpoint_success(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout: float):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)

    result = cli._check_public_endpoint("http://example.test/", "/health", timeout=2.5)

    assert result["ok"] is True
    assert result["url"] == "http://example.test/health"
    assert result["status"] == 200
    assert result["content_type"] == "application/json"
    assert result["bytes_read"] == len(b'{"status":"ok"}')
    assert seen == {"url": "http://example.test/health", "timeout": 2.5}


def test_write_live_demo_packet(tmp_path):
    run_dir = tmp_path / "live-dfhack-demo-rehearsal"
    run_dir.mkdir()
    trace_path = run_dir / "trace.jsonl"
    summary_path = run_dir / "summary.json"
    trace_path.write_text(json.dumps({"step": 0}) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps({"steps": 2}), encoding="utf-8")

    report = {
        "ok": True,
        "checks": {
            "dfhack_connect": True,
            "dig_accepted": True,
            "wait_ticks_advanced": True,
        },
        "run_id": "live-dfhack-demo-rehearsal",
        "trace": str(trace_path),
        "summary": str(summary_path),
        "wait_tick_advance": {"requested": 10, "ticks_advanced": 11},
    }
    endpoint_checks = [
        {
            "ok": True,
            "url": "http://example.test/health",
            "status": 200,
            "content_type": "application/json",
            "bytes_read": 15,
        }
    ]

    packet = cli._write_live_demo_packet(
        report=report,
        endpoint_checks=endpoint_checks,
        public_base_url="http://example.test",
    )

    text = packet.read_text(encoding="utf-8")
    assert packet == run_dir / "live_demo_packet.md"
    assert "Status: PASS" in text
    assert "- [x] `dfhack_connect`" in text
    assert "- [x] GET `http://example.test/health` -> `200`" in text
    assert f"- Trace: `{trace_path}`" in text
    assert '"ticks_advanced": 11' in text
