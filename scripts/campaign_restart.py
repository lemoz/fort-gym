"""One-use restart of a torn-down runtime at its exact latest saved boundary.

No save replacement, runtime copy, deletion, provider client or historical replay.
The caller still owns authorization, a clean source checkout and worker bounds.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import shutil
import socket
import stat
import time
from pathlib import Path
from typing import Any

from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_save import CampaignSaveError, save_inventory
from scripts.campaign_load_smoke import (
    _run_prepared_runtime,
    runtime_environment,
    runtime_live_members,
    verify_load_source,
)


def _owned(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid() or path.resolve() != path:
        raise CampaignSaveError("Restart paths must be regular, current-user-owned and non-link")


def _wait_for_restart_port(runtime: Path, port: int, *, timeout_seconds: float = 90) -> None:
    """Allow a closed TCP port to settle, without retrying any game operation."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if runtime_live_members(runtime):
            raise CampaignSaveError("Previous runtime still has live processes")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return
            except OSError as error:
                if error.errno != errno.EADDRINUSE:
                    raise
        # A live listener is a different condition from delayed TCP port reuse.
        # Never wait through or displace another service taking this endpoint.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CampaignSaveError("Closed restart port did not become bindable before timeout")
        with socket.socket() as probe:
            probe.settimeout(min(1, remaining))
            if probe.connect_ex(("127.0.0.1", port)) != errno.ECONNREFUSED:
                raise CampaignSaveError("Restart port has a listener or unknown connectivity")
        if time.monotonic() >= deadline:
            raise CampaignSaveError("Closed restart port did not become bindable before timeout")
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))


def restart_latest_checkpoint(
    *,
    previous_output: Path,
    previous_receipt_sha256: str,
    checkpoint_sha256: str,
    output: Path,
    revision: str,
    minimum_free_bytes: int,
    growth_allowance_bytes: int = 1048576,
    work=None,
) -> dict[str, Any]:
    """Restart once without replacing files; retain the claim even if launch fails.

    Only a sibling output and the previous runtime's own checkpoint are accepted.
    The same non-production port is reused, with a fresh bind check and no native
    process allowed before restart. An exclusive receipt lock serializes callers;
    a durable exclusive claim prevents a second use after the lock is released.
    """
    for value in (minimum_free_bytes, growth_allowance_bytes):
        if type(value) is not int or value < 0:
            raise CampaignSaveError("Restart disk limits must be nonnegative integers")
    previous_output, output = previous_output.absolute(), output.absolute()
    _owned(previous_output, directory=True)
    _owned(previous_output.parent, directory=True)
    if output.parent != previous_output.parent or output == previous_output:
        raise CampaignSaveError("Restart output must be a new sibling of the previous output")
    if output.exists() or output.is_symlink():
        raise CampaignSaveError("Restart output already exists")
    receipt = previous_output / "result.json"
    _owned(receipt, directory=False)
    descriptor = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as locked:
        try:
            fcntl.flock(locked.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CampaignSaveError("Another caller owns this runtime restart") from error
        data = locked.read()
        if hashlib.sha256(data).hexdigest() != previous_receipt_sha256:
            raise CampaignSaveError("Previous runtime receipt digest mismatch")
        prior = json.loads(data)
        runtime = previous_output / "runtime"
        port = prior.get("port")
        if (
            prior.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
            or prior.get("cleanup_verified") is not True
            or prior.get("native_load_verified") is not True
            or prior.get("listener_closed") is not True
            or prior.get("remaining_live_processes") != []
            or "error" in prior
            or "error_type" in prior
            or not isinstance(prior.get("experiment"), dict)
            or prior.get("runtime_path") != str(runtime)
            or prior.get("code_revision") != revision
            or type(port) is not int
            or not 1024 <= port <= 65535
            or port == 5000
        ):
            raise CampaignSaveError("Previous runtime lacks matching successful teardown evidence")
        for path in (runtime, runtime / "data", runtime / "data/save"):
            _owned(path, directory=True)
        checkpoint = previous_output / "checkpoint"
        _owned(checkpoint, directory=True)
        _, expected = verify_load_source(checkpoint, checkpoint_sha256, "campaign_checkpoint")
        if verify_checkpoint(checkpoint)["payload"].get("code_revision") != revision:
            raise CampaignSaveError("Checkpoint code revision differs from the restart")

        def verify_saved_bytes() -> None:
            verify_load_source(checkpoint, checkpoint_sha256, "campaign_checkpoint")
            if save_inventory(runtime / "data/save/campaign-resume") != expected["files"]:
                raise CampaignSaveError("Runtime save differs from its latest checkpoint")

        verify_saved_bytes()
        _wait_for_restart_port(runtime, port)
        available = shutil.disk_usage(output.parent).free
        if available - growth_allowance_bytes < minimum_free_bytes:
            raise CampaignSaveError("Restart allowance would cross the declared free-space floor")
        claim = previous_output / "restart-claim.json"
        claim_data = {
            "schema_version": "fortgym.latest-checkpoint-restart-claim/v1",
            "previous_receipt_sha256": previous_receipt_sha256,
            "checkpoint_file_sha256": checkpoint_sha256,
            "output": str(output),
            "code_revision": revision,
        }
        try:
            claim_descriptor = os.open(
                claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError as error:
            raise CampaignSaveError("This runtime restart has already been claimed") from error
        with os.fdopen(claim_descriptor, "w") as stream:
            json.dump(claim_data, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        parent_descriptor = os.open(previous_output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        output.mkdir(mode=0o700)
        result = {
            "schema_version": "fortgym.latest-checkpoint-restart/v1",
            "code_revision": revision,
            "previous_receipt_sha256": previous_receipt_sha256,
            "source_checkpoint_file_sha256": checkpoint_sha256,
            "runtime_path": str(runtime),
            "runtime_reused_without_save_replacement": True,
            "port": port,
            "native_load_verified": False,
            "campaign_recovery_verified": False,
            "cleanup_verified": False,
            "capacity_preflight": {
                "available_bytes": available,
                "minimum_free_bytes": minimum_free_bytes,
                "growth_allowance_bytes": growth_allowance_bytes,
                "space_reserved": False,
                "future_growth_bounded": False,
                "runtime_copy_bytes": 0,
            },
        }
        return _run_prepared_runtime(
            runtime=runtime,
            output=output,
            environment=runtime_environment(port),
            expected=expected,
            result=result,
            validate_source=lambda: verify_load_source(
                checkpoint, checkpoint_sha256, "campaign_checkpoint"
            ),
            validate_runtime=verify_saved_bytes,
            work=work,
        )
