import json
from pathlib import Path
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
@pytest.mark.parametrize("tick_limit", [2000, 2500])
def test_native_adapter_uses_existing_executor_without_assisted_completion(
    tmp_path, monkeypatch, placement, tick_limit
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
        expected_dfroot=tmp_path,
        workshop_placement_policy=placement,
        max_advance_ticks=tick_limit,
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
    assert calls[-1][2]["max_advance_ticks"] == tick_limit
    env.advance(tick_limit, state)
    assert calls[-1][1] == (tick_limit,)
    assert calls[-1][2]["max_advance_ticks"] == tick_limit
    env.close()
    assert calls[-1] == "close"


@pytest.mark.parametrize("tick_limit", [False, True, 0, -1, 2501, 2000.0, "2500"])
def test_invalid_campaign_tick_limit_fails_before_native_access(tmp_path, monkeypatch, tick_limit):
    monkeypatch.setattr(
        module, "run_lua_expr", lambda *args, **kwargs: pytest.fail("No native access")
    )
    with pytest.raises(ValueError, match="campaign tick limit"):
        module.NativeCampaignEnvironment(expected_dfroot=tmp_path, max_advance_ticks=tick_limit)


@pytest.mark.parametrize("ticks", [False, True, -1, 2501, 2500.0, "2500"])
def test_invalid_campaign_advance_fails_before_native_access(ticks):
    environment = module.NativeCampaignEnvironment.__new__(module.NativeCampaignEnvironment)
    environment.max_advance_ticks = 2500
    environment.observe = lambda: pytest.fail("No native access")
    with pytest.raises(ValueError, match="declared campaign tick limit"):
        environment.advance(ticks, {})


def test_declared_limit_reaches_the_clock_controller_through_the_real_client(monkeypatch):
    from fort_gym.bench.env import dfhack_client

    environment = module.NativeCampaignEnvironment.__new__(module.NativeCampaignEnvironment)
    environment.max_advance_ticks = 2500
    environment.observe = lambda: {"viewscreen_type": "viewscreen_dwarfmodest"}
    client = dfhack_client.DFHackClient.__new__(dfhack_client.DFHackClient)
    client._ensure_connection = lambda: None
    client.get_state = lambda: {}
    environment.client = client

    def clock(ticks, *, repause, max_advance_ticks=2000, **kwargs):
        assert repause is True and kwargs["interrupt_on_viewscreen_transition"] is True
        # This reproduces the clock controller's legacy default clamp. Omitting
        # the campaign bound would silently return 2000 for the 2500 request.
        requested = min(ticks, max_advance_ticks)
        return {"ok": True, "requested": requested, "ticks_advanced": requested}

    monkeypatch.setattr(dfhack_client, "advance_ticks_exact", clock)
    _, receipt = environment.advance(2500, {})
    assert receipt["requested"] == receipt["ticks_advanced"] == 2500


def test_retained_native_tick_fixture_preserves_receipts_and_non_gameplay_scope():
    from fort_gym.bench.tick_receipt import calendar_elapsed_ticks

    path = (
        Path(__file__).resolve().parents[1]
        / "experiments/evidence/local_native_tick_limit_20260907.json"
    )
    record = json.loads(path.read_text())
    assert record["execution_revision"] == "eca52a53021c8889ee9e63882f2184084590d391"
    fixture = record["fixture"]
    assert fixture["native_tick_limit_verified"] is True
    assert fixture["autonomous_gameplay"] is fixture["year_two_gameplay_verified"] is False
    assert fixture["provider_calls"] == 0 and fixture["total_observed_ticks"] == 4500
    previous = {"year": 30, "year_tick": 16801}
    for limit, advance in zip((2000, 2500), fixture["advances"], strict=True):
        assert advance["before"] == previous
        assert advance["requested_ticks"] == advance["declared_max_advance_ticks"] == limit
        receipt = advance["receipt"]
        assert receipt["requested"] == receipt["ticks_advanced"] == limit
        elapsed, error = calendar_elapsed_ticks(
            receipt["start_year"], receipt["start_tick"], receipt["end_year"], receipt["end_tick"]
        )
        assert error is None and elapsed == advance["calendar_elapsed_ticks"] == limit
        assert advance["overshoot_ticks"] == 0
        assert advance["out_of_bound_requests_rejected_without_advance"] is True
        assert advance["zero_request_preserved_boundary"] is True
        assert receipt["paused_after"] is receipt["repause_effective"] is True
        assert advance["after"] == {"year": receipt["end_year"], "year_tick": receipt["end_tick"]}
        previous = advance["after"]
    assert previous == {"year": 30, "year_tick": 21301}
    assert record["teardown"]["container_exit_code"] == 0
    assert all(
        value is True for key, value in record["teardown"].items() if key != "container_exit_code"
    )
    assert record["provider_calls"] == record["cloud_vms_created"] == 0
    assert record["historical_inputs_rewritten"] is record["production_deployed"] is False
