"""Checkout entry points load without a provider or a native runtime."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "command",
    [
        "campaign_run",
        "campaign_segment",
        "campaign_save_smoke",
        "campaign_load_smoke",
        "campaign_profile",
        "campaign_llama_server",
        "campaign_local_server",
        "campaign_output_replay",
    ],
)
def test_checkout_cli_help_needs_no_game_or_provider(command):
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "scripts." + command, "--help"],
        cwd=root,
        env={"PATH": os.defpath, "FORT_GYM_DISABLE_DOTENV": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


def test_untracked_source_is_rejected_before_native_launch(tmp_path, monkeypatch):
    from scripts import campaign_segment as module

    config_path = (
        Path(__file__).resolve().parents[1]
        / "experiments/campaigns/development_continuation_v1.json"
    )
    model = "qwen/qwen3.8-flash"
    config = module.load_segment_config(config_path, model)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-unused-credential")

    def git(command, **kwargs):
        if command[1] == "rev-parse":
            return "a" * 40
        assert "--untracked-files=all" in command
        return b"?? scripts/uncommitted_policy.py\n"

    monkeypatch.setattr(module.subprocess, "check_output", git)
    monkeypatch.setattr(module, "run_isolated", lambda **kwargs: pytest.fail("Must not launch"))
    args = SimpleNamespace(
        source=tmp_path / "unused-runtime",
        checkpoint=None,
        snapshot=tmp_path / "unused-snapshot",
        snapshot_sha256="b" * 64,
        output=tmp_path / "output",
    )
    with pytest.raises(ValueError, match="clean committed checkout"):
        module.launch_segment(args, config)
    assert not args.output.exists()
