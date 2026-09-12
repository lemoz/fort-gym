"""Prepare a matched own-save continuation; no VM, provider or gameplay actions."""

from pathlib import Path, PurePosixPath
from typing import Any

from ..eval.displayed_key_comparison import read_comparison, read_evidence_object

COHORT_SHA = "da38987cb71b1bafde853d10e476e0c9539a950c9d90580ff1c2b1ba7cb839b0"
CONFIG_SHA256 = {
    "astra-condition.json": "7bf8ebf8656cf9c993764b6f1d02bb22dcd75d2a68aa2d4d1f868e49b5f4e1ab",
    "astra-trial.json": "3925997ef8a992a6da24e760543750e9d256d54d3ca832732e371983789dc0c8",
    "sol-condition.json": "15119adc949afe3b691485a944856a295d8e9b0ccc57657a9f1086f8dddd3db4",
    "sol-trial.json": "964d7bccd0764e4d94737dd4211d89fb3a221491dad9cbee83d48559415996d7",
    "terra-condition.json": "2e2fec4f202b518f496a8d57edb86e19e5352795545502034c9440f0b560795f",
    "terra-trial.json": "864efc0b37848dc3be7bb2c38a429ab14bd3d912ea1e0ff01c9d0a8ba97f7c40",
}
PRESERVED_PROFILES = (
    "snapshot_profile",
    "runtime_rpc_transport",
    "private_measurement_profile",
    "private_measurement_timeout_seconds",
    "resource_observation_profile",
)


def prepare_window(root: Path, index_path: str, campaign_id: str) -> dict[str, Any]:
    """Bind the next common 64-response window to this attempt's saved result.

    This supports only the frozen September 11 fresh-64 to saved-128 comparison.
    A paused or failed first window remains recorded but cannot be promoted to
    an ordinary completed checkpoint. Runtime admission and actual native reload
    verification remain separate requirements, not claims made by this function.
    """
    report = read_comparison(root, index_path, boundary=64)
    if report["plan_sha256"] != COHORT_SHA:
        raise ValueError("Continuation requires the frozen displayed-key cohort")
    selected = [row for row in report["trials"] if row["campaign_id"] == campaign_id]
    if len(selected) != 1:
        raise ValueError("Choose one predeclared campaign")
    row = selected[0]
    result = row["result"]
    if result is None or result["status"] != "saved":
        raise ValueError("Continuation requires a reviewed saved first boundary")
    index = read_evidence_object(root, index_path)
    if index["config_sha256"] != CONFIG_SHA256:
        raise ValueError("Continuation configuration differs from the frozen declaration")
    plan = read_evidence_object(root, index["cohort"]["path"], COHORT_SHA)
    declaration = next(item for item in plan["sequence"] if item["id"] == campaign_id)
    directory = PurePosixPath(index["cohort"]["path"]).parent
    condition = read_evidence_object(
        root,
        str(directory / declaration["condition"]),
        index["config_sha256"][declaration["condition"]],
    )
    trial = read_evidence_object(
        root, str(directory / declaration["trial"]), index["config_sha256"][declaration["trial"]]
    )
    if (
        condition["max_dispatches"] != plan["campaign_dispatch_cap"]
        or condition["max_total_tokens"] != plan["campaign_token_cap"]
        or trial["steps_per_segment"] != 64
        or plan["common_decision_boundaries"] != [64, 128]
        or any(
            condition.get(key) is not False
            for key in ("api_fallback", "automatic_credit_purchase", "automatic_reset_consumption")
        )
    ):
        raise ValueError("Continuation cannot alter the frozen resource or save limits")
    if (
        type(result["returned_tokens"]) is not int
        or result["returned_tokens"] <= 0
        or result["returned_tokens"] >= condition["max_total_tokens"]
        or condition["max_dispatches"] < 128
    ):
        raise ValueError("The original campaign usage ceiling leaves no continuation allowance")
    checkpoint = result["checkpoint"]
    value = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "condition_id": condition["condition_id"],
        "original_condition": declaration["condition"],
        "continuation_from_next_step": 64,
        "continuation_checkpoint_sha256": checkpoint["sha256"],
        "steps_per_segment": 64,
        "max_segments": 1,
        "window_end_decision": 128,
        "expected_campaign_id": campaign_id,
        "source_native_revision": plan["native_source_revision"],
        "source_image_id": plan["native_image"],
        "source_cohort_sha256": COHORT_SHA,
        "source_result_sha256": row["evidence_sha256"],
        "source_audit_sha256": result["terminal_audit_sha256"],
        "source_condition_sha256": index["config_sha256"][declaration["condition"]],
        "source_trial_sha256": index["config_sha256"][declaration["trial"]],
        "accounted_responses_before_window": 64,
        "returned_tokens_before_window": result["returned_tokens"],
        "saved_elapsed_ticks_before_window": checkpoint["saved_elapsed_ticks"],
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        **{key: trial[key] for key in PRESERVED_PROFILES},
        "hypothesis": (
            "With the same model, prompt, controls, own save and saved memory, another "
            "64 decisions test adaptation and fortress development at the common 128-response "
            "boundary. Keep failures, pauses and rejected actions in the comparison. "
            "Do not infer sustainability from inventories or action descriptions."
        ),
        "continuity_note": (
            "Restore this attempt's exact checkpoint, agent memory, prompt and budget history, "
            "trace and usage prefixes. Verify the fresh native load before the next model call. "
            "No borrowed fortress, seed restart, input replay, human strategy or menu rescue."
        ),
        "budget_note": (
            "At most 64 additional responses within the unchanged 1280-dispatch and 40000000-token "
            "campaign ceilings. Configuration is not launch admission or a dollar reservation. "
            "Check current subscription allowance before each call; no paid fallback, reset or "
            "credit purchase. One existing local VM at a time, with mandatory teardown."
        ),
    }
    # The growing index is mutable. Refuse mixed-generation inputs during preparation.
    if (
        read_comparison(root, index_path, boundary=64) != report
        or read_evidence_object(root, index_path) != index
    ):
        raise ValueError("Comparison sources changed during continuation preparation")
    return value
