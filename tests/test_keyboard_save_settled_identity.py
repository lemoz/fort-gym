"""Separate-RPC identity proof must not relax the native save invariants."""

import json
from copy import deepcopy

import pytest

from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_save import (
    MENU_SETTLED_IDENTITY_SAVE_PROFILE, MenuPreservingSnapshotter, validate_menu_save,
)
from fort_gym.bench.run.keyboard_save_lua import MENU_SETTLED_IDENTITY_SAVE_LUA
from fort_gym.bench.run.keyboard_save_probe import MENU_IDENTITY_PROBE_LUA
from tests.test_campaign_save import NativeSaveSimulation
from tests.test_keyboard_save_identity import semantic_receipt


def settled_receipt(root):
    value = semantic_receipt(root)
    value["schema_version"] = "fortgym.native-menu-save/v3"
    value["ui_before"]["unit_id"] = 12
    value["ui_after"]["unit_id"] = -1  # reproduced transient inline helper value
    probe = {"schema_version": "fortgym.native-menu-identity/v1",
             "native_boundary": deepcopy(value["native_before"]),
             "stack": deepcopy(value["original_stack"]), "ui": deepcopy(value["ui_before"])}
    value["identity_before"], value["identity_after"] = probe, deepcopy(probe)
    return value


def validate(value, root):
    return validate_menu_save(value, root, profile=MENU_SETTLED_IDENTITY_SAVE_PROFILE)


def test_inline_discrepancy_remains_inspectable_but_settled_identity_is_equal(tmp_path):
    value = settled_receipt(tmp_path)
    assert validate(value, tmp_path) == value
    assert value["ui_before"] != value["ui_after"]
    assert value["identity_before"] == value["identity_after"]


@pytest.mark.parametrize("probe", ["identity_before", "identity_after"])
@pytest.mark.parametrize("path,value", [
    (("schema_version",), "unknown"),
    (("extra",), 0),
    (("native_boundary", "dfroot"), "/another"),
    (("native_boundary", "save_name"), "another-save"),
    (("native_boundary", "year"), 31),
    (("native_boundary", "year_tick"), 201),
    (("native_boundary", "paused"), 1),
    (("native_boundary", "paused"), False),
    (("native_boundary", "autosave_requested"), 0),
    (("native_boundary", "autosave_requested"), True),
    (("stack",), []),
    (("stack", 0, "address"), "other"),
    (("stack", 0, "type"), "<type: viewscreen_joblistst>"),
    (("ui", "focus"), "other"),
    (("ui", "unit_id"), -1),
    (("ui", "building_id"), 42),
    (("ui", "job_id"), 42),
    (("ui", "item_id"), 42),
    (("ui", "unit_id"), True),
    (("ui", "cursor", "x"), 20),
    (("ui", "viewport", "z"), 20),
    (("ui", "extra"), 0),
])
def test_changed_invalid_or_unbound_external_identity_fails(tmp_path, probe, path, value):
    source = settled_receipt(tmp_path)
    target = source[probe]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(CampaignSaveError):
        validate(source, tmp_path)


def test_matching_external_witnesses_still_need_to_match_operation_start(tmp_path):
    value = settled_receipt(tmp_path)
    for key in ("identity_before", "identity_after"):
        value[key]["ui"]["unit_id"] = 13
    with pytest.raises(CampaignSaveError, match="changed across save RPC"):
        validate(value, tmp_path)


@pytest.mark.parametrize("field", ["identity_before", "identity_after"])
def test_missing_witness_never_falls_back_to_inline_equality(tmp_path, field):
    value = settled_receipt(tmp_path)
    value["ui_after"] = deepcopy(value["ui_before"])
    del value[field]
    with pytest.raises(CampaignSaveError, match="probe is invalid"):
        validate(value, tmp_path)


@pytest.mark.parametrize("failure", [None, "before", "operation", "after", "changed_after", "world"])
def test_three_rpc_sequence_retains_evidence_and_never_retries(tmp_path, failure):
    native = NativeSaveSimulation(tmp_path)
    source = settled_receipt(native.dfroot)
    calls = []
    if failure == "changed_after":
        source["identity_after"]["ui"]["unit_id"] = 13

    def execute(expression, *, timeout):
        phase = ["before", "operation", "after"][len(calls)]
        calls.append(phase)
        if phase == "operation":
            assert expression.endswith(MENU_SETTLED_IDENTITY_SAVE_LUA) and timeout == 120
            native.request()
            native.status()
            native.status()
        else:
            assert expression.endswith(MENU_IDENTITY_PROBE_LUA) and timeout == 5
        if failure == phase:
            raise RuntimeError("Uncertain RPC")
        value = ({key: item for key, item in source.items()
                  if key not in ("identity_before", "identity_after")}
                 if phase == "operation" else source["identity_" + phase])
        return json.dumps(value)

    snapshotter = MenuPreservingSnapshotter(
        dfroot=native.dfroot, profile=MENU_SETTLED_IDENTITY_SAVE_PROFILE,
        execute=execute, status=native.status,
        screen_capture=lambda: {"width": 1, "height": 1, "tiles": [[32, 7, 0]]},
        observe=lambda: {"population": 8 if native.requests and failure == "world" else 7},
    )
    if failure:
        with pytest.raises((CampaignSaveError, RuntimeError)):
            snapshotter.capture(tmp_path / "snapshot")
    else:
        result = snapshotter.capture(tmp_path / "snapshot")
        assert result["save_operation"] == source
        assert result["snapshot_profile"] == MENU_SETTLED_IDENTITY_SAVE_PROFILE
        assert result["world_observations_unchanged"] is result["ui_identity_unchanged"] is True
    assert calls == (["before"] if failure == "before" else
                     ["before", "operation"] if failure == "operation" else
                     ["before", "operation", "after"])
    assert native.requests == (0 if failure == "before" else 1)
    if failure not in ("before", "operation"):
        assert "save_operation_raw" in snapshotter.attempt
    if failure in ("before", "operation", "after", "changed_after"):
        assert snapshotter.receipt is None
        assert not (tmp_path / "snapshot").exists()


def test_probe_source_is_read_only_and_v3_keeps_the_native_operation():
    from fort_gym.bench.run.keyboard_save_lua import MENU_IDENTITY_SAVE_LUA
    assert MENU_SETTLED_IDENTITY_SAVE_LUA.replace("fortgym.native-menu-save/v3",
                                                "fortgym.native-menu-save/v2") == MENU_IDENTITY_SAVE_LUA
    assert all(operation not in MENU_IDENTITY_PROBE_LUA
               for operation in (":logic(", "simulateInput", "hideGuard", "autosave_request = true"))
