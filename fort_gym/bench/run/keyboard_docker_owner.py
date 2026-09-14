"""Own one container on an existing local Docker engine, never the engine or VM."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from ..agent.keyboard_exchange import MAX_BYTES, digest, publish, read
from ..agent.codex_allowance import read_allowance
from .keyboard_docker_plan import (
    LABEL,
    NATIVE_OUTPUT,
    SECCOMP_SCHEMA,
    absolute_path,
    create_arguments,
    prepare_inputs,
    validate_runtime,
)
from .keyboard_seccomp import read_profile
from .keyboard_owner_process import capture_owner_process
from .keyboard_window_courier import DockerExchange, serve_fresh, serve_window


class DockerClient:
    """Record bounded command results, without shell evaluation or hidden retries."""

    def __init__(self, executable: Path, context: str, output: Path):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", context):
            raise ValueError("Select one literal existing Docker context")
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise ValueError("Docker executable must be an absolute executable file")
        self.command = [str(executable), "--context", context]
        self.context, self.output, self.sequence = context, output, 0

    def run(self, command: list[str], label: str, timeout: int = 30) -> str:
        self.sequence += 1
        stem = self.output / f"docker-{self.sequence:04d}-{label}"
        publish(stem.with_suffix(".command.json"), {"arguments": command, "timeout": timeout})
        stdout_path, stderr_path = stem.with_suffix(".log"), stem.with_suffix(".stderr.log")
        # Docker can emit a harmless platform warning on stderr while returning
        # a valid ID or JSON on stdout. Preserve diagnostics without mixing them
        # into machine-readable output or weakening exact identity validation.
        with stdout_path.open("xb") as stream, stderr_path.open("xb") as errors:
            completed = subprocess.run(
                command, stdout=stream, stderr=errors, timeout=timeout
            )
        if any(path.stat().st_size > MAX_BYTES for path in (stdout_path, stderr_path)):
            raise ValueError("Docker command output exceeds its bounded reader")
        value = stdout_path.read_text()
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, command)
        return value.strip()

    def output_command(self, command: list[str]) -> str:
        return self.run(command, "read")

    def call(self, *arguments: str, timeout: int = 30) -> str:
        return self.run(self.command + list(arguments), "command", timeout)

    def inspect(self, identity: str) -> dict:
        records = json.loads(self.call("inspect", identity))
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("Docker inspection did not resolve one container")
        return records[0]

    def preflight(self, runtime: dict) -> None:
        contexts = json.loads(self.call("context", "inspect", self.context))
        if (
            len(contexts) != 1
            or contexts[0]["Name"] != self.context
            or not contexts[0]["Endpoints"]["docker"]["Host"].startswith("unix://")
        ):
            raise ValueError("Portable owner requires an existing local Unix-socket engine")
        images = json.loads(self.call("image", "inspect", runtime["image"]))
        if (
            len(images) != 1
            or images[0].get("Id") != runtime["image"]
            or images[0].get("Os") != "linux"
            or images[0].get("Config", {}).get("Volumes")
        ):
            raise ValueError("Use the exact existing Linux image without implicit data volumes")


def owned_container(value: dict, runtime: dict, nonce: str) -> str:
    identity = value.get("Id")
    if (
        not isinstance(identity, str)
        or not re.fullmatch(r"[a-f0-9]{64}", identity)
        or value.get("Image") != runtime["image"]
        or value.get("Config", {}).get("Labels", {}).get(LABEL) != nonce
        or type(value.get("State", {}).get("Running")) is not bool
    ):
        raise ValueError("Container ownership or liveness is unverified")
    return identity


def source_inputs(args) -> dict:
    return prepare_inputs(
        args.condition, args.declaration, args.origin, args.campaign_id, mode=args.mode
    )


def run_owner(
    args,
    *,
    client_factory=DockerClient,
    fresh_server=serve_fresh,
    window_server=serve_window,
    allowance_check=read_allowance,
) -> dict:
    """Execute one attempt, retaining failures, all model receipts and owned teardown.

    This accepts ordinary fresh/unchanged-continuation declarations only. Existing
    recovery/extension launchers remain separate; none is silently rewritten.
    """
    runtime = validate_runtime(read(args.runtime))
    if (
        not args.model_executable.is_absolute()
        or not args.model_executable.is_file()
        or not os.access(args.model_executable, os.X_OK)
    ):
        raise ValueError("Model courier needs an existing absolute executable")
    inputs = source_inputs(args)
    output = absolute_path(args.output)
    if (
        not output.parent.is_dir()
        or output.exists()
        or output == args.origin
        or args.origin in output.parents
        or output in args.origin.parents
    ):
        raise ValueError("Use a new output directory outside retained native inputs")
    if shutil.disk_usage(output.parent).free < runtime["minimum_host_free_bytes"]:
        raise ValueError("Output filesystem is below the declared capacity floor")
    name, nonce = "fortgym-" + uuid.uuid4().hex, uuid.uuid4().hex
    command = create_arguments(runtime, inputs, output, args.origin, name, nonce, args.port)
    seccomp = (
        read_profile(runtime["seccomp_profile"], runtime["seccomp_sha256"])
        if runtime["schema_version"] == SECCOMP_SCHEMA else None
    )
    output.mkdir(mode=0o700)
    if seccomp is not None:
        with (output / "seccomp.json").open("xb") as stream:
            stream.write(seccomp)
    (output / "inputs").mkdir(mode=0o700)
    (output / "game").mkdir(mode=0o700)
    for path, key, filename_key in (
        (args.condition, "condition", "condition_name"),
        (args.declaration, "declaration", "declaration_name"),
    ):
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES or json.loads(raw) != inputs[key]:
            raise ValueError("Declared input changed before its read-only copy")
        with (output / "inputs" / inputs[filename_key]).open("xb") as stream:
            stream.write(raw)
    publish(
        output / "owner-plan.json",
        {
            "schema_version": "fortgym.keyboard-docker-owner-plan/v1",
            "runtime": runtime,
            "mode": args.mode,
            "campaign_id": args.campaign_id,
            "container_name": name,
            "owner_nonce": nonce,
            "create_arguments": command,
            "condition_sha256": digest(inputs["condition"]),
            "declaration_sha256": digest(inputs["declaration"]),
            "original_verified_record_sha256": digest(inputs["original"]),
            "response_limit": inputs["limit"],
            "courier_timeout_seconds": inputs["seconds"],
            "vm_provisioning": False,
            "owner_process": capture_owner_process(),
            "image_pull": False,
            "seccomp_sha256": runtime.get("seccomp_sha256"),
        },
    )
    result = {
        "schema_version": "fortgym.keyboard-docker-owner-result/v1",
        "campaign_id": args.campaign_id,
        "mode": args.mode,
        "source_revision": runtime["source_revision"],
        "image": runtime["image"],
        "seccomp_sha256": runtime.get("seccomp_sha256"),
        "status": "failed",
        "container_create_attempted": False,
        "container_id": None,
        "container_stopped_verified": False,
        "original_inputs_unchanged": False,
        "native_result": None,
        "model_responses": [],
        "reported_charge_usd": None,
        "native_acceptance_audited": False,
        "vm_created": False,
        "vm_stopped": False,
    }
    client, identity = None, None
    try:
        client = client_factory(args.docker, args.context, output)
        client.preflight(runtime)
        allowance = allowance_check(
            args.model_executable,
            maximum_used_percent=inputs["condition"]["maximum_included_usage_percent"],
        )
        publish(output / "model-admission.json", allowance)
        if allowance.get("allowed") is not True:
            result["status"] = "budget_limited_pause"
            return result
        if seccomp is not None:
            # Admission can take time. Recheck the retained client-side policy
            # immediately before Docker reads it, without another model call.
            read_profile(str(output / "seccomp.json"), runtime["seccomp_sha256"])
        result["container_create_attempted"] = True
        created = client.call(*command)
        if not re.fullmatch(r"[a-f0-9]{64}", created):
            raise ValueError("Docker create did not return an exact container ID")
        inspection = client.inspect(created)
        identity = owned_container(inspection, runtime, nonce)
        result["container_id"] = identity
        if identity != created or inspection["State"]["Running"]:
            raise ValueError("Created container identity or initial state differs")
        publish(output / "container-created.json", inspection)
        client.call("start", identity)
        exchange = DockerExchange(
            name=identity,
            out=output,
            docker=client.command,
            environment=dict(os.environ),
            output=client.output_command,
            run=client.run,
            native_output=NATIVE_OUTPUT,
            python_executable=runtime["python_executable"],
            project_directory=runtime["project_directory"],
        )
        options = dict(executable=args.model_executable, decisions=result["model_responses"])
        if args.mode == "fresh":
            fresh_server(exchange, inputs["condition"], inputs["declaration"], **options)
        else:
            window_server(
                exchange,
                inputs["condition"],
                inputs["declaration"],
                initial_memory=inputs["initial_memory"],
                **options,
            )
        native_path = output / "game/native/result.json"
        if native_path != native_path.resolve():
            raise ValueError("Native result traverses an unexpected link")
        native = read(native_path)
        result["native_result"] = native
        if (
            native.get("campaign_id") != args.campaign_id
            or native.get("source_revision") != runtime["source_revision"]
            or native.get("runtime_cleanup_verified") is not True
            or native.get("status") not in {"completed", "paused", "budget_limited_pause"}
        ):
            raise ValueError("Native execution did not return a settled owned result")
        result["status"] = "execution_finished"
    except (Exception, KeyboardInterrupt) as error:
        result["error_type"] = type(error).__name__
    finally:
        if client is not None and result["container_create_attempted"]:
            try:
                # Inspect the predeclared name if create returned an uncertain result.
                observed = client.inspect(identity or name)
                identity = owned_container(observed, runtime, nonce)
                result["container_id"] = identity
                if observed["State"]["Running"]:
                    try:
                        # Allow Docker's full grace period plus reply overhead.
                        client.call("stop", "--time", "30", identity, timeout=45)
                    except (Exception, KeyboardInterrupt) as error:
                        # A lost reply is not a live/dead verdict. Preserve the
                        # failed command, then inspect this exact owned ID once;
                        # never retry stop or turn a failed attempt into success.
                        result.update(status="failed", stop_error_type=type(error).__name__)
                stopped = client.inspect(identity)
                if (
                    owned_container(stopped, runtime, nonce) != identity
                    or stopped["State"]["Running"]
                ):
                    raise ValueError("Owned container did not stop")
                publish(output / "container-stopped.json", stopped)
                result["container_stopped_verified"] = True
                # Keep the stopped container and its evidence. Never remove shared
                # images, volumes, containers or a Docker-managed VM as cleanup.
                client.call("logs", identity)
                if stopped["State"].get("ExitCode") != 0:
                    result["status"] = "failed"
            except (Exception, KeyboardInterrupt) as error:
                result.update(status="failed", cleanup_error_type=type(error).__name__)
        try:
            result["original_inputs_unchanged"] = source_inputs(args) == inputs
        except Exception:
            pass
        if not result["original_inputs_unchanged"]:
            result["status"] = "failed"
        rows = result["model_responses"]
        result["known_returned_tokens"] = sum(
            row["total_tokens"] for row in rows if type(row.get("total_tokens")) is int
        )
        result["responses_with_unknown_tokens"] = sum(
            type(row.get("total_tokens")) is not int for row in rows
        )
        publish(output / "owner-result.json", result)
    return result
