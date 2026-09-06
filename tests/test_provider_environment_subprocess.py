from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from fort_gym.bench.run.process_supervisor import ProcessSupervisor, TerminalClass
from fort_gym.bench.run.runtime_contract import ProviderPolicy, RuntimeContract

_HASHES = {
    "image_manifest_sha256": "1" * 64,
    "image_config_sha256": "2" * 64,
    "image_archive_sha256": "3" * 64,
    "seed_tree_sha256": "4" * 64,
    "seed_world_sha256": "5" * 64,
    "code_sha256": "6" * 64,
}
_EXPECTED_CONTRACT_ENV_NAMES = frozenset(
    {
        "ARTIFACTS_DIR",
        "DFHACK_ENABLED",
        "DFHACK_HOST",
        "DFHACK_PORT",
        "DFROOT",
        "DF_PROTO_ENABLED",
        "FORT_GYM_CONTROL_DIR",
        "FORT_GYM_DB_PATH",
        "FORT_GYM_DFHACK_TRANSPORT",
        "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256",
        "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256",
        "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256",
        "FORT_GYM_EXPECTED_SEED_TREE_SHA256",
        "FORT_GYM_EXPECTED_SEED_WORLD_SHA256",
        "FORT_GYM_NETWORK_ALLOWED_HOST",
        "FORT_GYM_NETWORK_ALLOWED_PORT",
        "FORT_GYM_NETWORK_EVIDENCE_PATH",
        "FORT_GYM_NETWORK_POLICY",
        "FORT_GYM_RUNTIME_PREPARED",
        "FORT_GYM_RUNTIME_SAVE",
        "FORT_GYM_RUN_CONTRACT_SHA256",
        "FORT_GYM_RUN_ID",
        "FORT_GYM_RUN_NONCE",
        "FORT_GYM_SEED_SAVE",
        "FORT_GYM_TERMINAL_OWNER",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
    }
)
_POISON_VALUES = {
    "ambient-openrouter-secret",
    "ambient-openai-secret",
    "ambient-anthropic-secret",
    "ambient-google-secret",
    "ambient-unlisted-secret",
    "ambient-provider-model",
    "/ambient/poison/artifacts",
    "59998",
    "dotenv-openrouter-secret",
    "dotenv-openai-secret",
    "dotenv-anthropic-secret",
    "dotenv-google-secret",
    "dotenv-provider-name",
    "dotenv-only-secret",
    "/dotenv/poison/artifacts",
    "59999",
}


def test_scripted_runtime_contract_child_has_exact_provider_free_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise RuntimeContract and ProcessSupervisor across a real child exec."""

    run_id = "provider-env-subprocess"
    cwd = (tmp_path / "poisoned-cwd").resolve()
    cwd.mkdir()
    (cwd / ".env").write_text(
        "OPENROUTER_API_KEY=dotenv-openrouter-secret\n"
        "OPENAI_API_KEY=dotenv-openai-secret\n"
        "ANTHROPIC_API_KEY=dotenv-anthropic-secret\n"
        "GOOGLE_API_KEY=dotenv-google-secret\n"
        "OPENROUTER_PROVIDER_NAME=dotenv-provider-name\n"
        "OPENROUTER_STRICT_SUPERVISED=1\n"
        "DOTENV_ONLY_SENTINEL=dotenv-only-secret\n"
        "ARTIFACTS_DIR=/dotenv/poison/artifacts\n"
        "DFHACK_PORT=59999\n",
        encoding="utf-8",
    )

    inherited_tmp = (tmp_path / "inherited-tmp").resolve()
    inherited_tmp.mkdir()
    for name in ("LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("TMPDIR", str(inherited_tmp))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-openrouter-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic-secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-google-secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "ambient-provider-model")
    monkeypatch.setenv("UNLISTED_PARENT_SECRET", "ambient-unlisted-secret")
    monkeypatch.setenv("PYTHONPATH", "/ambient/pythonpath/poison")
    monkeypatch.setenv("HOME", "/ambient/poison/home")
    monkeypatch.setenv("ARTIFACTS_DIR", "/ambient/poison/artifacts")
    monkeypatch.setenv("DFHACK_PORT", "59998")

    contract = RuntimeContract(
        run_id=run_id,
        backend="dfhack",
        model="dfhack-governed-scripted",
        port=58_071,
        nonce="a" * 32,
        db_path=(tmp_path / "registry.sqlite3").resolve(),
        artifacts_root=(tmp_path / "gameplay-artifacts").resolve(),
        control_root=(tmp_path / "control").resolve(),
        dfroot=(tmp_path / "dfroot").resolve(),
        seed_save="region3-seed",
        runtime_save="provider-env-runtime",
        cohort_run_ids=(run_id,),
        provider=ProviderPolicy(),
        scripted=True,
        **_HASHES,
    )
    attempt_dir = (
        contract.control_root / run_id / "attempts" / "attempt-0001"
    ).resolve()
    child_code = """
import json
import os
import sys

socket_audit_events = []
def audit(event, _args):
    if event.startswith("socket."):
        socket_audit_events.append(event)
sys.addaudithook(audit)

environment_before_settings = dict(sorted(os.environ.items()))

from fort_gym.bench.config import get_settings
from fort_gym.bench.run import network_guard

settings = get_settings()
print(json.dumps({
    "environment_before_settings": environment_before_settings,
    "environment_after_settings": dict(sorted(os.environ.items())),
    "network_guard_installed": network_guard._INSTALLED,
    "socket_audit_events": socket_audit_events,
    "settings": {
        "DFHACK_ENABLED": settings.DFHACK_ENABLED,
        "DFHACK_HOST": settings.DFHACK_HOST,
        "DFHACK_PORT": settings.DFHACK_PORT,
        "ARTIFACTS_DIR": settings.ARTIFACTS_DIR,
        "FORT_GYM_SEED_SAVE": settings.FORT_GYM_SEED_SAVE,
        "FORT_GYM_RUNTIME_SAVE": settings.FORT_GYM_RUNTIME_SAVE,
        "OPENROUTER_API_KEY": settings.OPENROUTER_API_KEY,
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
        "OPENROUTER_PROVIDER_NAME": settings.OPENROUTER_PROVIDER_NAME,
        "OPENROUTER_STRICT_SUPERVISED": settings.OPENROUTER_STRICT_SUPERVISED,
    },
}, sort_keys=True))
"""
    contract_spec = contract.to_run_spec(
        argv=(
            sys.executable,
            "-c",
            child_code,
            "--external-run-id",
            run_id,
        ),
        cwd=cwd,
        attempt_dir=attempt_dir,
        timeout_seconds=10.0,
        term_grace_seconds=1.0,
        poll_interval_seconds=0.01,
    )
    # PROVIDER-ENV exercises only the child exec boundary. PORT-1/PORT-2 own
    # host socket leasing, so this provider-free test performs no socket call.
    spec = replace(contract_spec, port=None, runtime_cleanup_required=False)
    assert spec.runtime_cleanup_required is False
    assert set(spec.env) == _EXPECTED_CONTRACT_ENV_NAMES
    assert spec.env_allowlist == tuple(sorted(_EXPECTED_CONTRACT_ENV_NAMES))
    assert spec.scripted is True
    assert spec.provider_enabled is False
    assert spec.provider_route is None
    assert spec.provider_model is None
    assert spec.provider_name is None
    assert contract.environment_identity()["provider"] == {
        "enabled": False,
        "route": None,
        "model": None,
        "provider_name": None,
        "base_url": None,
        "max_total_tokens": None,
        "max_cost_usd": None,
        "credential_present": False,
        "strict_supervised": False,
    }
    expected_environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(inherited_tmp),
        **dict(spec.env),
        "FORT_GYM_DISABLE_DOTENV": "1",
    }
    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.COMPLETED
    assert result.payload["returncode"] == 0
    stdout = (attempt_dir / "child.stdout.log").read_text(encoding="utf-8")
    stderr = (attempt_dir / "child.stderr.log").read_text(encoding="utf-8")
    payload = json.loads(stdout.strip())
    if "__CF_USER_TEXT_ENCODING" in payload["environment_before_settings"]:
        # Some macOS Python builds add this fixed per-user value after exec,
        # including under `env -i`; when present it remains exactly pinned.
        expected_environment["__CF_USER_TEXT_ENCODING"] = (
            f"0x{os.getuid():X}:0x0:0x0"
        )
    assert payload["environment_before_settings"] == expected_environment
    assert payload["environment_after_settings"] == expected_environment
    assert payload["network_guard_installed"] is True
    assert payload["socket_audit_events"] == []
    assert payload["settings"] == {
        "DFHACK_ENABLED": True,
        "DFHACK_HOST": "127.0.0.1",
        "DFHACK_PORT": contract.port,
        "ARTIFACTS_DIR": str(contract.artifacts_root),
        "FORT_GYM_SEED_SAVE": contract.seed_save,
        "FORT_GYM_RUNTIME_SAVE": contract.runtime_save,
        "OPENROUTER_API_KEY": None,
        "OPENAI_API_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OPENROUTER_PROVIDER_NAME": None,
        "OPENROUTER_STRICT_SUPERVISED": False,
    }
    child_environment = payload["environment_after_settings"]
    assert child_environment["FORT_GYM_DISABLE_DOTENV"] == "1"
    assert child_environment["FORT_GYM_NETWORK_POLICY"] == "loopback-port-only"
    assert child_environment["FORT_GYM_NETWORK_ALLOWED_HOST"] == "127.0.0.1"
    assert child_environment["FORT_GYM_NETWORK_ALLOWED_PORT"] == str(contract.port)
    assert child_environment["PYTHONPATH"] != "/ambient/pythonpath/poison"
    serialized_evidence = "\n".join(
        (
            stdout,
            stderr,
            result.terminal_path.read_text(encoding="utf-8"),
            result.journal_path.read_text(encoding="utf-8"),
        )
    )
    assert all(poison not in serialized_evidence for poison in _POISON_VALUES)
    assert result.payload["budget"] == {
        "calls": 0,
        "events_seen": 0,
        "provider_enabled": False,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "max_total_tokens": 128_000,
        "max_cost_usd": 25.0,
        "requested_models": [],
        "resolved_models": [],
        "providers": [],
    }
    assert not (attempt_dir / "network-denials.jsonl").exists()
    assert spec.trace_path is not None and not spec.trace_path.exists()
    assert stderr == ""
