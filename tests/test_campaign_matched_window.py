import hashlib
import json

import pytest

from fort_gym.bench.run.keyboard_config import load_window
from scripts import campaign_matched_window as module

RECORDS = {
    "astra_r1": "59e3fe7a4a3edddcf6a6d1264c748237868b87f71a345d66e2c72c4c183906a1",
    "sol_r1": "0b213a6074777eb5d016cb885bb3df296c4096a8c47e88e43f443eec04142fda",
    "terra_r1": "9670b0e1e542df80f48abbecc39eec3f0e36ba071a0b6d0555d8f86724b92c7b",
    "terra_r2": "8f18ce3a115bc01435cf07fb699fb187a3c3003583e076442775e25b249b0b72",
    "sol_r2": "316a46641bb609350005ae734b74b881ad0d876b9f907fb2fc4eda1964b92ec3",
    "astra_r2": "8bd2a2c69ed08ed4c8c063dd955ae793873899ad24678109404e7b4d5b5a5dfb",
}


def record_path(identity):
    return module.PROJECT / f"experiments/evidence/keyboard_matched_{identity}_20260910.json"


def test_all_six_readiness_projection_binds_each_independent_result():
    path = (
        module.PROJECT
        / "experiments/evidence/keyboard_matched_all_six_continuation_inputs_20260910.json"
    )
    proof = json.loads(path.read_text())
    assert proof["passed"] is proof["full_six_trial_initial_cohort_audited"] is True
    assert proof["new_model_calls"] == proof["new_game_ticks"] == 0
    assert proof["launch_admitted"] is proof["vm_started"] is False
    rows = proof["inputs"]
    assert len(rows) == len(RECORDS) == 6
    assert len({row["checkpoint_sha256"] for row in rows}) == 6
    for identity, expected_digest in RECORDS.items():
        record = json.loads(record_path(identity).read_text())
        row = next(row for row in rows if row["campaign_id"] == record["campaign_id"])
        assert row["public_result_sha256"] == expected_digest == module.sha(record_path(identity))
        assert row["checkpoint_sha256"] == record["checkpoint_sha256"]
        assert row["terminal_audit_sha256"] == record["audit_sha256"]
        assert row["returned_tokens"] == record["usage"]["returned_tokens"]
        assert row["saved_elapsed_ticks"] == record["saved_elapsed_ticks"]
        assert row["model"] == record["model"]
        assert row["cursor"] == row["additional_response_limit"] == 32
        assert row["fresh_native_reload_verified"] is False
        declaration = (
            module.PROJECT
            / "experiments/keyboard_matched_continuations_20260910"
            / (identity + "-32-64.json")
        )
        assert row["declaration_sha256"] == module.sha(declaration)
        assert not {"memory", "agent_state_sha256", "trace_sha256", "usage_sha256"} & row.keys()


@pytest.mark.parametrize("identity", RECORDS)
def test_actual_windows_preserve_own_checkpoint_and_original_condition(tmp_path, identity):
    path = record_path(identity)
    record = json.loads(path.read_text())
    before = {p.name: module.sha(p) for p in module.PLAN.glob("*.json")}
    window = module.prepare(path, RECORDS[identity])
    target = tmp_path / "window.json"
    target.write_text(json.dumps(window))
    condition, parsed = load_window(module.PLAN / window["original_condition"], target)
    assert condition["model"] == record["model"]
    assert parsed["expected_campaign_id"] == record["campaign_id"]
    assert parsed["continuation_checkpoint_sha256"] == record["checkpoint_sha256"]
    assert parsed["source_audit_sha256"] == record["audit_sha256"]
    assert parsed["continuation_from_next_step"] == 32
    assert parsed["steps_per_segment"] == 32 and parsed["max_segments"] == 1
    assert all(parsed[k] is False for k in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert not {"budget_extension", "prompt_change", "restart"} & parsed.keys()
    assert (condition["max_dispatches"], condition["max_total_tokens"]) == (1280, 40000000)
    assert parsed["returned_tokens_before_window"] == record["usage"]["returned_tokens"]
    assert {p.name: module.sha(p) for p in module.PLAN.glob("*.json")} == before
    declared = (
        module.PROJECT
        / "experiments/keyboard_matched_continuations_20260910"
        / (identity + "-32-64.json")
    )
    assert json.loads(declared.read_text()) == window


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "model",
        "replicate",
        "seed",
        "condition",
        "trial",
        "checkpoint",
        "audit",
        "paused",
        "cursor",
        "bool_cursor",
        "unsettled",
        "unknown_tokens",
        "missing_teardown",
        "no_checkpoint",
        "borrowed_usage",
        "rescue",
        "lost_save",
    ],
)
def test_bad_or_unsettled_source_does_not_create_a_window(tmp_path, mutation):
    value = json.loads(record_path("astra_r1").read_text())
    if mutation == "model":
        value["model"] = "gpt-5.6-sol"
    elif mutation == "replicate":
        value["replicate"] = True
    elif mutation in ("seed", "condition", "trial"):
        key = {
            "seed": "seed_receipt_sha256",
            "condition": "condition_file_sha256",
            "trial": "trial_file_sha256",
        }[mutation]
        value["execution"][key] = "f" * 64
    elif mutation in ("checkpoint", "audit"):
        value[mutation + "_sha256"] = "unverified"
    elif mutation == "paused":
        value["status"] = "paused"
    elif mutation in ("cursor", "bool_cursor"):
        value["responses"] = True if mutation == "bool_cursor" else 31
    elif mutation == "unsettled":
        value["usage"]["dispatched_requests"] = 33
    elif mutation == "unknown_tokens":
        value["usage"]["returned_tokens"] = None
    elif mutation == "missing_teardown":
        value["vm_teardown_verified"] = False
    elif mutation == "no_checkpoint":
        value["checkpoint_verified"] = False
    elif mutation == "borrowed_usage":
        value["inherited_usage"] = True
    elif mutation == "rescue":
        value["human_gameplay_rescue"] = True
    elif mutation == "lost_save":
        value["new_native_save_losses"] = 1
    path = tmp_path / "result.json"
    path.write_text(json.dumps(value))
    expected = "0" * 64 if mutation == "digest" else hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        module.prepare(path, expected)
    assert list(tmp_path.iterdir()) == [path]
