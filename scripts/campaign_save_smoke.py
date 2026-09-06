"""Provider-free native snapshot smoke against an idle, paused DF runtime.

Retain the prior on-disk save before requesting one native save. This does not
start a campaign, load a checkpoint, advance time, or establish recovery proof.
Run as the game service account from a committed scratch checkout, not production.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from fort_gym.bench.run.campaign_save import (
    CampaignSaveError,
    NativeSaveSnapshotter,
    save_inventory,
)


def require_idle_registry(registry: Path) -> None:
    with sqlite3.connect(f"{registry.resolve().as_uri()}?mode=ro", uri=True) as connection:
        active = connection.execute(
            "SELECT COUNT(*) FROM runs WHERE status IS NULL "
            "OR status NOT IN ('completed', 'failed', 'stopped')"
        ).fetchone()[0]
    if active:
        raise CampaignSaveError("Native-save smoke requires an idle run registry")


def run_smoke(
    *,
    output: Path,
    registry: Path,
    snapshotter: NativeSaveSnapshotter,
    code_revision: str,
) -> dict[str, Any]:
    require_idle_registry(registry)
    before = dict(snapshotter.status())
    boundary = snapshotter._boundary(before)
    if before.get("autosave_requested") is not False:
        raise CampaignSaveError("Another native save is pending or unknown")
    source = snapshotter.dfroot / "data" / "save" / boundary[0]
    if source.resolve() in output.resolve().parents or output.resolve() == source.resolve():
        raise CampaignSaveError("Smoke output must be outside the live save")
    original_inventory = save_inventory(source)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    shutil.copytree(source, output / "before-save", symlinks=True)
    if (
        save_inventory(output / "before-save") != original_inventory
        or save_inventory(source) != original_inventory
        or dict(snapshotter.status()) != before
    ):
        raise CampaignSaveError("Save or native state changed while preserving the prior save")
    require_idle_registry(registry)
    receipt = snapshotter.capture(output / "native-snapshot")
    after = dict(snapshotter.status())
    if snapshotter._boundary(after) != boundary or after.get("autosave_requested") is not False:
        raise CampaignSaveError("Native snapshot did not preserve the paused game boundary")
    result = {
        "schema_version": "fortgym.native-save-smoke/v1",
        "code_revision": code_revision,
        "before": before,
        "after": after,
        "prior_save_files": original_inventory,
        "snapshot": receipt,
        "native_snapshot_verified": True,
        "gameplay_ticks_requested": 0,
        "provider_calls": 0,
        "checkpoint_loaded": False,
        "campaign_recovery_verified": False,
    }
    with (output / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--dfroot", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise CampaignSaveError("Run the native smoke from a clean committed checkout")
    result = run_smoke(
        output=args.output,
        registry=args.registry,
        snapshotter=NativeSaveSnapshotter(dfroot=args.dfroot),
        code_revision=revision,
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"snapshot", "prior_save_files"}
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
