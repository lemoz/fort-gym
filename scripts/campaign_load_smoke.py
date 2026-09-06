"""Load a verified native snapshot in a disposable process on an existing host.

Copies a small, explicit runtime file set, never modifies the source installation,
and never sends load-save until the RPC server identifies the copied runtime path.
No provider calls or gameplay advancement. Retains evidence and terminates its
own process group; this is native-load proof, not complete campaign continuation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from fort_gym.bench.dfhack_exec import _strip_ansi
from fort_gym.bench.run.campaign_save import CampaignSaveError, save_inventory

RUNTIME_DIRECTORIES = ("libs", "hack", "raw", "data", "stonesense", "sdl", "hook", "dfhack-config")
RUNTIME_FILES = ("df", "dfhack", "dfhack-run")
STATUS_LUA = """
local j=require('json')
local loaded=dfhack.isMapLoaded()
print(j.encode({
    dfroot=dfhack.getDFPath(), map_loaded=loaded,
    paused=df.global.pause_state, year=df.global.cur_year,
    year_tick=df.global.cur_year_tick,
    save_name=loaded and df.global.world.cur_savegame.save_dir or '',
}))
"""


def verify_snapshot(directory: Path, expected_digest: str) -> dict[str, Any]:
    result_path = directory / "result.json"
    if result_path.is_symlink() or not result_path.is_file():
        raise CampaignSaveError("Snapshot receipt must be a regular file")
    data = result_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise CampaignSaveError("Snapshot receipt digest mismatch")
    result = json.loads(data)
    if (
        result.get("schema_version") != "fortgym.native-save-smoke/v1"
        or result.get("native_snapshot_verified") is not True
        or result.get("before") != result.get("after")
        or result.get("after", {}).get("paused") is not True
        or save_inventory(directory / "native-snapshot") != result.get("snapshot", {}).get("files")
    ):
        raise CampaignSaveError("Snapshot receipt or retained save is inconsistent")
    return result


def prepare_runtime(source: Path, destination: Path, snapshot: Path, *, port: int) -> None:
    if not 1024 <= port <= 65535 or port == 5000:
        raise CampaignSaveError("Use a dedicated non-production unprivileged RPC port")
    if (
        source.resolve() in destination.resolve().parents
        or source.resolve() == destination.resolve()
    ):
        raise CampaignSaveError("Isolated runtime must be outside the source installation")
    if destination.exists() or destination.is_symlink():
        raise CampaignSaveError("Isolated runtime destination already exists")
    if "[PAUSE_ON_LOAD:YES]" not in (source / "data/init/d_init.txt").read_text():
        raise CampaignSaveError("Source game must already be configured to pause on load")
    destination.mkdir(mode=0o700)
    for name in RUNTIME_FILES:
        shutil.copy2(source / name, destination / name)
    for name in RUNTIME_DIRECTORIES:
        if not (source / name).is_dir():
            continue

        def exclude(path, names):
            if Path(path) == source / "data":
                return set(names) & {"save"}
            return set()

        shutil.copytree(source / name, destination / name, ignore=exclude)
    config = destination / "dfhack-config/remote-server.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({"allow_remote": False, "port": port}) + "\n")
    saves = destination / "data/save"
    saves.mkdir(exist_ok=False)
    shutil.copytree(snapshot, saves / "campaign-resume")
    if save_inventory(saves / "campaign-resume") != save_inventory(snapshot):
        raise CampaignSaveError("Prepared save does not match the retained snapshot")


def runtime_environment(port: int) -> dict[str, str]:
    # Keep the existing user HOME unchanged, but never inherit provider credentials,
    # preload overrides, production DB paths, or experiment state into the runtime.
    environment = {key: os.environ[key] for key in ("HOME", "LANG", "LC_ALL") if key in os.environ}
    environment.update(
        PATH=os.defpath,
        TERM="xterm-256color",
        DFHACK_PORT=str(port),
        DFHACK_HEADLESS="1",
        DFHACK_DISABLE_CONSOLE="1",
        SDL_VIDEODRIVER="dummy",
    )
    return environment


def rpc(runtime: Path, environment: dict[str, str], command: str, *args: str) -> str:
    return subprocess.check_output(
        [
            "script",
            "-q",
            "-c",
            shlex.join([str(runtime / "dfhack-run"), command, *args]),
            "/dev/null",
        ],
        cwd=runtime,
        env=environment,
        text=True,
        stderr=subprocess.STDOUT,
        timeout=5,
    ).strip()


def read_status(runtime: Path, environment: dict[str, str]) -> dict[str, Any]:
    result = json.loads(_strip_ansi(rpc(runtime, environment, "lua", STATUS_LUA)).strip())
    if Path(result.get("dfroot", "")).resolve() != runtime.resolve():
        raise CampaignSaveError("RPC endpoint belongs to a different runtime; refusing commands")
    return result


def wait_status(runtime, environment, process, *, loaded, timeout=90):
    deadline = time.monotonic() + timeout
    last_error = "no matching state observed"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CampaignSaveError("Isolated game exited before the expected native state")
        try:
            status = read_status(runtime, environment)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as error:
            last_error = str(error)[:2000]
            time.sleep(0.2)
            continue
        if status.get("map_loaded") is loaded:
            return status
        time.sleep(0.2)
    raise CampaignSaveError(f"Isolated runtime readiness timed out: {last_error}")


def runtime_live_members(runtime: Path) -> dict[int, str]:
    """Find this new runtime's processes, including DF's separate PTY session.

    Scope is the current UID and the exact newly-created runtime working directory
    or an executable inside that runtime. Start times protect later PID signalling.
    """
    if not Path("/proc/self/stat").exists():
        raise CampaignSaveError("Native load smoke requires Linux process inspection")
    members = {}
    root = runtime.resolve()
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            if path.parent.stat().st_uid != os.getuid():
                continue
            fields = path.read_text().rpartition(") ")[2].split()
            cwd = (path.parent / "cwd").resolve(strict=True)
            executable = (path.parent / "exe").resolve(strict=True)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if fields[0] not in {"Z", "X"} and (cwd == root or root in executable.parents):
            members[int(path.parent.name)] = fields[19]
    return members


def signal_runtime_members(runtime: Path, requested_signal: int) -> None:
    for pid, start_time in runtime_live_members(runtime).items():
        if runtime_live_members(runtime).get(pid) == start_time:
            try:
                os.kill(pid, requested_signal)
            except ProcessLookupError:
                pass


def run_smoke(*, source: Path, snapshot: Path, digest: str, output: Path, port: int, revision: str):
    for retained in (source, snapshot):
        if output.resolve() == retained.resolve() or retained.resolve() in output.resolve().parents:
            raise CampaignSaveError("Test output must be outside retained source and snapshot")
    receipt = verify_snapshot(snapshot, digest)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    runtime = output / "runtime"
    prepare_runtime(source, runtime, snapshot / "native-snapshot", port=port)
    environment = runtime_environment(port)
    result: dict[str, Any] = {
        "schema_version": "fortgym.native-load-smoke/v1",
        "code_revision": revision,
        "source_snapshot_receipt_sha256": digest,
        "port": port,
        "runtime_path": str(runtime.resolve()),
        "native_load_verified": False,
        "campaign_recovery_verified": False,
        "provider_calls": 0,
        "gameplay_ticks_requested": 0,
        "cleanup_verified": False,
    }
    with (output / "runtime.log").open("xb") as log:
        process = subprocess.Popen(
            ["script", "-qefc", shlex.quote(str(runtime / "dfhack")), "/dev/null"],
            cwd=runtime,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        result["launcher_pid"] = process.pid
        try:
            initial = wait_status(runtime, environment, process, loaded=False)
            result["initial"] = initial
            rpc(runtime, environment, "load-save", "campaign-resume")
            loaded = wait_status(runtime, environment, process, loaded=True)
            result["loaded"] = loaded
            expected = receipt["after"]
            if (
                loaded.get("save_name") != "campaign-resume"
                or loaded.get("paused") is not True
                or (loaded.get("year"), loaded.get("year_tick"))
                != (expected["year"], expected["year_tick"])
            ):
                raise CampaignSaveError("Loaded fortress does not match the saved paused calendar")
            verify_snapshot(snapshot, digest)
            result["native_load_verified"] = True
        except Exception as error:
            result["error_type"] = type(error).__name__
            result["error"] = str(error)
            raise
        finally:
            # The launcher started a new process group owned solely by this test.
            # util-linux script creates another PTY session for DF, so also target
            # processes bound to this exact new runtime path and UID.
            signal_runtime_members(runtime, signal.SIGTERM)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            cleanup_deadline = time.monotonic() + 5
            while runtime_live_members(runtime) and time.monotonic() < cleanup_deadline:
                time.sleep(0.1)
            if runtime_live_members(runtime):
                signal_runtime_members(runtime, signal.SIGKILL)
            cleanup_deadline = time.monotonic() + 5
            while runtime_live_members(runtime) and time.monotonic() < cleanup_deadline:
                time.sleep(0.1)
            listener_deadline = time.monotonic() + 5
            while True:
                result["remaining_live_processes"] = sorted(runtime_live_members(runtime))
                with socket.socket() as probe:
                    result["listener_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
                if (
                    result["listener_closed"] and not result["remaining_live_processes"]
                ) or time.monotonic() >= listener_deadline:
                    break
                time.sleep(0.1)
            result["cleanup_verified"] = (
                result["listener_closed"] and not result["remaining_live_processes"]
            )
            with (output / "result.json").open("x") as handle:
                json.dump(result, handle, indent=2, allow_nan=False)
                handle.write("\n")
    if not result["cleanup_verified"]:
        raise CampaignSaveError("Test listener still present after process teardown")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise CampaignSaveError("Run native loading from a clean committed checkout")
    result = run_smoke(
        source=args.source,
        snapshot=args.snapshot,
        digest=args.snapshot_sha256,
        output=args.output,
        port=args.port,
        revision=revision,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
