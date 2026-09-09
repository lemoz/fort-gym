"""Synthetic publication checks only; these fixtures are not native results."""

import copy
import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_continuations import keyboard_continuation
from tests.test_campaign_keyboard_records import evidence_root as evidence_root

SAMPLE = "synthetic_postrestart_continuation.json"


@pytest.fixture
def postrestart(evidence_root, monkeypatch):
    monkeypatch.setattr(records, "POSTRESTART_CONTINUATIONS", ())
    monkeypatch.setattr(records, "PARTIAL_FAILURES", ())
    monkeypatch.setattr(records, "OOM_FAILURES", ())
    monkeypatch.setattr(records, "RESUMED_WINDOWS", ())
    monkeypatch.setattr(records, "PROMPT_TRIALS", ())
    monkeypatch.setattr(records, "MODAL_TRIALS", ())
    monkeypatch.setattr(records, "SAVED_SEGMENTS", ())
    data = records.keyboard_campaign_records(evidence_root)
    parent = data["restarts"][-1]
    folder = evidence_root / "experiments/evidence"
    source = json.loads((folder / records.CONTINUATIONS[-1]).read_text())
    source.update({
        "schema_version": "fortgym.native-keyboard-continuation-summary/v3",
        "snapshot_profile": "native_menu_preserving_save/v4",
        "parent_record": parent["restart_id"],
        "parent_checkpoint_cursor": 647,
        "parent_checkpoint_sha256": parent["checkpoint_sha256"],
        "new_model_calls": 64,
        "new_accepted_decisions": 64,
        "steps_per_segment": 64,
        "cumulative_model_responses": 791,
        "new_elapsed_ticks": 9600,
        "retained_elapsed_ticks": 153000,
        "new_tokens": 1000,
        "campaign_tokens": 23331797,
        "all_attempt_tokens": 23400801,
        "native_save_loss_restarts": 2,
        "discarded_native_ticks": 23200,
        "checkpoints": [{
            "cursor": 711, "elapsed_native_ticks": 153000,
            "sha256": "a" * 64, "parent_sha256": parent["checkpoint_sha256"],
            "checkpoint_verified": True,
        }],
    })
    source["food_inventory"]["initial_checkpoint_cursor"] = 647
    source["food_inventory"]["initial_units"] = 82
    source["execution_counts"]["requested_elapsed_ticks"] = 9600
    (folder / SAMPLE).write_text(json.dumps(source))
    return evidence_root, data, source


def test_postrestart_preserves_both_losses_and_all_historical_usage(postrestart, monkeypatch):
    root, before, _ = postrestart
    monkeypatch.setattr(records, "POSTRESTART_CONTINUATIONS", (SAMPLE,))
    after = records.keyboard_campaign_records(root)
    row = after["continuations"][-1]
    assert row["checkpoint_cursor"] == 711
    assert row["progress"]["cumulative_model_responses"] == 791
    assert row["progress"]["native_save_loss_restarts"] == 2
    assert row["progress"]["discarded_native_ticks"] == 23200
    assert row["usage"]["campaign_tokens"] == 23331797
    assert row["usage"]["all_attempt_tokens"] == 23400801
    assert row["usage"]["reported_charge_usd"] is None
    assert row["food_inventory"]["initial_checkpoint_cursor"] == 647
    assert row["new_restart_performed"] is row["uninterrupted_campaign"] is False
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["snapshot_profile"] == "native_menu_preserving_save/v4"
    assert "operator_status" not in row
    assert after["continuations"][:-1] == before["continuations"]
    for key in ("restarts", "checkpoint_failures", "presave_failures", "save_acceptances"):
        assert after[key] == before[key]
    assert after["continuation_events"] == [
        *before["continuation_events"], {"kind": "continuation", "id": SAMPLE.removesuffix(".json")},
    ]


def test_postrestart_chain_inherits_parent_instead_of_old_failure_count(postrestart, monkeypatch):
    root, data, source = postrestart
    row = keyboard_continuation(root, SAMPLE, data["restarts"], data["checkpoint_failures"])
    following = copy.deepcopy(source)
    following.update({
        "parent_record": row["continuation_id"], "parent_checkpoint_cursor": 711,
        "parent_checkpoint_sha256": row["checkpoint_sha256"],
        "cumulative_model_responses": 855, "retained_elapsed_ticks": 162600,
        "campaign_tokens": 23332797, "all_attempt_tokens": 23401801,
        "checkpoints": [{
            "cursor": 775, "elapsed_native_ticks": 162600,
            "sha256": "b" * 64, "parent_sha256": row["checkpoint_sha256"],
            "checkpoint_verified": True,
        }],
    })
    following["food_inventory"]["initial_checkpoint_cursor"] = 711
    next_name = "synthetic_next_continuation.json"
    (root / "experiments/evidence" / next_name).write_text(json.dumps(following))
    monkeypatch.setattr(records, "POSTRESTART_CONTINUATIONS", (SAMPLE, next_name))
    after = records.keyboard_campaign_records(root)
    last = after["continuations"][-1]
    assert last["progress"]["native_save_loss_restarts"] == 2
    assert last["progress"]["discarded_native_ticks"] == 23200
    assert last["checkpoint_cursor"] == 775
    assert after["continuation_events"][-2:] == [
        {"kind": "continuation", "id": name.removesuffix(".json")}
        for name in (SAMPLE, next_name)
    ]


@pytest.mark.parametrize("field,value", [
    ("schema_version", "fortgym.native-keyboard-continuation-summary/v1"),
    ("schema_version", "fortgym.native-keyboard-continuation-summary/v2"),
    ("schema_version", "fortgym.native-keyboard-continuation-summary/v4"),
    ("snapshot_profile", "native_menu_preserving_save/v3"),
    ("parent_record", "missing"), ("parent_checkpoint_cursor", 631),
    ("parent_checkpoint_sha256", "b" * 64),
    ("cumulative_model_responses", 711), ("campaign_tokens", 1000),
    ("all_attempt_tokens", 23331797), ("new_tokens", 1001),
    ("native_save_loss_restarts", 1), ("native_save_loss_restarts", True),
    ("discarded_native_ticks", 2000), ("discarded_native_ticks", 21200),
    ("new_restart_performed", True), ("reset_memory", True), ("reset_usage", True),
    ("strategy_intervention", True), ("uninterrupted_campaign", True),
    ("historical_failed_run_reclassified_as_success", True),
    ("reported_charge_usd", 0), ("operator_status", "completed"),
    ("operator_observation_warning", None), ("teardown_verified", False),
    ("independent_retained_evidence_audit_passed", False),
    ("inherited_discontinuity_unchanged", False),
    ("final_checkpoint_fresh_reload_verified", True),
])
def test_postrestart_cannot_erase_loss_usage_or_weaken_provenance(postrestart, field, value):
    root, data, source = postrestart
    source[field] = value
    (root / "experiments/evidence" / SAMPLE).write_text(json.dumps(source))
    with pytest.raises(ValueError):
        keyboard_continuation(root, SAMPLE, data["restarts"], data["checkpoint_failures"])


@pytest.mark.parametrize("kind", ["legacy_restart", "legacy_continuation", "recovery"])
def test_postrestart_does_not_implicitly_upgrade_a_different_parent(postrestart, kind):
    root, data, source = postrestart
    parent = {
        "legacy_restart": data["restarts"][0],
        "legacy_continuation": data["continuations"][-1],
        "recovery": data["checkpoint_recoveries"][-1],
    }[kind]
    source["parent_record"] = parent.get("continuation_id", parent.get("recovery_id", parent.get("restart_id")))
    source["parent_checkpoint_sha256"] = parent["checkpoint_sha256"]
    (root / "experiments/evidence" / SAMPLE).write_text(json.dumps(source))
    with pytest.raises(ValueError, match="verified v4 parent"):
        keyboard_continuation(root, SAMPLE, [parent], data["checkpoint_failures"])


def test_postrestart_drops_private_content_and_requires_allowlisting(postrestart, monkeypatch):
    root, before, source = postrestart
    source["model_memory"] = source["screen"] = "private-secret"
    source["checkpoints"][0]["native_save"] = "private-secret"
    source["food_inventory"]["items"] = ["private-secret"]
    (root / "experiments/evidence" / SAMPLE).write_text(json.dumps(source))
    assert records.keyboard_campaign_records(root) == before
    monkeypatch.setattr(records, "POSTRESTART_CONTINUATIONS", (SAMPLE,))
    assert "private-secret" not in json.dumps(records.keyboard_campaign_records(root))


def test_postrestart_rendering_keeps_newest_save_and_original_failure(postrestart, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    root, _, _ = postrestart
    monkeypatch.setattr(records, "POSTRESTART_CONTINUATIONS", (SAMPLE,))
    data = records.keyboard_campaign_records(root)
    program = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.children = []; this.events = {}; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener(event, fn) { this.events[event] = fn; }
}
const elements = {};
const data = JSON.parse(process.argv[2]);
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {
    getElementById(id) { return elements[id] ||= new Element(); },
    createElement() { return new Element(); }
  },
  fetch: async () => ({ok: true, json: async () => data})
});
(async () => {
  await new Promise(setImmediate);
  assert.equal(elements['keyboard-results'].hidden, false);
  const rendered = elements['keyboard-results'].textContent;
  assert.ok(rendered.startsWith('Play continued · checkpoint 711'));
  assert.ok(rendered.indexOf('Play continued · checkpoint 711')
    < rendered.indexOf('New branch saved · checkpoint 647'));
  assert.ok(rendered.indexOf('New branch saved · checkpoint 647')
    < rendered.indexOf('Save failure before restart · checkpoint 631'));
  for (const text of [
    '64 new model decisions, 9,600 new ticks', '153,000 retained ticks',
    '791 accounted model responses', '23,331,797 campaign tokens',
    '23,400,801 including historical failed deliveries',
    'The earlier 23,200 lost ticks remain recorded',
    '82 at window start (checkpoint 647)', 'Unreported · Codex subscription',
    'final save still needed a separate fresh-process reload',
    'Recorded result, not a running campaign'
  ]) assert.ok(rendered.includes(text), text);
  assert.equal(rendered.split('Play continued · checkpoint 711').length - 1, 1);
  assert.equal(rendered.split('New branch saved · checkpoint 647').length - 1, 1);
  assert.doesNotMatch(rendered, /\$0/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node, "-e", program, str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
         json.dumps(data)], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_actual_postrestart_result_preserves_progress_warning_and_usage():
    data = records.keyboard_campaign_records()
    row = data["continuations"][-1]
    assert row["continuation_id"] == "astra_native_keyboard_postrestart_continuation_20260908"
    assert row["checkpoint_cursor"] == 711
    assert row["checkpoint_sha256"] == "34d325596121a9a6e3631b1ed0297a4c4558e0ae2fff39853f91c138e8335c57"
    assert row["progress"]["cumulative_model_responses"] == 791
    assert row["progress"]["new_model_calls"] == row["progress"]["new_accepted_decisions"] == 64
    assert row["progress"]["new_elapsed_ticks"] == 49200
    assert row["progress"]["retained_elapsed_ticks"] == 192600
    assert row["progress"]["discarded_native_ticks"] == 23200
    assert row["progress"]["native_save_loss_restarts"] == 2
    assert row["usage"]["new_tokens"] == 2039653
    assert row["usage"]["campaign_tokens"] == 25370450
    assert row["usage"]["all_attempt_tokens"] == 25439454
    assert row["usage"]["reported_charge_usd"] is None
    assert row["operator_status"] == "completed_with_warning"
    assert row["operator_observation_warning"] == {
        "operator_status": "completed_with_warning", "native_window_status": "completed",
        "kind": "terminal_container_observation_error", "command_exit_code": 128,
        "underlying_cause": "unverified", "original_error_retained": True,
    }
    assert row["outcome_counts"]["counts"]["completed_beds"] == {"start": 5, "end": 6}
    assert row["outcome_counts"]["counts"]["drink_units"] == {"start": 179, "end": 337}
    assert row["outcome_counts"]["advancing_decisions"] == 25
    assert row["outcome_counts"]["zero_tick_decisions"] == 39
    food = row["food_inventory"]
    assert food["initial_checkpoint_cursor"] == 647
    assert food["initial_units"] == 82 and food["final_units"] == 56
    assert food["observed_boundaries"] == 65 and food["complete_measurements"] == 64
    assert food["unknown_measurements"] == 1
    assert food["sustainability"] == "not_established"
    assert row["execution_counts"] == {
        "requested_elapsed_ticks": 49200, "model_input_rejections": 0,
        "rejected_native_key_events": 0, "menu_deferrals": 0, "clock_unavailable_timeouts": 0,
    }
    assert row["teardown_verified"] is True
    assert row["final_checkpoint_fresh_reload_verified"] is False
    event = {"kind": "continuation", "id": row["continuation_id"]}
    index = data["continuation_events"].index(event)
    assert data["continuation_events"][index - 1]["kind"] == "restart"
    assert data["continuation_events"][index + 1]["kind"] == "partial_failure"


@pytest.mark.parametrize("section,field,value", [
    (None, "operator_status", "failed"), (None, "operator_status", "completed"),
    (None, "operator_status", None), (None, "terminal_observation_warning_sha256", "bad"),
    (None, "terminal_observation_warning_sha256", None),
    (None, "operator_observation_warning", None),
    ("operator_observation_warning", "operator_status", "failed"),
    ("operator_observation_warning", "native_window_status", "failed"),
    ("operator_observation_warning", "kind", "exchange_observation_error"),
    ("operator_observation_warning", "command_exit_code", 137),
    ("operator_observation_warning", "command_exit_code", "128"),
    ("operator_observation_warning", "underlying_cause", "exit_race"),
    ("operator_observation_warning", "original_error_retained", False),
    ("operator_observation_warning", "original_error_retained", 1),
])
def test_terminal_warning_cannot_invent_cause_or_hide_original_error(
    evidence_root, section, field, value,
):
    path = evidence_root / "experiments/evidence" / records.POSTRESTART_CONTINUATIONS[0]
    source = json.loads(path.read_bytes())
    (source if section is None else source[section])[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_next_window_preserves_model_condition_memory_and_budget():
    from fort_gym.bench.run.keyboard_config import load_window

    root = records.PROJECT_ROOT
    condition = root / "experiments/campaign_astra_keyboard_20260907.json"
    before, previous = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908q.json")
    after, following = load_window(condition, root / "experiments/campaign_astra_keyboard_window_20260908r.json")
    assert before == after
    assert previous["continuation_from_next_step"] == 647
    assert following["continuation_from_next_step"] == 711
    for key in ("steps_per_segment", "max_segments", "snapshot_profile", "private_measurement_profile"):
        assert previous[key] == following[key]
    assert all(following[key] is False for key in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert "budget_extension" not in following and "restart" not in following
