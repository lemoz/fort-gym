"""Public declaration constraints; these checks are not native gameplay proof."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "experiments/keyboard_binding_continuation_20260911"


def test_own_checkpoint_and_exact_window():
    window = json.loads((PLAN / "window-32-64.json").read_text())
    prior = json.loads(
        (ROOT / "experiments/evidence/keyboard_binding_astra_r1_20260911.json").read_text()
    )
    assert window["continuation_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert window["continuation_from_next_step"] == prior["responses"] == 32
    assert window["steps_per_segment"] == 32 and window["max_segments"] == 1
    assert window["original_condition"] == "astra-condition.json"


def test_no_reset_restart_strategy_or_budget_extension():
    window = json.loads((PLAN / "window-32-64.json").read_text())
    assert all(
        window[name] is False for name in ("reset_memory", "reset_usage", "strategy_intervention")
    )
    assert all(name not in window for name in ("restart", "prompt_change", "budget_extension"))


def test_measurement_and_snapshot_conditions_preserved():
    window = json.loads((PLAN / "window-32-64.json").read_text())
    assert window["snapshot_profile"] == "native_menu_preserving_save/v4"
    assert window["runtime_rpc_transport"] == "native-rpc"
    assert window["private_measurement_profile"] == "fortgym.campaign-food-measurement/v1"
    assert window["private_measurement_timeout_seconds"] == 15
    assert window["resource_observation_profile"] == "fortgym.native-resource-observations/v1"


@pytest.mark.parametrize("digest", ["", "unverified"])
def test_export_requires_explicit_exact_audit_hash(digest):
    spec = importlib.util.spec_from_file_location("binding_continuation_export", PLAN / "export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError):
        module.build(digest)
