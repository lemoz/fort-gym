"""Offline planner checks use real save/audit machinery and fake gameplay."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run import keyboard_endurance_window as planning
from fort_gym.bench.run.keyboard_docker_audit import audit
from fort_gym.bench.run.keyboard_docker_plan import prepare_inputs
from fort_gym.bench.run.keyboard_endurance_window import prepare_window
from fort_gym.bench.run.keyboard_trial_config import load_trial
from scripts import prepare_keyboard_endurance_window as cli
from tests.test_keyboard_docker_audit import run_fixture, seed, write
from tests.test_keyboard_docker_owner import RUNTIME

TARGET = {"max_dispatches": 8, "max_total_tokens": 800}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh(tmp_path):
    origin = seed(tmp_path / "seed")
    attempt, checkpoint = run_fixture(
        tmp_path / "fresh", origin, "fresh", dispatch_limit=2, token_limit=200
    )
    return attempt, origin, checkpoint


def test_declared_astra_endurance_preserves_standard_input_condition():
    folder = ROOT / "experiments/astra_keyboard_endurance_v1"
    condition, trial = load_trial(folder / "condition.json", folder / "trial.json")
    baseline = read(ROOT / "experiments/selected_workshop_study_v1/keyboard-condition.json")
    baseline.update(
        condition_id="astra-standard-input-endurance-v1", max_dispatches=4, max_total_tokens=500000
    )
    assert condition == baseline and trial["steps_per_segment"] == 4
    protocol = read(folder / "protocol.json")
    assert protocol["initial_budget"] == {k: condition[k] for k in TARGET}
    assert protocol["target_budget"]["max_dispatches"] == 4 + 16 * protocol["responses_per_window"]
    assert protocol["first_anniversary_elapsed_ticks"] == 403200
    assert protocol["one_campaign_not_independent_window_trials"] is True
    assert protocol["native_acceptance_performed"] is False


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra"])
def test_generated_windows_extend_once_and_continue_each_configured_model(tmp_path, model):
    origin = seed(tmp_path / "seed")
    options = dict(model=model, dispatch_limit=2, token_limit=200)
    attempt, checkpoint = run_fixture(tmp_path / "fresh", origin, "fresh", **options)
    original = {p: p.read_bytes() for p in checkpoint.rglob("*") if p.is_file()}
    chain = [(attempt, origin)]
    for index, end in enumerate((4, 6, 8)):
        declaration, condition, parent = prepare_window(
            attempt,
            origin,
            RUNTIME,
            target_budget=TARGET,
            steps=2,
        )
        assert parent == checkpoint and read(condition)["model"] == model
        assert declaration["window_end_decision"] == end
        assert ("budget_extension" in declaration) == (index == 0)
        declaration_path = tmp_path / f"window-{index}.json"
        write(declaration_path, declaration)
        assert (
            prepare_inputs(
                condition, declaration_path, parent, "portable-audit-fixture", mode="continue"
            )["limit"]
            == 2
        )
        origin = parent
        attempt, checkpoint = run_fixture(
            tmp_path / f"continued-{index}",
            origin,
            "continue",
            declaration_override=declaration,
            **options,
        )
        chain.append((attempt, origin))
    report = audit(chain)
    assert report["passed"] and report["model_responses"] == 8
    assert report["cumulative_returned_tokens"] == 800
    assert len(read(checkpoint / "agent.json")["budget_extensions"]) == 1
    assert {p: p.read_bytes() for p in original} == original
    with pytest.raises(ValueError, match="dispatch budget exhausted"):
        prepare_window(attempt, origin, RUNTIME, target_budget=TARGET)


def test_last_window_stops_at_remaining_dispatches(fresh):
    attempt, origin, checkpoint = fresh
    declaration, _, parent = prepare_window(
        attempt,
        origin,
        RUNTIME,
        target_budget={"max_dispatches": 5, "max_total_tokens": 800},
    )
    assert parent == checkpoint
    assert declaration["steps_per_segment"] == 3
    assert declaration["window_end_decision"] == 5


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_revision", "c" * 40),
        ("image", "sha256:" + "c" * 64),
        ("cpus", 3),
        ("memory_mib", 8192),
    ],
)
def test_source_image_and_resource_migrations_are_not_enabled(fresh, key, value):
    attempt, origin, _ = fresh
    with pytest.raises(ValueError, match="preserve the prior"):
        prepare_window(attempt, origin, {**RUNTIME, key: value}, target_budget=TARGET)


@pytest.mark.parametrize(
    "target",
    [
        {"max_dispatches": True, "max_total_tokens": 800},
        {"max_dispatches": 8, "max_total_tokens": 199},
        {"max_dispatches": 8, "max_total_tokens": 200},
        {"max_dispatches": 2, "max_total_tokens": 800},
        {"max_dispatches": 1, "max_total_tokens": 800},
    ],
)
def test_invalid_reduced_or_exhausted_budgets_do_not_make_a_window(fresh, target):
    attempt, origin, _ = fresh
    with pytest.raises(ValueError):
        prepare_window(attempt, origin, RUNTIME, target_budget=target)


@pytest.mark.parametrize("steps", [True, 0, 65])
def test_each_native_window_remains_bounded(fresh, steps):
    attempt, origin, _ = fresh
    with pytest.raises(ValueError):
        prepare_window(attempt, origin, RUNTIME, target_budget=TARGET, steps=steps)


def test_incomplete_owner_cannot_generate_continuation(fresh):
    attempt, origin, _ = fresh
    file = attempt / "owner-result.json"
    owner = read(file)
    write(file, {**owner, "container_stopped_verified": False})
    with pytest.raises(ValueError, match="no settled saved window"):
        prepare_window(attempt, origin, RUNTIME, target_budget=TARGET)


def test_retained_condition_changed_after_audit_is_rejected(fresh, monkeypatch):
    attempt, origin, _ = fresh
    genuine_audit = planning.audit

    def changed_after_audit(windows):
        report = genuine_audit(windows)
        condition, _ = planning.input_paths(attempt)
        write(condition, {**read(condition), "condition_id": "changed-after-audit"})
        return report

    monkeypatch.setattr(planning, "audit", changed_after_audit)
    with pytest.raises(ValueError):
        prepare_window(attempt, origin, RUNTIME, target_budget=TARGET)


def test_cli_creates_only_new_declaration_outside_original_evidence(fresh, tmp_path, monkeypatch):
    attempt, origin, _ = fresh
    runtime, output = tmp_path / "runtime.json", tmp_path / "next-window.json"
    write(runtime, deepcopy(RUNTIME))
    args = [
        "prepare",
        "--previous-attempt",
        str(attempt),
        "--previous-origin",
        str(origin),
        "--runtime",
        str(runtime),
        "--max-dispatches",
        "8",
        "--max-total-tokens",
        "800",
        "--steps",
        "2",
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    before = output.read_bytes()
    assert json.loads(before)["window_end_decision"] == 4
    with pytest.raises(FileExistsError):
        cli.main()
    assert output.read_bytes() == before
    monkeypatch.setattr(sys, "argv", [*args[:-1], str(attempt / "new-window.json")])
    with pytest.raises(ValueError, match="separate from retained inputs"):
        cli.main()
    assert not (attempt / "new-window.json").exists()
