"""Source-pinned saved metadata complements, but never rewrites, native replay."""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_saved_metadata_is_the_reviewed_five_endpoint_projection():
    raw = (ROOT / "web/static/saved-outcomes.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "6314e0eba7433694d5f759d4a737bbc9b3b904d5ae4fa5ac071255f451f080a5"
    )
    data = json.loads(raw)
    assert [value["saved_decision"] for value in data["outcomes"]] == [900, 836, 772, 708, 644]
    previous = json.dumps(data["outcomes"][1:], separators=(",", ":")).encode()
    assert hashlib.sha256(previous).hexdigest() == (
        "20dabc6b9f54234b635908082ed9c52bc427da07dbe76607b1a57fb5f6a7e4b0"
    )
    for value in data["outcomes"]:
        assert value["reported_model_charge_usd"] is None
        assert value["fresh_reload_verified"] is True
        assert value["human_gameplay_rescue"] is value["sustainability_proven"] is False
        expected = {
            900: "operating_with_workshop_development",
            836: "operating_with_adaptive_supply_recovery",
        }.get(value["saved_decision"], "operating_but_fragile")
        assert value["functioning_assessment"] == expected
        source = (
            "bae881829d615dd3afd2e6b9357ad3b8f299ee8f" if value["saved_decision"] == 900 else
            "77f3f7227b79d41e6856fc0c3b142bc19b4e3a0a" if value["saved_decision"] == 836 else
            "e1b4e76c3f48e87fa3222b4e425ff6fa9d4492c6" if value["saved_decision"] == 772
            else "7d60e87c77ba31a4881d69b429c63566a7876ae4"
        )
        assert f"/{source}/" in value["result"]["url"]
        assert f"/{source}/" in value["review"]["url"]


def test_all_existing_recording_and_catalog_bytes_are_preserved():
    directory = ROOT / "web/static/recordings"
    for name, digest in {
        "catalog": "0219a9f02cc6da81ce6f04bf5389524af41c4dc151fd3a2d2c29c87fb119786b",
        "previews": "a348d12eb023b72cd269d060e0f5eba57d3f05569c8c29c044698d2c58fa8539",
    }.items():
        assert hashlib.sha256((directory / f"{name}.json").read_bytes()).hexdigest() == digest
    catalog = json.loads((directory / "catalog.json").read_text())["recordings"]
    assert len(catalog) == 37
    assert sum(row["frame_count"] for row in catalog) == 2920
    for name, digest in {
        "catalog": "6002123dd78873c8ebd6aabae45c2be677cc34190d5129a9701cbb91d0ea6688",
        "previews": "62ebbf957ce00730b85a4233c1ff17170c52556d2234021a4acef1f8ff676ae7",
    }.items():
        rows = json.loads((directory / f"{name}.json").read_text())["recordings"]
        assert len(rows[1:]) == 36
        assert hashlib.sha256(json.dumps(rows[1:], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == digest
    for row in catalog:
        raw = (directory / (row["id"] + ".json")).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_outcome_assets_and_existing_player_are_served_without_native_connection():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    html = client.get("/").text
    assert "/static/home-watch.mjs?v=20260913-checkpoint900" in html
    assert "saved-outcomes.mjs?v=20260913-checkpoint900" in (
        ROOT / "web/static/home-watch.mjs"
    ).read_text()
    assert 'id="watch-outcome-status" role="status" hidden' in html
    assert "Saved outcome at the end of this window" in html
    for route, relative in {
        "/static/saved-outcomes.json": "web/static/saved-outcomes.json",
        "/static/saved-outcomes.mjs": "web/static/saved-outcomes.mjs",
        "/static/home-watch.mjs": "web/static/home-watch.mjs",
    }.items():
        response = client.get(route)
        assert response.status_code == 200
        assert response.content == (ROOT / relative).read_bytes()
    assert client.get("/public/watch-active").json()["status"] == "not_connected"


def test_new_inventory_scope_preserves_raw_totals_and_unknown_drink_ownership():
    data = json.loads((ROOT / "web/static/saved-outcomes.json").read_text())
    latest = data["outcomes"][0]
    assert latest["saved_metrics"]["food_stock"] == 388
    assert latest["saved_metrics"]["drink_stock"] == 560
    assert latest["inventory_scope"] == {
        "schema_version": "fortgym.watch-inventory-scope/v1",
        "food_trader_flagged_units": 250,
        "food_nontrader_units": 138,
        "food_nontrader_start_units": 151,
        "drink_trader_flagged_units": None,
        "ownership_and_accessibility_proven": False,
    }
    assert all("inventory_scope" not in value for value in data["outcomes"][1:])
