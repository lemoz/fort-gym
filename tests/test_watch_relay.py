"""The relay accepts only a bounded spectator projection, never game controls."""

import json

import pytest

from scripts.receive_watch_relay import receive


@pytest.fixture
def root(tmp_path):
    (tmp_path / "web/static").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def value():
    return {
        "schema_version": "fortgym.watch-live/v1",
        "owner_alive": True,
        "observed_at_unix": 1000,
        "run_id": "astra-window",
        "model": "gpt-6-astra",
        "frame": {
            "decision": 257,
            "captured_at_unix": 990,
            "screen": {
                "width": 1,
                "height": 1,
                "tile_order": "column_major",
                "runs": [[1, 219, 7, 0]],
            },
            "action": {"intent": "Inspect the workshop", "keys": ["q"], "advance_ticks": 0},
            "action_status": "chosen_not_execution_verified",
        },
    }


def send(root, value, now=1000, run_id="astra-window"):
    return receive(root, json.dumps(value).encode(), run_id=run_id, now=now)


def target(root):
    return root / "web/static/live/watch-active.json"


def test_receiver_filters_private_fields_and_preserves_real_capture(root, value):
    value["private_memory"] = "DO_NOT_PUBLISH"
    value["frame"]["action"]["memory_update"] = "DO_NOT_PUBLISH"
    result = send(root, value)
    assert result == {
        "published": True,
        "run_id": "astra-window",
        "status": "running",
        "decision": 257,
    }
    raw = target(root).read_bytes()
    assert b"DO_NOT_PUBLISH" not in raw and b"memory" not in raw
    data = json.loads(raw)
    assert data["frame"]["screen"] == value["frame"]["screen"]
    assert data["frame"]["action_status"] == "chosen_not_execution_verified"
    assert target(root).stat().st_mode & 0o777 == 0o644
    assert list(target(root).parent.glob(".watch-*")) == [target(root).parent / ".watch-lock"]


@pytest.mark.parametrize(
    "case", ["stale", "future", "boolean", "wrong_id", "executed", "bad_screen", "oversized"]
)
def test_invalid_input_cannot_replace_current_feed(root, value, case):
    send(root, value)
    before = target(root).read_bytes()
    if case == "stale":
        value["observed_at_unix"] = 969
    elif case == "future":
        value["observed_at_unix"] = 1006
    elif case == "boolean":
        value["owner_alive"] = 1
    elif case == "wrong_id":
        value["run_id"] = "another"
    elif case == "executed":
        value["frame"]["action_status"] = "execution_verified"
    elif case == "bad_screen":
        value["frame"]["screen"]["runs"] = [[2, 219, 7, 0]]
    else:
        value["oversized"] = "x" * 2_000_000
    with pytest.raises(ValueError):
        send(root, value)
    assert target(root).read_bytes() == before


def test_different_live_owner_cannot_take_over_until_stopped_or_expired(root, value):
    send(root, value)
    value["run_id"] = "next-window"
    with pytest.raises(ValueError, match="Another active"):
        send(root, value, run_id="next-window")
    value["observed_at_unix"] = 1031
    assert send(root, value, now=1031, run_id="next-window")["published"] is True


@pytest.mark.parametrize("regression", ["time", "decision", "missing_frame"])
def test_same_owner_cannot_regress(root, value, regression):
    send(root, value)
    if regression == "time":
        value["observed_at_unix"] -= 1
    elif regression == "decision":
        value["frame"]["decision"] -= 1
    else:
        value["frame"] = None
    with pytest.raises(ValueError, match="regressed"):
        send(root, value)


def test_terminal_feed_preserves_last_frame_and_reports_stopped(root, value):
    send(root, value)
    value["owner_alive"] = False
    assert send(root, value)["status"] == "stopped"
    assert json.loads(target(root).read_bytes())["frame"] == value["frame"]


@pytest.mark.parametrize("where", ["directory", "file", "lock"])
def test_symlink_destination_is_rejected(root, value, where):
    outside = root / "outside"
    outside.mkdir()
    live = root / "web/static/live"
    if where == "directory":
        live.symlink_to(outside)
    else:
        live.mkdir()
        (live / ("watch-active.json" if where == "file" else ".watch-lock")).symlink_to(
            outside / "private"
        )
    with pytest.raises((ValueError, OSError)):
        send(root, value)
    assert not (outside / "private").exists()
