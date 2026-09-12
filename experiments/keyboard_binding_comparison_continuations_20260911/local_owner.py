"""Run one declared matched own-save 64-to-128 window on the existing local VM."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from typing import Any

from continuation_state import (
    BASE,
    FRESH,
    ROOT,
    REVISION,
    inspect_origin,
    load_native,
    read,
    require,
    sha,
)
from local_lifecycle import MINIMUM_FREE_KIB, execute
from window_courier import serve

SOURCE_BRANCH = "codex/displayed-key-owner"
INDEX = "experiments/evidence/keyboard_binding_comparison_20260911_index.json"
NATIVE_CI = "34619202196"


def native_arguments(condition_name: str) -> list[str]:
    parent = "/seed-evidence/astra/segment-0/"
    return [
        "-m",
        "scripts.campaign_keyboard_native",
        "run",
        "--condition",
        "/launch/" + condition_name,
        "--window",
        "/launch/window.json",
        "--source",
        "/opt/dwarf-fortress",
        "--checkpoint",
        parent + "checkpoint",
        "--latest-usage",
        parent + "loop/usage.jsonl",
        "--output",
        "/evidence/astra",
        "--port",
        "5615",
        "--revision",
        REVISION,
    ]


def launch_archive(condition_path: Path, window_path: Path) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        directory = tarfile.TarInfo("launch")
        directory.type, directory.mode = tarfile.DIRTYPE, 0o755
        archive.addfile(directory)
        for name, path in ((condition_path.name, condition_path), ("window.json", window_path)):
            data = path.read_bytes()
            entry = tarfile.TarInfo("launch/" + name)
            entry.mode, entry.size = 0o444, len(data)
            archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def specification(native: Any, origin: dict, window_path: Path, revision: str) -> dict:
    window, owner = origin["window"], native.owner
    identity = window["expected_campaign_id"]
    # Identity was validated by the shared preparation reader, before forming paths.
    require(
        re.fullmatch(r"bindings-comparison-20260911-(sol|terra|astra)-r[12]", identity) is not None,
        "Unknown matched campaign",
    )
    name = "fort-gym-" + identity + "-64-128"
    source_volume = "fort-gym-" + identity + "-evidence"
    condition_path = FRESH / window["original_condition"]
    archive = launch_archive(condition_path, window_path)
    config = owner.transport.APP / "fg-v2/colima.yaml"
    seccomp = owner.RUNTIME.parent / "seccomp-moby27-dfhack.json"
    require(
        sha(config) == owner.CONFIG_SHA and sha(seccomp) == owner.SECCOMP_SHA,
        "Existing VM configuration or seccomp changed",
    )
    parent_config = read(origin["checkpoint"].parents[3] / "container-config.json")
    parent_mounts = [row for row in parent_config["Mounts"] if row["Destination"] == "/evidence"]
    require(
        len(parent_mounts) == 1
        and parent_mounts[0]["Name"] == source_volume
        and parent_config["Image"] == owner.IMAGE,
        "Parent evidence volume differs",
    )
    binding = {
        "schema_version": "fortgym.private-matched-window-execution/v1",
        "campaign_id": identity,
        "declaration_revision": revision,
        "source_revision": REVISION,
        "image_id": owner.IMAGE,
        "window_sha256": sha(window_path),
        "condition_sha256": sha(condition_path),
        "parent_checkpoint_sha256": origin["manifest"]["sha256"],
        "parent_audit_sha256": window["source_audit_sha256"],
        "parent_source_volume": source_volume,
        "output_volume": name + "-evidence",
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "source_sha256": {path.name: sha(path) for path in sorted(BASE.glob("*.py"))},
        "vm_config_sha256": owner.CONFIG_SHA,
        "seccomp_sha256": owner.SECCOMP_SHA,
        "minimum_guest_free_kib": MINIMUM_FREE_KIB,
        "maximum_live_games": 1,
        "maximum_responses_per_start": 64,
        "courier_seconds": 23340,
    }
    return {
        "origin": origin,
        "session": owner.BASE / (identity + "-64-128"),
        "name": name,
        "volume": name + "-evidence",
        "source_volume": source_volume,
        "image": owner.IMAGE,
        "config": config,
        "seccomp": seccomp,
        "arguments": native_arguments(condition_path.name),
        "archive": archive,
        "binding": binding,
    }


def verify_ci(run_id: str, revision: str) -> None:
    require(re.fullmatch(r"[0-9]+", run_id) is not None, "Supply a known CI run ID")
    result = json.loads(
        subprocess.check_output(
            [
                "gh",
                "run",
                "view",
                run_id,
                "--repo",
                "lemoz/fort-gym",
                "--json",
                "headSha,status,conclusion",
            ],
            text=True,
            timeout=30,
        )
    )
    require(
        result == {"headSha": revision, "status": "completed", "conclusion": "success"},
        "Exact declared source CI has not passed",
    )


def verify_release(native: Any, revision: str, ci_run: str) -> None:
    require(
        re.fullmatch(r"[a-f0-9]{40}", revision) is not None,
        "Supply the exact reviewed owner revision",
    )
    # The full terminal audit must exist before this owner can launch.
    require((BASE / "terminal_review.py").is_file(), "Terminal audit integration is incomplete")
    for path in sorted(BASE.iterdir()):
        if path.is_file() and path.suffix in {".py", ".json", ".md"}:
            committed = subprocess.check_output(
                ["git", "show", revision + ":" + str(path.relative_to(ROOT))], cwd=ROOT, timeout=30
            )
            require(committed == path.read_bytes(), "Owner declaration source changed")
    remote = subprocess.check_output(
        ["git", "ls-remote", "github", "refs/heads/" + SOURCE_BRANCH],
        cwd=ROOT,
        text=True,
        timeout=30,
    ).split()[0]
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, remote], cwd=ROOT, check=True, timeout=30
    )
    verify_ci(ci_run, revision)
    owner = native.owner
    native_remote = subprocess.check_output(
        ["git", "ls-remote", "github", "refs/heads/codex/campaign-dismissed-screen-restart"],
        cwd=owner.WORKTREE,
        text=True,
        timeout=30,
    ).split()[0]
    require(native_remote == REVISION, "Frozen native source changed")
    verify_ci(NATIVE_CI, REVISION)
    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-m",
                "scripts.campaign_displayed_key_comparison",
                "--index",
                INDEX,
                "--boundary",
                "64",
            ],
            cwd=ROOT,
            text=True,
            timeout=30,
        )
    )
    require(
        report["declared_attempts"] == 6 and report["all_attempts_reported"] is True,
        "Finish and report the six predeclared fresh attempts before continuation",
    )
    require(owner.stopped(), "Another local run is active")
    default_vms = owner.output(["/opt/homebrew/bin/colima", "list", "--json"], owner.transport.ENV)
    require(
        all(json.loads(line)["status"] == "Stopped" for line in default_vms.splitlines()),
        "Another local VM is active",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=Path, required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--ci-run", required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    window_path = args.window.resolve(strict=True)
    require(window_path.parent == BASE.resolve(), "Select a committed matched window")
    native = load_native()
    origin = inspect_origin(ROOT, window_path, native)
    verify_release(native, args.declaration_revision, args.ci_run)
    spec = specification(native, origin, window_path, args.declaration_revision)
    require(not spec["session"].exists(), "Never relaunch an existing window")
    if args.preflight:
        admission = native.owner.read_allowance(
            Path("/opt/homebrew/bin/codex"), maximum_used_percent=98
        )
        print(
            json.dumps(
                {
                    "preflight_passed": admission["allowed"] is True,
                    "subscription_allowed": admission["allowed"],
                    "binding": spec["binding"],
                    "vm_started": False,
                    "model_calls": 0,
                }
            )
        )
        return
    execute(native, spec, serve)


if __name__ == "__main__":
    main()
