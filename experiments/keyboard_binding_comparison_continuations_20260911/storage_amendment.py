"""Explicit storage-only amendment for the one unused Astra r2 continuation."""

from __future__ import annotations

import json
from pathlib import Path

from continuation_state import ROOT, read, require, sha

DECLARATION = ROOT / "experiments/keyboard_comparison_storage_amendment_20260912.json"
OPERATION = ROOT / "fort_gym/artifacts/campaign-storage-amendment-20260912/attempt/result.json"
EXPECTED_BINDING = {
    "schema_version": "fortgym.matched-window-storage-amendment/v1",
    "amendment_id": "comparison-storage-20260912-40gib",
    "campaign_id": "bindings-comparison-20260911-astra-r2",
    "first_step": 64,
    "target_next_step": 128,
    "profile": "fg-v2",
    "original_config_sha256": "ee0e3b0ced1cb0642f691959783e48c4ed45ecb182474974ae1afee84f0def93",
    "vm_config_sha256": "d5d2cc59755f2c6ad4ec95097557e8ac2fff7a27b39f636a68f3c4e002f54263",
    "operation_receipt_sha256": "c378124e57bf04f64fee50c3c2e136c2f1e2c73f1b7c0f82017857cfdf1532f9",
    "disk_gib_before": 32,
    "disk_gib_after": 40,
    "cpu": 2,
    "memory_gib": 3,
    "root_disk_gib": 8,
    "minimum_guest_free_kib": 1572864,
    "model_or_prompt_changes": False,
    "native_source_or_image_changes": False,
    "other_configuration_changes": False,
    "mandatory_teardown": True,
    "declaration_sha256": "eeb3fa8b08234819247b4dec7ecf50fda9f137fd57cabe07d1426d968d15116e",
}


def verify_binding(value: dict, campaign_id: str) -> dict:
    """Accept only these public fields and exact types; never project private extras."""
    require(
        json.dumps(value, sort_keys=True, allow_nan=False)
        == json.dumps(EXPECTED_BINDING, sort_keys=True, allow_nan=False)
        and campaign_id == EXPECTED_BINDING["campaign_id"],
        "Storage amendment differs or is not declared for this campaign",
    )
    return dict(EXPECTED_BINDING)


def load_binding(path: Path, campaign_id: str) -> dict:
    """Require explicit selection, immutable declaration and retained operation proof."""
    require(
        path.resolve(strict=True) == DECLARATION.resolve(strict=True),
        "Select the canonical storage amendment",
    )
    require(
        sha(path) == EXPECTED_BINDING["declaration_sha256"]
        and sha(OPERATION) == EXPECTED_BINDING["operation_receipt_sha256"],
        "Storage declaration or operation receipt changed",
    )
    value = dict(read(path)["storage_binding"])
    value["declaration_sha256"] = sha(path)
    return verify_binding(value, campaign_id)
