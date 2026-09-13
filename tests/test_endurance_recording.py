"""The endurance replay is an audited save, separate from short control trials."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "web/static/recordings"
IDENTITY = "astra-keyboard-endurance-v1-1-68"


def test_endurance_recording_preserves_audited_keyboard_actions_and_save_boundary():
    raw = (RECORDINGS / (IDENTITY + ".json")).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "97cd1ae75d5afa68e6896bcb1868b476ca9cd8430ff59b4fd0975857fdae095c"
    data = json.loads(raw)
    assert data["audit_sha256"] == "a21451d867103c29b5786a9338d8829057228f54e9507d3606e71d22a608fe9f"
    assert data["source_revision"] == "4b526b5636e6f568a4cae1a1227d746d9c6922c3"
    assert data["control_profile"] == "native_keyboard_bindings/v1"
    assert data["saved_through_decision"] == 68
    frames = data["frames"]
    assert [f["decision"] for f in frames] == list(range(1, 69))
    assert sum(f["after"]["ticks_advanced"] for f in frames) == 30700
    assert frames[3]["after"]["tick"] == frames[4]["before"]["tick"]
    assert frames[-1]["after"]["population"] == 7
    assert all(f["accepted"] and "shortcut" not in f["action"] for f in frames)
    assert sum(len(f["action"]["keys"]) for f in frames) == 543


def test_endurance_card_keeps_the_short_study_and_year_two_claim_separate():
    catalog = json.loads((RECORDINGS / "catalog.json").read_text())["recordings"]
    assert catalog[0]["id"] == "astra-keyboard-endurance-v1-69-132"
    assert catalog[1]["id"] == IDENTITY
    assert catalog[2]["id"] == "controls-v2-p3-keyboard-1-128"
    assert len([row for row in catalog if row["id"].startswith("controls-v2-")]) == 6
    previews = json.loads((RECORDINGS / "previews.json").read_text())["recordings"]
    assert previews[1]["id"] == IDENTITY
    assert previews[1]["recording_sha256"] == catalog[1]["sha256"]
    html = (ROOT / "web/worlds.html").read_text()
    assert "30,700 game ticks" in html and "six installed beds" in html
    assert "1,788,513 returned tokens" in html
    assert "Both saves at decisions 4 and 68 were freshly reloaded" in html
    assert "It has not reached Year Two" in html
    assert "these stocks do not establish self-sufficiency" in html


def test_continuation_frames_do_not_duplicate_the_original_recording():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-69-132.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "eabd35f654dfd30a1860e2b233e38da38a8adc323720e9f6dd987133bf3a8166"
    data = json.loads(raw)
    assert data["audit_sha256"] == "6da9e5563a6a0da28330ee8fea337020163448d64c748db47da9f73b2feb3cc4"
    previous = json.loads((RECORDINGS / (IDENTITY + ".json")).read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(69, 133))
    assert data["saved_through_decision"] == 132
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 10000
    assert sum(frame["accepted"] for frame in frames) == 63
    assert all("shortcut" not in frame["action"] for frame in frames)
    assert frames[-1]["after"]["population"] == 7
    html = (ROOT / "web/worlds.html").read_text()
    assert "40,700 total game ticks" in html
    assert "3,799,537 returned tokens" in html
    assert "continuation, not an independent trial" in html
