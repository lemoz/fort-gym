"""Finite host exchange for a declared native window, without VM ownership.

The VM owner binds the native source, checkpoint, condition and window before
calling this courier. Native save verification and teardown remain separate.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..agent.keyboard_courier import answer_request
from ..agent.keyboard_exchange import publish, read, validate_request
from ..agent.keyboard_observation import observe_container_output
from .keyboard_config import positive, validate_condition


class Exchange(Protocol):
    out: Path

    def running(self) -> bool: ...
    def pending(self) -> list[str] | None: ...
    def copy_request(self, identifier: str, directory: Path) -> bool: ...
    def deliver(self, arguments: list[str], value: dict, label: str) -> None: ...


def window_bounds(condition: dict, window: dict) -> tuple[int, int]:
    """Derive response and wall-clock ceilings without extending campaign usage."""
    validate_condition(condition)
    if (
        window.get("schema_version") != "fortgym.codex-keyboard-window/v1"
        or any(
            window.get(k) is not False
            for k in ("reset_memory", "reset_usage", "strategy_intervention")
        )
        or {"prompt_change", "budget_extension", "restart"} & window.keys()
    ):
        raise ValueError("Window courier requires unchanged continuation conditions")
    cursor = positive(window.get("continuation_from_next_step"), "continuation cursor")
    steps = positive(window.get("steps_per_segment"), "segment size", maximum=64)
    segments = positive(window.get("max_segments"), "segment count", maximum=16)
    limit = steps * segments
    if cursor + limit > condition["max_dispatches"]:
        raise ValueError("Window exceeds the original campaign dispatch ceiling")
    return limit, limit * (condition["exchange_timeout_seconds"] + 120) + segments * 300


def serve_window(
    exchange: Exchange,
    condition: dict,
    window: dict,
    *,
    initial_memory: str,
    executable: Path,
    decisions: list[dict],
    answer: Callable = answer_request,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], None] = time.sleep,
    emit: Callable[[dict], None] | None = None,
) -> None:
    """Answer each new request once; retain errors and never retry an inference."""
    limit, seconds = window_bounds(condition, window)
    if not isinstance(initial_memory, str) or decisions:
        raise ValueError("A new window requires its own memory and empty decision receipt list")
    if not exchange.out.is_absolute() or exchange.out.is_symlink() or not exchange.out.is_dir():
        raise ValueError("A window requires an existing owned absolute output directory")
    model_root = exchange.out / "model"
    model_root.mkdir(mode=0o700)
    handled: set[str] = set()
    memory, handshake, terminal_response = initial_memory, False, False
    deadline = clock() + seconds
    while clock() < deadline:
        if not exchange.running():
            return
        pending = exchange.pending()
        if pending is None:
            return
        for identifier in pending:
            if re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
                raise ValueError("Invalid native request identifier")
            if identifier in handled:
                continue
            if len(handled) >= limit or terminal_response:
                raise ValueError("Native window requested an extra or retried model response")
            if clock() >= deadline:
                raise TimeoutError("Declared window courier deadline reached")
            directory = model_root / identifier
            # The copy adapter creates this directory only once a request is ready.
            if not exchange.copy_request(identifier, directory):
                continue
            request = read(directory / "request.json")
            validate_request(request)
            if (
                request["request_id"] != identifier
                or request["memory"] != memory
                or [request["screen"]["width"], request["screen"]["height"]]
                != condition["screen_size"]
            ):
                raise ValueError("Request does not continue its bound memory or screen condition")
            if not handshake:
                exchange.deliver(
                    ["probe", "--output", "/evidence/astra/transport-probe.json"],
                    {"probe": "bounded-json-delivery/v1"},
                    "model-handoff-preflight",
                )
                handshake = True
            handled.add(identifier)
            response, summary = answer(
                request, directory=directory, condition=condition, executable=executable
            )
            summary = {"decision_index": len(decisions), **summary}
            decisions.append(summary)
            publish(directory / "summary.json", summary)
            exchange.deliver(
                [
                    "publish-response",
                    "--exchange",
                    "/evidence/astra/exchange",
                    "--request-id",
                    identifier,
                ],
                response,
                "response-publish-" + identifier,
            )
            result = response["result"]
            if result.get("action_grammar_valid") is True:
                memory = result["action"]["memory_update"]
                if not isinstance(memory, str):
                    raise ValueError("Model memory update is not a string")
            terminal_response = summary.get("model_dispatched") is not True
            if emit is not None:
                emit(summary)
        wait(0.5)
    raise TimeoutError("Declared window courier deadline reached")


@dataclass
class DockerExchange:
    """Owned-container file transport; only literal read-only probes are retried."""

    name: str
    out: Path
    docker: list[str]
    environment: dict[str, str]
    output: Callable[[list[str]], str]
    run: Callable
    process: Callable = subprocess.run
    failures: int = 0

    @property
    def inspection(self) -> list[str]:
        return self.docker + ["inspect", self.name, "--format", "{{json .State}}"]

    def running(self) -> bool:
        state = json.loads(self.output(self.inspection))
        if not isinstance(state, dict) or type(state.get("Running")) is not bool:
            raise ValueError("Container liveness is unknown")
        return state["Running"]

    def _failure(self, value: dict) -> None:
        self.failures += 1
        publish(self.out / f"read-failure-{self.failures:04d}.json", value)

    def _observe(self, script: str) -> str | None:
        return observe_container_output(
            self.docker + ["exec", self.name, "/bin/sh", "-c", script],
            output=self.output,
            inspect_command=self.inspection,
            retain_warning=lambda value: publish(
                self.out / "terminal-observation-warning.json", value
            ),
            max_live_read_attempts=3,
            retain_failure=self._failure,
        )

    def pending(self) -> list[str] | None:
        value = self._observe(
            "if test -d /evidence/astra/exchange; then ls -1 /evidence/astra/exchange; fi"
        )
        return None if value is None else value.splitlines()

    def copy_request(self, identifier: str, directory: Path) -> bool:
        if re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
            raise ValueError("Invalid native request identifier")
        remote = "/evidence/astra/exchange/" + identifier
        ready = self._observe("if test -f " + remote + "/request.json; then echo ready; fi")
        if ready != "ready":
            return False
        directory.mkdir(mode=0o700)
        self.run(
            self.docker
            + ["cp", self.name + ":" + remote + "/request.json", str(directory / "request.json")],
            "request-copy-" + identifier,
            20,
        )
        return True

    def deliver(self, arguments: list[str], value: dict, label: str) -> None:
        with (self.out / (label + ".log")).open("xb") as log:
            result = self.process(
                self.docker
                + [
                    "exec",
                    "-i",
                    self.name,
                    "/opt/python/bin/python3.11",
                    "-m",
                    "scripts.campaign_keyboard_native",
                    *arguments,
                ],
                input=json.dumps(value, allow_nan=False).encode(),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=self.environment,
                timeout=20,
            )
        if result.returncode != 0 or read(self.out / (label + ".log")) != {
            "published_and_read_verified": True
        }:
            raise ValueError("Game-user response delivery was not verified")
