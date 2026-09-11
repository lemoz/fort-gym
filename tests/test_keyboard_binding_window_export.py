"""Reject unbound sources before reading private experiment evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "binding_window_export",
    ROOT / "experiments/keyboard_binding_continuation_20260911/export_window.py",
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


@pytest.mark.parametrize(
    "field,value",
    [
        ("audit_sha", "unverified"),
        ("source_sha", ""),
        ("owner_name", "../checkpoint"),
        ("owner_name", "keyboard-bindings-astra-r1-reload-v1"),
        ("source_result", "../private.json"),
        ("source_result", "unrelated.json"),
        ("reviewer_name", "../terminal_review.py"),
        ("reviewer_name", "operator.py"),
    ],
)
def test_rejects_unbound_or_unrelated_source(field, value):
    args = dict(
        audit_sha="a" * 64,
        owner_name="keyboard-bindings-astra-r1-64-96-v1",
        source_result="keyboard_binding_astra_r1_continuation_32_64_20260911.json",
        source_sha="b" * 64,
    )
    args[field] = value
    with pytest.raises(AssertionError):
        export.build(**args)


def test_unverified_parent_cannot_produce_result():
    with pytest.raises(AssertionError):
        export.build(
            "a" * 64,
            owner_name="keyboard-bindings-astra-r1-64-96-v1",
            source_result="keyboard_binding_astra_r1_continuation_32_64_20260911.json",
            source_sha="b" * 64,
        )


def test_continuation_condition_requires_exact_equality():
    prior = {
        "schema_version": "fortgym.public-keyboard-binding-continuation-result/v1",
        "condition": {"model": "gpt-6-astra", "max_dispatches": 1280},
    }
    export.verify_condition(dict(prior["condition"]), prior)
    with pytest.raises(AssertionError):
        export.verify_condition({**prior["condition"], "max_dispatches": 1281}, prior)


def test_trial_condition_requires_pinned_full_file(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "WORKTREE", tmp_path)
    relative = "experiments/keyboard_bindings_20260911/astra-condition.json"
    condition = dict(
        model="gpt-6-astra",
        reasoning_effort="medium",
        transport="codex-exec-chatgpt/v1",
        control_profile="native_keyboard_bindings/v1",
        prompt_profile="native_keyboard_binding_instructions/v1",
        screen_size=[120, 40],
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(condition))
    summary = {
        **condition,
        "condition_path": relative,
        "config_sha256": {path.name: export.sha(path)},
        "starting_boundary": {"screen_size": [120, 40]},
    }
    prior = {
        "schema_version": "fortgym.public-keyboard-binding-trial-result/v1",
        "condition": summary,
    }
    export.verify_condition(condition, prior)
    path.write_text(json.dumps({**condition, "model": "different"}))
    with pytest.raises(AssertionError):
        export.verify_condition(condition, prior)


def test_unknown_result_schema_rejected():
    with pytest.raises(AssertionError):
        export.verify_condition({}, {"schema_version": "unknown", "condition": {}})
