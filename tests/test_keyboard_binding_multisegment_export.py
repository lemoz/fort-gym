"""Synthetic export composition checks; not native gameplay or reload proof."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "binding_window_export_v2",
    ROOT / "experiments/keyboard_binding_continuation_20260911/export_window_v2.py",
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


@pytest.fixture
def composed(tmp_path, monkeypatch):
    """Stub only the native auditor; check exact arguments and public composition."""
    monkeypatch.setattr(export, "RUNTIME", tmp_path)
    original = tmp_path / "prior/checkpoint/checkpoint.json"
    original.parent.mkdir(parents=True)
    original.write_text(json.dumps({"sha256": "a" * 64}))
    native = tmp_path / "current/evidence/astra"
    metrics = {"population": 7, "food_stock": 58}
    condition = {"condition_id": "synthetic"}
    window = {"max_segments": 5}
    prior = {"checkpoint_sha256": "a" * 64, "saved_metrics": metrics}
    saved = []
    parent = prior["checkpoint_sha256"]
    for index in range(5):
        row = {
            "segment_index": index,
            "first_step": 96 + 32 * index,
            "next_step": 128 + 32 * index,
            "new_responses": 32,
            "new_tokens": 100,
            "new_saved_ticks": 2000,
            "saved_elapsed_ticks": 59500 + 2000 * (index + 1),
            "usage": {"total_tokens": 2567162 + 100 * (index + 1)},
            "prior_checkpoint_sha256": parent,
            "checkpoint_sha256": str(index) * 64,
            "initial_metrics": metrics,
            "saved_metrics": metrics,
            "source_checkpoint_fresh_load_verified": True,
            "native_cleanup_verified": True,
            "final_fresh_reload_verified": index < 4,
        }
        saved.append(row)
        parent = row["checkpoint_sha256"]
        path = native / f"segment-{index}/native-after.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "year": 30,
                    "year_tick": 78301 + index * 2000,
                    "pause_state": True,
                    "test_metrics": metrics,
                }
            )
        )
    report = {
        "segments": saved,
        "first_step": 96,
        "next_step": 256,
        "new_responses": 160,
        "new_tokens": 500,
        "new_saved_ticks": 10000,
        "saved_elapsed_ticks": 69500,
        "usage": saved[-1]["usage"],
        "checkpoint_sha256": saved[-1]["checkpoint_sha256"],
        "prior_checkpoint_sha256": prior["checkpoint_sha256"],
        "initial_metrics": metrics,
        "saved_metrics": metrics,
        "status": "completed",
        "final_fresh_reload_verified": False,
    }
    audit = {
        "schema_version": "fortgym.private-binding-window-terminal-review/v1",
        "sources": {"prior/checkpoint/checkpoint.json": export.sha(original)},
        "checkpoint_segments": copy.deepcopy(saved),
        **{
            key: value
            for key, value in report.items()
            if key not in {"segments", "next_step", "new_saved_ticks", "prior_checkpoint_sha256"}
        },
        "responses": 256,
        "new_saved_elapsed_ticks": 10000,
        "source_checkpoint_sha256": prior["checkpoint_sha256"],
    }
    calls = []
    fake = ModuleType("fort_gym.bench.run.keyboard_window_checkpoint_audit")

    def verified(path, parent, **kwargs):
        assert path == native and parent == original.parent
        assert kwargs == {"condition": condition, "window": window, "initial_metrics": metrics}
        calls.append(True)
        return report

    fake.verify_window_checkpoints = verified
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    import fort_gym.bench.eval.campaign_profile as profile

    monkeypatch.setattr(profile, "metrics_from_state", lambda state: state["test_metrics"])
    return native, audit, prior, condition, window, report, calls


def invoke(composed):
    return export.checkpoint_chain(*composed[:5])


def test_five_saved_boundaries_are_not_collapsed_into_last_checkpoint(composed):
    checkpoints = invoke(composed)
    assert [row["next_step"] for row in checkpoints] == [128, 160, 192, 224, 256]
    assert [row["final_fresh_reload_verified"] for row in checkpoints] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert checkpoints[-1]["final_boundary"] == {"year": 30, "year_tick": 86301, "paused": True}
    assert composed[-1] == [True]


@pytest.mark.parametrize(
    "field",
    [
        "responses",
        "new_responses",
        "new_tokens",
        "new_saved_elapsed_ticks",
        "saved_elapsed_ticks",
        "usage",
        "checkpoint_sha256",
        "source_checkpoint_sha256",
        "initial_metrics",
        "saved_metrics",
        "status",
    ],
)
def test_reaudited_checkpoint_totals_must_equal_bound_terminal_audit(composed, field):
    composed[1][field] = "changed"
    with pytest.raises(AssertionError, match="mismatch"):
        invoke(composed)


def test_mismatched_segment_receipts_are_rejected(composed):
    composed[1]["checkpoint_segments"][2]["checkpoint_sha256"] = "f" * 64
    with pytest.raises(AssertionError):
        invoke(composed)


def test_final_save_cannot_claim_a_subsequent_reload(composed):
    composed[5]["final_fresh_reload_verified"] = True
    with pytest.raises(AssertionError):
        invoke(composed)


def test_missing_original_save_is_not_substituted_with_final_save(composed):
    composed[1]["sources"] = {}
    with pytest.raises(AssertionError, match="Exactly one"):
        invoke(composed)


def test_duplicate_original_save_source_is_rejected(composed):
    composed[1]["sources"]["prior/checkpoint/../checkpoint/checkpoint.json"] = "a" * 64
    with pytest.raises(AssertionError, match="Exactly one"):
        invoke(composed)


def test_source_path_cannot_escape_owned_runtime(composed):
    composed[1]["sources"] = {"../outside/checkpoint/checkpoint.json": "a" * 64}
    with pytest.raises(AssertionError):
        invoke(composed)


def test_completed_paused_prefix_keeps_both_checkpoint_identities(composed):
    audit, report = composed[1], composed[5]
    saved = copy.deepcopy(report["segments"][:2])
    saved[-1].update(
        next_step=148,
        new_responses=20,
        new_tokens=60,
        new_saved_ticks=1250,
        saved_elapsed_ticks=62750,
        usage={"total_tokens": 2567322},
        final_fresh_reload_verified=False,
    )
    report.update(
        segments=saved,
        status="paused",
        next_step=148,
        new_responses=52,
        new_tokens=160,
        new_saved_ticks=3250,
        saved_elapsed_ticks=62750,
        usage=saved[-1]["usage"],
        checkpoint_sha256=saved[-1]["checkpoint_sha256"],
    )
    audit.update(
        checkpoint_segments=copy.deepcopy(saved),
        status="paused",
        responses=148,
        new_responses=52,
        new_tokens=160,
        new_saved_elapsed_ticks=3250,
        saved_elapsed_ticks=62750,
        usage=saved[-1]["usage"],
        checkpoint_sha256=saved[-1]["checkpoint_sha256"],
    )
    checkpoints = invoke(composed)
    assert [row["next_step"] for row in checkpoints] == [128, 148]
    assert [row["final_fresh_reload_verified"] for row in checkpoints] == [True, False]


def test_zero_response_pause_still_retains_its_new_save(composed):
    audit, report = composed[1], composed[5]
    saved = copy.deepcopy(report["segments"][:1])
    saved[0].update(
        next_step=96,
        new_responses=0,
        new_tokens=0,
        new_saved_ticks=0,
        saved_elapsed_ticks=59500,
        usage={"total_tokens": 2567162},
        final_fresh_reload_verified=False,
    )
    report.update(
        segments=saved,
        status="paused",
        next_step=96,
        new_responses=0,
        new_tokens=0,
        new_saved_ticks=0,
        saved_elapsed_ticks=59500,
        usage=saved[0]["usage"],
        checkpoint_sha256=saved[0]["checkpoint_sha256"],
    )
    audit.update(
        checkpoint_segments=copy.deepcopy(saved),
        status="paused",
        responses=96,
        new_responses=0,
        new_tokens=0,
        new_saved_elapsed_ticks=0,
        saved_elapsed_ticks=59500,
        usage=saved[0]["usage"],
        checkpoint_sha256=saved[0]["checkpoint_sha256"],
    )
    checkpoints = invoke(composed)
    assert len(checkpoints) == 1 and checkpoints[0]["new_responses"] == 0
    assert checkpoints[0]["checkpoint_sha256"] != checkpoints[0]["prior_checkpoint_sha256"]
    assert checkpoints[0]["final_fresh_reload_verified"] is False


def test_extra_private_fields_are_not_exported(composed):
    saved = copy.deepcopy(composed[5]["segments"][0])
    saved["private_path"] = "/private/model"
    saved["memory_update"] = "not public"
    public = export.public_checkpoint(saved)
    assert "private_path" not in public and "memory_update" not in public


def test_legacy_single_segment_remains_legacy():
    assert (
        export.checkpoint_chain(
            None,
            {"schema_version": "fortgym.private-binding-continuation-terminal-review/v1"},
            {},
            {},
            {"max_segments": 1},
        )
        is None
    )
    with pytest.raises(AssertionError):
        export.checkpoint_chain(
            None,
            {"schema_version": "fortgym.private-binding-continuation-terminal-review/v1"},
            {},
            {},
            {"max_segments": 5},
        )
