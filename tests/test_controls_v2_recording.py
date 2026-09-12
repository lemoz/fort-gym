"""The first corrected shortcuts replay preserves native outcomes and both routes."""
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


def test_latest_replay_is_v2_and_does_not_claim_a_completed_comparison():
    catalog = json.loads((RECORDINGS / "catalog.json").read_text())["recordings"]
    assert catalog[0]["id"] == IDENTITY
    assert catalog[1]["id"] == "controls-p1-keyboard-1-128"
    assert "campaign" not in catalog[0]
    html = (ROOT / "web/worlds.html").read_text()
    assert "68,200 game ticks" in html and "queued jobs are not completed products" in html
    assert "paired keyboard run is still pending a final result" in html
    assert "do not establish sustainability" in html
