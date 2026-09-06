"""Explicitly published campaign evidence, never a scan of private run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_PROBES = (("dev-glm-flash-20260906-b", "development_glm_flash_20260906.json"),)
PUBLIC_FIELDS = (
    "evidence_id",
    "phase",
    "code_revision",
    "model",
    "config_path",
    "outcome",
    "terminal_code",
    "native_elapsed_ticks",
    "last_observed_population",
    "action_rows",
    "reported_model_cost_usd",
    "reported_total_tokens",
    "dispatches",
    "returned_responses",
    "dispatches_without_returned_usage",
    "billing_reconciled",
    "cleanup_verified",
    "campaign_recovery_verified",
    "year_two_gameplay_verified",
    "source_sha256",
    "limits",
    "action_diagnostic",
    "provider_diagnostic",
    "source_snapshot_receipt_sha256",
)


def campaign_catalog(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Return only explicit evidence selected for the public website.

    No registry mutation, private directory globbing, model calls, or inferred
    leaderboard eligibility. Missing published evidence fails instead of becoming
    an empty successful experiment field.
    """
    config_path = "experiments/campaigns/development_probe_v1.json"
    config = json.loads((root / config_path).read_text())
    if config.get("schema_version") != "fortgym.development-probe/v1":
        raise ValueError("Invalid published experiment configuration")
    records = []
    for evidence_id, filename in PUBLISHED_PROBES:
        source = json.loads((root / "experiments/evidence" / filename).read_text())
        if (
            source.get("schema_version") != "fortgym.development-probe-evidence/v1"
            or source.get("evidence_id") != evidence_id
            or source.get("model") not in config["models"]
            or source.get("config_path") != config_path
        ):
            raise ValueError("Published probe does not match its declared condition")
        records.append({key: source.get(key) for key in PUBLIC_FIELDS})
    return {
        "schema_version": "fortgym.public-campaign-experiments/v1",
        "scope": "published_development_probes",
        "live_tracking_available": False,
        "comparison_rankings_available": False,
        "ticks_per_year": 403200,
        "condition": {
            "config_path": config_path,
            "hypothesis": config["hypothesis"],
            "models": config["models"],
            "max_steps": config["max_steps"],
            "max_dispatches": config["max_dispatches"],
            "reported_usage_stop_usd": config["max_cost_usd"],
            "notes": config["notes"],
        },
        "experiments": records,
    }
