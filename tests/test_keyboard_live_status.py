import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api.keyboard_live import SCHEMA, live_status, project_status
from scripts.campaign_keyboard_observe import publish_status, snapshot
from fort_gym.bench.agent.keyboard_exchange import digest


@pytest.fixture
def value():
    return {
        "schema_version": SCHEMA,
        "run_id": "fixture",
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "source_revision": "a" * 40,
        "owner_alive": True,
        "observed_at_unix": 1000,
        "saved_checkpoint_cursor": 775,
        "saved_elapsed_ticks": 198600,
        "new_responses": 2,
        "new_tokens": 300,
        "campaign_responses": 926,
        "campaign_tokens": 1000,
        "all_attempt_tokens": 1100,
        "window_response_limit": 64,
        "deferrals_observed": 1,
        "unsaved_ticks_lower_bound": None,
        "reported_charge_usd": None,
    }


def test_projection_separates_fresh_liveness_from_saved_progress(value):
    value.update(private_prompt="secret", owner_pid=123, path="private")
    current = project_status(value, now=1010)
    assert current["status"] == "running" and current["new_save_verified"] is False
    assert current["unsaved_ticks_lower_bound"] is None
    assert all(
        key not in current
        for key in ("private_prompt", "owner_pid", "path", "owner_alive")
    )
    assert project_status(value, now=1031)["status"] == "stale"
    value["owner_alive"] = False
    assert project_status(value, now=1010)["status"] == "stopped"
    assert project_status(value, now=1031)["status"] == "stale"


@pytest.mark.parametrize(
    "key,changed",
    [
        ("observed_at_unix", 1020),
        ("observed_at_unix", True),
        ("owner_alive", 1),
        ("reported_charge_usd", 0),
        ("new_tokens", -1),
        ("new_responses", 65),
        ("campaign_responses", 0),
        ("campaign_tokens", 1),
        ("all_attempt_tokens", 0),
        ("unsaved_ticks_lower_bound", False),
        ("deferrals_observed", 3),
        ("model", "<script>alert(1)</script>"),
    ],
)
def test_invalid_live_data_is_not_published(value, key, changed):
    value[key] = changed
    with pytest.raises(ValueError):
        project_status(value, now=1000)


def test_bounded_atomic_derivative_and_absent_source(tmp_path, value):
    assert live_status(None) == {"schema_version": SCHEMA, "status": "not_connected"}
    with pytest.raises(ValueError):
        live_status(tmp_path)
    publish_status(tmp_path, value)
    assert live_status(tmp_path, now=1000)["status"] == "running"
    assert list(tmp_path.iterdir()) == [tmp_path / "keyboard-active.json"]
    target = tmp_path / "elsewhere"
    target.write_text(json.dumps(value))
    (tmp_path / "keyboard-active.json").unlink()
    (tmp_path / "keyboard-active.json").symlink_to(target)
    with pytest.raises(ValueError):
        live_status(tmp_path, now=1000)


def test_endpoint_no_cache_and_no_private_errors(tmp_path, value, monkeypatch):
    from fort_gym.bench.api import server

    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path)),
    )
    client = TestClient(server.app)
    response = client.get("/public/keyboard-active")
    assert response.status_code == 503 and str(tmp_path) not in response.text
    publish_status(tmp_path, value)
    response = client.get("/public/keyboard-active")
    assert (
        response.status_code == 200 and "no-store" in response.headers["cache-control"]
    )
    assert response.json()["status"] == "stale"


def test_snapshot_counts_only_completed_responses_and_subsequent_feedback(
    tmp_path, value
):
    base = {
        **value,
        "campaign_responses": 10,
        "campaign_tokens": 100,
        "historical_failed_delivery_tokens": 7,
    }
    folder = tmp_path / "attempt/model/one"
    folder.mkdir(parents=True)
    request = {
        "request_id": "one",
        "feedback": {"simulation": {"ticks_advanced": 20, "deferred": False}},
    }
    response = {
        "request_sha256": digest(request),
        "result": {
            "transport_receipt": {
                "total_tokens": 15,
                "dispatched": True,
                "reported_charge_usd": None,
            }
        },
    }
    summary = {
        "decision_index": 0,
        "request_id": "one",
        "model_dispatched": True,
        "total_tokens": 15,
        "reported_charge_usd": None,
    }
    for name, data in (
        ("request", request),
        ("response", response),
        ("summary", summary),
    ):
        (folder / (name + ".json")).write_text(json.dumps(data))
    result = snapshot(tmp_path, base, alive=True, now=1000)
    assert result["campaign_responses"] == 11 and result["campaign_tokens"] == 115
    assert (
        result["all_attempt_tokens"] == 122
        and result["unsaved_ticks_lower_bound"] is None
    )
    assert result["saved_elapsed_ticks"] == 198600
    second = folder.parent / "two"
    second.mkdir()
    request["request_id"] = "two"
    response["request_sha256"] = digest(request)
    next_summary = {**summary, "request_id": "two", "decision_index": 1}
    for name, data in (
        ("request", request),
        ("response", response),
        ("summary", next_summary),
    ):
        (second / (name + ".json")).write_text(json.dumps(data))
    result = snapshot(tmp_path, base, alive=True, now=1000)
    assert result["campaign_responses"] == 12 and result["campaign_tokens"] == 130
    assert (
        result["all_attempt_tokens"] == 137
        and result["unsaved_ticks_lower_bound"] == 20
    )
    summary["reported_charge_usd"] = 2
    (folder / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="charges"):
        snapshot(tmp_path, base, alive=True, now=1000)


def test_browser_state_expires_even_without_a_new_response(value):
    script = (
        Path(__file__).resolve().parents[1] / "web/static/campaign-keyboard-live.js"
    )
    data = project_status(value, now=1000)
    program = """
const assert = require('node:assert/strict');
const { state } = require(process.argv[1]);
const data = JSON.parse(process.argv[2]);
assert.equal(state(data, 1001), 'running');
assert.equal(state(data, 1031), 'stale');
assert.throws(() => state({...data, fresh_for_seconds: 600}, 1001));
assert.throws(() => state({...data, reported_charge_usd: 0}, 1001));
assert.equal(state({schema_version:data.schema_version,status:'not_connected'}, 1001), 'not_connected');
"""
    subprocess.run(["node", "-e", program, str(script), json.dumps(data)], check=True)


def test_stale_renderer_identifies_historical_save_and_points_to_recorded_results(value):
    script = Path(__file__).resolve().parents[1] / "web/static/campaign-keyboard-live.js"
    program = r'''
const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
class Element {
  constructor() { this.children = []; }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener() {}
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
}
const elements = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {hidden: false, addEventListener() {},
    getElementById: id => elements[id] ||= new Element(), createElement: () => new Element()},
  fetch: async () => ({ok: true, json: async () => JSON.parse(process.argv[2])}),
  setTimeout, clearTimeout, setInterval: () => 0, AbortController
});
(async () => {
  await new Promise(setImmediate);
  assert.match(elements['keyboard-live-status'].textContent, /Live feed is stale/);
  assert.match(elements['keyboard-live-status'].textContent, /Check recorded results below/);
  assert.match(elements['keyboard-live-content'].textContent, /At the last live observation/);
  assert.match(elements['keyboard-live-content'].textContent, /checkpoint 775/);
  assert.doesNotMatch(elements['keyboard-live-status'].textContent, /running|may still be active/);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    subprocess.run(["node", "-e", program, str(script), json.dumps(project_status(value, now=1031))], check=True)
