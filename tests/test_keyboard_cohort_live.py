import json
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api import keyboard_cohort as cohort
from fort_gym.bench.api import keyboard_cohort_live as live
from scripts import campaign_matched_observe as observer


@pytest.fixture
def value():
    plan = cohort._read(cohort.PLAN_PATH, cohort.PLAN_SHA256)
    return {
        "schema_version": live.SCHEMA, "campaign_id": "matched-20260910-terra-r2",
        "model": "gpt-5.6-terra", "reasoning_effort": "medium",
        "source_revision": cohort.PLAN_REVISION,
        "seed_receipt_sha256": plan["source_snapshot_receipt_sha256"],
        "execution_binding_sha256": cohort.STORAGE_BINDING, "data_disk_gib": 32,
        "controller_alive": True, "observed_at_unix": int(time.time()),
        "responses": 2, "returned_tokens": 30, "unsettled_claims": 1,
        "observed_elapsed_ticks_lower_bound": None,
        "teardown_reported": None, "reported_charge_usd": None,
    }


def test_expiry_privacy_and_stopped_are_separate_from_save_proof(value):
    value.update(private_prompt="secret", owner_pid=1, private_path="/private")
    now = value["observed_at_unix"]
    data = live.project_status(value, now=now)
    assert data["status"] == "controller_running"
    assert data["new_save_verified"] is False
    assert data["origin_kind"] == "independent_seed_trial"
    assert data["observed_elapsed_ticks_lower_bound"] is None
    assert data["reported_charge_usd"] is None
    assert not set(("private_prompt", "owner_pid", "private_path", "controller_alive")) & set(data)
    assert live.project_status(value, now=now + 31)["status"] == "stale"
    value.update(controller_alive=False, teardown_reported=True)
    assert live.project_status(value, now=now)["status"] == "controller_stopped"
    assert live.project_status(value, now=now + 31)["status"] == "stale"


@pytest.mark.parametrize("field,changed", [
    ("controller_alive", 1), ("responses", True), ("responses", 33),
    ("returned_tokens", -1), ("unsettled_claims", 31),
    ("reported_charge_usd", 0), ("observed_elapsed_ticks_lower_bound", False),
    ("teardown_reported", True), ("model", "gpt-6-astra"),
    ("campaign_id", "other"), ("data_disk_gib", 24),
    ("execution_binding_sha256", cohort.ORIGINAL_BINDING),
    ("observed_at_unix", 2**53), ("source_revision", "a" * 40),
])
def test_bad_conditions_types_and_unknowns_fail_closed(value, field, changed):
    value[field] = changed
    with pytest.raises(ValueError):
        live.project_status(value, now=int(time.time()))


def test_atomic_live_file_and_api_without_private_errors(tmp_path, value, monkeypatch):
    from fort_gym.bench.api import server
    assert live.live_status(tmp_path)["status"] == "not_connected"
    observer.publish_status(tmp_path, value)
    assert list(tmp_path.iterdir()) == [tmp_path / live.FILENAME]
    monkeypatch.setattr(server, "get_settings", lambda: SimpleNamespace(
        FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path)))
    client = TestClient(server.app)
    response = client.get("/public/keyboard-cohort-active")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["new_save_verified"] is False
    path = tmp_path / live.FILENAME
    path.write_text(" " * (live.MAX_BYTES + 1))
    response = client.get("/public/keyboard-cohort-active")
    assert response.status_code == 503 and str(tmp_path) not in response.text
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError):
        live.live_status(tmp_path)
    with pytest.raises(ValueError):
        observer.publish_status(tmp_path, value)


def receipt(root, index, feedback=None):
    identity = f"{index:032x}"
    folder = root / "model" / identity
    folder.mkdir(parents=True)
    request = {
        "schema_version": "fortgym.keyboard-exchange-request/v3",
        "request_id": identity, "model": "gpt-5.6-terra", "reasoning_effort": "medium",
        "screen": {"width": 120, "height": 40, "tiles": [[65, 7, 0]] * 4800},
        "memory": "" if index == 0 else "fixture", "feedback": feedback,
        "control_profile": "native_keyboard/v2", "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1", "max_advance_ticks": 2000,
    }
    summary = {"decision_index": index, "request_id": identity, "model_dispatched": True,
               "total_tokens": 15, "reported_charge_usd": None}
    response = {"request_sha256": digest(request), "result": {"transport_receipt": {
        "dispatched": True, "total_tokens": 15, "reported_charge_usd": None}}}
    for name, data in (("request", request), ("summary", summary),
                       ("response", response), ("claim", {})):
        (folder / (name + ".json")).write_text(json.dumps(data))
    return folder


def test_snapshot_lower_bounds_claims_and_terminal_report(tmp_path, value):
    now = int(time.time())
    receipt(tmp_path, 0)
    assert observer.snapshot(tmp_path, value, alive=True, now=now)["observed_elapsed_ticks_lower_bound"] is None
    receipt(tmp_path, 1, {"simulation": {"ticks_advanced": 50}})
    pending = tmp_path / "model" / ("f" * 32)
    pending.mkdir()
    (pending / "claim.json").write_text("{}")
    data = observer.snapshot(tmp_path, value, alive=True, now=now)
    assert (data["responses"], data["returned_tokens"], data["unsettled_claims"]) == (2, 30, 1)
    assert data["observed_elapsed_ticks_lower_bound"] == 50
    assert data["teardown_reported"] is None
    (tmp_path / "result.json").write_text(json.dumps({
        "campaign_id": value["campaign_id"], "vm_observed_stopped": True}))
    assert observer.snapshot(tmp_path, value, alive=False, now=now)["teardown_reported"] is True


@pytest.mark.parametrize("mutation", ["hash", "model", "unknown_dispatch", "gap", "borrowed_memory"])
def test_bad_receipts_do_not_refresh_live_status(tmp_path, value, mutation):
    folder = receipt(tmp_path, 0)
    name = "response" if mutation == "hash" else "request" if mutation in ("model", "borrowed_memory") else "summary"
    path = folder / (name + ".json")
    data = json.loads(path.read_text())
    if mutation == "hash":
        data["request_sha256"] = "f" * 64
    elif mutation == "model":
        data["model"] = "gpt-6-astra"
    elif mutation == "unknown_dispatch":
        data["model_dispatched"] = None
    elif mutation == "gap":
        data["decision_index"] = 1
    else:
        data["memory"] = "borrowed"
    path.write_text(json.dumps(data))
    if name == "request":
        response_path = folder / "response.json"
        response = json.loads(response_path.read_text())
        response["request_sha256"] = digest(data)
        response_path.write_text(json.dumps(response))
    with pytest.raises(ValueError):
        observer.snapshot(tmp_path, value, alive=True, now=int(time.time()))


@pytest.mark.parametrize("changed", ["reused", "timeout"])
def test_owner_reuse_stops_but_observation_timeout_never_claims_stopped(tmp_path, value, monkeypatch, changed):
    run = tmp_path / value["campaign_id"]
    run.mkdir()
    operator = tmp_path / "operator_storage_v2.py"
    monkeypatch.setattr("sys.argv", ["observer", "--run-dir", str(run), "--operator", str(operator),
        "--execution", str(tmp_path / "execution.json"), "--public-dir", str(tmp_path / "public"),
        "--owner-pid", "123", "--index", "3"])
    calls = iter(["start -u operator_storage_v2.py 3", "another start -u operator_storage_v2.py 3"])
    def identity(pid):
        answer = next(calls)
        if changed == "timeout" and answer.startswith("another"):
            raise subprocess.TimeoutExpired("ps", 5)
        return answer
    monkeypatch.setattr(observer, "owner_identity", identity)
    monkeypatch.setattr(observer, "baseline", lambda *args: value)
    published = []
    monkeypatch.setattr(observer, "publish_status", lambda root, data: published.append(data))
    monkeypatch.setattr(observer.time, "sleep", lambda _: (_ for _ in ()).throw(StopIteration()))
    if changed == "timeout":
        with pytest.raises(RuntimeError, match="generator raised StopIteration"):
            observer.main()
        assert published == []
    else:
        observer.main()
        assert len(published) == 1 and published[0]["controller_alive"] is False


def test_live_ui_expires_even_after_a_failed_refresh(value):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    program = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.events = {}; }
  set textContent(v) { this.text = String(v); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(n => n.textContent).join(' '); }
  appendChild(v) { this.children.push(v); } replaceChildren(...v) { this.children = v; this.text = ''; }
  addEventListener(k, v) { this.events[k] = v; }
}
const data = JSON.parse(process.argv[2]), nodes = {}, timers = [];
let now = data.observed_at_unix * 1000, fail = false;
class Clock extends Date { static now() { return now; } }
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  Date: Clock, document: {hidden: false, addEventListener() {},
    getElementById: id => nodes[id] ||= new Element(), createElement: () => new Element()},
  fetch: async url => { assert.equal(url, '/public/keyboard-cohort-active'); return {ok: !fail, json: async () => data}; },
  setInterval: fn => timers.push(fn), setTimeout, clearTimeout, AbortController
});
(async () => {
  await new Promise(setImmediate);
  assert.match(nodes['matched-live-status'].textContent, /controller active/);
  assert.match(nodes['matched-live-content'].textContent, /not a verified|No new save/);
  assert.match(nodes['matched-live-content'].textContent, /Unknown/);
  fail = true; await nodes['refresh-matched-live'].events.click();
  assert.match(nodes['matched-live-status'].textContent, /Refresh failed/);
  now += 31000; timers[0]();
  assert.match(nodes['matched-live-status'].textContent, /stale/);
  assert.doesNotMatch(nodes['matched-live-status'].textContent, /controller active/);
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-e", program, str(cohort.PROJECT_ROOT / "web/static/campaign-matched-live.js"),
        json.dumps(live.project_status(value, now=value["observed_at_unix"]))],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
