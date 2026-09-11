"""Synthetic multi-save website fixtures; no new native experiment results."""

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from fort_gym.bench.api import keyboard_binding_campaign as campaign
from fort_gym.bench.api.keyboard_binding_stock_context import stock_context
from fort_gym.bench.api.keyboard_binding_checkpoints import (
    mark_source_reload,
    validate_window_checkpoints,
    window_checkpoints,
)

URL = "https://github.com/lemoz/fort-gym/blob/" + "f" * 40 + "/synthetic-not-published.json"


def fixture(counts=None):
    counts = counts if counts is not None else [32] * 5
    prior = campaign.read_result(campaign.LATEST_RESULT_PATH, campaign.LATEST_RESULT_SHA256)
    result = copy.deepcopy(prior)
    result.update(
        first_step=96,
        responses=96 + sum(counts),
        new_responses=sum(counts),
        new_tokens=sum(counts) * 10,
        new_saved_elapsed_ticks=sum(counts) * 2000,
        saved_elapsed_ticks=59500 + sum(counts) * 2000,
        source_checkpoint_sha256=prior["checkpoint_sha256"],
        timeline=[],
        checkpoint_segments=[],
        new_confirmed_key_presses=sum(counts),
        status="completed" if len(counts) == 5 and counts[-1] == 32 else "paused",
    )
    result["stop_reason"] = (
        "segment_limit" if result["status"] == "completed" else "budget_limited_pause"
    )
    result["initial_metrics"] = copy.deepcopy(prior["saved_metrics"])
    result["window"] = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "condition_id": result["condition"]["condition_id"],
        "expected_campaign_id": result["campaign_id"],
        "source_native_revision": result["source_revision"],
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        "accounted_responses_before_window": 96,
        "returned_tokens_before_window": prior["usage"]["total_tokens"],
        "saved_elapsed_ticks_before_window": 59500,
        "max_segments": 5,
        "steps_per_segment": 32,
        "continuation_from_next_step": 96,
        "continuation_checkpoint_sha256": prior["checkpoint_sha256"],
        "window_end_decision": 256,
    }
    result["audit"].update(
        saved_checkpoints_verified=len(counts),
        source_checkpoint_fresh_load_verified=True,
        provider_receipts_verified=sum(counts),
    )
    cursor, ticks, tokens = 96, 59500, prior["usage"]["total_tokens"]
    parent, metrics = prior["checkpoint_sha256"], prior["saved_metrics"]
    for index, count in enumerate(counts):
        first, initial = cursor, copy.deepcopy(metrics)
        after = {**metrics, "completed_beds": metrics["completed_beds"] + 1} if count else metrics
        for _ in range(count):
            cursor += 1
            ticks += 2000
            tokens += 10
            row = copy.deepcopy(prior["timeline"][-1])
            row.update(
                decision=cursor,
                model_intent="Synthetic fixture, not gameplay",
                keys=["SYM:0:Escape"],
                confirmed_key_presses=1,
                requested_ticks=2000,
                ticks_advanced=2000,
                saved_elapsed_ticks=ticks,
                returned_tokens=10,
                clock_error=None,
                input_accepted=True,
                metrics=copy.deepcopy(after),
            )
            result["timeline"].append(row)
        metrics = after
        usage = {
            **prior["usage"],
            "accounted_responses": cursor,
            "dispatched_requests": cursor,
            "returned_responses": cursor,
            "total_tokens": tokens,
        }
        calendar = (
            prior["final_boundary"]["year"] * 403200
            + prior["final_boundary"]["year_tick"]
            + ticks
            - 59500
        )
        boundary = {"year": calendar // 403200, "year_tick": calendar % 403200, "paused": True}
        point = {
            "segment_index": index,
            "first_step": first,
            "next_step": cursor,
            "new_responses": count,
            "new_tokens": count * 10,
            "new_saved_ticks": count * 2000,
            "saved_elapsed_ticks": ticks,
            "usage": usage,
            "prior_checkpoint_sha256": parent,
            "checkpoint_sha256": f"{index + 1:064x}",
            "initial_metrics": initial,
            "saved_metrics": copy.deepcopy(metrics),
            "source_checkpoint_fresh_load_verified": True,
            "native_cleanup_verified": True,
            "final_fresh_reload_verified": index < len(counts) - 1,
            "final_boundary": boundary,
        }
        result["checkpoint_segments"].append(point)
        parent = point["checkpoint_sha256"]
    result.update(
        checkpoint_sha256=parent, final_boundary=boundary, usage=usage, saved_metrics=metrics
    )
    return prior, result


def test_every_checkpoint_is_preserved_and_only_final_one_has_vm_shutdown():
    prior, result = fixture()
    campaign.validate_continuation(prior, result)
    points = window_checkpoints(result, URL)
    assert [row["responses"] for row in points] == [128, 160, 192, 224, 256]
    assert [row["continuation_reload_verified"] for row in points] == [True] * 4 + [False]
    assert all(row["separate_fresh_reload_verified"] is False for row in points)
    assert [row["shutdown"] for row in points[:-1]] == [None] * 4
    assert points[-1]["shutdown"] == result["audit"]["shutdown"]


@pytest.mark.parametrize("counts", [[0], [32, 0], [32, 11], [32, 32, 32, 32, 31]])
def test_pause_preserves_partial_prefix_and_distinct_zero_response_save(counts):
    prior, result = fixture(counts)
    campaign.validate_continuation(prior, result)
    points = window_checkpoints(result, URL)
    assert len(points) == len(counts)
    assert points[-1]["new_responses"] == counts[-1]
    assert len({row["checkpoint_sha256"] for row in points}) == len(points)
    assert points[-1]["continuation_reload_verified"] is False
    if counts == [32, 0]:
        assert [row["responses"] for row in points] == [128, 128]


@pytest.mark.parametrize(
    "field,value",
    [
        ("segment_index", True),
        ("first_step", 0),
        ("next_step", 191),
        ("new_responses", 0),
        ("new_tokens", 321),
        ("new_saved_ticks", 63999),
        ("saved_elapsed_ticks", 0),
        ("prior_checkpoint_sha256", "0" * 64),
        ("checkpoint_sha256", "not-a-hash"),
        ("source_checkpoint_fresh_load_verified", False),
        ("native_cleanup_verified", False),
        ("initial_metrics", {}),
        ("saved_metrics", {}),
        ("final_fresh_reload_verified", False),
        ("usage", {}),
        ("final_boundary", {"year": 30, "year_tick": 403200, "paused": True}),
    ],
)
def test_changed_middle_checkpoint_cannot_pass(field, value):
    prior, result = fixture()
    result["checkpoint_segments"][2][field] = value
    with pytest.raises(ValueError, match="checkpoint chain"):
        campaign.validate_continuation(prior, result)


def test_omitted_or_repeated_checkpoint_is_rejected():
    prior, result = fixture()
    result["checkpoint_segments"].pop(2)
    with pytest.raises(ValueError):
        campaign.validate_continuation(prior, result)
    prior, result = fixture()
    result["checkpoint_segments"][2]["checkpoint_sha256"] = result["checkpoint_segments"][1][
        "checkpoint_sha256"
    ]
    with pytest.raises(ValueError):
        campaign.validate_continuation(prior, result)


def test_terminal_checkpoint_does_not_invent_reload_proof():
    prior, result = fixture()
    result["checkpoint_segments"][-1]["final_fresh_reload_verified"] = True
    with pytest.raises(ValueError):
        validate_window_checkpoints(prior, result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("condition_id", "changed"),
        ("expected_campaign_id", "another-campaign"),
        ("source_native_revision", "0" * 40),
        ("reset_memory", True),
        ("reset_usage", True),
        ("strategy_intervention", True),
        ("budget_extension", {}),
        ("accounted_responses_before_window", 95),
        ("returned_tokens_before_window", 0),
        ("saved_elapsed_ticks_before_window", 0),
        ("max_segments", True),
    ],
)
def test_window_cannot_change_identity_baseline_or_original_conditions(field, value):
    prior, result = fixture()
    result["window"][field] = value
    with pytest.raises(ValueError):
        validate_window_checkpoints(prior, result)


def test_summary_cannot_misstate_starting_metrics_or_final_reload():
    prior, result = fixture()
    result["initial_metrics"] = {}
    with pytest.raises(ValueError):
        validate_window_checkpoints(prior, result)
    prior, result = fixture()
    result["proof_limits"]["fresh_final_checkpoint_reload_verified"] = True
    with pytest.raises(ValueError):
        validate_window_checkpoints(prior, result)


def test_prior_reload_evidence_updates_only_exact_last_save():
    prior, result = fixture()
    history = campaign.keyboard_binding_campaign()["checkpoints"]
    old = copy.deepcopy(history)
    mark_source_reload(history, result, URL)
    assert history[:-1] == old[:-1]
    assert history[-1]["checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert history[-1]["continuation_reload_verified"] is True
    assert history[-1]["separate_fresh_reload_verified"] is False
    assert history[-1]["continuation_reload_url"] == URL
    result["source_checkpoint_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        mark_source_reload(history, result, URL)


def test_new_capability_does_not_register_synthetic_results():
    data = campaign.keyboard_binding_campaign()
    assert data["responses"] == 96
    assert [point["responses"] for point in data["checkpoints"]] == [32, 64, 96]
    assert "synthetic" not in json.dumps(data).lower()
    assert all("continuation_reload_verified" not in point for point in data["checkpoints"])


def test_following_window_replaces_stale_unloaded_note_without_rewriting_prior_history():
    prior, result = fixture()
    campaign.validate_continuation(prior, result)
    history = window_checkpoints(result, URL)
    old = copy.deepcopy(history)
    assert "not yet been reloaded" in history[-1]["reload_note"]
    next_url = URL.replace("synthetic-not-published", "synthetic-next-window")
    following = {
        "source_checkpoint_sha256": result["checkpoint_sha256"],
        "audit": {"source_checkpoint_fresh_load_verified": True},
    }
    mark_source_reload(history, following, next_url)
    assert history[:-1] == old[:-1]
    assert history[-1]["continuation_reload_verified"] is True
    assert history[-1]["continuation_reload_url"] == next_url
    assert history[-1]["separate_fresh_reload_verified"] is False
    assert history[-1]["shutdown"] == old[-1]["shutdown"]
    assert "not yet been reloaded" not in history[-1]["reload_note"]
    assert "no standalone reload test was performed" in history[-1]["reload_note"]


@pytest.mark.parametrize("paused", [False, True])
def test_checkpoint_renderer_uses_safe_text_and_distinguishes_pause(paused):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    prior, result = fixture([32, 0] if paused else None)
    campaign.validate_continuation(prior, result)
    data = campaign.keyboard_binding_campaign()
    mark_source_reload(data["checkpoints"], result, URL)
    data["checkpoints"].extend(window_checkpoints(result, URL))
    data["timeline"].extend(result["timeline"])
    data.update(
        responses=result["responses"],
        stock_context=stock_context(result),
        status=result["status"],
        stop_reason=result["stop_reason"],
        saved_metrics=result["saved_metrics"],
        saved_elapsed_ticks=result["saved_elapsed_ticks"],
        usage=result["usage"],
        confirmed_key_presses=data["confirmed_key_presses"] + result["new_confirmed_key_presses"],
    )
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/keyboard_binding_checkpoints_dom.cjs"),
            str(root / "web/static/campaign-binding-campaign.js"),
        ],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=True,
    )
