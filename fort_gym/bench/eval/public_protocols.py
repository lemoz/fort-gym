"""Public-safe Fort-Eval protocol catalog.

The Easy entry intentionally exposes only published manifest metadata. It does
not expose prompts, held-out material, or operational run configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PublicProtocolDefinition:
    """Public metadata suitable for the protocol index and detail pages."""

    slug: str
    name: str
    profile: str
    profile_version: str
    status: str
    result_status: str
    summary: str
    interface: dict[str, str]
    actions: list[str]
    observation_bounds: dict[str, str]
    knowledge: dict[str, str]
    observer_firewall: str
    comparability_fields: list[str]
    comparability_defaults: dict[str, str]
    ranking: str
    pilot_state: str
    requires_public_eligibility: bool = False

    def to_public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result.pop("comparability_defaults")
        result.pop("requires_public_eligibility")
        return result


def _manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "experiments" / "fort_eval_easy_v1.yaml"


def _p1_manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "experiments"
        / "fort_eval_easy_p1_g7_v3.yaml"
    )


def _required_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Easy protocol manifest is missing mapping: {key}")
    return value


def _easy_protocol() -> PublicProtocolDefinition:
    with _manifest_path().open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if not isinstance(manifest, dict):
        raise RuntimeError("Easy protocol manifest must be a mapping")

    program = _required_mapping(manifest, "program")
    interface = _required_mapping(manifest, "interface")
    actions = _required_mapping(manifest, "actions")
    knowledge = _required_mapping(manifest, "knowledge")
    comparability = _required_mapping(manifest, "comparability")
    ranking = _required_mapping(manifest, "ranking")
    pilot = _required_mapping(manifest, "staged_pilot")
    current_repo_truth = _required_mapping(program, "current_repo_truth")
    copy_screen = _required_mapping(current_repo_truth, "copy_screen_text")
    minimap = _required_mapping(current_repo_truth, "fort_minimap")
    focused_maps = _required_mapping(current_repo_truth, "focused_access_maps")
    observer_snapshot = _required_mapping(current_repo_truth, "observer_snapshot")

    action_names = actions.get("legal_semantic_dfhack")
    comparison_fields = comparability.get("fields")
    if not isinstance(action_names, list) or not all(isinstance(item, str) for item in action_names):
        raise RuntimeError("Easy protocol manifest has invalid legal actions")
    if not isinstance(comparison_fields, dict):
        raise RuntimeError("Easy protocol manifest has invalid comparability fields")

    return PublicProtocolDefinition(
        slug="fort-eval-easy-v1",
        name="Fort-Eval Easy",
        profile=str(program["profile"]),
        profile_version=str(program["profile_version"]),
        status=str(manifest["status"]),
        result_status="Provisional P0/substrate results only; no ranked results.",
        summary=(
            "Provisional P0/substrate pilot using governed structured state and bounded "
            "legal semantic DFHack controls."
        ),
        interface={
            "observation": str(interface["agent_observation_profile"]),
            "actions": str(interface["agent_action_profile"]),
        },
        actions=action_names,
        observation_bounds={
            "copy_screen_text": f"{copy_screen['width']}x{copy_screen['height']}",
            "fort_minimap": f"up to {minimap['max_width']}x{minimap['max_height']}",
            "focused_access_maps": (
                f"up to {focused_maps['max_width']}x{focused_maps['max_height']} per focused level"
            ),
            "observer_snapshot": (
                f"up to {observer_snapshot['max_width']}x{observer_snapshot['max_height']}; "
                "observer-only by default"
            ),
        },
        knowledge={
            "condition": str(knowledge["condition"]),
            "documents": "not allowed",
            "live_web": "not allowed",
        },
        observer_firewall=(
            "Observer snapshots are evidence surfaces and are not agent input without an "
            "explicit declared override."
        ),
        comparability_fields=list(comparison_fields),
        comparability_defaults={key: str(value) for key, value in comparison_fields.items()},
        ranking=(
            f"{ranking['status']}; ranked seed split and resolved provenance are required "
            "before ranking."
        ),
        pilot_state=f"{pilot['stage']} now; {pilot['next_stage']} next.",
    )


def _p1_protocol() -> PublicProtocolDefinition:
    with _p1_manifest_path().open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if not isinstance(manifest, dict):
        raise RuntimeError("P1 protocol manifest must be a mapping")

    program = _required_mapping(manifest, "program")
    task = _required_mapping(manifest, "task")
    condition = _required_mapping(manifest, "benchmark_condition")
    observation = _required_mapping(condition, "observation")
    action = _required_mapping(condition, "action")
    knowledge = _required_mapping(condition, "knowledge")
    memory = _required_mapping(condition, "memory")
    budget = _required_mapping(condition, "budget")

    return PublicProtocolDefinition(
        slug=str(manifest["manifest_id"]),
        name=str(manifest["name"]),
        profile=str(program["profile"]),
        profile_version=str(program["profile_version"]),
        status=str(manifest["status"]),
        result_status=(
            "Provisional P1 fixed-seed results. Eligible completed runs report "
            "G7 pass, fail, or unknown outcomes; no ranked results."
        ),
        summary=str(manifest["description"]),
        interface={
            "observation": str(observation["profile"]),
            "actions": str(action["profile"]),
        },
        actions=["legal semantic DFHack actions"],
        observation_bounds={
            "vision": "enabled" if observation.get("vision_enabled") else "disabled",
            "budget": (
                f"{budget['max_steps']} steps; {budget['ticks_per_step']} ticks per step; "
                f"{budget['max_ticks']} ticks maximum"
            ),
        },
        knowledge={
            "condition": str(knowledge["condition"]),
            "documents": "allowed" if knowledge.get("documents_allowed") else "not allowed",
            "live_web": "allowed" if knowledge.get("live_web_allowed") else "not allowed",
        },
        observer_firewall="Observer maps remain outside agent input.",
        comparability_fields=[
            "task_id",
            "task_version",
            "seed_split",
            "mechanics_digest",
            "observation_digest",
            "action_digest",
            "budget_digest",
            "model_digest",
            "prompt_digest",
            "memory_digest",
            "fort_gym_commit",
            "df_version",
            "evaluator_version",
        ],
        comparability_defaults={
            "task_id": str(task["task_id"]),
            "task_version": str(task["task_version"]),
            "seed_split": str(task["seed_split"]),
            "mechanics_digest": "df-51.11+governed-semantic-dfhack-v1",
            "observation_digest": "governed_structured_state_v1+fort_minimap_vision_v1",
            "action_digest": str(action["profile"]),
            "budget_digest": (
                f"max_steps_{budget['max_steps']}_ticks_per_step_{budget['ticks_per_step']}"
            ),
            "model_digest": "resolved_at_run",
            "prompt_digest": "resolved_at_run",
            "memory_digest": "memory_off" if memory.get("mode") == "off" else str(memory["mode"]),
            "fort_gym_commit": "resolved_at_run",
            "df_version": "df-51.11",
            "evaluator_version": "score-v5+g7-v3",
        },
        ranking="Provisional only; P1 does not establish a model ranking.",
        pilot_state="P1 Easy fixed-seed discovery; P0 substrate remains separately published.",
        requires_public_eligibility=True,
    )


def _future_protocols() -> tuple[PublicProtocolDefinition, PublicProtocolDefinition]:
    hard = PublicProtocolDefinition(
        slug="fort-eval-hard-v1",
        name="Fort-Eval Hard",
        profile="hard",
        profile_version="hard-v1",
        status="planned",
        result_status="No results. Planned future profile.",
        summary=(
            "Planned fixed-pixel and primitive-input profile for active perception, navigation, "
            "spatial memory, and z-level reasoning."
        ),
        interface={
            "observation": "fixed-pixel viewport with a declared capture policy",
            "actions": "primitive human inputs only",
        },
        actions=["directional movement", "selection", "confirmation", "cancel"],
        observation_bounds={
            "viewport": "fixed dimensions and capture policy must be declared before ranking",
            "timing": "pause semantics and action timing are part of comparability",
        },
        knowledge={"condition": "declared per run", "documents": "declared per run", "live_web": "declared per run"},
        observer_firewall="Observer evidence must remain outside agent inputs unless explicitly declared.",
        comparability_fields=[
            "viewport",
            "capture_policy",
            "input_primitives",
            "pause_timing_policy",
            "knowledge_condition",
        ],
        comparability_defaults={},
        ranking="No ranking until the interface and comparability key are frozen.",
        pilot_state="Planned after Easy validation.",
    )
    discovery = PublicProtocolDefinition(
        slug="fort-eval-discovery-v1",
        name="Fort-Eval Discovery",
        profile="discovery",
        profile_version="discovery-v1",
        status="research_horizon",
        result_status="No results. Research-horizon profile.",
        summary=(
            "Research horizon for transfer and discovery on the future Hard interface under "
            "controlled information limits."
        ),
        interface={
            "observation": "future Hard fixed-pixel interface",
            "actions": "future Hard primitive human inputs",
        },
        actions=["future Hard primitive input set"],
        observation_bounds={
            "learner_state": "bounded cross-episode state with logged read and write events",
            "held_out_material": "not exposed through agent, observer, or retry paths",
        },
        knowledge={"condition": "none", "documents": "not allowed", "live_web": "not allowed"},
        observer_firewall="Observer evidence and held-out material must not reach agent context or retries.",
        comparability_fields=[
            "hard_interface_digest",
            "knowledge_condition",
            "learner_state_budget",
            "seed_split",
            "mechanics_split",
        ],
        comparability_defaults={},
        ranking="No ranking until Hard is stable and the held-out protocol is frozen.",
        pilot_state="Research horizon; no active pilot.",
    )
    return hard, discovery


@lru_cache(maxsize=1)
def _catalog() -> dict[str, PublicProtocolDefinition]:
    easy = _easy_protocol()
    p1 = _p1_protocol()
    hard, discovery = _future_protocols()
    return {entry.slug: entry for entry in (easy, p1, hard, discovery)}


def list_public_protocols() -> list[PublicProtocolDefinition]:
    """Return the fixed, public-safe protocol allowlist."""

    return list(_catalog().values())


def get_public_protocol(slug: str) -> PublicProtocolDefinition | None:
    """Look up a public protocol without exposing non-allowlisted metadata."""

    return _catalog().get(slug)


__all__ = ["PublicProtocolDefinition", "get_public_protocol", "list_public_protocols"]
