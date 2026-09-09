"""A saved segment survives a failed window without erasing earlier losses."""

from copy import deepcopy
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_saved_segments import saved_segment
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.SAVED_SEGMENTS[0]
    return path, json.loads(path.read_bytes())


def test_saved_progress_and_failed_window_are_both_visible():
    from fort_gym.bench.api.server import app

    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    data = response.json()
    row = data["saved_segments"][-1]
    event = {"kind": "saved_segment", "id": row["saved_segment_id"]}
    index = data["continuation_events"].index(event)
    assert data["continuation_events"][index - 1:index + 1] == [
        {"kind": "modal_trial", "id": row["previous_trial"]},
        {"kind": "saved_segment", "id": row["saved_segment_id"]},
    ]
    assert row["checkpoint_verified"] is row["fresh_checkpoint_load_verified"] is True
    assert row["window_completed"] is row["year_two_success"] is False
    assert row["progress"] == {
        "parent_checkpoint_cursor": 775, "checkpoint_cursor": 807,
        "parent_elapsed_ticks": 198600, "saved_elapsed_ticks": 206582,
        "new_saved_ticks": 7982, "new_model_responses": 32,
        "cumulative_model_responses": 989, "loss_records": 6, "known_lost_ticks": 48429,
    }
    assert row["loss_ticks_complete"] is False
    assert row["usage"]["campaign_tokens"] == 31207909
    assert row["usage"]["all_attempt_tokens"] == 31276913
    assert row["usage"]["reported_charge_usd"] is None
    assert row["window_outcome"]["second_segment_final_clock"] is None
    assert row["window_outcome"]["second_segment_model_requests"] == 0
    assert row["saved_observation"] == {
        "population": 12, "recorded_dead_citizens": 0, "drink_stock": 404,
        "completed_farms": 7, "planned_unfinished_farms": 1,
        "completed_beds": 6, "completed_workshops": 4,
        "food_stock": None, "food_measurement_available": False,
    }


@pytest.mark.parametrize("path,value", [
    (("status",), "completed"), (("model",), "other"),
    (("checkpoint_verified",), 1), (("fresh_checkpoint_load_verified",), False),
    (("window_completed",), True), (("loss_ticks_complete",), True),
    (("year_two_success",), True), (("sustainability_established",), True),
    (("actions_replayed",), True), (("saved_memory_retained",), False),
    (("checkpoint_sha256",), "bad"), (("source_revision",), "bad"),
    (("independent_audit_sha256",), "bad"), (("parent_checkpoint_sha256",), "a" * 64),
    (("previous_trial",), "missing"), (("progress", "checkpoint_cursor"), 808),
    (("progress", "new_model_responses"), True), (("progress", "new_model_responses"), 65),
    (("progress", "saved_elapsed_ticks"), 403200), (("progress", "new_saved_ticks"), 0),
    (("progress", "cumulative_model_responses"), 32), (("progress", "loss_records"), 0),
    (("progress", "known_lost_ticks"), 0), (("usage", "new_tokens"), 0),
    (("usage", "campaign_tokens"), 861928), (("usage", "all_attempt_tokens"), 31207909),
    (("usage", "historical_failed_delivery_tokens"), 0), (("usage", "reported_charge_usd"), 0),
    (("window_outcome", "second_segment_final_clock"), 0),
    (("window_outcome", "second_segment_model_requests"), 1),
    (("window_outcome", "underlying_resource_cause"), "pids_limit"),
    (("window_outcome", "container_oom_killed"), True),
    (("saved_observation", "food_stock"), 70), (("saved_observation", "completed_farms"), True),
    (("saved_observation", "population"), -1), (("saved_observation", "population"), 2**53),
])
def test_inconsistent_public_claims_are_rejected(evidence_root, path, value):
    file, source = publication(evidence_root)
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "missing_prior", "duplicate_prior", "duplicate_save", "wrong_parent"])
def test_original_publication_and_unique_parents_are_required(evidence_root, kind):
    data = records.keyboard_campaign_records(evidence_root)
    file, source = publication(evidence_root)
    parents, prior = data["resumed_windows"], data["modal_trials"]
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
    elif kind == "duplicate_prior":
        prior = [*prior, deepcopy(prior[-1])]
    elif kind == "duplicate_save":
        parents = [*parents, deepcopy(parents[-1])]
    else:
        prior[-1]["parent_record"] = "another-save"
    with pytest.raises(ValueError):
        saved_segment(evidence_root, records.SAVED_SEGMENTS[0], parents, prior)


def test_private_fields_and_unlisted_files_are_not_exposed(evidence_root):
    before = records.keyboard_campaign_records(evidence_root)
    file, source = publication(evidence_root)
    source["prompt"] = source["saved_observation"]["memory"] = "private-sentinel"
    source["usage"]["account"] = "private-sentinel"
    file.write_text(json.dumps(source))
    file.with_name("astra_native_keyboard_unlisted.json").write_text("invalid")
    assert records.keyboard_campaign_records(evidence_root) == before


def test_saved_segment_renderer_keeps_progress_losses_and_unknowns_distinct():
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
  const start = rendered.indexOf('Checkpoint 807 saved · restart interrupted');
  assert.ok(start >= 0);
  const latest = rendered.slice(start, rendered.indexOf('Dialog handling worked'));
  for (const text of ['206,582 ticks', '51.2%', '7,982 ticks', '32 new decisions were saved',
    '0 recorded deaths', '404 drinks', '7 completed farms', '1 unfinished farm',
    '6 beds', '4 workshops', 'Food: Unknown', '989 responses', '861,928 tokens',
    '31,207,909 campaign tokens', '31,276,913 including', 'Unreported · Codex subscription',
    '6 historical losses', '48,429 lost ticks plus an unknown remainder',
    "second segment's final clock is Unknown", 'full window remains failed']) {
    assert.ok(latest.includes(text), text);
  }
  assert.doesNotMatch(latest, /\$0|8 completed farms|Food: 0/);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
                             json.dumps(records.keyboard_campaign_records())], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
