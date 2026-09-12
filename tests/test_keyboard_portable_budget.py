"""Budget continuation uses real save/journal machinery and fake game/model data."""

from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.campaign_budget import effective_budget
from fort_gym.bench.agent.keyboard_exchange import digest, publish, read
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.keyboard_docker_audit import audit
from fort_gym.bench.run.keyboard_docker_plan import prepare_inputs
from fort_gym.bench.run.keyboard_docker_watch import baseline
from fort_gym.bench.run import keyboard_docker_recording as recording
from fort_gym.bench.run.keyboard_window_checkpoint_audit import verify_window_checkpoints
from fort_gym.bench.run.keyboard_window_budget import (
    WINDOW_V2, declared_limits, verify_checkpoint_budget,
)
from fort_gym.bench.run.keyboard_window_courier import window_bounds
from scripts import campaign_keyboard_native as native
from tests.test_keyboard_docker_audit import run_fixture, seed, write
from tests.test_keyboard_runtime import CONDITION, saved as saved
from tests.test_keyboard_window_courier import (
    CONDITION as COURIER_CONDITION, WINDOW, FakeExchange, serve,
)


def budget(state):
    return effective_budget(state["configuration"], state.get("budget_extensions", []), state["usage"])


def window(checkpoint, **changes):
    state = read(checkpoint / "agent.json")
    return {
        "schema_version": WINDOW_V2,
        "condition_id": "fixture-budget-extension",
        "original_condition": "condition.json",
        "continuation_checkpoint_sha256": verify_checkpoint(checkpoint)["sha256"],
        "continuation_from_next_step": verify_checkpoint(checkpoint)["payload"]["next_step"],
        "steps_per_segment": 2,
        "max_segments": 1,
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        "budget_before": budget(state),
        "budget_extension": {"max_dispatches": 16, "max_total_tokens": 2000000},
        **changes,
    }


def test_owner_binds_extension_without_modifying_original_save_or_condition(tmp_path, saved):
    checkpoint, _, _ = saved
    paths = tmp_path / "condition.json", tmp_path / "window.json"
    publish(paths[0], CONDITION)
    declaration = window(checkpoint)
    publish(paths[1], declaration)
    before = {p: p.read_bytes() for p in checkpoint.rglob("*") if p.is_file()}
    inputs = prepare_inputs(*paths, checkpoint, "runtime-test", mode="continue")
    assert inputs["condition"] == CONDITION and inputs["limit"] == 2
    state = read(checkpoint / "agent.json")
    expected = verify_checkpoint_budget(state, declaration, inputs["original"]["sha256"])
    assert expected["memory"] == state["memory"] == inputs["initial_memory"]
    assert expected["usage"] == state["usage"]
    assert expected["configuration"] == state["configuration"]
    assert expected["budget_extensions"][-1]["previous"] == declaration["budget_before"]
    assert expected["budget_extensions"][-1]["checkpoint_sha256"] == inputs["original"]["sha256"]
    assert {p: p.read_bytes() for p in before} == before
    assert read(paths[0]) == CONDITION


@pytest.mark.parametrize("change", [
    {"continuation_checkpoint_sha256": "0" * 64},
    {"budget_before": {"max_dispatches": 9, "max_total_tokens": 1000000}},
    {"budget_before": {"max_dispatches": True, "max_total_tokens": 1000000}},
    {"budget_extension": None},
    {"budget_extension": {}},
    {"budget_extension": {"max_dispatches": 16, "max_total_tokens": 1}},
    {"budget_extension": {"max_dispatches": True, "max_total_tokens": 2000000}},
    {"budget_extension": {"max_dispatches": 16, "max_total_tokens": 2000000, "reset": True}},
    {"reset_usage": True}, {"reset_memory": True}, {"strategy_intervention": True},
    {"restart": {}}, {"prompt_change": {}},
])
def test_changed_or_ambiguous_parent_budget_is_rejected(tmp_path, saved, change):
    checkpoint, _, _ = saved
    condition, declaration = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    publish(declaration, window(checkpoint, **change))
    with pytest.raises(ValueError):
        prepare_inputs(condition, declaration, checkpoint, "runtime-test", mode="continue")


def test_extension_cannot_be_applied_twice_at_the_same_checkpoint(saved):
    checkpoint, _, _ = saved
    declaration = window(checkpoint)
    sha = verify_checkpoint(checkpoint)["sha256"]
    state = verify_checkpoint_budget(read(checkpoint / "agent.json"), declaration, sha)
    again = {**declaration, "budget_before": budget(state),
             "budget_extension": {"max_dispatches": 32, "max_total_tokens": 4000000}}
    with pytest.raises(ValueError, match="lineage"):
        verify_checkpoint_budget(state, again, sha)


def test_noop_extension_rejected_but_inherited_budget_is_valid(saved):
    checkpoint, _, _ = saved
    declaration = window(checkpoint)
    with pytest.raises(ValueError, match="increase"):
        declared_limits({**declaration, "budget_extension": declaration["budget_before"]})
    del declaration["budget_extension"]
    original = read(checkpoint / "agent.json")
    expected = verify_checkpoint_budget(
        original, declaration, verify_checkpoint(checkpoint)["sha256"]
    )
    assert expected == original and expected is not original


def test_legacy_courier_still_rejects_extensions_and_v2_obeys_its_exact_limit(tmp_path):
    before = {k: COURIER_CONDITION[k] for k in ("max_dispatches", "max_total_tokens")}
    extended = {**WINDOW, "schema_version": WINDOW_V2,
                "continuation_checkpoint_sha256": "a" * 64,
                "continuation_from_next_step": before["max_dispatches"],
                "steps_per_segment": 2, "max_segments": 1, "budget_before": before,
                "budget_extension": {**before, "max_dispatches": before["max_dispatches"] + 2}}
    assert window_bounds(COURIER_CONDITION, extended)[0] == 2
    exchange = FakeExchange(tmp_path, total=3)
    with pytest.raises(ValueError, match="extra or retried"):
        serve(exchange, window=extended)
    assert exchange.calls == exchange.responded == 2
    with pytest.raises(ValueError):
        window_bounds(COURIER_CONDITION, {**extended, "schema_version": WINDOW["schema_version"]})
    with pytest.raises(ValueError, match="dispatch ceiling"):
        window_bounds(COURIER_CONDITION, {**extended, "steps_per_segment": 3})


def test_native_entry_rejects_wrong_budget_before_starting_runtime(tmp_path, saved, monkeypatch):
    checkpoint, usage, _ = saved
    condition, declaration = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    value = window(checkpoint, budget_before={"max_dispatches": 9, "max_total_tokens": 1000000})
    publish(declaration, value)
    assert load_window(condition, declaration)[1] == value
    monkeypatch.setattr(native, "run_isolated", lambda **kwargs: pytest.fail("Must not start game"))
    args = SimpleNamespace(condition=condition, window=declaration, checkpoint=checkpoint,
                           latest_usage=usage, port=5555, output=tmp_path / "native")
    with pytest.raises(ValueError, match="exact parent"):
        native.run_window(args)
    assert not args.output.exists()


def test_real_save_chain_extends_once_then_inherits_budget_across_windows(tmp_path, monkeypatch):
    origin = seed(tmp_path / "seed")
    options = dict(dispatch_limit=2, token_limit=200)
    fresh, checkpoint = run_fixture(tmp_path / "fresh", origin, "fresh", **options)
    original = {p: p.read_bytes() for p in checkpoint.rglob("*") if p.is_file()}
    extension = {"max_dispatches": 8, "max_total_tokens": 800}
    continuation, second = run_fixture(
        tmp_path / "extension", checkpoint, "continue", segments=2,
        budget_window=True, extension=extension, **options,
    )
    inherited, final = run_fixture(
        tmp_path / "inherited", second, "continue", budget_window=True, **options,
    )
    report = audit([(fresh, origin), (continuation, checkpoint), (inherited, second)])
    assert report["passed"] and report["model_responses"] == 8
    assert report["cumulative_returned_tokens"] == 800
    assert report["reported_charge_usd"] is None
    assert report["windows"][1]["budget_before"] == {"max_dispatches": 2, "max_total_tokens": 200}
    for row in report["windows"][1:]:
        assert row["budget_after"] == extension and row["append_only_budget_history_verified"]
        assert row["memory_usage_and_history_preserved"]
    assert report["windows"][2]["budget_extension"] is None
    state = read(final / "agent.json")
    assert state["configuration"]["max_dispatches"] == 2
    assert len(state["budget_extensions"]) == 1 and state["usage"]["total_tokens"] == 800
    assert state["memory"] == "PRIVATE_MODEL_MEMORY" * 8
    assert {p: p.read_bytes() for p in original} == original
    assert (final / "trace.jsonl").read_bytes().startswith((checkpoint / "trace.jsonl").read_bytes())
    assert baseline(continuation)["saved_checkpoint_cursor"] == 2
    assert baseline(inherited)["saved_checkpoint_cursor"] == 6
    report_path = tmp_path / "audit.json"
    write(report_path, report)
    replay = recording.export(
        [fresh, continuation, inherited], report_path, recording.sha(report_path),
        identity="extended-fixture", title="Fixture only",
    )
    assert len(replay["frames"]) == 8 and replay["saved_through_decision"] == 8
    genuine_verify = recording.verify_checkpoint

    def mismatched_intermediate(path):
        value = genuine_verify(path)
        if path == continuation / "game/native/segment-0/checkpoint":
            return {**value, "sha256": "0" * 64}
        return value

    with monkeypatch.context() as patch:
        patch.setattr(recording, "verify_checkpoint", mismatched_intermediate)
        with pytest.raises(ValueError, match="segments are not consecutive own saves"):
            recording.export(
                [fresh, continuation, inherited], report_path, recording.sha(report_path),
                identity="bad-chain", title="Fixture only",
            )
    with pytest.raises(ValueError, match="dispatch ceiling"):
        run_fixture(tmp_path / "overrun", final, "continue", budget_window=True, **options)


def test_auditor_rejects_declared_extension_that_native_worker_did_not_apply(tmp_path):
    original = seed(tmp_path / "seed")
    fresh, checkpoint = run_fixture(tmp_path / "fresh", original, "fresh")
    continuation, _ = run_fixture(
        tmp_path / "continue", checkpoint, "continue", budget_window=True,
    )
    declaration_path = continuation / "inputs/declaration.json"
    declaration = read(declaration_path)
    declaration["budget_extension"] = {"max_dispatches": 16, "max_total_tokens": 2000000}
    write(declaration_path, declaration)
    write(continuation / "game/native/window.json", declaration)
    owner_path = continuation / "owner-plan.json"
    plan = read(owner_path)
    plan["declaration_sha256"] = digest(declaration)
    write(owner_path, plan)
    with pytest.raises(ValueError, match="bound agent state"):
        audit([(fresh, original), (continuation, checkpoint)])


def test_native_declaration_cannot_exceed_the_effective_dispatch_budget(tmp_path, saved):
    checkpoint, _, _ = saved
    condition, declaration = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    publish(declaration, window(checkpoint, steps_per_segment=16))
    with pytest.raises(ValueError, match="dispatch ceiling"):
        load_window(condition, declaration)


def test_private_window_audit_verifies_the_same_append_only_extension(tmp_path):
    origin = seed(tmp_path / "seed")
    options = dict(dispatch_limit=2, token_limit=200)
    _, checkpoint = run_fixture(tmp_path / "fresh", origin, "fresh", **options)
    continuation, _ = run_fixture(
        tmp_path / "extension", checkpoint, "continue", segments=2, budget_window=True,
        extension={"max_dispatches": 8, "max_total_tokens": 800}, **options,
    )
    native_path = continuation / "game/native"
    declaration = read(native_path / "window.json")
    declaration.update(
        expected_campaign_id="portable-audit-fixture",
        source_native_revision="b" * 40, window_end_decision=6,
        accounted_responses_before_window=2, returned_tokens_before_window=200,
        saved_elapsed_ticks_before_window=20,
    )
    write(native_path / "window.json", declaration)
    from fort_gym.bench.eval.campaign_profile import metrics_from_state

    report = verify_window_checkpoints(
        native_path, checkpoint, condition=read(native_path / "condition.json"),
        window=declaration,
        initial_metrics=metrics_from_state(read(native_path / "segment-0/native-before.json")),
    )
    assert report["new_responses"] == 4 and report["usage"]["total_tokens"] == 600
    assert report["segments"][0]["final_fresh_reload_verified"] is True
