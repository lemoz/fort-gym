"""Website-only shortcut projection and relay contracts; not gameplay evidence."""
from copy import deepcopy
import json

import pytest

from fort_gym.bench.api import watch
from scripts.receive_watch_relay import receive


def action():
    return {"type": "WORKSHOP_JOB", "params": {"item": "bed", "quantity": 2},
            "advance_ticks": 100, "intent": "Queue two beds", "memory_update": "PRIVATE"}


def feed():
    return {"schema_version": watch.SCHEMA, "owner_alive": True, "observed_at_unix": 100,
            "run_id": "shortcut-fixture", "model": "gpt-6-astra", "private_memory": "PRIVATE",
            "frame": {"decision": 1, "captured_at_unix": 100,
                      "screen": {"width": 1, "height": 1, "tile_order": "column_major",
                                 "runs": [[1, 32, 7, 0]]},
                      "action": watch.action_projection(action()),
                      "action_status": "chosen_not_execution_verified"}}


def test_shortcut_projection_exposes_only_the_public_job_request():
    result = watch.action_projection({**action(), "workshop_id": 99})
    assert result == {"intent": "Queue two beds", "keys": [], "advance_ticks": 100,
                      "shortcut": {"type": "WORKSHOP_JOB", "item": "bed", "quantity": 2}}
    assert "PRIVATE" not in json.dumps(result)
    assert "workshop_id" not in result


@pytest.mark.parametrize("item", ["bed", "door", "table", "chair", "barrel", "bin", "brew"])
def test_receiver_retains_shortcut_semantics_without_private_fields(tmp_path, item):
    (tmp_path / "web/static").mkdir(parents=True)
    value = feed()
    value["frame"]["action"]["shortcut"]["item"] = item
    value["frame"]["action"]["memory_update"] = "PRIVATE"
    result = receive(tmp_path, json.dumps(value).encode(), run_id="shortcut-fixture", now=100)
    assert result == {"published": True, "run_id": "shortcut-fixture", "status": "running", "decision": 1}
    raw = (tmp_path / "web/static/live/watch-active.json").read_bytes()
    public = json.loads(raw)
    assert public["frame"]["action"]["shortcut"] == {"type": "WORKSHOP_JOB", "item": item, "quantity": 2}
    assert public["frame"]["action"]["keys"] == []
    assert public["frame"]["action_status"] == "chosen_not_execution_verified"
    assert b"PRIVATE" not in raw and b"memory" not in raw


@pytest.mark.parametrize("quantity", [True, False, 0, 6, 1.5, "2", None])
def test_shortcut_quantity_is_not_coerced(quantity):
    with pytest.raises(ValueError):
        watch.action_projection({**action(), "params": {"item": "bed", "quantity": quantity}})


@pytest.mark.parametrize("change", [None, {}, {"type": "OTHER", "item": "bed", "quantity": 1},
    {"type": "WORKSHOP_JOB", "item": "unknown", "quantity": 1},
    {"type": "WORKSHOP_JOB", "item": "bed", "quantity": 1, "workshop_id": 99}])
def test_malformed_shortcut_cannot_replace_a_valid_relay(tmp_path, change):
    (tmp_path / "web/static").mkdir(parents=True)
    value = feed()
    receive(tmp_path, json.dumps(value).encode(), run_id="shortcut-fixture", now=100)
    target = tmp_path / "web/static/live/watch-active.json"
    before = target.read_bytes()
    value["frame"]["action"]["shortcut"] = change
    with pytest.raises(ValueError):
        receive(tmp_path, json.dumps(value).encode(), run_id="shortcut-fixture", now=100)
    assert target.read_bytes() == before


def test_mixed_keys_are_rejected_and_keyboard_frames_remain_unchanged():
    value = feed()
    value["frame"]["action"]["keys"] = ["q"]
    with pytest.raises(ValueError):
        watch.project_live(value, now=100)
    keyboard = deepcopy(value)
    del keyboard["frame"]["action"]["shortcut"]
    assert watch.project_live(keyboard, now=100)["frame"] == keyboard["frame"]
