from __future__ import annotations

from scripts.live_interact_smoke import verify_trace_row


def test_live_interact_smoke_verifier_requires_zero_tick_audit_and_no_credit() -> None:
    row = {
        "action": {"type": "INTERACT", "advance_ticks": 0},
        "validation": {"valid": True},
        "execute": {
            "accepted": True,
            "provenance": "dfhack_governed",
            "gameplay_progress_eligible": False,
        },
        "interaction": {
            "keys_sent": 1,
            "pause_before": True,
            "pause_after": True,
            "viewscreen_before": "viewscreen_textviewerst",
            "viewscreen_after": "viewscreen_dwarfmodest",
            "screen_before_sha256": "a" * 64,
            "screen_after_sha256": "b" * 64,
        },
        "tick_advance": {"ticks_advanced": 0},
        "gameplay_proof": {"ok": False},
        "screen_text_after_interaction": "next page",
    }

    result = verify_trace_row(row)

    assert result["ok"] is True
    row["execute"]["gameplay_progress_eligible"] = True
    assert verify_trace_row(row)["ok"] is False
