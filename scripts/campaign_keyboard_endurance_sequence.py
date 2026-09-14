"""Sequence existing bounded endurance operators; never change their native runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

CAMPAIGN = "astra-keyboard-endurance-v1"
SOURCE = "4b526b5636e6f568a4cae1a1227d746d9c6922c3"
IMAGE = "sha256:a2f12a74805949b8a2fcf0262b5d63048f4bd3a6f2faf4d8bbc74c261b172ed4"
OPERATOR_SHA = "938887dfb05c02961e3d855d540697014a61dfc492c30f8f3c77525d9f7034d3"
RELAY_SHA = "4227d8ef97ab8d802b869a9b2f7db71cc0a75998f9bab1f9032169ecc55ec512"
LIMITS = {"max_dispatches": 1028, "max_total_tokens": 40000000}
STOP_FLAGS = (
    "both_vms_stopped",
    "configs_unchanged",
    "global_context_unchanged",
    "fg-portable_disk_closed",
    "fg-v2_disk_closed",
    "prior_inventory_preserved",
)


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def write(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def settled(path: Path, base: Path) -> dict:
    """Resolve only the finished continuation belonging to the pinned campaign."""
    require(
        path.is_absolute()
        and path.resolve() == path
        and path.parent.parent == base
        and path.name == "result.json",
        "Wrong previous-operation path",
    )
    value = read(path)
    require(
        value.get("schema_version") == "fortgym.endurance-continue-operation/v1"
        and value.get("mode") == "continue"
        and value.get("campaign_id") == CAMPAIGN
        and value.get("source_revision") == SOURCE
        and value.get("image") == IMAGE
        and value.get("owner_execution_finished") is True
        and all(value.get(key) is True for key in STOP_FLAGS)
        and value.get("running_containers_before_vm_stop") == ""
        and not any(key.endswith("error") for key in value),
        "Previous window is unsettled",
    )
    first, end = value["first_step"], value["window_end_decision"]
    require(
        type(first) is int
        and type(end) is int
        and first >= 4
        and end == first + 64
        and end <= 1028
        and end % 64 == 4
        and path.parent.name == f"continuation-{first}-{end}-operation",
        "Previous window boundary differs",
    )
    attempt = Path(value["owner_output"])
    require(
        attempt.is_absolute()
        and attempt.resolve() == attempt
        and attempt.name == f"{CAMPAIGN}-{first + 1}-{end}",
        "Wrong owner output",
    )
    require(
        sha(attempt / "owner-result.json") == value["owner_result_sha256"],
        "Previous owner result changed",
    )
    return value


def next_paths(value: dict, base: Path) -> tuple[int, Path, Path]:
    end = value["window_end_decision"]
    require(
        type(end) is int and 68 <= end < 1028 and end % 64 == 4,
        "No declared continuation remains",
    )
    target = min(1028, end + 64)
    attempt = Path(value["owner_output"]).parent / f"{CAMPAIGN}-{end + 1}-{target}"
    operation = base / f"continuation-{end}-{target}-operation/result.json"
    return target, attempt, operation


class Coordinator:
    def __init__(self, base: Path, source: Path, output: Path):
        self.base, self.source, self.output = base, source, output
        self.stop_requested = False
        self.child: subprocess.Popen | None = None
        self.last_window_outcome: dict | None = None
        self.launched_windows = 0

    def request_stop(self, *_args: object) -> None:
        self.stop_requested = True
        if self.child is not None and self.child.poll() is None:
            # Only the exact owned supervisor receives the signal; it owns teardown.
            self.child.terminate()

    def verify_tools(self) -> None:
        require(sha(self.base / "run_continue.py") == OPERATOR_SHA, "Operator changed")
        require(sha(self.base / "relay.py") == RELAY_SHA, "Relay changed")
        require(
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self.source, text=True
            ).strip()
            == SOURCE,
            "Native source changed",
        )
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=self.source
            ),
            "Native source is dirty",
        )

    def command(self, module: str, *args: str) -> list[str]:
        return [sys.executable, "-B", "-m", module, *args]

    def record(self, value: dict) -> None:
        value = {"observed_at_unix": int(time.time()), **value}
        with (self.output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(value, allow_nan=False) + "\n")
            stream.flush()
        print(json.dumps(value, allow_nan=False), flush=True)

    def audit(self, previous: Path, value: dict) -> dict:
        """Audit/export this window alone; never double-count its checkpoint prefix."""
        end, first = value["window_end_decision"], value["first_step"]
        audit_path = self.output / f"audit-{first + 1}-{end}.json"
        subprocess.run(
            self.command(
                "scripts.campaign_keyboard_docker_audit",
                "--window",
                value["owner_output"],
                value["origin"],
                "--output",
                str(audit_path),
            ),
            cwd=self.source,
            check=True,
        )
        report = read(audit_path)
        require(
            report["passed"] is True
            and report["campaign_id"] == CAMPAIGN
            and report["source_revision"] == SOURCE
            and report["image"] == IMAGE
            and len(report["windows"]) == 1,
            "Native audit differs",
        )
        window = report["windows"][0]
        require(
            window["first_step"] == first
            and window["next_step"] == end
            and window["new_model_responses"] == 64,
            "Audited boundary differs",
        )
        attempt = Path(value["owner_output"])
        index = window["segments"][-1]["segment_index"]
        state = read(attempt / f"game/native/segment-{index}/checkpoint/agent.json")
        extensions = state.get("budget_extensions", [])
        require(
            len(extensions) == 1
            and extensions[0]["limits"] == LIMITS
            and state["usage"]["returned_responses"] == end
            and state["usage"]["total_tokens"] == report["cumulative_returned_tokens"],
            "Saved cumulative budget changed",
        )
        recording = self.output / f"recording-{first + 1}-{end}.json"
        identity = f"{CAMPAIGN}-{first + 1}-{end}"
        subprocess.run(
            self.command(
                "scripts.export_keyboard_docker_recording",
                "--attempt",
                str(attempt),
                "--audit",
                str(audit_path),
                "--audit-sha256",
                sha(audit_path),
                "--id",
                identity,
                "--title",
                f"Astra keyboard endurance · decisions {first + 1}–{end}",
                "--output",
                str(recording),
            ),
            cwd=self.source,
            check=True,
        )
        require(
            settled(previous, self.base) == value,
            "Previous operation changed during audit",
        )
        return {
            "type": "checkpoint_verified",
            "decision": end,
            "operation": str(previous),
            "operation_sha256": sha(previous),
            "audit": str(audit_path),
            "audit_sha256": sha(audit_path),
            "recording": str(recording),
            "recording_sha256": sha(recording),
            "checkpoint_sha256": window["checkpoint_manifest_sha256"],
            "saved_elapsed_ticks": window["saved_elapsed_ticks"],
            "saved_metrics": window["saved_metrics"],
            "cumulative_returned_tokens": report["cumulative_returned_tokens"],
            "reported_subscription_charge_usd": None,
            "budget_extensions": 1,
            "guest_poweroff_returncode": value.get("guest-poweroff_returncode"),
            "vm_stop_returncode": value.get("vm-stop_returncode"),
            "website_recording_published": False,
            "full_goal_complete": False,
        }

    def run_window(self, previous: Path, value: dict) -> Path:
        target, attempt, operation = next_paths(value, self.base)
        require(
            not attempt.exists() and not operation.parent.exists(),
            "Next window already exists",
        )
        relay = None
        relay_attempted = False
        with (
            (self.output / f"owner-{target}.log").open("x") as owner_log,
            (self.output / f"relay-{target}.log").open("x") as relay_log,
        ):
            if self.stop_requested:
                raise InterruptedError("Stopped before launch")
            self.child = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(self.base / "run_continue.py"),
                    "--previous-operation",
                    str(previous),
                ],
                stdout=owner_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.launched_windows += 1
            try:
                self.record(
                    {
                        "type": "window_started",
                        "target": target,
                        "supervisor_pid": self.child.pid,
                    }
                )
                while self.child.poll() is None:
                    if not relay_attempted and (attempt / "owner-plan.json").is_file():
                        relay_attempted = True
                        try:
                            relay = subprocess.Popen(
                                [
                                    sys.executable,
                                    "-B",
                                    str(self.base / "relay.py"),
                                    "--attempt",
                                    str(attempt),
                                ],
                                stdout=relay_log,
                                stderr=subprocess.STDOUT,
                                start_new_session=True,
                            )
                        except OSError as error:
                            self.record(
                                {
                                    "type": "relay_start_failed",
                                    "target": target,
                                    "error_type": type(error).__name__,
                                }
                            )
                    time.sleep(1)
                code = self.child.wait()
            finally:
                # An exception or user interrupt must let the original supervisor tear down.
                if self.child.poll() is None:
                    self.child.terminate()
                    self.child.wait()
                self.child = None
                if relay is not None:
                    try:
                        relay.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        relay.terminate()
                        relay.wait()
            self.last_window_outcome = {
                "type": "window_finished",
                "target": target,
                "returncode": code,
                "relay_returncode": None if relay is None else relay.returncode,
                "operation": str(operation),
            }
            if (attempt / "owner-result.json").is_file():
                owner_result = read(attempt / "owner-result.json")
                self.last_window_outcome["reported_owner_status"] = owner_result.get(
                    "status"
                )
                self.last_window_outcome["owner_result_sha256"] = sha(
                    attempt / "owner-result.json"
                )
            self.record(self.last_window_outcome)
        require(
            code == 0, "Owner stopped without a successful window; preserve its outcome"
        )
        return operation

    def execute(self, previous: Path, max_windows: int) -> dict:
        require(
            type(max_windows) is int and 1 <= max_windows <= 16, "Invalid window count"
        )
        self.verify_tools()
        settled(previous, self.base)
        require(
            self.output.is_absolute()
            and self.output.resolve() == self.output
            and self.output.parent == self.base,
            "Output must be a new operator-local directory",
        )
        self.output.mkdir(mode=0o700)
        result = {
            "schema_version": "fortgym.endurance-sequence/v1",
            "campaign_id": CAMPAIGN,
            "source_revision": SOURCE,
            "image": IMAGE,
            "initial_operation": str(previous),
            "maximum_new_windows": max_windows,
            "launched_windows": 0,
            "last_verified_decision": None,
            "status": "running",
            "full_goal_complete": False,
        }
        write(
            self.output / "plan.json",
            {
                **result,
                "operator_sha256": OPERATOR_SHA,
                "relay_sha256": RELAY_SHA,
                "sequence_sha256": sha(Path(__file__)),
                "cumulative_limits": LIMITS,
                "model_switch": False,
                "new_vm": False,
            },
        )
        try:
            while True:
                self.verify_tools()
                value = settled(previous, self.base)
                report = self.audit(previous, value)
                self.record(report)
                result["last_verified_decision"] = report["decision"]
                result["last_verified_operation"] = str(previous)
                if self.stop_requested:
                    result["status"] = "interrupted"
                    break
                if report["saved_metrics"].get("population") == 0:
                    result["status"] = "no_living_population"
                    break
                if (
                    report["decision"] == 1028
                    or result["launched_windows"] == max_windows
                ):
                    result["status"] = "declared_boundary_reached"
                    break
                previous = self.run_window(previous, value)
                result["launched_windows"] = self.launched_windows
        except BaseException as error:
            result.update(
                status="interrupted"
                if self.stop_requested
                else "stopped_for_inspection",
                error_type=type(error).__name__,
                error=str(error),
                window_outcome=self.last_window_outcome,
                launched_windows=self.launched_windows,
            )
        write(self.output / "result.json", result)
        self.record(result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-directory", type=Path, required=True)
    parser.add_argument("--runtime-source", type=Path, required=True)
    parser.add_argument("--previous-operation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-windows", type=int, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    coordinator = Coordinator(args.operator_directory, args.runtime_source, args.output)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, coordinator.request_stop)
    result = coordinator.execute(args.previous_operation, args.max_windows)
    if result["status"] not in ("declared_boundary_reached", "no_living_population"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
