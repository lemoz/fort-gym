"""Source-pinned saved metadata complements, but never rewrites, native replay."""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_saved_metadata_is_the_reviewed_four_endpoint_projection():
    raw = (ROOT / "web/static/saved-outcomes.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "5953aac42361031c75653c100b99ab26dcf722acd78afe58f3b6a7d3939a3a23"
    )
    data = json.loads(raw)
    assert [value["saved_decision"] for value in data["outcomes"]] == [836, 772, 708, 644]
    previous = json.dumps(data["outcomes"][1:], separators=(",", ":")).encode()
    assert hashlib.sha256(previous).hexdigest() == (
        "2d90082fb21a8d3cbeb99e5d839c587deb77fbc24d0fda949ea57e59300a3133"
    )
    for value in data["outcomes"]:
        assert value["reported_model_charge_usd"] is None
        assert value["fresh_reload_verified"] is True
        assert value["human_gameplay_rescue"] is value["sustainability_proven"] is False
        expected = "operating_with_adaptive_supply_recovery" if value["saved_decision"] == 836 else "operating_but_fragile"
        assert value["functioning_assessment"] == expected
        source = (
            "77f3f7227b79d41e6856fc0c3b142bc19b4e3a0a" if value["saved_decision"] == 836 else
            "e1b4e76c3f48e87fa3222b4e425ff6fa9d4492c6" if value["saved_decision"] == 772
            else "7d60e87c77ba31a4881d69b429c63566a7876ae4"
        )
        assert f"/{source}/" in value["result"]["url"]
        assert f"/{source}/" in value["review"]["url"]


def test_all_existing_recording_and_catalog_bytes_are_preserved():
    directory = ROOT / "web/static/recordings"
    for name, digest in {
        "catalog": "879324126b5767915d24dd894ac0174aa948e6adaeaedd49c231523533e4fe03",
        "previews": "61eb6c8fe2cfa4795460b4fe21ba253949c23caf125b53238791beb89690f1f2",
    }.items():
        assert hashlib.sha256((directory / f"{name}.json").read_bytes()).hexdigest() == digest
    catalog = json.loads((directory / "catalog.json").read_text())["recordings"]
    assert len(catalog) == 36
    assert sum(row["frame_count"] for row in catalog) == 2856
    for name, digest in {
        "catalog": "9a3a4c1644cd3bf04eb099ae070b907bbe1f6ac446c52b8e8e2681d9679cba2a",
        "previews": "61c706ada66d33a4b578a4660e5e21c8b6c9943207de59acc8a9082b498fb857",
    }.items():
        rows = json.loads((directory / f"{name}.json").read_text())["recordings"]
        assert len(rows[1:]) == 35
        assert hashlib.sha256(json.dumps(rows[1:], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == digest
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
