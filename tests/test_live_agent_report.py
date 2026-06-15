from __future__ import annotations

from fort_gym.bench import cli


def test_write_live_agent_packet(tmp_path):
    report = {
        "ok": True,
        "comparison": {
            "baseline_score": 23.5,
            "model_score": 26.0,
            "score_delta": 2.5,
            "result": "model_higher",
        },
        "runs": {
            "baseline": {
                "run_id": "baseline-run",
                "model": "fake",
                "status": "completed",
                "score": 23.5,
                "public_run_url": "http://example.test/public/runs/base",
                "public_replay_url": "http://example.test/public/runs/base/events/replay",
                "public_trace_url": "http://example.test/public/runs/base/export/trace",
                "trace": "/tmp/base/trace.jsonl",
                "summary": "/tmp/base/summary.json",
                "actions": [
                    {
                        "step": 0,
                        "type": "DIG",
                        "ticks_advanced": 0,
                        "score": 23.5,
                        "intent": "baseline dig",
                    }
                ],
            },
            "model": {
                "run_id": "model-run",
                "model": "anthropic-keystroke",
                "status": "completed",
                "score": 26.0,
                "public_run_url": "http://example.test/public/runs/model",
                "public_replay_url": "http://example.test/public/runs/model/events/replay",
                "public_trace_url": "http://example.test/public/runs/model/export/trace",
                "trace": "/tmp/model/trace.jsonl",
                "summary": "/tmp/model/summary.json",
                "actions": [
                    {
                        "step": 0,
                        "type": "KEYSTROKE",
                        "ticks_advanced": 200,
                        "score": 26.0,
                        "intent": "starter dig",
                    }
                ],
            },
        },
    }

    packet = cli._write_live_agent_packet(
        report=report,
        packet_path=None,
        server_artifacts_dir=str(tmp_path),
    )

    text = packet.read_text(encoding="utf-8")
    assert packet == tmp_path / "model-run" / "live_agent_report.md"
    assert "Status: PASS" in text
    assert "Result: `model_higher`" in text
    assert "Score delta: `2.5`" in text
    assert "http://example.test/public/runs/model/events/replay" in text
    assert "step 0: KEYSTROKE ticks=200 score=26.0" in text
