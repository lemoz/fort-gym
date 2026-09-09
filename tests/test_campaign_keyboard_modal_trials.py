"""Recorded dialog handling is neither a saved campaign nor a model-score win."""

from copy import deepcopy
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_modal_trials import modal_trial
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.MODAL_TRIALS[0]
    return path, json.loads(path.read_bytes())


def test_recorded_dialog_trial_keeps_partial_success_and_terminal_failure_separate():
    from fort_gym.bench.api.server import app

    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    data = response.json()
    row = data["modal_trials"][-1]
    prior = data["prompt_trials"][-1]
    expected_events = [
        {"kind": "prompt_trial", "id": prior["trial_id"]},
        {"kind": "modal_trial", "id": row["trial_id"]},
    ]
    offset = data["continuation_events"].index(expected_events[0])
    assert data["continuation_events"][offset:offset + len(expected_events)] == expected_events
    assert row["status"] == "failed" and row["new_checkpoint_verified"] is False
    assert row["teardown_verified"] is True
    assert row["progress"]["native_modal_deferrals_verified"] == 4
    assert row["progress"]["checkpointed_elapsed_ticks"] == 198600
    assert row["progress"]["new_committed_unsaved_ticks"] == 12724
    assert row["progress"]["final_uncommitted_ticks"] is None
    assert row["progress"]["final_elapsed_ticks_complete"] is False
    assert row["progress"]["existing_known_lost_ticks"] == 35705
    assert row["usage"]["campaign_responses"] == 957
    assert row["usage"]["all_attempt_tokens"] == 30414985
    assert row["usage"]["reported_charge_usd"] is None
    assert row["last_unsaved_observation"]["food_stock"] is None
    assert row["underlying_read_failure_cause"] == "unverified_output_not_retained"


@pytest.mark.parametrize("path,value", [
    (("status",), "completed"), (("model",), "other"), (("reasoning_effort",), "low"),
    (("parent_checkpoint_sha256",), "a" * 64), (("parent_checkpoint_cursor",), 807),
    (("new_checkpoint_verified",), True), (("parent_checkpoint_unchanged",), False),
    (("parent_native_load_verified",), False), (("teardown_verified",), 1),
    (("container_oom_killed",), True), (("source_revision",), "bad"),
    (("independent_audit_sha256",), "bad"), (("integrity_audit_passed",), False),
    (("final_uncommitted_ticks",), 0), (("final_elapsed_ticks_complete",), True),
    (("final_requested_advance_ticks",), 1), (("final_input_keys_confirmed",), 0),
    (("committed_trace_cursor",), 808), (("new_responses",), True), (("new_responses",), 32),
    (("committed_trace_decisions",), 33), (("checkpointed_elapsed_ticks",), 211324),
    (("new_committed_unsaved_ticks",), 64001), (("final_uncommitted_decisions",), 0),
    (("native_modal_deferrals_verified",), 33), (("existing_loss_records",), 4),
    (("existing_known_lost_ticks",), 35091), (("existing_loss_ticks_complete",), True),
    (("model_selected_continuation_after_deferrals_verified",), False),
    (("underlying_read_failure_cause",), "oom"), (("memory_clears",), 34),
    (("sustainability_established",), True), (("year_two_success",), True),
    (("matched_comparison",), True), (("gameplay_collapse_established",), True),
    (("usage", "campaign_responses"), 939), (("usage", "new_tokens"), 0),
    (("usage", "campaign_tokens"), 28911047), (("usage", "all_attempt_tokens"), 30345981),
    (("usage", "historical_failed_delivery_tokens"), 0), (("usage", "reported_charge_usd"), 0),
    (("last_unsaved_observation", "food_stock"), 0),
    (("last_unsaved_observation", "drink_stock"), True),
])
def test_false_claims_or_lost_accounting_are_rejected(evidence_root, path, value):
    file, source = publication(evidence_root)
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "missing_prior", "ambiguous_prior", "ambiguous_save"])
def test_original_file_and_prior_attempt_are_required(evidence_root, kind):
    data = records.keyboard_campaign_records(evidence_root)
    file, source = publication(evidence_root)
    parents, prior = data["resumed_windows"], data["prompt_trials"]
    if kind == "missing":
        file.unlink()
    elif kind == "symlink":
        target = file.with_suffix(".original")
        file.rename(target)
        file.symlink_to(target)
    elif kind == "oversized":
        source["padding"] = "x" * 65536
        file.write_text(json.dumps(source))
    elif kind == "missing_prior":
        prior = []
    elif kind == "ambiguous_prior":
        prior = [*prior, deepcopy(prior[-1])]
    else:
        parents = [*parents, deepcopy(parents[-1])]
    with pytest.raises(ValueError):
        modal_trial(evidence_root, records.MODAL_TRIALS[0], parents, prior)


def test_private_fields_and_unlisted_files_are_not_projected(evidence_root, monkeypatch):
    before = records.keyboard_campaign_records(evidence_root)
    file, source = publication(evidence_root)
    source["prompt"] = source["continuation_note"] = "private-sentinel"
    source["usage"]["account"] = source["last_unsaved_observation"]["memory"] = "private-sentinel"
    file.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before
    monkeypatch.setattr(records, "MODAL_TRIALS", ())
    monkeypatch.setattr(records, "SAVED_SEGMENTS", ())
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", ())
    file.unlink()
    after = records.keyboard_campaign_records(evidence_root)
    assert after["modal_trials"] == []
    assert after["continuation_events"] == [
        event for event in before["continuation_events"]
        if event["kind"] not in {"modal_trial", "saved_segment", "completed_window"}
    ]


def test_dialog_trial_renderer_keeps_unknown_time_and_latest_first_order():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    program = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.children = []; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener() {}
}
const elements = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById(id) {return elements[id] ||= new Element();},
             createElement() {return new Element();}},
  fetch: async () => ({ok: true, json: async () => JSON.parse(process.argv[2])})
});
(async () => {
  await new Promise(setImmediate);
  const rendered = elements['keyboard-results'].textContent;
  assert.equal(elements['keyboard-results'].hidden, false);
  assert.ok(rendered.startsWith('Checkpoint 839 saved · window complete'));
  assert.ok(rendered.includes('Checkpoint 807 saved · restart interrupted'));
  const trial = rendered.slice(rendered.indexOf('Dialog handling worked'), rendered.indexOf('Memory experiment interrupted'));
  for (const text of ['198,600 ticks', '12,724 ticks', 'Final uncommitted game time Unknown',
    '4 paused-dialog receipts', 'Unknown time is not zero', 'underlying read failure is unknown',
    'Checkpoint 775', '35,705 lost ticks', '927,074 new tokens', '30,345,981 campaign tokens',
    '30,414,985 including', 'Unreported · Codex subscription', '12 living dwarves',
    '420 drinks', 'Food: Unknown', 'No new save', 'later read-retry repair was not tested']) {
    assert.ok(trial.includes(text), text);
  }
  assert.doesNotMatch(trial, /\$0|checkpoint 807|Final uncommitted game time0/);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(records.keyboard_campaign_records())], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
