"""Exercise native fixture sequencing using explicit test doubles, never gameplay."""

import json
from types import SimpleNamespace

import pytest

from scripts import campaign_workshop_smoke as fixture


@pytest.mark.parametrize("complete", [True, False])
def test_fixture_retains_controls_ticks_save_and_close_without_any_model(
    tmp_path, monkeypatch, complete
):
    from fort_gym.bench import dfhack_backend, dfhack_exec
    from fort_gym.bench.run import campaign_environment, campaign_save

    clock = 19309
    actions = []
    closed = []

    class Environment:
        def __init__(self, *, expected_dfroot, workshop_placement_policy):
            assert expected_dfroot == tmp_path / "runtime"
            assert workshop_placement_policy == "dfhack_047_ground/v1"

        def _verify_runtime(self):
            pass

        def observe(self):
            return {
                "year": 30,
                "year_tick": clock,
                "work": {"carpenter_workshops_usable": int(complete and len(actions) >= 4)},
            }

        def apply(self, action, state):
            actions.append(action)
            accepted = action["type"] != "BUILD" or len(actions) >= 4
            return {
                "accepted": accepted,
                "why": None if accepted else "no_building_material",
                "command_mutation": "not_attempted",
            }

        def advance(self, ticks, state):
            nonlocal clock
            clock += ticks
            return self.observe(), {"ok": True, "ticks_advanced": ticks}

        def close(self):
            closed.append(True)

    monkeypatch.setenv("DFROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(campaign_environment, "NativeCampaignEnvironment", Environment)
    monkeypatch.setattr(
        dfhack_backend,
        "build_workshop",
        lambda **kw: {"error": "tile_not_open_floor", "command_mutation": "not_attempted"},
    )
    monkeypatch.setattr(
        dfhack_exec,
        "run_lua_expr",
        lambda *a, **kw: json.dumps(
            {
                "version": "0.47.05-r8",
                "wood": {"free_flags": 1},
                "trees": [[5, 6, 7]],
                "workshop": {"x": 1, "y": 2, "z": 3, "shapes": {"SHRUB": 9}},
            }
        ),
    )
    monkeypatch.setattr(
        campaign_save,
        "NativeSaveSnapshotter",
        lambda **kw: SimpleNamespace(capture=lambda path: {"verified_test_snapshot": True}),
    )
    result = fixture.worker(tmp_path)
    assert result["autonomous_gameplay"] is False and result["provider_calls"] == 0
    assert result["terrain_predicate_verified"] is True
    assert result["workshop_complete"] is complete
    assert [action["type"] for action in actions[:4]] == ["WAIT", "BUILD", "DIG", "BUILD"]
    assert clock - 19309 == sum(action["advance_ticks"] for action in actions)
    assert result["final_snapshot"] == {"verified_test_snapshot": True}
    assert json.loads((tmp_path / "worker-result.json").read_text()) == result
    assert closed == [True]
