"""Fixture-only serial save publication checks; no native run result is invented."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_windows import completed_window
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


@pytest.fixture
def serial_publication(evidence_root, monkeypatch):
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", (records.COMPLETED_WINDOWS[0],))
    parent = records.keyboard_campaign_records(evidence_root)["completed_windows"][-1]
    folder = evidence_root / "experiments/evidence"
    source = json.loads((folder / records.COMPLETED_WINDOWS[0]).read_bytes())
    p, u = parent["progress"], parent["usage"]
    source.update(schema_version="fortgym.native-keyboard-completed-window/v2",
                  parent_record=parent["window_id"], parent_checkpoint_sha256=parent["checkpoint_sha256"],
                  checkpoint_sha256="b" * 64, checkpoint_file_sha256="d" * 64)
    source["progress"].update(parent_checkpoint_cursor=p["checkpoint_cursor"],
        checkpoint_cursor=p["checkpoint_cursor"] + 64, parent_elapsed_ticks=p["saved_elapsed_ticks"],
        saved_elapsed_ticks=p["saved_elapsed_ticks"] + 4000, new_saved_ticks=4000,
        new_model_responses=64, cumulative_model_responses=p["cumulative_model_responses"] + 64)
    source["usage"].update(new_tokens=6400, campaign_tokens=u["campaign_tokens"] + 6400,
                           all_attempt_tokens=u["all_attempt_tokens"] + 6400)
    source["food"].update(after_action_complete_readings=64, after_action_unknown_readings=0)
    source["saved_observation"].update(completed_tables=None, completed_chairs=None)
    source["clock_outcomes"].update(advancing_decisions=2, zero_tick_decisions=62, zero_tick_timeouts=0)
    source["checkpoints"] = [{
        "cursor": p["checkpoint_cursor"] + 32 * (index + 1),
        "saved_elapsed_ticks": p["saved_elapsed_ticks"] + 2000 * (index + 1),
        "new_saved_ticks": 2000, "new_model_responses": 32,
        "cumulative_model_responses": p["cumulative_model_responses"] + 32 * (index + 1),
        "campaign_tokens": u["campaign_tokens"] + 3200 * (index + 1),
        "checkpoint_sha256": ("a" if index == 0 else "b") * 64,
        "checkpoint_file_sha256": ("c" if index == 0 else "d") * 64,
        "parent_checkpoint_sha256": parent["checkpoint_sha256"] if index == 0 else "a" * 64,
        "fresh_load_verified": index == 0,
    } for index in range(2)]
    path = folder / "fixture_completed_two_segments.json"
    path.write_text(json.dumps(source))
    return path, source, parent


def project(root, fixture):
    path, source, parent = fixture
    path.write_text(json.dumps(source))
    return completed_window(root, path.name, [parent])


def test_serial_checkpoint_lineage_and_reload_evidence_are_projected(evidence_root, serial_publication):
    row = project(evidence_root, serial_publication)
    assert [item["cursor"] for item in row["checkpoints"]] == [871, 903]
    assert [item["fresh_load_verified"] for item in row["checkpoints"]] == [True, False]
    assert row["checkpoints"][-1]["checkpoint_sha256"] == row["checkpoint_sha256"]
    assert row["checkpoints"][-1]["campaign_tokens"] == row["usage"]["campaign_tokens"]
    assert row["fresh_checkpoint_load_verified"] is row["sustainability_established"] is False


@pytest.mark.parametrize("keys,value", [
    (("schema_version",), "fortgym.native-keyboard-completed-window/v3"),
    (("schema_version",), []), (("schema_version",), {}), (("schema_version",), False),
    (("checkpoints",), []), (("checkpoints",), None),
    (("saved_observation", "completed_tables"), True),
    (("saved_observation", "completed_chairs"), -1),
    (("checkpoints", 0, "cursor"), True), (("checkpoints", 0, "cursor"), 870),
    (("checkpoints", 0, "new_model_responses"), 0),
    (("checkpoints", 0, "saved_elapsed_ticks"), 0),
    (("checkpoints", 0, "new_saved_ticks"), -1),
    (("checkpoints", 0, "campaign_tokens"), 2**53),
    (("checkpoints", 0, "checkpoint_sha256"), "bad"),
    (("checkpoints", 0, "checkpoint_file_sha256"), "bad"),
    (("checkpoints", 0, "parent_checkpoint_sha256"), "f" * 64),
    (("checkpoints", 0, "fresh_load_verified"), False),
    (("checkpoints", 0, "fresh_load_verified"), 1),
    (("checkpoints", 1, "fresh_load_verified"), True),
    (("checkpoints", 1, "fresh_load_verified"), 0),
    (("checkpoints", 1, "parent_checkpoint_sha256"), "f" * 64),
    (("checkpoints", 1, "checkpoint_file_sha256"), "f" * 64),
    (("checkpoints", 1, "checkpoint_sha256"), "a" * 64),
    (("checkpoints", 1, "checkpoint_sha256"), "f" * 64),
    (("checkpoints", 1, "saved_elapsed_ticks"), 220583),
    (("checkpoints", 1, "cumulative_model_responses"), 1086),
    (("checkpoints", 1, "campaign_tokens"), 0),
    (("checkpoints", 1, "campaign_tokens"), 32368634),
])
def test_serial_inconsistencies_fail_closed(evidence_root, serial_publication, keys, value):
    source = serial_publication[1]
    target = source
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    with pytest.raises(ValueError):
        project(evidence_root, serial_publication)


@pytest.mark.parametrize("mutation", ["missing", "reordered", "oversized", "duplicate"])
def test_segment_list_must_be_complete_and_ordered(evidence_root, serial_publication, mutation):
    source = serial_publication[1]
    if mutation == "missing":
        del source["checkpoints"]
    elif mutation == "reordered":
        source["checkpoints"].reverse()
    elif mutation == "oversized":
        source["checkpoints"] = [{}] * 129
    else:
        source["checkpoints"][1] = deepcopy(source["checkpoints"][0])
    with pytest.raises(ValueError):
        project(evidence_root, serial_publication)


def test_private_segment_data_is_not_projected(evidence_root, serial_publication):
    before = project(evidence_root, serial_publication)
    serial_publication[1]["checkpoints"][0]["model_memory"] = "private-sentinel"
    assert project(evidence_root, serial_publication) == before


def test_segment_tick_budget_cannot_be_borrowed_from_another_segment(evidence_root, serial_publication):
    source, parent = serial_publication[1:]
    start = parent["progress"]["saved_elapsed_ticks"]
    source["progress"].update(new_saved_ticks=128000, saved_elapsed_ticks=start + 128000)
    source["clock_outcomes"].update(advancing_decisions=64, zero_tick_decisions=0)
    source["checkpoints"][0].update(new_saved_ticks=64001, saved_elapsed_ticks=start + 64001)
    source["checkpoints"][1].update(new_saved_ticks=63999, saved_elapsed_ticks=start + 128000)
    with pytest.raises(ValueError, match="Segment checkpoint lineage"):
        project(evidence_root, serial_publication)


def test_new_serial_window_extends_recorded_order(evidence_root, serial_publication, monkeypatch):
    path, _, parent = serial_publication
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", (*records.COMPLETED_WINDOWS, path.name))
    data = records.keyboard_campaign_records(evidence_root)
    assert data["continuation_events"][-2:] == [
        {"kind": "completed_window", "id": parent["window_id"]},
        {"kind": "completed_window", "id": path.stem},
    ]
    assert data["completed_windows"][-1]["checkpoints"][-1]["cursor"] == 903


def test_renderer_distinguishes_reloaded_intermediate_from_final_save(evidence_root, serial_publication, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", (*records.COMPLETED_WINDOWS, serial_publication[0].name))
    data = records.keyboard_campaign_records(evidence_root)
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
  const text = elements['keyboard-results'].textContent;
  assert.ok(text.startsWith('Checkpoint 903 saved · window complete'));
  assert.ok(text.includes('Checkpoint 871: 218,582 saved ticks · freshly reloaded into the next segment'));
  assert.ok(text.includes('Checkpoint 903: 220,582 saved ticks · final save; separate fresh reload not yet verified at publication'));
  assert.ok(text.includes('At publication, the final save was verified in process'));
  assert.ok(text.includes('Checkpoint 839 saved · window complete'));
  assert.doesNotMatch(text, /Checkpoint 903:.*freshly reloaded into the next segment/);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(data)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_recorded_y_preserves_both_saves_usage_food_and_completed_dining_furniture():
    data = records.keyboard_campaign_records()
    x, y = data["completed_windows"]
    assert y["parent_record"] == x["window_id"]
    assert [row["cursor"] for row in y["checkpoints"]] == [871, 903]
    assert [row["fresh_load_verified"] for row in y["checkpoints"]] == [True, False]
    assert y["progress"]["saved_elapsed_ticks"] == 268582
    assert y["progress"]["new_saved_ticks"] == 52000
    assert y["progress"]["cumulative_model_responses"] == 1085
    assert y["usage"]["campaign_tokens"] == 34521087
    assert y["usage"]["all_attempt_tokens"] == 34590091
    assert y["usage"]["reported_charge_usd"] is None
    assert y["saved_observation"]["completed_tables"] == y["saved_observation"]["completed_chairs"] == 1
    assert y["saved_observation"]["completed_beds"] == 11
    assert y["saved_observation"]["population"] == 16
    assert y["saved_observation"]["recorded_dead_citizens"] == 0
    assert y["food"]["raw_edible_units"] == 47 and y["food"]["trader_flagged_units"] == 0
    assert y["food"]["after_action_complete_readings"] == 64
    assert y["sustainability_established"] is y["year_two_reached"] is False
