import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records


def test_keyboard_endpoint_preserves_unknown_charges_and_separate_milestones():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    response = client.get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    data = response.json()
    assert data == records.keyboard_campaign_records()
    assert data["live_tracking"] is False
    row = data["milestones"][0]
    assert row["progress"]["model_decisions"] == 8
    assert row["progress"]["elapsed_native_ticks"] == 6000
    assert row["usage"]["reported_charge_usd"] is None
    assert row["usage"]["all_attempt_tokens"] == 305806
    assert row["usage"]["campaign_tokens"] == 236802
    assert row["fortress_success"] == "not_assessed_in_public_operational_summary"
    assert "Astra Medium" in client.get("/campaigns").text
    assert client.get("/static/campaign-keyboard.js").status_code == 200


@pytest.fixture
def evidence_root(tmp_path):
    folder = tmp_path / "experiments/evidence"
    folder.mkdir(parents=True)
    for filename in (*records.PUBLISHED, *records.INTERRUPTIONS, *records.RECOVERIES,
                     *records.CHECKPOINT_FAILURES, *records.RESTARTS, *records.CHECKPOINT_REVIEWS,
                     *records.CHECKPOINT_RECOVERIES, *records.CONTINUATIONS,
                     records.TAIL_INTERRUPTION, *records.TAIL_RECOVERIES,
                     *records.PRESAVE_FAILURES, *records.SAVE_ACCEPTANCES, *records.PRESAVE_RESTARTS,
                     *records.POSTRESTART_CONTINUATIONS, *records.PARTIAL_FAILURES, *records.OOM_FAILURES,
                     *records.RESUMED_WINDOWS, *records.PROMPT_TRIALS, *records.MODAL_TRIALS,
                     *records.SAVED_SEGMENTS, *records.COMPLETED_WINDOWS, *records.PAUSED_WINDOWS,
                     *records.CHECKPOINT_RELOADS):
        shutil.copyfile(records.PROJECT_ROOT / "experiments/evidence" / filename, folder / filename)
    return tmp_path


def test_private_fields_and_unlisted_files_are_never_projected(evidence_root):
    path = evidence_root / "experiments/evidence" / records.PUBLISHED[0]
    value = json.loads(path.read_text())
    value["private_prompt"] = "secret-screen"
    value["campaign_result"]["map"] = "secret-map"
    value["usage"]["account_id"] = "secret-account"
    path.write_text(json.dumps(value))
    (path.parent / "private.json").write_text('{"token":"secret-token"}')
    assert "secret-" not in json.dumps(records.keyboard_campaign_records(evidence_root))


@pytest.mark.parametrize("mutation", ["zero", "tokens", "checkpoint", "teardown", "audit"])
def test_inconsistent_publications_are_rejected(evidence_root, mutation):
    path = evidence_root / "experiments/evidence" / records.PUBLISHED[0]
    value = json.loads(path.read_text())
    if mutation == "zero":
        value["usage"]["reported_charge_usd"] = 0
    elif mutation == "tokens":
        value["usage"]["total_tokens"] += 1
    elif mutation == "checkpoint":
        value["campaign_result"]["checkpoint_cursors"] = [4, 7]
    elif mutation == "teardown":
        value["attempts"][0]["teardown_verified"] = False
    else:
        value["campaign_result"]["independent_retained_evidence_audit_passed"] = False
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_missing_publication_is_not_empty_success(monkeypatch):
    from fort_gym.bench.api.server import app

    def missing():
        raise FileNotFoundError("private-path")

    monkeypatch.setattr(records, "keyboard_campaign_records", missing)
    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 503
    assert "private-path" not in response.text


def test_interruption_separates_latest_usage_from_resumable_checkpoint(evidence_root):
    path = evidence_root / "experiments/evidence" / records.INTERRUPTIONS[0]
    source = json.loads(path.read_text())
    source["progress"]["private_screen"] = "secret-screen"
    source["usage"]["account_id"] = "secret-account"
    path.write_text(json.dumps(source))
    row = records.keyboard_campaign_records(evidence_root)["interruptions"][0]
    assert "secret-" not in json.dumps(row)
    assert row["progress"]["committed_decisions"] == 100
    assert row["progress"]["returned_model_decisions"] == 101
    assert row["progress"]["latest_verified_checkpoint_cursor"] == 88
    assert row["recovery_requires_reconciliation"] and row["teardown_verified"]
    assert row["usage"]["campaign_tokens"] == 3231792
    assert row["usage"]["all_attempt_tokens"] == 3300796
    assert row["usage"]["reported_charge_usd"] is None


@pytest.mark.parametrize("section,field,value", [
    ("progress", "returned_model_decisions", 100),
    ("progress", "latest_verified_checkpoint_cursor", 100),
    ("progress", "elapsed_native_ticks", True),
    ("usage", "reported_charge_usd", 0),
    ("usage", "all_attempt_tokens", 3231792),
    ("usage", "failed_tail_model_tokens_included", 0),
])
def test_interruption_cannot_hide_tail_or_reset_cost(evidence_root, section, field, value):
    path = evidence_root / "experiments/evidence" / records.INTERRUPTIONS[0]
    source = json.loads(path.read_text())
    source[section][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_recovery_binds_original_failure_without_exposing_private_fields(evidence_root):
    path = evidence_root / "experiments/evidence" / records.RECOVERIES[0]
    source = json.loads(path.read_text())
    source["native_save_path"] = "secret-save"
    source["model_memory"] = "secret-memory"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["recoveries"][0]
    assert row["checkpoint_cursor"] == 101
    assert row["parent_checkpoint_cursor"] == 88
    assert row["elapsed_native_ticks"] == 29000
    assert row["model_calls_to_recover"] == row["native_keys_to_recover"] == 0
    assert row["native_ticks_to_recover"] == 0
    assert row["usage"]["all_attempt_tokens"] == 3300796
    assert row["usage"]["reported_charge_usd"] is None
    assert data["interruptions"][0]["recovery_requires_reconciliation"] is True
    assert row["original_failure_preserved"] is True
    assert "secret-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("original_interruption", "unknown"),
    ("original_failed_run_reclassified_as_success", True),
    ("native_recovery_checkpoint_verified", False),
    ("checkpoint_sha256", "wrong"),
    ("parent_checkpoint_cursor", 87),
    ("next_step", 102),
    ("elapsed_native_ticks", 30000),
    ("model_calls_to_recover", 1),
    ("native_keys_to_recover", 1),
    ("native_ticks_to_recover", False),
    ("campaign_tokens", 3231791),
    ("all_attempt_tokens_including_historical_failures", 3231792),
    ("reported_campaign_charge_usd", 0),
    ("source_bytes_unchanged", False),
    ("teardown_verified", False),
])
def test_recovery_cannot_invent_progress_discard_usage_or_relabel_failure(
    evidence_root, field, value,
):
    path = evidence_root / "experiments/evidence" / records.RECOVERIES[0]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("food_units", ["recorded", "historical", 27, 0, None])
def test_keyboard_javascript_renders_recorded_usage_and_failure(food_units):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    program = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const helpers = require(process.argv[1]);
assert.equal(helpers.cost({cost_basis:'codex_subscription_charge_unreported/v1',
  reported_charge_usd:null}), 'Unreported · Codex subscription');
for (const value of [0, false, '', undefined, '0']) {
  assert.equal(helpers.cost({reported_charge_usd:value}), 'Unknown');
}
class Element {
  constructor() { this.children = []; this.events = {}; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener(event, fn) { this.events[event] = fn; }
}
const elements = {};
const fakeDocument = {
  getElementById(id) { return elements[id] ||= new Element(); },
  createElement() { return new Element(); }
};
const data = JSON.parse(process.argv[2]);
let fail = false;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: fakeDocument,
  fetch: async url => {
    assert.equal(url, '/public/keyboard-campaigns');
    return {ok: !fail, json: async () => data};
  }
});
(async () => {
  await new Promise(setImmediate);
  assert.equal(elements['keyboard-results'].hidden, false);
  assert.match(elements['keyboard-results'].textContent, /236,802 campaign tokens/);
  assert.match(elements['keyboard-results'].textContent, /305,806 including failed/);
  assert.match(elements['keyboard-results'].textContent, /Unreported/);
  assert.match(elements['keyboard-results'].textContent, /Interrupted at 100 committed decisions/);
  assert.match(elements['keyboard-results'].textContent, /101 model responses/);
  assert.match(elements['keyboard-results'].textContent, /Checkpoint at interruption: decision 88/);
  assert.match(elements['keyboard-results'].textContent, /Recovery verified · checkpoint 101/);
  assert.match(elements['keyboard-results'].textContent, /0 new model calls, 0 replayed keys, 0 added ticks/);
  assert.match(elements['keyboard-results'].textContent, /Subsequently recovered as checkpoint 101/);
  assert.match(elements['keyboard-results'].textContent, /original interrupted window remains failed/);
  assert.match(elements['keyboard-results'].textContent, /Interrupted at 183 committed decisions/);
  assert.match(elements['keyboard-results'].textContent, /Unsupported model key names stopped the harness/);
  assert.match(elements['keyboard-results'].textContent, /184 model responses/);
  assert.match(elements['keyboard-results'].textContent, /Recovery verified · checkpoint 184/);
  assert.match(elements['keyboard-results'].textContent, /Subsequently recovered as checkpoint 184/);
  const newest = (data.paused_windows || []).at(-1) || data.completed_windows.at(-1);
  const label = newest.status === 'paused' ? 'paused' : 'complete';
  assert.ok(elements['keyboard-results'].textContent.startsWith(`Checkpoint ${newest.progress.checkpoint_cursor} saved · window ${label}`));
  assert.ok(elements['keyboard-results'].textContent.includes('Checkpoint 807 saved · restart interrupted'));
  assert.match(elements['keyboard-results'].textContent, /614 new game ticks are unsaved/);
  assert.match(elements['keyboard-results'].textContent, /507,860 new tokens/);
  assert.match(elements['keyboard-results'].textContent, /not a matched comparison/);
  assert.match(elements['keyboard-results'].textContent, /49,200 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /192,600 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /791 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /Runner observation warning: a final container check returned exit 128/);
  assert.match(elements['keyboard-results'].textContent, /container was then observed stopped with exit 0/);
  assert.match(elements['keyboard-results'].textContent, /New branch saved · checkpoint 647/);
  assert.ok(elements['keyboard-results'].textContent.includes('This window added no game time.'));
  assert.ok(elements['keyboard-results'].textContent.includes('Save failure before restart · checkpoint 631'));
  assert.match(elements['keyboard-results'].textContent, /Saved game time 143,400 ticks/);
  assert.match(elements['keyboard-results'].textContent, /Unsaved game time 21,200 ticks/);
  assert.match(elements['keyboard-results'].textContent, /Accounted model responses 711/);
  assert.match(elements['keyboard-results'].textContent, /22,819,077 campaign tokens/);
  assert.match(elements['keyboard-results'].textContent, /22,888,081 including historical/);
  assert.match(elements['keyboard-results'].textContent, /decision 695; there is no checkpoint/);
  assert.match(elements['keyboard-results'].textContent, /Save fix verified/);
  assert.match(elements['keyboard-results'].textContent, /did not recover the unsaved progress or restart gameplay/);
  assert.match(elements['keyboard-results'].textContent, /Native-predicate food units 82 43/);
  assert.match(elements['keyboard-results'].textContent, /63 complete food readings and 2 unknown/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 21,200 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /143,400 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /647 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /Completed farm plots 5 7/);
  assert.match(elements['keyboard-results'].textContent, /Installed beds 4 5/);
  assert.match(elements['keyboard-results'].textContent, /Completed workshops 3 4/);
  assert.match(elements['keyboard-results'].textContent, /Existing drink units 181 179/);
  assert.match(elements['keyboard-results'].textContent, /Play continued · checkpoint 567/);
  assert.match(elements['keyboard-results'].textContent, /Runner warning: the game completed and saved/);
  assert.match(elements['keyboard-results'].textContent, /exit 137/);
  assert.match(elements['keyboard-results'].textContent, /The cause is unverified; the original error is retained/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 7,200 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /122,200 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /583 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /Living dwarves 7 12/);
  assert.match(elements['keyboard-results'].textContent, /Existing drink units 172 181/);
  const latest = data.continuations.find(row => row.checkpoint_cursor === 631);
  if (latest.food_inventory) {
    const food = latest.food_inventory;
    const initialLabel = food.initial_units === null ? 'Unknown' : String(food.initial_units);
    const finalLabel = food.final_units === null ? 'Unknown' : String(food.final_units);
    assert.match(elements['keyboard-results'].textContent, /Measured food inventory/);
    assert.ok(elements['keyboard-results'].textContent.includes(`Native-predicate food units: ${initialLabel} at window start (checkpoint 567); ${finalLabel} at window end.`));
    assert.match(elements['keyboard-results'].textContent, /missing or partial reading is unknown, not zero/);
    assert.match(elements['keyboard-results'].textContent, /Earlier food unknowns remain unknown/);
    assert.match(elements['keyboard-results'].textContent, /Accessibility was not assessed/);
  } else {
    assert.doesNotMatch(elements['keyboard-results'].textContent, /Measured food inventory/);
  }
  assert.match(elements['keyboard-results'].textContent, /Food stocks are unverified/);
  assert.match(elements['keyboard-results'].textContent, /Play continued · checkpoint 503/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 14,000 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /115,000 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /519 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /64 inputs accepted; 0 rejected before native dispatch/);
  assert.match(elements['keyboard-results'].textContent, /14,000 ticks requested, 14,000 actually advanced/);
  assert.match(elements['keyboard-results'].textContent, /Menu-blocked requests: 0; verified clock timeouts: 0/);
  assert.match(elements['keyboard-results'].textContent, /Existing drink units 162 172/);
  assert.match(elements['keyboard-results'].textContent, /Play continued · checkpoint 439/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 24,000 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /101,000 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /455 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /63 inputs accepted; 1 rejected before native dispatch/);
  assert.match(elements['keyboard-results'].textContent, /26,000 ticks requested, 24,000 actually advanced/);
  assert.match(elements['keyboard-results'].textContent, /Menu-blocked requests: 1; verified clock timeouts: 0/);
  assert.match(elements['keyboard-results'].textContent, /12 decisions advanced game time; 52 did not advance it/);
  assert.match(elements['keyboard-results'].textContent, /Play continued · checkpoint 375/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 11,400 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /77,000 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /391 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /12,907,163 including historical/);
  assert.match(elements['keyboard-results'].textContent, /Completed farm plots 2 4/);
  assert.match(elements['keyboard-results'].textContent, /7 decisions advanced game time; 57 did not advance it/);
  assert.match(elements['keyboard-results'].textContent, /Recovery verified · checkpoint 311/);
  assert.match(elements['keyboard-results'].textContent, /327 existing model responses and 65,600 elapsed ticks preserved/);
  assert.match(elements['keyboard-results'].textContent, /Workshop clock interrupted · decision 310/);
  assert.match(elements['keyboard-results'].textContent, /15 new responses, 14 committed actions and 2,000 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /Subsequently recovered as checkpoint 311/);
  assert.match(elements['keyboard-results'].textContent, /10,765,958 including historical/);
  assert.match(elements['keyboard-results'].textContent, /Play continued · checkpoint 296/);
  assert.match(elements['keyboard-results'].textContent, /64 new model decisions, 14,400 new ticks/);
  assert.match(elements['keyboard-results'].textContent, /63,600 retained ticks/);
  assert.match(elements['keyboard-results'].textContent, /312 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /10,284,908 including historical/);
  assert.match(elements['keyboard-results'].textContent, /When this gameplay window ended, its final save still needed a separate fresh-process reload/);
  assert.match(elements['keyboard-results'].textContent, /Recovery verified · checkpoint 232/);
  assert.match(elements['keyboard-results'].textContent, /248 existing model responses and 49,200 elapsed ticks preserved/);
  assert.match(elements['keyboard-results'].textContent, /Menu selection is verified again after the save call returns/);
  assert.match(elements['keyboard-results'].textContent, /Recovery verified · checkpoint 216/);
  assert.match(elements['keyboard-results'].textContent, /Menu identity changed during saving/);
  assert.match(elements['keyboard-results'].textContent, /248 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /8,219,231 including historical/);
  assert.match(elements['keyboard-results'].textContent, /exact menu-field change was not captured/);
  assert.match(elements['keyboard-results'].textContent, /Checkpoint verification stopped · decision 216/);
  assert.match(elements['keyboard-results'].textContent, /Subsequently recovered as checkpoint 216 and verified in a fresh game process/);
  assert.match(elements['keyboard-results'].textContent, /no additional progress was lost/);
  assert.match(elements['keyboard-results'].textContent, /New branch saved · checkpoint 200/);
  assert.match(elements['keyboard-results'].textContent, /Subsequently recovered as checkpoint 232 and verified in a fresh game process/);
  assert.match(elements['keyboard-results'].textContent, /232 accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /7,775,559 including historical/);
  assert.match(elements['keyboard-results'].textContent, /retained trace: 47,200 ticks/);
  assert.match(elements['keyboard-results'].textContent, /216 total accounted model responses/);
  assert.match(elements['keyboard-results'].textContent, /46,000 retained elapsed ticks/);
  assert.match(elements['keyboard-results'].textContent, /Total discarded game time remains 2,000 ticks/);
  assert.match(elements['keyboard-results'].textContent, /Total discarded game time remains 23,200 ticks/);
  assert.match(elements['keyboard-results'].textContent, /7,053,040 including historical/);
  assert.match(elements['keyboard-results'].textContent, /518,169 tokens/);
  assert.match(elements['keyboard-results'].textContent, /not uninterrupted play or an independent comparison/);
  assert.match(elements['keyboard-results'].textContent, /Save failed after decision 200/);
  assert.match(elements['keyboard-results'].textContent, /16 accepted model responses and 2,000 new ticks were not preserved/);
  assert.match(elements['keyboard-results'].textContent, /Game save at this failure: decision 184, 44,000 elapsed ticks/);
  assert.match(elements['keyboard-results'].textContent, /newer game state is not resumable/);
  assert.match(elements['keyboard-results'].textContent, /6,534,871 including historical/);
  assert.match(elements['keyboard-results'].textContent, /unsaved tail used 531,913 tokens, all included/);
  assert.match(elements['keyboard-results'].textContent, /6,002,958 including historical/);
  assert.ok(elements['keyboard-results'].textContent.indexOf('Interrupted at 183')
    < elements['keyboard-results'].textContent.indexOf('Recovery verified · checkpoint 101'));
  assert.match(elements['keyboard-results'].textContent, /3,300,796 including historical/);
  assert.doesNotMatch(elements['keyboard-results'].textContent, /\$0/);
  assert.match(elements['keyboard-status'].textContent, /not a live activity/);
  fail = true;
  await elements['refresh-keyboard-campaigns'].events.click();
  assert.equal(elements['keyboard-results'].hidden, true);
  assert.equal(elements['refresh-keyboard-campaigns'].disabled, false);
  assert.match(elements['keyboard-status'].textContent, /could not be loaded/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    data = records.keyboard_campaign_records()
    if food_units == "historical":
        for row in [*data["continuations"], *data["resumed_windows"]]:
            row.pop("food_inventory", None)
    elif food_units != "recorded":
        # Synthetic rendering fixture only, never written to published evidence.
        historical = next(row for row in data["continuations"] if row["checkpoint_cursor"] == 631)
        historical["food_inventory"] = {
            "initial_checkpoint_cursor": 567, "initial_units": food_units, "final_units": food_units,
            "observed_boundaries": 65, "complete_measurements": 0 if food_units is None else 65,
            "unknown_measurements": 65 if food_units is None else 0,
        }
    subprocess.run(
        [
            node,
            "-e",
            program,
            str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
            json.dumps(data),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_rejected_input_projection_preserves_nonexecution_and_usage(evidence_root):
    path = evidence_root / "experiments/evidence" / records.INTERRUPTIONS[1]
    source = json.loads(path.read_text())
    source["raw_response"] = "private-response"
    source["progress"]["native_screen"] = "private-screen"
    path.write_text(json.dumps(source))
    row = records.keyboard_campaign_records(evidence_root)["interruptions"][1]
    assert row["progress"]["committed_decisions"] == 183
    assert row["progress"]["returned_model_decisions"] == 184
    assert row["progress"]["latest_verified_checkpoint_cursor"] == 181
    assert row["progress"]["failed_tail_key_events_confirmed"] == 0
    assert row["usage"]["failed_tail_model_tokens_included"] == 32731
    assert row["usage"]["campaign_tokens"] == 5933954
    assert row["usage"]["all_attempt_tokens"] == 6002958
    assert "private-" not in json.dumps(row)
    recovered = records.keyboard_campaign_records(evidence_root)["recoveries"][1]
    assert recovered["checkpoint_cursor"] == 184 and recovered["parent_checkpoint_cursor"] == 181
    assert recovered["original_interruption"] == row["interruption_id"]
    assert recovered["usage"]["campaign_tokens"] == row["usage"]["campaign_tokens"]
    assert recovered["model_calls_to_recover"] == recovered["native_keys_to_recover"] == 0


@pytest.mark.parametrize("kind", ["keys", "success", "tokens", "reason"])
def test_rejection_publication_cannot_claim_dispatch_or_erase_the_failure(evidence_root, kind):
    path = evidence_root / "experiments/evidence" / records.INTERRUPTIONS[1]
    source = json.loads(path.read_text())
    if kind == "keys":
        source["progress"]["failed_tail_key_events_confirmed"] = 1
    elif kind == "success":
        source["historical_run_reclassified_as_success"] = True
    elif kind == "tokens":
        source["usage"]["rejected_response_tokens_included"] = 0
    else:
        source["terminal_reason"] = "fortress_collapse"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
