"""A later reload supplements a paused save without promoting it into gameplay."""

from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_reloads import CHECKPOINT_RELOADS, checkpoint_reload


def test_later_reload_preserves_the_saved_pause_and_earlier_verification():
    data = records.keyboard_campaign_records()
    pause = data["paused_windows"][0]
    earlier, later = data["checkpoint_reloads"]
    assert data["checkpoint_reload_status"] == "available"
    assert earlier["checkpoint_cursor"] == 903
    assert earlier["evidence_revision"] == "4980cdd5e8c1961772f839eeaa848d196672ed6f"
    assert later["checkpoint_cursor"] == 929 and later["saved_elapsed_ticks"] == 292582
    assert later["parent_record"] == pause["window_id"]
    assert later["checkpoint_sha256"] == pause["checkpoint_sha256"]
    assert later["evidence_revision"] == "b1a73c746621f17e38b08fca061b1799c6a7025d"
    assert later["model_calls"] == later["new_tokens"] == later["new_game_ticks"] == 0
    assert later["new_checkpoint_created"] is later["gameplay_result"] is False
    assert later["fresh_native_reload_verified"] is later["teardown_verified"] is True
    assert pause["status"] == "paused" and pause["fresh_checkpoint_load_verified"] is False
    assert pause["progress"]["cumulative_model_responses"] == 1111
    assert pause["usage"]["campaign_tokens"] == 35385830
    assert pause["pause"]["unattempted_decisions"] == 6
    event = {"kind": "paused_window", "id": pause["window_id"]}
    assert data["continuation_events"].count(event) == 1
    assert not any(row["id"] == later["verification_id"] for row in data["continuation_events"])


def test_reload_does_not_guess_between_duplicate_checkpoint_parents():
    data = records.keyboard_campaign_records()
    pause = data["paused_windows"][0]
    with pytest.raises(ValueError, match="one matching saved parent"):
        checkpoint_reload(records.PROJECT_ROOT, CHECKPOINT_RELOADS[1], [pause, deepcopy(pause)])


@pytest.mark.parametrize("case", ["valid", "wrong-parent", "gameplay"])
def test_renderer_adds_verification_to_paused_save_only_when_matched(case):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    data = deepcopy(records.keyboard_campaign_records())
    later = data["checkpoint_reloads"][1]
    if case == "wrong-parent":
        later["checkpoint_sha256"] = "a" * 64
    elif case == "gameplay":
        later["new_game_ticks"] = 1
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
  const pause = full.slice(full.indexOf('Checkpoint 929 saved'), full.indexOf('Checkpoint 903 saved'));
  assert.match(pause, /Checkpoint 929 saved · window paused/);
  assert.match(pause, /292,582 ticks/); assert.match(pause, /1,111 responses/);
  assert.match(pause, /26 of 32 declared decisions/); assert.match(pause, /6 decision slots remain/);
  assert.match(pause, /35,385,830 campaign tokens/);
  assert.match(pause, /a separate fresh reload had not yet been verified/);
  assert.doesNotMatch(pause, /window complete/);
  if (scenario === 'valid') {
    assert.match(pause, /Checkpoint 929 reopened in a fresh game process/);
    assert.match(pause, /0 game ticks, 0 model calls and no new checkpoint/);
  } else assert.doesNotMatch(pause, /Later checkpoint verification/);
  assert.match(full, /Checkpoint 903 reopened in a fresh game process/);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                    json.dumps(data), case], check=True, capture_output=True, text=True, timeout=10)
