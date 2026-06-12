from __future__ import annotations

import socket

from fort_gym.bench.cli import _available_port, _run_quickstart_mock
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.storage import RunRegistry


def test_quickstart_mock_registers_public_leaderboard(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_dir))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    run_id, trace_path, summary_path, token, leaderboard = _run_quickstart_mock(
        max_steps=2,
        ticks_per_step=5,
        registry=registry,
    )

    assert run_id
    assert trace_path.is_file()
    assert summary_path.is_file()
    assert registry.get_share(token) is not None
    assert leaderboard
    assert leaderboard[0]["model"] == "random"
    assert leaderboard[0]["backend"] == "mock"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_available_port_skips_bound_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]

        assert _available_port(occupied) != occupied
