"""Exercise actual campaign policy adapters with fake providers and game state."""

import hashlib
import json
from pathlib import Path

import pytest

from fort_gym.bench.agent import campaign_llama_identity as identity
from fort_gym.bench.env.campaign_view import DECISION_PROFILE, OBSERVATION_PROFILE
from fort_gym.bench.run.campaign_config import load_segment_config
from fort_gym.bench.run.campaign_loop import CampaignLoop, CampaignNoActionPause
from tests.test_campaign_map_view import SELECTION, action
from tests.test_campaign_map_view_loop import ViewEnvironment
from tests.test_campaign_llama import CONFIG, MODEL, fake_server, generations, policy


def local_config():
    config = load_segment_config(CONFIG, MODEL)
    config.update(
        decision_profile=DECISION_PROFILE,
        observation_profile=OBSERVATION_PROFILE,
        condition_id="test-only-map-inspection",
    )
    config["local_inference"]["chat_template_sha256"][MODEL] = hashlib.sha256(
        b"test-template"
    ).hexdigest()
    config["local_inference"]["model_metadata_sha256"][MODEL] = identity.json_digest(
        {"test_model": True}
    )
    return config


@pytest.mark.parametrize("outcome", ["wait", "output_pause"])
def test_local_model_selects_view_and_restores_it_before_next_request(
    tmp_path, monkeypatch, outcome
):
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    config = local_config()
    responses = 0

    def response(value, props):
        nonlocal responses
        responses += 1
        if responses == 1:
            value["choices"][0]["message"]["content"] = json.dumps(action())
        elif outcome == "output_pause":
            value["choices"][0].update(finish_reason="length")
            value["choices"][0]["message"]["content"] = ""
            value["usage"].update(
                completion_tokens=config["max_output_tokens"],
                total_tokens=42 + config["max_output_tokens"],
            )

    calls, _ = fake_server(config, monkeypatch, mutate=response)
    agent, environment = policy(config, tmp_path), ViewEnvironment()
    run = CampaignLoop(
        campaign_id="llama-test",
        agent=agent,
        environment=environment,
        output=tmp_path / "campaign",
        observation_profile=OBSERVATION_PROFILE,
        advance_policy=config["advance_policy"],
    )
    first = run.step()
    assert first["action"]["type"] == "VIEW" and first["execute"]["accepted"]
    assert run.observation_view == SELECTION and not environment.actions
    request = generations(calls)[0]
    assert "VIEW: params" in request["messages"][0]["content"]
    variants = request["response_format"]["schema"]["oneOf"]
    view_schema = next(row for row in variants if row["properties"]["type"]["enum"] == ["VIEW"])
    assert view_schema["properties"]["advance_ticks"]["maximum"] == 0
    assert view_schema["properties"]["params"]["required"] == ["origin", "size"]
    saved_agent = agent.export_campaign_state()
    assert saved_agent["configuration"]["decision_profile"] == DECISION_PROFILE
    checkpoint = tmp_path / "checkpoint"
    run.checkpoint(checkpoint, snapshotter=environment, code_revision="synthetic-map")
    (tmp_path / "restored-agent").mkdir()
    restored = CampaignLoop.resume(
        checkpoint,
        agent=policy(config, tmp_path / "restored-agent"),
        environment=ViewEnvironment(),
        output=tmp_path / "resumed",
        latest_usage_path=run.journal,
    )
    assert restored.agent.export_campaign_state() == saved_agent
    assert restored.observation_view == SELECTION and len(generations(calls)) == 1
    if outcome == "output_pause":
        with pytest.raises(CampaignNoActionPause):
            restored.step()
        assert restored.next_step == 1 and restored.committed_elapsed_ticks == 0
        assert not restored.environment.actions
        paused_checkpoint = tmp_path / "paused-checkpoint"
        restored.checkpoint(
            paused_checkpoint, snapshotter=restored.environment, code_revision="synthetic-map"
        )
        assert (
            json.loads((paused_checkpoint / "runner.json").read_text())["observation_view"]
            == SELECTION
        )
    else:
        second = restored.step()
        assert second["observation"]["map_view"]["selection"] == SELECTION
        assert second["tick_advance"]["ticks_advanced"] == 20
    second_request = generations(calls)[1]
    text = next(
        item["content"]
        for item in second_request["messages"]
        if "Native facts and recent commands:\n" in item["content"]
    )
    observation = json.loads(text.split("Native facts and recent commands:\n")[1])
    assert observation["map_view"]["selection"] == SELECTION
    assert observation["campaign_clock"]["elapsed_ticks"] == 0
    assert restored.agent.export_campaign_state()["usage"]["returned_responses"] == 2


def test_old_local_policy_and_checkpoint_identity_do_not_silently_gain_view(tmp_path):
    old_config = local_config()
    old_config.update(
        decision_profile="campaign_action/v1", observation_profile="campaign_state/v2"
    )
    old, new = policy(old_config, tmp_path / "old"), policy(local_config(), tmp_path / "new")
    with pytest.raises(ValueError, match="declared native controls"):
        old._campaign_action(action())
    assert new._campaign_action(action()) == action()
    assert "VIEW: params" not in old._campaign_system_prompt()
    assert old.export_campaign_state()["configuration"]["prompt_sha256"] != (
        new.export_campaign_state()["configuration"]["prompt_sha256"]
    )
    with pytest.raises(ValueError):
        new.restore_campaign_state(old.export_campaign_state(), campaign_id="llama-test")
    assert old.dispatches == new.dispatches == 0
    text = json.dumps(action()) + '\n{"type":"WAIT","params":{},"advance_ticks":20}'
    assert old._json_payload_from_text(text)["type"] == "WAIT"
    assert new._inspection_json_payload_from_text(text)["type"] == "VIEW"
    assert new._inspection_json_payload_from_text([{"text": text}])["type"] == "VIEW"
    assert new._inspection_json_payload_from_text("no JSON") is None
    assert (
        new._extract_tool_payload({"choices": [{"message": {"content": text}}]})["type"] == "VIEW"
    )


def test_hosted_configured_policy_can_select_view_without_native_world_dispatch(
    tmp_path, monkeypatch
):
    from fort_gym.bench.config import get_settings
    from tests.test_campaign_autonomous import fake_policy, run as segment

    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    get_settings.cache_clear()
    try:
        path = (
            Path(__file__).resolve().parents[1]
            / "experiments/campaigns/development_autonomous_v1.json"
        )
        config = json.loads(path.read_text())
        config.update(
            decision_profile=DECISION_PROFILE,
            observation_profile=OBSERVATION_PROFILE,
            condition_id="test-only-hosted-view",
        )
        agent, requests = fake_policy(config, tmp_path, monkeypatch, payload=action())
        environment = ViewEnvironment()
        result = segment(tmp_path, agent, config, environment)
        assert result["status"] == "bounded_segment_complete" and result["next_step"] == 3
        assert not environment.actions and environment.advances == [0, 0, 0]
        assert len(requests) == 3
        assert (
            "VIEW"
            in requests[0]["tools"][0]["function"]["parameters"]["properties"]["type"]["enum"]
        )
        assert "VIEW: params" in requests[0]["messages"][0]["content"]
        assert result["usage"]["returned_responses"] == 3
    finally:
        get_settings.cache_clear()
