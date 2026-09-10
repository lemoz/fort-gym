"""A completed continuation may follow a saved pause without rewriting history."""

from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_window_sequence import saved_window_sequence
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def add_completed_fixture(root, monkeypatch):
    before = records.keyboard_campaign_records(root)
    parent = before["paused_windows"][-1]
    source = json.loads((root / "experiments/evidence" / records.PAUSED_WINDOWS[-1]).read_bytes())
    source.update(schema_version="fortgym.native-keyboard-completed-window/v2", status="completed",
                  parent_record=parent["window_id"], parent_checkpoint_sha256=parent["checkpoint_sha256"],
                  checkpoint_sha256="a" * 64, checkpoint_file_sha256="b" * 64)
    del source["pause"]
    p = source["progress"]
    p.update(parent_checkpoint_cursor=929, checkpoint_cursor=961,
             parent_elapsed_ticks=292582, saved_elapsed_ticks=324582, new_saved_ticks=32000,
             new_model_responses=32, cumulative_model_responses=1143)
    source["usage"].update(new_tokens=1000, campaign_tokens=35386830, all_attempt_tokens=35455834)
    source["food"].update(after_action_complete_readings=32, after_action_unknown_readings=0)
    source["clock_outcomes"].update(advancing_decisions=16, zero_tick_decisions=16, zero_tick_timeouts=0)
    source["checkpoints"] = [{
        "cursor": 961, "saved_elapsed_ticks": 324582, "new_saved_ticks": 32000,
        "new_model_responses": 32, "cumulative_model_responses": 1143, "campaign_tokens": 35386830,
        "checkpoint_sha256": "a" * 64, "checkpoint_file_sha256": "b" * 64,
        "parent_checkpoint_sha256": parent["checkpoint_sha256"], "fresh_load_verified": False,
    }]
    path = root / "experiments/evidence/fixture_completed_after_pause.json"
    path.write_text(json.dumps(source))
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", (*records.COMPLETED_WINDOWS, path.name))
    return before, path, source


def test_completed_after_pause_loads_in_lineage_order(evidence_root, monkeypatch):
    before, _, _ = add_completed_fixture(evidence_root, monkeypatch)
    data = records.keyboard_campaign_records(evidence_root)
    assert data["completed_windows"][:-1] == before["completed_windows"]
    assert data["paused_windows"] == before["paused_windows"]
    assert data["checkpoint_reloads"] == before["checkpoint_reloads"]
    assert data["continuation_events"][:-1] == before["continuation_events"]
    assert data["continuation_events"][-1] == {
        "kind": "completed_window", "id": "fixture_completed_after_pause"}
    assert data["completed_windows"][-1]["progress"]["checkpoint_cursor"] == 961


def test_registry_file_order_does_not_override_parent_dependencies(evidence_root, monkeypatch):
    add_completed_fixture(evidence_root, monkeypatch)
    ordered = records.keyboard_campaign_records(evidence_root)
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", tuple(reversed(records.COMPLETED_WINDOWS)))
    assert records.keyboard_campaign_records(evidence_root) == ordered


@pytest.mark.parametrize("change", ["missing", "self", "cycle", "duplicate", "duplicate_kind", "wrong_digest"])
def test_invalid_lineage_remains_rejected(evidence_root, monkeypatch, change):
    _, path, source = add_completed_fixture(evidence_root, monkeypatch)
    if change == "missing":
        source["parent_record"] = "missing"
    elif change == "self":
        source["parent_record"] = path.stem
    elif change == "cycle":
        pause_path = evidence_root / "experiments/evidence" / records.PAUSED_WINDOWS[0]
        pause = json.loads(pause_path.read_bytes())
        pause["parent_record"] = path.stem
        pause_path.write_text(json.dumps(pause))
    elif change == "duplicate":
        monkeypatch.setattr(records, "COMPLETED_WINDOWS", (*records.COMPLETED_WINDOWS, path.name))
    elif change == "duplicate_kind":
        monkeypatch.setattr(records, "PAUSED_WINDOWS", (*records.PAUSED_WINDOWS, path.name))
    else:
        source["parent_checkpoint_sha256"] = "c" * 64
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_duplicate_seed_parents_rejected():
    parents = records.keyboard_campaign_records()["saved_segments"]
    with pytest.raises(ValueError, match="duplicate saved parents"):
        saved_window_sequence(records.PROJECT_ROOT, (), (), [*parents, deepcopy(parents[-1])])


def test_empty_registry_preserves_no_windows():
    assert saved_window_sequence(records.PROJECT_ROOT, (), (), []) == []


def test_renderer_keeps_completed_child_above_its_unchanged_paused_parent(evidence_root, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    add_completed_fixture(evidence_root, monkeypatch)
    data = records.keyboard_campaign_records(evidence_root)
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
  assert.ok(full.startsWith('Checkpoint 961 saved · window complete'));
  const pause = full.indexOf('Checkpoint 929 saved · window paused');
  const prior = full.indexOf('Checkpoint 903 saved · window complete');
  assert.ok(pause > 0 && prior > pause);
  assert.ok(full.slice(pause, prior).includes('6 decision slots remain unattempted'));
  assert.ok(full.slice(0, pause).includes('32 new decisions saved'));
  assert.doesNotMatch(full.slice(0, pause), /year-two success|sustainability established|\$0/);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(data)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
