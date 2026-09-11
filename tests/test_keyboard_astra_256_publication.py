"""Published Astra-256 evidence on the real registry, not synthetic future records."""

from dataclasses import replace
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_endurance_live_v2 as live
from fort_gym.bench.api import keyboard_endurance_records as records

IDENTITY = "matched-20260910-astra-r1"
RESULT_SHA = "a61dd8db4bb61b4bf5639e94ec58647423a27e1a73f9e08397af157db51e685e"
REVISION = "4bb97d6c4fe3b5a1f8acc7d416c46817bcff5100"


def terminal_observation():
    """Explicit replay of the stopped observer's last public counts."""
    return {
        **live.identity_fields(IDENTITY),
        "controller_alive": False,
        "observed_at_unix": 1789106452,
        "responses": 128,
        "returned_tokens": 5874925,
        "unsettled_claims": 0,
        "observed_elapsed_ticks_lower_bound": 82000,
        "teardown_reported": True,
        "reported_charge_usd": None,
    }


def test_actual_256_publication_preserves_all_six_128_records(monkeypatch):
    current = records.keyboard_endurance_records()
    with monkeypatch.context() as historical:
        historical.setattr(
            records, "RESULTS", {key: rows[:1] for key, rows in records.RESULTS.items()}
        )
        before = records.keyboard_endurance_records()
    assert (
        current["declared_trials"],
        current["recorded_endurance_windows"],
        current["recorded_endurance_boundaries"],
        current["latest_saved_responses"],
        current["latest_saved_tokens"],
    ) == (6, 7, 512, 896, 28581994)
    for row, prior in zip(current["trials"], before["trials"], strict=True):
        assert row["windows"][0] == prior["windows"][0]
        if row["campaign_id"] != IDENTITY:
            assert row == prior
            assert row["latest_result"]["next_decision"] == 128
    astra = current["trials"][0]
    saved = astra["latest_result"]
    assert [entry["result"]["next_decision"] for entry in astra["windows"]] == [128, 256]
    assert astra["windows"][-1]["evidence_sha256"] == RESULT_SHA
    assert "/" + REVISION + "/" in astra["latest_result_url"]
    assert saved["prior_checkpoint_sha256"] == astra["windows"][0]["result"]["checkpoint_sha256"]
    assert (
        saved["checkpoint_sha256"]
        == "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342"
    )
    assert (saved["new_responses"], saved["new_saved_ticks"], saved["saved_elapsed_ticks"]) == (
        128,
        84000,
        135400,
    )
    assert saved["usage"]["campaign_returned_tokens"] == 10419162
    assert saved["usage"]["reported_charge_usd"] is None
    assert saved["initial_metrics"] == astra["windows"][0]["result"]["saved_metrics"]
    assert tuple(
        saved["saved_metrics"][key]
        for key in (
            "population",
            "recorded_dead_citizens",
            "completed_beds",
            "completed_farms",
            "completed_workshops",
            "food_stock",
            "drink_stock",
        )
    ) == (7, 0, 8, 2, 3, 34, 199)
    assert [point["decision"] for point in saved["new_window_timeline"]] == list(range(129, 257))
    assert saved["new_window_timeline"][-1]["campaign_elapsed_ticks"] == 135400
    assert (
        saved["audit_sha256"] == "03ff01cbc906d2f286d874981c8fe1c387c5b9580091ad0a09b1b19ea8aa23ee"
    )
    assert saved["source_checkpoint_fresh_load_verified"] is True
    assert saved["checkpoint_verified"] is True
    assert saved["native_cleanup_verified"] is saved["vm_teardown_verified"] is True
    assert saved["final_fresh_reload_verified"] is False
    assert (
        saved["human_gameplay_rescue"]
        is saved["prompt_change"]
        is saved["budget_extension"]
        is False
    )
    assert saved["year_two_reached"] is saved["sustainability_established"] is False
    assert current["strong_ranking_supported"] is current["live_owner_status_included"] is False


def test_actual_audited_link_does_not_rewrite_stale_observation_or_128_parent():
    value = terminal_observation()
    observed = live.project_status(value, now=value["observed_at_unix"] + 60)
    row, parent, _ = live.source_record(IDENTITY)
    assert observed["status"] == "stale"
    assert observed["source_result_url"] == parent["evidence_url"]
    assert observed["audited_result_url"] == row["latest_result_url"]
    assert observed["saved_elapsed_ticks_before_window"] == 51400
    assert observed["returned_tokens_before_window"] == 4544237
    assert observed["campaign_returned_responses"] == 256
    assert observed["campaign_returned_tokens"] == 10419162
    assert observed["new_elapsed_ticks_lower_bound"] == 82000
    assert observed["campaign_elapsed_ticks_lower_bound"] == 133400
    assert row["latest_result"]["saved_elapsed_ticks"] == 135400
    assert observed["new_save_verified"] is False
    assert observed["teardown_reported"] is True
    assert observed["reported_charge_usd"] is None


def test_actual_routes_keep_historical_results_and_fail_closed_on_new_digest(tmp_path, monkeypatch):
    from fort_gym.bench.api import server

    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path)),
    )
    (tmp_path / live.FILENAME).write_text(json.dumps(terminal_observation()))
    client = TestClient(server.app)
    stable_routes = (
        "/public/keyboard-campaigns",
        "/public/keyboard-cohort",
        "/public/keyboard-cohort-continuations",
        "/public/keyboard-cohort-endurance-active",
    )
    before = [client.get(route).json() for route in stable_routes]
    route = "/public/keyboard-cohort-endurance-records"
    response = client.get(route)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_endurance_records()
    active = client.get("/public/keyboard-cohort-endurance-v2-active")
    assert active.status_code == 200
    assert "no-store" in active.headers["cache-control"]
    assert active.json()["audited_result_url"] == response.json()["trials"][0]["latest_result_url"]
    for result in (response, active):
        for private in ('"/Users/', '"owner_pid":', '"screen":', '"memory":', '"account_id":'):
            assert private not in result.text
    with monkeypatch.context() as historical:
        historical.setattr(
            records, "RESULTS", {key: rows[:1] for key, rows in records.RESULTS.items()}
        )
        assert before == [client.get(path).json() for path in stable_routes]
    changed = dict(records.RESULTS)
    first, latest = changed[IDENTITY]
    changed[IDENTITY] = (first, replace(latest, result_sha256="0" * 64))
    monkeypatch.setattr(records, "RESULTS", changed)
    for path in (route, "/public/keyboard-cohort-endurance-v2-active"):
        failed = client.get(path)
        assert failed.status_code == 503
        assert "/Users/" not in failed.text
