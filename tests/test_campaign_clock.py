"""Elapsed-time observations: synthetic loop tests, not native gameplay proof."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from fort_gym.bench.agent.campaign_context import pack_messages, project_observation
from fort_gym.bench.env.campaign_encoder import (
    CLOCK_PROFILE,
    PROFILE,
    campaign_clock,
    encode_campaign_observation,
)
from fort_gym.bench.eval.campaign import TICKS_PER_YEAR
from fort_gym.bench.run.campaign_config import load_segment_config
from fort_gym.bench.run.campaign_loop import CampaignLoop
from tests.test_campaign_loop import TestAgent, TestEnvironment


def encode(*, profile=CLOCK_PROFILE, elapsed=None, decisions=0):
    return encode_campaign_observation(
        {
            "year": 30,
            "year_tick": 220140,
            "population": 9,
            "stocks": {"drink": 25},
            "campaign_clock": {"elapsed_ticks": 999999999},  # Not an authoritative source.
        },
        screen_text="test-only native screen",
        action_history=[],
        last_action_result=None,
        model_requested_time=True,
        profile=profile,
        committed_elapsed_ticks=elapsed,
        completed_decisions=decisions,
    )


def test_historical_v1_observation_bytes_are_unchanged():
    text, observed = encode(profile=PROFILE, elapsed=203339, decisions=83)
    assert "campaign_clock" not in observed
    # Captured before this change from the existing v1 encoder, not regenerated.
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "98421d661ead8a356ad2f0faebb79f9a1be230e539b39cc74cc373c9be261d0c"
    )
    assert hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest() == (
        "cb838e1db6c174dfcfbaa80d831044e9c4794300eb040a2845fa92d4c0a579f9"
    )


@pytest.mark.parametrize(
    "elapsed,years,current,remainder",
    [
        (0, 0, 1, 0),
        (203339, 0, 1, 203339),
        (403199, 0, 1, 403199),
        (403200, 1, 2, 0),
        (403201, 1, 2, 1),
        (806400, 2, 3, 0),
        (None, None, None, None),
    ],
)
def test_clock_distinguishes_elapsed_years_from_world_year(elapsed, years, current, remainder):
    text, observed = encode(elapsed=elapsed, decisions=83)
    clock = observed["campaign_clock"]
    assert observed["year"] == 30 and observed["year_tick"] == 220140
    assert observed["observation_profile"] == CLOCK_PROFILE
    assert clock["elapsed_ticks"] == elapsed
    assert clock["ticks_per_year"] == TICKS_PER_YEAR == 403200
    assert clock["completed_elapsed_years"] == years
    assert clock["current_elapsed_year"] == current
    assert clock["ticks_into_current_elapsed_year"] == remainder
    assert clock["completed_decisions"] == 83
    assert (clock["time_evidence"] == "unknown") == (elapsed is None)
    assert "not a fortress-success verdict" in text
    assert text.splitlines()[0] == "Native calendar: year=30 tick=220140"
    assert text.splitlines()[3] == "Last Action: UNKNOWN"
    assert "Campaign elapsed:" in text.splitlines()[4]


@pytest.mark.parametrize("invalid", [True, False, -1, 1.0, "100", [], {}])
@pytest.mark.parametrize("field", ["elapsed", "decisions"])
def test_invalid_clock_counters_do_not_become_facts(invalid, field):
    with pytest.raises(ValueError, match="counters"):
        campaign_clock(invalid if field == "elapsed" else 0, invalid if field == "decisions" else 0)


class RolloverEnvironment(TestEnvironment):
    def advance(self, ticks, state):
        absolute = self.state["year"] * TICKS_PER_YEAR + self.state["year_tick"] + ticks
        self.state["year"], self.state["year_tick"] = divmod(absolute, TICKS_PER_YEAR)
        return self.observe(), {"ok": True, "ticks_advanced": ticks}


def start(tmp_path, *, profile=CLOCK_PROFILE, agent=None, environment=None):
    return CampaignLoop(
        campaign_id="clock-test",
        agent=agent or TestAgent(),
        environment=environment or RolloverEnvironment(),
        output=tmp_path / "campaign",
        observation_profile=profile,
    )


def test_checkpoint_resume_preserves_elapsed_clock_across_world_new_year(tmp_path):
    environment = RolloverEnvironment()
    environment.state.update(year=30, year_tick=TICKS_PER_YEAR - 100)
    loop = start(tmp_path, environment=environment)
    first = loop.step()
    assert first["observation"]["campaign_clock"]["elapsed_ticks"] == 0
    assert first["state_after_advance"]["year"] == 31
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=environment, code_revision="clock-test-only")
    restored_env = RolloverEnvironment()
    restored_env.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=TestAgent(),
        environment=restored_env,
        output=tmp_path / "resumed",
        latest_usage_path=loop.journal,
        observation_profile=CLOCK_PROFILE,
    )
    expected, actual = loop.step(), resumed.step()
    assert actual == expected
    assert actual["observation"]["year"] == 31
    assert actual["observation"]["campaign_clock"]["elapsed_ticks"] == 200
    assert actual["observation"]["campaign_clock"]["current_elapsed_year"] == 1
    assert actual["observation"]["campaign_clock"]["completed_decisions"] == 1
    assert resumed.committed_elapsed_ticks == 400
    assert resumed.agent.prompts == [loop.agent.prompts[-1]]
    assert restored_env.actions == ["test decision 2"]


def test_zero_tick_decision_does_not_advance_the_elapsed_clock(tmp_path):
    class ZeroFirst(TestAgent):
        def decide(self, text, observation):
            action = super().decide(text, observation)
            if self.count == 1:
                action["advance_ticks"] = 0
            return action

    loop = start(tmp_path, agent=ZeroFirst())
    clocks = [loop.step()["observation"]["campaign_clock"] for _ in range(3)]
    assert [clock["elapsed_ticks"] for clock in clocks] == [0, 0, 200]
    assert [clock["completed_decisions"] for clock in clocks] == [0, 1, 2]
    assert loop.committed_elapsed_ticks == 400


@pytest.mark.parametrize("profile", [PROFILE, CLOCK_PROFILE])
def test_observation_version_cannot_change_on_resume(tmp_path, profile):
    loop = start(tmp_path, profile=profile)
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="clock-test-only")
    with pytest.raises(ValueError, match="observation profile"):
        CampaignLoop.resume(
            checkpoint,
            agent=TestAgent(),
            environment=RolloverEnvironment(),
            output=tmp_path / "bad-resume",
            latest_usage_path=loop.journal,
            observation_profile=CLOCK_PROFILE if profile == PROFILE else PROFILE,
        )
    assert not (tmp_path / "bad-resume").exists()


def test_prompt_projection_and_packing_preserve_the_clock():
    _, observed = encode(elapsed=203339, decisions=83)
    before = deepcopy(observed)
    observed["action_history"] = [{"step": step} for step in range(12)]
    projected = project_observation(observed, 0)
    assert projected["campaign_clock"] == before["campaign_clock"]
    projected["campaign_clock"]["elapsed_ticks"] = 999
    assert observed["campaign_clock"] == before["campaign_clock"]
    messages = pack_messages(
        observed, system_prompt="test-only policy", memory_context="", fits=lambda _: True
    )
    assert messages is not None
    packed = json.loads(messages[1]["content"].split("Native facts and recent commands:\n")[1])
    assert packed["campaign_clock"] == before["campaign_clock"]
    assert "Campaign elapsed: ticks=203339" in messages[1]["content"]


@pytest.mark.parametrize(
    "filename",
    ["development_autonomous_v1.json", "local_native_qwen35_year_two_reasoning_budget_v1.json"],
)
def test_new_profile_is_configurable_without_modifying_historical_conditions(tmp_path, filename):
    source = Path(__file__).resolve().parents[1] / "experiments/campaigns" / filename
    original = source.read_bytes()
    config = json.loads(original)
    assert config["observation_profile"] == PROFILE
    config.update(observation_profile=CLOCK_PROFILE, condition_id="test-only-clock-v2")
    modified = tmp_path / "clock.json"
    modified.write_text(json.dumps(config))
    assert load_segment_config(modified, config["models"][0]) == config
    assert source.read_bytes() == original
    config["decision_profile"] = "governed_review/v1"
    modified.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="profiles"):
        load_segment_config(modified, config["models"][0])


def test_clock_reaches_local_transport_and_survives_an_accounted_output_pause(
    tmp_path, monkeypatch
):
    from fort_gym.bench.agent import campaign_llama_identity as identity
    from fort_gym.bench.run.campaign_loop import CampaignNoActionPause
    from tests.test_campaign_llama import CONFIG, MODEL, fake_server, generations, policy

    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    config = load_segment_config(CONFIG, MODEL)
    config.update(observation_profile=CLOCK_PROFILE, condition_id="test-only-local-clock")
    local = config["local_inference"]
    local["chat_template_sha256"][MODEL] = hashlib.sha256(b"test-template").hexdigest()
    local["model_metadata_sha256"][MODEL] = identity.json_digest({"test_model": True})

    def output_pause(response, props):
        response["choices"][0].update(finish_reason="length")
        response["choices"][0]["message"]["content"] = ""
        response["usage"].update(
            completion_tokens=config["max_output_tokens"],
            total_tokens=42 + config["max_output_tokens"],
        )

    calls, _ = fake_server(config, monkeypatch, mutate=output_pause)
    agent, environment = policy(config, tmp_path), TestEnvironment()
    loop = CampaignLoop(
        campaign_id="llama-test",
        agent=agent,
        environment=environment,
        output=tmp_path / "local-clock",
        observation_profile=CLOCK_PROFILE,
        advance_policy=config["advance_policy"],
    )
    with pytest.raises(CampaignNoActionPause):
        loop.step()
    assert loop.next_step == 0 and loop.committed_elapsed_ticks == 0
    assert not environment.actions
    requests = generations(calls)
    assert len(requests) == 1
    content = next(
        item["content"]
        for item in requests[0]["messages"]
        if "Native facts and recent commands:\n" in item["content"]
    )
    observed = json.loads(content.split("Native facts and recent commands:\n")[1])
    assert observed["observation_profile"] == CLOCK_PROFILE
    assert observed["campaign_clock"]["elapsed_ticks"] == 0
    assert observed["campaign_clock"]["completed_decisions"] == 0

    checkpoint = tmp_path / "local-checkpoint"
    loop.checkpoint(checkpoint, snapshotter=environment, code_revision="test-only")
    restored = CampaignLoop.resume(
        checkpoint,
        agent=policy(config, tmp_path / "restored-model"),
        environment=TestEnvironment(),
        output=tmp_path / "restored-local-clock",
        latest_usage_path=loop.journal,
        observation_profile=CLOCK_PROFILE,
    )
    assert restored.committed_elapsed_ticks == 0
    assert restored.agent.export_campaign_state() == agent.export_campaign_state()
    assert len(generations(calls)) == 1  # Resume itself does not dispatch another request.
