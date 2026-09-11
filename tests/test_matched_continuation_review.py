"""Contract tests for continuation audits/exports, not native gameplay evidence."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/keyboard_binding_comparison_continuations_20260911"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    return importlib.import_module("terminal_review"), importlib.import_module("publish_result")


@pytest.fixture
def control():
    value = {
        "provider_calls_complete": True,
        "vm_observed_stopped": True,
        "vm_config_unchanged": True,
        "original_checkpoint_verified_unchanged": True,
        "guest_poweroff_returncode": 0,
    }
    for tag in (
        "container-stop",
        "container-log",
        "container-final-state",
        "evidence-copy",
        "vm_stop",
    ):
        value[tag + "_returncode"] = 0
    return value


def test_guest_disconnect_warns_only_when_actual_vm_stop_is_verified(modules, control):
    review, _ = modules
    control["guest_poweroff_returncode"] = 1
    result = review.verify_teardown(control)
    assert result["guest_command_warning"] is True
    assert result["vm_observed_stopped"] is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("provider_calls_complete", False),
        ("vm_observed_stopped", False),
        ("vm_config_unchanged", False),
        ("original_checkpoint_verified_unchanged", False),
        ("container-stop_returncode", 1),
        ("container-log_returncode", None),
        ("container-final-state_returncode", False),
        ("evidence-copy_returncode", 1),
        ("vm_stop_returncode", 1),
        ("guest_poweroff_returncode", None),
        ("container_cleanup_error_type", "RuntimeError"),
    ],
)
def test_incomplete_or_failed_cleanup_cannot_be_certified(modules, control, key, value):
    control[key] = value
    with pytest.raises(ValueError):
        modules[0].verify_teardown(control)


@pytest.fixture
def key_receipt():
    state = {"paused": True, "year": 30, "year_tick": 19701, "save_name": "own-fort"}
    action = {"type": "KEYSTROKE", "params": {"keys": ["d"]}}
    condition = {"control_profile": "native_keyboard_bindings/v1", "bindings_sha256": "a" * 64}
    receipt = {
        "events": ["D_DESIGNATE"],
        "ok": True,
        "input_calls": 1,
        "command_mutation": "completed",
        "before": deepcopy(state),
        "after": deepcopy(state),
    }
    result = {
        **condition,
        "keys_sent": 1,
        "keys_confirmed": 1,
        "native_receipts": [{"key": "d", "events": ["D_DESIGNATE"], "receipt": receipt}],
    }
    record = {"action": deepcopy(action), "execute": {"accepted": True, "result": result}}
    index = SimpleNamespace(sha256=condition["bindings_sha256"], resolve=lambda _: ["D_DESIGNATE"])
    return record, action, condition, index, lambda value: value


def test_exact_key_receipt_is_counted(modules, key_receipt):
    assert modules[0].verify_keys(*key_receipt) == 1


@pytest.mark.parametrize(
    "field,value", [("paused", False), ("year_tick", 19702), ("save_name", "peer")]
)
def test_key_receipt_cannot_advance_time_or_use_another_save(modules, key_receipt, field, value):
    receipt = key_receipt[0]["execute"]["result"]["native_receipts"][0]["receipt"]
    receipt["after"][field] = value
    with pytest.raises(ValueError, match="simulation boundary"):
        modules[0].verify_keys(*key_receipt)


@pytest.mark.parametrize(
    "field,value", [("ok", False), ("events", ["OTHER"]), ("input_calls", True)]
)
def test_unconfirmed_native_key_receipt_fails(modules, key_receipt, field, value):
    key_receipt[0]["execute"]["result"]["native_receipts"][0]["receipt"][field] = value
    with pytest.raises(ValueError, match="receipt differs"):
        modules[0].verify_keys(*key_receipt)


def test_rejected_model_response_remains_rejected(modules):
    record = {"action": None, "execute": {"accepted": False}}
    assert modules[0].verify_keys(record, None, {}, None, None) == 0
    record["execute"]["accepted"] = True
    with pytest.raises(ValueError, match="became an action"):
        modules[0].verify_keys(record, None, {}, None, None)


@pytest.fixture
def export():
    window = json.loads((BASE / "sol-r1-window-64-128.json").read_text())
    report = {
        "schema_version": "fortgym.private-matched-window-terminal-review/v1",
        "passed": True,
        "campaign_id": window["expected_campaign_id"],
        "model": "gpt-5.6-sol",
        "replicate": 1,
        "reasoning_effort": "medium",
        "source_revision": window["source_native_revision"],
        "image_id": window["source_image_id"],
        "source_checkpoint_sha256": window["continuation_checkpoint_sha256"],
        "first_step": 64,
        "next_step": 128,
        "responses": 128,
        "new_responses": 64,
        "status": "completed",
        "stop_reason": "segment_limit",
        "usage": {"accounted_responses": 128, "total_tokens": 1259331},
        "new_tokens": 1010,
        "saved_elapsed_ticks": 3000,
        "new_saved_elapsed_ticks": 100,
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "human_gameplay_rescue": False,
        "checkpoint_sha256": "b" * 64,
        "saved_metrics": {"population": 7, "wood_stock": None},
        "source_checkpoint_fresh_load_verified": True,
        "fresh_final_checkpoint_reload_verified": False,
        "confirmed_key_presses": 64,
        "clock_outcomes": {"no_error": 64},
        "private_memory": "must never be exported",
        "sources": {"/private/raw/provider/receipt.json": "secret"},
    }
    return report, window, "c" * 64


def test_public_export_has_no_raw_memory_paths_or_false_success_claim(modules, export):
    value = modules[1].project(*export)
    assert value["responses"] == 128 and value["response_limit"] == 128
    assert value["checkpoint"]["metrics"]["wood_stock"] is None
    assert value["reported_charge_usd"] is None
    assert value["assessment"]["gameplay_success_assessment"] == "not_inferred_by_export"
    assert value["assessment"]["strong_model_ranking_supported"] is False
    assert "private" not in json.dumps(value) and "secret" not in json.dumps(value)


@pytest.mark.parametrize("count", [64, 79, 127])
def test_paused_save_remains_partial_at_128_boundary(modules, export, count):
    report, _, _ = export
    report.update(
        status="paused",
        stop_reason="budget_limited_pause",
        next_step=count,
        responses=count,
        new_responses=count - 64,
    )
    report["usage"]["accounted_responses"] = count
    value = modules[1].project(*export)
    assert value["status"] == "budget_limited_pause"
    assert value["checkpoint"]["next_step"] == count
    assert value["response_limit"] == 128


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "gpt-6-astra"),
        ("replicate", 2),
        ("replicate", True),
        ("reasoning_effort", "low"),
        ("source_checkpoint_sha256", "d" * 64),
        ("next_step", 127),
        ("responses", 127),
        ("new_tokens", 0),
        ("new_saved_elapsed_ticks", 0),
        ("vm_teardown_verified", False),
        ("human_gameplay_rescue", True),
        ("passed", False),
        ("stop_reason", "infrastructure_failure"),
        ("source_checkpoint_fresh_load_verified", False),
        ("fresh_final_checkpoint_reload_verified", True),
    ],
)
def test_public_export_rejects_mismatched_or_unsettled_result(modules, export, key, value):
    export[0][key] = value
    with pytest.raises(ValueError):
        modules[1].project(*export)
