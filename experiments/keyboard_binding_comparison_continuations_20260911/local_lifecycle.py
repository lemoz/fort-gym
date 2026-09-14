"""Own one existing local VM for a bounded native window and retain every outcome."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Callable

from continuation_state import read, require, sha

START_ARGS = [
    "start",
    "--arch=aarch64",
    "--vm-type=vz",
    "--vz-rosetta",
    "--cpus=2",
    "--memory=3",
    "--root-disk=8",
    "--disk=32",
    "--runtime=docker",
    "--activate=false",
    "--ssh-config=false",
    "--ssh-agent=false",
    "--network-address=false",
    "--mount=none",
]
MINIMUM_FREE_KIB = 1536 * 1024


def verify_container(config: dict, spec: dict) -> None:
    host = config["HostConfig"]
    require(
        host["Init"] is True
        and host["PidsLimit"] == 256
        and host["NetworkMode"] == "none"
        and host["PortBindings"] == {}
        and host["Memory"] == host["MemorySwap"] == 1610612736
        and host["NanoCpus"] == 2000000000,
        "Container resource boundary differs",
    )
    require(
        config["Image"] == spec["image"]
        and config["Config"]["User"] == "dfh"
        and config["Config"]["Labels"]["fortgym.owner"] == spec["name"],
        "Container ownership or image differs",
    )
    for destination, volume, writable in (
        ("/seed-evidence", spec["source_volume"], False),
        ("/evidence", spec["volume"], True),
    ):
        matches = [row for row in config["Mounts"] if row["Destination"] == destination]
        require(
            len(matches) == 1 and matches[0]["Name"] == volume and matches[0]["RW"] is writable,
            "Container evidence mount differs",
        )


def create_arguments(spec: dict, seccomp: Path) -> list[str]:
    return [
        "create",
        "--name",
        spec["name"],
        "--init",
        "--platform=linux/amd64",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt=seccomp=" + str(seccomp),
        "--memory=1536m",
        "--memory-swap=1536m",
        "--cpus=2",
        "--pids-limit=256",
        "--label=fortgym.owner=" + spec["name"],
        "--mount=type=volume,src=" + spec["source_volume"] + ",dst=/seed-evidence,readonly",
        "--mount=type=volume,src=" + spec["volume"] + ",dst=/evidence",
        "--entrypoint=/opt/python/bin/python3.11",
        spec["image"],
        *spec["arguments"],
    ]


def cleanup(
    owner: Any, spec: dict, out: Path, result: dict, *, created: bool, started: bool
) -> None:
    """Observe each cleanup separately; an earlier error never skips owned-VM teardown."""
    docker, colima, name = owner.DOCKER, owner.COLIMA, spec["name"]
    if created:
        try:
            label = owner.output(
                docker + ["inspect", name, "--format", '{{index .Config.Labels "fortgym.owner"}}']
            )
            require(label == name, "Refusing cleanup of an unrelated container")
            for command, tag, bound in (
                (docker + ["stop", "--time=30", name], "container-stop", 45),
                (docker + ["logs", name], "container-log", 30),
                (
                    docker + ["inspect", name, "--format", "{{json .State}}"],
                    "container-final-state",
                    20,
                ),
                (docker + ["cp", name + ":/evidence", str(out / "evidence")], "evidence-copy", 120),
            ):
                try:
                    result[tag + "_returncode"] = owner.run(
                        command, tag, bound, check=False, cleanup=True
                    )
                except Exception as error:
                    result[tag + "_error_type"] = type(error).__name__
        except Exception as error:
            result["container_cleanup_error_type"] = type(error).__name__
    if started:
        try:
            result["guest_poweroff_returncode"] = owner.run(
                colima + ["ssh", "--", "sudo", "systemctl", "poweroff"],
                "guest-poweroff",
                20,
                check=False,
                cleanup=True,
            )
            for _ in range(30):
                if owner.stopped():
                    break
                time.sleep(1)
        except Exception as error:
            result["guest_poweroff_error_type"] = type(error).__name__
        finally:
            try:
                result["vm_stop_returncode"] = owner.run(
                    colima + ["stop"], "vm-stop", 90, check=False, cleanup=True
                )
                result["vm_observed_stopped"] = owner.stopped()
            except Exception as error:
                result["vm_cleanup_error_type"] = type(error).__name__


def finalize(native: Any, spec: dict, out: Path, result: dict) -> None:
    """Retain an honest result even when native output or final checks are incomplete."""
    try:
        result["vm_config_unchanged"] = sha(spec["config"]) == native.owner.CONFIG_SHA
        result["original_checkpoint_verified_unchanged"] = (
            native.verify_checkpoint(spec["origin"]["checkpoint"]) == spec["origin"]["manifest"]
        )
    except Exception as error:
        result["final_verification_error_type"] = type(error).__name__
    path = out / "evidence/astra/result.json"
    if path.is_file():
        try:
            result["native"] = read(path)
        except Exception as error:
            result["native_result_read_error_type"] = type(error).__name__
    summaries = result["model_decisions"]
    result["confirmed_model_calls"] = sum(row.get("model_dispatched") is True for row in summaries)
    claims = list((out / "model").glob("*/claim.json"))
    result["provider_calls_complete"] = len(claims) == len(summaries) and all(
        type(row.get("model_dispatched")) is bool for row in summaries
    )
    if result["provider_calls_complete"]:
        result["provider_calls"] = result["confirmed_model_calls"]
    if not any("error" in key for key in result) and result["status"] != "budget_limited_pause":
        result["status"] = "terminal_pending_audit"
    native.owner.publish(out / "result.json", result)
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "campaign_id",
                    "status",
                    "confirmed_model_calls",
                    "provider_calls_complete",
                    "vm_observed_stopped",
                    "original_checkpoint_verified_unchanged",
                )
            }
        ),
        flush=True,
    )


def execute(native: Any, spec: dict, courier: Callable) -> dict:
    """Start only after preflight; no retries, disk growth, deletion or paid fallback."""
    owner, session = native.owner, spec["session"]
    require(
        not session.exists() and owner.stopped(), "A window requires an unused path and stopped VM"
    )
    session.mkdir(mode=0o700, parents=True, exist_ok=False)
    out = session / "attempt"
    out.mkdir(mode=0o700)
    previous = Path.cwd()
    os.chdir(session)
    owner.transport.OUT = out
    owner.transport.DEADLINE = time.monotonic() + 23340 + 900
    result = {
        "schema_version": "fortgym.private-matched-window-owner/v1",
        "campaign_id": spec["origin"]["window"]["expected_campaign_id"],
        "model": spec["origin"]["condition"]["model"],
        "reasoning_effort": "medium",
        "source_revision": owner.REVISION,
        "image_id": spec["image"],
        "binding": spec["binding"],
        "first_step": 64,
        "target_next_step": 128,
        "model_decisions": [],
        "cloud_vms_created": 0,
        "reported_model_charge_usd": None,
        "hardware_energy_and_app_cost_usd": None,
        "vm_started": False,
        "status": "failed",
        "provider_calls": None,
        "native_result_audited": False,
    }
    created = started = False
    prior_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        owner.publish(out / "launch.json", result)
        admission = owner.read_allowance(Path("/opt/homebrew/bin/codex"), maximum_used_percent=98)
        owner.publish(out / "subscription-admission.json", admission)
        if admission["allowed"] is not True:
            result.update(status="budget_limited_pause", provider_calls=0)
            return result
        for sig in prior_signals:
            signal.signal(sig, owner.transport.interrupted)
        started = result["vm_started"] = True
        owner.run(owner.COLIMA + START_ARGS, "vm-start", 480)
        require(owner.output(owner.DOCKER + ["ps", "-q"]) == "", "Another game is already running")
        require(
            spec["name"]
            not in owner.output(owner.DOCKER + ["ps", "-a", "--format", "{{.Names}}"]).splitlines(),
            "Never relaunch an existing container",
        )
        volumes = owner.output(
            owner.DOCKER + ["volume", "ls", "--format", "{{.Name}}"]
        ).splitlines()
        require(
            spec["source_volume"] in volumes and spec["volume"] not in volumes,
            "Own-save source missing or output volume already used",
        )
        disk = owner.output(owner.COLIMA + ["ssh", "--", "df", "-Pk", "/var/lib/docker"])
        owner.publish(out / "data-disk-before.json", {"df_pk": disk})
        require(
            int(disk.splitlines()[-1].split()[3]) >= MINIMUM_FREE_KIB,
            "Retained evidence leaves insufficient guest capacity",
        )
        image = json.loads(owner.output(owner.DOCKER + ["image", "inspect", spec["image"]]))[0]
        require(
            image["Id"] == spec["image"]
            and image["Architecture"] == "amd64"
            and image["Config"]["User"] == "dfh",
            "Frozen native image differs",
        )
        owner.publish(session / "execution.json", spec["binding"])
        created = True
        owner.run(owner.DOCKER + create_arguments(spec, spec["seccomp"]), "container-create", 120)
        observed = json.loads(owner.output(owner.DOCKER + ["inspect", spec["name"]]))[0]
        owner.publish(out / "container-config.json", observed)
        verify_container(observed, spec)
        with (out / "launch-archive.log").open("xb") as log:
            copied = subprocess.run(
                owner.DOCKER + ["cp", "-", spec["name"] + ":/"],
                input=spec["archive"],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=owner.transport.VM_ENV,
                timeout=30,
            )
        require(copied.returncode == 0, "Launch archive delivery failed")
        owner.run(owner.DOCKER + ["start", spec["name"]], "native-start", 30)
        courier(
            native, spec["origin"], name=spec["name"], out=out, decisions=result["model_decisions"]
        )
        state = json.loads(
            owner.output(owner.DOCKER + ["inspect", spec["name"], "--format", "{{json .State}}"])
        )
        require(
            state["Running"] is False and state["ExitCode"] == 0, "Native window did not settle"
        )
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        try:
            cleanup(owner, spec, out, result, created=created, started=started)
            finalize(native, spec, out, result)
        finally:
            for sig, handler in prior_signals.items():
                signal.signal(sig, handler)
            os.chdir(previous)
    return result
