"""Failed native partial actions never become saved or free gameplay."""

import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_partial import SOURCE_DIGESTS, partial_failure
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.PARTIAL_FAILURES[0]
    return path, json.loads(path.read_text())


def test_recorded_failure_preserves_saved_game_and_extra_response():
    data = records.keyboard_campaign_records()
    failure = data["partial_failures"][-1]
    parent = data["continuations"][-1]
    assert failure["parent_record"] == parent["continuation_id"]
    assert failure["checkpoint_cursor"] == parent["checkpoint_cursor"] == 711
    assert failure["checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert failure["progress"] == {
        "checkpointed_elapsed_ticks": 192600,
        "committed_trace_next_step": 733,
        "committed_trace_elapsed_ticks": 198600,
        "new_committed_decisions": 22,
        "new_model_responses": 23,
        "new_committed_ticks": 6000,
        "uncommitted_responses": 1,
        "uncommitted_native_ticks": 691,
        "unsaved_new_native_ticks": 6691,
        "accounted_model_responses": 814,
        "inherited_save_loss_restarts": 2,
        "inherited_discarded_native_ticks": 23200,
    }
    assert failure["usage"] == {
        "new_tokens": 743053,
        "campaign_tokens": 26113503,
        "all_attempt_tokens": 26182507,
        "historical_failed_delivery_tokens": 69004,
        "reported_charge_usd": None,
        "cost_basis": "codex_subscription_charge_unreported/v1",
    }
    assert failure["failure"]["native_save_requested"] is True
    assert failure["failure"]["save_stage"] == "identity_after_save_request_pending"
    assert failure["status"] == "failed" and failure["new_checkpoint_created"] is False
    assert failure["new_restart_performed"] is False
    assert failure["teardown_verified"] is failure["native_load_verified"] is True
    expected_events = [
        {"kind": "continuation", "id": parent["continuation_id"]},
        {"kind": "partial_failure", "id": failure["failure_id"]},
    ]
    offset = data["continuation_events"].index(expected_events[0])
    assert data["continuation_events"][offset:offset + len(expected_events)] == expected_events
    assert parent["operator_observation_warning"]["underlying_cause"] == "unverified"
    assert data["presave_failures"][-1]["checkpoint_cursor"] == 631
    assert data["restarts"][-1]["native_save_loss_restarts"] == 2
    assert data["live_tracking"] is False


@pytest.mark.parametrize(
    "path,value",
    [
        (("status",), "completed"),
        (("parent_record",), "missing"),
        (("snapshot_profile",), "native_menu_preserving_save/v3"),
        (("model",), "other"),
        (("reasoning_effort",), "high"),
        (("last_verified_checkpoint_cursor",), 733),
        (("last_verified_checkpoint_sha256",), "a" * 64),
        (("source_revision",), "bad"),
        (("private_failure_audit_sha256",), "bad"),
        (("independent_failure_audit_passed",), False),
        (("native_load_verified",), False),
        (("teardown_verified",), 1),
        (("new_checkpoint_created",), True),
        (("new_restart_performed",), True),
        (("gameplay_rescue_or_replay_performed",), True),
        (("last_checkpoint_save_files_unchanged_except_event_log",), False),
        (("original_failure_preserved",), False),
        (("failure", "clock_reason"), "model_failed"),
        (("failure", "save_stage"), "identity_before_save"),
        (("failure", "native_save_requested"), False),
        (("failure", "save_remained_pending"), False),
        (("failure", "clean_interruption_with_post_input_boundary"), False),
        (("progress", "checkpointed_elapsed_ticks"), 199291),
        (("progress", "committed_trace_next_step"), 734),
        (("progress", "committed_trace_elapsed_ticks"), 199291),
        (("progress", "new_committed_decisions"), 23),
        (("progress", "new_model_responses"), 22),
        (("progress", "new_committed_ticks"), 6691),
        (("progress", "uncommitted_responses"), 0),
        (("progress", "uncommitted_responses"), True),
        (("progress", "uncommitted_native_ticks"), 0),
        (("progress", "unsaved_new_native_ticks"), 7382),
        (("progress", "accounted_model_responses"), 813),
        (("progress", "inherited_save_loss_restarts"), 3),
        (("progress", "inherited_discarded_native_ticks"), 29891),
        (("usage", "new_tokens"), 0),
        (("usage", "campaign_tokens"), 25370450),
        (("usage", "all_attempt_tokens"), 26113503),
        (("usage", "historical_failed_delivery_tokens"), 0),
        (("usage", "reported_charge_usd"), 0),
        (("usage", "cost_basis"), "free"),
    ],
)
def test_partial_failure_cannot_hide_usage_or_promote_unsaved_ticks(evidence_root, path, value):
    file, source = publication(evidence_root)
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field", SOURCE_DIGESTS)
def test_partial_publication_requires_all_source_digests(evidence_root, field):
    file, source = publication(evidence_root)
    del source["source_evidence_sha256"][field]
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_partial_publication_requires_allowlisting_and_drops_private_fields(
    evidence_root, monkeypatch
):
    file, source = publication(evidence_root)
    before = records.keyboard_campaign_records(evidence_root)
    source["private_prompt"] = source["screen"] = "private-sentinel"
    source["progress"]["dwarf_names"] = source["usage"]["account_id"] = "private-sentinel"
    source["failure"]["model_memory"] = "private-sentinel"
    file.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before
    monkeypatch.setattr(records, "PARTIAL_FAILURES", ())
    monkeypatch.setattr(records, "OOM_FAILURES", ())
    monkeypatch.setattr(records, "RESUMED_WINDOWS", ())
    monkeypatch.setattr(records, "PROMPT_TRIALS", ())
    monkeypatch.setattr(records, "MODAL_TRIALS", ())
    monkeypatch.setattr(records, "SAVED_SEGMENTS", ())
    without = records.keyboard_campaign_records(evidence_root)
    assert without["partial_failures"] == []
    assert without["continuations"] == before["continuations"]
    assert without["continuation_events"] == [event for event in before["continuation_events"]
                                              if event["kind"] not in {"partial_failure", "oom_failure", "resumed", "prompt_trial", "modal_trial", "saved_segment"}]
    assert "private-sentinel" not in json.dumps(without)


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "wrong_parent"])
def test_partial_failure_requires_bounded_file_and_exact_parent(evidence_root, kind):
    file, source = publication(evidence_root)
    parents = records.keyboard_campaign_records(evidence_root)["continuations"]
    if kind == "missing":
        file.unlink()
    elif kind == "symlink":
        target = file.with_suffix(".original")
        file.rename(target)
        file.symlink_to(target)
    elif kind == "oversized":
        source["padding"] = "x" * 65536
        file.write_text(json.dumps(source))
    else:
        parents = [parents[0]]
    with pytest.raises(ValueError):
        partial_failure(evidence_root, records.PARTIAL_FAILURES[0], parents)


def test_partial_failure_renderer_orders_failed_attempt_above_saved_parent():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    data = records.keyboard_campaign_records()
    data["oom_failures"] = []
    data["resumed_windows"] = []
    data["prompt_trials"] = []
    data["modal_trials"] = []
    data["saved_segments"] = []
    data["continuation_events"] = [row for row in data["continuation_events"]
                                   if row["kind"] not in {"oom_failure", "resumed", "prompt_trial", "modal_trial", "saved_segment"}]
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
const data = JSON.parse(process.argv[2]);
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: { getElementById(id) { return elements[id] ||= new Element(); },
              createElement() { return new Element(); } },
  fetch: async () => ({ok: true, json: async () => data})
});
(async () => {
  await new Promise(setImmediate);
  const rendered = elements['keyboard-results'].textContent;
  assert.equal(elements['keyboard-results'].hidden, false);
  assert.ok(rendered.startsWith('Harness interruption · last saved checkpoint 711'));
  const failure = rendered.slice(0, rendered.indexOf('Play continued · checkpoint 711'));
  for (const text of [
    '192,600 ticks', '6,691 ticks', '814', '23 new model responses', '22 committed actions',
    '6,000 ticks', '691 more', 'A save was then requested but remained pending',
    'not a recorded fortress collapse', '26,113,503 campaign tokens', '26,182,507 including',
    '743,053 tokens, all included', 'decision 733', '198,600 elapsed ticks',
    'included in the unsaved total, not added twice', '23,200 lost ticks',
    'No restart has been recorded for this failure yet', 'Unreported · Codex subscription',
    'Game and VM stopped. Recorded evidence, not a live run'
  ]) assert.ok(failure.includes(text), text);
  assert.doesNotMatch(failure, /\$0|before requesting a save|checkpoint 733|checkpoint 734/);
  assert.equal(rendered.split('Harness interruption · last saved checkpoint 711').length - 1, 1);
  assert.ok(rendered.includes('Runner observation warning'));
  assert.ok(rendered.includes('Save failure before restart · checkpoint 631'));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
            json.dumps(data),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
