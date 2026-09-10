"""Publish the real completed AB run without promoting or rewriting its history."""

from copy import deepcopy
import hashlib
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root

WINDOW = "astra_native_keyboard_completed_window_20260910ab"
REVISION = "18086313ee34a7df70efe1974f342df882976138"


def test_real_year_two_result_preserves_all_four_saves_and_qualifications():
    data = records.keyboard_campaign_records()
    row = data["completed_windows"][-1]
    assert row["window_id"] == WINDOW and row["status"] == "completed"
    assert row["parent_record"] == "astra_native_keyboard_paused_window_20260910aa"
    assert row["evidence_revision"] == REVISION
    assert row["progress"] == {
        "parent_checkpoint_cursor": 929, "checkpoint_cursor": 1057,
        "parent_elapsed_ticks": 292582, "saved_elapsed_ticks": 456582,
        "new_saved_ticks": 164000, "new_model_responses": 128,
        "cumulative_model_responses": 1239, "loss_records": 6, "known_lost_ticks": 48429,
    }
    assert row["year_two_reached"] is row["checkpoint_verified"] is row["teardown_verified"] is True
    assert [c["cursor"] for c in row["checkpoints"]] == [961, 993, 1025, 1057]
    assert [c["saved_elapsed_ticks"] for c in row["checkpoints"]] == [340582, 386582, 410582, 456582]
    assert [c["fresh_load_verified"] for c in row["checkpoints"]] == [True, True, True, False]
    assert row["usage"]["campaign_tokens"] == 39994420
    assert row["usage"]["all_attempt_tokens"] == 40063424
    assert row["usage"]["new_tokens"] == 4608590
    assert row["usage"]["reported_charge_usd"] is None
    assert row["saved_observation"] == {
        "population": 16, "recorded_dead_citizens": 0, "drink_stock": 613,
        "completed_farms": 8, "planned_unfinished_farms": 0, "completed_beds": 13,
        "completed_workshops": 4, "completed_tables": 3, "completed_chairs": 3,
    }
    assert row["food"]["raw_edible_units"] == 75 and row["food"]["trader_flagged_units"] == 0
    assert row["resources"]["memory_peak_bytes"] == 1610616832 > row["resources"]["memory_limit_bytes"]
    assert row["clock_outcomes"] == {"zero_tick_timeouts": 0, "advancing_decisions": 82, "zero_tick_decisions": 46}
    assert row["fresh_checkpoint_load_verified"] is row["sustainability_established"] is False
    assert row["matched_comparison"] is row["loss_ticks_complete"] is False
    assert data["continuation_events"][-1] == {"kind": "completed_window", "id": WINDOW}


def test_entire_historical_public_response_is_unchanged():
    data = deepcopy(records.keyboard_campaign_records())
    data["completed_windows"] = [r for r in data["completed_windows"] if r["window_id"] != WINDOW]
    data["continuation_events"] = [r for r in data["continuation_events"] if r["id"] != WINDOW]
    data["checkpoint_reloads"] = [r for r in data["checkpoint_reloads"] if r["checkpoint_cursor"] != 1057]
    # Canonical response verified from the clean parent ab51ba914, before AB registration.
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == "8110a8539d6c860912ab3ff3818bd56c81bf9cd10b123c41deab8e17a1c3c3f8"


def test_real_lineage_does_not_depend_on_registry_order(monkeypatch):
    before = records.keyboard_campaign_records()
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", tuple(reversed(records.COMPLETED_WINDOWS)))
    assert records.keyboard_campaign_records() == before


def test_publication_bytes_stay_pinned_and_private_fields_are_ignored(evidence_root):
    path = evidence_root / "experiments/evidence" / (WINDOW + ".json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "b32b1f514064cfd201f97b1be1d7b5217dd2e36052708a2b085a388ccbfa9edb"
    before = records.keyboard_campaign_records(evidence_root)
    source = json.loads(path.read_bytes())
    source.update(evidence_revision="attacker", private_prompt="private-sentinel")
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before


def test_real_result_is_available_on_existing_endpoint():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    response = client.get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json()["completed_windows"][-1]["window_id"] == WINDOW
    assert "/static/campaign-keyboard.js?v=16" in client.get("/campaigns").text


@pytest.mark.parametrize("revision", [REVISION, "invalid/../../main", None])
def test_renderer_shows_retained_year_not_sustainability_and_links_exact_revision(revision):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    data = deepcopy(records.keyboard_campaign_records())
    data["completed_windows"][-1]["evidence_revision"] = revision
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
const elements = {}, data = JSON.parse(process.argv[2]);
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => elements[id] ||= new Element(), createElement: () => new Element()},
  fetch: async () => ({ok: true, json: async () => data})
});
(async () => {
  await new Promise(setImmediate);
  const first = elements['keyboard-results'].children[0], text = first.textContent;
  assert.ok(text.startsWith('Checkpoint 1,057 saved · window complete'));
  for (const expected of ['Elapsed game years 1.13', '456,582 ticks', '53,382 ticks beyond the first anniversary',
    '128 new decisions saved', '16', '613 drinks', '13 beds', '75 raw-edible units',
    '39,994,420 campaign tokens', '40,063,424 including historical', 'Unreported · Codex subscription',
    '48,429 lost ticks plus an unknown remainder', 'separate fresh reload not yet verified',
    'not proof of sustainable production or a matched model comparison']) assert.ok(text.includes(expected), expected);
  assert.doesNotMatch(text, /113\.2%|\$0|sustainability established/);
  assert.match(text, /Checkpoint 1,057 reopened in a fresh game process/);
  const links = first.children.filter(x => x.href).map(x => x.href);
  const revision = data.completed_windows.at(-1).evidence_revision;
  if (revision === process.argv[3]) assert.deepEqual(links, [
    'https://github.com/lemoz/fort-gym/blob/' + revision + '/experiments/evidence/astra_native_keyboard_completed_window_20260910ab.json'
  ]); else assert.equal(links.length, 0);
  const prior = elements['keyboard-results'].children[1];
  assert.ok(prior.textContent.startsWith('Checkpoint 929 saved · window paused'));
  assert.ok(prior.children.some(x => x.href?.includes('/blob/codex/campaign-codex-subscription/')));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(data), REVISION], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
