"""OOM publication preserves saved progress, unknown tails and observer effects."""

import json
import shutil
import subprocess

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_oom import DIGESTS, SOURCE_DIGESTS, oom_failure
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.OOM_FAILURES[0]
    return path, json.loads(path.read_text())


def test_oom_result_keeps_save_usage_unknown_tail_and_three_losses():
    data = records.keyboard_campaign_records()
    row, parent = data["oom_failures"][-1], data["partial_failures"][-1]
    assert row["parent_record"] == parent["failure_id"]
    assert row["checkpoint_cursor"] == parent["checkpoint_cursor"] == 711
    assert row["progress"]["checkpointed_elapsed_ticks"] == 192600
    assert row["progress"]["committed_trace_cursor"] == 738
    assert row["progress"]["new_committed_decisions"] == 27
    assert row["progress"]["new_model_responses"] == 28
    assert row["progress"]["new_committed_unsaved_ticks"] == 5200
    assert row["progress"]["uncommitted_elapsed_ticks"] is None
    assert row["progress"]["existing_loss_records"] == 3
    assert row["progress"]["existing_lost_ticks"] == 29891
    assert row["progress"]["accounted_responses"] == 842
    assert row["usage"]["campaign_tokens"] == 26990171
    assert row["usage"]["all_attempt_tokens"] == 27059175
    assert row["usage"]["reported_charge_usd"] is None
    assert row["new_checkpoint_created"] is row["another_restart_performed"] is False
    assert row["possible_observer_contribution"] is True
    assert row["teardown_verified"] is True
    assert data["continuation_events"][-5:-3] == [
        {"kind": "partial_failure", "id": parent["failure_id"]},
        {"kind": "oom_failure", "id": row["failure_id"]},
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_record", "../private.json"),
        ("source_revision", "invalid"),
        ("classification", "model_failure"),
        ("model", "other"),
        ("reasoning_effort", "high"),
        ("screen_size", [80, 25]),
        ("oom_victim", "game"),
        ("exact_oom_cause", "model"),
        ("independent_failure_audit_passed", False),
        ("native_load_verified", False),
        ("teardown_verified", 1),
        ("last_checkpoint_cursor", 738),
        ("last_checkpoint_sha256", "a" * 64),
        ("checkpointed_elapsed_ticks", 197800),
        ("committed_trace_cursor", 739),
        ("new_committed_decisions", True),
        ("new_model_responses", 27),
        ("uncommitted_model_responses", 0),
        ("uncommitted_native_keys_confirmed", 0),
        ("uncommitted_elapsed_ticks", 0),
        ("uncommitted_clock_receipt_available", True),
        ("final_calendar_observation_available", True),
        ("accounted_responses", 814),
        ("existing_loss_records", 2),
        ("existing_lost_ticks", 23200),
        ("new_committed_unsaved_ticks", -1),
        ("latest_attested_paused_tick", 403200),
        ("last_population", -1),
        ("last_recorded_dead", True),
        ("new_tokens", 0),
        ("campaign_tokens", 26113503),
        ("all_attempt_tokens", 26990171),
        ("historical_failed_delivery_tokens", 0),
        ("reported_charge_usd", 0),
        ("every_subscription_event_receipt_redecoded", False),
        ("new_checkpoint_verified", True),
        ("another_restart_performed", True),
        ("clock_fix_native_acceptance", True),
        ("gameplay_collapse_proven", True),
        ("native_save_world_sav_matches_parent", False),
        ("save_inventory_changed_paths", ["world.sav"]),
    ],
)
def test_invalid_oom_record_fails(evidence_root, field, value):
    path, source = publication(evidence_root)
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field", DIGESTS)
def test_required_audit_digests(evidence_root, field):
    path, source = publication(evidence_root)
    source[field] = "invalid"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field", SOURCE_DIGESTS)
def test_required_native_digests(evidence_root, field):
    path, source = publication(evidence_root)
    del source["source_sha256"][field]
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_extra_private_fields_and_unlisted_records_are_not_exposed(evidence_root, monkeypatch):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source["private_memory"] = source["source_sha256"]["private_screen"] = "secret-sentinel"
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before
    monkeypatch.setattr(records, "OOM_FAILURES", ())
    monkeypatch.setattr(records, "RESUMED_WINDOWS", ())
    monkeypatch.setattr(records, "PROMPT_TRIALS", ())
    monkeypatch.setattr(records, "MODAL_TRIALS", ())
    without = records.keyboard_campaign_records(evidence_root)
    assert without["oom_failures"] == []
    assert without["continuation_events"] == [event for event in before["continuation_events"]
                                              if event["kind"] not in {"oom_failure", "resumed", "prompt_trial", "modal_trial"}]
    assert without["partial_failures"] == before["partial_failures"]


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "wrong_parent"])
def test_bounded_file_and_parent_are_required(evidence_root, kind):
    parents = records.keyboard_campaign_records(evidence_root)["partial_failures"]
    path, source = publication(evidence_root)
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        target = path.with_suffix(".original")
        path.rename(target)
        path.symlink_to(target)
    elif kind == "oversized":
        source["padding"] = "x" * 65536
        path.write_text(json.dumps(source))
    else:
        parents = []
    with pytest.raises(ValueError):
        oom_failure(evidence_root, records.OOM_FAILURES[0], parents)


def test_oom_renderer_is_newest_and_does_not_hide_prior_failure():
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
  assert.ok(rendered.startsWith('Dialog handling worked · host interruption prevented a save'));
  const latest = rendered.slice(rendered.indexOf('Play resumed after restart'), rendered.indexOf('Memory-related interruption'));
  for (const text of ['198,600 retained ticks', '64 new model decisions, 6,000 new ticks',
    '906 accounted model responses', '4 loss records', 'at least 35,091 ticks',
    'Total discarded time is Unknown', '28,911,047 campaign tokens', '28,980,051 including',
    '1,920,876 tokens', '3 decisions advanced game time; 61 did not advance it',
    '56 at window start', 'Unknown at window end', '63 complete readings', '2 unknown readings',
    'returned exit 1', 'separate fresh-process reload', 'not a running campaign']) {
    assert.ok(latest.includes(text), text);
  }
  assert.doesNotMatch(latest, /\$0|lost 0 ticks|year.two success/i);
  const current = rendered.slice(rendered.indexOf('Memory-related interruption'), rendered.indexOf('Harness interruption'));
  for (const text of ['192,600 ticks', '5,200 ticks', 'Final uncommitted game time Unknown',
    '842', '28 new responses', '27 committed actions', '5 confirmed keys', 'No new save',
    'may have contributed', 'cause and affected process are unverified',
    'not a clean model-performance result', '12 living dwarves', '0 recorded deaths',
    '26,990,171 campaign tokens', '27,059,175 including', '876,668 tokens, all included',
    '3 earlier loss records totaling 29,891 ticks', 'unknown, not zero',
    'Unreported · Codex subscription', 'Game and VM stopped'
  ]) assert.ok(current.includes(text), text);
  assert.doesNotMatch(current, /\$0|checkpoint 738|checkpoint 739/);
  assert.ok(rendered.includes('This loss was retained by the following restarted attempt'));
  assert.ok(rendered.includes('A save was then requested but remained pending'));
  assert.ok(rendered.includes('Runner observation warning'));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
            json.dumps(records.keyboard_campaign_records()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
