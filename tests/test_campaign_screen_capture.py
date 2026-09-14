from copy import deepcopy
from types import SimpleNamespace

import pytest

from fort_gym.bench.run import campaign_environment as module


def fixture(monkeypatch, statuses=None, screen=None):
    calls = []
    status = {"ok": True, "paused": True, "save_name": "fixture", "year": 30, "year_tick": 123}
    values = iter(statuses or [status, status])
    monkeypatch.setattr(module, "native_save_status", lambda: next(values))
    capture = screen or {"width": 2, "height": 1, "tiles": [[3, 15, 1], [32, 7, 0]]}
    env = module.NativeCampaignEnvironment.__new__(module.NativeCampaignEnvironment)
    env._verify_runtime = lambda: calls.append("runtime")

    def read():
        calls.append("screen")
        return capture

    env.client = SimpleNamespace(get_screen=read)
    return env, calls, capture, status


def test_native_screen_path_preserves_only_capture_without_state_reader(monkeypatch):
    env, calls, capture, _ = fixture(monkeypatch)
    capture["hidden_terrain"] = "never supplied"
    original = deepcopy(capture)
    result = env.screen_capture()
    assert calls == ["runtime", "screen", "runtime"]
    assert result == {
        "observation_profile": "native_screen_tiles/v1",
        "tile_order": "column_major",
        "width": 2,
        "height": 1,
        "tiles": [[3, 15, 1], [32, 7, 0]],
    }
    assert capture == original
    assert result["tiles"] is not capture["tiles"]


@pytest.mark.parametrize(
    "change",
    [
        {"ok": False},
        {"paused": False},
        {"paused": 1},
        {"save_name": ""},
        {"year": True},
        {"year_tick": "123"},
        {"year_tick": 403200},
    ],
)
def test_invalid_boundary_rejects_before_capture(monkeypatch, change):
    _, _, _, state = fixture(monkeypatch)
    env, calls, _, _ = fixture(monkeypatch, [{**state, **change}])
    with pytest.raises(RuntimeError, match="paused, identified fortress"):
        env.screen_capture()
    assert calls == ["runtime"]


@pytest.mark.parametrize(
    "change",
    [{"save_name": "different"}, {"year": 31}, {"year_tick": 124}, {"paused": False}],
)
def test_changed_boundary_is_not_returned_as_a_current_observation(monkeypatch, change):
    _, _, _, state = fixture(monkeypatch)
    env, calls, _, _ = fixture(monkeypatch, [state, {**state, **change}])
    with pytest.raises(RuntimeError):
        env.screen_capture()
    assert calls == ["runtime", "screen"]


def test_capture_shape_failure_is_not_replaced_with_a_default_screen(monkeypatch):
    env, _, _, _ = fixture(monkeypatch, screen={"width": 80, "height": 25, "tiles": []})
    with pytest.raises(ValueError, match="tile count"):
        env.screen_capture()


def test_changed_runtime_after_capture_is_rejected(monkeypatch):
    env, calls, _, _ = fixture(monkeypatch)

    def verify():
        if "screen" in calls:
            raise RuntimeError("wrong isolated runtime")

    env._verify_runtime = verify
    with pytest.raises(RuntimeError, match="wrong isolated runtime"):
        env.screen_capture()
