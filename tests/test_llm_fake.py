from __future__ import annotations

import json
from pathlib import Path

from fort_gym.bench.agent.fake_llm import FakeLLMAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import run_once


def test_fake_llm_emits_dig(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    get_settings()

    run_id = run_once(FakeLLMAgent(), env="mock", max_steps=2, ticks_per_step=5)
    trace_path = Path(tmp_path) / run_id / "trace.jsonl"
    assert trace_path.is_file()
    with trace_path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    assert any(rec.get("action", {}).get("type") == "DIG" for rec in records)
