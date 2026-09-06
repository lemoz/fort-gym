import hashlib
import json
from copy import deepcopy

import pytest

from scripts import campaign_continuation_smoke
from scripts.campaign_continuation_smoke import ContinuationFixtureAgent, verify_continuation
from scripts.campaign_load_smoke import verify_load_source
from fort_gym.bench.run.campaign_checkpoint import create_checkpoint
from fort_gym.bench.run.campaign_save import save_inventory


def receipt(step, start, ticks, requested):
    return {
        "step": step,
        "previous_step": step - 1,
        "action": {"type": "WAIT", "advance_ticks": requested},
        "tick_advance": {
            "ok": True,
            "start_year": 30,
            "start_tick": start,
            "end_year": 30,
            "end_tick": start + ticks,
            "ticks_advanced": ticks,
            "elapsed_ms": 500,
        },
    }


def worker_results():
    first = {
        "actions": [receipt(0, 19309, 11, 10), receipt(1, 19320, 22, 20)],
        "agent_state": {"memory": {"decisions": 2}},
        "next_step": 2,
        "initial": {"year": 30, "year_tick": 19309, "pause_state": True},
        "final": {"year": 30, "year_tick": 19342, "pause_state": True},
    }
    resumed = {
        "actions": [receipt(1, 19320, 23, 20)],
        "agent_state": deepcopy(first["agent_state"]),
        "next_step": 2,
        "initial": {"year": 30, "year_tick": 19320, "pause_state": True},
        "final": {"year": 30, "year_tick": 19343, "pause_state": True},
    }
    return first, resumed


def test_native_verifier_counts_observed_ticks_without_claiming_exact_wall_timing():
    result = verify_continuation(*worker_results())
    assert result["native_continuation_fixture_verified"] is True
    assert result["first_process_observed_ticks"] == 33
    assert result["resumed_process_observed_ticks"] == 23
    assert result["autonomous_gameplay"] is False
    assert result["provider_calls"] == 0


@pytest.mark.parametrize(
    "mutation",
    ["replayed_action", "wrong_history", "wrong_start", "missing_ticks", "unpaused", "overshoot"],
)
def test_native_verifier_rejects_bad_continuation(mutation):
    first, resumed = worker_results()
    row = resumed["actions"][0]
    if mutation == "replayed_action":
        row["action"]["advance_ticks"] = 10
    elif mutation == "wrong_history":
        row["previous_step"] = -1
    elif mutation == "wrong_start":
        resumed["initial"]["year_tick"] = 19309
    elif mutation == "missing_ticks":
        row["tick_advance"]["ticks_advanced"] = 0
    elif mutation == "unpaused":
        resumed["final"]["pause_state"] = False
    else:
        row["tick_advance"].update(ticks_advanced=1000, end_tick=20320)
    with pytest.raises(ValueError):
        verify_continuation(first, resumed)


def test_fixture_preserves_decision_count_without_any_provider():
    first = ContinuationFixtureAgent()
    first.set_campaign_context(campaign_id="fixture")
    assert first.decide("", {})["advance_ticks"] == 10
    restored = ContinuationFixtureAgent()
    restored.restore_campaign_state(first.export_campaign_state(), campaign_id="fixture")
    assert restored.decide("", {})["advance_ticks"] == 20
    assert restored.export_campaign_state()["usage"]["total_cost_usd"] == "0"
    with pytest.raises(ValueError, match="only two"):
        restored.decide("", {})


def test_loader_accepts_only_digest_bound_complete_v2_checkpoint(tmp_path):
    class Snapshot:
        def capture(self, directory):
            directory.mkdir()
            (directory / "world.sav").write_bytes(b"not-a-real-game-save")
            return {"year": 30, "year_tick": 10, "paused": True, "files": save_inventory(directory)}

    agent = ContinuationFixtureAgent()
    agent.set_campaign_context(campaign_id="fixture")
    trace, usage = tmp_path / "trace.jsonl", tmp_path / "usage.jsonl"
    trace.write_text(
        json.dumps(
            {"run_id": "fixture", "step": 0, "tick_advance": {"end_year": 30, "end_tick": 10}}
        )
        + "\n"
    )
    usage.write_text("{}\n")
    checkpoint = tmp_path / "checkpoint"
    create_checkpoint(
        checkpoint,
        campaign_id="fixture",
        agent=agent,
        snapshotter=Snapshot(),
        trace_path=trace,
        last_committed_step=0,
        code_revision="test",
        runner_state={},
        usage_path=usage,
    )
    digest = hashlib.sha256((checkpoint / "checkpoint.json").read_bytes()).hexdigest()
    save, boundary = verify_load_source(checkpoint, digest, "campaign_checkpoint")
    assert save == checkpoint / "game" and boundary["year_tick"] == 10
    with pytest.raises(RuntimeError, match="digest"):
        verify_load_source(checkpoint, "0" * 64, "campaign_checkpoint")
    (checkpoint / "game/world.sav").write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="digest"):
        verify_load_source(checkpoint, digest, "campaign_checkpoint")


@pytest.mark.parametrize("cleanup_verified", [True, False])
def test_parent_reuses_only_successfully_torn_down_first_phase(
    tmp_path, monkeypatch, cleanup_verified
):
    first_output, output = tmp_path / "first", tmp_path / "continuation"
    first_output.mkdir()
    checkpoint = first_output / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "checkpoint.json").write_text("{}")
    first, resumed = worker_results()
    (first_output / "worker-result.json").write_text(json.dumps(first))
    (first_output / "result.json").write_text(
        json.dumps(
            {
                "native_load_verified": True,
                "cleanup_verified": cleanup_verified,
                "runtime_path": str(first_output / "runtime"),
                "code_revision": "first-revision",
            }
        )
    )
    calls = []

    def isolated(**kwargs):
        calls.append(kwargs)
        kwargs["output"].mkdir()
        (kwargs["output"] / "worker-result.json").write_text(json.dumps(resumed))
        return {"cleanup_verified": True}

    monkeypatch.setattr(campaign_continuation_smoke, "run_isolated", isolated)
    monkeypatch.setattr(
        campaign_continuation_smoke.subprocess,
        "check_output",
        lambda args, **kwargs: "resumed-revision" if args[1] == "rev-parse" else "",
    )
    monkeypatch.setattr(
        campaign_continuation_smoke.sys,
        "argv",
        [
            "campaign_continuation_smoke",
            "--source",
            str(tmp_path / "source"),
            "--first-output",
            str(first_output),
            "--output",
            str(output),
            "--port",
            "5501",
            "--resume-port",
            "5502",
        ],
    )
    if not cleanup_verified:
        with pytest.raises(ValueError, match="teardown"):
            campaign_continuation_smoke.main()
        assert calls == []
        return
    campaign_continuation_smoke.main()
    assert len(calls) == 1
    assert calls[0]["port"] == 5502
    assert calls[0]["source_kind"] == "campaign_checkpoint"
    assert calls[0]["snapshot"] == checkpoint
    result = json.loads((output / "result.json").read_text())
    assert result["first_code_revision"] == "first-revision"
    assert result["code_revision"] == "resumed-revision"
    assert result["first_output"] == str(first_output)
