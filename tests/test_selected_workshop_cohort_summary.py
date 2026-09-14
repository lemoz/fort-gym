import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.summarize_selected_workshop_cohort import summarize

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"
STUDY = EVIDENCE / "selected_workshop_runtime_v2_declaration_20260912.json"
KEYBOARD = EVIDENCE / "selected_workshop_v2_p1_keyboard_128_20260912.json"
SHORTCUTS = EVIDENCE / "selected_workshop_v2_p1_shortcuts_128_20260912.json"


def changed(tmp_path, source, key, value):
    data = json.loads(source.read_bytes())
    data[key] = value
    target = tmp_path / source.name
    target.write_text(json.dumps(data))
    return target


def test_actual_first_pair_is_descriptive_and_incomplete():
    data = summarize(STUDY, [KEYBOARD, SHORTCUTS])
    assert data["supplied_attempts"] == 2 and data["declared_attempts"] == 6
    assert len(data["missing_results"]) == 4
    assert data["all_declared_terminal_manifests_supplied"] is False
    assert [pair["both_terminal_manifests_supplied"] for pair in data["pairs"]] == [
        True,
        False,
        False,
    ]
    delta = data["pairs"][0]["keyboard_minus_shortcuts"]
    assert delta["completed_beds"] == 0 and delta["saved_elapsed_ticks"] == 2700
    assert delta["food_stock"] == 4 and delta["drink_stock"] == 20
    assert delta["returned_tokens"] == 107304 and delta["wood_stock"] is None
    assert data["returned_tokens_in_supplied_results"] == 7652294
    assert data["reported_charge_usd_for_supplied_results"] is None
    assert data["known_reported_charge_subtotal_usd"] is None
    assert data["results_with_unreported_charge"] == 2
    for key in (
        "native_audit_performed",
        "ranking_performed",
        "sustainability_assessed",
        "goal_completion_assessed",
    ):
        assert data[key] is False
    assert (
        data["pairs"][0]["results"]["keyboard"]["result_sha256"]
        == hashlib.sha256(KEYBOARD.read_bytes()).hexdigest()
    )


def test_missing_outcomes_are_not_fabricated_failures_or_zero_cost():
    data = summarize(STUDY, [])
    assert len(data["missing_results"]) == 6 and data["supplied_attempts"] == 0
    assert data["reported_charge_usd_for_supplied_results"] is None
    assert data["known_reported_charge_subtotal_usd"] is None
    assert all(pair["keyboard_minus_shortcuts"] is None for pair in data["pairs"])
    assert "outcome unknown" in data["missing_result_meaning"]


def test_one_sided_pair_has_no_delta_and_argument_order_is_irrelevant():
    partial = summarize(STUDY, [KEYBOARD])
    assert partial["pairs"][0]["results"]["shortcuts"] is None
    assert partial["pairs"][0]["keyboard_minus_shortcuts"] is None
    assert summarize(STUDY, [KEYBOARD, SHORTCUTS]) == summarize(STUDY, [SHORTCUTS, KEYBOARD])


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", "live-progress"),
        ("study_id", "selected-workshop-v1"),
        ("source_revision", "other"),
        ("image", "other"),
        ("model", "other"),
        ("reasoning_effort", "high"),
        ("study_declaration_sha256", "0" * 64),
        ("condition_sha256", "0" * 64),
        ("pair", True),
        ("campaign_id", "undeclared"),
        ("condition", "shortcuts"),
        ("status", "running"),
        ("model_responses", 64),
        ("comparison_boundary", True),
        ("returned_tokens", 8000001),
        ("returned_tokens", True),
        ("saved_elapsed_ticks", -1),
        ("saved_metrics", {"population": True}),
        ("reported_charge_usd", True),
        ("reported_charge_usd", -1),
        ("checkpoint_verified", "true"),
        ("parent_64_checkpoint_fresh_reload_verified", False),
        ("teardown_verified", False),
        ("audit_sha256", None),
        ("checkpoint_file_sha256", "invalid"),
        ("final_checkpoint_fresh_reload_verified", "false"),
        ("action_counts", {}),
        ("action_counts", None),
        ("action_counts", {"clock": None}),
    ],
)
def test_incompatible_or_unfinished_manifest_is_an_error_not_silently_dropped(tmp_path, key, value):
    path = changed(tmp_path, KEYBOARD, key, value)
    with pytest.raises(ValueError):
        summarize(STUDY, [path, SHORTCUTS])


def test_duplicate_attempts_rejected():
    with pytest.raises(ValueError, match="Duplicate supplied"):
        summarize(STUDY, [KEYBOARD, KEYBOARD])


@pytest.mark.parametrize("charge", [0, 1.25])
def test_known_cost_subtotal_is_not_mistaken_for_unknown_total(tmp_path, charge):
    path = changed(tmp_path, KEYBOARD, "reported_charge_usd", charge)
    data = summarize(STUDY, [path, SHORTCUTS])
    assert data["known_reported_charge_subtotal_usd"] == charge
    assert data["reported_charge_usd_for_supplied_results"] is None
    assert data["results_with_unreported_charge"] == 1


def test_two_explicit_zero_charges_are_a_known_zero(tmp_path):
    paths = [
        changed(tmp_path, source, "reported_charge_usd", 0) for source in (KEYBOARD, SHORTCUTS)
    ]
    assert summarize(STUDY, paths)["reported_charge_usd_for_supplied_results"] == 0


def test_nonfinite_json_rejected(tmp_path):
    path = changed(tmp_path, KEYBOARD, "reported_charge_usd", float("nan"))
    with pytest.raises(ValueError, match="Non-finite"):
        summarize(STUDY, [path])


def test_declared_pair_cannot_omit_a_condition(tmp_path):
    path = changed(tmp_path, STUDY, "order", ["selected-workshop-v2-p1-keyboard"])
    with pytest.raises(ValueError, match="both conditions"):
        summarize(path, [])


def test_duplicate_declared_attempts_are_rejected(tmp_path):
    order = json.loads(STUDY.read_bytes())["order"]
    path = changed(tmp_path, STUDY, "order", [*order, order[0]])
    with pytest.raises(ValueError, match="Duplicate declared"):
        summarize(path, [])


def test_all_fixture_endpoints_cover_the_declaration_but_do_not_prove_goal(tmp_path):
    paths = []
    for pair in (1, 2, 3):
        for condition, source in (("keyboard", KEYBOARD), ("shortcuts", SHORTCUTS)):
            data = json.loads(source.read_bytes())
            data.update(pair=pair, campaign_id=f"selected-workshop-v2-p{pair}-{condition}")
            target = tmp_path / f"fixture-{pair}-{condition}.json"
            target.write_text(json.dumps(data))
            paths.append(target)
    report = summarize(STUDY, paths)
    assert report["all_declared_terminal_manifests_supplied"] is True
    assert report["missing_results"] == []
    assert report["goal_completion_assessed"] is False
    assert report["ranking_performed"] is False
    assert report["native_audit_performed"] is False
    assert report == summarize(STUDY, list(reversed(paths)))


def test_cli_is_read_only_and_returns_the_same_summary():
    inputs = (STUDY, KEYBOARD, SHORTCUTS)
    before = {path: path.read_bytes() for path in inputs}
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/summarize_selected_workshop_cohort.py"),
            "--study",
            str(STUDY),
            "--result",
            str(KEYBOARD),
            "--result",
            str(SHORTCUTS),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == summarize(STUDY, [KEYBOARD, SHORTCUTS])
    assert {path: path.read_bytes() for path in inputs} == before
