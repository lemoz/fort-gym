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
    assert len(catalog) == 37
    total = 0
    for row in catalog:
        response = client.get(f"/static/recordings/{row['id']}.json")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        total += len(response.json()["frames"])
    assert total == 2920


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
            ROOT / "experiments/evidence/year_two_release_checkpoint900_source_20260913.json"
        ).read_text()
    )


def test_refreshed_release_preserves_published_and_native_source_bytes():
    manifest = release_manifest()
    assert (
        manifest["published_website_revision"]
        == "d8b681e1d8f059d8ac3ee4480aab05778d4cf365"
    )
    assert (
        manifest["combined_base_revision"] == "90e4c977cb49b1efbefda295b4bd27ec806ae98f"
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
    previous_bytes = (ROOT / manifest["previous_release_source_manifest"]).read_bytes()
    assert hashlib.sha256(previous_bytes).hexdigest() == (
        manifest["previous_release_source_manifest_sha256"]
    ) == "5b3bd64df0004a13541776f5fd74985ad932f3efac51755de99fdb389c457fda"
    previous = json.loads(previous_bytes)
    assert len(previous["recordings"]) == 36
    assert manifest["recordings"][1:] == previous["recordings"]
    assert manifest["recording_count"] == len(current) == 37
    assert (
        manifest["frame_count"]
        == sum(row["frames"] for row in current.values())
        == 2920
    )


def test_saved_outcome_assets_are_served_by_the_combined_application(client):
    response = client.get("/static/saved-outcomes.json")
    assert response.status_code == 200
    assert response.content == (ROOT / "web/static/saved-outcomes.json").read_bytes()
    outcomes = response.json()["outcomes"]
    assert [row["saved_decision"] for row in outcomes] == [900, 836, 772, 708, 644]
    module = client.get("/static/saved-outcomes.mjs?v=20260913-checkpoint900")
    assert module.status_code == 200
    assert module.content == (ROOT / "web/static/saved-outcomes.mjs").read_bytes()
    assert 'id="watch-outcome-status"' in client.get("/").text
    assert "home-watch.mjs?v=20260913-checkpoint900" in client.get("/").text


def test_inventory_qualification_survives_combined_application_delivery(client):
    manifest = release_manifest()
    outcomes = client.get("/static/saved-outcomes.json").json()["outcomes"]
    latest = outcomes[0]
    assert latest["saved_decision"] == manifest["latest_saved_decision"] == 900
    assert latest["saved_elapsed_ticks"] == manifest["latest_saved_elapsed_ticks"] == 606650
    assert latest["inventory_scope"] == manifest["inventory_scope"] == {
        "schema_version": "fortgym.watch-inventory-scope/v1",
        "food_trader_flagged_units": 250,
        "food_nontrader_units": 138,
        "food_nontrader_start_units": 151,
        "drink_trader_flagged_units": None,
        "ownership_and_accessibility_proven": False,
    }
    assert latest["saved_metrics"]["food_stock"] == 388
    assert latest["saved_metrics"]["drink_stock"] == 560
    assert latest["functioning_assessment"] == "operating_with_workshop_development"
    assert all("inventory_scope" not in row for row in outcomes[1:])


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
