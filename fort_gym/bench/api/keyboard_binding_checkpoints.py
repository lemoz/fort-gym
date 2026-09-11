"""Validate and display each saved checkpoint in a recorded continuation window."""

import re

from ..eval.campaign import TICKS_PER_YEAR

_CONTINUATION_RELOAD_NOTE = (
    "A fresh game process loaded this save for the following segment; "
    "no standalone reload test was performed."
)


def _require(value: bool) -> None:
    if not value:
        raise ValueError("Displayed-key checkpoint chain differs from its recorded window")


def _integer(value: object, minimum: int = 0, maximum: int | None = None) -> bool:
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def validate_window_checkpoints(prior: dict, result: dict) -> None:
    """Reconcile public checkpoint metadata with every corresponding action row."""
    if "checkpoint_segments" not in result:
        return
    saved, window = result["checkpoint_segments"], result["window"]
    _require(isinstance(saved, list) and isinstance(window, dict))
    _require(window.get("schema_version") == "fortgym.codex-keyboard-window/v1")
    _require(window.get("condition_id") == result["condition"]["condition_id"])
    _require(window.get("expected_campaign_id") == result["campaign_id"])
    _require(window.get("source_native_revision") == result["source_revision"])
    _require(
        all(
            window.get(key) is False
            for key in ("reset_memory", "reset_usage", "strategy_intervention")
        )
    )
    _require(not ({"restart", "prompt_change", "budget_extension"} & window.keys()))
    _require(result.get("initial_metrics") == prior["saved_metrics"])
    _require(result["proof_limits"].get("fresh_final_checkpoint_reload_verified") is False)
    for key, expected in (
        ("accounted_responses_before_window", prior["responses"]),
        ("returned_tokens_before_window", prior["usage"]["total_tokens"]),
        ("saved_elapsed_ticks_before_window", prior["saved_elapsed_ticks"]),
    ):
        _require(_integer(window.get(key)) and window[key] == expected)
    steps, maximum = window.get("steps_per_segment"), window.get("max_segments")
    _require(_integer(steps, 1, 64) and _integer(maximum, 1, 16))
    _require(1 <= len(saved) <= maximum)
    _require(window.get("continuation_from_next_step") == prior["responses"])
    _require(window.get("continuation_checkpoint_sha256") == prior["checkpoint_sha256"])
    _require(window.get("window_end_decision") == prior["responses"] + steps * maximum)
    _require(window["window_end_decision"] <= result["condition"]["max_dispatches"])
    _require(result["audit"].get("source_checkpoint_fresh_load_verified") is True)
    _require(
        type(result["audit"].get("saved_checkpoints_verified")) is int
        and result["audit"]["saved_checkpoints_verified"] == len(saved)
    )
    _require(result["status"] in {"completed", "paused"})
    _require(
        result["stop_reason"]
        == ("segment_limit" if result["status"] == "completed" else "budget_limited_pause")
    )
    if result["status"] == "completed":
        _require(len(saved) == maximum)
    cursor, tokens, ticks = (
        prior["responses"],
        prior["usage"]["total_tokens"],
        prior["saved_elapsed_ticks"],
    )
    parent, metrics = prior["checkpoint_sha256"], prior["saved_metrics"]
    seen = {parent}
    for index, point in enumerate(saved):
        _require(isinstance(point, dict))
        first, end = point.get("first_step"), point.get("next_step")
        _require(_integer(point.get("segment_index")) and point["segment_index"] == index)
        _require(_integer(first) and first == cursor == prior["responses"] + index * steps)
        _require(_integer(end, first, first + steps))
        count = end - first
        paused = result["status"] == "paused" and index == len(saved) - 1
        _require(count < steps if paused else count == steps)
        _require(_integer(point.get("new_responses")) and point["new_responses"] == count)
        _require(_integer(point.get("new_tokens")) and _integer(point.get("new_saved_ticks")))
        _require(point.get("prior_checkpoint_sha256") == parent)
        digest = point.get("checkpoint_sha256")
        _require(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) is not None)
        _require(digest not in seen)
        _require(
            point.get("source_checkpoint_fresh_load_verified") is True
            and point.get("native_cleanup_verified") is True
        )
        _require(point.get("final_fresh_reload_verified") is (index < len(saved) - 1))
        _require(point.get("initial_metrics") == metrics)
        rows = result["timeline"][first - prior["responses"] : end - prior["responses"]]
        _require(len(rows) == count)
        _require(sum(row["returned_tokens"] for row in rows) == point["new_tokens"])
        _require(sum(row["ticks_advanced"] for row in rows) == point["new_saved_ticks"])
        metrics = rows[-1]["metrics"] if rows else metrics
        _require(point.get("saved_metrics") == metrics)
        tokens += point["new_tokens"]
        ticks += point["new_saved_ticks"]
        usage = point.get("usage")
        _require(isinstance(usage, dict))
        _require(_integer(usage.get("total_tokens")) and usage["total_tokens"] == tokens)
        _require(usage.get("total_cost_usd") is None)
        for key in ("accounted_responses", "dispatched_requests", "returned_responses"):
            _require(_integer(usage.get(key)) and usage[key] == end)
        _require(
            _integer(point.get("saved_elapsed_ticks")) and point["saved_elapsed_ticks"] == ticks
        )
        boundary = point.get("final_boundary")
        _require(isinstance(boundary, dict) and boundary.get("paused") is True)
        _require(
            _integer(boundary.get("year"))
            and _integer(boundary.get("year_tick"), 0, TICKS_PER_YEAR - 1)
        )
        baseline = prior["final_boundary"]
        calendar_ticks = (
            (boundary["year"] - baseline["year"]) * TICKS_PER_YEAR
            + boundary["year_tick"]
            - baseline["year_tick"]
        )
        _require(calendar_ticks == ticks - prior["saved_elapsed_ticks"])
        seen.add(digest)
        cursor, parent = end, digest
    _require(cursor == result["responses"] and parent == result["checkpoint_sha256"])
    _require(tokens == result["usage"]["total_tokens"] and ticks == result["saved_elapsed_ticks"])
    _require(saved[-1]["usage"] == result["usage"] and metrics == result["saved_metrics"])
    _require(saved[-1]["final_boundary"] == result["final_boundary"])


def window_checkpoints(result: dict, result_url: str) -> list[dict]:
    """Project an already-validated window, preserving the legacy one-save shape."""
    if "checkpoint_segments" not in result:
        return [
            {
                "responses": result["responses"],
                "saved_elapsed_ticks": result["saved_elapsed_ticks"],
                "checkpoint_sha256": result["checkpoint_sha256"],
                "save_verified": True,
                "separate_fresh_reload_verified": result["proof_limits"][
                    "fresh_final_checkpoint_reload_verified"
                ],
                "result_url": result_url,
                "reload_url": None,
                "reload_note": "No separate post-run fresh reload of this checkpoint has been performed.",
                "shutdown": result["audit"]["shutdown"],
            }
        ]
    points = result["checkpoint_segments"]
    return [
        {
            "responses": point["next_step"],
            "saved_elapsed_ticks": point["saved_elapsed_ticks"],
            "checkpoint_sha256": point["checkpoint_sha256"],
            "save_verified": True,
            "separate_fresh_reload_verified": False,
            "result_url": result_url,
            "reload_url": None,
            "reload_note": (
                _CONTINUATION_RELOAD_NOTE
                if point["final_fresh_reload_verified"]
                else "This saved endpoint has not yet been reloaded by a following segment or standalone test."
            ),
            "shutdown": result["audit"]["shutdown"] if index == len(points) - 1 else None,
            "segment_index": point["segment_index"],
            "new_responses": point["new_responses"],
            "continuation_reload_verified": point["final_fresh_reload_verified"],
            "continuation_reload_url": result_url if point["final_fresh_reload_verified"] else None,
        }
        for index, point in enumerate(points)
    ]


def mark_source_reload(checkpoints: list[dict], result: dict, result_url: str) -> None:
    """Attach newly verified continued-play reload evidence to the exact prior save."""
    if result["audit"].get("source_checkpoint_fresh_load_verified") is not True:
        return
    _require(
        bool(checkpoints)
        and checkpoints[-1]["checkpoint_sha256"] == result["source_checkpoint_sha256"]
    )
    checkpoints[-1].update(
        continuation_reload_verified=True,
        continuation_reload_url=result_url,
    )
    if "segment_index" in checkpoints[-1] and not checkpoints[-1]["separate_fresh_reload_verified"]:
        checkpoints[-1]["reload_note"] = _CONTINUATION_RELOAD_NOTE
