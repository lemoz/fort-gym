"""The recorded continuation chain must not rewrite the original trial or cohort."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_binding_campaign as records
from fort_gym.bench.api import keyboard_binding_results as original
from fort_gym.bench.api import keyboard_endurance_records as historical


def test_cumulative_campaign_and_reload_identity_are_exact():
    old_trial = original.keyboard_binding_result()
    old_cohort = historical.keyboard_endurance_records()
    data = records.keyboard_binding_campaign()
    assert data["recorded_only"] is True and data["independent_attempts"] == 1
    assert data["included_in_historical_cohort"] is False
    assert data["responses"] == 96 and data["saved_elapsed_ticks"] == 59500
    assert data["confirmed_key_presses"] == 591
    assert data["usage"]["total_tokens"] == 2567162
    assert data["saved_metrics"]["completed_beds"] == 5
    assert data["saved_metrics"]["food_stock"] == 58
    assert data["saved_metrics"]["drink_stock"] == 121
    assert data["latest_window"]["elapsed_ticks"] == 30000
    assert data["latest_window"]["returned_tokens"] == 984136
    assert data["timeline"][:32] == old_trial["result"]["timeline"]
    assert [row["decision"] for row in data["timeline"]] == list(range(1, 97))
    assert sum(row["ticks_advanced"] for row in data["timeline"]) == 59500
    assert sum(row["returned_tokens"] for row in data["timeline"]) == 2567162
    first, middle, latest = data["checkpoints"]
    assert middle["responses"] == 64 and middle["separate_fresh_reload_verified"] is False
    assert middle["shutdown"]["guest_command_warning"] is True
    assert latest["shutdown"]["guest_command_warning"] is False
    earlier = records.read_result(records.RESULT_PATH, records.RESULT_SHA256)
    assert data["timeline"][32:64] == earlier["timeline"]
    assert data["saved_metrics"]["functional_rooms"] is None
    assert first["responses"] == 32 and first["separate_fresh_reload_verified"] is True
    assert latest["responses"] == 96 and latest["separate_fresh_reload_verified"] is False
    assert first["checkpoint_sha256"] != latest["checkpoint_sha256"]
    assert latest["reload_url"] is None
    assert original.keyboard_binding_result() == old_trial
    assert historical.keyboard_endurance_records() == old_cohort
    assert old_cohort["latest_saved_responses"] == 896


@pytest.mark.parametrize("path_name", ["RESULT_PATH", "LATEST_RESULT_PATH", "RELOAD_PATH"])
@pytest.mark.parametrize("mode", ["missing", "changed", "symlink", "oversize"])
def test_new_registered_evidence_is_required_and_unchanged(tmp_path, monkeypatch, path_name, mode):
    payloads = {
        name: (historical.PROJECT_ROOT / getattr(records, name)).read_bytes()
        for name in ("RESULT_PATH", "LATEST_RESULT_PATH", "RELOAD_PATH")
    }
    original_payload = (historical.PROJECT_ROOT / original.RESULT_PATH).read_bytes()
    monkeypatch.setattr(historical, "PROJECT_ROOT", tmp_path)
    initial = tmp_path / original.RESULT_PATH
    initial.parent.mkdir(parents=True)
    initial.write_bytes(original_payload)
    for name, raw in payloads.items():
        target = tmp_path / getattr(records, name)
        if name != path_name:
            target.write_bytes(raw)
        elif mode == "changed":
            target.write_bytes(raw + b"\n")
        elif mode == "symlink":
            target.symlink_to(initial)
        elif mode == "oversize":
            target.write_bytes(raw)
            monkeypatch.setattr(historical, "MAX_RECORD_BYTES", len(raw) - 1)
    with pytest.raises((OSError, ValueError)):
        records.keyboard_binding_campaign()


@pytest.mark.parametrize(
    "mutation", ["parent", "model", "tokens", "ticks", "row", "cohort", "reload"]
)
def test_chain_cannot_be_relabelled_or_double_counted(mutation):
    prior = original.keyboard_binding_result()["result"]
    result = records.read_result(records.RESULT_PATH, records.RESULT_SHA256)
    reload = records.read_result(records.RELOAD_PATH, records.RELOAD_SHA256)
    if mutation == "parent":
        result["source_checkpoint_sha256"] = "0" * 64
    elif mutation == "model":
        result["condition"]["model"] = "another-model"
    elif mutation == "tokens":
        result["usage"]["total_tokens"] += 1
    elif mutation == "ticks":
        result["saved_elapsed_ticks"] += 1
    elif mutation == "row":
        result["timeline"][0]["decision"] = 32
    elif mutation == "cohort":
        result["proof_limits"]["same_condition_as_historical_matched_cohort"] = True
    else:
        reload["checkpoint_sha256"] = result["checkpoint_sha256"]
    with pytest.raises(ValueError):
        records.validate_chain(prior, result, reload)


def test_http_preserves_older_endpoints_and_exposes_no_private_data(monkeypatch):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    paths = (
        "/public/keyboard-binding-results",
        "/public/keyboard-cohort",
        "/public/keyboard-cohort-continuations",
        "/public/keyboard-cohort-endurance-records",
        "/public/keyboard-campaigns",
    )
    before = {path: client.get(path).content for path in paths}
    response = client.get("/public/keyboard-binding-campaign")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_binding_campaign()
    assert "/Users/" not in response.text and "memory_update" not in response.text
    page = client.get("/campaigns")
    assert page.status_code == 200 and "/static/campaign-binding-campaign.js?v=4" in page.text
    assert "Original 32-decision trial" in page.text
    assert client.get("/static/campaign-binding-campaign.js").status_code == 200
    assert client.get("/static/campaign-binding-results.js").status_code == 200
    monkeypatch.setattr(records, "RESULT_SHA256", "0" * 64)
    unavailable = client.get("/public/keyboard-binding-campaign")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Displayed-key campaign evidence is unavailable"}
    assert {path: client.get(path).content for path in paths} == before


def test_cumulative_frontend_safe_text_and_stale_refresh():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/keyboard_binding_campaign_dom.cjs"),
            str(root / "web/static/campaign-binding-campaign.js"),
        ],
        input=json.dumps(records.keyboard_binding_campaign()),
        text=True,
        capture_output=True,
        check=True,
    )


@pytest.mark.parametrize("field", ["max_dispatches", "screen_size", "bindings_sha256"])
def test_later_window_full_configuration_cannot_change(field):
    prior = records.read_result(records.RESULT_PATH, records.RESULT_SHA256)
    result = records.read_result(records.LATEST_RESULT_PATH, records.LATEST_RESULT_SHA256)
    result["condition"][field] = "changed"
    with pytest.raises(ValueError, match="full condition"):
        records.validate_continuation(prior, result)


@pytest.mark.parametrize("field", ["source_result_path", "source_result_sha256"])
def test_registered_chain_requires_exact_parent_record(monkeypatch, field):
    original_read = records.read_result

    def changed(path, digest):
        result = original_read(path, digest)
        if path == records.LATEST_RESULT_PATH:
            result[field] = "changed"
        return result

    monkeypatch.setattr(records, "read_result", changed)
    with pytest.raises(ValueError, match="source result differs"):
        records.keyboard_binding_campaign()
