"""Read-only live spectator adapter for the portable Docker owner's host layout."""
from __future__ import annotations

import json
from pathlib import Path
import re

from ..agent.keyboard_exchange import digest, read, validate_request
from .keyboard_config import validate_condition
from .keyboard_docker_owner import owned_container
from .keyboard_docker_plan import absolute_path
from .keyboard_docker_recording import require, sha
from scripts.campaign_watch_observe import snapshot as watch_snapshot


def baseline(attempt: Path) -> dict:
    absolute_path(attempt)
    plan_path = attempt / "owner-plan.json"
    plan = read(plan_path)
    require(plan.get("schema_version") == "fortgym.keyboard-docker-owner-plan/v1"
            and plan.get("mode") in ("fresh", "continue")
            and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", plan.get("campaign_id", "")) is not None,
            "Unsupported public owner plan")
    inputs = [read(path) for path in (attempt / "inputs").glob("*.json")]
    conditions = [value for value in inputs
                  if value.get("schema_version", "").startswith("fortgym.codex-keyboard-condition/")]
    declarations = [value for value in inputs if value not in conditions]
    require(len(conditions) == len(declarations) == 1, "Ambiguous owner inputs")
    condition, declaration = conditions[0], declarations[0]
    validate_condition(condition)
    require(digest(condition) == plan["condition_sha256"]
            and digest(declaration) == plan["declaration_sha256"], "Owner input binding differs")
    fresh = plan["mode"] == "fresh"
    require(declaration["schema_version"] ==
            ("fortgym.keyboard-fresh-trial/v1" if fresh else "fortgym.codex-keyboard-window/v1"),
            "Owner mode and declaration differ")
    first = 0 if fresh else declaration["continuation_from_next_step"]
    require(type(first) is int and first >= 0 and
            type(plan["response_limit"]) is int and 1 <= plan["response_limit"] <= 1024,
            "Invalid spectator decision boundary")
    return {"run_id": plan["campaign_id"], "model": condition["model"],
            "saved_checkpoint_cursor": first, "condition": condition, "plan": plan,
            "plan_sha256": sha(plan_path)}


def terminal(attempt: Path, base: dict) -> bool:
    """Retained terminal proof permits a stopped snapshot, never a live claim."""
    owner = read(attempt / "owner-result.json")
    plan = base["plan"]
    require(owner["campaign_id"] == base["run_id"] and owner["mode"] == plan["mode"]
            and owner["source_revision"] == plan["runtime"]["source_revision"]
            and owner["image"] == plan["runtime"]["image"]
            and owner["status"] in ("execution_finished", "failed", "budget_limited_pause"),
            "Terminal owner identity differs")
    if owner["container_create_attempted"]:
        container = read(attempt / "container-stopped.json")
        identity = owned_container(container, plan["runtime"], plan["owner_nonce"])
        require(identity == owner["container_id"] and owner["container_stopped_verified"] is True
                and container["State"]["Running"] is False, "Owned container stop is unverified")
    return True


def snapshot(attempt: Path, base: dict, *, alive: bool, now: int) -> dict:
    require(sha(attempt / "owner-plan.json") == base["plan_sha256"], "Owner plan changed")
    entries = sorted((read(path)["decision_index"], path.parent)
                     for path in (attempt / "model").glob("*/summary.json"))
    require(len(entries) <= base["plan"]["response_limit"] and
            [index for index, _ in entries] == list(range(len(entries))),
            "Spectator receipt boundary differs")
    if entries:
        folder = entries[-1][1]
        request, response = read(folder / "request.json"), read(folder / "response.json")
        validate_request(request)
        require(folder.name == request["request_id"] and
                read(folder / "claim.json")["request_sha256"] ==
                response["request_sha256"] == digest(request), "Unbound spectator response")
        for key in ("model", "reasoning_effort", "control_profile", "max_advance_ticks",
                    "prompt_profile", "bindings_sha256"):
            require(request.get(key) == base["condition"].get(key),
                    "Spectator model condition differs")
    return watch_snapshot(attempt, base, alive=alive, now=now)


def validate_output(attempt: Path, output: Path) -> None:
    absolute_path(output)
    require(output != attempt and attempt not in output.parents and output not in attempt.parents,
            "Publish derivatives outside original owner evidence")


def public_summary(value: dict) -> str:
    return json.dumps({"status": value["status"],
                       "decision": value["frame"]["decision"] if value["frame"] else None})
