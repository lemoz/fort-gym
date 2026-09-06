"""Explicit, versioned terminal snapshots alongside optional live reporting."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..eval.campaign_public import parse_update_time, public_snapshot
from ..run.campaign_feed import MAX_BYTES, MAX_RECORDS, read_feed

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Only deliberately published bundles belong here, never private artifact scans.
PUBLISHED_BUNDLES = (
    "local_native_packed_comparison_20260906.json",
    "local_native_harness_repair_20260906.json",
    "local_native_workshop_ground_20260906.json",
)


def published_records(root: Path = PROJECT_ROOT) -> list[dict]:
    records = []
    seen = set()
    for filename in PUBLISHED_BUNDLES:
        path = root / "experiments/evidence" / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError("Published campaign bundle must be a bounded regular file")
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError("Published campaign bundle exceeds its byte limit")
        bundle = json.loads(raw)
        if (
            not isinstance(bundle, dict)
            or bundle.get("schema_version") != "fortgym.published-campaign-bundle/v1"
        ):
            raise ValueError("Unsupported published campaign bundle")
        config = bundle["configuration"]
        if not isinstance(config, dict) or not isinstance(config.get("models"), list):
            raise ValueError("Invalid published campaign configuration")
        receipt = bundle.get("source_snapshot_receipt_sha256")
        if not isinstance(receipt, str) or re.fullmatch(r"[a-f0-9]{64}", receipt) is None:
            raise ValueError("Published comparison requires its starting-save receipt digest")
        digest = hashlib.sha256(
            json.dumps(config, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        snapshots = bundle["campaigns"]
        if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= MAX_RECORDS:
            raise ValueError("Invalid published campaign count")
        for value in snapshots:
            if not isinstance(value, dict):
                raise ValueError("Invalid published campaign snapshot")
            record = public_snapshot(value)
            identity = record["campaign_id"]
            if (
                identity in seen
                or record["lifecycle"] != "finished"
                or record["cleanup_verified"] is not True
                or record["condition_id"] != config["condition_id"]
                or record["configuration_sha256"] != digest
                or record["model"] not in config["models"]
            ):
                raise ValueError("Published campaign identity, condition or teardown is invalid")
            seen.add(identity)
            records.append(
                {
                    **record,
                    "freshness": "recorded",
                    "publication": "versioned_snapshot",
                    "declared_starting_snapshot_receipt_sha256": receipt,
                }
            )
    if len(records) > MAX_RECORDS:
        raise ValueError("Published campaigns exceed their record bound")
    return records


def campaign_feed(live_root: Path | None, *, project_root: Path = PROJECT_ROOT) -> dict:
    # A broken configured live source still fails; published data cannot hide it.
    response = read_feed(live_root)
    published = published_records(project_root)
    merged = {record["campaign_id"]: record for record in published}
    for live in response["campaigns"]:
        previous = merged.get(live["campaign_id"])
        if previous is not None:
            if any(
                live[key] != previous[key]
                for key in ("model", "condition_id", "configuration_sha256", "code_revision")
            ):
                raise ValueError("Live and published campaign identities disagree")
            if parse_update_time(live["updated_at"]) <= parse_update_time(previous["updated_at"]):
                continue
        merged[live["campaign_id"]] = live
    if len(merged) > MAX_RECORDS:
        raise ValueError("Combined campaign feed exceeds its record bound")
    response.update(
        campaigns=sorted(merged.values(), key=lambda item: item["updated_at"], reverse=True),
        published_snapshots=len(published),
    )
    return response
