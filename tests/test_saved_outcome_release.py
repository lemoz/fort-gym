"""Source-pinned saved metadata complements, but never rewrites, native replay."""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_saved_metadata_is_the_reviewed_three_endpoint_projection():
    raw = (ROOT / "web/static/saved-outcomes.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "226e7c774f1f51c6b4051d949eb1fc2fac3b6e6c078d1150b3de5ff89a2e5ace"
    )
    data = json.loads(raw)
    assert [value["saved_decision"] for value in data["outcomes"]] == [772, 708, 644]
    previous = json.dumps(data["outcomes"][1:], separators=(",", ":")).encode()
    assert hashlib.sha256(previous).hexdigest() == (
        "b242bc89e3daa31ec80dfe2a4d2bee5725b93a4d27f55bce7b49201683a13eee"
    )
    for value in data["outcomes"]:
        assert value["reported_model_charge_usd"] is None
        assert value["fresh_reload_verified"] is True
        assert value["human_gameplay_rescue"] is value["sustainability_proven"] is False
        assert value["functioning_assessment"] == "operating_but_fragile"
        source = (
            "e1b4e76c3f48e87fa3222b4e425ff6fa9d4492c6" if value["saved_decision"] == 772
            else "7d60e87c77ba31a4881d69b429c63566a7876ae4"
        )
        assert f"/{source}/" in value["result"]["url"]
        assert f"/{source}/" in value["review"]["url"]


def test_all_existing_recording_and_catalog_bytes_are_preserved():
    directory = ROOT / "web/static/recordings"
    for name, digest in {
        "catalog": "0e724b3c87c88dc76bf354c1d534f06590c40d1eef6a96f7d45ddc025d88f3b5",
        "previews": "e0731112f2d69bed0f17bab60ff5907e8af7579f96b544a9c47f3de1928b6075",
    }.items():
        assert hashlib.sha256((directory / f"{name}.json").read_bytes()).hexdigest() == digest
    catalog = json.loads((directory / "catalog.json").read_text())["recordings"]
    assert len(catalog) == 35
    assert sum(row["frame_count"] for row in catalog) == 2792
    for name, digest in {
        "catalog": "8afd401f52d845978b2afffc793779c44a01c618b57bb461cbd3186abf1c36ca",
        "previews": "e851fea0612b898cc0ab30f1f9e5d2ef41c029227d0215986ff0e4d9e9f5eca0",
    }.items():
        rows = json.loads((directory / f"{name}.json").read_text())["recordings"]
        assert len(rows[1:]) == 34
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
