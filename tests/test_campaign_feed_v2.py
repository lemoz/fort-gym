"""Synthetic v2 publisher coverage, not a replacement for frozen native reports."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_campaign_feed import feed
from tests.test_campaign_profile_v2 import native_v2


def publish_metrics(tmp_path, monkeypatch, states):
    from fort_gym.bench.api import server

    publisher = feed(tmp_path / "public")
    publisher.start()
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(publisher.root)),
    )
    results = []
    with TestClient(server.app) as client:
        for step, state in enumerate(states, start=1):
            original = deepcopy(state)
            publisher.progress(
                {"status": "started"},
                SimpleNamespace(next_step=step, committed_elapsed_ticks=step * 2500),
                state,
            )
            assert state == original
            response = client.get("/public/campaign-feed")
            assert response.status_code == 200
            row = next(r for r in response.json()["campaigns"] if r["campaign_id"] == "campaign")
            assert row["committed_steps"] == step
            assert row["elapsed_ticks"] == step * 2500
            assert row["lifecycle"] == "running" and row["cleanup_verified"] is None
            assert row["functioning_fortress"] == row["fortress_collapse"] == "not_assessed"
            results.append(row["current_metrics"])
    return results


@pytest.mark.parametrize("population,drink", [(7, 60), (0, 0)])
def test_active_publisher_exposes_v2_native_counts_through_http(
    tmp_path, monkeypatch, population, drink
):
    state = native_v2()
    state["population"] = population
    state["stocks"]["drink"] = state["stock_observations"]["drink"]["units"] = drink
    metrics = publish_metrics(tmp_path, monkeypatch, [state])[0]
    assert metrics["population"] == population and metrics["drink_stock"] == drink
    assert all(metrics[key] is None for key in ("food_stock", "wood_stock", "stone_stock"))


def test_active_publisher_drops_unverified_drink_without_losing_population(tmp_path, monkeypatch):
    state = native_v2()
    incomplete = deepcopy(state)
    incomplete["stock_observations"]["drink"]["complete"] = False
    first, second = publish_metrics(tmp_path, monkeypatch, [state, incomplete])
    assert first["drink_stock"] == 60
    assert second["population"] == 7 and second["drink_stock"] is None


def test_active_publisher_does_not_reuse_previous_metrics_after_missing_read(tmp_path, monkeypatch):
    first, second = publish_metrics(tmp_path, monkeypatch, [native_v2(), None])
    assert first["population"] == 7 and first["drink_stock"] == 60
    assert all(value is None for value in second.values())
