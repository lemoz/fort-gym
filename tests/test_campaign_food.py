"""Private native measurement must never alter the playing model's condition."""
from copy import deepcopy
import json

import pytest

from fort_gym.bench.food_inventory import COUNTERS, SCHEMA, SOURCE, SCOPE
from fort_gym.bench.run import campaign_food as module
from fort_gym.bench.eval.campaign_profile import metrics_from_state
from tests.test_campaign_profile_v2 import native_v2
from tests.test_campaign_codex_keyboard import start, decision


def measurement(root="/fixture"):
    boundary = {"dfroot": str(root), "save_name": "fixture", "paused": True,
                "year": 30, "year_tick": 123}
    inventory = {key: 0 for key in COUNTERS}
    inventory.update(schema_version=SCHEMA, source=SOURCE, scope=SCOPE,
                     predicate_argument=0, complete=True, units=27, scanned_units=27,
                     food_records=15, scanned_records=15)
    return {"schema_version": module.PROFILE, "available": True, "before": boundary,
            "after": dict(boundary), "inventory": inventory}


def state():
    result = native_v2()
    result.update(year=30, year_tick=123, private_food_measurement=measurement())
    return result


def test_native_measurement_reads_only_once_and_normalizes_extra_content(tmp_path, monkeypatch):
    raw = measurement(tmp_path)
    raw["inventory"]["private_items"] = "not retained"
    raw["before"]["extra"] = "not retained"
    calls = []
    def run(script, **kwargs):
        calls.append(script)
        assert kwargs == {"timeout": 5.0}
        assert "local expected_root=" + json.dumps(str(tmp_path)) in script
        assert "read_food_inventory" in script
        return json.dumps(raw)
    monkeypatch.setattr(module, "run_lua_expr", run)
    actual = module.read_food_measurement(expected_dfroot=tmp_path, year=30, year_tick=123)
    assert actual == measurement(tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [
    module.DFHackError("native unavailable"), OSError("transport unavailable"), "invalid-json",
])
def test_native_measurement_failure_is_unknown_metadata_not_a_gameplay_stop(tmp_path, monkeypatch, failure):
    def run(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(module, "run_lua_expr", run)
    value = module.read_food_measurement(expected_dfroot=tmp_path, year=30, year_tick=123)
    assert value["available"] is False and value["inventory"] is None
    assert value["error_type"]


@pytest.mark.parametrize("key,value", [
    ("year", 31), ("year_tick", 124), ("year_tick", True), ("paused", False),
    ("dfroot", "/different"), ("save_name", "different"),
])
def test_mismatched_native_read_boundary_cannot_become_food_count(tmp_path, monkeypatch, key, value):
    raw = measurement(tmp_path)
    raw["after"][key] = value
    monkeypatch.setattr(module, "run_lua_expr", lambda *args, **kwargs: json.dumps(raw))
    assert module.read_food_measurement(
        expected_dfroot=tmp_path, year=30, year_tick=123)["available"] is False


def test_private_food_count_does_not_promote_or_replace_ui_estimate():
    original = state()
    before = deepcopy(original)
    assert metrics_from_state(original)["food_stock"] == 27
    assert original == before and original["stocks"]["food"] == 45
    legacy = native_v2()
    assert metrics_from_state(legacy)["food_stock"] is None
    assert "private_food_measurement" not in legacy


@pytest.mark.parametrize("units", [0, 27])
def test_complete_zero_is_distinct_from_unknown(units):
    current = state()
    current["private_food_measurement"]["inventory"].update(units=units, scanned_units=units)
    assert metrics_from_state(current)["food_stock"] == units


@pytest.mark.parametrize("change", [
    "missing", "unavailable", "wrong_profile", "partial", "bad_counter", "old_calendar",
])
def test_unavailable_partial_or_stale_private_counts_remain_unknown(change):
    current = state()
    food = current["private_food_measurement"]
    if change == "missing":
        del current["private_food_measurement"]
    elif change == "unavailable":
        food["available"] = False
    elif change == "wrong_profile":
        food["schema_version"] = "other"
    elif change == "partial":
        food["inventory"].update(complete=False, units=None, list_read_failures=1)
    elif change == "bad_counter":
        food["inventory"]["units"] = True
    else:
        current["year_tick"] += 1
    assert metrics_from_state(current)["food_stock"] is None


def test_measurement_persists_in_trace_but_never_enters_model_inputs_or_feedback(tmp_path):
    sent = []
    def callback(screen, memory, feedback):
        sent.append((screen, memory, feedback))
        return decision(screen, memory, feedback)
    loop = start(tmp_path, callback)
    observe = loop.environment.observe
    def private_observation():
        current = observe()
        value = measurement()
        value["before"]["year_tick"] = value["after"]["year_tick"] = current["year_tick"]
        current["private_food_measurement"] = value
        return current
    loop.environment.observe = private_observation
    loop.step()
    loop.step()
    assert len(sent) == 2
    assert "food" not in json.dumps(sent)
    rows = [json.loads(line) for line in (tmp_path / "first/trace.jsonl").read_text().splitlines()]
    assert rows[-1]["state_after_advance"]["private_food_measurement"]["inventory"]["units"] == 27


@pytest.mark.parametrize("profile", [True, False, 0, "", "unknown", [], {}])
def test_invalid_profile_is_rejected_before_native_access(profile):
    with pytest.raises(ValueError, match="private food"):
        module.validate_profile(profile)

def test_declared_window_changes_only_private_measurement_and_continuation_identity():
    from pathlib import Path
    from fort_gym.bench.run.keyboard_config import load_window
    root = Path(__file__).resolve().parents[1]
    condition = root / "experiments/campaign_astra_keyboard_20260907.json"
    before, old = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908m.json")
    after, new = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908n.json")
    assert before == after
    assert old["continuation_from_next_step"] == 503 and new["continuation_from_next_step"] == 567
    assert new["private_measurement_profile"] == module.PROFILE
    assert "private_measurement_profile" not in old
    for key in ("steps_per_segment", "max_segments", "reset_memory", "reset_usage",
                "strategy_intervention", "snapshot_profile"):
        assert old[key] == new[key]
    assert "budget_extension" not in new and "restart" not in new


def test_worker_passes_declared_measurement_profile_without_changing_agent(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from scripts import campaign_keyboard_native as native
    root = Path(__file__).resolve().parents[1]
    supplied = []
    closed = []
    environment = SimpleNamespace(
        observe=lambda: {}, screen_capture=lambda: {}, close=lambda: closed.append(True),
        private_measurement_profile=module.PROFILE,
    )
    def create(**kwargs):
        supplied.append(kwargs)
        return environment
    monkeypatch.setattr(native, "NativeCampaignEnvironment", create)
    monkeypatch.setattr(native, "MenuPreservingSnapshotter", lambda **kwargs: object())
    def segment(**kwargs):
        assert kwargs["environment"] is environment
        assert kwargs["condition"]["observation_profile"] == "native_screen_text/v1"
        assert "private_measurement_profile" not in kwargs["agent"].configuration
        return {"fixture": True}
    monkeypatch.setattr(native, "run_keyboard_segment", segment)
    args = SimpleNamespace(
        condition=root / "experiments/campaign_astra_keyboard_20260907.json",
        window=root / "experiments/campaign_astra_keyboard_window_20260908n.json",
        runtime=tmp_path, exchange=tmp_path, output=tmp_path, checkpoint=tmp_path,
        latest_usage=tmp_path, cursor=567, revision="test-only", extend_budget=False,
    )
    assert native.worker(args) == {"fixture": True}
    assert supplied[0]["private_measurement_profile"] == module.PROFILE
    assert closed == [True]
