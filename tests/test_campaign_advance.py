"""Clock policy regressions use deterministic doubles, not gameplay evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fort_gym.bench.run.campaign_advance import ACCEPTED_ONLY, MODEL_REQUESTED, requested_ticks
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
from fort_gym.bench.run.campaign_loop import CampaignLoop
from tests.test_campaign_loop import TestAgent, TestEnvironment
from tests.test_campaign_local import CONFIG, MODEL, packed_config
from fort_gym.bench.run.campaign_config import load_segment_config
from fort_gym.bench import dfhack_backend


@pytest.mark.parametrize("ticks", [0, 200, 2000])
def test_clock_uses_only_model_requested_time(ticks):
    rejection = {"accepted": False, "result": {"ok": False, "command_mutation": "not_attempted"}}
    for policy in (ACCEPTED_ONLY, MODEL_REQUESTED):
        assert requested_ticks(ticks, {"accepted": True}, policy) == ticks
    assert requested_ticks(ticks, rejection, ACCEPTED_ONLY) == 0
    assert requested_ticks(ticks, rejection, MODEL_REQUESTED) == ticks
    assert (
        requested_ticks(
            ticks, {"accepted": False, "command_mutation": "not_attempted"}, MODEL_REQUESTED
        )
        == ticks
    )


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"ok": False},
        {"ok": False, "command_mutation": "attempted"},
        {"ok": False, "rollback_verified": True, "command_mutation": "attempted"},
        {"partial": True, "placed_count": 1, "command_mutation": "attempted"},
    ],
)
def test_uncertain_or_partial_execution_does_not_get_extra_time(result):
    with pytest.raises(ValueError, match="definite"):
        requested_ticks(2000, {"accepted": False, "result": result}, MODEL_REQUESTED)


def test_native_adapter_labels_only_resultless_python_rejections():
    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    for result in [
        {"accepted": False, "why": "Python validation"},
        {"accepted": False, "why": "native error", "result": {"ok": False}},
    ]:
        env.executor = SimpleNamespace(apply=lambda *a, **kw: deepcopy(result))
        actual = env.apply({}, {})
        if "result" not in result:
            assert actual["command_mutation"] == "not_attempted"
        else:
            assert actual == result


def test_python_helper_receipt_does_not_turn_transport_errors_into_preflight(monkeypatch):
    def dispatch_error(*args, **kwargs):
        raise dfhack_backend.DFHackError("test-only transport error")

    monkeypatch.setattr(dfhack_backend, "run_lua_file", dispatch_error)
    preflight = dfhack_backend.build_construction("Wall", 0, 0, 0, 20, 0)
    assert preflight["command_mutation"] == "not_attempted"
    failed = dfhack_backend.build_construction("Wall", 0, 0, 0)
    assert failed == {"ok": False, "error": "test-only transport error"}
    with pytest.raises(ValueError, match="definite"):
        requested_ticks(200, {"accepted": False, "result": failed}, MODEL_REQUESTED)


def test_requested_time_is_model_visible_checkpointed_and_continuable(tmp_path):
    class RejectedEnvironment(TestEnvironment):
        def apply(self, action, state):
            self.actions.append(deepcopy(action))
            return {
                "accepted": False,
                "why": "path_cache_stale",
                "result": {
                    "ok": False,
                    "error": "path_cache_stale",
                    "command_mutation": "not_attempted",
                },
            }

    env = RejectedEnvironment()
    loop = CampaignLoop(
        campaign_id="requested-time-test",
        agent=TestAgent(),
        environment=env,
        output=tmp_path / "first",
        observation_profile="campaign_state/v1",
        advance_policy=MODEL_REQUESTED,
    )
    row = loop.step()
    assert row["action"]["advance_ticks"] == row["tick_advance"]["ticks_advanced"] == 200
    assert row["execute"]["accepted"] is False
    assert row["observation"]["time_control"]["policy"] == MODEL_REQUESTED
    assert "preflight rejection" in row["observation_text"]
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=env, code_revision="test")
    assert json.loads((checkpoint / "runner.json").read_text())["advance_policy"] == MODEL_REQUESTED
    with pytest.raises(ValueError, match="advance policy differs"):
        CampaignLoop.resume(
            checkpoint,
            agent=TestAgent(),
            environment=env,
            output=tmp_path / "wrong",
            latest_usage_path=loop.journal,
            advance_policy=ACCEPTED_ONLY,
        )
    assert not (tmp_path / "wrong").exists()
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=TestAgent(),
        environment=env,
        output=tmp_path / "second",
        latest_usage_path=loop.journal,
        advance_policy=MODEL_REQUESTED,
    )
    assert resumed.step()["step"] == 1
    assert resumed.committed_elapsed_ticks == 400 and len(env.actions) == 2


def test_partial_execution_retains_failure_without_advancing(tmp_path, monkeypatch):
    env = TestEnvironment()
    partial = {
        "accepted": False,
        "result": {"ok": False, "partial": True, "command_mutation": "attempted"},
    }
    monkeypatch.setattr(env, "apply", lambda *a: partial)
    monkeypatch.setattr(
        env, "advance", lambda *a: pytest.fail("Must not advance uncertain execution")
    )
    loop = CampaignLoop(
        campaign_id="partial-test",
        agent=TestAgent(),
        environment=env,
        output=tmp_path / "campaign",
        observation_profile="campaign_state/v1",
        advance_policy=MODEL_REQUESTED,
    )
    with pytest.raises(ValueError, match="definite"):
        loop.step()
    failure = json.loads((loop.output / "failures.jsonl").read_text())
    assert failure["execute"] == partial and failure["action"]["advance_ticks"] == 200
    assert loop.failed and not loop.at_boundary and loop.next_step == 0


@pytest.mark.parametrize("value", ["unknown/v1", False, None, [], {}])
def test_configuration_rejects_unknown_time_semantics(tmp_path, value):
    config = packed_config()
    config["advance_policy"] = value
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="advance policy"):
        load_segment_config(path, MODEL)


def test_repair_condition_preserves_comparison_bounds_and_declares_both_changes():
    previous = packed_config()
    new = load_segment_config(CONFIG.with_name("local_native_harness_repair_v1.json"), MODEL)
    for key in previous.keys() - {"condition_id", "hypothesis", "notes", "local_inference"}:
        assert new[key] == previous[key]
    assert new["advance_policy"] == MODEL_REQUESTED
    assert new["local_inference"] == {
        **previous["local_inference"],
        "prompt_packing": "bounded_history_corrections/v1",
    }
