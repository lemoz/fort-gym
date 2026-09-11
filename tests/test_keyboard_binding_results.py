"""Real published pilot data, isolated from the unchanged historical cohort."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_binding_results as records
from fort_gym.bench.api import keyboard_endurance_records as historical


def test_exact_native_result_and_all_decisions_are_published_separately():
    before = historical.keyboard_endurance_records()
    data = records.keyboard_binding_result()
    assert data["recorded_only"] is True
    assert data["included_in_historical_cohort"] is False
    result = data["result"]
    assert result["responses"] == 32 and result["confirmed_key_presses"] == 248
    assert result["saved_elapsed_ticks"] == 15500
    assert result["usage"]["total_tokens"] == 785690
    assert result["usage"]["total_cost_usd"] is None
    assert result["saved_metrics"] == result["timeline"][-1]["metrics"]
    assert result["saved_metrics"]["completed_workshops"] == 2
    assert result["saved_metrics"]["completed_farms"] == 1
    assert result["saved_metrics"]["completed_beds"] == 0
    assert result["timeline"][7]["clock_error"] == "blocking_native_menu"
    assert result["timeline"][8]["ticks_advanced"] == 2000
    assert sum(row["returned_tokens"] for row in result["timeline"]) == 785690
    assert sum(row["ticks_advanced"] for row in result["timeline"]) == 15500
    assert not any(result["proof_limits"].values())
    assert "/aae122e086b4254ed6865bb5886b307a576032a1/" in data["result_url"]
    assert "/8b9fffa1de4f93506cbcbdf82fd154aeb17b5697/" in data["condition_url"]
    assert historical.keyboard_endurance_records() == before
    assert before["declared_trials"] == 6 and before["latest_saved_responses"] == 896


@pytest.mark.parametrize("mode", ["missing", "changed", "symlink", "oversize"])
def test_missing_or_changed_registered_evidence_fails_closed(tmp_path, monkeypatch, mode):
    data = (historical.PROJECT_ROOT / records.RESULT_PATH).read_bytes()
    monkeypatch.setattr(historical, "PROJECT_ROOT", tmp_path)
    target = tmp_path / records.RESULT_PATH
    target.parent.mkdir(parents=True)
    if mode == "changed":
        target.write_bytes(data + b"\n")
    elif mode == "symlink":
        actual = tmp_path / "private.json"
        actual.write_bytes(data)
        target.symlink_to(actual)
    elif mode == "oversize":
        target.write_bytes(data)
        monkeypatch.setattr(historical, "MAX_RECORD_BYTES", len(data) - 1)
    with pytest.raises((ValueError, OSError)):
        records.keyboard_binding_result()


@pytest.mark.parametrize("field", ["campaign_id", "source_revision", "schema_version"])
def test_identity_cannot_be_silently_relabelled(monkeypatch, field):
    data = copy.deepcopy(records.keyboard_binding_result()["result"])
    data[field] = "wrong"
    monkeypatch.setattr(records, "read_result", lambda *_: data)
    with pytest.raises(ValueError):
        records.keyboard_binding_result()


def test_http_and_page_contract_without_changing_cohort_or_leaking_paths(monkeypatch):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    before = client.get("/public/keyboard-cohort-endurance-records").json()
    response = client.get("/public/keyboard-binding-results")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_binding_result()
    assert "/Users/" not in response.text and "memory_update" not in response.text
    page = client.get("/campaigns")
    assert page.status_code == 200
    assert page.text.index('id="binding-results-title"') < page.text.index(
        'id="keyboard-cohort-title"'
    )
    assert client.get("/static/campaign-binding-results.js").status_code == 200
    assert client.get("/public/keyboard-cohort-endurance-records").json() == before
    monkeypatch.setattr(records, "RESULT_SHA256", "0" * 64)
    unavailable = client.get("/public/keyboard-binding-results")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Displayed-key evidence is unavailable"}
    assert client.get("/public/keyboard-cohort-endurance-records").json() == before


def test_packaged_evidence_is_identical_to_its_published_digest():
    payload = (historical.PROJECT_ROOT / records.RESULT_PATH).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == records.RESULT_SHA256


def test_frontend_real_record_unknowns_safe_text_and_refresh_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/keyboard_binding_results_dom.cjs"),
            str(root / "web/static/campaign-binding-results.js"),
        ],
        input=json.dumps(records.keyboard_binding_result()),
        text=True,
        capture_output=True,
        check=True,
    )
