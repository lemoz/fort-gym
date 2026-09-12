"""Displayed-key transport: fake native calls are not gameplay acceptance."""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from fort_gym.bench.env import campaign_binding_keys as module
from fort_gym.bench.env import campaign_keyboard
from fort_gym.bench.env.display_key_catalog import BINDING_PROFILE, DISPLAY_KEYS, binding_event
from fort_gym.bench.env.keyboard_bindings import parse_bindings
from tests.test_campaign_keyboard import receipt as probe_receipt

RAW = (
    b"[BIND:CUSTOM_B:REPEAT_NOT]\n[KEY:b]\n"
    b"[BIND:HOTKEY_CARPENTER_BED:REPEAT_NOT]\n[KEY:b]\n"
    b"[BIND:STRING_A098:REPEAT_SLOW]\n[KEY:b]\n"
    b"[BIND:SELECT:REPEAT_NOT]\n[SYM:0:Enter]\n"
)


def install(monkeypatch, changes=None):
    index = parse_bindings(RAW)
    calls = []
    monkeypatch.setattr(module, "read_binding_index", lambda root: index)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    def probe(hook, mode, *args, **kwargs):
        assert mode == "probe"
        return probe_receipt(mode)

    def invoke(hook, root, year, tick, save, *events, **kwargs):
        calls.append(events)
        boundary = probe_receipt("probe")["after"]
        value = dict(
            schema_version="fortgym.campaign-binding-set/v1",
            ok=True,
            input_calls=1,
            command_mutation="completed",
            events=list(events),
            before=boundary,
            after=deepcopy(boundary),
        )
        if changes:
            changes(value)
        return value

    monkeypatch.setattr(campaign_keyboard, "run_lua_file", probe)
    monkeypatch.setattr(module, "run_lua_file", invoke)
    return calls


def execute(keys):
    return campaign_keyboard.execute_campaign_keys(
        keys,
        expected_dfroot=Path("/isolated"),
        year=30,
        year_tick=123,
        control_profile=BINDING_PROFILE,
    )


def test_one_complete_set_per_displayed_press(monkeypatch):
    calls = install(monkeypatch)
    result = execute(["b", "SYM:0:Enter", "b"])
    assert result["accepted"] is True
    assert calls == [
        ("CUSTOM_B", "HOTKEY_CARPENTER_BED", "STRING_A098"),
        ("SELECT",),
        ("CUSTOM_B", "HOTKEY_CARPENTER_BED", "STRING_A098"),
    ]
    assert result["result"]["keys_confirmed"] == 3
    assert result["result"]["command_mutation"] == "completed"
    assert [row["key"] for row in result["result"]["native_receipts"]] == ["b", "SYM:0:Enter", "b"]


def test_empty_batch_has_no_input_and_validates_binding_identity(monkeypatch):
    calls = install(monkeypatch)
    assert execute([])["result"]["command_mutation"] == "not_attempted"
    assert calls == []
    monkeypatch.setattr(
        module, "read_binding_index", lambda root: (_ for _ in ()).throw(ValueError("changed"))
    )
    assert execute([])["accepted"] is False
    assert calls == []


@pytest.mark.parametrize("keys", [["SELECT"], ["bb"], ["b", "bad"], [True], None, ["b"] * 101])
def test_invalid_displayed_batch_never_partially_dispatches(monkeypatch, keys):
    calls = install(monkeypatch)
    assert execute(keys)["accepted"] is False
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(input_calls=True),
        lambda r: r.update(input_calls=2),
        lambda r: r.update(events=["CUSTOM_B"]),
        lambda r: r.update(schema_version="wrong"),
        lambda r: r["after"].update(year_tick=124),
        lambda r: r["after"].update(paused=False),
        lambda r: r["after"].update(save_name="other"),
        lambda r: r["before"].update(year=True),
    ],
)
def test_bad_receipt_is_uncertain_and_never_replayed(monkeypatch, change):
    calls = install(monkeypatch, change)
    result = execute(["b", "b"])
    assert result["accepted"] is False and len(calls) == 1
    assert result["result"]["command_mutation"] == "unknown"
    assert result["result"]["keys_sent"] is None


def test_partial_failure_keeps_first_input_but_never_sends_third(monkeypatch):
    def reject_second(value):
        if len(calls) == 2:
            value.update(
                ok=False, input_calls=0, command_mutation="not_attempted", error="boundary_mismatch"
            )

    calls = install(monkeypatch, reject_second)
    result = execute(["b", "b", "b"])
    assert result["accepted"] is False and len(calls) == 2
    assert result["result"]["keys_confirmed"] == 1
    assert result["result"]["command_mutation"] == "partial"


def test_runtime_file_pin_and_capability_match_are_required(tmp_path, monkeypatch):
    path = tmp_path / "data/init/interface.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(RAW)
    with pytest.raises(ValueError, match="differs"):
        module.read_binding_index(tmp_path)
    monkeypatch.setattr(module, "BINDINGS_SHA256", hashlib.sha256(RAW).hexdigest())
    with pytest.raises(ValueError, match="capabilities"):
        module.read_binding_index(tmp_path)
    monkeypatch.setattr(module, "DISPLAY_KEYS", {"b", "SYM:0:Enter"})
    assert module.read_binding_index(tmp_path).resolve(binding_event("b")) == (
        "CUSTOM_B",
        "HOTKEY_CARPENTER_BED",
        "STRING_A098",
    )


def test_pinned_public_key_labels_and_legacy_nel_record():
    assert len(DISPLAY_KEYS) == 405
    assert {"b", "B", " ", "SYM:0:Enter", "SYM:2:n", "SYM:0:Backspace"} <= DISPLAY_KEYS
    assert not {"SELECT", "CUSTOM_B", "HOTKEY_CARPENTER_BED"} & DISPLAY_KEYS
    assert binding_event("SYM:1:Enter") == {"type": "symbol", "modifiers": 1, "value": "Enter"}
    with pytest.raises(ValueError):
        binding_event("SYM:3:Enter")  # No such binding in the declared file.
    value = parse_bindings("[BIND:STRING_A133:REPEAT_SLOW]\r\n[KEY:\x85]\r\n".encode())
    assert value.resolve({"type": "character", "value": "\x85"}) == ("STRING_A133",)
