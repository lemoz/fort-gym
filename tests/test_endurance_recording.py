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
    assert [row["id"] for row in catalog[:9]] == [
        "astra-keyboard-endurance-v1-453-516",
        "astra-keyboard-endurance-v1-389-452",
        "astra-keyboard-endurance-v1-325-388",
        "astra-keyboard-endurance-v1-261-324",
        "astra-keyboard-endurance-v1-197-260",
        "astra-keyboard-endurance-v1-133-196",
        "astra-keyboard-endurance-v1-69-132",
        IDENTITY,
        "controls-v2-p3-keyboard-1-128",
    ]
    assert len([row for row in catalog if row["id"].startswith("controls-v2-")]) == 6
    previews = json.loads((RECORDINGS / "previews.json").read_text())["recordings"]
    assert previews[7]["id"] == IDENTITY
    assert previews[7]["recording_sha256"] == catalog[7]["sha256"]
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


def test_checkpoint_196_is_a_nonoverlapping_native_continuation():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-133-196.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "d5da30777c97f7f4827daee5048f276ce0b843e901c633c9b99628ad8249bcc7"
    data = json.loads(raw)
    assert data["audit_sha256"] == "1f91ef6907f37c7a942b2b983bc243b9e9c745a3e5ac09c44bc2b82bdcee7307"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-69-132.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(133, 197))
    assert data["saved_through_decision"] == 196
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 33200
    assert sum(frame["accepted"] for frame in frames) == 63
    assert all("shortcut" not in frame["action"] for frame in frames)
    assert frames[-1]["after"]["population"] == 7
    html = (ROOT / "web/worlds.html").read_text()
    assert "73,900 total game ticks" in html
    assert "5,751,089 returned tokens" in html
    assert "decision-196 save was freshly reloaded" in html
    assert "stock counts alone do not establish sustainability" in html


def test_checkpoint_260_retains_its_audited_actions_and_automatic_continuation():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-197-260.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "c67e515a936bee675d6563dcd18e5be094d06c22bc6c4560d8725111cd9b21eb"
    data = json.loads(raw)
    assert data["audit_sha256"] == "6c6636e95b01963d4b222c97e984cca4c37936546258c87b091a800cae609920"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-133-196.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(197, 261))
    assert data["saved_through_decision"] == 260
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 31200
    assert all(frame["accepted"] and "shortcut" not in frame["action"] for frame in frames)
    assert sum(len(frame["action"]["keys"]) for frame in frames) == 459
    assert frames[-1]["after"]["population"] == 7
    html = (ROOT / "web/worlds.html").read_text()
    assert "105,100 total game ticks" in html
    assert "8,141,754 returned tokens" in html
    assert "decision-260 save was freshly reloaded" in html
    assert "the run continued automatically" in html
    assert "stock counts alone do not establish sustainability" in html


def test_checkpoint_324_preserves_growth_rejection_and_its_native_boundary():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-261-324.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "78ff11dcc9deed6ed21e0214b868971b41fd753eea5bc274121837ae9f27eca4"
    data = json.loads(raw)
    assert data["audit_sha256"] == "f26641935a00c70bbdf704896d6563f9dcb6bb9ebee848cd5f467a1b3b60a20f"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-197-260.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(261, 325))
    assert data["saved_through_decision"] == 324
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 64000
    assert sum(frame["accepted"] for frame in frames) == 63
    assert all("shortcut" not in frame["action"] for frame in frames)
    assert sum(len(frame["action"]["keys"]) for frame in frames if frame["accepted"]) == 232
    rejected = [frame for frame in frames if not frame["accepted"]]
    assert [(frame["decision"], frame["action"]["keys"]) for frame in rejected] == [
        (294, ["SYM:0:PageDown"])
    ]
    assert previous["frames"][-1]["after"]["population"] == 7
    assert frames[-1]["after"]["population"] == 11
    html = (ROOT / "web/worlds.html").read_text()
    assert "169,100 total game ticks" in html
    assert "10,418,341 returned tokens" in html
    assert "decision-324 save was freshly reloaded" in html
    assert "grew from seven to eleven living dwarves" in html
    assert "stock counts alone do not establish sustainability" in html


def test_checkpoint_388_keeps_growth_and_interrupted_native_time_visible():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-325-388.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "0049b28cc0e13fbb1ae2143b51eac5e6fef8bc26faf44fc5dc0d9282d340612f"
    data = json.loads(raw)
    assert data["audit_sha256"] == "3509c41e5f8e97c3c03786bde64edf8dd9d77ae1d87fd6fac1009a3fc48d9f56"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-261-324.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(325, 389))
    assert data["saved_through_decision"] == 388
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 65950
    assert sum(frame["action"]["advance_ticks"] for frame in frames) == 78000
    assert all(frame["accepted"] and "shortcut" not in frame["action"] for frame in frames)
    assert sum(len(frame["action"]["keys"]) for frame in frames) == 149
    interrupted = [frame for frame in frames if frame["after"]["ticks_advanced"] < frame["action"]["advance_ticks"]]
    assert [frame["decision"] for frame in interrupted] == [351, 353, 354, 358, 362, 364, 369]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames if frame["decision"] > 369) == 30000
    assert previous["frames"][-1]["after"]["population"] == 11
    assert frames[-1]["after"]["population"] == 19
    html = (ROOT / "web/worlds.html").read_text()
    assert "235,050 total game ticks" in html
    assert "12,096,579 returned tokens" in html
    assert "decision-388 save was freshly reloaded" in html
    assert "grew from eleven to nineteen living dwarves" in html
    assert "Seven meeting or text screens interrupted time advancement" in html
    assert "stock counts alone do not establish sustainability" in html


def test_checkpoint_452_preserves_native_continuity_and_declining_supplies():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-389-452.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "c64ee2c324d0a343fb6f0ee80991a515dff035c97c2c8a127728194f2b678860"
    data = json.loads(raw)
    assert data["audit_sha256"] == "4d2cea9669cbe40ef04cc9984c65ada1a8b83d5bc7ca43ab7498fedeaaf4d2b6"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-325-388.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(389, 453))
    assert data["saved_through_decision"] == 452
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 66000
    assert sum(frame["action"]["advance_ticks"] for frame in frames) == 66000
    assert all(frame["after"]["ticks_advanced"] == frame["action"]["advance_ticks"] for frame in frames)
    assert all(frame["accepted"] and "shortcut" not in frame["action"] for frame in frames)
    assert sum(len(frame["action"]["keys"]) for frame in frames) == 235
    assert previous["frames"][-1]["after"]["population"] == frames[-1]["after"]["population"] == 19
    html = (ROOT / "web/worlds.html").read_text()
    assert "301,050 total game ticks" in html
    assert "14,136,731 returned tokens" in html
    assert "decision-452 save was freshly reloaded" in html
    assert "Food fell from 184 to 134 and drinks from 88 to 29" in html
    assert "stock counts alone do not establish sustainability" in html


def test_checkpoint_516_preserves_native_continuity_without_inferring_production():
    raw = (RECORDINGS / "astra-keyboard-endurance-v1-453-516.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "36982b8e7703c0ddaaec1d38f11209c95fca23159819fe2441a2171e3f210231"
    data = json.loads(raw)
    assert data["audit_sha256"] == "4bf53a6e6086e3636076a67bf944746d4ff2d035d20ae0c34a75aaccb0081d25"
    previous = json.loads((RECORDINGS / "astra-keyboard-endurance-v1-389-452.json").read_text())
    frames = data["frames"]
    assert [frame["decision"] for frame in frames] == list(range(453, 517))
    assert data["saved_through_decision"] == 516
    assert data["source_revision"] == previous["source_revision"]
    assert data["control_profile"] == previous["control_profile"]
    assert frames[0]["before"]["tick"] == previous["frames"][-1]["after"]["tick"]
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == 44000
    assert sum(frame["action"]["advance_ticks"] for frame in frames) == 44000
    assert all(frame["after"]["ticks_advanced"] == frame["action"]["advance_ticks"] for frame in frames)
    assert all(frame["accepted"] and "shortcut" not in frame["action"] for frame in frames)
    assert sum(len(frame["action"]["keys"]) for frame in frames) == 209
    assert previous["frames"][-1]["after"]["population"] == frames[-1]["after"]["population"] == 19
    html = (ROOT / "web/worlds.html").read_text()
    assert "345,050 total game ticks" in html
    assert "15,847,406 returned tokens" in html
    assert "decision-516 save was freshly reloaded" in html
    assert "Food rose from 134 to 170 and drinks remained at 29" in html
    assert "stock counts alone do not establish sustainability" in html
