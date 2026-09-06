"""Pinned local llama.cpp API identity; file hashes require a separate launch receipt."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

from .campaign_local import LocalInferenceError, local_json

TRANSPORT = "llama-cpp-local/v1"
BUILD = "b10516-b95502ba9"
TOKEN_PROFILE = "llama-chat-input-tokens/v1"


def json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_llama_settings(config: dict) -> None:
    """Require the measured text-only server profile without widening old conditions."""
    local = config["local_inference"]
    if local.get("server_version") != BUILD or local.get("token_count_profile") != TOKEN_PROFILE:
        raise ValueError("Unsupported pinned llama.cpp build or token-count profile")
    if type(local.get("enable_thinking")) is not bool:
        raise ValueError("Local llama.cpp thinking mode must be an explicit boolean")
    for key, lower, upper in (
        ("top_k", 1, 1000),
        ("context_headroom_tokens", 1, 4096),
        ("token_count_timeout_seconds", 1, 30),
    ):
        if type(local.get(key)) is not int or not lower <= local[key] <= upper:
            raise ValueError(f"Invalid local llama.cpp setting: {key}")
    top_p = local.get("top_p")
    if type(top_p) not in (int, float) or not 0 < top_p <= 1:
        raise ValueError("Invalid local llama.cpp top_p")
    for key in ("model_metadata_sha256", "chat_template_sha256"):
        values = local.get(key)
        if not isinstance(values, dict) or set(values) != set(config["models"]):
            raise ValueError(f"Bind every local model to {key}")
        if any(
            not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in values.values()
        ):
            raise ValueError(f"Invalid local model digest: {key}")
    files = local.get("model_files")
    if not isinstance(files, dict) or set(files) != set(config["models"]):
        raise ValueError("Bind every local model to a GGUF filename")
    if any(
        not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.gguf", v)
        for v in files.values()
    ):
        raise ValueError("Local model files must be GGUF basenames, not private paths")


def verify_llama_model(endpoint: str, config: dict, model: str) -> dict:
    """Check observed API properties; never claim the API computes a weight-file hash."""
    local = config["local_inference"]
    props = local_json(endpoint, "/props")
    models = local_json(endpoint, "/v1/models").get("data")
    settings = props.get("default_generation_settings")
    if (
        props.get("build_info") != BUILD
        or type(props.get("total_slots")) is not int
        or props["total_slots"] != 1
        or props.get("is_sleeping") is not False
        or not isinstance(settings, dict)
        or type(settings.get("n_ctx")) is not int
        or settings["n_ctx"] != local["context_tokens"]
        or not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
        or models[0].get("id") != model
        or not isinstance(models[0].get("meta"), dict)
    ):
        raise LocalInferenceError("Local llama.cpp runtime or model identity differs")
    path, template = props.get("model_path"), props.get("chat_template")
    if (
        not isinstance(path, str)
        or PurePosixPath(path).name != local["model_files"][model]
        or not isinstance(template, str)
        or hashlib.sha256(template.encode()).hexdigest() != local["chat_template_sha256"][model]
        or json_digest(models[0]["meta"]) != local["model_metadata_sha256"][model]
    ):
        raise LocalInferenceError("Local llama.cpp model metadata or template differs")
    return {
        "build_info": BUILD,
        "context_tokens": settings["n_ctx"],
        "model_metadata_sha256": local["model_metadata_sha256"][model],
        "chat_template_sha256": local["chat_template_sha256"][model],
        "scope": "observed_api_properties_not_a_weight_file_hash_attestation",
    }
