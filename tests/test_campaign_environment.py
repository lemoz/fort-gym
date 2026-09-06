import json
from types import SimpleNamespace

import pytest

from fort_gym.bench.run import campaign_environment as module


def test_wrong_runtime_is_rejected_before_connect_or_gameplay(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module, "run_lua_expr", lambda *args, **kwargs: json.dumps({"dfroot": "/other"})
    )
    monkeypatch.setattr(module, "DFHackClient", lambda **kwargs: pytest.fail("Must not connect"))
    with pytest.raises(RuntimeError, match="expected isolated"):
        module.NativeCampaignEnvironment(expected_dfroot=tmp_path)


@pytest.mark.parametrize("placement", ["strict_floor/v1", "dfhack_047_ground/v1"])
def test_native_adapter_uses_existing_executor_without_assisted_completion(
    tmp_path, monkeypatch, placement
):
    calls = []

    def get_state(**kwargs):
        assert kwargs == {"require_native": True}
        return {"year": 0, "population": 7, "pause_state": True}

    client = SimpleNamespace(
        connect=lambda: calls.append("connect"),
        close=lambda: calls.append("close"),
        set_work_metrics_global_only=lambda value: calls.append(("global", value)),
        get_state=get_state,
        advance=lambda *args, **kwargs: calls.append(("advance", args, kwargs)),
        last_tick_info={"ticks_advanced": 50},
        get_screen_text=lambda **kwargs: "native test screen",
    )
    monkeypatch.setattr(module, "DFHackClient", lambda **kwargs: client)
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(DFHACK_HOST="127.0.0.1", DFHACK_PORT=5501)
    )
    monkeypatch.setattr(
        module, "run_lua_expr", lambda *args, **kwargs: json.dumps({"dfroot": str(tmp_path)})
    )
    monkeypatch.setattr(module, "ensure_paused_external", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        module,
        "native_save_status",
        lambda: {"ok": True, "paused": True, "year": 30, "year_tick": 19309},
    )
    monkeypatch.setattr(
        module, "read_campaign_fort_metrics", lambda: {"ok": True, "constructions": 0}
    )
    monkeypatch.setattr(
        module, "read_campaign_job_metrics", lambda: {"ok": True, "citizens": {"total": 7}}
    )
    env = module.NativeCampaignEnvironment(
        expected_dfroot=tmp_path, workshop_placement_policy=placement
    )
    assert env.executor._allow_assisted_dig_completion is False
    state = env.observe()
    assert env.executor._workshop_placement_policy == placement
    assert ("workshop_placement" in state) == (placement == "dfhack_047_ground/v1")
    assert state["year"] == 30 and state["year_tick"] == 19309
    quality = state["campaign_observation_quality"]
    assert quality["schema_version"] == "fortgym.campaign-observation-quality/v2"
    assert quality["native_population_and_stock_value_types_validated"] is True
    assert quality["food_drink_flow_measurement"] == "unavailable"
    assert "not freshness or accessibility" in quality["stock_validation_scope"]
    assert "survival" not in state  # Do not invent cumulative G7 measurement.
    assert env.apply({"type": "WAIT", "params": {}}, state)["accepted"] is True
    assert env.advance(0, state)[1]["ticks_advanced"] == 0
    assert not any(isinstance(call, tuple) and call[0] == "advance" for call in calls)
    assert env.advance(50, state)[1]["ticks_advanced"] == 50
    assert calls[-1][2]["interrupt_on_viewscreen_transition"] is True
    env.close()
    assert calls[-1] == "close"
