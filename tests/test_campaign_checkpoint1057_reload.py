"""Real final-save reload and corrected input counts remain later evidence."""

from copy import deepcopy
import hashlib
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root

FILENAME = "astra_native_keyboard_checkpoint1057_reload_20260910.json"
REVISION = "a542b0b732b2e59fe316b68d8140dd21bb9ecc39"


def test_final_reload_preserves_entire_previous_response_and_manifest_bytes():
    data = deepcopy(records.keyboard_campaign_records())
    reload = data["checkpoint_reloads"].pop()
    assert reload["verification_id"] == FILENAME.removesuffix(".json")
    assert reload["checkpoint_cursor"] == 1057 and reload["saved_elapsed_ticks"] == 456582
    assert reload["evidence_revision"] == REVISION
    assert reload["parent_record"] == data["completed_windows"][-1]["window_id"]
    assert reload["checkpoint_sha256"] == data["completed_windows"][-1]["checkpoint_sha256"]
    assert reload["new_game_ticks"] == reload["model_calls"] == reload["new_tokens"] == 0
    assert reload["normal_campaign_loop_restored"] is reload["teardown_verified"] is True
    assert reload["native_calendar"] == {"year": 31, "year_tick": 70183, "paused": True}
    inputs = reload["production_measurement"]
    assert inputs["brewable_plant_units"] == 69 and inputs["brewable_plant_stacks"] == 34
    assert inputs["brewable_plant_stacks_in_jobs"] == 0
    assert inputs["material_tokens"] == ["MUSHROOM_HELMET_PLUMP"]
    assert inputs["old_reported_brewable_plant_units"] == 0
    assert inputs["old_false_negative_reproduced"] is True
    assert inputs["old_false_negative_item_count"] == inputs["observed_plant_records"] == 34
    assert inputs["completed_brewing_measured"] is inputs["ownership_accessibility_assessed"] is False
    # Live-read from the clean 1bc49b9 parent: nothing but the new verification may change.
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == "eb0e79aa399fdbcdc5a7dc9de0638f40e599343d20f55d2b59c6a61195fbac90"
    path = records.PROJECT_ROOT / "experiments/evidence" / FILENAME
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "307efa0080b1fca70248fc99e7fb043c672f25f895fdbe9be0bbfb62b1b9f5c1"


@pytest.mark.parametrize("key,value", [
    ("schema_version", "unknown"), ("hook_profile", "old"),
    ("independent_inventory_scan_verified", 1), ("original_observation_unchanged", False),
    ("completed_brewing_measured", True), ("ownership_accessibility_assessed", True),
    ("brewable_plant_units", True), ("brewable_plant_units", -1),
    ("brewable_plant_units", 2**53), ("brewable_plant_stacks", 35),
    ("brewable_plant_stacks_in_jobs", 1), ("observed_plant_records", 33),
    ("old_false_negative_item_count", 35), ("old_false_negative_reproduced", False),
    ("old_reported_brewable_plant_units", None),
    ("material_tokens", "MUSHROOM_HELMET_PLUMP"), ("material_tokens", []),
    ("material_tokens", ["<private>"]), ("material_tokens", [["nested"]]),
    ("material_tokens", ["PLANT", "PLANT"]),
])
def test_invalid_production_evidence_never_promotes_or_hides_gameplay(evidence_root, key, value):
    before = records.keyboard_campaign_records(evidence_root)
    path = evidence_root / "experiments/evidence" / FILENAME
    source = json.loads(path.read_bytes())
    source["production_measurement"][key] = value
    path.write_text(json.dumps(source))
    after = records.keyboard_campaign_records(evidence_root)
    assert after["checkpoint_reload_status"] == "unavailable"
    assert after["checkpoint_reloads"] == []
    assert {k: v for k, v in before.items() if not k.startswith("checkpoint_reload")} == {
        k: v for k, v in after.items() if not k.startswith("checkpoint_reload")}


def test_optional_private_production_fields_are_not_published(evidence_root):
    before = records.keyboard_campaign_records(evidence_root)
    path = evidence_root / "experiments/evidence" / FILENAME
    source = json.loads(path.read_bytes())
    source["production_measurement"].update(private_inventory="private-sentinel", item_ids=[123])
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before


@pytest.mark.parametrize("case", ["valid", "legacy", "invalid-count", "unverified", "gameplay"])
def test_renderer_shows_later_inventory_without_turning_it_into_production(case):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    data = deepcopy(records.keyboard_campaign_records())
    reload = data["checkpoint_reloads"][-1]
    if case == "legacy":
        del reload["production_measurement"]
    elif case == "invalid-count":
        reload["production_measurement"]["brewable_plant_units"] = True
    elif case == "unverified":
        reload["production_measurement"]["independent_inventory_scan_verified"] = False
    elif case == "gameplay":
        reload["new_game_ticks"] = 1
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
  const section = elements['keyboard-results'].children[0], text = section.textContent;
  assert.match(text, /Checkpoint 1,057 saved · window complete/);
  assert.match(text, /456,582 ticks/);
  assert.match(text, /At publication, the final save was verified in process/);
  if (scenario === 'gameplay') assert.doesNotMatch(text, /Later checkpoint verification/);
  else assert.match(text, /Checkpoint 1,057 reopened in a fresh game process/);
  if (scenario === 'valid') {
    assert.match(text, /69 plant units in 34 unassigned stacks/);
    assert.match(text, /original scan reported 0; its record is unchanged/);
    assert.match(text, /not proof of ownership, accessibility or completed brewing/);
    const links = element => [element.href, ...element.children.flatMap(links)].filter(Boolean);
    assert.ok(links(section).includes('https://github.com/lemoz/fort-gym/blob/' + process.argv[4]
      + '/experiments/evidence/astra_native_keyboard_checkpoint1057_reload_20260910.json'));
  } else assert.doesNotMatch(text, /Corrected brewing-input scan/);
  assert.doesNotMatch(text, /sustainability established|\$0/);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(data), case, REVISION], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
