"""Observer-only projection of rejected choices under the declared controls."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.watch import action_projection, receipt_action
from fort_gym.bench.env.screen_observation import TEXT_PROFILE, encode_screen
from scripts.campaign_watch_observe import snapshot


@pytest.fixture(params=["native_keyboard/v2", "native_keyboard_bindings/v1"])
def rejected(request):
    profile = request.param
    screen = {
        "width": 1,
        "height": 1,
        "tile_order": "column_major",
        "tiles": [[219, 7, 0]],
    }
    value = {
        "request_id": "one",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "control_profile": profile,
        "max_advance_ticks": 2000,
        "screen": screen,
    }
    action = {
        "type": "KEYSTROKE",
        "params": {"keys": ["SYM:0:>"]},
        "advance_ticks": 0,
        "intent": "Inspect the lower level",
        "memory_update": "private attempted memory",
    }
    result = {
        "control_profile": profile,
        "observation_profile": TEXT_PROFILE,
        "screen_sha256": digest(encode_screen(screen, TEXT_PROFILE)),
        "action_grammar_valid": False,
        "action": None,
        "native_action_dispatched": False,
        "error": "Keyboard keys must be supported native interface events",
        "transport_receipt": {
            "accepted": True,
            "dispatched": True,
            "model_requested": value["model"],
            "reasoning_effort_requested": "medium",
            "auth_mode": "chatgpt",
            "transport": "codex-exec-chatgpt/v1",
            "reported_charge_usd": None,
            "usage_complete": True,
            "total_tokens": 123,
            "usage": {"total_tokens": 123},
            "native_game_commands": 0,
            "timed_out": False,
            "interrupted": False,
            "response": action,
        },
    }
    return value, result, action


def test_typed_rejection_preserves_choice_but_publishes_no_private_memory(rejected):
    request, result, action = rejected
    before = deepcopy((request, result))
    recovered = receipt_action(request, result)
    assert recovered == action
    public = action_projection(recovered)
    assert public["keys"] == ["SYM:0:>"]
    assert "memory" not in json.dumps(public)
    assert (request, result) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("control_profile", "wrong-profile"),
        ("screen_sha256", "b" * 64),
        ("native_action_dispatched", True),
        ("action_grammar_valid", True),
    ],
)
def test_wrong_control_screen_or_dispatch_cannot_be_projected(rejected, field, value):
    request, result, _ = rejected
    result[field] = value
    with pytest.raises(ValueError):
        receipt_action(request, result)


def test_live_snapshot_keeps_rejected_frame_and_status(tmp_path, rejected):
    request, result, action = rejected
    folder = tmp_path / "model/one"
    folder.mkdir(parents=True)
    for name, value in [
        ("summary", {"decision_index": 0, "request_id": "one"}),
        ("request", request),
        ("response", {"request_sha256": digest(request), "result": result}),
    ]:
        (folder / (name + ".json")).write_text(json.dumps(value))
    now = int((folder / "request.json").stat().st_mtime)
    public = snapshot(
        tmp_path,
        {
            "model": request["model"],
            "run_id": "rejected-controls",
            "saved_checkpoint_cursor": 64,
        },
        alive=True,
        now=now,
    )
    assert public["frame"]["decision"] == 65
    assert public["frame"]["action_status"] == "rejected"
    assert public["frame"]["action"]["keys"] == action["params"]["keys"]
    assert public["status"] == "running"
    assert "private" not in json.dumps(public)
