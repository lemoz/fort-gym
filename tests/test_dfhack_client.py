from __future__ import annotations

from typing import Any

from fort_gym.bench.env.dfhack_client import DFHackClient


class _TimeoutBuildingClient(DFHackClient):
    def _ensure_connection(self) -> None:
        return

    def _run_command(self, *_args: Any, **_kwargs: Any) -> None:
        raise TimeoutError("timed out")


def test_place_building_returns_failure_on_timeout() -> None:
    client = _TimeoutBuildingClient()

    ok, why = client.place_building("CarpenterWorkshop", 51, 36, 0)

    assert ok is False
    assert why == "timed out"
