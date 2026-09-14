"""Configuration tests use synthetic outcomes, not new gameplay evidence."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fort_gym.bench.run import displayed_key_window as windows

ROOT = Path(__file__).resolve().parents[1]
PLAN = "experiments/keyboard_binding_comparison_20260911"
INDEX = "experiments/evidence/keyboard_binding_comparison_20260911_index.json"
SOL = "bindings-comparison-20260911-sol-r1"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    shutil.copytree(ROOT / PLAN, tmp_path / PLAN)
    index = json.loads((ROOT / INDEX).read_text())
    template = json.loads((ROOT / index["results"][SOL]["64"]["path"]).read_text())
    index["results"] = {}
    plan = json.loads((ROOT / PLAN / "cohort.json").read_text())
    for slot in plan["sequence"]:
        value = json.loads(json.dumps(template))
        value.update(
            campaign_id=slot["id"],
            model=plan["models"][slot["model"]],
            replicate=slot["replicate"],
            returned_tokens=12345,
            condition_file_sha256=index["config_sha256"][slot["condition"]],
            trial_file_sha256=index["config_sha256"][slot["trial"]],
        )
        value.pop("assessment", None)
        value.pop("evidence_details", None)
        value["checkpoint"]["sha256"] = hashlib.sha256(slot["id"].encode()).hexdigest()
        path = "experiments/evidence/synthetic-" + slot["id"] + ".json"
        digest = write(tmp_path / path, value)
        index["results"][slot["id"]] = {
            "64": {"path": path, "sha256": digest, "revision": "2" * 40}
        }
    write(tmp_path / INDEX, index)
    return tmp_path, index


def change_result(bundle, mutate):
    root, index = bundle
    reference = index["results"][SOL]["64"]
    value = json.loads((root / reference["path"]).read_text())
    mutate(value)
    reference["sha256"] = write(root / reference["path"], value)
    write(root / INDEX, index)


@pytest.mark.parametrize(
    "name,repeat", [("sol", 1), ("terra", 1), ("astra", 1), ("terra", 2), ("sol", 2), ("astra", 2)]
)
def test_six_slots_prepare_only_their_own_unmodified_continuation(bundle, name, repeat):
    root, index = bundle
    identity = f"bindings-comparison-20260911-{name}-r{repeat}"
    value = windows.prepare_window(root, INDEX, identity)
    source = json.loads((root / index["results"][identity]["64"]["path"]).read_text())
    assert value["expected_campaign_id"] == identity
    assert value["continuation_checkpoint_sha256"] == source["checkpoint"]["sha256"]
    assert value["source_result_sha256"] == index["results"][identity]["64"]["sha256"]
    assert value["continuation_from_next_step"] == value["steps_per_segment"] == 64
    assert value["window_end_decision"] == 128 and value["max_segments"] == 1
    assert value["returned_tokens_before_window"] == 12345
    assert value["accounted_responses_before_window"] == 64
    assert value["saved_elapsed_ticks_before_window"] == source["checkpoint"]["saved_elapsed_ticks"]
    trial = json.loads((root / PLAN / (name + "-trial.json")).read_text())
    for key in windows.PRESERVED_PROFILES:
        assert value[key] == trial[key]
    assert value["reset_memory"] is value["reset_usage"] is value["strategy_intervention"] is False
    assert not {"restart", "prompt_change", "budget_extension", "memory_update"}.intersection(value)


@pytest.mark.parametrize(
    "status", ["budget_limited_pause", "infrastructure_failure", "gameplay_collapse"]
)
def test_partial_or_failed_result_is_not_promoted_to_a_saved_continuation(bundle, status):
    change_result(bundle, lambda value: value.update(status=status))
    with pytest.raises(ValueError, match="reviewed saved"):
        windows.prepare_window(bundle[0], INDEX, SOL)


@pytest.mark.parametrize(
    "identity", [None, "../private", "astra", "bindings-comparison-20260911-sol-r3"]
)
def test_unknown_campaign_does_not_become_a_path(bundle, identity):
    with pytest.raises(ValueError, match="predeclared"):
        windows.prepare_window(bundle[0], INDEX, identity)


def test_missing_result_does_not_become_a_new_seed_start(bundle):
    root, index = bundle
    del index["results"][SOL]
    write(root / INDEX, index)
    with pytest.raises(ValueError, match="reviewed saved"):
        windows.prepare_window(root, INDEX, SOL)


@pytest.mark.parametrize("tokens", [0, None, -1, True, 40000000, 40000001])
def test_invalid_or_exhausted_usage_cannot_gain_an_extension(bundle, tokens):
    change_result(bundle, lambda value: value.update(returned_tokens=tokens))
    with pytest.raises(ValueError):
        windows.prepare_window(bundle[0], INDEX, SOL)


def test_moving_index_cannot_mix_two_generations(bundle, monkeypatch):
    root, _ = bundle
    original = windows.read_comparison
    count = 0

    def reading(*args, **kwargs):
        nonlocal count
        count += 1
        result = original(*args, **kwargs)
        if count == 2:
            result["recorded_attempts"] -= 1
        return result

    monkeypatch.setattr(windows, "read_comparison", reading)
    with pytest.raises(ValueError, match="sources changed"):
        windows.prepare_window(root, INDEX, SOL)


def test_even_consistently_rebound_configuration_cannot_change_the_frozen_trial(bundle):
    root, index = bundle
    for name in ("sol", "terra", "astra"):
        file = name + "-condition.json"
        condition = json.loads((root / PLAN / file).read_text())
        condition["max_advance_ticks"] = 1000
        index["config_sha256"][file] = write(root / PLAN / file, condition)
    for identity, results in index["results"].items():
        reference = results["64"]
        value = json.loads((root / reference["path"]).read_text())
        name = identity.split("-")[-2]
        value["condition_file_sha256"] = index["config_sha256"][name + "-condition.json"]
        reference["sha256"] = write(root / reference["path"], value)
    write(root / INDEX, index)
    with pytest.raises(ValueError, match="frozen declaration"):
        windows.prepare_window(root, INDEX, SOL)


def test_actual_sol_checkpoint_preparation_has_no_vm_or_model_side_effect():
    value = windows.prepare_window(ROOT, INDEX, SOL)
    assert (
        value["continuation_checkpoint_sha256"]
        == "985f00da901dfd8edd684e4bb242cec022a9f8937d3f5f733ff7567684ebdb0e"
    )
    assert value["returned_tokens_before_window"] == 1258321
    assert value["saved_elapsed_ticks_before_window"] == 2900
    output = subprocess.check_output(
        [sys.executable, "-m", "scripts.campaign_displayed_key_window", "--campaign-id", SOL],
        cwd=ROOT,
        text=True,
    )
    assert json.loads(output) == value
    declared = (
        ROOT
        / "experiments/keyboard_binding_comparison_continuations_20260911/sol-r1-window-64-128.json"
    )
    assert declared.read_text() == output
    assert hashlib.sha256(declared.read_bytes()).hexdigest() == (
        "2ee16e7609bd55134aa6c229e2c42ed4c1ec817d08405a0a29b819ee0a4c4263"
    )


@pytest.mark.parametrize("slot", ["sol-r1", "terra-r1", "astra-r1", "terra-r2", "sol-r2", "astra-r2"])
def test_each_prepared_window_is_exactly_derived_from_its_own_recorded_result(slot):
    identity = "bindings-comparison-20260911-" + slot
    path = ROOT / "experiments/keyboard_binding_comparison_continuations_20260911"
    path /= slot + "-window-64-128.json"
    expected = windows.prepare_window(ROOT, INDEX, identity)
    assert json.loads(path.read_text()) == expected
    assert expected["accounted_responses_before_window"] == 64
    assert expected["window_end_decision"] == 128
    assert expected["reset_memory"] is expected["reset_usage"] is False
    assert expected["strategy_intervention"] is False
