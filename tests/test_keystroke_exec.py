from __future__ import annotations

from fort_gym.bench.env.keystroke_exec import VALID_KEYS


def test_valid_keys_include_real_building_construction_path() -> None:
    assert "D_BUILDING" in VALID_KEYS
    assert "HOTKEY_BUILDING_WORKSHOP" in VALID_KEYS
    assert "HOTKEY_BUILDING_WORKSHOP_CARPENTER" in VALID_KEYS


def test_valid_keys_include_native_manager_path() -> None:
    assert "D_JOBLIST" in VALID_KEYS
    assert "UNITJOB_MANAGER" in VALID_KEYS
    assert "MANAGER_NEW_ORDER" in VALID_KEYS
