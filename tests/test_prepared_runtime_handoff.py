from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.mock_env import MockEnvironment
from fort_gym.bench.run import runner
from fort_gym.bench.run.runtime_contract import (
    PreparedRuntimeIdentityError,
    RuntimeContract,
)

_PREPARED_ENVIRONMENT_NAMES = (
    "FORT_GYM_RUNTIME_PREPARED",
    "FORT_GYM_RUN_ID",
    "FORT_GYM_RUN_NONCE",
    "FORT_GYM_RUN_CONTRACT_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256",
    "FORT_GYM_EXPECTED_SEED_TREE_SHA256",
    "FORT_GYM_EXPECTED_SEED_WORLD_SHA256",
    "FORT_GYM_SEED_SAVE",
    "FORT_GYM_RUNTIME_SAVE",
)


class WaitAgent(Agent):
    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "WAIT",
            "params": {},
            "intent": "exercise prepared runtime handoff",
            "advance_ticks": 10,
        }


class ResetBoundary(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _contract(tmp_path: Path, run_id: str = "prepared-run") -> RuntimeContract:
    return RuntimeContract(
        run_id=run_id,
        backend="dfhack",
        model="fake",
        port=58_101,
        nonce="a" * 32,
        image_manifest_sha256="1" * 64,
        image_config_sha256="2" * 64,
        image_archive_sha256="3" * 64,
        seed_tree_sha256="4" * 64,
        seed_world_sha256="5" * 64,
        code_sha256="6" * 64,
        db_path=tmp_path / "registry.sqlite3",
        artifacts_root=tmp_path / "artifacts",
        control_root=tmp_path / "control",
        dfroot=tmp_path / "df",
        seed_save="region3-seed",
        runtime_save="runtime-prepared-run",
        cohort_run_ids=(run_id,),
    )


def _install_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    for name in _PREPARED_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FORT_GYM_DFHACK_COMPLETE_DIG", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_prepared_runtime_skips_host_reset_and_persists_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    _install_environment(monkeypatch, contract.child_environment())
    state = MockEnvironment().observe()
    state.update({"pause_state": True, "year": 0, "year_tick": 0, "time": 0})
    connected = False

    class FakeDFHackClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.last_tick_info: dict[str, Any] = {}

        def connect(self) -> None:
            nonlocal connected
            connected = True

        def pause(self) -> None:
            return None

        def advance(self, ticks: int, **_kwargs: Any) -> dict[str, Any]:
            state["time"] = int(state["time"]) + ticks
            state["year_tick"] = state["time"]
            self.last_tick_info = {
                "ok": True,
                "ticks_advanced": ticks,
                "repause_requested": True,
                "repause_effective": True,
            }
            return dict(state)

        def close(self) -> None:
            return None

    def unexpected_reset(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("prepared runtime must not perform a host seed reset")

    monkeypatch.setattr(runner, "DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        runner.StateReader,
        "from_dfhack",
        lambda _client: dict(state),
    )
    monkeypatch.setattr(
        runner,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(runner, "maybe_reset_dfhack_seed", unexpected_reset)
    monkeypatch.setattr(runner, "pristine_seed_sha256", unexpected_reset)

    run_id = runner.run_once(
        WaitAgent(),
        backend="dfhack",
        model="fake",
        max_steps=1,
        ticks_per_step=10,
        run_id=contract.run_id,
        preserve_save=False,
        seed_save=contract.seed_save,
        runtime_save=contract.runtime_save,
    )

    assert run_id == contract.run_id
    assert connected is True
    summary = json.loads(
        (contract.artifacts_root / contract.run_id / "summary.json").read_text()
    )
    identity = summary["environment_contract"]
    assert identity["contract_sha256"] == contract.contract_sha256
    assert identity["seed"]["tree_sha256"] == contract.seed_tree_sha256
    assert identity["seed"]["world_sha256"] == contract.seed_world_sha256
    assert identity["image"]["manifest_sha256"] == contract.image_manifest_sha256
    assert contract.nonce not in json.dumps(identity, sort_keys=True)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("FORT_GYM_EXPECTED_SEED_TREE_SHA256", None, "incomplete"),
        ("FORT_GYM_EXPECTED_SEED_WORLD_SHA256", "bad", "malformed"),
        ("FORT_GYM_RUN_CONTRACT_SHA256", "A" * 64, "malformed"),
        ("FORT_GYM_RUN_ID", "wrong-run", "does not match"),
    ],
)
def test_invalid_prepared_runtime_rejects_before_artifacts_reset_or_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str | None,
    message: str,
) -> None:
    contract = _contract(tmp_path)
    environment = contract.child_environment()
    if value is None:
        environment.pop(name)
    else:
        environment[name] = value
    _install_environment(monkeypatch, environment)
    reset_called = False
    connected = False

    def unexpected_reset(*_args: Any, **_kwargs: Any) -> None:
        nonlocal reset_called
        reset_called = True

    class UnexpectedDFHackClient:
        def __init__(self, **_kwargs: Any) -> None:
            nonlocal connected
            connected = True

    monkeypatch.setattr(runner, "maybe_reset_dfhack_seed", unexpected_reset)
    monkeypatch.setattr(runner, "DFHackClient", UnexpectedDFHackClient)

    with pytest.raises(PreparedRuntimeIdentityError, match=message):
        runner.run_once(
            WaitAgent(),
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
            run_id=contract.run_id,
            preserve_save=False,
            seed_save=contract.seed_save,
            runtime_save=contract.runtime_save,
        )

    assert reset_called is False
    assert connected is False
    assert not (contract.artifacts_root / contract.run_id).exists()


def test_legacy_dfhack_still_performs_host_seed_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "DFHACK_ENABLED": "1",
    }
    _install_environment(monkeypatch, environment)
    calls: list[tuple[str | None, str | None]] = []
    connected = False

    def stop_after_reset(
        _settings: Any,
        *,
        seed_save: str | None,
        runtime_save: str | None,
    ) -> None:
        calls.append((seed_save, runtime_save))
        raise ResetBoundary("reset boundary")

    class UnexpectedDFHackClient:
        def __init__(self, **_kwargs: Any) -> None:
            nonlocal connected
            connected = True

    monkeypatch.setattr(runner, "maybe_reset_dfhack_seed", stop_after_reset)
    monkeypatch.setattr(runner, "DFHackClient", UnexpectedDFHackClient)
    monkeypatch.setattr(
        runner,
        "_cleanup_dfhack_runtime",
        lambda *_args, **_kwargs: {"ok": True, "errors": []},
    )

    with pytest.raises(ResetBoundary, match="reset boundary"):
        runner.run_once(
            WaitAgent(),
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
            run_id="legacy-run",
            preserve_save=False,
            seed_save="legacy-seed",
            runtime_save="legacy-runtime",
        )

    assert calls == [("legacy-seed", "legacy-runtime")]
    assert connected is False
