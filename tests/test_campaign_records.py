"""Publication checks and retained-result regressions, not new gameplay/deployment."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_records as records
from fort_gym.bench.run.campaign_feed import CampaignFeed, initialize_feed

CONFIG = {"condition_id": "test-condition", "models": ["test-model"]}


def test_local_campaign_configuration_links_are_exact_and_revision_bound():
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const helpers = require(process.argv[1]);
const revision = 'a'.repeat(40);
for (const [condition, file] of [
  ['local-native-llama-typed-v1', 'local_native_llama_typed_v1.json'],
  ['local-native-llama-thinking-v1', 'local_native_llama_thinking_v1.json'],
  ['local-native-llama-long-v1', 'local_native_llama_long_v1.json'],
  ['local-native-llama-long-v2', 'local_native_llama_long_v2.json']
]) {
  assert.equal(helpers.configurationUrl({condition_id:condition,code_revision:revision}),
    'https://github.com/lemoz/fort-gym/blob/'+revision+'/experiments/campaigns/'+file);
}
assert.equal(helpers.configurationUrl({condition_id:'unpublished',code_revision:revision}),null);
assert.equal(helpers.configurationUrl({condition_id:'constructor',code_revision:revision}),null);
assert.equal(helpers.configurationUrl({condition_id:'local-native-llama-long-v2',code_revision:'../main'}),null);
""",
            str(records.PROJECT_ROOT / "web/static/campaign-feed.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_three_published_native_attempts_preserve_distinct_failure_causes():
    result = records.campaign_feed(None)
    assert result["configured"] is False and result["published_snapshots"] == 10
    by_model = {
        row["model"]: row
        for row in result["campaigns"]
        if row["condition_id"] == "local-native-packed-comparison-v1"
    }
    qwen = by_model["qwen2.5:7b-instruct"]
    llama = by_model["llama3.1:8b-instruct-q4_K_M"]
    mistral = by_model["mistral:7b-instruct-v0.3-q4_K_M"]
    assert (qwen["committed_steps"], qwen["elapsed_ticks"]) == (16, 1600)
    assert (llama["committed_steps"], llama["elapsed_ticks"]) == (16, 0)
    assert (mistral["committed_steps"], mistral["elapsed_ticks"]) == (12, 0)
    assert mistral["actions"]["path_cache_stale_rejections"] == 12
    assert mistral["checkpoint_verified"] is False
    assert qwen["checkpoint_verified"] is True and llama["checkpoint_verified"] is True
    assert sum(row["usage"]["total_tokens"] for row in by_model.values()) == 224746
    assert sum(row["usage"]["dispatched_requests"] for row in by_model.values()) == 45
    assert len({row["configuration_sha256"] for row in by_model.values()}) == 1
    assert len({row["declared_starting_snapshot_receipt_sha256"] for row in by_model.values()}) == 1
    assert all(row["cleanup_verified"] is True for row in by_model.values())
    assert all(row["comparison_rankings_available"] is False for row in by_model.values())


def test_recorded_comparison_is_served_without_enabling_a_live_directory(monkeypatch):
    from fort_gym.bench.api import server

    monkeypatch.setattr(
        server, "get_settings", lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=None)
    )
    client = TestClient(server.app)
    response = client.get("/public/campaign-feed")
    assert response.status_code == 200 and response.json()["configured"] is False
    assert len(response.json()["campaigns"]) == 10
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/campaigns").status_code == 200


def test_llama_native_result_distinguishes_valid_waits_from_fortress_development():
    record = next(
        row
        for row in records.campaign_feed(None)["campaigns"]
        if row["condition_id"] == "local-native-llama-typed-v1"
    )
    assert (record["committed_steps"], record["elapsed_ticks"]) == (16, 1600)
    assert record["actions"]["by_type"] == {"WAIT": {"accepted": 16, "rejected": 0, "unknown": 0}}
    assert record["usage"]["total_tokens"] == 142218
    assert record["usage"]["dispatched_requests"] == record["usage"]["accounted_responses"] == 16
    assert record["checkpoint_verified"] is True and record["cleanup_verified"] is True
    assert record["current_metrics"]["completed_workshops"] == 0
    assert record["current_metrics"]["population"] == 7
    assert record["current_metrics"]["food_stock"] == 45
    assert record["current_metrics"]["drink_stock"] == 60
    assert record["functioning_fortress"] == "not_assessed"
    assert record["comparison_rankings_available"] is False
    assert record["code_revision"] == "f04b3f92bfadf08da92039d373ee1bb62eee6e49"
    bundle = json.loads(
        (
            records.PROJECT_ROOT / "experiments/evidence/local_native_llama_typed_20260906.json"
        ).read_text()
    )
    assert bundle["native_audit"]["checkpoint_cursor"] == 16
    assert (
        bundle["native_audit"]["returned_usage_audit"]["tokens_summed_from_native_model_responses"]
        == 142218
    )
    assert (
        bundle["native_audit"]["measured_context"][
            "all_committed_prompt_counts_match_returned_usage"
        ]
        is True
    )
    assert len(bundle["native_audit"]["segments"]) == 2
    assert bundle["configuration"]["local_inference"]["enable_thinking"] is False


def test_repair_record_preserves_clock_and_checkpoint_without_claiming_success():
    rows = records.campaign_feed(None)["campaigns"]
    repaired = next(row for row in rows if row["condition_id"] == "local-native-harness-repair-v1")
    original = next(row for row in rows if row["campaign_id"] == "local-packed-mistral-20260906-a")
    assert repaired["model"] == original["model"]
    assert repaired["configuration_sha256"] != original["configuration_sha256"]
    assert repaired["code_revision"] == "75cc9318f09cf79f66789f83321e76ffe08b146d"
    assert (
        repaired["declared_starting_snapshot_receipt_sha256"]
        == original["declared_starting_snapshot_receipt_sha256"]
    )
    assert (repaired["committed_steps"], repaired["elapsed_ticks"]) == (16, 28000)
    assert repaired["usage"]["total_tokens"] == 96919
    assert (
        repaired["usage"]["dispatched_requests"] == repaired["usage"]["accounted_responses"] == 16
    )
    assert repaired["usage"]["metered_provider_charge_usd"] == "0"
    assert repaired["usage"]["infrastructure_cost_usd"] is None
    assert repaired["checkpoint_verified"] is True and repaired["cleanup_verified"] is True
    assert repaired["actions"]["accepted"] == 0 and repaired["actions"]["rejected"] == 16
    assert repaired["actions"]["path_cache_stale_rejections"] == 4
    assert repaired["current_metrics"]["completed_workshops"] == 0
    assert repaired["current_metrics"]["population"] == 7
    assert repaired["elapsed_ticks"] < 403200
    assert repaired["functioning_fortress"] == "not_assessed"
    assert repaired["comparison_rankings_available"] is False


def test_thinking_native_resource_gain_is_not_completed_development_or_a_ranking():
    from fort_gym.bench.api import server

    rows = records.campaign_feed(None)["campaigns"]
    thinking = next(row for row in rows if row["condition_id"] == "local-native-llama-thinking-v1")
    baseline = next(row for row in rows if row["condition_id"] == "local-native-llama-typed-v1")
    assert thinking["model"] == baseline["model"]
    assert thinking["configuration_sha256"] != baseline["configuration_sha256"]
    assert (thinking["committed_steps"], thinking["elapsed_ticks"]) == (8, 5000)
    assert thinking["usage"]["total_tokens"] == 58359
    assert thinking["usage"]["dispatched_requests"] == thinking["usage"]["accounted_responses"] == 8
    assert thinking["actions"]["accepted"] == 6 and thinking["actions"]["rejected"] == 2
    assert thinking["actions"]["changed_command_after_rejection"] == 2
    assert thinking["current_metrics"]["wood_stock"] == 12
    assert baseline["current_metrics"]["wood_stock"] == 3
    assert thinking["current_metrics"]["completed_workshops"] == 0
    assert thinking["checkpoint_verified"] is True and thinking["cleanup_verified"] is True
    assert thinking["functioning_fortress"] == "not_assessed"
    assert thinking["comparison_rankings_available"] is False
    assert thinking["code_revision"] == "91ba6df9f79b3a8d43bb4e862e71080258d99910"
    filename = "local_native_llama_thinking_20260906.json"
    bundle = json.loads((records.PROJECT_ROOT / "experiments/evidence" / filename).read_text())
    assert bundle["native_audit"]["checkpoint_cursor"] == 8
    assert bundle["native_audit"]["designation_outcomes"]["shrubs_designated"] == 10
    assert bundle["native_audit"]["designation_outcomes"]["trees_designated"] == 2
    assert bundle["native_audit"]["thinking_mode"]["returned_responses_with_reasoning_content"] == 8
    assert bundle["configuration"]["local_inference"]["enable_thinking"] is True
    page = TestClient(server.app).get("/campaigns").text
    assert "Earlier result: autonomous wood collection" in page and filename in page
    assert "wood stock from 3 to 12" in page and "58,359 tokens" in page


def test_long_native_timeout_preserves_missing_usage_and_nonresumable_save():
    from fort_gym.bench.api import server

    record = next(
        row
        for row in records.campaign_feed(None)["campaigns"]
        if row["condition_id"] == "local-native-llama-long-v1"
    )
    assert (record["committed_steps"], record["elapsed_ticks"]) == (3, 1000)
    assert record["segment_status"] == "failed" and record["failure_kind"] == "provider"
    assert record["usage"]["dispatched_requests"] == 4
    assert record["usage"]["accounted_responses"] == record["usage"]["returned_responses"] == 3
    assert record["usage"]["dispatches_without_returned_usage"] == 1
    assert record["usage"]["total_tokens"] == 21429
    assert record["checkpoint_verified"] is False and record["cleanup_verified"] is True
    assert record["current_metrics"]["completed_workshops"] == 0
    assert record["fortress_collapse"] == "not_assessed"
    assert record["comparison_rankings_available"] is False
    filename = "local_native_llama_long_timeout_20260906.json"
    bundle = json.loads((records.PROJECT_ROOT / "experiments/evidence" / filename).read_text())
    assert bundle["configuration"]["local_inference"]["timeout_seconds"] == 180
    assert bundle["native_audit"]["checkpoint_cursor"] == 0
    segment = bundle["native_audit"]["segments"][0]
    assert segment["next_step"] == 3 and segment["periodic_checkpoints"] == []
    assert segment["forensic_native_save"]["inventory_verified"] is True
    assert segment["forensic_native_save"]["resumable_checkpoint"] is False
    assert segment["forensic_native_save"]["save_bytes"] == 8621334
    page = TestClient(server.app).get("/campaigns").text
    assert "Latest attempt: local model timeout" in page and filename in page
    assert "21,429 accounted tokens" in page
    assert "One request has no returned token usage" in page


def test_native_workshop_fixture_is_visible_but_never_a_model_comparison_row():
    from fort_gym.bench.api import server

    path = records.PROJECT_ROOT / "experiments/evidence/native_workshop_ground_20260906.json"
    fixture = json.loads(path.read_text())
    assert fixture["autonomous_gameplay"] is False and fixture["model_ranking_evidence"] is False
    assert fixture["provider_calls"] == 0 and fixture["elapsed_native_ticks"] == 4010
    assert fixture["initial_materials"]["free_flags"] == 0
    assert fixture["initial_observation"]["fixture_tree_was_in_existing_model_map"] is True
    assert fixture["final_snapshot"]["inventory_verified"] is True
    workshop = fixture["final_workshops"][0]
    assert workshop["stage"] == workshop["max_stage"] == 3 and workshop["built"] is True
    assert fixture["teardown"]["independent_process_check_empty"] is True
    assert fixture["teardown"]["independent_listener_closed"] is True
    page = TestClient(server.app).get("/campaigns").text
    assert "Adapter acceptance, not model performance" in page
    assert "4,010 game ticks" in page and path.name in page
    assert path.name not in records.PUBLISHED_BUNDLES


def test_completed_ground_condition_keeps_model_failure_separate_from_successful_fixture():
    record = next(
        row
        for row in records.campaign_feed(None)["campaigns"]
        if row["condition_id"] == "local-native-workshop-ground-v1"
    )
    assert (record["committed_steps"], record["elapsed_ticks"]) == (16, 32000)
    assert record["checkpoint_verified"] is True and record["cleanup_verified"] is True
    assert record["actions"]["accepted"] == 0 and record["actions"]["rejected"] == 16
    assert record["current_metrics"]["completed_workshops"] == 0
    assert record["usage"]["total_tokens"] == 98658
    assert record["usage"]["dispatched_requests"] == record["usage"]["accounted_responses"] == 16
    assert record["comparison_rankings_available"] is False
    assert record["code_revision"] == "82bcab14b758d6f4624e9080c857a607c2da0b51"


def test_qwen14_record_separates_native_usage_from_synthetic_feasibility():
    path = records.PROJECT_ROOT / "experiments/evidence/local_native_qwen14_q3_20260906.json"
    bundle = json.loads(path.read_text())
    record = next(
        row
        for row in records.campaign_feed(None)["campaigns"]
        if row["campaign_id"] == "local-qwen14-q3-20260906-a"
    )
    assert (record["committed_steps"], record["elapsed_ticks"]) == (16, 3200)
    assert record["checkpoint_verified"] is True and record["cleanup_verified"] is True
    assert record["actions"]["by_type"] == {"DIG": {"accepted": 0, "rejected": 16, "unknown": 0}}
    assert record["current_metrics"]["completed_workshops"] == 0
    assert record["usage"]["total_tokens"] == 82782
    assert record["usage"]["dispatched_requests"] == record["usage"]["accounted_responses"] == 16
    assert record["code_revision"] == "82645015444759f7bcebc048c34ea704930da8f4"
    assert record["comparison_rankings_available"] is False
    assert bundle["condition_completion"] == "completed_dispatch_budget"
    assert record["segment_status"] == "budget_limited_pause"
    assert [segment["next_step"] for segment in bundle["audits"][0]["segments"]] == [6, 11, 16]
    assert bundle["local_runtime"]["observed_gpu_layers"] == 49
    assert bundle["synthetic_feasibility"]["total_tokens"] == 1182
    assert bundle["synthetic_feasibility"]["all_cases_exact"] is False
    assert bundle["prior_candidate_feasibility"]["requests_without_returned_usage"] == 1
    assert bundle["prior_candidate_feasibility"]["total_returned_tokens"] == 766


def test_reference_record_retains_terminal_usage_and_unsaved_command_boundary():
    path = (
        records.PROJECT_ROOT
        / "experiments/evidence/local_native_designation_reference_20260906.json"
    )
    bundle = json.loads(path.read_text())
    row = next(
        row
        for row in records.campaign_feed(None)["campaigns"]
        if row["campaign_id"] == "local-reference-qwen14-20260906-a"
    )
    assert (row["committed_steps"], row["elapsed_ticks"]) == (14, 2800)
    assert row["usage"]["total_tokens"] == 78023
    assert row["usage"]["dispatched_requests"] == row["usage"]["accounted_responses"] == 15
    assert row["checkpoint_verified"] is False and row["cleanup_verified"] is True
    assert row["segment_status"] == "budget_limited_pause"
    assert row["actions"]["accepted"] == 0 and row["actions"]["rejected"] == 14
    assert row["current_metrics"]["completed_workshops"] == 0
    assert row["code_revision"] == "8148f6d55494ad88caf46a780cfbea11d16d6a4a"
    assert row["condition_id"] == "local-native-designation-reference-v1"
    assert row["comparison_rankings_available"] is False
    assert bundle["condition_completion"] == "request_bound_pause_requires_reconciliation"
    audit = bundle["audits"][0]
    assert audit["action_reference"]["every_committed_request_contains_exact_reference"] is True
    assert audit["raw_designation_modes"] == {"dig": 2, "omitted_default_dig": 12}
    assert bundle["baseline_raw_mode_diagnostic"]["raw_designation_modes"] == {"dig": 16}
    assert audit["packing"]["maximum_request_bytes"] == 21977
    assert audit["packing"]["maximum_history_rows_omitted"] == 10
    assert [segment["next_step"] for segment in audit["segments"]] == [6, 12, 14]
    assert audit["segments"][-1]["new_checkpoint_verified"] is False
    assert audit["segments"][-1]["recovery_requires_reconciliation"] is True
    assert bundle["recovery"]["latest_verified_checkpoint_next_step"] == 12
    assert bundle["recovery"]["committed_steps_after_checkpoint"] == 2
    assert bundle["recovery"]["failed_response_native_command_executed"] is False
    assert bundle["recovery"]["automatic_resume_allowed"] is False
    assert bundle["recovery"]["dispatch_allowance_remaining"] == 1
    assert len(bundle["configuration"]["models"]) == 4
    assert len(bundle["campaigns"]) == 1


def test_website_separates_incomplete_checkpoint_and_new_model_compatibility():
    from fort_gym.bench.api import server

    page = TestClient(server.app).get("/campaigns").text
    assert "Earlier result: request-size pause" in page
    assert "latest save covers 12 commands, not 14" in page
    assert "not the spending cap" in page
    assert "Local model compatibility, not gameplay" in page
    assert "two of three supplied test commands exactly" in page
    assert "typed-contract follow-up copied all three exactly" in page
    assert "5,466 and 7,992 prompt tokens without dropping history" in page
    assert "local_llama_adapter_20260906.json" in page
    assert "local_llama_adapter_20260906.json" not in records.PUBLISHED_BUNDLES
    filename = "local_qwen35_9b_feasibility_20260906.json"
    assert filename in page and filename not in records.PUBLISHED_BUNDLES
    candidate = json.loads((records.PROJECT_ROOT / "experiments/evidence" / filename).read_text())
    assert candidate["native_game_loaded"] is False and candidate["native_actions_executed"] == 0
    assert candidate["all_cases_exact"] is False
    assert candidate["usage"]["total_tokens"] == 1207
    assert candidate["usage"]["accounted_responses"] == 3
    assert [case["exact_match"] for case in candidate["cases"]] == [True, True, False]
    assert candidate["cases"][-1]["omitted_field"] == "params.kind"
    assert candidate["teardown"]["independent_listener_closed"] is True
    typed = candidate["typed_follow_up"]
    assert typed["all_cases_exact"] is True and typed["native_actions_executed"] == 0
    assert typed["usage"]["accounted_responses"] == 3
    assert typed["usage"]["total_tokens"] == 5303
    assert typed["fit_diagnostic"]["requests_fit"] == 0
    assert len(typed["fit_diagnostic"]["requests"]) == 14
    assert candidate["combined_diagnostic_usage"]["total_tokens"] == 6510
    assert {
        row["campaign_id"]
        for row in records.campaign_feed(None)["campaigns"]
        if "qwen35" in row["model"]
    } == {
        "local-llama-qwen35-20260906-a",
        "local-thinking-qwen35-20260906-a",
        "local-long-qwen35-20260906-a",
    }


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PUBLISHED_BUNDLES", ("test-bundle.json",))
    bundle = {
        "schema_version": "fortgym.published-campaign-bundle/v1",
        "configuration": CONFIG,
        "source_snapshot_receipt_sha256": "f" * 64,
        "campaigns": [
            {
                "schema_version": "fortgym.public-campaign-state/v1",
                "campaign_id": "test-campaign",
                "segment_id": "segment-000001",
                "model": "test-model",
                "condition_id": "test-condition",
                "code_revision": "a" * 40,
                "configuration_sha256": hashlib.sha256(
                    json.dumps(CONFIG, sort_keys=True).encode()
                ).hexdigest(),
                "updated_at": "2020-01-01T00:00:00+00:00",
                "lifecycle": "finished",
                "segment_status": "bounded_segment_complete",
                "cleanup_verified": True,
                "checkpoint_verified": True,
                "committed_steps": 2,
                "elapsed_ticks": 123,
            }
        ],
    }
    path = tmp_path / "experiments/evidence/test-bundle.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bundle))
    return tmp_path, path, bundle


def test_recorded_results_do_not_claim_live_configuration(published):
    root, _, _ = published
    feed = records.campaign_feed(None, project_root=root)
    assert feed["configured"] is False and feed["published_snapshots"] == 1
    assert feed["campaigns"][0]["publication"] == "versioned_snapshot"
    assert feed["campaigns"][0]["freshness"] == "recorded"
    assert feed["campaigns"][0]["elapsed_ticks"] == 123
    assert feed["campaigns"][0]["declared_starting_snapshot_receipt_sha256"] == "f" * 64
    assert feed["comparison_rankings_available"] is False


def test_published_data_is_reprojected_and_unlisted_files_ignored(published):
    root, path, bundle = published
    bundle["private_path"] = "/private/secret"
    bundle["campaigns"][0].update(
        agent_memory="secret-prompt", current_metrics={"raw": "secret-world"}
    )
    path.write_text(json.dumps(bundle))
    (path.parent / "unlisted.json").write_text('{"private":"unlisted-secret"}')
    output = json.dumps(records.campaign_feed(None, project_root=root))
    assert "secret" not in output and "private_path" not in output and "agent_memory" not in output


@pytest.mark.parametrize(
    "change",
    [
        {"lifecycle": "running"},
        {"cleanup_verified": False},
        {"model": "other-model"},
        {"condition_id": "other-condition"},
        {"configuration_sha256": "b" * 64},
    ],
)
def test_unverified_or_mismatched_snapshot_is_not_published(published, change):
    root, path, bundle = published
    bundle["campaigns"][0].update(change)
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        records.campaign_feed(None, project_root=root)


def test_missing_duplicate_and_oversized_publication_fail(published):
    root, path, bundle = published
    bundle["campaigns"] *= 2
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="identity"):
        records.published_records(root)
    path.write_text(" " * (records.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="bounded"):
        records.published_records(root)
    path.unlink()
    with pytest.raises(ValueError, match="regular"):
        records.published_records(root)


def test_published_data_does_not_mask_broken_live_source(published):
    root, _, _ = published
    with pytest.raises(ValueError):
        records.campaign_feed(root / "missing-live", project_root=root)


def test_matching_live_identity_updates_without_duplicate_or_rollback(published):
    root, path, bundle = published
    live = root / "live"
    initialize_feed(live)
    publisher = CampaignFeed(
        live,
        campaign_id="test-campaign",
        segment_id="segment-000002",
        model="test-model",
        config=CONFIG,
        revision="a" * 40,
    )
    publisher.start()
    feed = records.campaign_feed(live, project_root=root)
    assert feed["configured"] is True and len(feed["campaigns"]) == 1
    assert feed["campaigns"][0]["segment_id"] == "segment-000002"
    bundle["campaigns"][0]["updated_at"] = "2099-01-01T00:00:00+00:00"
    path.write_text(json.dumps(bundle))
    assert (
        records.campaign_feed(live, project_root=root)["campaigns"][0]["publication"]
        == "versioned_snapshot"
    )
    bundle["campaigns"][0]["code_revision"] = "b" * 40
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="identities disagree"):
        records.campaign_feed(live, project_root=root)
