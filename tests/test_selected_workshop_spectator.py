"""Public actions expose a route and job request, never private model memory."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.api import watch
from fort_gym.bench.env.workshop_job_profile import CONTROL_PROFILE
from scripts.export_displayed_key_recording import recorded_action
from tests.test_selected_workshop_profile import job_action


def test_shortcut_projection_is_explicit_and_has_no_keys_or_private_memory():
    value = {**job_action(), "memory_update": "private", "workshop_id": 99}
    result = watch.action_projection(value)
    assert result == {
        "intent": value["intent"], "keys": [], "advance_ticks": 100,
        "shortcut": {"type": "WORKSHOP_JOB", "item": "bed", "quantity": 2},
    }
    assert "private" not in json.dumps(result) and "workshop_id" not in result


@pytest.mark.parametrize("quantity", [True, 0, 6, "2", 1.5])
def test_spectator_cannot_invent_or_coerce_quantity(quantity):
    with pytest.raises(ValueError):
        watch.action_projection({**job_action(), "params": {"item": "bed", "quantity": quantity}})


def test_unavailable_workshop_remains_an_explicit_failed_action_in_recording():
    action = job_action()
    row = {"action": action, "execute": {"accepted": False, "result": {
        "action_route": "selected_workshop_job", "command_mutation": "not_attempted",
        "jobs_queued": 0,
    }}}
    request = {"control_profile": CONTROL_PROFILE}
    assert recorded_action(watch, request, {"action": action}, row) == action
    for profile in ("native_keyboard_bindings/v1", "native_keyboard/v2"):
        with pytest.raises(ValueError):
            recorded_action(watch, {"control_profile": profile}, {"action": action}, row)
    for key, value in (("command_mutation", "unknown"), ("jobs_queued", 1), ("jobs_queued", False)):
        changed = deepcopy(row)
        changed["execute"]["result"][key] = value
        with pytest.raises(ValueError):
            recorded_action(watch, request, {"action": action}, changed)


def test_live_projection_keeps_shortcut_and_rejects_mixed_or_private_fields():
    data = {
        "schema_version": watch.SCHEMA, "owner_alive": True, "observed_at_unix": 100,
        "run_id": "shortcut-fixture", "model": "gpt-6-astra",
        "frame": {
            "decision": 1, "captured_at_unix": 100,
            "screen": {"width": 1, "height": 1, "tile_order": "column_major", "runs": [[1, 32, 7, 0]]},
            "action": watch.action_projection(job_action()),
            "action_status": "chosen_not_execution_verified",
        },
    }
    projected = watch.project_live(data, now=100)
    assert projected["frame"]["action"] == data["frame"]["action"]
    for value in (None, {}, {"type": "WORKSHOP_JOB", "item": "bed", "quantity": 1, "memory": "secret"}):
        changed = deepcopy(data)
        changed["frame"]["action"]["shortcut"] = value
        with pytest.raises(ValueError):
            watch.project_live(changed, now=100)
    changed = deepcopy(data)
    changed["frame"]["action"]["keys"] = ["q"]
    with pytest.raises(ValueError):
        watch.project_live(changed, now=100)
