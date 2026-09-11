"""Decision-96 website delivery, separate from native progress and public deployment."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"


def record():
    return json.loads((EVIDENCE / "keyboard_binding_96_website_20260911.json").read_text())


def test_exact_native_result_and_all_checkpoints():
    row = record()
    native = ROOT / row["native_result_path"]
    assert hashlib.sha256(native.read_bytes()).hexdigest() == row["native_result_sha256"]
    result = json.loads(native.read_text())
    assert row["displayed_decisions"] == result["responses"] == 96
    assert row["displayed_saved_elapsed_ticks"] == result["saved_elapsed_ticks"] == 59500
    assert row["displayed_total_tokens"] == result["usage"]["total_tokens"] == 2567162
    assert row["independent_campaigns"] == 1
    assert row["checkpoint_reload_display"] == [
        {"decisions": 32, "save_verified": True, "separate_fresh_reload_verified": True},
        {"decisions": 64, "save_verified": True, "separate_fresh_reload_verified": False},
        {"decisions": 96, "save_verified": True, "separate_fresh_reload_verified": False},
    ]
    assert row["checkpoint_shutdown_warning_display"] == [
        {"decisions": 64, "guest_command_warning": True},
        {"decisions": 96, "guest_command_warning": False},
    ]


def test_preserves_previous_data_and_lineage():
    row = record()
    prior = json.loads((EVIDENCE / "keyboard_binding_64_website_20260911.json").read_text())
    assert row["base_revision"] == prior["website_revision"]
    assert row["stable_route_sha256"] == prior["stable_route_sha256"]
    assert len(row["stable_route_sha256"]) == 5
    assert row["previous_64_decision_timeline_unchanged"] is True
    assert row["generic_feed_http_status"] == 200 and row["published_snapshots"] == 11
    reload = ROOT / row["reload_result_path"]
    assert hashlib.sha256(reload.read_bytes()).hexdigest() == row["reload_result_sha256"]


def test_verification_and_delivery_claims_are_bounded():
    row = record()
    assert row["full_tests"] == {"passed": 5001, "skipped": 10, "failed": 0}
    assert row["focused_campaign_chain_tests_passed"] == 27
    assert row["static_checks"]["globally_clean"] is False
    assert row["static_checks"]["same_diagnostics_ignoring_shifted_line_numbers"] is True
    assert not any(row["proof_limits"].values())
    ci = row["github_ci_at_publication"]
    assert ci["headSha"] == row["website_revision"]
    assert ci["run_id"] == 34591095349
    assert ci["status"] in {"in_progress", "completed"}
    assert ci["conclusion"] == ("success" if ci["status"] == "completed" else None)
