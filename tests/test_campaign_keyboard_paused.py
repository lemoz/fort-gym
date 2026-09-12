"""A saved admission pause remains distinct from completed and failed play."""

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_windows import completed_window
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.PAUSED_WINDOWS[0]
    return path, json.loads(path.read_bytes())


def test_paused_window_preserves_completed_history_and_usage():
    data = records.keyboard_campaign_records()
    row = data["paused_windows"][0]
    parent = next(window for window in data["completed_windows"]
                  if window["window_id"] == row["parent_record"])
    assert row["status"] == "paused"
    assert parent["status"] == "completed" and parent["progress"]["checkpoint_cursor"] == 903
    pause_index = data["continuation_events"].index({"kind": "paused_window", "id": row["window_id"]})
    assert data["continuation_events"][pause_index - 1:pause_index + 1] == [
        {"kind": "completed_window", "id": parent["window_id"]},
        {"kind": "paused_window", "id": row["window_id"]},
    ]
    assert row["progress"]["checkpoint_cursor"] == 929
    assert row["progress"]["new_model_responses"] == 26
    assert row["progress"]["saved_elapsed_ticks"] == 292582
    assert row["progress"]["new_saved_ticks"] == 24000
    assert row["progress"]["cumulative_model_responses"] == 1111
    assert row["progress"]["known_lost_ticks"] == 48429
    assert row["usage"]["new_tokens"] == 864743
    assert row["usage"]["campaign_tokens"] == 35385830
    assert row["usage"]["all_attempt_tokens"] == 35454834
    assert row["usage"]["reported_charge_usd"] is None
    assert row["saved_observation"]["drink_stock"] == 567
    assert row["saved_observation"]["completed_tables"] == 2
    assert row["food"]["raw_edible_units"] == 57
    assert row["food"]["after_action_complete_readings"] == 26
    assert row["checkpoint_verified"] is row["teardown_verified"] is True
    assert row["fresh_checkpoint_load_verified"] is row["year_two_reached"] is False
    assert row["matched_comparison"] is row["sustainability_established"] is False
    assert data["checkpoint_reloads"][0]["checkpoint_cursor"] == 903


@pytest.mark.parametrize("keys,value", [
    (("status",), "completed"), (("status",), "failed"),
    (("schema_version",), "fortgym.native-keyboard-completed-window/v2"),
    (("pause",), None), (("pause",), []),
    (("pause", "reason"), "provider_limit_reached"),
    (("pause", "decision_limit"), 26), (("pause", "decision_limit"), True),
    (("pause", "decision_limit"), 1025), (("pause", "unattempted_decisions"), 0),
    (("pause", "denied_request_index"), 27),
    (("pause", "denied_request_dispatched"), True),
    (("pause", "denied_request_tokens_added"), 1),
    (("pause", "denied_request_tokens_added"), False),
    (("pause", "undispatched_requests"), 2),
    (("pause", "included_usage_cutoff_percent"), 100),
    (("pause", "included_usage_cutoff_percent"), 90),
    (("pause", "previous_included_usage_cutoff_percent"), 0),
    (("pause", "operating_policy_changed"), False),
    (("pause", "api_fallback_used"), True),
    (("progress", "new_model_responses"), 32), (("usage", "reported_charge_usd"), 0),
    (("checkpoints",), []), (("checkpoints", 0, "fresh_load_verified"), True),
    (("checkpoints", 0, "parent_checkpoint_sha256"), "a" * 64),
])
def test_pause_cannot_claim_dispatch_completion_or_weaken_save_proof(evidence_root, keys, value):
    path, source = publication(evidence_root)
    target = source
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_completed_reader_cannot_accept_paused_schema(evidence_root):
    data = records.keyboard_campaign_records(evidence_root)
    with pytest.raises(ValueError, match="Unsupported saved window"):
        completed_window(evidence_root, records.PAUSED_WINDOWS[0], data["completed_windows"])


def test_private_admission_fields_do_not_reach_publication(evidence_root):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source["pause"].update(account_id="private-sentinel", windows=[{"used_percent": "private-sentinel"}])
    source["private_prompt"] = "private-sentinel"
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before


def test_pause_is_available_through_existing_endpoint():
    from fort_gym.bench.api.server import app

    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_campaign_records()


def test_renderer_distinguishes_saved_pause_and_preserves_prior_results():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
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
  document: {getElementById: id => elements[id] ||= new Element(), createElement: () => new Element()},
  fetch: async () => ({ok: true, json: async () => JSON.parse(process.argv[2])})
});
(async () => {
  await new Promise(setImmediate);
  const full = elements['keyboard-results'].textContent;
  assert.ok(full.includes('Checkpoint 929 saved · window paused'));
  const row = full.slice(full.indexOf('Checkpoint 929 saved'), full.indexOf('Checkpoint 903 saved'));
  for (const expected of ['26 of 32', '0 model tokens', '6 decision slots remain unattempted',
    'harness threshold, not proof that the provider limit was reached', '90% to a 98% cutoff',
    '292,582 ticks', '72.6%', '24,000 ticks', '16', '567 drinks', '57 raw-edible units',
    '2 tables and 1 chair', '35,385,830 campaign tokens', '35,454,834 including historical',
    'Unreported · Codex subscription', '48,429 lost ticks plus an unknown remainder',
    'final save; separate fresh reload not yet verified at publication', 'teardown verified']) {
    assert.ok(row.includes(expected), expected);
  }
  assert.doesNotMatch(row, /window complete|\$0|year-two success|sustainability established/);
  assert.ok(full.includes('Checkpoint 903 saved · window complete'));
  assert.ok(full.includes('Later checkpoint verification'));
  assert.ok(full.includes('full window remains failed; the first segment is saved'));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(records.keyboard_campaign_records())], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
