from __future__ import annotations

from pathlib import Path

from fort_gym.bench import dfhack_backend

HOOK_SOURCE = (
    Path(__file__).resolve().parents[1] / "hook" / "g7_evidence.lua"
).read_text(encoding="utf-8")
DEATH_FIXTURE_HOOK_SOURCE = (
    Path(__file__).resolve().parents[1] / "hook" / "calibration_kill_one.lua"
).read_text(encoding="utf-8")


def test_g7_evidence_is_run_scoped_and_event_backed() -> None:
    for needle in (
        "FORT_GYM_G7_EVIDENCE",
        "eventful.onItemCreated[CALLBACK_KEY]",
        "eventful.onUnitDeath[CALLBACK_KEY]",
        "eventful.eventType.ITEM_CREATED",
        "eventful.eventType.UNIT_DEATH",
        "start_item_next_id",
        "active.baseline_dead_ids[tostring(unit_id)]",
        "food_produced_in_run",
        "food_consumed_in_run",
        "drink_produced_in_run",
        "drink_consumed_in_run",
        "flow_evidence_complete",
        "death_evidence_complete",
        "death_causes_known",
    ):
        assert needle in HOOK_SOURCE


def test_g7_consumption_uses_per_unit_eat_history_not_stock_deltas() -> None:
    assert "unit.status and unit.status.eat_history" in HOOK_SOURCE
    assert "local history = eat_history[kind]" in HOOK_SOURCE
    assert "history.year_time[idx]" in HOOK_SOURCE
    assert "ledger.history_seen" in HOOK_SOURCE
    assert "ui.tasks.food" not in HOOK_SOURCE
    assert "stock_delta" not in HOOK_SOURCE


def test_g7_food_production_is_farm_output_not_any_created_food_item() -> None:
    assert "item_on_completed_farm_plot" in HOOK_SOURCE
    assert "bld:getType() == df.building_type.FarmPlot" in HOOK_SOURCE
    assert "bld:getBuildStage() >= bld:getMaxBuildStage()" in HOOK_SOURCE
    assert (
        "farm_check_ok, on_completed_farm = item_on_completed_farm_plot(item)"
        in HOOK_SOURCE
    )
    farm_classifier = HOOK_SOURCE.split(
        "local function item_on_completed_farm_plot", 1
    )[1].split("local function record_created_item", 1)[0]
    assert "return ok, ok and result or false" in farm_classifier
    assert "farm_output_classification_failed" in HOOK_SOURCE
    assert "nonfarm_plants_created_in_run" in HOOK_SOURCE


def test_g7_death_classification_fails_closed_for_non_direct_cases() -> None:
    assert "df.incident.find(id)" in HOOK_SOURCE
    assert "victim ~= tonumber(unit.id)" in HOOK_SOURCE
    assert "incident.death_cause" in HOOK_SOURCE
    assert "world.incidents.all[death_id].death_cause" in HOOK_SOURCE
    assert "record.cause_name == 'HUNGER'" in HOOK_SOURCE
    assert "record.cause_name == 'THIRST'" in HOOK_SOURCE
    assert "if #deaths == 0 or direct_neglect_deaths > 0 then" in HOOK_SOURCE
    assert "Other deaths need separate tantrum-chain evidence" in HOOK_SOURCE


def test_death_calibration_forces_real_incident_fallback_only() -> None:
    assert "force_incident_death_cause = mode == 'force_incident_death_cause'" in HOOK_SOURCE
    assert "if not ledger.force_incident_death_cause" in HOOK_SOURCE
    assert "incident_death_cause(unit, incident_id)" in HOOK_SOURCE
    assert "measurement_calibration_mode = ledger.calibration_mode" in HOOK_SOURCE


def test_g7_backend_helpers_dispatch_bounded_commands(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], float]] = []

    def fake_run(path: str, *args: str, timeout: float):
        calls.append((path, args, timeout))
        return {"ok": True, "args": list(args)}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run)

    assert dfhack_backend.start_g7_evidence("run-123")["ok"] is True
    assert dfhack_backend.read_g7_evidence()["ok"] is True
    assert dfhack_backend.stop_g7_evidence()["ok"] is True
    assert [call[1] for call in calls] == [
        ("start", "run-123"),
        ("read",),
        ("stop",),
    ]
    assert all(call[0].endswith("g7_evidence.lua") for call in calls)
    assert all(call[2] == 5.0 for call in calls)


def test_g7_backend_death_calibration_passes_narrow_mode(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(path: str, *args: str, timeout: float):
        del path, timeout
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run)

    assert dfhack_backend.start_g7_evidence(
        "run-123", measurement_calibration_mode="force_incident_death_cause"
    ) == {"ok": True}
    assert calls == [
        ("start", "run-123", "force_incident_death_cause"),
    ]
    assert dfhack_backend.start_g7_evidence(
        "run-123", measurement_calibration_mode="invented"
    ) == {"ok": False, "error": "invalid_measurement_calibration_mode"}


def test_death_calibration_fixture_is_one_bounded_friendly_kill(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], float]] = []

    def fake_run(path: str, *args: str, timeout: float):
        calls.append((path, args, timeout))
        return {
            "ok": True,
            "fixture": "dfhack_bounded_friendly_bloodloss",
            "target": "citizen",
            "limit": 1,
            "method": "blood_loss_next_tick",
            "unit_id": 243,
            "race_token": "DWARF",
            "blood_before": 60000,
            "blood_after": 0,
        }

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run)

    result = dfhack_backend.trigger_p1_death_calibration_fixture()

    assert result == {
        "ok": True,
        "fixture": "dfhack_bounded_friendly_bloodloss",
        "target": "citizen",
        "limit": 1,
        "method": "blood_loss_next_tick",
        "unit_id": 243,
        "race_token": "DWARF",
        "blood_before": 60000,
        "blood_after": 0,
    }
    assert calls[0][0].endswith("calibration_kill_one.lua")
    assert calls[0][1] == ()
    assert calls[0][2] == 5.0
    for needle in (
        "dfhack.units.isCitizen(unit, true)",
        "not dfhack.units.isDead(unit)",
        "unit.id < target.id",
        "target.body.blood_count = 0",
        "blood_loss_next_tick",
        "It does not write any measurement or death-cause evidence itself.",
    ):
        assert needle in DEATH_FIXTURE_HOOK_SOURCE


def test_death_calibration_fixture_fails_without_command_confirmation(
    monkeypatch,
) -> None:
    def fake_run(path: str, *args: str, timeout: float):
        del path, args, timeout
        return {
            "ok": True,
            "fixture": "dfhack_bounded_friendly_bloodloss",
            "target": "citizen",
            "limit": 1,
            "method": "blood_loss_next_tick",
            "unit_id": 243,
            "blood_before": 60000,
            "blood_after": 60000,
        }

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run)

    assert dfhack_backend.trigger_p1_death_calibration_fixture() == {
        "ok": False,
        "fixture": "dfhack_bounded_friendly_bloodloss",
        "target": "citizen",
        "limit": 1,
        "method": "blood_loss_next_tick",
        "error": "invalid_fixture_confirmation",
        "observed": {
            "ok": True,
            "fixture": "dfhack_bounded_friendly_bloodloss",
            "target": "citizen",
            "limit": 1,
            "method": "blood_loss_next_tick",
            "unit_id": 243,
            "blood_before": 60000,
            "blood_after": 60000,
        },
    }


def test_g7_stop_error_does_not_claim_callbacks_are_inactive(monkeypatch) -> None:
    def fail_run(path: str, *args: str, timeout: float):
        raise OSError("dfhack unavailable")

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fail_run)

    result = dfhack_backend.stop_g7_evidence()

    assert result["ok"] is False
    assert result["active"] is None
