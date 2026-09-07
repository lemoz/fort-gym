import json
import hashlib
from copy import deepcopy

import pytest

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent, SUBSCRIPTION_COST_BASIS
from fort_gym.bench.agent.codex_transport import MODEL, REASONING_EFFORT, CodexTransportError
from fort_gym.bench.agent.codex_protocol import TRANSPORT
from fort_gym.bench.env.native_key_catalog import NATIVE_PROFILE
from fort_gym.bench.env.screen_observation import TEXT_PROFILE, encode_screen
from fort_gym.bench.run.campaign_loop import (
    CampaignLoop,
    CampaignPreDispatchPause,
    reconciled_usage,
)
from fort_gym.bench.run.campaign_save import save_inventory


def decision(screen, memory, feedback):
    return {
        "screen_sha256": hashlib.sha256(
            json.dumps(
                encode_screen(screen, TEXT_PROFILE),
                allow_nan=False,
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "action": {
            "type": "KEYSTROKE",
            "params": {"keys": ["D_BUILDING"] if not memory else ["LEAVESCREEN"]},
            "advance_ticks": 10,
            "intent": "model fixture",
            "memory_update": memory + "x",
        },
        "action_grammar_valid": True,
        "control_profile": NATIVE_PROFILE,
        "observation_profile": TEXT_PROFILE,
        "transport_receipt": {
            "accepted": True,
            "dispatched": True,
            "total_tokens": 100,
            "usage": [{"input_tokens": 90, "output_tokens": 10}],
            "model_requested": MODEL,
            "reasoning_effort_requested": REASONING_EFFORT,
            "auth_mode": "chatgpt",
            "transport": TRANSPORT,
            "reported_charge_usd": None,
        },
    }


class Environment:
    control_profile = NATIVE_PROFILE

    def __init__(self):
        self.tick = 123
        self.actions = []

    def observe(self):
        return {
            "year": 30,
            "year_tick": self.tick,
            "pause_state": True,
            "population": 7,
            "hidden": "do not send to model",
        }

    def screen_capture(self):
        return {"width": 1, "height": 1, "tiles": [[65, 7, 0]]}

    def screen(self):
        pytest.fail("Keyboard mode must use the declared native capture")

    def apply(self, action, state):
        self.actions.append(deepcopy(action))
        return {"accepted": True, "result": {"keys_confirmed": 1, "command_mutation": "completed"}}

    def advance(self, ticks, state):
        self.tick += ticks
        return self.observe(), {"ok": True, "ticks_advanced": ticks}

    def capture(self, directory):
        directory.mkdir()
        (directory / "world.sav").write_text(str(self.tick))
        return {
            "schema_version": "fortgym.native-save-snapshot/v1",
            "save_name": "fixture",
            "year": 30,
            "year_tick": self.tick,
            "paused": True,
            "files": save_inventory(directory),
        }


def agent(callback=decision, limit=8):
    return CodexKeyboardAgent(decision=callback, max_dispatches=limit, max_total_tokens=10000)


def start(tmp_path, callback=decision, limit=8):
    return CampaignLoop(
        campaign_id="keyboard-test",
        agent=agent(callback, limit),
        environment=Environment(),
        output=tmp_path / "first",
        observation_profile=TEXT_PROFILE,
    )


def test_keyboard_uses_capture_and_execution_feedback_without_hidden_metrics(tmp_path):
    observations = []

    def callback(screen, memory, feedback):
        observations.append((screen, memory, feedback))
        return decision(screen, memory, feedback)

    loop = start(tmp_path, callback)
    first, second = loop.step(), loop.step()
    assert first["action"]["params"]["keys"] == ["D_BUILDING"]
    assert second["action"]["params"]["keys"] == ["LEAVESCREEN"]
    assert len(loop.environment.actions) == 2
    assert "hidden" not in json.dumps(observations)
    assert observations[1][1] == "x"
    assert observations[1][2]["keys_confirmed"] == 1
    usage = loop.agent.export_campaign_state()["usage"]
    assert usage["total_tokens"] == 200 and usage["dispatched_requests"] == 2
    assert usage["total_cost_usd"] is None and usage["cost_basis"] == SUBSCRIPTION_COST_BASIS


def test_checkpoint_resume_keeps_memory_usage_and_never_replays_old_action(tmp_path):
    loop = start(tmp_path)
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="fixture")
    environment = Environment()
    environment.tick = int((checkpoint / "game/world.sav").read_text())
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=agent(),
        environment=environment,
        output=tmp_path / "second",
        latest_usage_path=loop.journal,
    )
    assert environment.actions == []
    assert resumed.step() == loop.step()
    assert [a["params"]["keys"] for a in environment.actions] == [["LEAVESCREEN"]]
    assert resumed.agent.memory == "xx"
    assert resumed.agent.usage["total_tokens"] == 200
    assert resumed.agent.usage["total_cost_usd"] is None


def test_cumulative_bound_stops_before_next_model_or_native_call(tmp_path):
    loop = start(tmp_path, limit=1)
    loop.step()
    with pytest.raises(CampaignPreDispatchPause):
        loop.step()
    assert len(loop.environment.actions) == 1
    assert loop.at_boundary
    assert not loop.failed


@pytest.mark.parametrize("mutation", ["model", "grammar", "usage", "auth"])
def test_failed_decision_retains_usage_without_native_dispatch(tmp_path, mutation):
    def callback(*args):
        result = decision(*args)
        if mutation == "model":
            result["transport_receipt"]["model_requested"] = "wrong"
        elif mutation == "auth":
            result["transport_receipt"]["auth_mode"] = "apikey"
        elif mutation == "grammar":
            result["action"] = {"type": "ORDER"}
        else:
            result["transport_receipt"]["total_tokens"] = None
        return result

    loop = start(tmp_path, callback)
    with pytest.raises((ValueError, CodexTransportError)):
        loop.step()
    assert not loop.environment.actions and loop.failed
    assert loop.agent.usage["total_tokens"] == (0 if mutation == "usage" else 100)
    with pytest.raises(ValueError):
        reconciled_usage(loop.agent.export_campaign_state(), loop.journal.read_bytes())


def test_subscription_cost_cannot_be_silently_rewritten_to_zero(tmp_path):
    loop = start(tmp_path)
    loop.step()
    records = [json.loads(line) for line in loop.journal.read_text().splitlines()]
    records[-1]["usage"]["total_cost_usd"] = "0"
    raw = "".join(json.dumps(row) + "\n" for row in records).encode()
    with pytest.raises(ValueError, match="unreported"):
        reconciled_usage(loop.agent.export_campaign_state(), raw)


def test_mismatched_native_condition_is_rejected_before_output(tmp_path):
    environment = Environment()
    environment.control_profile = "dfhack_shortcuts/v1"
    with pytest.raises(ValueError, match="profiles must match"):
        CampaignLoop(
            campaign_id="keyboard-test",
            agent=agent(),
            environment=environment,
            output=tmp_path / "no-output",
            observation_profile=TEXT_PROFILE,
        )
    assert not (tmp_path / "no-output").exists()
