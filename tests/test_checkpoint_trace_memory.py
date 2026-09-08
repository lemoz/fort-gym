"""Expanded trace rows must not overlap source validation during saving."""
import json
import weakref
from types import SimpleNamespace

from fort_gym.bench.run import campaign_checkpoint, keyboard_recovery
from tests.test_campaign_checkpoint import campaign as campaign
from tests.test_campaign_codex_keyboard import agent
from tests.test_keyboard_recovery import loaded_fixture, source as source


class TrackedRow(dict):
    pass


def test_checkpoint_releases_parsed_rows_before_native_capture(tmp_path, campaign, monkeypatch):
    references = []
    original_loads = json.loads

    def tracked_loads(value, *args, **kwargs):
        result = original_loads(value, *args, **kwargs)
        if isinstance(result, dict) and "step" in result and "run_id" in result:
            result = TrackedRow(result)
            references.append(weakref.ref(result))
        return result

    monkeypatch.setattr(campaign_checkpoint, "json", SimpleNamespace(
        loads=tracked_loads, dumps=json.dumps,
    ))
    original = campaign["snapshotter"].capture

    def capture(destination):
        assert references and all(reference() is None for reference in references)
        return original(destination)

    monkeypatch.setattr(campaign["snapshotter"], "capture", capture)
    manifest = campaign_checkpoint.create_checkpoint(tmp_path / "checkpoint", **campaign)
    assert manifest["payload"]["next_step"] == 1


def test_recovery_releases_parsed_history_before_checkpoint_creation(tmp_path, source, monkeypatch):
    plan = keyboard_recovery.inspect_recovery_source(**source)
    environment = loaded_fixture(tmp_path, source)
    references = []
    original_rows = keyboard_recovery._rows

    def tracked_rows(path):
        rows = original_rows(path)
        if path.name == "trace.jsonl":
            rows = [TrackedRow(row) for row in rows]
            references.extend(weakref.ref(row) for row in rows)
        return rows

    monkeypatch.setattr(keyboard_recovery, "_rows", tracked_rows)
    original = keyboard_recovery.CampaignLoop.checkpoint

    def checkpoint(loop, *args, **kwargs):
        assert references and all(reference() is None for reference in references)
        return original(loop, *args, **kwargs)

    monkeypatch.setattr(keyboard_recovery.CampaignLoop, "checkpoint", checkpoint)
    result = keyboard_recovery.reconcile_loaded_tail(
        **source, plan=plan, agent=agent(), environment=environment, snapshotter=environment,
        output=tmp_path / "recovered", revision="memory-regression",
    )
    assert result["checkpoint_verified"] is True
    assert result["model_calls"] == result["native_input_commands"] == result["native_ticks_requested"] == 0

