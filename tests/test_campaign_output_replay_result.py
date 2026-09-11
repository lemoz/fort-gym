"""Public diagnostic evidence must not turn missing usage into success."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_published_replay_retains_failed_case_and_unknown_total_usage():
    path = ROOT / "experiments/evidence/local_year_two_output_budget_20260907.json"
    result = json.loads(path.read_text())
    plan = ROOT / "experiments/diagnostics/local_year_two_output_budget_v1.json"
    assert result["plan_sha256"] == hashlib.sha256(plan.read_bytes()).hexdigest()
    diagnostic = result["diagnostic"]
    assert diagnostic["status"] == "stopped_without_retry"
    assert diagnostic["dispatched_requests"] == 2
    assert diagnostic["returned_responses"] == diagnostic["accounted_responses"] == 1
    assert diagnostic["usage_complete"] is False
    first, second = diagnostic["cases"]
    assert first["output_token_allowance"] == 4096
    assert first["status"] == "output_limit"
    assert first["usage"]["total_tokens"] == 8793 + 4096 == 12889
    assert second["output_token_allowance"] == 8192
    assert second["status"] == "failed"
    assert second["usage"]["returned_responses"] == 0
    assert all(case["action_syntax_valid"] is False for case in (first, second))
    assert result["interpretation"]["actual_total_tokens"] is None
    assert result["interpretation"]["larger_output_solves_original_pause"] == "not_established"
    assert result["native_actions_executed"] == result["hosted_provider_calls"] == 0
    assert result["metered_provider_charge_usd"] == "0"
    assert result["hardware_energy_and_app_cost_usd"] is None
    assert result["teardown"]["owned_processes_independently_absent"] is True
    assert result["teardown"]["model_listener_independently_closed"] is True
    assert result["teardown"]["source_file_unchanged"] is True
    public = path.read_text()
    assert not any(value in public for value in ("/Users/", "messages", "reasoning_content"))


def test_reasoning_budget_receipt_is_transport_acceptance_not_gameplay():
    path = ROOT / "experiments/evidence/local_year_two_reasoning_budget_20260907.json"
    result = json.loads(path.read_text())
    condition = ROOT / "experiments/campaigns/local_native_qwen35_year_two_reasoning_budget_v1.json"
    assert result["configuration_file_sha256"] == hashlib.sha256(condition.read_bytes()).hexdigest()
    assert result["only_serialized_request_change"] == {"reasoning_budget_tokens": 2048}
    assert result["finish_reason"] == "stop"
    assert result["diagnostic"]["action_type"] == "DIG"
    assert result["diagnostic"]["action_syntax_valid"] is True
    assert result["diagnostic"]["usage_complete"] is True
    assert result["returned_usage"]["prompt_tokens"] == 8793
    assert result["returned_usage"]["completion_tokens"] == 2210
    assert result["returned_usage"]["total_tokens"] == 11003
    assert result["diagnostic"]["usage"]["total_tokens"] == 11003
    assert result["reasoning_token_usage"] is None
    assert result["scope"]["native_actions_executed"] == 0
    assert result["scope"]["native_legality"] == result["scope"]["native_utility"] == "not_checked"
    assert result["scope"]["campaign_resumed"] is False
    assert result["scope"]["model_ranking_established"] is False
    assert result["teardown"]["owned_processes_independently_absent"] is True
    assert result["teardown"]["model_listener_independently_closed"] is True
    assert result["metered_provider_charge_usd"] == "0"
    public = path.read_text()
    assert not any(value in public for value in ("/Users/", "messages", "reasoning_content"))
