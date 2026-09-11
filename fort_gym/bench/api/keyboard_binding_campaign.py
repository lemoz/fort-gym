"""A registered displayed-key campaign chain, separate from historical cohorts."""

from .keyboard_binding_results import REPOSITORY, SOURCE_REVISION, keyboard_binding_result
from .keyboard_endurance_records import read_result

RESULT_PATH = "experiments/evidence/keyboard_binding_astra_r1_continuation_32_64_20260911.json"
RESULT_SHA256 = "5f86a754fbb979a567c14a236250ccd518c171db79e598ae9adaa4745db9d8e4"
RESULT_REVISION = "fac32010f483959ed2c28d358ec358c1d9ab20fc"
RELOAD_PATH = "experiments/evidence/keyboard_binding_astra_r1_reload_20260911.json"
RELOAD_SHA256 = "291bee15debe7c47d606221b61e99ce8eef0415233480042a4fa0720c5d39458"
RELOAD_REVISION = "242fa861227fd725a839909f04e7a6203cd0f20a"


def validate_chain(prior: dict, result: dict, reload: dict) -> None:
    """Reject changed identities or inconsistent cumulative accounting."""
    if (
        result["schema_version"] != "fortgym.public-keyboard-binding-continuation-result/v1"
        or result["campaign_id"] != prior["campaign_id"]
        or result["source_revision"] != SOURCE_REVISION
        or result["source_checkpoint_sha256"] != prior["checkpoint_sha256"]
        or result["first_step"] != prior["responses"]
        or result["status"] not in {"completed", "paused"}
        or result["audit"]["passed"] is not True
        or result["proof_limits"]["same_campaign_own_save_continuation"] is not True
        or any(
            result["proof_limits"][key] is not False
            for key in (
                "same_condition_as_historical_matched_cohort",
                "memory_or_usage_reset",
                "prompt_or_budget_changed",
                "human_gameplay_rescue",
            )
        )
    ):
        raise ValueError("Unexpected displayed-key continuation identity")
    for key in ("model", "reasoning_effort", "control_profile", "prompt_profile", "transport"):
        if result["condition"][key] != prior["condition"][key]:
            raise ValueError("Displayed-key continuation changed its condition")
    rows = result["timeline"]
    expected = list(range(prior["responses"] + 1, result["responses"] + 1))
    if (
        len(rows) != result["new_responses"]
        or [row["decision"] for row in rows] != expected
        or result["responses"] != prior["responses"] + result["new_responses"]
        or result["saved_elapsed_ticks"]
        != prior["saved_elapsed_ticks"] + result["new_saved_elapsed_ticks"]
        or sum(row["ticks_advanced"] for row in rows) != result["new_saved_elapsed_ticks"]
        or sum(row["returned_tokens"] for row in rows) != result["new_tokens"]
        or result["usage"]["total_tokens"] != prior["usage"]["total_tokens"] + result["new_tokens"]
        or result["audit"]["provider_receipts_verified"] != len(rows)
        or (rows and rows[-1]["metrics"] != result["saved_metrics"])
    ):
        raise ValueError("Displayed-key continuation accounting differs")
    if (
        reload["schema_version"] != "fortgym.public-binding-checkpoint-reload/v1"
        or reload["campaign_id"] != prior["campaign_id"]
        or reload["checkpoint_sha256"] != prior["checkpoint_sha256"]
        or reload["next_step"] != prior["responses"]
        or reload["native_load_verified"] is not True
        or reload["normal_loop_restore_verified"] is not True
        or reload["restored_agent_memory_configuration_prompt_and_history_unchanged"] is not True
        or any(
            reload[key] != 0
            for key in ("new_model_calls", "new_gameplay_actions", "new_gameplay_ticks")
        )
    ):
        raise ValueError("Reload evidence does not identify the earlier checkpoint")


def keyboard_binding_campaign() -> dict:
    """Return the exact recorded chain; never scan private or active artifacts."""
    initial = keyboard_binding_result()
    prior = initial["result"]
    result = read_result(RESULT_PATH, RESULT_SHA256)
    reload = read_result(RELOAD_PATH, RELOAD_SHA256)
    validate_chain(prior, result, reload)
    result_url = REPOSITORY + RESULT_REVISION + "/" + RESULT_PATH
    reload_url = REPOSITORY + RELOAD_REVISION + "/" + RELOAD_PATH
    return {
        "schema_version": "fortgym.public-keyboard-binding-campaign/v1",
        "recorded_only": True,
        "included_in_historical_cohort": False,
        "independent_attempts": 1,
        "campaign_id": result["campaign_id"],
        "status": result["status"],
        "stop_reason": result["stop_reason"],
        "condition": result["condition"],
        "responses": result["responses"],
        "saved_elapsed_ticks": result["saved_elapsed_ticks"],
        "ticks_per_year": result["ticks_per_year"],
        "saved_metrics": result["saved_metrics"],
        "usage": result["usage"],
        "confirmed_key_presses": prior["confirmed_key_presses"]
        + result["new_confirmed_key_presses"],
        "timeline": [*prior["timeline"], *result["timeline"]],
        "latest_window": {
            "first_step": result["first_step"],
            "responses": result["new_responses"],
            "elapsed_ticks": result["new_saved_elapsed_ticks"],
            "returned_tokens": result["new_tokens"],
            "initial_metrics": result["initial_metrics"],
            "clock_outcomes": result["new_clock_outcomes"],
        },
        "checkpoints": [
            {
                "responses": prior["responses"],
                "saved_elapsed_ticks": prior["saved_elapsed_ticks"],
                "checkpoint_sha256": prior["checkpoint_sha256"],
                "save_verified": True,
                "separate_fresh_reload_verified": True,
                "result_url": initial["result_url"],
                "reload_url": reload_url,
                "reload_note": "Default menu after reload; no manual menu restoration. Original save and agent state unchanged. The copied save only appended two DFHack load-event log lines; the initial strict equality failure and later scoped audit remain recorded.",
            },
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
                "reload_note": "No separate post-run fresh reload of this latest checkpoint has been performed.",
            },
        ],
        "result_url": result_url,
        "result_sha256": RESULT_SHA256,
        "condition_url": initial["condition_url"],
        "trial_url": initial["trial_url"],
        "initial_result_url": initial["result_url"],
        "reload_url": reload_url,
        "proof_limits": result["proof_limits"],
        "cost_limits": result["cost_limits"],
        "shutdown": result["audit"]["shutdown"],
    }
