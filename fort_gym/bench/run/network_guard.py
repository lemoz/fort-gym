"""Early Python network guard for provider-free supervised workers.

The guard is installed by the adjacent ``sitecustomize.py`` before the Fort
Gym CLI imports application modules. It is intentionally narrow: provider-free
DFHack workers may connect only to their exact loopback RPC port, while mock
workers may not open Internet sockets at all. Unix-domain sockets remain
available for local runtime/library use.

This is a fail-closed application boundary, not a replacement for the isolated
Linux acceptance host's syscall/cgroup network evidence.
"""

from __future__ import annotations

import errno
import json
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_POLICY_ENV = "FORT_GYM_NETWORK_POLICY"
_POLICY_DENY_INET = "deny-inet"
_POLICY_LOOPBACK_PORT = "loopback-port-only"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_INSTALLED = False
_ORIGINAL_SOCKET = socket.socket
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


class NetworkGuardConfigurationError(RuntimeError):
    """A supervised child supplied an incomplete network policy."""


def _bounded(value: object, maximum: int = 200) -> str:
    return " ".join(str(value).split())[:maximum]


def _normalize_port(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return port if 1 <= port <= 65_535 else None


def _address_allowed(
    family: int,
    address: object,
    *,
    policy: str,
    allowed_host: str | None,
    allowed_port: int | None,
) -> bool:
    if family == socket.AF_UNIX:
        return True
    if family not in {socket.AF_INET, socket.AF_INET6}:
        return False
    if policy == _POLICY_DENY_INET:
        return False
    if policy != _POLICY_LOOPBACK_PORT or not isinstance(address, tuple):
        return False
    if len(address) < 2:
        return False
    host = str(address[0])
    port = _normalize_port(address[1])
    return host == allowed_host and port == allowed_port


def _append_denial(
    path: Path,
    *,
    run_id: str,
    contract_sha256: str,
    operation: str,
    family: int,
    address: object,
) -> None:
    payload = {
        "schema": "fortgym.network-denial/v1",
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "contract_sha256": contract_sha256,
        "operation": operation,
        "family": int(family),
        "address": _bounded(address),
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("short network-denial evidence write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_from_environment() -> bool:
    """Install the configured guard once; return whether a policy was active."""

    global _INSTALLED
    policy = os.environ.get(_POLICY_ENV)
    if policy is None:
        return False
    if _INSTALLED:
        return True
    if policy not in {_POLICY_DENY_INET, _POLICY_LOOPBACK_PORT}:
        raise NetworkGuardConfigurationError("unsupported supervised network policy")

    run_id = os.environ.get("FORT_GYM_RUN_ID", "")
    contract_sha256 = os.environ.get("FORT_GYM_RUN_CONTRACT_SHA256", "")
    evidence_raw = os.environ.get("FORT_GYM_NETWORK_EVIDENCE_PATH", "")
    allowed_host = os.environ.get("FORT_GYM_NETWORK_ALLOWED_HOST")
    allowed_port = _normalize_port(os.environ.get("FORT_GYM_NETWORK_ALLOWED_PORT"))
    if not _RUN_ID_RE.fullmatch(run_id):
        raise NetworkGuardConfigurationError("network policy run ID is invalid")
    if not _SHA256_RE.fullmatch(contract_sha256):
        raise NetworkGuardConfigurationError("network policy contract digest is invalid")
    evidence_path = Path(evidence_raw)
    if not evidence_path.is_absolute() or not evidence_path.parent.is_dir():
        raise NetworkGuardConfigurationError(
            "network denial evidence path must have an existing absolute parent"
        )
    if policy == _POLICY_LOOPBACK_PORT:
        if allowed_host != "127.0.0.1" or allowed_port is None:
            raise NetworkGuardConfigurationError(
                "loopback policy requires exact 127.0.0.1 host and port"
            )
    elif allowed_host is not None or allowed_port is not None:
        raise NetworkGuardConfigurationError(
            "deny-inet policy cannot carry an allowed endpoint"
        )

    def deny(operation: str, family: int, address: object) -> None:
        _append_denial(
            evidence_path,
            run_id=run_id,
            contract_sha256=contract_sha256,
            operation=operation,
            family=family,
            address=address,
        )
        raise PermissionError(
            errno.EACCES,
            f"Fort Gym supervised network policy denied {operation}",
        )

    class GuardedSocket(_ORIGINAL_SOCKET):
        def connect(self, address: Any) -> None:
            if not _address_allowed(
                self.family,
                address,
                policy=policy,
                allowed_host=allowed_host,
                allowed_port=allowed_port,
            ):
                deny("connect", self.family, address)
            return super().connect(address)

        def connect_ex(self, address: Any) -> int:
            if not _address_allowed(
                self.family,
                address,
                policy=policy,
                allowed_host=allowed_host,
                allowed_port=allowed_port,
            ):
                try:
                    deny("connect_ex", self.family, address)
                except PermissionError:
                    return errno.EACCES
            return super().connect_ex(address)

        def sendto(self, data: bytes, *args: Any) -> int:
            address = args[-1] if args and isinstance(args[-1], tuple) else None
            if address is not None and not _address_allowed(
                self.family,
                address,
                policy=policy,
                allowed_host=allowed_host,
                allowed_port=allowed_port,
            ):
                deny("sendto", self.family, address)
            return super().sendto(data, *args)

        def sendmsg(
            self,
            buffers: Any,
            ancdata: Any = (),
            flags: int = 0,
            address: Any = None,
        ) -> int:
            if address is not None and not _address_allowed(
                self.family,
                address,
                policy=policy,
                allowed_host=allowed_host,
                allowed_port=allowed_port,
            ):
                deny("sendmsg", self.family, address)
            if address is None:
                return super().sendmsg(buffers, ancdata, flags)
            return super().sendmsg(buffers, ancdata, flags, address)

    def guarded_getaddrinfo(
        host: Any,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        requested_family = family or socket.AF_INET
        candidate = (str(host), port)
        if not _address_allowed(
            requested_family,
            candidate,
            policy=policy,
            allowed_host=allowed_host,
            allowed_port=allowed_port,
        ):
            deny("getaddrinfo", requested_family, candidate)
        return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

    socket.socket = GuardedSocket
    socket.SocketType = GuardedSocket
    socket.getaddrinfo = guarded_getaddrinfo
    _INSTALLED = True
    return True


__all__ = [
    "NetworkGuardConfigurationError",
    "install_from_environment",
]
