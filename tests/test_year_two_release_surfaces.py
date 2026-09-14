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
    assert len(catalog) == 39
    total = 0
    for row in catalog:
        response = client.get(f"/static/recordings/{row['id']}.json")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        total += len(response.json()["frames"])
    assert total == 3048


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
            ROOT / "experiments/evidence/year_two_release_checkpoint1028_source_20260913.json"
        ).read_text()
    )


def test_refreshed_release_preserves_published_and_native_source_bytes():
    manifest = release_manifest()
    assert (
        manifest["published_website_revision"]
        == "62427fce64590b0b958e4618c36aab31586c41c2"
    )
    assert (
        manifest["combined_base_revision"] == "f3d3a3d2020ea20086806fd5363d7bad08c64bec"
    )
    for group in (
        "imported_files",
        "compatibility_adjusted_files",
        "protected_native_files",
        "retained_harness_assets",
        "source_evidence_files",
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
    ) == "c7a9ec932f8714fd62bdd289038b80fbd4157741cdc1726ad08273512c3c8a4a"
    previous = json.loads(previous_bytes)
    assert len(previous["recordings"]) == 37
    assert manifest["recordings"][2:] == previous["recordings"]
    older_bytes = (ROOT / previous["previous_release_source_manifest"]).read_bytes()
    assert hashlib.sha256(older_bytes).hexdigest() == (
        previous["previous_release_source_manifest_sha256"]
    ) == "5b3bd64df0004a13541776f5fd74985ad932f3efac51755de99fdb389c457fda"
    assert manifest["recording_count"] == len(current) == 39
    assert (
        manifest["frame_count"]
        == sum(row["frames"] for row in current.values())
        == 3048
    )


def test_saved_outcome_assets_are_served_by_the_combined_application(client):
    response = client.get("/static/saved-outcomes.json")
    assert response.status_code == 200
    assert response.content == (ROOT / "web/static/saved-outcomes.json").read_bytes()
    outcomes = response.json()["outcomes"]
    assert [row["saved_decision"] for row in outcomes] == [1028, 964, 900, 836, 772, 708, 644]
    module = client.get("/static/saved-outcomes.mjs?v=20260913-checkpoint1028")
    assert module.status_code == 200
    assert module.content == (ROOT / "web/static/saved-outcomes.mjs").read_bytes()
    assert 'id="watch-outcome-status"' in client.get("/").text
    assert "home-watch.mjs?v=20260913-checkpoint1028" in client.get("/").text
    assert 'id="watch-fresh-reload"' in client.get("/").text


def test_inventory_qualification_survives_combined_application_delivery(client):
    manifest = release_manifest()
    outcomes = client.get("/static/saved-outcomes.json").json()["outcomes"]
    latest = outcomes[0]
    assert latest["saved_decision"] == manifest["latest_saved_decision"] == 1028
    assert latest["saved_elapsed_ticks"] == manifest["latest_saved_elapsed_ticks"] == 765895
    assert latest["inventory_scope"] == manifest["inventory_scope"] == {
        "schema_version": "fortgym.watch-inventory-scope/v1",
        "food_trader_flagged_units": 0,
        "food_nontrader_units": 172,
        "food_nontrader_start_units": 139,
        "drink_trader_flagged_units": None,
        "ownership_and_accessibility_proven": False,
    }
    assert latest["saved_metrics"]["food_stock"] == 172
    assert latest["saved_metrics"]["drink_stock"] == 348
    assert latest["functioning_assessment"] == "operating_at_declared_boundary_with_production_gaps"
    assert outcomes[1]["functioning_assessment"] == "operating_with_incident_recovery"
    assert outcomes[2]["functioning_assessment"] == "operating_with_workshop_development"
    assert all("inventory_scope" not in row for row in outcomes[3:])


def test_all_saved_outcome_evidence_is_available_in_the_checkout(client):
    manifest = release_manifest()
    evidence = {row["url"]: row for row in manifest["source_evidence_files"]}
    assert len(evidence) == 16
    refs = [
        row[key]
        for row in client.get("/static/saved-outcomes.json").json()["outcomes"]
        for key in ("result", "review", "reload")
        if key in row
    ]
    assert len(refs) == 15
    for ref in refs:
        source = evidence[ref["url"]]
        assert source["sha256"] == ref["sha256"]
        assert source["url"] == (
            "https://github.com/lemoz/fort-gym/blob/"
            + source["source_revision"] + "/" + source["path"]
        )
        assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == ref["sha256"]


def test_final_stop_save_reload_and_publication_keep_distinct_proof(client):
    latest = client.get("/static/saved-outcomes.json").json()["outcomes"][0]
    manifest = release_manifest()
    assert latest["termination"] == manifest["termination"] == {
        "schema_version": "fortgym.watch-terminal-boundary/v1",
        "reason": "declared_response_boundary_reached",
        "response_limit": 1028,
        "next_decision_dispatched": False,
    }
    directory = ROOT / "experiments/evidence"
    save = json.loads((directory / "astra_keyboard_endurance_1028_save_20260913.json").read_text())
    reload = json.loads((directory / "astra_keyboard_endurance_1028_reload_20260913.json").read_text())
    delivery = json.loads((directory / "astra_keyboard_endurance_1028_website_20260913.json").read_text())
    assert save["fresh_reload"]["verified"] is False
    assert reload["final_native_reload_verified"] is True
    inspection = reload["operation"]["inspection"]
    for key in ("model_calls", "gameplay_actions", "observed_elapsed_ticks", "new_returned_tokens", "native_saves_requested"):
        assert inspection[key] == 0
    assert delivery["public_acceptance"]["passed"] is True
    assert delivery["website_revision"] == manifest["published_website_revision"]
    assert manifest["final_native_campaign_stopped"] is True


def test_current_quickstart_matches_bundled_replay_snapshot():
    manifest = release_manifest()
    text = (ROOT / "docs/YEAR_TWO_QUICKSTART.md").read_text()
    assert f'{manifest["recording_count"]} immutable recording windows' in text
    assert f'{manifest["frame_count"]:,} frames' in text
    assert "astra-keyboard-endurance-v1-965-1028" in text
    assert "YEAR_TWO_RELEASE_CHECKPOINT1028_20260913.md" in text
    assert "declared response limit" in text


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
