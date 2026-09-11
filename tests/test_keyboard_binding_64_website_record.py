"""Website delivery is separate from native gameplay and public deployment."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"


def read_record():
    return json.loads((EVIDENCE / "keyboard_binding_64_website_20260911.json").read_text())


def test_binds_exact_native_result_and_checkpoint_specific_reload():
    record = read_record()
    for path, digest in (
        ("native_result_path", "native_result_sha256"),
        ("reload_result_path", "reload_result_sha256"),
    ):
        assert hashlib.sha256((ROOT / record[path]).read_bytes()).hexdigest() == record[digest]
    result = json.loads((ROOT / record["native_result_path"]).read_text())
    assert record["displayed_decisions"] == result["responses"] == 64
    assert record["displayed_saved_elapsed_ticks"] == result["saved_elapsed_ticks"] == 29500
    assert record["displayed_total_tokens"] == result["usage"]["total_tokens"] == 1583026
    assert record["independent_campaigns"] == 1
    assert record["checkpoint_reload_display"] == [
        {"decisions": 32, "save_verified": True, "separate_fresh_reload_verified": True},
        {"decisions": 64, "save_verified": True, "separate_fresh_reload_verified": False},
    ]


def test_preserves_historical_endpoint_hashes_and_original_snapshot():
    record = read_record()
    prior = json.loads((EVIDENCE / "keyboard_binding_website_20260911.json").read_text())
    assert record["original_and_historical_routes_unchanged"] is True
    assert len(record["stable_route_sha256"]) == 5
    for route, digest in prior["verification"]["historical_routes_byte_identical"].items():
        assert record["stable_route_sha256"][route] == digest
    assert record["generic_feed_http_status"] == 200 and record["published_snapshots"] == 11
    assert record["base_revision"] == "c5288317b4b689e4a70ccaf979fe753aa4bb102c"
    assert prior["proof_limits"]["public_website_deployed"] is False


def test_tests_and_proof_limits_are_separate():
    record = read_record()
    assert record["full_tests"] == {"passed": 4992, "skipped": 10, "failed": 0}
    assert record["focused_current_original_historical_tests_passed"] == 56
    assert record["static_checks"]["globally_clean"] is False
    assert record["static_checks"]["same_diagnostics_ignoring_shifted_line_numbers"] is True
    assert not any(record["proof_limits"].values())
    assert record["github_ci_at_publication"]["status"] == "in_progress"


def test_later_ci_binds_same_revision_without_rewriting_publication_snapshot():
    record = read_record()
    ci = json.loads((EVIDENCE / "keyboard_binding_64_website_ci_20260911.json").read_text())
    assert ci["website_revision"] == ci["headSha"] == record["website_revision"]
    assert ci["run_id"] == record["github_ci_at_publication"]["run_id"] == 34586640666
    assert ci["status"] == "completed" and ci["conclusion"] == "success"
    assert (
        hashlib.sha256((ROOT / ci["publication_record_path"]).read_bytes()).hexdigest()
        == ci["publication_record_sha256"]
    )
    assert ci["prior_publication_snapshot_unchanged"] is True
    assert (
        ci["main_merged"]
        is ci["public_website_deployed"]
        is ci["additional_native_gameplay"]
        is False
    )
