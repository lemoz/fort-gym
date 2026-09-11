"""Public diagnostic integrity; native evidence is supplied by the retained audit."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "experiments/evidence/keyboard_input_native_diagnostic_20260911.json"


def read():
    return json.loads(RESULT.read_bytes())


def test_exact_sources_and_result_exclude_private_campaign_data():
    raw = RESULT.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "7f625c56ac900da40986f237da7d8d78d0c24c5f49b5b684da3aa01319fbd72f"
    )
    for private in (b"/Users/", b'"memory":', b'"screen":', b'"account_id":', b'"owner_pid":'):
        assert private not in raw
    value = read()
    for relative, expected in value["diagnostic_sources"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    fixture = ROOT / "experiments/keyboard_input_diagnostic_20260911/fixture.py"
    tree = ast.parse(fixture.read_text())
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"ARMS", "PORTS"}
    }
    assert assignments["ARMS"] == {row["arm"]: row["keys"] for row in value["arms"]}
    assert len(set(assignments["PORTS"].values())) == 4


def test_native_queue_changes_are_not_input_acceptance_or_model_success():
    result = read()
    custom, literal, native, scroll = result["arms"]
    assert custom["keys"] == ["CUSTOM_B"] and literal["keys"] == ["STRING_A098"]
    assert native["keys"] == ["HOTKEY_CARPENTER_BED"]
    assert custom["new_jobs"] == literal["new_jobs"] == []
    assert native["new_jobs"] == [
        {
            "id": 495,
            "type": "ConstructBed",
            "reaction_name": "",
            "suspend": False,
            "repeat_job": False,
        }
    ]
    assert [job["type"] for job in scroll["new_jobs"]] == ["MakeShield"]
    assert custom["before_focus"] == custom["after_focus"]
    assert literal["before_focus"] == literal["after_focus"]
    assert native["after_focus"].endswith("/Workshop/Job")
    assert scroll["after_focus"].endswith("/Workshop/Job")
    assert all(row["existing_jobs"] == custom["existing_jobs"] for row in result["arms"])
    assert (
        result["model_calls"]
        == result["observed_elapsed_ticks"]
        == result["native_saves_requested"]
        == 0
    )
    assert result["autonomous_gameplay"] is result["new_scored_campaign_checkpoint"] is False
    assert result["hardware_energy_and_app_cost_usd"] is None


def test_posthoc_review_does_not_rewrite_the_original_acceptance_failure():
    result = read()
    assert result["original_full_frame_acceptance_passed"] is False
    assert result["original_owner_status"] == "failed"
    assert result["original_container_exit_code"] == 1
    assert result["posthoc_menu_boundary_review_passed"] is True
    assert result["original_failure"] == "full_screen_rows_equal_after_four_completed_arms"
    assert "posthoc" in result["menu_comparison_scope"]["basis"]
    assert [len(row["full_frame_glyph_differences"]) for row in result["arms"]] == [0, 3, 1, 2]
    for row in result["arms"]:
        assert row["menu_sidebar_tiles_equal"] is True
        assert all(point["x"] < 64 for point in row["full_frame_glyph_differences"])
    assert result["prior_attempt"]["status"] == "infrastructure_limited"
    assert result["prior_attempt"]["completed_arms"] == 1
    assert result["prior_attempt"]["evidence_preserved"] is True


def test_original_checkpoint_and_cleanup_are_bound_to_the_audited_save():
    result = read()
    saved = json.loads((ROOT / result["source_result_path"]).read_bytes())
    assert result["checkpoint_sha256"] == saved["checkpoint_sha256"]
    assert result["source_revision"] == saved["execution"]["source_revision"]
    assert result["image_id"] == saved["execution"]["image_id"]
    assert result["source_checkpoint_unchanged"] is True
    assert result["vm_teardown_verified"] is result["native_cleanup_verified"] is True
    assert result["prior_attempt"]["vm_teardown_verified"] is True
    assert all(row["source_calendar"] == [30, 152201] for row in result["arms"])
    assert all(row["observed_elapsed_ticks"] == 0 for row in result["arms"])
