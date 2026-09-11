"""Preparation invariants only; these checks cannot establish native acceptance."""

import ast
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
    assert "mandatory" not in readme or "teardown" in readme
