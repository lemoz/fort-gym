"""The native harness and published spectator UI coexist without a game process."""

import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import server

ROOT = Path(__file__).resolve().parents[1]


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value and value.startswith("/"):
                self.links.add(urlsplit(value).path)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=None),
    )
    return TestClient(server.app)


@pytest.mark.parametrize(
    "route", ["/", "/results", "/worlds", "/campaigns", "/protocols", "/findings"]
)
def test_public_and_campaign_pages_keep_local_assets_and_protocol_links(client, route):
    response = client.get(route)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    page = PageLinks()
    page.feed(response.text)
    for link in sorted(page.links):
        if link.startswith(("/static/", "/protocols/")):
            assert client.get(link).status_code == 200, (route, link)


@pytest.mark.parametrize("route", ["/", "/results"])
def test_campaign_tracking_remains_reachable_from_public_navigation(client, route):
    html = client.get(route).text
    assert html.count('href="/campaigns"') >= 2  # Desktop and mobile navigation.
    assert client.get("/campaigns").status_code == 200


def test_every_catalog_replay_is_served_with_its_audited_bytes(client):
    catalog = client.get("/static/recordings/catalog.json").json()["recordings"]
    assert len(catalog) == 36
    total = 0
    for row in catalog:
        response = client.get(f"/static/recordings/{row['id']}.json")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        total += len(response.json()["frames"])
    assert total == 2856


def test_operator_and_spectator_feeds_remain_explicitly_disconnected(client):
    campaign = client.get("/public/campaign-feed")
    spectator = client.get("/public/watch-active")
    assert campaign.status_code == spectator.status_code == 200
    assert campaign.json()["configured"] is False
    assert spectator.json()["status"] == "not_connected"
    assert "no-store" in campaign.headers["cache-control"]
    assert "no-store" in spectator.headers["cache-control"]


def test_release_does_not_install_a_live_feed():
    assert not (ROOT / "web/static/live/watch-active.json").exists()


def release_manifest():
    return json.loads(
        (
            ROOT / "experiments/evidence/year_two_release_outcomes_source_20260913.json"
        ).read_text()
    )


def test_refreshed_release_preserves_published_and_native_source_bytes():
    manifest = release_manifest()
    assert (
        manifest["published_website_revision"]
        == "d5af4339a936a908e0caf34ecbdaa6a4ec5837cd"
    )
    assert (
        manifest["combined_base_revision"] == "5957c4890ad05905bdea7c3519a71a096f73efef"
    )
    for group in (
        "imported_files",
        "compatibility_adjusted_files",
        "protected_native_files",
        "retained_harness_assets",
    ):
        assert manifest[group]
        for row in manifest[group]:
            actual = hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest()
            assert actual == row["sha256"], row["path"]


def test_original_release_snapshot_and_recording_history_remain_immutable():
    manifest = release_manifest()
    historical_bytes = (
        ROOT / "experiments/evidence/year_two_release_source_20260913.json"
    ).read_bytes()
    assert (
        hashlib.sha256(historical_bytes).hexdigest()
        == manifest["historical_source_manifest_sha256"]
    )
    historical = json.loads(historical_bytes)
    current = {row["id"]: row for row in manifest["recordings"]}
    assert len(historical["recordings"]) == 32
    assert all(current[row["id"]] == row for row in historical["recordings"])
    assert manifest["recording_count"] == len(current) == 36
    assert (
        manifest["frame_count"]
        == sum(row["frames"] for row in current.values())
        == 2856
    )


def test_saved_outcome_assets_are_served_by_the_combined_application(client):
    response = client.get("/static/saved-outcomes.json")
    assert response.status_code == 200
    assert response.content == (ROOT / "web/static/saved-outcomes.json").read_bytes()
    outcomes = response.json()["outcomes"]
    assert [row["saved_decision"] for row in outcomes] == [836, 772, 708, 644]
    module = client.get("/static/saved-outcomes.mjs?v=20260913")
    assert module.status_code == 200
    assert module.content == (ROOT / "web/static/saved-outcomes.mjs").read_bytes()
    assert 'id="watch-outcome-status"' in client.get("/").text
    assert "home-watch.mjs?v=20260913-saved-outcomes" in client.get("/").text


def test_source_refresh_does_not_claim_native_or_public_deployment():
    manifest = release_manifest()
    for field in (
        "active_experiment_changed",
        "main_merged",
        "combined_application_deployed",
        "native_gameplay_executed_by_integration",
        "private_observer_included",
        "full_goal_complete",
    ):
        assert manifest[field] is False
