"""Checkpoint verification does not expand an entire screen history in memory."""

import json
import tracemalloc
from types import SimpleNamespace

from fort_gym.bench.run.campaign_checkpoint import create_checkpoint, verify_checkpoint
from tests.test_campaign_codex_keyboard import Environment


def test_large_trace_checkpoint_decodes_one_observation_at_a_time(tmp_path):
    trace = tmp_path / "trace.jsonl"
    with trace.open("wb") as stream:
        for step in range(500):
            stream.write(
                json.dumps(
                    {
                        "run_id": "bounded-checkpoint",
                        "step": step,
                        "tick_advance": {"end_year": 30, "end_tick": 123 + (step + 1) * 10},
                        "screen_tiles": [[1, 2, 3]] * 2048,
                    }
                ).encode()
                + b"\n"
            )
    size = trace.stat().st_size
    assert size > 10_000_000
    env = Environment()
    env.tick = 5123
    agent = SimpleNamespace(export_campaign_state=lambda: {"campaign_id": "bounded-checkpoint"})
    tracemalloc.start()
    try:
        manifest = create_checkpoint(
            tmp_path / "checkpoint",
            campaign_id="bounded-checkpoint",
            agent=agent,
            snapshotter=env,
            trace_path=trace,
            last_committed_step=499,
            code_revision="fixture",
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * size
    assert manifest["payload"]["next_step"] == 500
    assert verify_checkpoint(tmp_path / "checkpoint") == manifest
    assert (tmp_path / "checkpoint/trace.jsonl").read_bytes() == trace.read_bytes()
