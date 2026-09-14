"""One fresh native-keyboard segment, distinct from continuation windows."""

from pathlib import Path
import re

from ..agent.keyboard_exchange import read
from .keyboard_config import positive, validate_condition
from .keyboard_save import SAVE_PROFILES
from .campaign_food import validate_profile, validate_timeout_seconds
from .campaign_resources import PROFILE as RESOURCE_PROFILE


def load_trial(condition_path: Path, trial_path: Path) -> tuple[dict, dict]:
    condition, trial = validate_condition(read(condition_path)), read(trial_path)
    required = {
        "schema_version",
        "original_condition",
        "source_snapshot_receipt_sha256",
        "steps_per_segment",
        "initial_memory",
        "strategy_intervention",
        "snapshot_profile",
        "runtime_rpc_transport",
    }
    optional = {
        "private_measurement_profile",
        "private_measurement_timeout_seconds",
        "resource_observation_profile",
        "hypothesis",
        "notes",
    }
    if not required <= trial.keys() or trial.keys() - required - optional:
        raise ValueError("Fresh trial contains missing or unsupported fields")
    if (
        trial.get("schema_version") != "fortgym.keyboard-fresh-trial/v1"
        or trial.get("original_condition") != condition_path.name
        or trial.get("initial_memory") != "empty"
        or trial.get("strategy_intervention") is not False
        or any(
            key in trial
            for key in (
                "restart",
                "prompt_change",
                "budget_extension",
                "continuation_from_next_step",
            )
        )
    ):
        raise ValueError("Fresh trial must be independent, not a relabeled continuation")
    if not isinstance(trial.get("source_snapshot_receipt_sha256"), str) or not re.fullmatch(
        r"[a-f0-9]{64}", trial["source_snapshot_receipt_sha256"]
    ):
        raise ValueError("Fresh trial requires the exact starting snapshot receipt")
    positive(trial.get("steps_per_segment"), "initial segment size", maximum=64)
    if trial["steps_per_segment"] > condition["max_dispatches"]:
        raise ValueError("Fresh segment exceeds its declared dispatch allowance")
    if (
        not isinstance(trial.get("snapshot_profile"), str)
        or trial["snapshot_profile"] not in SAVE_PROFILES
    ):
        raise ValueError("Fresh trial must declare its native save profile")
    if trial.get("runtime_rpc_transport") not in ("cli", "native-rpc"):
        raise ValueError("Fresh trial must declare its native RPC transport")
    validate_profile(trial.get("private_measurement_profile"))
    if "private_measurement_timeout_seconds" in trial:
        validate_timeout_seconds(trial["private_measurement_timeout_seconds"])
        if trial.get("private_measurement_profile") is None:
            raise ValueError("Measurement timeout needs a measurement profile")
    if trial.get("resource_observation_profile") not in (None, RESOURCE_PROFILE):
        raise ValueError("Invalid fresh-trial resource observation profile")
    return condition, trial
