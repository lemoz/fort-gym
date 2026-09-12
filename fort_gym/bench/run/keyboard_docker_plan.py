"""Portable container launch inputs, without starting Docker, a game or a model."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
import re

from ..agent.campaign_keyboard import CodexKeyboardAgent
from ..agent.keyboard_exchange import read
from ..agent.keyboard_prompt import BASE_PROMPT, declared_prompt_change
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import reconciled_usage
from .keyboard_config import load_window, positive
from .keyboard_trial_config import load_trial
from .keyboard_window_courier import container_path, window_bounds
from .keyboard_seccomp import read_profile

SCHEMA = "fortgym.keyboard-docker-runtime/v1"
SECCOMP_SCHEMA = "fortgym.keyboard-docker-runtime/v2"
NATIVE_OUTPUT = "/fortgym-evidence/native"
LABEL = "org.fortgym.owner"


def validate_runtime(value: dict) -> dict:
    required = {
        "schema_version",
        "image",
        "source_revision",
        "project_directory",
        "python_executable",
        "runtime_directory",
        "cpus",
        "memory_mib",
        "pids_limit",
        "minimum_host_free_bytes",
    }
    if value.get("schema_version") == SECCOMP_SCHEMA:
        required |= {"seccomp_profile", "seccomp_sha256"}
    if set(value) != required or value["schema_version"] not in (SCHEMA, SECCOMP_SCHEMA):
        raise ValueError("Docker runtime configuration fields differ")
    if (
        not isinstance(value["image"], str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", value["image"])
        or not isinstance(value["source_revision"], str)
        or not re.fullmatch(r"[a-f0-9]{40}", value["source_revision"])
    ):
        raise ValueError("Runtime needs an exact existing image and source revision")
    for key in ("project_directory", "python_executable", "runtime_directory"):
        path = container_path(value[key])
        if any(
            path == root or path.startswith(root + "/")
            for root in ("/fortgym-evidence", "/fortgym-config", "/fortgym-origin")
        ):
            raise ValueError("Runtime paths overlap the owner's mounts")
    positive(value["cpus"], "Docker CPUs", maximum=64)
    positive(value["memory_mib"], "Docker memory", maximum=262144)
    positive(value["pids_limit"], "Docker process limit", maximum=4096)
    if value["memory_mib"] < 512 or value["pids_limit"] < 32:
        raise ValueError("Docker runtime resources are too small")
    if (
        type(value["minimum_host_free_bytes"]) is not int
        or value["minimum_host_free_bytes"] < 1073741824
    ):
        raise ValueError("Runtime free-space floor must be at least 1 GiB")
    if value["schema_version"] == SECCOMP_SCHEMA:
        if not isinstance(value["seccomp_profile"], str) or not isinstance(
            value["seccomp_sha256"], str
        ):
            raise ValueError("Seccomp profile and SHA256 must be strings")
        read_profile(value["seccomp_profile"], value["seccomp_sha256"])
    return value


def absolute_path(path: Path) -> Path:
    # Docker --mount uses comma-separated fields. Reject ambiguity, not shell-escape it.
    if (
        not path.is_absolute()
        or path != path.resolve()
        or any(char in str(path) for char in (",", "\n", "\r", "\0"))
    ):
        raise ValueError("Owner paths must be resolved absolute paths without mount separators")
    return path


def prepare_inputs(
    condition_path: Path, declaration_path: Path, origin: Path, campaign_id: str, *, mode: str
) -> dict:
    for path in (condition_path, declaration_path, origin):
        absolute_path(path)
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", campaign_id)
        or not origin.is_dir()
        or mode not in ("fresh", "continue")
    ):
        raise ValueError("Invalid native campaign identity, origin or mode")
    names = [condition_path.name, declaration_path.name]
    if names[0] == names[1] or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", n) for n in names
    ):
        raise ValueError("Condition and declaration need distinct literal filenames")
    if mode == "fresh":
        from scripts.campaign_load_smoke import verify_snapshot

        condition, declaration = load_trial(condition_path, declaration_path)
        original = verify_snapshot(origin, declaration["source_snapshot_receipt_sha256"])
        memory = ""
        limit = declaration["steps_per_segment"]
        seconds = limit * (condition["exchange_timeout_seconds"] + 120) + 300
    else:
        condition, declaration = load_window(condition_path, declaration_path)
        limit, seconds = window_bounds(condition, declaration)
        original = verify_checkpoint(origin)
        if (
            original["payload"]["campaign_id"] != campaign_id
            or original["payload"]["next_step"] != declaration["continuation_from_next_step"]
            or declaration.get("continuation_checkpoint_sha256", original["sha256"])
            != original["sha256"]
        ):
            raise ValueError("Continuation differs from its own declared checkpoint")
        state = read(origin / "agent.json")
        declared_prompt_change(
            state,
            None,
            profile=condition.get("prompt_profile", BASE_PROMPT),
            checkpoint_sha256=original["sha256"],
            next_step=declaration["continuation_from_next_step"],
        )
        if reconciled_usage(state, (origin / "usage.jsonl").read_bytes()) != state["usage"]:
            raise ValueError("Checkpoint usage is not settled")
        agent = CodexKeyboardAgent(
            decision=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Offline only")),
            **{
                key: condition[key]
                for key in (
                    "max_dispatches",
                    "max_total_tokens",
                    "max_advance_ticks",
                    "model",
                    "reasoning_effort",
                    "control_profile",
                )
            },
        )
        agent.restore_campaign_state(state, campaign_id=campaign_id)
        memory = agent.memory
    if (
        declaration.get("expected_campaign_id", campaign_id) != campaign_id
        or declaration.get(
            "source_condition_sha256", hashlib.sha256(condition_path.read_bytes()).hexdigest()
        )
        != hashlib.sha256(condition_path.read_bytes()).hexdigest()
    ):
        raise ValueError("Declaration campaign or original condition binding differs")
    if mode == "continue":
        expected = {
            "source_native_revision": original["payload"]["code_revision"],
            "window_end_decision": original["payload"]["next_step"] + limit,
            "accounted_responses_before_window": state["usage"]["accounted_responses"],
            "returned_tokens_before_window": state["usage"]["total_tokens"],
        }
        if any(key in declaration and declaration[key] != value for key, value in expected.items()):
            raise ValueError("Declaration source or original usage binding differs")
    return {
        "mode": mode,
        "campaign_id": campaign_id,
        "condition": condition,
        "declaration": declaration,
        "original": original,
        "initial_memory": memory,
        "limit": limit,
        "seconds": seconds,
        "condition_name": names[0],
        "declaration_name": names[1],
    }


def create_arguments(
    runtime: dict, inputs: dict, output: Path, origin: Path, name: str, nonce: str, port: int
) -> list[str]:
    validate_runtime(runtime)
    lineage = {
        "source_native_revision": "source_revision",
        "source_image_id": "image",
        "seccomp_sha256": "seccomp_sha256",
    }
    if any(
        key in inputs["declaration"] and inputs["declaration"][key] != runtime.get(target)
        for key, target in lineage.items()
    ):
        raise ValueError("Declared native source or image requires its original runtime owner")
    absolute_path(output)
    absolute_path(origin)
    segments = inputs["declaration"].get("max_segments", 1)
    if (
        type(port) is not int
        or not 1024 <= port <= 65535 - segments
        or 5000 in range(port, port + segments)
        or os.getuid() == 0
    ):
        raise ValueError("Use an unprivileged owner and a dedicated native port range")
    if not re.fullmatch(r"fortgym-[a-f0-9]{32}", name) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid owner identity")
    mounts = [
        (output / "game", "/fortgym-evidence", False),
        (output / "inputs", "/fortgym-config", True),
        (origin, "/fortgym-origin", True),
    ]
    command = [
        "create",
        "--pull",
        "never",
        "--name",
        name,
        "--init",
        "--label",
        LABEL + "=" + nonce,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cpus",
        str(runtime["cpus"]),
        "--memory",
        str(runtime["memory_mib"]) + "m",
        "--memory-swap",
        str(runtime["memory_mib"]) + "m",
        "--pids-limit",
        str(runtime["pids_limit"]),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=64m",
        "--workdir",
        runtime["project_directory"],
        "--entrypoint",
        runtime["python_executable"],
        "--env",
        "FORT_GYM_DISABLE_DOTENV=1",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    if runtime["schema_version"] == SECCOMP_SCHEMA:
        # The owner retains verified bytes here before Docker reads this profile.
        # Docker reads it on the client; it is never a mount into the game.
        command += ["--security-opt", "seccomp=" + str(output / "seccomp.json")]
    for source, target, readonly in mounts:
        command += [
            "--mount",
            f"type=bind,src={source},dst={target}" + (",readonly" if readonly else ""),
        ]
    fresh = inputs["mode"] == "fresh"
    module = "scripts.campaign_keyboard_trial" if fresh else "scripts.campaign_keyboard_native"
    command += [
        runtime["image"],
        "-m",
        module,
        "run",
        "--condition",
        "/fortgym-config/" + inputs["condition_name"],
        "--trial" if fresh else "--window",
        "/fortgym-config/" + inputs["declaration_name"],
        "--source",
        runtime["runtime_directory"],
        "--output",
        NATIVE_OUTPUT,
        "--revision",
        runtime["source_revision"],
        "--port",
        str(port),
    ]
    if fresh:
        command += ["--campaign-id", inputs["campaign_id"], "--snapshot", "/fortgym-origin"]
    else:
        command += [
            "--checkpoint",
            "/fortgym-origin",
            "--latest-usage",
            "/fortgym-origin/usage.jsonl",
        ]
    return command
