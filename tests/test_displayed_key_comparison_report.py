"""Synthetic public records test reporting; fixtures are not gameplay outcomes."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.eval.displayed_key_comparison import METRICS, read_comparison

ROOT = Path(__file__).resolve().parents[1]
PLAN = "experiments/keyboard_binding_comparison_20260911"
INDEX = "experiments/evidence/synthetic-comparison-index.json"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    plan = json.loads((ROOT / PLAN / "cohort.json").read_text())
    hashes = {}
    for name in {row[key] for row in plan["sequence"] for key in ("condition", "trial")}:
        hashes[name] = write(tmp_path / PLAN / name, json.loads((ROOT / PLAN / name).read_text()))
    digest = write(tmp_path / PLAN / "cohort.json", plan)
    index = {
        "schema_version": "fortgym.public-displayed-key-index/v1",
        "cohort": {
            "path": PLAN + "/cohort.json",
            "sha256": digest,
            "revision": "1" * 40,
        },
        "config_sha256": hashes,
        "results": {},
    }
    write(tmp_path / INDEX, index)
    return tmp_path, plan, index


def result(fixture, slot=0, status="saved", count=64):
    _, plan, index = fixture
    row = plan["sequence"][slot]
    return {
        "schema_version": "fortgym.public-displayed-key-result/v1",
        "cohort_id": plan["cohort_id"],
        "campaign_id": row["id"],
        "model": plan["models"][row["model"]],
        "replicate": row["replicate"],
        "reasoning_effort": "medium",
        "source_revision": plan["native_source_revision"],
        "image_id": plan["native_image"],
        "seed_receipt_sha256": plan["seed_receipt_sha256"],
        "condition_file_sha256": index["config_sha256"][row["condition"]],
        "trial_file_sha256": index["config_sha256"][row["trial"]],
        "response_limit": 64,
        "human_gameplay_rescue": False,
        "status": status,
        "responses": count,
        "returned_tokens": 12345,
        "reported_charge_usd": None,
        "native_teardown_verified": True,
        "vm_teardown_verified": True,
        "terminal_audit_sha256": "a" * 64,
        "checkpoint": {
            "next_step": count,
            "sha256": "b" * 64,
            "saved_elapsed_ticks": 2000,
            "metrics": {key: 7 if key == "population" else None for key in METRICS},
        },
    }


def add(fixture, value):
    root, _, index = fixture
    path = "experiments/evidence/synthetic-" + value["campaign_id"] + ".json"
    digest = write(root / path, value)
    index["results"][value["campaign_id"]] = {
        "64": {"path": path, "sha256": digest, "revision": "2" * 40}
    }
    write(root / INDEX, index)


def report(fixture):
    return read_comparison(fixture[0], INDEX, boundary=64)


def test_all_declared_slots_remain_without_published_results(fixture):
    data = report(fixture)
    assert data["declared_attempts"] == 6 and data["recorded_attempts"] == 0
    assert [row["campaign_id"] for row in data["trials"]] == [
        row["id"] for row in fixture[1]["sequence"]
    ]
    assert all(row["result"] is None for row in data["trials"])
    assert all(row["publication_state"] == "no_published_result" for row in data["trials"])
    assert data["all_attempts_reported"] is data["all_saved_boundaries_reached"] is False
    assert data["strong_ranking_supported"] is data["live_status_included"] is False


def test_partial_saved_result_does_not_hide_the_five_other_attempts(fixture):
    add(fixture, result(fixture))
    data = report(fixture)
    assert data["recorded_attempts"] == 1 and len(data["trials"]) == 6
    saved = data["trials"][0]["result"]
    assert saved["checkpoint"]["metrics"]["population"] == 7
    assert saved["checkpoint"]["metrics"]["food_stock"] is None
    assert saved["reported_charge_usd"] is None
    assert data["trials"][0]["evidence_url"].startswith(
        "https://github.com/lemoz/fort-gym/blob/" + "2" * 40
    )


def test_failed_paused_and_unknown_usage_remain_in_the_denominator(fixture):
    for slot, status in enumerate(
        ("saved", "budget_limited_pause", "infrastructure_failure", "gameplay_collapse")
    ):
        value = result(fixture, slot, status, 64 if status == "saved" else 12)
        if status == "infrastructure_failure":
            value.update(responses=None, returned_tokens=None, checkpoint=None)
        add(fixture, value)
    data = report(fixture)
    assert data["recorded_attempts"] == 4 and data["declared_attempts"] == 6
    assert data["outcome_counts"] == {
        name: 1
        for name in (
            "saved",
            "budget_limited_pause",
            "infrastructure_failure",
            "gameplay_collapse",
        )
    }
    assert data["trials"][2]["result"]["responses"] is None
    assert data["trials"][2]["result"]["checkpoint"] is None
    assert data["trials"][1]["result"]["checkpoint"]["next_step"] == 12
    assert not data["all_saved_boundaries_reached"]


def test_reporting_all_outcomes_is_not_the_same_as_every_model_reaching_the_boundary(
    fixture,
):
    for slot in range(6):
        add(
            fixture,
            result(
                fixture,
                slot,
                "budget_limited_pause" if slot == 4 else "saved",
                5 if slot == 4 else 64,
            ),
        )
    data = report(fixture)
    assert data["all_attempts_reported"] is True
    assert data["all_saved_boundaries_reached"] is data["strong_ranking_supported"] is False


def test_all_six_equal_boundaries_still_do_not_create_a_strong_ranking(fixture):
    for slot in range(6):
        add(fixture, result(fixture, slot))
    data = report(fixture)
    assert data["all_saved_boundaries_reached"] is True
    assert data["strong_ranking_supported"] is False
    assert data["production_rates"] is data["consumption_rates"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "different"),
        ("replicate", True),
        ("response_limit", 128),
        ("source_revision", "3" * 40),
        ("image_id", "sha256:" + "3" * 64),
        ("condition_file_sha256", "3" * 64),
        ("trial_file_sha256", "3" * 64),
        ("seed_receipt_sha256", "3" * 64),
        ("human_gameplay_rescue", True),
        ("reasoning_effort", "high"),
    ],
)
def test_declared_matching_fields_are_not_silently_relaxed(fixture, field, value):
    data = result(fixture)
    data[field] = value
    add(fixture, data)
    with pytest.raises(ValueError, match="declared comparison"):
        report(fixture)


@pytest.mark.parametrize(
    "change",
    [
        "short",
        "unsaved",
        "teardown",
        "bool_tokens",
        "unknown_tokens",
        "negative_cost",
        "bad_metric",
    ],
)
def test_saved_result_requires_proportionate_proof(fixture, change):
    data = result(fixture)
    if change == "short":
        data["responses"] = data["checkpoint"]["next_step"] = 32
    elif change == "unsaved":
        data["checkpoint"] = None
    elif change == "teardown":
        data["vm_teardown_verified"] = False
    elif change == "bool_tokens":
        data["returned_tokens"] = True
    elif change == "unknown_tokens":
        data["returned_tokens"] = None
    elif change == "negative_cost":
        data["reported_charge_usd"] = -1
    else:
        data["checkpoint"]["metrics"]["food_stock"] = False
    add(fixture, data)
    with pytest.raises(ValueError):
        report(fixture)


def test_a_changed_public_file_is_not_trusted_because_its_schema_still_matches(fixture):
    add(fixture, result(fixture))
    reference = next(iter(fixture[2]["results"].values()))["64"]
    data = result(fixture)
    data["returned_tokens"] += 1
    write(fixture[0] / reference["path"], data)
    with pytest.raises(ValueError, match="bytes differ"):
        report(fixture)


def test_extra_private_fields_are_not_projected_into_the_website_report(fixture):
    data = result(fixture)
    data["private_memory"] = "DO_NOT_EXPORT"
    data["checkpoint"]["metrics"]["private_account"] = "DO_NOT_EXPORT"
    add(fixture, data)
    assert "DO_NOT_EXPORT" not in json.dumps(report(fixture))


def test_all_other_controls_must_match_even_when_each_config_hash_is_valid(fixture):
    root, _, index = fixture
    path = root / PLAN / "terra-condition.json"
    data = json.loads(path.read_text())
    data["model_timeout_seconds"] += 1
    index["config_sha256"][path.name] = write(path, data)
    write(root / INDEX, index)
    with pytest.raises(ValueError, match="more than their declared selection"):
        report(fixture)


@pytest.mark.parametrize("mutation", ["duplicate", "bool_replicate", "missing_replicate"])
def test_cohort_denominator_cannot_shrink_or_duplicate(fixture, mutation):
    root, plan, index = fixture
    if mutation == "duplicate":
        plan["sequence"].append(deepcopy(plan["sequence"][0]))
    elif mutation == "bool_replicate":
        plan["sequence"][0]["replicate"] = True
    else:
        plan["sequence"].pop()
    index["cohort"]["sha256"] = write(root / PLAN / "cohort.json", plan)
    write(root / INDEX, index)
    with pytest.raises(ValueError):
        report(fixture)


def test_longer_boundary_is_not_substituted_for_a_missing_shorter_result(fixture):
    add(fixture, result(fixture))
    data = read_comparison(fixture[0], INDEX, boundary=128)
    assert data["recorded_attempts"] == 0
    with pytest.raises(ValueError, match="Boundary"):
        read_comparison(fixture[0], INDEX, boundary=32)


@pytest.mark.parametrize("mutation", ["traversal", "symlink", "oversized", "missing"])
def test_only_bounded_regular_reviewed_files_are_read(fixture, mutation):
    root, _, index = fixture
    add(fixture, result(fixture))
    reference = next(iter(index["results"].values()))["64"]
    path = root / reference["path"]
    if mutation == "traversal":
        reference["path"] = "experiments/../../outside.json"
        write(root / INDEX, index)
    elif mutation == "symlink":
        target = path.with_suffix(".copy")
        path.rename(target)
        path.symlink_to(target)
    elif mutation == "oversized":
        path.write_bytes(b" " * (1024 * 1024 + 1))
    else:
        path.unlink()
    with pytest.raises(ValueError):
        report(fixture)


def test_cli_only_prints_the_synthetic_report(fixture):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.campaign_displayed_key_comparison",
            "--project-root",
            str(fixture[0]),
            "--index",
            INDEX,
            "--boundary",
            "64",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert json.loads(completed.stdout) == report(fixture)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_ambiguous_or_nonfinite_json_is_rejected(fixture, raw):
    (fixture[0] / INDEX).write_text(raw)
    with pytest.raises(ValueError):
        report(fixture)


def test_actual_declared_cohort_index_has_no_fabricated_results():
    data = read_comparison(
        ROOT,
        "experiments/evidence/keyboard_binding_comparison_20260911_index.json",
        boundary=64,
    )
    assert data["declared_attempts"] == 6
    assert data["plan_sha256"] == "da38987cb71b1bafde853d10e476e0c9539a950c9d90580ff1c2b1ba7cb839b0"
    assert all(
        row["model"] in {"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra"} for row in data["trials"]
    )
    assert data["strong_ranking_supported"] is False


def test_actual_saved_sol_outcome_is_preserved_without_a_success_claim():
    data = read_comparison(
        ROOT,
        "experiments/evidence/keyboard_binding_comparison_20260911_index.json",
        boundary=64,
    )
    row = data["trials"][0]
    assert row["campaign_id"] == "bindings-comparison-20260911-sol-r1"
    assert (
        row["evidence_sha256"] == "5d0cb5ea363ef5ac4bf24d8336ea1479bbd84a1966a90f68a646d0635923af66"
    )
    assert row["result"]["status"] == "saved" and row["result"]["responses"] == 64
    assert row["result"]["checkpoint"]["saved_elapsed_ticks"] == 2900
    assert row["result"]["checkpoint"]["metrics"]["population"] == 7
    assert row["result"]["checkpoint"]["metrics"]["completed_workshops"] == 0
    assert row["result"]["returned_tokens"] == 1258321
    assert row["result"]["reported_charge_usd"] is None
    assert data["strong_ranking_supported"] is False


def test_actual_saved_terra_outcome_preserves_unknowns_and_native_progress():
    data = read_comparison(
        ROOT,
        "experiments/evidence/keyboard_binding_comparison_20260911_index.json",
        boundary=64,
    )
    row = next(
        item
        for item in data["trials"]
        if item["campaign_id"] == "bindings-comparison-20260911-terra-r1"
    )
    assert row["evidence_sha256"] == (
        "b4ea68600315b7788c38e53848a47ba27513fa3bcca418b878f31a51f564b7bf"
    )
    result = row["result"]
    assert result["status"] == "saved" and result["responses"] == 64
    assert result["returned_tokens"] == 1589877
    assert result["reported_charge_usd"] is None
    assert result["native_teardown_verified"] is result["vm_teardown_verified"] is True
    checkpoint = result["checkpoint"]
    assert checkpoint["saved_elapsed_ticks"] == 4200
    assert checkpoint["sha256"] == (
        "8338569453b6c517ff5e314d2f76a76de02b7735887edbbc27800a6599b12292"
    )
    assert checkpoint["metrics"]["population"] == 7
    assert checkpoint["metrics"]["completed_workshops"] == 0
    assert checkpoint["metrics"]["food_stock"] == 51
    assert checkpoint["metrics"]["wood_stock"] is None
    assert data["strong_ranking_supported"] is False
