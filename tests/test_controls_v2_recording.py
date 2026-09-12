"""Corrected controls replays preserve actual outcomes and their distinct routes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "web/static/recordings"
IDENTITY = "controls-v2-p1-shortcuts-1-128"


def test_v2_shortcuts_replay_is_exactly_the_audited_two_window_export():
    raw = (RECORDINGS / (IDENTITY + ".json")).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "9063c997563bd5c00eb3726acfff77088a50877dd66aeb12a95662b46c62d17b"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "628112a07c1181ce5fca4f94aa706c59579b60d8c867c1ae45983b3bcf179cff"
    assert data["control_profile"] == "native_keyboard_selected_workshop_jobs/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 68200
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][-1]["after"]["population"] == 7
    shortcuts = [frame for frame in data["frames"] if "shortcut" in frame["action"]]
    assert len(shortcuts) == 12
    assert sum(frame["action"]["shortcut"]["quantity"] for frame in shortcuts) == 36
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 574
    assert all(frame["accepted"] for frame in data["frames"])
    forbidden = {"memory", "memory_update", "reasoning", "analysis", "request", "response",
                 "provider_events", "account", "access_token", "api_key", "prompt"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(data)


def test_all_six_v2_replays_are_present_without_claiming_a_control_ranking():
    catalog = json.loads((RECORDINGS / "catalog.json").read_text())["recordings"]
    assert catalog[0]["id"] == "controls-v2-p3-keyboard-1-128"
    assert catalog[1]["id"] == "controls-v2-p3-shortcuts-1-128"
    assert catalog[2]["id"] == "controls-v2-p2-shortcuts-1-128"
    assert catalog[3]["id"] == "controls-v2-p2-keyboard-1-128"
    assert catalog[4]["id"] == "controls-v2-p1-keyboard-1-128"
    assert catalog[5]["id"] == IDENTITY
    assert catalog[6]["id"] == "controls-p1-keyboard-1-128"
    assert "campaign" not in catalog[0]
    html = (ROOT / "web/worlds.html").read_text()
    assert "68,200 game ticks" in html and "queued jobs are not completed products" in html
    assert "first matched pair uses the same seed and 128-decision limit" in html
    assert "one pair remains" not in html
    assert "All three matched pairs are recorded" in html
    assert "not independent worlds" in html
    assert "70,900 game ticks" in html and "43 food and 135 drinks" in html
    assert "paired keyboard run is still pending a final result" not in html
    assert "do not establish sustainability" in html
    assert "51,900 game ticks" in html and "61 food and 122 drinks" in html
    assert "One recorded drowning" in html
    assert "second pair's shortcuts run is still pending" not in html
    assert "49,600 game ticks" in html and "40 food and 136 drinks" in html
    assert "4,014,250 returned tokens" in html and "subscription dollar charges were not reported" in html
    assert "58,200 game ticks" in html and "56 food and 161 drinks" in html
    assert "3,621,402 returned tokens" in html and "final keyboard result remains" not in html
    assert "46,400 game ticks" in html and "42 food and 122 drinks" in html
    assert "3,753,509 returned tokens" in html and "751 key presses" in html


def test_final_keyboard_replay_preserves_the_exact_saved_native_result():
    raw = (RECORDINGS / "controls-v2-p3-keyboard-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "337ca3bd834be6f50c2d09afbd3668228eee69d142e65d632f0b013974cdb337"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "52ecd5c277a001b91de5e1d62e76e5c09567bc001a9a6177fe345de55e9b1f58"
    assert data["control_profile"] == "native_keyboard_bindings/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 46400
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][-1]["after"]["population"] == 7
    assert all("shortcut" not in frame["action"] for frame in data["frames"])
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 751
    assert all(frame["accepted"] for frame in data["frames"])


def test_v2_pair3_shortcuts_preserves_its_original_audited_export():
    raw = (RECORDINGS / "controls-v2-p3-shortcuts-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "02b139ad1021de3e560d20a2404944121cfc896b5477180c8c3e3a0dde71226a"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "432b19374f5e5c1260adcbd390679feb2e8cf83775e10e1ae56fec875396f106"
    assert data["control_profile"] == "native_keyboard_selected_workshop_jobs/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 58200
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][-1]["after"]["population"] == 7
    shortcuts = [frame for frame in data["frames"] if "shortcut" in frame["action"]]
    assert len(shortcuts) == 12
    assert sum(frame["action"]["shortcut"]["quantity"] for frame in shortcuts) == 49
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 741
    assert all(frame["accepted"] for frame in data["frames"])


def test_v2_keyboard_replay_is_the_audited_128_decision_own_save_export():
    raw = (RECORDINGS / "controls-v2-p1-keyboard-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "280e6193242088f0743a000cc84ace5cefa23b82d4c9877f73abf46597c533f5"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "3302c95c7e3855f5621e60033b1d97b6bd0803f3609cced273233535039a3a5b"
    assert data["control_profile"] == "native_keyboard_bindings/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 70900
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][-1]["after"]["population"] == 7
    assert all("shortcut" not in frame["action"] for frame in data["frames"])
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 669
    assert all(frame["accepted"] for frame in data["frames"])


def test_v2_pair2_shortcuts_preserves_its_original_audited_export():
    raw = (RECORDINGS / "controls-v2-p2-shortcuts-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "4890518b7d6c550a49e25a6c134945141a16c136dc9f50721d605ab0f89db1cd"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "29535eb68e81a633675cf983f25674a9855a620e6ab0667590ec11af7b663b8b"
    assert data["control_profile"] == "native_keyboard_selected_workshop_jobs/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 49600
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][-1]["after"]["population"] == 7
    shortcuts = [frame for frame in data["frames"] if "shortcut" in frame["action"]]
    assert len(shortcuts) == 11
    assert sum(frame["action"]["shortcut"]["quantity"] for frame in shortcuts) == 43
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 675
    assert all(frame["accepted"] for frame in data["frames"])


def test_v2_pair2_keyboard_preserves_audited_progress_and_population_loss():
    raw = (RECORDINGS / "controls-v2-p2-keyboard-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "9d15f665d816f9ba53f6b332480bc6017c192bcc8f50d73a208c0e067563c76e"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "5ddf1e6718dab2e8351e8dc24a2afe5071cd2592"
    assert data["audit_sha256"] == "ba2df79ae65339ed9681446d530b25c24a4ae5136764cae979b38420bf8ddf14"
    assert data["control_profile"] == "native_keyboard_bindings/v1"
    assert data["saved_through_decision"] == 128
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 51900
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert data["frames"][84]["after"]["population"] == 7
    assert data["frames"][85]["after"]["population"] == 6
    assert data["frames"][-1]["after"]["population"] == 6
    assert all("shortcut" not in frame["action"] for frame in data["frames"])
    assert sum(len(frame["action"]["keys"]) for frame in data["frames"]) == 731
    assert all(frame["accepted"] for frame in data["frames"])
