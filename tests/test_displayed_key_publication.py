"""Public matched comparison and replay remain tied to reviewed real evidence."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "name,replay_sha,ticks",
    [
        ("sol", "50bc9a2b94b6a0de3fadf1507ec59fbde845c2cc4e5461623d2c26e0dab78741", 2900),
        ("terra", "3499bc18073141858398ab631389155a2672ded691b3b0324aaf5d26c7d5e6bb", 4200),
        ("astra", "24380f7d5226ef28633b6eb37776ffa905069ac1cc1006b29ffd92b14950bfcc", 23000),
    ],
)
def test_public_report_and_replay_bindings(name, replay_sha, ticks):
    path = ROOT / "web/static/displayed-key-comparison.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "d5d0a334e02017288595bafa825ba0ebcd2e2e669ac4864150ba79610de47baf"
    )
    report = json.loads(path.read_text())
    identity = "bindings-comparison-20260911-" + name + "-r1"
    result = next(row for row in report["trials"] if row["campaign_id"] == identity)
    assert report["recorded_attempts"] == 4 and report["strong_ranking_supported"] is False
    replay_path = ROOT / ("web/static/recordings/" + name + "-matched-r1-1-64.json")
    assert hashlib.sha256(replay_path.read_bytes()).hexdigest() == replay_sha
    replay = json.loads(replay_path.read_text())
    assert [frame["decision"] for frame in replay["frames"]] == list(range(1, 65))
    assert replay["saved_through_decision"] == result["result"]["responses"] == 64
    assert replay["audit_sha256"] == result["result"]["terminal_audit_sha256"]
    assert sum(frame["after"]["ticks_advanced"] for frame in replay["frames"]) == ticks
    assert result["result"]["checkpoint"]["saved_elapsed_ticks"] == ticks
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


def test_terra_repeat_keeps_every_rejected_choice_and_actual_zero_time():
    path = ROOT / "web/static/recordings/terra-matched-r2-1-64.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "d34f451723a40ef11c2cb966b2c568702e44489163b51e79721bffb15aeaeeb1"
    )
    recording = json.loads(path.read_text())
    frames = recording["frames"]
    assert [frame["decision"] for frame in frames] == list(range(1, 65))
    assert [frame["decision"] for frame in frames if frame["accepted"] is False] == (
        [3, 4, 8, 23, 25, 46, 51, 62, 63]
    )
    assert all(frame["after"]["ticks_advanced"] == 0 for frame in frames)
    assert all(set(frame["action"]) == {"intent", "keys", "advance_ticks"} for frame in frames)
    report = json.loads((ROOT / "web/static/displayed-key-comparison.json").read_text())
    result = report["trials"][3]["result"]
    assert result["terminal_audit_sha256"] == recording["audit_sha256"]
    assert result["returned_tokens"] == 1186821
    assert result["checkpoint"]["saved_elapsed_ticks"] == 0
    assert result["reported_charge_usd"] is None


def test_current_comparison_is_not_the_legacy_benchmark():
    html = (ROOT / "web/results.html").read_text()
    assert html.index('id="matched-comparison"') < html.index('id="current-recordings-title"')
    assert "not equal game time or token use" in html
    assert "not $0" in html
    assert "fort-eval-easy-p1-g7-v3" in html
    assert "completed Year-Two campaign" not in html
