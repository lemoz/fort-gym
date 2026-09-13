"""Source-pinned saved metadata complements, but never rewrites, native replay."""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_saved_metadata_is_the_reviewed_six_endpoint_projection():
    raw = (ROOT / "web/static/saved-outcomes.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "2e1e4d5998abe3ca1e4c53e3a23feee78ffabbf5f69c7b92f1102bfccfca5823"
    )
    data = json.loads(raw)
    assert [value["saved_decision"] for value in data["outcomes"]] == [964, 900, 836, 772, 708, 644]
    previous = json.dumps(data["outcomes"][1:], separators=(",", ":")).encode()
    assert hashlib.sha256(previous).hexdigest() == (
        "81aa14a0960d8b7d5683c744e37959656eba9f92a26907bbac728b63442428e4"
    )
    for value in data["outcomes"]:
        assert value["reported_model_charge_usd"] is None
        assert value["fresh_reload_verified"] is True
        assert value["human_gameplay_rescue"] is value["sustainability_proven"] is False
        expected = {
            964: "operating_with_incident_recovery",
            900: "operating_with_workshop_development",
            836: "operating_with_adaptive_supply_recovery",
        }.get(value["saved_decision"], "operating_but_fragile")
        assert value["functioning_assessment"] == expected
        source = (
            "62d31fdd8efd36f54b8c3a2caa3d04653faf566e" if value["saved_decision"] == 964 else
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
        "catalog": "cd3a39d1cb5ce1e72703756b9b1b9447a9624680e545056b177eb8d7c6f37122",
        "previews": "f3fa10d478866953d928e48146628a91036544bbac8835a97643e1fe657dbc4f",
    }.items():
        assert hashlib.sha256((directory / f"{name}.json").read_bytes()).hexdigest() == digest
    catalog = json.loads((directory / "catalog.json").read_text())["recordings"]
    assert len(catalog) == 38
    assert sum(row["frame_count"] for row in catalog) == 2984
    for name, digest in {
        "catalog": "22a15adc27ed1880e3656bc7941c72750e06399f6721e2fe427f7012bb14bed9",
        "previews": "8c145437b1aa836edf8798babec55952006aa2d9e84f22c4ed0f9b5c750c6470",
    }.items():
        rows = json.loads((directory / f"{name}.json").read_text())["recordings"]
        assert len(rows[1:]) == 37
        assert hashlib.sha256(json.dumps(rows[1:], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == digest
    for row in catalog:
        raw = (directory / (row["id"] + ".json")).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_outcome_assets_and_existing_player_are_served_without_native_connection():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    html = client.get("/").text
    assert "/static/home-watch.mjs?v=20260913-checkpoint964" in html
    assert "saved-outcomes.mjs?v=20260913-checkpoint964" in (
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
    assert latest["saved_metrics"]["food_stock"] == 389
    assert latest["saved_metrics"]["drink_stock"] == 531
    assert latest["inventory_scope"] == {
        "schema_version": "fortgym.watch-inventory-scope/v1",
        "food_trader_flagged_units": 250,
        "food_nontrader_units": 139,
        "food_nontrader_start_units": 138,
        "drink_trader_flagged_units": None,
        "ownership_and_accessibility_proven": False,
    }
    assert all("inventory_scope" not in value for value in data["outcomes"][2:])
