"""The native harness and published spectator UI coexist without a game process."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

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
    assert len(catalog) == 32
    total = 0
    for row in catalog:
        response = client.get(f"/static/recordings/{row['id']}.json")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        total += len(response.json()["frames"])
    assert total == 2600


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
