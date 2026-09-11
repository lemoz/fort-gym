"""Keep interface acceptance summaries free of captured gameplay payloads."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"


def test_map_inspection_summary_keeps_failed_attempts_and_excludes_game_state():
    result = json.loads(
        (EVIDENCE / "local_native_map_inspection_outcomes_20260907.json").read_text()
    )
    assert [item["status"] for item in result["attempts"]] == ["failed", "failed", "passed"]
    assert all(
        set(item) == {"attempt_id", "fixture_version", "status", "diagnosis", "teardown_verified"}
        for item in result["attempts"]
    )
    assert all(type(value) is bool for value in result["checks"].values())
    assert result["provider_calls"] == 0 and result["metered_provider_charge_usd"] == "0"
    assert result["hardware_energy_app_and_ci_cost_usd"] is None
    assert result["autonomous_gameplay"] is False and result["year_two_gameplay_verified"] is False
    assert result["new_model_comparison_rows"] == 0
    for forbidden in (
        "map_rows",
        "map_origin",
        "map_dimensions",
        "screen_text",
        "screen_sha256",
        "visibility_mask",
        "native_save",
        "source_hashes",
        "final_calendar",
    ):
        assert f'"{forbidden}":' not in json.dumps(result)


def test_declared_native_fixtures_keep_their_exact_published_source():
    for suffix in ("", "_v2", "_v3"):
        declaration = json.loads(
            (
                EVIDENCE / f"local_native_map_inspection{suffix}_declaration_20260907.json"
            ).read_text()
        )
        source = ROOT / declaration["fixture_source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == declaration["fixture_sha256"]
        assert declaration["bounds"]["provider_calls"] == 0
        assert declaration["bounds"]["advancing_ticks_requested"] == 0
        assert declaration["bounds"]["mandatory_teardown"] is True
