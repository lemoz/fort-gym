from __future__ import annotations

from fort_gym.bench.eval.gates import FAIL, PASS, UNKNOWN, _model_usage, evaluate_g7


def _row(
    step: int,
    *,
    survival=None,
    dead: int = 0,
    drink: int = 80,
    completed_beds: int | None = 5,
    ticks_advanced: int = 403_200,
):
    survival_payload = dict(survival or {})
    survival_payload.setdefault("run_id", "g7-test")
    survival_payload.setdefault("death_records", [])
    survival_payload.setdefault("deaths_in_run", dead)
    crew = {}
    if completed_beds is not None:
        crew["placed_furniture_completed"] = {"bed": completed_beds}
    state = {
        "population": 15,
        "dead": dead,
        "stocks": {"food": 80, "drink": drink},
        "crew": crew,
        "survival": survival_payload,
    }
    return {
        "run_id": "g7-test",
        "step": step,
        "action": {"type": "WAIT", "params": {}, "advance_ticks": ticks_advanced},
        "observation": state,
        "state_after_advance": state,
        "metrics": {
            "dead": dead,
            "fort_functional_rooms": 3,
            "fort_metrics_observed": True,
            "governed_owned_operational_farm_evidence_complete": True,
        },
        "execute": {"accepted": True, "provenance": "dfhack_governed"},
        "tick_advance": {"ticks_advanced": ticks_advanced},
        "screen_text": "DF screen",
        "gameplay_proof": {
            "ok": True,
            "source": "dfhack-map-and-state",
            "provenance": "dfhack_governed",
        },
        "events": [
            {
                "type": "tool_call",
                "data": {
                    "tool": "openrouter.chat.completions.create",
                    "input": {"model": "z-ai/glm-5v-turbo"},
                    "output": {
                        "generation_id": f"gen-{step}",
                        "resolved_model": "z-ai/glm-5v-turbo",
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "cost": 0.01,
                    },
                },
            }
        ],
    }


def _summary(**overrides):
    value = {
        "duration_ticks": 403_200,
        "end_pop": 15,
        "fort_functional_rooms": 3,
        "total_score": 150,
        "score_version": 5,
        "rubric": {"rubric_score": 70, "blockers": []},
    }
    value.update(overrides)
    return value


def test_model_usage_separates_failed_attempt_events_from_billed_generations() -> None:
    row = _row(0)
    row["events"].insert(
        0,
        {
            "type": "tool_call",
            "data": {
                "tool": "openrouter.chat.completions.create",
                "input": {"model": "z-ai/glm-5v-turbo"},
                "output": {"error": "timeout", "retrying": True},
            },
        },
    )

    usage = _model_usage([row])

    assert usage["attempt_events"] == 2
    assert usage["failed_attempt_events"] == 1
    assert usage["calls"] == 1
    assert usage["generation_ids"] == ["gen-0"]


def test_g7_pass_requires_every_ratified_fact() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    result = evaluate_g7([_row(0, survival=survival)], _summary())

    assert result["status"] == PASS
    assert result["gate_version"] == 4
    assert "duration" not in result["criteria"]
    assert "population" not in result["criteria"]
    assert "scalar_score" not in result["criteria"]
    assert result["diagnostics"]["duration"]["gate_effect"] == "none"
    assert result["diagnostics"]["population"]["gate_effect"] == "none"
    assert result["diagnostics"]["scalar_score"]["gate_effect"] == "none"


def test_g7_v5_passes_only_from_owned_accessible_final_evidence() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival, completed_beds=99)
    row["metrics"].update(
        {
            "governed_owned_accessible_functional_rooms": 3,
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_unique_construction_tiles": 24,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )
    summary = _summary(
        end_pop=7,
        peak_pop=22,
        governed_owned_accessible_layout_rooms=3,
        rubric={"measurement_version": 2, "score": None},
    )

    result = evaluate_g7([row], summary, gate_version=5)

    assert result["status"] == PASS
    assert result["gameplay_outcome"]["status"] == PASS
    assert result["evaluation_validity"]["status"] == PASS
    assert result["criteria"]["initial_cohort_bed_capacity"]["required"].startswith(
        ">=3"
    )
    assert "rubric" not in result["criteria"]
    assert "scalar_score" not in result["criteria"]


def test_g7_v5_proven_room_lower_bound_survives_global_scan_truncation() -> None:
    survival = {
        "food_produced_in_run": 0,
        "food_consumed_in_run": 99,
        "drink_produced_in_run": 0,
        "drink_consumed_in_run": 99,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival)
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": False,
            "governed_owned_layout_room_lower_bound_proven": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["owned_accessible_layout_rooms"]["status"] == PASS
    assert result["criteria"]["owned_operational_provisioning"]["status"] == PASS
    assert result["evaluation_validity"]["status"] == PASS


def test_g7_v5_global_rooms_cannot_replace_owned_room_evidence() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival)
    row["metrics"].update(
        {
            "fort_functional_rooms": 50,
            "governed_owned_accessible_functional_rooms": 0,
            "governed_owned_accessible_layout_rooms": 0,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=0),
        gate_version=5,
    )

    assert result["status"] == FAIL
    assert result["criteria"]["owned_accessible_layout_rooms"]["status"] == FAIL


def test_g7_v5_missing_layout_sensor_is_unknown_not_zero() -> None:
    row = _row(0)
    row["metrics"]["governed_owned_completed_beds"] = 3

    result = evaluate_g7([row], _summary(), gate_version=5)

    assert result["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN
    assert result["criteria"]["owned_accessible_layout_rooms"]["status"] == UNKNOWN
    assert result["criteria"]["initial_cohort_bed_capacity"]["status"] == UNKNOWN


def test_g7_v5_owned_provisioning_is_independent_of_stock_and_flow_exposure() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival, drink=0)
    row["metrics"].update(
        {
            "governed_owned_accessible_functional_rooms": 3,
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["owned_operational_provisioning"]["status"] == PASS
    assert "produced_in_run" in str(
        result["criteria"]["owned_operational_provisioning"]["observed"]
    )


def test_g7_v5_inherited_seed_stock_cannot_replace_owned_brew_output() -> None:
    row = _row(
        0,
        survival={
            "flow_evidence_complete": True,
            "food_produced_in_run": 0,
            "food_consumed_in_run": 0,
            "drink_produced_in_run": 0,
            "drink_consumed_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert row["observation"]["stocks"] == {"food": 80, "drink": 80}
    assert result["evaluation_validity"]["status"] == PASS
    assert result["gameplay_outcome"]["status"] == FAIL
    assert result["criteria"]["owned_operational_provisioning"]["status"] == FAIL


def test_g7_v5_operational_farm_latch_cannot_replace_final_owned_farm() -> None:
    row = _row(
        0,
        survival={
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 0,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["evaluation_validity"]["status"] == PASS
    assert result["criteria"]["owned_operational_provisioning"]["status"] == FAIL
    assert result["gameplay_outcome"]["status"] == FAIL


def test_g7_v5_malformed_owned_counts_are_unknown_not_zero() -> None:
    row = _row(
        0,
        dead=1,
        survival={
            "deaths_in_run": 1,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": "malformed",
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": "malformed",
            "governed_owned_completed_farm_plots": "malformed",
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["initial_cohort_bed_capacity"]["status"] == UNKNOWN
    assert result["criteria"]["owned_operational_provisioning"]["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_negative_counts_are_unknown_not_fail_or_pass() -> None:
    row = _row(
        0,
        dead=1,
        survival={
            "deaths_in_run": -1,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": -1,
            "governed_owned_completed_farm_plots": -1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["initial_cohort_bed_capacity"]["status"] == UNKNOWN
    assert result["criteria"]["owned_operational_provisioning"]["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_missing_owned_provisioning_sensor_is_unknown_not_failure() -> None:
    row = _row(
        0,
        survival={
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    criterion = result["criteria"]["owned_operational_provisioning"]
    assert criterion["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN
    assert result["gameplay_outcome"]["status"] == UNKNOWN


def test_g7_v5_missing_stock_sensor_is_diagnostic_only() -> None:
    row = _row(
        0,
        survival={
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["observation"]["stocks"] = {}
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["gameplay_outcome"]["status"] == PASS
    assert result["criteria"]["owned_operational_provisioning"]["status"] == PASS
    assert result["evaluation_validity"]["status"] == PASS
    assert result["evaluation_validity"]["stock_evidence_complete"] is False
    assert result["status"] == PASS


def test_g7_v5_duration_mismatch_is_diagnostic_only() -> None:
    row = _row(
        0,
        ticks_advanced=1_000,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(
            duration_ticks=403_200,
            governed_owned_accessible_layout_rooms=3,
        ),
        gate_version=5,
    )

    assert result["diagnostics"]["duration"]["status"] == "inconsistent"
    assert result["diagnostics"]["duration"]["gate_effect"] == "none"
    assert result["evaluation_validity"]["status"] == PASS
    assert result["status"] == PASS


def test_g7_v5_requires_run_scoped_death_count_without_global_fallback() -> None:
    row = _row(
        0,
        dead=0,
        survival={
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )
    row["observation"]["survival"].pop("deaths_in_run")

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["observed"]["dead"] is None
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_malformed_brew_output_is_unknown_not_zero() -> None:
    for output_by_job in (None, {"brew": None}, {"brew": "malformed"}, {"brew": 0.5}):
        row = _row(
            0,
            survival={
                "deaths_in_run": 0,
                "death_evidence_complete": True,
                "death_causes_known": True,
                "neglect_deaths": 0,
            },
        )
        row["metrics"].update(
            {
                "governed_owned_accessible_layout_rooms": 3,
                "governed_owned_room_evidence_complete": True,
                "governed_owned_building_evidence_complete": True,
                "governed_owned_completed_beds": 3,
                "governed_owned_completed_farm_plots": 1,
                "governed_owned_completed_stills": 1,
                "governed_owned_operational_farm_plots": 1,
                "governed_owned_output_units_by_job": output_by_job,
                "governed_owned_output_evidence_complete": True,
            }
        )

        result = evaluate_g7(
            [row],
            _summary(governed_owned_accessible_layout_rooms=3),
            gate_version=5,
        )

        criterion = result["criteria"]["owned_operational_provisioning"]
        assert criterion["status"] == UNKNOWN
        assert criterion["observed"]["owned_brew_output_units"] is None


def test_g7_v5_stale_brew_mapping_requires_explicit_lower_bound_proof() -> None:
    row = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": False,
            "governed_owned_output_lower_bound_proven": False,
        }
    )

    stale = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )
    row["metrics"]["governed_owned_output_lower_bound_proven"] = True
    proven = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert stale["criteria"]["owned_operational_provisioning"]["status"] == UNKNOWN
    assert proven["criteria"]["owned_operational_provisioning"]["status"] == PASS
    assert proven["evaluation_validity"]["status"] == PASS


def test_g7_v5_nonintegral_owned_counts_are_unknown() -> None:
    row = _row(
        0,
        survival={
            "deaths_in_run": 0.5,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3.5,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3.5,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3.5),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["owned_accessible_layout_rooms"]["status"] == UNKNOWN
    assert result["criteria"]["initial_cohort_bed_capacity"]["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_positive_death_count_requires_authoritative_record_details() -> None:
    row = _row(
        0,
        dead=1,
        survival={
            "deaths_in_run": 1,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    missing = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )
    row["observation"]["survival"]["death_records"] = [
        {
            "unit_id": 42,
            "cause_enum": 1,
            "cause_name": "FALLING_OBJECT",
            "cause_known": True,
            "cause_source": "world.incidents.all[death_id].death_cause",
            "incident_id": 9,
        }
    ]
    authoritative = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert missing["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert authoritative["criteria"]["neglect_deaths"]["status"] == PASS
    assert authoritative["status"] == PASS


def test_g7_v5_rejects_non_authoritative_death_cause_source() -> None:
    row = _row(
        0,
        dead=1,
        survival={
            "deaths_in_run": 1,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
            "death_records": [
                {
                    "unit_id": 42,
                    "cause_known": True,
                    "cause_source": "current_drowning_flag",
                }
            ],
        },
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["observed"][
        "death_records_complete"
    ] is False


def test_g7_v5_rejects_contradictory_death_aggregates_as_invalid() -> None:
    row = _row(
        0,
        dead=0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 1,
        },
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    criterion = result["criteria"]["neglect_deaths"]
    assert criterion["status"] == UNKNOWN
    assert "exceeds" in criterion["reason"]
    assert result["evaluation_validity"]["status"] == FAIL
    assert result["status"] == UNKNOWN


def test_g7_v5_zero_deaths_requires_an_empty_authoritative_record_list() -> None:
    row = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
            "death_records": [
                {
                    "unit_id": 42,
                    "cause_known": True,
                    "cause_source": "counters.death_cause",
                }
            ],
        },
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["observed"][
        "death_records_complete"
    ] is False


def test_g7_v5_rejects_duplicate_death_records() -> None:
    row = _row(
        0,
        dead=2,
        survival={
            "deaths_in_run": 2,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
            "death_records": [
                {
                    "unit_id": 42,
                    "cause_known": True,
                    "cause_source": "counters.death_cause",
                },
                {
                    "unit_id": 42,
                    "cause_known": True,
                    "cause_source": "counters.death_cause",
                },
            ],
        },
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["observed"][
        "death_records_complete"
    ] is False


def test_g7_v5_rejects_hunger_record_with_zero_neglect_aggregate() -> None:
    row = _row(
        0,
        dead=1,
        survival={
            "deaths_in_run": 1,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
            "death_records": [
                {
                    "unit_id": 42,
                    "cause_enum": 2,
                    "cause_name": "HUNGER",
                    "cause_known": True,
                    "cause_source": "counters.death_cause",
                    "incident_id": 9,
                }
            ],
        },
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    criterion = result["criteria"]["neglect_deaths"]
    assert criterion["status"] == UNKNOWN
    assert criterion["observed"]["direct_neglect_deaths_from_records"] == 1
    assert result["evaluation_validity"]["status"] == FAIL
    assert result["status"] == UNKNOWN


def test_g7_v5_diagnostics_do_not_coerce_malformed_inputs_to_zero() -> None:
    row = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["tick_advance"]["ticks_advanced"] = "malformed"

    result = evaluate_g7(
        [row],
        _summary(
            duration_ticks="malformed",
            end_pop="malformed",
            peak_pop=0.5,
            total_score="malformed",
            score_version="malformed",
        ),
        gate_version=5,
    )

    diagnostics = result["diagnostics"]
    assert diagnostics["duration"]["status"] == "unavailable"
    assert diagnostics["duration"]["observed"]["trace_ticks"] is None
    assert diagnostics["duration"]["observed"]["summary_ticks"] is None
    assert diagnostics["duration"]["observed"]["summary_consistent"] is None
    assert diagnostics["population"]["status"] == "unavailable"
    assert diagnostics["population"]["observed"]["end_population"] is None
    assert diagnostics["population"]["observed"]["peak_population"] is None
    assert diagnostics["scalar_score"]["status"] == "unavailable"
    assert diagnostics["scalar_score"]["observed"]["score"] is None
    assert diagnostics["scalar_score"]["observed"]["score_version"] is None


def test_g7_v5_requires_every_action_row_to_share_one_run_id() -> None:
    first = _row(0)
    second = _row(1)
    second.pop("run_id")

    result = evaluate_g7(
        [first, second],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["provenance_completeness"]["status"] == UNKNOWN
    assert result["provenance_completeness"]["observed"][
        "trace_run_binding_complete"
    ] is False
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_never_backfills_missing_terminal_metrics() -> None:
    first = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    first["metrics"].update(
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )
    final = _row(1, survival=first["observation"]["survival"])
    final.pop("metrics")

    result = evaluate_g7(
        [first, final],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["criteria"]["owned_accessible_layout_rooms"]["status"] == UNKNOWN
    assert result["criteria"]["owned_operational_provisioning"]["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_requires_terminal_post_advance_state_without_pre_action_fallback() -> (
    None
):
    row = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row.pop("state_after_advance")

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    assert result["provenance_completeness"]["status"] == UNKNOWN
    assert result["provenance_completeness"]["observed"][
        "final_state_evidence_complete"
    ] is False
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN


def test_g7_v5_requires_current_operational_farm_evidence() -> None:
    row = _row(
        0,
        survival={
            "deaths_in_run": 0,
            "death_evidence_complete": True,
            "death_causes_known": True,
            "neglect_deaths": 0,
        },
    )
    row["metrics"].update(
        {
            "governed_owned_building_evidence_complete": True,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_completed_stills": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_operational_farm_evidence_complete": False,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_evidence_complete": True,
        }
    )

    result = evaluate_g7(
        [row],
        _summary(governed_owned_accessible_layout_rooms=3),
        gate_version=5,
    )

    criterion = result["criteria"]["owned_operational_provisioning"]
    assert criterion["status"] == UNKNOWN
    assert criterion["observed"]["owned_operational_farm_plots"] is None
    assert criterion["observed"][
        "owned_operational_farm_evidence_complete"
    ] is False


def test_g7_v5_missing_provenance_is_unknown_not_gameplay_failure() -> None:
    row = _row(0)
    row["screen_text"] = "(screen capture failed)"

    result = evaluate_g7([row], _summary(), gate_version=5)

    assert result["status"] == UNKNOWN
    assert result["evaluation_validity"]["status"] == UNKNOWN
    assert result["provenance_completeness"]["status"] == UNKNOWN


def test_g7_room_criterion_is_unknown_when_final_fort_read_failed() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival)
    row["metrics"]["fort_metrics_observed"] = False

    result = evaluate_g7([row], _summary())

    rooms = result["criteria"]["functional_rooms"]
    assert rooms["status"] == UNKNOWN
    assert rooms["observed"] == {
        "trace_rooms": 3,
        "summary_rooms": 3,
        "summary_consistent": True,
        "fort_metrics_observed": False,
    }
    assert rooms["reason"] == "final trace lacks an attested fort structure observation"


def test_g7_rejects_summary_rooms_that_disagree_with_final_trace() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival)
    row["metrics"]["fort_functional_rooms"] = 0

    result = evaluate_g7([row], _summary(fort_functional_rooms=3))

    rooms = result["criteria"]["functional_rooms"]
    assert result["status"] == FAIL
    assert rooms["status"] == FAIL
    assert rooms["observed"] == {
        "trace_rooms": 0,
        "summary_rooms": 3,
        "summary_consistent": False,
        "fort_metrics_observed": True,
    }
    assert (
        rooms["reason"] == "summary room count disagrees with final trace observation"
    )


def test_g7_requires_strict_boolean_final_fort_attestation() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    for attestation in (None, 1, "true"):
        row = _row(0, survival=survival)
        if attestation is None:
            row["metrics"].pop("fort_metrics_observed")
        else:
            row["metrics"]["fort_metrics_observed"] = attestation

        result = evaluate_g7([row], _summary())

        assert result["criteria"]["functional_rooms"]["status"] == UNKNOWN


def test_g7_v4_scalar_score_is_diagnostic_while_v3_retains_score_gate() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }

    row = _row(0, survival=survival)
    result = evaluate_g7([row], _summary(score_version=3))

    assert result["status"] == PASS
    assert "scalar_score" not in result["criteria"]
    assert result["diagnostics"]["scalar_score"]["observed"]["score_version"] == 3

    legacy = evaluate_g7([row], _summary(score_version=3), gate_version=3)
    assert legacy["status"] == FAIL
    assert legacy["criteria"]["scalar_score"]["status"] == FAIL
    assert legacy["criteria"]["scalar_score"]["required"] == "score-v5 >=150.0"


def test_g7_failure_wins_over_unknown_evidence() -> None:
    result = evaluate_g7(
        [
            _row(
                0,
                dead=1,
                drink=0,
                completed_beds=None,
                ticks_advanced=199_691,
            )
        ],
        _summary(
            duration_ticks=199_691,
            fort_functional_rooms=0,
            total_score=209.44,
            rubric={"rubric_score": 63.79, "blockers": []},
        ),
    )
    assert result["status"] == FAIL
    assert "duration" not in result["criteria"]
    assert result["diagnostics"]["duration"]["observed"]["trace_ticks"] == 199_691
    assert result["criteria"]["food_and_drink_loop"]["status"] == FAIL
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["installed_beds"]["status"] == UNKNOWN


def test_g7_death_without_cause_is_unknown_when_everything_else_passes() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
    }
    result = evaluate_g7([_row(0, survival=survival, dead=1)], _summary())

    assert result["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN


def test_g7_zero_deaths_without_complete_run_scoped_evidence_is_unknown() -> None:
    result = evaluate_g7([_row(0)], _summary())

    assert result["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert "run-scoped" in result["criteria"]["neglect_deaths"]["reason"]


def test_g7_v4_duration_is_diagnostic_only_even_when_summary_disagrees() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(
        0,
        ticks_advanced=1_000,
        survival=survival,
    )

    result = evaluate_g7([row], _summary(duration_ticks=403_200))

    assert result["status"] == PASS
    assert "duration" not in result["criteria"]
    duration = result["diagnostics"]["duration"]
    assert duration["status"] == "inconsistent"
    assert duration["gate_effect"] == "none"
    assert duration["observed"] == {
        "trace_ticks": 1_000,
        "summary_ticks": 403_200,
        "summary_consistent": False,
    }


def test_g7_v4_population_is_diagnostic_only() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    row = _row(0, survival=survival, completed_beds=3)
    row["observation"]["population"] = 7
    row["state_after_advance"]["population"] = 7

    result = evaluate_g7(
        [row],
        _summary(end_pop=7, peak_pop=7),
    )

    assert result["status"] == PASS
    assert "population" not in result["criteria"]
    population = result["diagnostics"]["population"]
    assert population["gate_effect"] == "none"
    assert population["observed"] == {
        "end_population": 7,
        "peak_population": 7,
        "deaths_in_run": 0,
    }


def test_g7_v3_retains_frozen_duration_gate_for_legacy_rescoring() -> None:
    row = _row(0, ticks_advanced=1_000)

    result = evaluate_g7(
        [row],
        _summary(duration_ticks=1_000),
        gate_version=3,
    )

    assert result["gate_version"] == 3
    assert result["status"] == FAIL
    assert result["criteria"]["duration"]["status"] == FAIL
    assert result["criteria"]["duration"]["required"] == ">=403200"
    assert result["criteria"]["population"]["required"] == ">=15"
    assert result["criteria"]["scalar_score"]["required"] == "score-v5 >=150.0"
    assert result["diagnostics"] == {}


def test_g7_missing_step_evidence_fails_closed() -> None:
    row = _row(0)
    row.pop("screen_text")
    result = evaluate_g7([row], _summary())

    assert result["status"] == FAIL
    assert result["criteria"]["evidence"]["status"] == FAIL


def test_g7_validation_rejection_keeps_complete_evidence_without_progress() -> None:
    row = _row(0, ticks_advanced=0)
    row["validation"] = {"valid": False, "reason": "bounded target rejected"}
    row["execute"] = {
        "accepted": False,
        "why": "bounded target rejected",
        "provenance": "dfhack_governed",
        "gameplay_progress_eligible": False,
        "validation_rejected": True,
    }
    row["gameplay_proof"] = {
        "ok": False,
        "source": "dfhack-map-and-state",
        "provenance": "dfhack_governed",
        "gameplay_progress_eligible": False,
    }

    result = evaluate_g7([row], _summary(duration_ticks=0))

    assert result["criteria"]["evidence"]["status"] == PASS
    assert "duration" not in result["criteria"]
    assert result["diagnostics"]["duration"]["observed"]["trace_ticks"] == 0


def test_g7_screen_capture_error_is_not_counted_as_evidence() -> None:
    row = _row(0)
    row["screen_text"] = "(screen capture failed)"

    result = evaluate_g7([row], _summary())

    assert result["criteria"]["evidence"]["status"] == FAIL


def test_g7_rejects_complete_survival_facts_from_another_run() -> None:
    survival = {
        "run_id": "stale-run",
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }

    result = evaluate_g7([_row(0, survival=survival, dead=1)], _summary())

    assert result["criteria"]["food_and_drink_loop"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
