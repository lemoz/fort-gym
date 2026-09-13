"""Source-pinned saved metadata complements, but never rewrites, native replay."""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_saved_metadata_is_the_reviewed_two_endpoint_projection():
    raw = (ROOT / "web/static/saved-outcomes.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "5edffc6acb14e6ae8b9a6bd7d320f0d74012e64146e33696a67571d7ac5c429f"
    )
    data = json.loads(raw)
    assert [value["saved_decision"] for value in data["outcomes"]] == [708, 644]
    for value in data["outcomes"]:
        assert value["reported_model_charge_usd"] is None
        assert value["fresh_reload_verified"] is True
        assert value["human_gameplay_rescue"] is value["sustainability_proven"] is False
        assert value["functioning_assessment"] == "operating_but_fragile"
        assert "/7d60e87c77ba31a4881d69b429c63566a7876ae4/" in value["result"]["url"]
        assert "/7d60e87c77ba31a4881d69b429c63566a7876ae4/" in value["review"]["url"]


def test_all_existing_recording_and_catalog_bytes_are_preserved():
    directory = ROOT / "web/static/recordings"
    for name, digest in {
        "catalog": "401b4549953edde21e42106ae374b9e5e5c38de683c35491f690dae3dd826152",
        "previews": "612823c50f0bf76990f28cdc8cbf6d6179f65e7009d2cd1f2354d2500dbcc9dc",
    }.items():
        assert hashlib.sha256((directory / f"{name}.json").read_bytes()).hexdigest() == digest
    catalog = json.loads((directory / "catalog.json").read_text())["recordings"]
    assert len(catalog) == 34
    assert sum(row["frame_count"] for row in catalog) == 2728
    for row in catalog:
        raw = (directory / (row["id"] + ".json")).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_outcome_assets_and_existing_player_are_served_without_native_connection():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    html = client.get("/").text
    assert "/static/home-watch.mjs?v=20260913-saved-outcomes" in html
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
