"""Public matched comparison and replay remain tied to reviewed real evidence."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_report_and_replay_bindings():
    path = ROOT / "web/static/displayed-key-comparison.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "03e806f4fb88195a449e8a842275edbf750dd57d99321d9cd6bd483c9ec5468c"
    )
    report = json.loads(path.read_text())
    result = report["trials"][0]
    assert report["recorded_attempts"] == 1
    assert result["campaign_id"] == "bindings-comparison-20260911-sol-r1"
    assert (
        result["evidence_sha256"]
        == "5d0cb5ea363ef5ac4bf24d8336ea1479bbd84a1966a90f68a646d0635923af66"
    )
    replay_path = ROOT / "web/static/recordings/sol-matched-r1-1-64.json"
    assert hashlib.sha256(replay_path.read_bytes()).hexdigest() == (
        "50bc9a2b94b6a0de3fadf1507ec59fbde845c2cc4e5461623d2c26e0dab78741"
    )
    replay = json.loads(replay_path.read_text())
    assert [frame["decision"] for frame in replay["frames"]] == list(range(1, 65))
    assert replay["saved_through_decision"] == result["result"]["responses"] == 64
    assert replay["audit_sha256"] == result["result"]["terminal_audit_sha256"]
    assert sum(frame["after"]["ticks_advanced"] for frame in replay["frames"]) == 2900
    assert replay["frames"][-1]["after"]["population"] == 7
    assert all(frame["accepted"] for frame in replay["frames"])
    forbidden = {
        "memory",
        "memory_update",
        "reasoning",
        "analysis",
        "request",
        "response",
        "provider_events",
        "account",
        "access_token",
        "api_key",
        "prompt",
    }

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(replay)
    check(report)


def test_comparison_client():
    subprocess.run(
        ["node", "--test", "tests/displayed_key_comparison_client.mjs"], cwd=ROOT, check=True
    )


def test_current_comparison_is_not_the_legacy_benchmark():
    html = (ROOT / "web/results.html").read_text()
    assert html.index('id="matched-comparison"') < html.index('id="current-recordings-title"')
    assert "not equal game time or token use" in html
    assert "not $0" in html
    assert "fort-eval-easy-p1-g7-v3" in html
    assert "completed Year-Two campaign" not in html
