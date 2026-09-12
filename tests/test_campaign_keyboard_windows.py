"""Completed windows preserve saved lineage without turning limits into success."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_windows import completed_window
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


@pytest.fixture(autouse=True)
def historical_x_only(monkeypatch):
    # Mutating a historical parent should not invalidate an unrelated descendant
    # fixture. The serial-publication tests cover descendant reconciliation.
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", (records.COMPLETED_WINDOWS[0],))
    monkeypatch.setattr(records, "PAUSED_WINDOWS", ())


def publication(root):
    path = root / "experiments/evidence" / records.COMPLETED_WINDOWS[0]
    return path, json.loads(path.read_bytes())


def test_completed_window_preserves_prior_failed_window_and_saved_progress():
    data = records.keyboard_campaign_records()
    row = data["completed_windows"][-1]
    assert data["continuation_events"][-2:] == [
        {"kind": "saved_segment", "id": row["parent_record"]},
        {"kind": "completed_window", "id": row["window_id"]},
    ]
    assert row["progress"]["checkpoint_cursor"] == 839
    assert row["progress"]["saved_elapsed_ticks"] == 216582
    assert row["progress"]["new_saved_ticks"] == 10000
    assert row["progress"]["cumulative_model_responses"] == 1021
    assert row["usage"]["campaign_tokens"] == 32362233
    assert row["usage"]["all_attempt_tokens"] == 32431237
    assert row["usage"]["reported_charge_usd"] is None
    assert row["food"]["raw_edible_units"] == 259
    assert row["food"]["trader_flagged_units"] == 210
    assert row["food"]["ownership_accessibility_assessed"] is False
    assert row["food"]["after_action_complete_readings"] == 32
    assert row["saved_observation"]["completed_farms"] == row["saved_observation"]["completed_beds"] == 8
    assert row["resources"]["memory_peak_bytes"] == row["resources"]["memory_limit_bytes"] == 1610612736
    assert row["resources"]["memory_max_events"] == 791
    assert row["resources"]["oom_events"] == row["resources"]["oom_kill_events"] == 0
    assert row["resources"]["headroom_established"] is False
    assert row["checkpoint_verified"] is row["parent_checkpoint_fresh_load_verified"] is True
    assert row["fresh_checkpoint_load_verified"] is row["year_two_reached"] is False
    assert data["saved_segments"][-1]["window_completed"] is False


@pytest.mark.parametrize("keys,value", [
    (("status",), "failed"), (("checkpoint_verified",), 1),
    (("fresh_checkpoint_load_verified",), True), (("teardown_verified",), False),
    (("sustainability_established",), True), (("loss_ticks_complete",), True),
    (("actions_replayed",), True), (("reset_usage",), True), (("reset_memory",), True),
    (("strategy_intervention",), True), (("model",), "<script>"), (("reasoning_effort",), None),
    (("source_revision",), "bad"), (("checkpoint_sha256",), "bad"),
    (("independent_audit_sha256",), "bad"), (("parent_checkpoint_sha256",), "a" * 64),
    (("parent_record",), "missing"), (("progress", "checkpoint_cursor"), 840),
    (("progress", "new_model_responses"), True), (("progress", "new_model_responses"), 1025),
    (("progress", "saved_elapsed_ticks"), 403200), (("progress", "known_lost_ticks"), 0),
    (("progress", "loss_records"), 0), (("usage", "new_tokens"), 0),
    (("usage", "all_attempt_tokens"), 0), (("usage", "reported_charge_usd"), 0),
    (("saved_observation", "population"), True), (("saved_observation", "completed_beds"), -1),
    (("food", "raw_edible_units"), 0), (("food", "complete"), 1),
    (("food", "available"), False), (("food", "trader_flagged_units"), 260),
    (("food", "after_action_complete_readings"), 31), (("food", "ownership_accessibility_assessed"), True),
    (("resources", "headroom_established"), True), (("resources", "memory_limit_bytes"), 0),
    (("resources", "oom_events"), True), (("resources", "memory_peak_bytes"), 2**53),
    (("clock_outcomes", "zero_tick_timeouts"), 32), (("clock_outcomes", "zero_tick_decisions"), 0),
    (("private_measurement_timeout_seconds",), True), (("private_measurement_timeout_seconds",), 31),
    (("max_advance_ticks",), True), (("max_advance_ticks",), 2501), (("max_advance_ticks",), 1),
])
def test_inconsistent_claims_rejected(evidence_root, keys, value):
    path, data = publication(evidence_root)
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "duplicate_parent", "missing_parent"])
def test_bounded_publication_and_unique_parent_required(evidence_root, kind):
    data = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    parents = data["saved_segments"]
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif kind == "oversized":
        source["padding"] = "x" * 65536
        path.write_text(json.dumps(source))
    elif kind == "duplicate_parent":
        parents = [*parents, deepcopy(parents[-1])]
    else:
        parents = []
    with pytest.raises(ValueError):
        completed_window(evidence_root, records.COMPLETED_WINDOWS[0], parents)


def test_unknown_food_and_observations_remain_unknown(evidence_root):
    path, source = publication(evidence_root)
    source["food"].update(available=False, complete=False, raw_edible_units=None,
                          trader_flagged_units=None, in_job_units=None,
                          after_action_complete_readings=31, after_action_unknown_readings=1)
    source["saved_observation"]["completed_farms"] = None
    path.write_text(json.dumps(source))
    row = records.keyboard_campaign_records(evidence_root)["completed_windows"][-1]
    assert row["food"]["available"] is False and row["food"]["raw_edible_units"] is None
    assert row["saved_observation"]["completed_farms"] is None


def test_elapsed_year_two_does_not_imply_sustainable_success(evidence_root):
    path, source = publication(evidence_root)
    source["progress"]["new_saved_ticks"] = 403200 - source["progress"]["parent_elapsed_ticks"]
    source["progress"]["saved_elapsed_ticks"] = 403200
    source["progress"].update(new_model_responses=128, checkpoint_cursor=935, cumulative_model_responses=1117)
    source["clock_outcomes"].update(advancing_decisions=100, zero_tick_decisions=28)
    source["food"]["after_action_complete_readings"] = 128
    path.write_text(json.dumps(source))
    row = records.keyboard_campaign_records(evidence_root)["completed_windows"][-1]
    assert row["year_two_reached"] is True
    assert row["sustainability_established"] is row["matched_comparison"] is False


def test_next_window_reuses_same_contract_and_can_declare_another_model(evidence_root):
    records_before = records.keyboard_campaign_records(evidence_root)
    parent = records_before["completed_windows"][-1]
    path, source = publication(evidence_root)
    source.update(parent_record=parent["window_id"], parent_checkpoint_sha256=parent["checkpoint_sha256"],
                  checkpoint_sha256="a" * 64, model="fixture-model")
    p = source["progress"]
    p.update(parent_checkpoint_cursor=839, checkpoint_cursor=871, parent_elapsed_ticks=216582,
             saved_elapsed_ticks=226582, cumulative_model_responses=1053)
    for key in ("campaign_tokens", "all_attempt_tokens"):
        source["usage"][key] += source["usage"]["new_tokens"]
    next_path = path.with_name("fixture_completed_window.json")
    next_path.write_text(json.dumps(source))
    row = completed_window(evidence_root, next_path.name, [parent])
    assert row["progress"]["checkpoint_cursor"] == 871 and row["model"] == "fixture-model"
    assert row["matched_comparison"] is False


def test_extra_private_data_is_not_projected(evidence_root):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source["prompt"] = source["saved_observation"]["memory"] = "private-sentinel"
    source["resources"]["environment"] = source["food"]["map"] = "private-sentinel"
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before


@pytest.mark.parametrize("food_available", [True, False])
def test_renderer_keeps_saved_food_resource_and_history_claims_distinct(food_available):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    program = r"""
const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
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
  document: {getElementById(id) {return elements[id] ||= new Element();}, createElement() {return new Element();}},
  fetch: async () => ({ok: true, json: async () => JSON.parse(process.argv[2])})
});
(async () => {
  await new Promise(setImmediate);
  const full = elements['keyboard-results'].textContent;
  assert.ok(full.startsWith('Checkpoint 839 saved · window complete'));
  const text = full.slice(0, full.indexOf('Checkpoint 807 saved'));
  for (const expected of ['216,582 ticks', '53.7%', '10,000 ticks', '32 new decisions saved',
    '420 drinks', '8 completed farms', '8 beds', '32,362,233 campaign tokens',
    '32,431,237 including historical', 'Unreported · Codex subscription', '48,429 lost ticks plus an unknown remainder',
    'At publication, the final save was verified in process', '791 memory-limit events', '0 OOM events',
    'Memory headroom is not established', 'teardown verified']) assert.ok(text.includes(expected), expected);
  assert.doesNotMatch(text, /\$0|sustainability established|year-two success/);
  if (JSON.parse(process.argv[2]).completed_windows[0].food.available) {
    for (const expected of ['259 raw-edible units', '210 trader-flagged units',
      'not a count of accessible fortress-owned food']) assert.ok(text.includes(expected), expected);
  } else {
    assert.ok(text.includes('Food measurement unavailable'));
    assert.doesNotMatch(text, /259 raw-edible|0 raw-edible/);
  }
  assert.ok(full.includes('full window remains failed; the first segment is saved'));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    data = records.keyboard_campaign_records()
    if not food_available:
        data["completed_windows"][0]["food"].update(available=False, complete=False,
                                                   raw_edible_units=None, trader_flagged_units=None, in_job_units=None)
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(data)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
