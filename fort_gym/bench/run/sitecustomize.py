"""Fail-closed early installer for the supervised-worker network guard."""

from __future__ import annotations

import os
import sys

try:
    from fort_gym.bench.run.network_guard import install_from_environment

    install_from_environment()
except Exception as exc:  # noqa: BLE001 - sitecustomize must fail closed on any error
    message = " ".join(str(exc).split())[:300]
    sys.stderr.write(
        "Fort Gym supervised network guard failed before worker import: "
        f"{type(exc).__name__}: {message}\n"
    )
    sys.stderr.flush()
    os._exit(78)
