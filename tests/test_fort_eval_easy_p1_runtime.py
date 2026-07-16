from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from fort_gym.bench.eval.fort_eval_easy_p1 import (
    P1_CALIBRATION_MODEL,
    P1_CALIBRATION_REQUIRED_REGRESSION_TESTS,
    P1_PROTOCOL,
    P1_PROTOCOL_V3,
    P1_SEED_WORLD_SHA256,
    attest_seed_region3,
    enrich_openrouter_usage,
    p1_evaluation_is_publishable,
    p1_integrity_attestation,
    p1_measurement_calibration_is_complete,
    p1_task_verdict,
    p1_usage_is_publishable,
    resolved_model_digest,
    validate_p1_declaration,
)


def _initial_state() -> dict:
    return {
        "time": 16801,
        "population": 7,
        "pause_state": True,
        "stocks": {"food": 45, "drink": 60, "wealth": 9},
        "dead": 0,
        "hostiles": False,
        "risks": [],
        "work": {"workshop_count": 0},
        "fort": {
            "player_buildings": 0,
            "constructions": 0,
            "functional_rooms": 0,
            "nearby_trees": {"total": 213},
        },
        "crew": {
            "farm_plots": 0,
            "citizens": {
                "mining_labor": 1,
                "woodcutting_labor": 1,
                "carpentry_labor": 1,
            },
            "seeds": [{"token": "MUSHROOM_HELMET_PLUMP", "count": 5}],
        },
        "survival": {
            "active": True,
            "food_produced_in_run": 0,
            "drink_produced_in_run": 0,
            "deaths_in_run": 0,
        },
    }


def test_seed_region3_attestation_accepts_frozen_start() -> None:
    result = attest_seed_region3(
        _initial_state(),
        runtime_save="fortgym_runtime",
        seed_world_sha256=P1_SEED_WORLD_SHA256,
    )

    assert result["eligible"] is True
    assert result["failed_checks"] == []
    assert result["observed"]["nearby_trees"] == 213


def test_seed_region3_attestation_fails_closed_on_prior_world_change() -> None:
    state = _initial_state()
    state["fort"]["player_buildings"] = 1
    state["stocks"]["food"] = 44

    result = attest_seed_region3(
        state,
        runtime_save="fortgym_runtime",
        seed_world_sha256=P1_SEED_WORLD_SHA256,
    )

    assert result["eligible"] is False
    assert result["failed_checks"] == ["food", "no_fort_structures"]


def test_seed_region3_attestation_fails_closed_when_zero_valued_sensors_are_missing() -> (
    None
):
    state = _initial_state()
    del state["dead"]
    del state["risks"]
    del state["work"]["workshop_count"]
    del state["crew"]["farm_plots"]
    del state["fort"]["constructions"]
    del state["survival"]["deaths_in_run"]

    result = attest_seed_region3(
        state,
        runtime_save="fortgym_runtime",
        seed_world_sha256=P1_SEED_WORLD_SHA256,
    )

    assert result["eligible"] is False
    assert {
        "clean_g7_ledger",
        "no_deaths",
        "no_farm_plots",
        "no_fort_structures",
        "no_risks",
        "no_workshops",
    }.issubset(result["failed_checks"])

    malformed = _initial_state()
    malformed["dead"] = "0"
    malformed["work"]["workshop_count"] = 0.0
    assert (
        attest_seed_region3(
            malformed,
            runtime_save="fortgym_runtime",
            seed_world_sha256=P1_SEED_WORLD_SHA256,
        )["eligible"]
        is False
    )


def test_p1_declaration_requires_exact_arm_seed_and_budget_but_blocks_calibration() -> (
    None
):
    with pytest.raises(ValueError, match="calibration-only"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
        )

    with pytest.raises(ValueError, match="ticks_per_step must be 2500"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2000,
        )

    with pytest.raises(ValueError, match="runtime_save must be region1"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="other-runtime",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
        )


def test_measurement_unlock_requires_pinned_reviewed_live_evidence(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.eval import fort_eval_easy_p1 as contract

    calibration_commit = "a" * 40
    runtime_proto_digest = "b" * 64
    monkeypatch.setattr(
        contract,
        "p1_remote_proto_runtime_digest",
        lambda: runtime_proto_digest,
    )
    trace_items = []
    trace_payloads = {}
    for index, scenario in enumerate(
        (
            "owned_layout_and_provisioning",
            "death_cause_fallback",
            "sensor_dropout",
        )
    ):
        run_id = f"run-{index}"
        artifact = tmp_path / f"{scenario}.jsonl"
        metrics = {
            # The positive lower bound remains valid even if an unrelated
            # component prevents an exhaustive global space enumeration.
            "governed_owned_room_evidence_complete": False,
            "governed_owned_building_evidence_complete": True,
            "governed_owned_output_evidence_complete": True,
            "governed_owned_accessible_layout_rooms": 3,
            "governed_owned_layout_room_lower_bound_proven": True,
            "governed_owned_unique_construction_tiles": 4,
            "governed_owned_completed_beds": 3,
            "governed_owned_completed_farm_plots": 1,
            "governed_owned_operational_farm_plots": 1,
            "governed_owned_operational_farm_evidence_complete": True,
            "governed_owned_completed_stills": 1,
            "governed_owned_output_units_by_job": {"brew": 1},
            "governed_owned_output_attribution_scope": (
                "exact_order_job_completion_and_uncontaminated_positive_output_delta"
            ),
            "governed_owned_output_manager_orders_observed_complete": True,
            "governed_owned_output_manager_orders_present": False,
            "governed_owned_layout_room_signatures": ["room-1", "room-2", "room-3"],
            "governed_owned_room_structural_evidence": {
                "room-1": {"ownership_basis": "owned_excavation_majority"},
                "room-2": {"ownership_basis": "owned_construction_majority"},
                "room-3": {"ownership_basis": "owned_door_closure"},
            },
        }
        state_after_advance = {
            "survival": {
                "deaths_in_run": 0,
                "death_evidence_complete": True,
                "death_causes_known": True,
            }
        }
        if scenario == "death_cause_fallback":
            state_after_advance = {
                "survival": {
                    "deaths_in_run": 1,
                    "death_evidence_complete": True,
                    "death_causes_known": True,
                    "measurement_calibration_mode": "force_incident_death_cause",
                },
                "crew": {
                    "dead_citizen_records": [
                        {"cause_source": ("world.incidents.all[death_id].death_cause")}
                    ]
                },
            }
        if scenario == "sensor_dropout":
            metrics["governed_owned_room_evidence_complete"] = False
            state_after_advance["fort"] = {
                "measurement_calibration_fault": {
                    "sensor": "fort_metrics",
                    "field": "spaces_truncated",
                    "value": True,
                }
            }
        trace_payload = (
            json.dumps(
                {
                    "run_id": run_id,
                    "action": {
                        "type": "WAIT",
                        "params": {},
                        "advance_ticks": 1,
                    },
                    "execute": {
                        "accepted": True,
                        "provenance": "dfhack_governed",
                    },
                    "metrics": metrics,
                    "state_after_advance": state_after_advance,
                    "events": (
                        [
                            {
                                "type": "measurement_calibration_fixture",
                                "data": {
                                    "run_id": run_id,
                                    "step": 0,
                                    "ok": True,
                                    "fixture": "dfhack_exterminate_friendly_instant",
                                    "target": "DWARF",
                                    "limit": 1,
                                    "output": "marked one friendly unit",
                                },
                            }
                        ]
                        if scenario == "death_cause_fallback"
                        else []
                    ),
                }
            )
            + "\n"
        ).encode()
        trace_payloads[scenario] = trace_payload
        artifact.write_bytes(trace_payload)
        summary_artifact = tmp_path / f"{scenario}-summary.json"
        summary_artifact.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "backend": "dfhack",
                    "model": P1_CALIBRATION_MODEL,
                    "evaluation_protocol": P1_PROTOCOL,
                    "evaluator_version": "outcome-vector-v1+g7-v5",
                    "remote_proto_runtime_sha256": runtime_proto_digest,
                    "fort_gym_commit": calibration_commit,
                    "measurement_calibration_scenario": scenario,
                    "measurement_calibration_fixture": (
                        {
                            "ok": True,
                            "fixture": "dfhack_exterminate_friendly_instant",
                            "target": "DWARF",
                            "limit": 1,
                            "output": "marked one friendly unit",
                        }
                        if scenario == "death_cause_fallback"
                        else {}
                    ),
                    "seed_attestation": {"eligible": True},
                    "evaluation_validity": {
                        "status": "unknown" if scenario == "sensor_dropout" else "pass"
                    },
                    "gameplay_outcome": {
                        "status": "pass",
                        "criteria": {
                            "owned_operational_provisioning": {"status": "pass"},
                            "owned_accessible_layout_rooms": {"status": "pass"},
                            "initial_cohort_bed_capacity": {"status": "pass"},
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        trace_item = {
            "scenario": scenario,
            "run_id": run_id,
            "artifact": artifact.name,
            "trace_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "summary_artifact": summary_artifact.name,
            "summary_sha256": hashlib.sha256(summary_artifact.read_bytes()).hexdigest(),
        }
        if scenario == "sensor_dropout":
            trace_item["sensor_field"] = "governed_owned_room_evidence_complete"
        trace_items.append(trace_item)
    regression_report = tmp_path / "measurement-regressions.xml"
    regression_report.write_text(
        "<testsuite>"
        + "".join(
            f'<testcase name="{name}" />'
            for name in sorted(P1_CALIBRATION_REQUIRED_REGRESSION_TESTS)
        )
        + "</testsuite>",
        encoding="utf-8",
    )
    evidence = {
        "protocol": P1_PROTOCOL,
        "evaluator_version": "outcome-vector-v1+g7-v5",
        "seed_world_sha256": P1_SEED_WORLD_SHA256,
        "manifest_semantic_sha256": contract.p1_manifest_semantic_digest(),
        "measurement_code_sha256": contract.p1_measurement_code_digest(),
        "remote_proto_runtime_sha256": runtime_proto_digest,
        "calibration_fort_gym_commit": calibration_commit,
        "review_status": "approved",
        "reviewer": "test-reviewer",
        "live_traces": trace_items,
        "regression_report": {
            "artifact": regression_report.name,
            "sha256": hashlib.sha256(regression_report.read_bytes()).hexdigest(),
        },
    }
    path = tmp_path / "calibration.json"
    raw = json.dumps(evidence, sort_keys=True).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(contract, "P1_MEASUREMENT_CALIBRATION_COMPLETE", True)
    monkeypatch.setattr(contract, "P1_MEASUREMENT_CALIBRATION_EVIDENCE_PATH", path)
    monkeypatch.setattr(contract, "P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        contract,
        "P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )

    assert p1_measurement_calibration_is_complete() is True

    monkeypatch.setattr(
        contract,
        "p1_remote_proto_runtime_digest",
        lambda: "c" * 64,
    )
    assert p1_measurement_calibration_is_complete() is False
    monkeypatch.setattr(
        contract,
        "p1_remote_proto_runtime_digest",
        lambda: runtime_proto_digest,
    )

    death_item = next(
        item for item in trace_items if item["scenario"] == "death_cause_fallback"
    )
    death_path = tmp_path / "death_cause_fallback.jsonl"
    observation_only = json.loads(
        trace_payloads["death_cause_fallback"].decode("utf-8")
    )
    observation_only["observation"] = observation_only.pop("state_after_advance")
    observation_only_payload = (json.dumps(observation_only) + "\n").encode()
    death_path.write_bytes(observation_only_payload)
    death_item["trace_sha256"] = hashlib.sha256(observation_only_payload).hexdigest()
    assert (
        contract._live_calibration_traces_are_bound(trace_items, calibration_commit)
        is False
    )
    death_path.write_bytes(trace_payloads["death_cause_fallback"])
    death_item["trace_sha256"] = hashlib.sha256(
        trace_payloads["death_cause_fallback"]
    ).hexdigest()

    failed_report = tmp_path / "failed-regressions.xml"
    failed_name = sorted(P1_CALIBRATION_REQUIRED_REGRESSION_TESTS)[0]
    failed_report.write_text(
        f'<testsuite><testcase name="{failed_name}"><failure /></testcase></testsuite>',
        encoding="utf-8",
    )
    assert (
        contract._calibration_regression_report_is_bound(
            {
                "artifact": failed_report.name,
                "sha256": hashlib.sha256(failed_report.read_bytes()).hexdigest(),
            }
        )
        is False
    )

    (tmp_path / "sensor_dropout.jsonl").write_text(
        json.dumps({"run_id": "invented"}) + "\n", encoding="utf-8"
    )
    assert p1_measurement_calibration_is_complete() is False

    (tmp_path / "sensor_dropout.jsonl").write_bytes(trace_payloads["sensor_dropout"])
    monkeypatch.setattr(
        contract, "P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256", "0" * 64
    )
    assert p1_measurement_calibration_is_complete() is False


def test_scripted_live_calibration_bootstraps_without_unlocking_model_arms() -> None:
    validate_p1_declaration(
        protocol=P1_PROTOCOL,
        backend="dfhack",
        model=P1_CALIBRATION_MODEL,
        seed_save="seed_region3_fresh",
        runtime_save="region1",
        preserve_save=False,
        max_steps=200,
        ticks_per_step=2500,
        measurement_calibration_scenario="owned_layout_and_provisioning",
    )

    with pytest.raises(ValueError, match="measurement calibration model"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
            measurement_calibration_scenario="owned_layout_and_provisioning",
        )


def test_measurement_calibration_scenario_requires_v5_protocol() -> None:
    with pytest.raises(ValueError, match="require.*G7-v5 protocol"):
        validate_p1_declaration(
            protocol=None,
            backend="dfhack",
            model=P1_CALIBRATION_MODEL,
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
            measurement_calibration_scenario="sensor_dropout",
        )


def test_measurement_digest_normalizes_only_post_calibration_lock_values() -> None:
    from fort_gym.bench.eval import fort_eval_easy_p1 as contract

    first = b"\n".join(
        (
            b"P1_MEASUREMENT_CALIBRATION_COMPLETE = False",
            b"P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str | None = None",
            b"validator_rule = 'strict'",
        )
    )
    locked = b"\n".join(
        (
            b"P1_MEASUREMENT_CALIBRATION_COMPLETE = True",
            b"P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str | None = 'a' * 64",
            b"validator_rule = 'strict'",
        )
    )
    changed_validator = locked.replace(b"'strict'", b"'loose'")

    assert contract._normalized_calibration_contract_source(first) == (
        contract._normalized_calibration_contract_source(locked)
    )
    assert contract._normalized_calibration_contract_source(first) != (
        contract._normalized_calibration_contract_source(changed_validator)
    )


def test_measurement_digest_covers_runtime_and_calibration_dependencies(
    monkeypatch,
) -> None:
    from fort_gym.bench.eval import fort_eval_easy_p1 as contract

    required = {
        "fort_gym/bench/config.py",
        "fort_gym/bench/dfhack_exec.py",
        "fort_gym/bench/tick_controller.py",
        "fort_gym/bench/tick_receipt.py",
        "fort_gym/bench/env/dfhack_client.py",
        "fort_gym/bench/env/encoder.py",
        "fort_gym/bench/env/keystroke_exec.py",
        "fort_gym/bench/env/remote_proto/__init__.py",
        "fort_gym/bench/env/remote_proto/fetch_proto.py",
        "fort_gym/bench/env/state_reader.py",
        "fort_gym/bench/eval/milestones.py",
        "fort_gym/bench/eval/protocol.py",
        "fort_gym/bench/eval/scoring.py",
        "fort_gym/bench/run/seed_reset.py",
        "scripts/run_p1_live_calibration.py",
        "scripts/build_p1_live_calibration_bundle.py",
    }
    assert required <= set(contract.P1_MEASUREMENT_CODE_RELATIVE_PATHS)

    baseline = contract.p1_measurement_code_digest()
    original_read_bytes = Path.read_bytes

    def changed_tick_controller(path: Path) -> bytes:
        source = original_read_bytes(path)
        if path.as_posix().endswith("fort_gym/bench/tick_controller.py"):
            return source + b"\n# digest sensitivity probe\n"
        return source

    monkeypatch.setattr(Path, "read_bytes", changed_tick_controller)
    assert contract.p1_measurement_code_digest() != baseline


def test_manifest_semantic_digest_survives_only_activation_lifecycle_flip(
    tmp_path,
) -> None:
    from fort_gym.bench.eval import fort_eval_easy_p1 as contract

    manifest = yaml.safe_load(contract.P1_MANIFEST_PATH.read_text(encoding="utf-8"))
    calibration = tmp_path / "calibration.yaml"
    active = tmp_path / "active.yaml"
    changed = tmp_path / "changed.yaml"
    calibration.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    active_manifest = copy.deepcopy(manifest)
    active_manifest["status"] = "provisional"
    active_manifest["publication"]["calibration_results_public"] = True
    active_manifest["comparability"]["pair_comparison_enabled"] = True
    active_manifest["comparability"]["pair_comparison_reason"] = "calibration approved"
    active.write_text(yaml.safe_dump(active_manifest), encoding="utf-8")

    changed_manifest = copy.deepcopy(active_manifest)
    changed_manifest["task"]["objective"] = "different benchmark semantics"
    changed.write_text(yaml.safe_dump(changed_manifest), encoding="utf-8")

    assert contract.p1_manifest_semantic_digest(calibration) == (
        contract.p1_manifest_semantic_digest(active)
    )
    assert contract.p1_manifest_semantic_digest(calibration) != (
        contract.p1_manifest_semantic_digest(changed)
    )

    with pytest.raises(ValueError, match="scenario is not declared"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model=P1_CALIBRATION_MODEL,
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
            measurement_calibration_scenario="invented",
        )


def test_bundle_builder_binds_clean_checkout_to_trace_commit(
    monkeypatch, tmp_path
) -> None:
    from scripts import build_p1_live_calibration_bundle as builder

    commit = "a" * 40
    outputs = iter((f"{commit}\n", ""))

    def fake_run(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    builder._require_clean_checkout_at_commit(tmp_path, commit)


def test_bundle_builder_rejects_wrong_or_dirty_checkout(monkeypatch, tmp_path) -> None:
    from scripts import build_p1_live_calibration_bundle as builder

    commit = "a" * 40
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=f"{'b' * 40}\n"),
    )
    with pytest.raises(RuntimeError, match="does not match trace commit"):
        builder._require_clean_checkout_at_commit(tmp_path, commit)

    outputs = iter((f"{commit}\n", "?? untracked-proof.py\n"))

    def fake_dirty_run(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(builder.subprocess, "run", fake_dirty_run)
    with pytest.raises(RuntimeError, match="requires a clean checkout"):
        builder._require_clean_checkout_at_commit(tmp_path, commit)


def test_live_calibration_runner_rejects_untracked_checkout(monkeypatch) -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="?? untracked-plan.json\n")

    monkeypatch.setattr(calibration_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="checkout is dirty"):
        calibration_runner._require_clean_checkout()

    assert calls[0][0] == [
        "git",
        "status",
        "--porcelain",
        "--untracked-files=all",
    ]


def test_owned_calibration_plan_is_bounded_and_keeps_a_settlement_buffer() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    actions = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )

    assert len(actions) == 125
    assert [action["type"] for action in actions[:15]] == [
        "DIG",
        "DIG",
        "DIG",
        "DIG",
        "DIG",
        "DIG",
        "DIG",
        "WAIT",
        "WAIT",
        "WAIT",
        "WAIT",
        "WAIT",
        "WAIT",
        "WAIT",
        "BUILD",
    ]
    assert all(action["type"] != "INTERACT" for action in actions)
    assert [action["type"] for action in actions[-20:]] == ["WAIT"] * 20
    assert [
        action["params"]["job"]
        for action in actions
        if action["type"] == "ORDER" and action["params"]["job"] == "brew"
    ] == ["brew"]
    wall_indices = [
        index
        for index, action in enumerate(actions)
        if action["type"] == "BUILD" and action["params"]["kind"] == "Wall"
    ]
    assert len(wall_indices) == 27
    assert all(
        actions[index]["params"]["x2"] is None
        and actions[index]["params"]["y2"] is None
        and actions[index + 1]["type"] == "WAIT"
        for index in wall_indices
    )
    assert actions[14]["params"] == {
        "kind": "CarpenterWorkshop",
        "structure": None,
        "material": None,
        "location": None,
        "x": 94,
        "y": 93,
        "z": 161,
        "x2": None,
        "y2": None,
    }


def test_live_calibration_agent_waits_for_observed_workshop() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    action = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )[16]
    agent = calibration_runner.CalibrationPlanAgent([action])

    waiting = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "work": {"carpenter_workshops_usable": 0},
            "crew": {"farm_plot_details": []},
        },
    )
    ready = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "work": {"carpenter_workshops_usable": 1},
            "crew": {"farm_plot_details": []},
        },
    )

    assert waiting["type"] == "WAIT"
    assert waiting["advance_ticks"] == 2500
    assert ready["type"] == "ORDER"
    assert ready["params"]["job"] == "barrel"


def test_live_calibration_agent_waits_for_produced_furniture() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    action = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )[56]
    agent = calibration_runner.CalibrationPlanAgent([action])

    waiting = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {
                "farm_plot_details": [],
                "goods": {"bed": 1},
                "placed_furniture": {"bed": 1},
            },
        },
    )
    ready = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {
                "farm_plot_details": [],
                "goods": {"bed": 2},
                "placed_furniture": {"bed": 1},
            },
        },
    )

    assert waiting["type"] == "WAIT"
    assert ready["type"] == "BUILD"
    assert ready["params"]["kind"] == "Bed"


def test_live_calibration_agent_waits_for_observed_brew_inputs() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    action = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )[104]
    agent = calibration_runner.CalibrationPlanAgent([action])
    base_crew = {
        "farm_plot_details": [],
        "workshops": [
            {
                "subtype": "Still",
                "stage_read_ok": True,
                "built": True,
            }
        ],
    }

    waiting = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {
                **base_crew,
                "production_inputs": {
                    "brewable_plant_stacks": 0,
                    "empty_barrels": 1,
                },
            },
        },
    )
    ready = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {
                **base_crew,
                "production_inputs": {
                    "brewable_plant_stacks": 1,
                    "empty_barrels": 1,
                },
            },
        },
    )

    assert waiting["type"] == "WAIT"
    assert ready["type"] == "ORDER"
    assert ready["params"]["job"] == "brew"


def test_live_calibration_agent_remaps_farm_ids_from_observation() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    actions = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )
    agent = calibration_runner.CalibrationPlanAgent(
        [actions[24], actions[25], actions[25]]
    )

    build = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {"farm_plot_details": []},
        },
    )
    live_state = {
        "viewscreen_type": "viewscreen_dwarfmodest",
        "crew": {"farm_plot_details": [{"id": 31, "built": True}]},
    }
    first_farm = agent.decide("main map", live_state)
    second_farm = agent.decide("main map", live_state)

    assert build["type"] == "BUILD"
    assert first_farm["params"]["building_id"] == 31
    assert second_farm["params"]["building_id"] == 31


def test_live_calibration_agent_recovers_modal_without_consuming_plan_action() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    actions = calibration_runner._load_plan(
        Path("experiments/calibration/p1_g7_v5_owned_layout_and_provisioning.json"),
        scenario="owned_layout_and_provisioning",
    )
    agent = calibration_runner.CalibrationPlanAgent(
        [actions[0], actions[1]]
    )

    recovery = agent.decide(
        "a - Begin discussion",
        {
            "viewscreen_type": "viewscreen_topicmeetingst",
            "pause_state": True,
            "crew": {"farm_plot_details": []},
        },
    )
    first_plan_action = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {"farm_plot_details": []},
        },
    )
    second_plan_action = agent.decide(
        "main map",
        {
            "viewscreen_type": "viewscreen_dwarfmodest",
            "crew": {"farm_plot_details": []},
        },
    )

    assert recovery["type"] == "INTERACT"
    assert recovery["params"]["operation"] == "topic_option_a"
    assert first_plan_action["type"] == "DIG"
    assert second_plan_action["type"] == "DIG"


@pytest.mark.parametrize(
    "viewscreen",
    sorted(
        {
            "viewscreen_textviewerst",
            "viewscreen_meetingst",
            "viewscreen_requestagreementst",
            "viewscreen_topicmeeting_fill_land_holder_positionsst",
            "viewscreen_topicmeeting_takerequestsst",
            "viewscreen_storesst",
        }
    ),
)
def test_live_calibration_agent_uses_nonselecting_modal_recovery(
    viewscreen: str,
) -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    recovery = calibration_runner.CalibrationPlanAgent._interaction_recovery(
        "blocking menu",
        {"viewscreen_type": viewscreen, "pause_state": True},
    )

    assert recovery is not None
    assert recovery["type"] == "INTERACT"
    assert recovery["params"]["operation"] == "cancel"
    assert recovery["advance_ticks"] == 0


def test_live_calibration_agent_never_sends_input_without_pause_attestation() -> None:
    from scripts import run_p1_live_calibration as calibration_runner

    assert (
        calibration_runner.CalibrationPlanAgent._interaction_recovery(
            "Press Enter to close window",
            {"viewscreen_type": "viewscreen_textviewerst", "pause_state": False},
        )
        is None
    )


def test_task_failure_terminal_forces_failed_task_verdict() -> None:
    assert (
        p1_task_verdict(
            gameplay_outcome={"status": "pass"}, terminal_class="task_failure"
        )
        == "fail"
    )
    assert (
        p1_task_verdict(gameplay_outcome={"status": "pass"}, terminal_class="completed")
        == "pass"
    )


def test_non_p1_declaration_is_unchanged() -> None:
    validate_p1_declaration(
        protocol="fort-eval-easy-v1",
        backend="mock",
        model="random",
        seed_save=None,
        runtime_save=None,
        preserve_save=False,
        max_steps=1,
        ticks_per_step=1,
    )


def test_frozen_g7_v3_declaration_cannot_be_relaunched() -> None:
    with pytest.raises(ValueError, match="G7-v3 is frozen and no longer launchable"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL_V3,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
        )


def test_p1_usage_requires_provider_truth_but_cache_is_diagnostic() -> None:
    usage = {
        "calls": 200,
        "models": ["openai/gpt-5.6-sol"],
        "resolved_models": ["openai/gpt-5.6-sol-20260709"],
        "providers": ["OpenAI"],
        "generation_ids": [f"gen-{index}" for index in range(200)],
        "generation_metadata": [
            {
                "id": f"gen-{index}",
                "model": "openai/gpt-5.6-sol-20260709",
                "provider_name": "OpenAI",
                "total_cost": 0.01,
                "native_tokens_prompt": 5000,
                "native_tokens_completion": 500,
                "status": "available",
            }
            for index in range(200)
        ],
        "calls_missing_cost": 0,
        "calls_missing_resolved_model": 0,
        "cached_tokens": 900_000,
        "generation_telemetry_complete": True,
    }

    assert p1_usage_is_publishable(model="dfhack-governed-llm-gpt56-sol", usage=usage)
    assert "providers=OpenAI" in resolved_model_digest(
        model="dfhack-governed-llm-gpt56-sol", usage=usage
    )

    usage["cached_tokens"] = 0
    assert p1_usage_is_publishable(model="dfhack-governed-llm-gpt56-sol", usage=usage)

    usage["cached_tokens"] = 900_000
    usage["resolved_models"] = ["openai/gpt-5.5"]
    assert not p1_usage_is_publishable(
        model="dfhack-governed-llm-gpt56-sol", usage=usage
    )


def test_p1_publication_requires_valid_complete_evaluation_not_gameplay_pass() -> None:
    assert p1_evaluation_is_publishable(
        evaluation_validity={"status": "pass"},
        provenance_completeness={"status": "pass"},
    )
    assert not p1_evaluation_is_publishable(
        evaluation_validity={"status": "unknown"},
        provenance_completeness={"status": "pass"},
    )
    assert not p1_evaluation_is_publishable(
        evaluation_validity={"status": "pass"},
        provenance_completeness={"status": "unknown"},
    )


def test_generation_enrichment_retries_pending_rows_and_uses_provider_truth(
    monkeypatch,
) -> None:
    attempts: dict[str, int] = {}
    sleeps: list[float] = []

    class FakeResponse:
        def __init__(self, generation_id: str, *, unavailable: bool) -> None:
            self.generation_id = generation_id
            self.unavailable = unavailable

        def raise_for_status(self) -> None:
            if self.unavailable:
                raise RuntimeError("404 generation pending")

        def json(self) -> dict:
            return {
                "data": {
                    "model": "openai/gpt-5.6-sol-20260709",
                    "provider_name": "OpenAI",
                    "total_cost": 0.25,
                    "cache_discount": 0.1,
                    "native_tokens_prompt": 5000,
                    "native_tokens_completion": 500,
                }
            }

    def get(_url, *, params, headers, timeout):
        del headers, timeout
        generation_id = params["id"]
        attempts[generation_id] = attempts.get(generation_id, 0) + 1
        return FakeResponse(
            generation_id,
            unavailable=generation_id == "gen-pending" and attempts[generation_id] == 1,
        )

    monkeypatch.setattr(
        "fort_gym.bench.eval.fort_eval_easy_p1.import_module",
        lambda _name: SimpleNamespace(get=get),
    )
    monkeypatch.setattr(
        "fort_gym.bench.eval.fort_eval_easy_p1.time.sleep", sleeps.append
    )

    enriched = enrich_openrouter_usage(
        {
            "calls": 2,
            "generation_ids": ["gen-ready", "gen-pending"],
            "resolved_models": ["openai/gpt-5.6-sol"],
            "calls_missing_cost": 2,
            "calls_missing_resolved_model": 0,
        },
        api_key="test-key",
        base_url="https://openrouter.test/api/v1",
    )

    assert attempts == {"gen-ready": 1, "gen-pending": 2}
    assert sleeps == [1.0]
    assert enriched["resolved_models"] == ["openai/gpt-5.6-sol-20260709"]
    assert enriched["providers"] == ["OpenAI"]
    assert enriched["calls_missing_cost"] == 0
    assert enriched["calls_missing_resolved_model"] == 0
    assert enriched["provider_total_cost_usd"] == pytest.approx(0.5)
    assert enriched["generation_telemetry_complete"] is True
    by_id = {item["id"]: item for item in enriched["generation_metadata"]}
    assert by_id["gen-ready"]["lookup_attempts"] == 1
    assert by_id["gen-pending"]["lookup_attempts"] == 2


def test_generation_enrichment_bounds_unavailable_row_retries(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class MissingResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("404 generation unavailable")

    def get(_url, *, params, headers, timeout):
        nonlocal attempts
        del params, headers, timeout
        attempts += 1
        return MissingResponse()

    monkeypatch.setattr(
        "fort_gym.bench.eval.fort_eval_easy_p1.import_module",
        lambda _name: SimpleNamespace(get=get),
    )
    monkeypatch.setattr(
        "fort_gym.bench.eval.fort_eval_easy_p1.time.sleep", sleeps.append
    )

    enriched = enrich_openrouter_usage(
        {"calls": 1, "generation_ids": ["gen-missing"]},
        api_key="test-key",
        base_url="https://openrouter.test/api/v1",
    )

    assert attempts == 5
    assert sleeps == [1.0, 2.0, 4.0, 8.0]
    assert enriched["generation_telemetry_complete"] is False
    assert enriched["generation_telemetry_unavailable"] == 1
    assert enriched["calls_missing_cost"] == 1
    assert enriched["calls_missing_resolved_model"] == 1
    assert enriched["generation_metadata"][0]["lookup_attempts"] == 5


def test_p1_integrity_attestation_rejects_harness_terminal_failure() -> None:
    assert p1_integrity_attestation(None, run_failed=False) == {
        "schema_version": "fort-eval.integrity-attestation/v1",
        "status": "pass",
        "terminal_class": "completed",
        "terminal_reason": None,
    }

    failed = p1_integrity_attestation(
        {"code": "tick_request_attestation_failed", "requested_ticks": 2500},
        run_failed=True,
    )
    assert failed["status"] == "fail"
    assert failed["terminal_class"] == "invalid_execution"
    assert failed["terminal_reason"]["code"] == "tick_request_attestation_failed"

    aborted = p1_integrity_attestation(None, run_failed=True)
    assert aborted["status"] == "fail"
    assert aborted["terminal_class"] == "invalid_execution"
    assert aborted["terminal_reason"] == {"code": "run_aborted_without_terminal_reason"}

    model_failure = p1_integrity_attestation(
        {"code": "governed_review_contract_exhausted"},
        run_failed=True,
    )
    assert model_failure["status"] == "pass"
    assert model_failure["terminal_class"] == "task_failure"
