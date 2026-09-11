"""Preparation invariants only; these checks cannot establish native acceptance."""

import ast
import hashlib
import json
from pathlib import Path


DIRECTORY = (
    Path(__file__).resolve().parents[1] / "experiments/keyboard_binding_integration_20260911"
)


def source():
    return (DIRECTORY / "fixture.py").read_text()


def test_committed_adapter_and_checkpoint_are_explicit():
    value = source()
    ast.parse(value)
    assert "8b9fffa1de4f93506cbcbdf82fd154aeb17b5697" in value
    assert "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342" in value
    assert "control_profile=BINDING_PROFILE" in value
    assert "env.apply(" in value
    assert "execute_binding_keys(" not in value
    assert "event_set.lua" not in value


def test_sequence_tests_navigation_and_mixed_case_text():
    tree = ast.parse(source())
    labels = [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "press"
        and len(node.args) == 2
    ]
    assert len(labels) == 14 and len(set(labels)) == 14
    assert {
        "query-enter",
        "query-exit",
        "cursor-left",
        "cursor-right",
        "queue-bed",
        "name-type",
        "name-backspace",
        "name-enter",
        "final-exit",
    } <= set(labels)
    assert "FgAb7" in source() and "ConstructBed" in source()


def test_declared_limits_preserve_scored_evidence():
    value = source()
    assert "checkpoint_copies=0" in value and "screen_size=(120, 40)" in value
    assert '"native_saves_requested": 0' in value
    assert '"model_calls": 0' in value and '"autonomous_gameplay": False' in value
    assert '"human_edited_copy_eligible_for_campaign": False' in value
    probe = (DIRECTORY / "menu_probe.lua").read_text()
    assert "df.global.pause_state==true" in probe
    assert "df.global.cur_year==30 and df.global.cur_year_tick==152201" in probe
    assert "target.name=" not in probe and "simulateInput" not in probe


def test_predeclared_scope_does_not_claim_cancellation_or_autonomy():
    readme = (DIRECTORY / "README.md").read_text()
    assert "not cancellation semantics" in readme
    assert "must never become a scored campaign origin" in readme


def result():
    return json.loads(
        (DIRECTORY.parent / "evidence/keyboard_binding_integration_20260911.json").read_text()
    )


def test_executed_public_sources_stay_byte_identical():
    record = result()
    for name in ("fixture.py", "menu_probe.lua", "Dockerfile.v2", "review.py"):
        assert (
            hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest()
            == record["context_sha256"][name]
        )
    assert (DIRECTORY / "Dockerfile").read_text().startswith("FROM sha256:")
    assert (
        (DIRECTORY / "Dockerfile.v2")
        .read_text()
        .startswith("FROM fortgym-campaign:checkpoint-1057-production-reload-v1\n")
    )


def test_passing_native_controls_are_not_scored_gameplay():
    record = result()
    assert record["status"] == "passed" and record["scope"]["native_environment_apply"]
    assert record["scope"]["operator_reset_reveal_and_workshop_positioning"]
    for field in (
        "autonomous_navigation",
        "autonomous_gameplay",
        "model_performance_claim",
        "physical_keyboard_equivalence_claim",
        "naming_escape_cancellation_tested",
        "human_edited_copy_eligible_for_campaign",
    ):
        assert record["scope"][field] is False
    assert record["outcomes"]["action_batches"] == 14 and record["outcomes"]["key_presses"] == 18
    assert record["outcomes"]["native_workshop_name"] == "FgAb"
    assert [job["type"] for job in record["outcomes"]["new_jobs"]] == ["ConstructBed"]
    assert not any(record["delivery"].values())


def test_failed_packaging_and_both_teardowns_remain_visible():
    record = result()
    assert [row["version"] for row in record["attempts"]] == [1, 2]
    assert record["attempts"][0]["status"] == "image_build_failed_before_game"
    assert record["attempts"][1]["status"] == "passed"
    assert all(row["vm_teardown_verified"] for row in record["attempts"])
    resources = record["resources"]
    assert resources["sequential_vm_starts"] == 2
    assert resources["simultaneously_running_vms_max"] == 1
    assert resources["live_vm_stopped_verified"] and resources["vm_config_unchanged"]
    assert resources["model_calls"] == resources["metered_provider_charge_usd"] == 0
    assert resources["native_saves_requested"] == resources["new_scored_campaign_checkpoints"] == 0
    assert resources["hardware_energy_and_app_cost_usd"] is None
