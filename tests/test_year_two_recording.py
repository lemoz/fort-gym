"""The public continuation is a new window, not a replacement or extra trial."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "web/static/recordings"


def test_year_two_replay_is_bound_to_saved_evidence():
    path = RECORDINGS / "astra-year-two-257-416.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "79a42eeb8501fe7669f134670e9ce6c947a5628eeb5e94506973f1afa78f83d9"
    )
    data = json.loads(path.read_text())
    assert list(range(257, 417)) == [frame["decision"] for frame in data["frames"]]
    assert data["saved_through_decision"] == 416
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 200000
    assert data["audit_sha256"] == (
        "beb2760bd0516fcb884420c3fd87a3fbcc4fd54d170857e97d7cdb471d27f743"
    )
    outcome = data["campaign"]
    assert outcome["saved_elapsed_ticks"] == 429845
    assert outcome["elapsed_years"] == 429845 / 403200
    assert outcome["ticks_into_year_two"] == 26645
    assert outcome["total_responses"] == 448
    assert outcome["total_tokens"] == 11866456
    assert outcome["reported_model_charge_usd"] is None
    assert outcome["fresh_reload_verified"] is True
    assert outcome["historical_lost_decisions"] == 32
    assert outcome["historical_lost_ticks"] == 422
    assert outcome["uninterrupted_campaign"] is False
    assert outcome["human_gameplay_rescue"] is False
    assert outcome["sustainability_proven"] is False
    assert outcome["repeated_matched_comparison"] is False
    assert outcome["saved_metrics"]["food_stock"] == 43
    assert outcome["saved_metrics"]["drink_stock"] == 389
    assert outcome["saved_metrics"]["population"] == data["frames"][-1]["after"]["population"] == 13
    assert outcome["saved_metrics"]["recorded_dead_citizens"] == 0
    catalog = json.loads((RECORDINGS / "catalog.json").read_text())["recordings"]
    assert catalog[0]["id"] == data["id"]
    assert catalog[0]["campaign"] == outcome
    assert catalog[1]["id"] == outcome["source_recording_id"]


def test_year_two_public_frames_do_not_include_private_receipts_or_memory():
    data = json.loads((RECORDINGS / "astra-year-two-257-416.json").read_text())
    forbidden = {"memory", "memory_update", "reasoning", "analysis", "request", "response",
                 "provider_events", "account", "access_token", "api_key", "prompt"}

    def visit(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(data)
    for frame in data["frames"]:
        assert set(frame["before"]) == {"year", "tick"}
        assert set(frame["after"]) == {"year", "tick", "population", "ticks_advanced"}
        assert set(frame["screen"]) == {"width", "height", "tile_order", "runs"}


def test_outcome_is_explicitly_an_endpoint_not_a_scrubbed_supply_measurement():
    html = (ROOT / "web/landing.html").read_text()
    assert "Saved outcome at the end of this window" in html
    assert "Production rates and stock accessibility were not measured" in html
    assert "not a repeated model comparison" in html
    assert 'id="watch-outcome"' in html
    assert 'id="watch-result"' in html and 'id="watch-reload"' in html
