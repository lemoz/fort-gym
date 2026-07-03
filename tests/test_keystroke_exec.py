from __future__ import annotations

from fort_gym.bench.env.keystroke_exec import VALID_KEYS, _translate_key


def test_valid_keys_include_real_building_construction_path() -> None:
    assert "D_BUILDING" in VALID_KEYS
    assert "HOTKEY_BUILDING_WORKSHOP" in VALID_KEYS
    assert "HOTKEY_BUILDING_WORKSHOP_CARPENTER" in VALID_KEYS


def test_valid_keys_include_native_manager_path() -> None:
    assert "D_JOBLIST" in VALID_KEYS
    assert "UNITJOB_MANAGER" in VALID_KEYS
    assert "MANAGER_NEW_ORDER" in VALID_KEYS


def test_valid_keys_include_native_workshop_task_path() -> None:
    assert "D_BUILDJOB" in VALID_KEYS
    assert "BUILDJOB_ADD" in VALID_KEYS
    assert "BUILDJOB_REPEAT" in VALID_KEYS
    assert "BUILDJOB_NOW" in VALID_KEYS


def test_keyboard_cursor_aliases_translate_to_df_cursor_keys() -> None:
    assert _translate_key("KEYBOARD_CURSOR_DOWN", None) == "CURSOR_DOWN"
    assert _translate_key("KEYBOARD_CURSOR_UP", None) == "CURSOR_UP"
