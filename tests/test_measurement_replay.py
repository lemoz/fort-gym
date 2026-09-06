from __future__ import annotations

from fort_gym.bench.eval.measurement_replay import (
    historical_sensor_coverage,
    replay_measurements,
)


def test_historical_replay_counts_partial_constructions_without_claiming_v5_completion() -> (
    None
):
    records = [
        {
            "action": {"type": "BUILD", "params": {"kind": "Wall"}},
            "execute": {
                "accepted": False,
                "result": {
                    "partial": True,
                    "placed": [
                        {"x": 10, "y": 20, "z": 5, "building_id": 42},
                    ],
                },
            },
            "metrics": {},
            "state_after_advance": {
                "fort": {
                    "construction_tiles": [[10, 20, 5]],
                    "spaces": [{"kind": "bedroom"}],
                }
            },
        }
    ]

    coverage = historical_sensor_coverage(records)

    assert coverage["claimed_partial_placement_coordinates"] == 1
    assert coverage["claimed_constructions_observed_final"] == 1
    assert coverage["final_unique_construction_coordinates"] == 1
    assert coverage["v5_replay_complete"] is False
    assert coverage["missing_evidence_policy"] == "unknown_not_zero"


def test_historical_replay_reports_missing_v5_domains_as_unknown() -> None:
    report = replay_measurements(
        [
            {
                "action": {"type": "WAIT", "params": {}},
                "execute": {"accepted": True, "provenance": "dfhack_governed"},
                "metrics": {},
                "state_after_advance": {"survival": {}},
            }
        ],
        {},
    )

    assert report["comparison_status"] == "incomplete_or_invalid_evidence"
    assert "unknown_behavior_domains" in report["comparison_incomplete_reasons"]
    assert report["calibration_behavior_v2"]["unknown_domain_count"] == 6
    assert all(
        value is None
        for value in report["calibration_behavior_v2"]["achieved_domains"].values()
    )


def test_replay_requires_final_row_sensors_not_early_rows() -> None:
    records = [
        {
            "run_id": "replay",
            "metrics": {
                "governed_owned_room_evidence_complete": True,
                "governed_owned_building_evidence_complete": True,
                "governed_owned_output_evidence_complete": True,
            },
            "state_after_advance": {
                "survival": {
                    "run_id": "replay",
                    "flow_evidence_complete": True,
                    "death_evidence_complete": True,
                    "food_produced_in_run": 1,
                    "food_consumed_in_run": 0,
                    "drink_produced_in_run": 1,
                    "drink_consumed_in_run": 0,
                }
            },
        },
        {"run_id": "replay", "metrics": {}, "state_after_advance": {}},
    ]

    coverage = historical_sensor_coverage(
        records,
        {
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_completed_beds": 3,
        },
    )

    assert coverage["v5_replay_complete"] is False
    assert coverage["final_v5_sensor_status"]["room"] is False


def test_replay_does_not_backfill_final_state_from_pre_action_observation() -> None:
    coverage = historical_sensor_coverage(
        [
            {
                "run_id": "replay",
                "action": {"type": "WAIT", "params": {}},
                "observation": {
                    "survival": {
                        "run_id": "replay",
                        "flow_evidence_complete": True,
                        "food_produced_in_run": 1,
                        "food_consumed_in_run": 0,
                        "drink_produced_in_run": 1,
                        "drink_consumed_in_run": 0,
                        "death_evidence_complete": True,
                        "deaths_in_run": 0,
                    }
                },
                "metrics": {
                    "governed_owned_room_evidence_complete": True,
                    "governed_owned_building_evidence_complete": True,
                    "governed_owned_output_evidence_complete": True,
                },
            }
        ]
    )

    assert coverage["final_v5_sensor_status"]["survival_flow"] is False
    assert coverage["final_v5_sensor_status"]["death"] is False


def test_replay_unwraps_public_summary_but_labels_compact_data_incomplete() -> None:
    report = replay_measurements([], {"run": {}, "summary": {"peak_pop": 21}})

    assert report["summary_source"] == "public_wrapper"
    assert report["summary_is_full_for_v5"] is False
    assert report["counterfactual_g7_v4_input_complete"] is False
    assert (
        report["counterfactual_g7_v4"]["criteria"]["functional_rooms"]["status"]
        == "unknown"
    )
    assert report["comparison_status"] == "incomplete_or_invalid_evidence"
    assert "compact_summary" in report["comparison_incomplete_reasons"]


def test_replay_null_summary_measurements_are_incomplete_not_present() -> None:
    coverage = historical_sensor_coverage(
        [],
        {
            "governed_owned_accessible_layout_rooms": None,
            "duration_ticks": 100,
            "end_pop": 7,
        },
    )

    assert coverage["final_v5_sensor_status"]["full_summary"] is False


def test_replay_requires_known_death_causes_when_deaths_occurred() -> None:
    records = [
        {
            "run_id": "replay",
            "metrics": {
                "governed_owned_room_evidence_complete": True,
                "governed_owned_building_evidence_complete": True,
                "governed_owned_output_evidence_complete": True,
            },
            "state_after_advance": {
                "survival": {
                    "run_id": "replay",
                    "flow_evidence_complete": True,
                    "food_produced_in_run": 1,
                    "food_consumed_in_run": 0,
                    "drink_produced_in_run": 1,
                    "drink_consumed_in_run": 0,
                    "death_evidence_complete": True,
                    "deaths_in_run": 1,
                    "death_causes_known": False,
                }
            },
        }
    ]

    coverage = historical_sensor_coverage(
        records,
        {
            "governed_owned_accessible_layout_rooms": 3,
            "duration_ticks": 100,
            "end_pop": 6,
        },
    )

    assert coverage["final_v5_sensor_status"]["death"] is False
    assert coverage["v5_replay_complete"] is False


def test_replay_null_flow_facts_are_missing_sensor_evidence() -> None:
    coverage = historical_sensor_coverage(
        [
            {
                "run_id": "replay",
                "metrics": {
                    "governed_owned_room_evidence_complete": True,
                    "governed_owned_building_evidence_complete": True,
                    "governed_owned_output_evidence_complete": True,
                },
                "state_after_advance": {
                    "survival": {
                        "run_id": "replay",
                        "flow_evidence_complete": True,
                        "food_produced_in_run": None,
                        "food_consumed_in_run": None,
                        "drink_produced_in_run": None,
                        "drink_consumed_in_run": None,
                        "death_evidence_complete": True,
                        "deaths_in_run": 0,
                    }
                },
            }
        ],
        {
            "governed_owned_accessible_layout_rooms": 3,
            "duration_ticks": 100,
            "end_pop": 7,
        },
    )

    assert coverage["final_v5_sensor_status"]["survival_flow"] is False
    assert coverage["v5_replay_complete"] is False


def test_replay_rejects_nonintegral_negative_and_unscoped_survival_facts() -> None:
    base = {
        "run_id": "replay",
        "action": {"type": "WAIT", "params": {}},
        "metrics": {
            "governed_owned_room_evidence_complete": True,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_output_evidence_complete": True,
        },
        "state_after_advance": {
            "survival": {
                "run_id": "replay",
                "flow_evidence_complete": True,
                "food_produced_in_run": 1.5,
                "food_consumed_in_run": 0,
                "drink_produced_in_run": 1,
                "drink_consumed_in_run": -1,
                "death_evidence_complete": True,
                "deaths_in_run": -1,
                "death_causes_known": True,
                "neglect_deaths": 0,
            }
        },
    }

    coverage = historical_sensor_coverage([base])

    assert coverage["final_v5_sensor_status"]["survival_flow"] is False
    assert coverage["final_v5_sensor_status"]["death"] is False

    missing_run_id = {**base, "run_id": None}
    coverage = historical_sensor_coverage([missing_run_id])

    assert coverage["final_v5_sensor_status"]["survival_flow"] is False
    assert coverage["final_v5_sensor_status"]["death"] is False


def test_replay_accepts_explicit_room_and_output_lower_bound_proofs() -> None:
    coverage = historical_sensor_coverage(
        [
            {
                "run_id": "replay",
                "action": {"type": "WAIT", "params": {}},
                "metrics": {
                    "governed_owned_room_evidence_complete": False,
                    "governed_owned_layout_room_lower_bound_proven": True,
                    "governed_owned_building_evidence_complete": True,
                    "governed_owned_output_evidence_complete": False,
                    "governed_owned_output_lower_bound_proven": True,
                },
                "state_after_advance": {
                    "survival": {
                        "run_id": "replay",
                        "flow_evidence_complete": True,
                        "food_produced_in_run": 1,
                        "food_consumed_in_run": 0,
                        "drink_produced_in_run": 1,
                        "drink_consumed_in_run": 0,
                        "death_evidence_complete": True,
                        "deaths_in_run": 0,
                    }
                },
            }
        ],
        {
            "governed_owned_accessible_layout_rooms": 3,
            "duration_ticks": 1,
            "end_pop": 7,
        },
    )

    assert coverage["final_v5_sensor_status"]["room"] is True
    assert coverage["final_v5_sensor_status"]["output"] is True
    assert coverage["v5_replay_complete"] is True
