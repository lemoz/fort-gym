"""Later reload evidence supplements an immutable completed gameplay record."""

from copy import deepcopy
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_reloads import checkpoint_reload, CHECKPOINT_RELOADS
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / CHECKPOINT_RELOADS[0]
    return path, json.loads(path.read_bytes())


def test_later_reload_does_not_rewrite_or_add_gameplay():
    data = records.keyboard_campaign_records()
    y = data["completed_windows"][-1]
    reload = data["checkpoint_reloads"][0]
    assert data["checkpoint_reload_status"] == "available"
    assert reload["parent_record"] == y["window_id"]
    assert reload["checkpoint_sha256"] == y["checkpoint_sha256"]
    assert reload["checkpoint_cursor"] == 903 and reload["saved_elapsed_ticks"] == 268582
    assert reload["fresh_native_reload_verified"] is reload["teardown_verified"] is True
    assert reload["model_calls"] == reload["new_tokens"] == reload["new_game_ticks"] == 0
    assert reload["gameplay_result"] is reload["new_checkpoint_created"] is False
    assert y["fresh_checkpoint_load_verified"] is False
    assert y["checkpoints"][-1]["fresh_load_verified"] is False
    assert y["progress"]["cumulative_model_responses"] == 1085
    assert y["usage"]["campaign_tokens"] == 34521087
    assert y["usage"]["reported_charge_usd"] is None
    assert data["continuation_events"][-1] == {"kind": "completed_window", "id": y["window_id"]}
    assert reload["disposable_save_tree_byte_identical"] is False
    assert reload["disposable_save_tree_difference"]["other_files_unchanged"] == 126


@pytest.mark.parametrize("key,value", [
    ("schema_version", "unknown"), ("checkpoint_sha256", "a" * 64),
    ("checkpoint_cursor", 902), ("retained_elapsed_native_ticks", 268583),
    ("cumulative_campaign_responses", 1086), ("campaign_tokens", 0),
    ("campaign_model", "other-model"), ("model_calls_to_reload", 1),
    ("new_model_tokens", False), ("observed_new_native_ticks", 1),
    ("native_saves_requested", 1), ("new_checkpoint_created", True),
    ("fresh_native_reload_verified", 1), ("normal_campaign_loop_restored", False),
    ("original_checkpoint_unchanged", False), ("vm_observed_stopped", False),
    ("disposable_save_tree_byte_identical", True), ("audit_sha256", "bad"),
    ("reported_campaign_charge_usd", 0), ("total_lost_ticks", 0),
    ("year_two_success", True), ("cross_model_comparison", True),
    ("recorded_date_utc", "2026-99-99"), ("native_calendar", {"year": True, "year_tick": 0, "paused": True}),
])
def test_bad_reload_is_not_promoted_or_allowed_to_hide_history(evidence_root, key, value):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source[key] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        checkpoint_reload(evidence_root, CHECKPOINT_RELOADS[0], before["completed_windows"])
    after = records.keyboard_campaign_records(evidence_root)
    assert after["checkpoint_reload_status"] == "unavailable" and after["checkpoint_reloads"] == []
    assert {key: value for key, value in before.items() if not key.startswith("checkpoint_reload")} == {
        key: value for key, value in after.items() if not key.startswith("checkpoint_reload")}


@pytest.mark.parametrize("kind", ["missing", "oversize", "symlink", "nonobject"])
def test_unreadable_verification_does_not_remove_completed_window(evidence_root, kind):
    path, source = publication(evidence_root)
    if kind in ("missing", "symlink"):
        path.unlink()
        if kind == "symlink":
            target = path.parent / "private.json"
            target.write_text(json.dumps(source))
            path.symlink_to(target)
    else:
        path.write_text(" " * 65537 if kind == "oversize" else "[]")
    data = records.keyboard_campaign_records(evidence_root)
    assert data["checkpoint_reload_status"] == "unavailable"
    assert data["completed_windows"][-1]["progress"]["checkpoint_cursor"] == 903


def test_private_fields_do_not_reach_api(evidence_root):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source.update(private_path="secret-path", account_id="secret-account", memory="secret-memory")
    source["native_calendar"]["map"] = "secret-map"
    source["disposable_save_tree_difference"]["private_log"] = "secret-log"
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before


def test_endpoint_serves_separate_verification_without_new_route():
    from fort_gym.bench.api.server import app

    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_campaign_records()


@pytest.mark.parametrize("case", ["valid", "wrong-parent", "gameplay", "unavailable", "legacy"])
def test_renderer_attaches_only_matching_no_gameplay_verification(case):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    data = deepcopy(records.keyboard_campaign_records())
    if case == "wrong-parent":
        data["checkpoint_reloads"][0]["checkpoint_sha256"] = "a" * 64
    elif case == "gameplay":
        data["checkpoint_reloads"][0]["new_game_ticks"] = 1
    elif case == "unavailable":
        data.update(checkpoint_reload_status="unavailable", checkpoint_reloads=[])
    elif case == "legacy":
        del data["checkpoint_reload_status"], data["checkpoint_reloads"]
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
const elements = {}, data = JSON.parse(process.argv[2]), scenario = process.argv[3];
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => elements[id] ||= new Element(), createElement: () => new Element()},
  fetch: async () => ({ok: true, json: async () => data})
});
(async () => {
  await new Promise(setImmediate);
  const full = elements['keyboard-results'].textContent;
  assert.ok(full.startsWith('Checkpoint 903 saved · window complete'));
  const y = full.slice(0, full.indexOf('Checkpoint 839 saved'));
  assert.match(y, /268,582 ticks/); assert.match(y, /1,085 responses/);
  assert.match(y, /At publication, the final save was verified in process/);
  assert.match(y, /separate fresh reload not yet verified at publication/);
  if (scenario === 'valid') {
    assert.match(y, /Later checkpoint verification/);
    assert.match(y, /Checkpoint 903 reopened in a fresh game process/);
    assert.match(y, /0 game ticks, 0 model calls and no new checkpoint/);
    assert.match(y, /two DFHack load-log lines/);
    const text = full.slice(full.indexOf('Checkpoint 839 saved'));
    assert.doesNotMatch(text, /Later checkpoint verification/);
  } else assert.doesNotMatch(full, /Checkpoint 903 reopened in a fresh game process/);
  if (scenario === 'unavailable') assert.match(elements['keyboard-status'].textContent, /verification is unavailable/);
  assert.notEqual(elements['keyboard-results'].hidden, true);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                    json.dumps(data), case], check=True, capture_output=True, text=True, timeout=10)
