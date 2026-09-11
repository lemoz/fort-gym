import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api.watch import FILENAME, SCHEMA, live_status, project_live

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def value():
    return {
        "schema_version": SCHEMA,
        "owner_alive": True,
        "observed_at_unix": 1000,
        "run_id": "fixture",
        "model": "gpt-6-astra",
        "frame": {
            "decision": 97,
            "captured_at_unix": 990,
            "screen": {
                "width": 1,
                "height": 1,
                "tile_order": "column_major",
                "runs": [[1, 219, 7, 0]],
            },
            "action": {"intent": "Inspect", "keys": ["q"], "advance_ticks": 0},
            "action_status": "chosen_not_execution_verified",
        },
    }


def test_live_projection_is_allowlisted_and_expires(value):
    value["memory"] = "private"
    value["frame"]["action"]["memory_update"] = "private"
    result = project_live(value, now=1000)
    assert result["status"] == "running"
    assert "private" not in json.dumps(result) and "memory" not in json.dumps(result)
    assert result["frame"]["action_status"] == "chosen_not_execution_verified"
    assert project_live(value, now=1031)["status"] == "stale"
    value["owner_alive"] = False
    assert project_live(value, now=1000)["status"] == "stopped"


@pytest.mark.parametrize(
    "key,changed",
    [
        ("owner_alive", 1),
        ("observed_at_unix", True),
        ("observed_at_unix", 1006),
        ("run_id", "../private"),
        ("schema_version", "wrong"),
    ],
)
def test_invalid_live_observation_is_rejected(value, key, changed):
    value[key] = changed
    with pytest.raises(ValueError):
        project_live(value, now=1000)


def test_screens_and_execution_claims_are_bounded(value):
    value["frame"]["action_status"] = "executed"
    with pytest.raises(ValueError):
        project_live(value, now=1000)
    value["frame"]["action_status"] = "chosen_not_execution_verified"
    value["frame"]["screen"]["runs"][0][0] = 10000
    with pytest.raises(ValueError):
        project_live(value, now=1000)


def test_public_endpoint_no_connection_no_cache_and_no_private_errors(
    tmp_path, value, monkeypatch
):
    from fort_gym.bench.api.server import app

    monkeypatch.setenv("FORT_GYM_PUBLIC_CAMPAIGN_DIR", str(tmp_path))
    client = TestClient(app)
    assert client.get("/public/watch-active").json()["status"] == "not_connected"
    target = tmp_path / FILENAME
    target.write_text(json.dumps(value))
    response = client.get("/public/watch-active")
    assert (
        response.status_code == 200 and "no-store" in response.headers["cache-control"]
    )
    assert response.json()["status"] == "stale"
    target.write_text("private broken data")
    response = client.get("/public/watch-active")
    assert response.status_code == 503 and "private" not in response.text
    target.unlink()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        live_status(tmp_path)


def test_recordings_match_the_reviewed_export_and_contain_no_private_fields():
    root = ROOT / "web/static/recordings"
    catalog = json.loads((root / "catalog.json").read_text())
    assert len(catalog["recordings"]) == 6
    total = 0
    for row in catalog["recordings"]:
        path = root / (row["id"] + ".json")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        recording = json.loads(path.read_text())
        assert recording["audit_sha256"] == row["audit_sha256"]
        for frame in recording["frames"]:
            assert set(frame) == {
                "decision",
                "screen",
                "action",
                "accepted",
                "before",
                "after",
            }
            assert set(frame["action"]) == {"intent", "keys", "advance_ticks"}
        total += len(recording["frames"])
    assert total == 544
    astra = json.loads((root / "astra-97-256.json").read_text())
    assert astra["saved_through_decision"] == 224 and astra["last_decision"] == 256


def test_recovery_is_separate_and_prior_recordings_are_immutable():
    root = ROOT / "web/static/recordings"
    expected = {
        "astra-97-256": "5627f83eec939aa7b86603e9aa5d18d2eb7a839560ae3a5ff3354ab8d52a4ee0",
        "sol-65-128": "3eb8184e5b9a5f7bffee4ce6c972556c3baf030f74c4c59baf251c9a3100e696",
        "terra-65-128": "37dc8ce0f22df8c9a6b4630743dc443b6fdbac4505ce50ebdad30f38d5df0bfc",
        "astra-recovery-225-256": "7aba3fdddea9f44e9a85a42738c93bd275d168692f6d4edbbc579cc70ee4e3f0",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((root / (name + ".json")).read_bytes()).hexdigest() == digest
    data = json.loads((root / "astra-recovery-225-256.json").read_text())
    assert (data["first_decision"], data["last_decision"], data["saved_through_decision"]) == (225, 256, 256)
    assert len(data["frames"]) == 32
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 28345
    assert data["parent_independent_audit_sha256"] == "01a9ba65e1d444dcd7c4eda7f4e46eaedbcc9c2ac0105a315dd8fe1fd166556b"
    recovery = data["recovery"]
    assert recovery["restored_checkpoint"] == 224
    assert recovery["lost_decisions"] == 32 and recovery["lost_ticks"] == 422
    assert recovery["total_responses"] == 288
    assert recovery["source_recording_id"] == "astra-97-256"
    assert recovery["uninterrupted_campaign"] is False
    assert recovery["actions_replayed"] is False
    catalog = json.loads((root / "catalog.json").read_text())["recordings"]
    row = next(item for item in catalog if item["id"] == data["id"])
    assert row["recovery"] == recovery


def test_homepage_and_assets_work_on_production_baseline():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    html = client.get("/").text
    assert html.index('id="watch-root"') < html.index('class="home-hero"')
    for route in [
        "/static/home-watch.mjs",
        "/static/home-watch-model.mjs",
        "/static/home-watch.css",
        "/static/recordings/catalog.json",
        "/static/recordings/previews.json",
        "/static/worlds-recordings.mjs",
        "/worlds",
        "/health",
    ]:
        assert client.get(route).status_code == 200
    assert "/admin" not in (ROOT / "web/static/home-watch.mjs").read_text()


def test_worlds_recordings_and_previews_match_the_published_catalog():
    from fort_gym.bench.api.server import app

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []
            self.recordings = []
            self.links = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if "id" in values:
                self.ids.append(values["id"])
            if "data-recording-preview" in values:
                self.recordings.append(values["data-recording-preview"])
            if tag == "a":
                self.links.append(values.get("href"))

    client = TestClient(app)
    html = client.get("/worlds").text
    page = Page()
    page.feed(html)
    assert len(page.ids) == len(set(page.ids))
    catalog = client.get("/static/recordings/catalog.json").json()["recordings"]
    previews = client.get("/static/recordings/previews.json").json()
    assert previews["schema_version"] == "fortgym.watch-previews/v1"
    assert page.recordings == [row["id"] for row in catalog]
    assert page.recordings == [row["id"] for row in previews["recordings"]]
    assert html.index('id="recent-recordings"') < html.index('id="filters-form"')
    assert "544 captured decisions" in html
    assert "observed, unsaved tail" in html
    for item, preview in zip(catalog, previews["recordings"], strict=True):
        recording = client.get("/static/recordings/" + item["id"] + ".json").json()
        assert preview == {
            "id": item["id"],
            "recording_sha256": item["sha256"],
            "decision": recording["frames"][0]["decision"],
            "screen": recording["frames"][0]["screen"],
        }
        target = "/?recording=" + item["id"] + "#watch-root"
        assert page.links.count(target) == 2
        assert client.get(target).status_code == 200
        assert item["title"] in html
        assert f'{len(recording["frames"])} frames' in html


def test_homepage_client_contracts():
    subprocess.run(
        [
            "node",
            "--test",
            str(ROOT / "tests/home_watch_client.mjs"),
            str(ROOT / "tests/worlds_recordings_client.mjs"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
