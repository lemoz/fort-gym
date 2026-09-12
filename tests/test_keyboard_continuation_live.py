import json
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api import keyboard_cohort as cohort
from fort_gym.bench.api import keyboard_continuation_live as live
from scripts import campaign_continuation_observe as observer
from scripts import campaign_matched_observe as common


@pytest.fixture
def value():
    return {
        "schema_version": live.SCHEMA,
        **live.identity_fields("matched-20260910-astra-r1"),
        "controller_alive": True,
        "observed_at_unix": int(time.time()),
        "responses": 2,
        "returned_tokens": 30,
        "unsettled_claims": 1,
        "observed_elapsed_ticks_lower_bound": 50,
        "teardown_reported": None,
        "reported_charge_usd": None,
    }


def test_saved_baseline_and_new_progress_are_not_double_counted(value):
    value.update(memory="private", owner_pid=123, private_path="/private", new_save_verified=True)
    data = live.project_status(value, now=value["observed_at_unix"])
    assert data["status"] == "controller_running"
    assert data["origin_kind"] == "saved_campaign_checkpoint"
    assert data["source_checkpoint_verified"] is True and data["new_save_verified"] is False
    assert (data["start_decision"], data["end_decision"], data["responses"]) == (32, 64, 2)
    assert data["saved_elapsed_ticks_before_window"] == 11200
    assert data["new_elapsed_ticks_lower_bound"] == 50
    assert data["campaign_elapsed_ticks_lower_bound"] == 11250
    assert data["campaign_returned_tokens"] == 1043596 + 30
    assert data["campaign_returned_responses"] == 34
    assert data["data_disk_gib"] == 32 and data["reported_charge_usd"] is None
    assert not {"memory", "owner_pid", "private_path", "controller_alive"} & data.keys()
    assert live.project_status(value, now=value["observed_at_unix"] + 31)["status"] == "stale"
    value.update(controller_alive=False, teardown_reported=True)
    assert (
        live.project_status(value, now=value["observed_at_unix"])["status"] == "controller_stopped"
    )
    value["observed_elapsed_ticks_lower_bound"] = None
    data = live.project_status(value, now=value["observed_at_unix"])
    assert data["new_elapsed_ticks_lower_bound"] is None
    assert data["campaign_elapsed_ticks_lower_bound"] == 11200


@pytest.mark.parametrize(
    "field,changed",
    [
        ("schema_version", "fortgym.public-matched-live/v1"),
        ("controller_alive", 1),
        ("responses", True),
        ("responses", 33),
        ("unsettled_claims", 31),
        ("returned_tokens", -1),
        ("returned_tokens", 2**53 - 1),
        ("reported_charge_usd", 0),
        ("observed_elapsed_ticks_lower_bound", False),
        ("observed_elapsed_ticks_lower_bound", 2**53 - 1),
        ("teardown_reported", True),
        ("prior_checkpoint_sha256", "f" * 64),
        ("window_sha256", "f" * 64),
        ("declaration_revision", "a" * 40),
        ("model", "gpt-5.6-sol"),
        ("campaign_id", "matched-20260910-astra-r2"),
        ("data_disk_gib", 24),
        ("execution_binding_sha256", cohort.ORIGINAL_BINDING),
        ("source_revision", "a" * 40),
        ("observed_at_unix", 2**53),
    ],
)
def test_wrong_origins_types_and_bounds_do_not_refresh(value, field, changed):
    value[field] = changed
    with pytest.raises(ValueError):
        live.project_status(value, now=int(time.time()))


@pytest.mark.parametrize("identity", cohort.RESULTS)
def test_each_declared_attempt_uses_its_own_saved_baseline(value, identity):
    value.update(live.identity_fields(identity))
    result = live.project_status(value, now=value["observed_at_unix"])
    row, source, _, _ = live.source_record(identity)
    assert result["prior_checkpoint_sha256"] == row["result"]["checkpoint_sha256"]
    assert result["campaign_returned_tokens"] == source["returned_tokens"] + 30
    assert result["saved_elapsed_ticks_before_window"] == row["result"]["saved_elapsed_ticks"]


def test_public_file_endpoint_and_error_privacy(tmp_path, value, monkeypatch):
    from fort_gym.bench.api import server

    assert live.live_status(tmp_path)["status"] == "not_connected"
    common.publish_status(tmp_path, value, projector=live.project_status, filename=live.FILENAME)
    monkeypatch.setattr(
        server, "get_settings", lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path))
    )
    client = TestClient(server.app)
    route = "/public/keyboard-cohort-continuation-active"
    response = client.get(route)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json()["campaign_returned_responses"] == 34
    assert client.get("/public/keyboard-cohort-active").json()["status"] == "not_connected"
    path = tmp_path / live.FILENAME
    path.write_text(" " * (live.MAX_BYTES + 1))
    response = client.get(route)
    assert response.status_code == 503 and str(tmp_path) not in response.text
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError):
        live.live_status(tmp_path)
    with pytest.raises(ValueError):
        common.publish_status(
            tmp_path, value, projector=live.project_status, filename=live.FILENAME
        )


def receipt(root, index, memory, feedback):
    identity = f"{index:032x}"
    folder = root / "model" / identity
    folder.mkdir(parents=True)
    request = {
        "schema_version": "fortgym.keyboard-exchange-request/v3",
        "request_id": identity,
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
        "memory": memory,
        "feedback": feedback,
        "screen": {"width": 120, "height": 40, "tiles": [[65, 7, 0]] * 4800},
        "control_profile": "native_keyboard/v2",
        "observation_profile": "native_screen_text/v1",
        "prompt_profile": "native_keyboard_memory_replacement/v1",
        "max_advance_ticks": 2000,
    }
    summary = {
        "decision_index": index,
        "request_id": identity,
        "model_dispatched": True,
        "total_tokens": 15,
        "reported_charge_usd": None,
    }
    response = {
        "request_sha256": digest(request),
        "result": {
            "transport_receipt": {
                "dispatched": True,
                "total_tokens": 15,
                "reported_charge_usd": None,
            }
        },
    }
    for name, data in (
        ("request", request),
        ("summary", summary),
        ("response", response),
        ("claim", {}),
    ):
        (folder / (name + ".json")).write_text(json.dumps(data))
    return folder


def test_first_feedback_belongs_to_prior_window_and_is_not_added_again(tmp_path, value):
    receipt(tmp_path, 0, "saved memory", {"simulation": {"ticks_advanced": 2000}})
    data = common.snapshot(
        tmp_path,
        value,
        alive=True,
        now=int(time.time()),
        initial_memory="saved memory",
        allow_initial_feedback=True,
        projector=live.project_status,
    )
    assert data["responses"] == 1 and data["observed_elapsed_ticks_lower_bound"] is None
    receipt(tmp_path, 1, "new memory", {"simulation": {"ticks_advanced": 150}})
    data = common.snapshot(
        tmp_path,
        value,
        alive=True,
        now=int(time.time()),
        initial_memory="saved memory",
        allow_initial_feedback=True,
        projector=live.project_status,
    )
    projected = live.project_status(data, now=int(time.time()))
    assert projected["new_elapsed_ticks_lower_bound"] == 150
    assert projected["campaign_elapsed_ticks_lower_bound"] == 11350
    with pytest.raises(ValueError, match="initial agent"):
        common.snapshot(
            tmp_path,
            value,
            alive=True,
            now=int(time.time()),
            initial_memory="borrowed memory",
            allow_initial_feedback=True,
            projector=live.project_status,
        )


@pytest.fixture
def bound_owner(tmp_path, monkeypatch):
    identity = "matched-20260910-astra-r1"
    row, source, window, readiness = live.source_record(identity)
    run = tmp_path / (identity + "-continue-32-64-config-v3")
    (run / "config").mkdir(parents=True)
    actual_window = (
        cohort.PROJECT_ROOT
        / "experiments/keyboard_matched_continuations_20260910/astra_r1-32-64.json"
    )
    shutil.copyfile(actual_window, run / "config/window.json")
    operator = tmp_path / "operator_continue_v3.py"
    operator.write_text("# test-only owner")
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    usage = {"accounted_responses": 32, "total_tokens": source["returned_tokens"]}
    (checkpoint / "agent.json").write_text(
        json.dumps({"usage": usage, "memory": "private saved memory"})
    )
    for name in ("trace.jsonl", "usage.jsonl"):
        (checkpoint / name).write_text("{}\n")
    manifest = {
        "sha256": source["checkpoint_sha256"],
        "payload": {"campaign_id": identity, "next_step": 32},
    }
    monkeypatch.setattr(observer, "verify_checkpoint", lambda path: manifest)
    monkeypatch.setattr(observer, "reconciled_usage", lambda *args: usage)
    binding = {
        "operator_sha256": observer.file_sha(operator),
        "source_revision": cohort.PLAN_REVISION,
        "image_id": row["result"]["execution"]["image_id"],
        "initial_execution_sha256": cohort.STORAGE_BINDING,
        "condition_sha256": row["result"]["execution"]["condition_file_sha256"],
        "declaration_revision": live.DECLARATION_REVISION,
        "declaration_ci": "34535040094",
        "window_sha256": source["declaration_sha256"],
        "prior_checkpoint_sha256": source["checkpoint_sha256"],
        "maximum_new_responses": window["steps_per_segment"],
        "data_disk_gib": 32,
        **{
            "prior_" + name + "_sha256": observer.file_sha(
                checkpoint / (name + (".json" if name == "agent" else ".jsonl"))
            )
            for name in ("agent", "trace", "usage")
        },
        "initial_cohort_audits": {
            r["campaign_id"]: r["terminal_audit_sha256"] for r in readiness["inputs"]
        },
        "cohort_windows_sha256": {
            r["campaign_id"]: r["declaration_sha256"] for r in readiness["inputs"]
        },
    }
    launch = {
        "campaign_id": identity,
        "run_id": run.name,
        "binding": binding,
        "source_revision": cohort.PLAN_REVISION,
        "image_id": binding["image_id"],
        "model": "gpt-6-astra",
        "reasoning_effort": "medium",
    }
    (run / "launch.json").write_text(json.dumps(launch))
    return run, operator, checkpoint, launch


def test_baseline_binds_real_inventory_hook_and_keeps_memory_private(bound_owner):
    run, operator, checkpoint, _ = bound_owner
    base, memory, suffix = observer.baseline(run, operator, checkpoint, 0)
    assert memory == "private saved memory" and "memory" not in base
    assert suffix.endswith(live.DECLARATION_REVISION + " 34535040094")
    assert (
        base["prior_checkpoint_sha256"]
        == live.identity_fields(base["campaign_id"])["prior_checkpoint_sha256"]
    )


@pytest.mark.parametrize(
    "field",
    [
        "operator_sha256",
        "condition_sha256",
        "prior_checkpoint_sha256",
        "prior_agent_sha256",
        "prior_trace_sha256",
        "prior_usage_sha256",
        "window_sha256",
        "declaration_revision",
        "initial_cohort_audits",
        "cohort_windows_sha256",
    ],
)
def test_wrong_bound_owner_cannot_attach(bound_owner, field):
    run, operator, checkpoint, launch = bound_owner
    launch["binding"][field] = "changed"
    (run / "launch.json").write_text(json.dumps(launch))
    with pytest.raises(ValueError):
        observer.baseline(run, operator, checkpoint, 0)


@pytest.mark.parametrize("changed", ["reused", "timeout"])
def test_process_reuse_stops_and_timeout_never_claims_death(bound_owner, monkeypatch, changed):
    run, operator, checkpoint, _ = bound_owner
    _, _, suffix = observer.baseline(run, operator, checkpoint, 0)
    monkeypatch.setattr(
        "sys.argv",
        [
            "observer",
            "--run-dir",
            str(run),
            "--operator",
            str(operator),
            "--checkpoint",
            str(checkpoint),
            "--public-dir",
            str(run / "public"),
            "--owner-pid",
            "123",
            "--index",
            "0",
        ],
    )
    calls = iter(["first" + suffix, "second" + suffix])

    def identity(pid):
        answer = next(calls)
        if changed == "timeout" and answer.startswith("second"):
            raise subprocess.TimeoutExpired("ps", 5)
        return answer

    monkeypatch.setattr(observer, "owner_identity", identity)
    published = []
    monkeypatch.setattr(
        observer, "publish_status", lambda root, value, **kwargs: published.append(value)
    )
    monkeypatch.setattr(observer.time, "sleep", lambda _: (_ for _ in ()).throw(StopIteration()))
    if changed == "timeout":
        with pytest.raises(RuntimeError, match="generator raised StopIteration"):
            observer.main()
        assert published == []
    else:
        observer.main()
        assert len(published) == 1 and published[0]["controller_alive"] is False


def test_continuation_ui_keeps_saved_baseline_and_expires_after_refresh_failure(value):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    value["observed_elapsed_ticks_lower_bound"] = None
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
  fetch: async url => { assert.equal(url, '/public/keyboard-cohort-continuation-active'); return {ok: !fail, json: async () => data}; },
  setInterval: fn => timers.push(fn), setTimeout, clearTimeout, AbortController
});
(async () => {
  await new Promise(setImmediate);
  assert.match(nodes['continuation-live-status'].textContent, /continuation active/);
  assert.match(nodes['continuation-live-content'].textContent, /11,200/);
  assert.match(nodes['continuation-live-content'].textContent, /1,043,626/);
  assert.match(nodes['continuation-live-content'].textContent, /Unknown/);
  assert.match(nodes['continuation-live-content'].textContent, /does not verify a new save/);
  assert.doesNotMatch(nodes['continuation-live-content'].textContent, /Independent start/);
  fail = true; await nodes['refresh-continuation-live'].events.click();
  assert.match(nodes['continuation-live-status'].textContent, /Refresh failed/);
  now += 31000; timers[0]();
  assert.match(nodes['continuation-live-status'].textContent, /stale/);
  assert.doesNotMatch(nodes['continuation-live-status'].textContent, /continuation active/);
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(cohort.PROJECT_ROOT / "web/static/campaign-continuation-live.js"),
            json.dumps(live.project_status(value, now=value["observed_at_unix"])),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
