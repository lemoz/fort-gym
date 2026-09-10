"""Synthetic temporary evidence only; these are not recorded campaign results."""

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.keyboard_live import SCHEMA, project_status
from fort_gym.bench.run.campaign_checkpoint import _json_bytes
from scripts.campaign_keyboard_boundaries import (
    EVIDENCE,
    PENDING,
    file_sha,
    latest_boundary,
)
from scripts.campaign_keyboard_observe import snapshot


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def evidence(tmp_path):
    base = {
        "schema_version": SCHEMA,
        "run_id": "fixture",
        "source_revision": "a" * 40,
        "model": "fixture-model",
        "reasoning_effort": "medium",
        "saved_checkpoint_cursor": 775,
        "saved_elapsed_ticks": 198600,
        "campaign_responses": 10,
        "campaign_tokens": 100,
        "historical_failed_delivery_tokens": 7,
        "window_response_limit": 8,
        "steps_per_segment": 2,
        "max_segments": 4,
        "initial_checkpoint_sha256": "b" * 64,
    }
    for index, ticks in enumerate((999, 10, 20, 30)):
        folder = tmp_path / f"attempt/model/request{index}"
        folder.mkdir(parents=True)
        request = {
            "request_id": folder.name,
            "memory": "saved memory",
            "feedback": {"simulation": {"ticks_advanced": ticks}},
        }
        write(folder / "request.json", request)
        write(
            folder / "response.json",
            {
                "request_sha256": digest(request),
                "result": {
                    "transport_receipt": {
                        "dispatched": True,
                        "total_tokens": 15,
                        "reported_charge_usd": None,
                    }
                },
            },
        )
        write(
            folder / "summary.json",
            {
                "decision_index": index,
                "request_id": folder.name,
                "model_dispatched": True,
                "total_tokens": 15,
                "reported_charge_usd": None,
            },
        )
    directory = tmp_path / "segment-boundary-0-evidence"
    directory.mkdir()
    for name in EVIDENCE:
        write(directory / name, {"private": "not for publication"})
    usage = {"accounted_responses": 12, "total_tokens": 130}
    agent = {"usage": usage, "memory": "saved memory"}
    for name in ("saved-agent.json", "second-agent.json"):
        write(directory / name, agent)
    payload = {
        "next_step": 777,
        "parent_sha256": "b" * 64,
        "agent_sha256": file_sha(directory / "saved-agent.json"),
    }
    checkpoint_sha = hashlib.sha256(_json_bytes(payload)).hexdigest()
    write(directory / "checkpoint.json", {"payload": payload, "sha256": checkpoint_sha})
    write(
        directory / "first-result.json",
        {
            "source_revision": "a" * 40,
            "committed_elapsed_ticks": 198630,
            "usage": usage,
        },
    )
    report = {
        "schema_version": "fortgym.private-native-segment-boundary/v1",
        "passed": True,
        "segment_index": 0,
        "source_revision": "a" * 40,
        "first_checkpoint_cursor": 777,
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_file_sha256": file_sha(directory / "checkpoint.json"),
        "first_segment_saved_elapsed_ticks": 198630,
        "first_segment_usage": usage,
        "first_runtime_cleanup_verified": True,
        "second_worker_state_and_memory_match_save": True,
        "second_worker_first_request_sha256": file_sha(
            tmp_path / "attempt/model/request2/request.json"
        ),
        "source_sha256": {name: file_sha(directory / name) for name in EVIDENCE},
        **{key: False for key in PENDING},
    }
    path = tmp_path / "segment-boundary-0-review.json"
    write(path, report)
    return tmp_path, base, path, report


def test_snapshot_uses_boundary_without_resetting_usage_or_double_counting_ticks(
    evidence,
):
    root, base, _, _ = evidence
    value = snapshot(root, base, alive=True, now=1000)
    assert value["saved_checkpoint_cursor"] == 775
    assert value["new_responses"] == 4 and value["campaign_responses"] == 14
    assert value["new_tokens"] == 60 and value["all_attempt_tokens"] == 167
    assert value["unsaved_ticks_lower_bound"] == 60
    assert value["latest_verified_save"]["checkpoint_cursor"] == 777
    # Request 2 contains the feedback for the last step included in the save.
    assert value["ticks_since_verified_save_lower_bound"] == 30
    public = project_status(value, now=1000)
    assert public["new_save_verified"] is False
    assert (
        public["latest_verified_save"]["full_inventory_and_trace_audit_complete"]
        is False
    )
    assert "saved memory" not in json.dumps(public)
    assert "not for publication" not in json.dumps(public)
    assert "initial_checkpoint_sha256" not in public


@pytest.mark.parametrize(
    "feedback,expected", [(None, None), ({"simulation": {"ticks_advanced": 0}}, 0)]
)
def test_post_save_unknown_is_not_zero(evidence, feedback, expected):
    root, base, _, _ = evidence
    path = root / "attempt/model/request3/request.json"
    request = json.loads(path.read_text())
    request["feedback"] = feedback
    write(path, request)
    response = json.loads(path.with_name("response.json").read_text())
    response["request_sha256"] = digest(request)
    write(path.with_name("response.json"), response)
    assert (
        snapshot(root, base, alive=True, now=1000)[
            "ticks_since_verified_save_lower_bound"
        ]
        == expected
    )


@pytest.mark.parametrize(
    "key,changed",
    [
        ("source_revision", "c" * 40),
        ("passed", False),
        ("segment_index", True),
        ("first_runtime_cleanup_verified", False),
        ("second_worker_state_and_memory_match_save", 1),
        ("first_checkpoint_cursor", 999),
        ("checkpoint_sha256", "d" * 64),
        ("first_segment_saved_elapsed_ticks", 1),
        ("second_worker_first_request_sha256", "d" * 64),
        *[(key, True) for key in PENDING],
    ],
)
def test_mismatching_or_overclaiming_report_rejected(evidence, key, changed):
    root, base, path, report = evidence
    report[key] = changed
    write(path, report)
    with pytest.raises(ValueError):
        snapshot(root, base, alive=True, now=1000)


def test_changed_evidence_and_missing_parent_rejected(evidence):
    root, base, path, report = evidence
    path.rename(root / "segment-boundary-1-review.json")
    with pytest.raises(ValueError, match="consecutive"):
        snapshot(root, base, alive=True, now=1000)
    write(path, report)
    (root / "segment-boundary-1-review.json").unlink()
    write(root / "segment-boundary-0-evidence/second-before.json", {})
    with pytest.raises(ValueError, match="evidence changed"):
        snapshot(root, base, alive=True, now=1000)


@pytest.mark.parametrize(
    "key,changed",
    [
        ("checkpoint_cursor", 778),
        ("elapsed_ticks", 1),
        ("window_responses", 4),
        ("window_responses", True),
        ("campaign_tokens", 999),
        ("report_sha256", "private/path"),
        ("evidence_basis", "complete"),
        ("full_inventory_and_trace_audit_complete", True),
    ],
)
def test_public_and_browser_boundaries_reject_invalid_claims(evidence, key, changed):
    root, base, _, _ = evidence
    value = snapshot(root, base, alive=True, now=1000)
    public = project_status(value, now=1000)
    value["latest_verified_save"][key] = changed
    with pytest.raises(ValueError):
        project_status(value, now=1000)
    public["latest_verified_save"][key] = changed
    script = (
        Path(__file__).resolve().parents[1] / "web/static/campaign-keyboard-live.js"
    )
    program = "const {state}=require(process.argv[1]); require('node:assert/strict').throws(()=>state(JSON.parse(process.argv[2]),1000));"
    subprocess.run(["node", "-e", program, str(script), json.dumps(public)], check=True)


@pytest.mark.parametrize("ticks", [True, -1, 61, "missing"])
def test_post_save_count_cannot_exceed_all_reported_time(evidence, ticks):
    root, base, _, _ = evidence
    value = snapshot(root, base, alive=True, now=1000)
    value["ticks_since_verified_save_lower_bound"] = ticks
    with pytest.raises(ValueError):
        project_status(value, now=1000)


def test_new_report_waits_for_snapshot_receipt_prefix(evidence):
    root, base, _, _ = evidence
    assert latest_boundary(root, base, []) is None


def test_later_boundary_replaces_only_save_baseline_not_window_usage(evidence):
    root, base, _, first = evidence
    for index in (4, 5):
        folder = root / f"attempt/model/request{index}"
        folder.mkdir()
        request = {
            "request_id": folder.name,
            "memory": "next memory",
            "feedback": {"simulation": {"ticks_advanced": 40 if index == 4 else 50}},
        }
        write(folder / "request.json", request)
        write(
            folder / "response.json",
            {
                "request_sha256": digest(request),
                "result": {
                    "transport_receipt": {
                        "dispatched": True,
                        "total_tokens": 15,
                        "reported_charge_usd": None,
                    },
                },
            },
        )
        write(
            folder / "summary.json",
            {
                "decision_index": index,
                "request_id": folder.name,
                "model_dispatched": True,
                "total_tokens": 15,
                "reported_charge_usd": None,
            },
        )
    directory = root / "segment-boundary-1-evidence"
    directory.mkdir()
    for name in EVIDENCE:
        write(
            directory / name,
            json.loads((root / "segment-boundary-0-evidence" / name).read_text()),
        )
    usage = {"accounted_responses": 14, "total_tokens": 160}
    for name in ("saved-agent.json", "second-agent.json"):
        write(directory / name, {"memory": "next memory", "usage": usage})
    payload = {
        "next_step": 779,
        "parent_sha256": first["checkpoint_sha256"],
        "agent_sha256": file_sha(directory / "saved-agent.json"),
    }
    sha = hashlib.sha256(_json_bytes(payload)).hexdigest()
    write(directory / "checkpoint.json", {"payload": payload, "sha256": sha})
    write(
        directory / "first-result.json",
        {
            "source_revision": base["source_revision"],
            "usage": usage,
            "committed_elapsed_ticks": 198700,
        },
    )
    write(
        root / "segment-boundary-1-review.json",
        {
            **first,
            "segment_index": 1,
            "first_checkpoint_cursor": 779,
            "checkpoint_sha256": sha,
            "checkpoint_file_sha256": file_sha(directory / "checkpoint.json"),
            "first_segment_saved_elapsed_ticks": 198700,
            "first_segment_usage": usage,
            "second_worker_first_request_sha256": file_sha(
                root / "attempt/model/request4/request.json"
            ),
            "source_sha256": {name: file_sha(directory / name) for name in EVIDENCE},
        },
    )
    public = project_status(snapshot(root, base, alive=True, now=1000), now=1000)
    assert public["saved_checkpoint_cursor"] == 775
    assert public["latest_verified_save"]["checkpoint_cursor"] == 779
    assert public["ticks_since_verified_save_lower_bound"] == 50
    assert public["unsaved_ticks_lower_bound"] == 150
    assert public["new_responses"] == 6 and public["new_tokens"] == 90
    assert public["all_attempt_tokens"] == 197


def test_boundary_renderer_explains_saved_start_reload_and_pending_audit(evidence):
    root, base, _, _ = evidence
    value = project_status(snapshot(root, base, alive=True, now=1000), now=1000)
    script = (
        Path(__file__).resolve().parents[1] / "web/static/campaign-keyboard-live.js"
    )
    program = r"""
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
  document: {hidden: false, addEventListener() {},
    getElementById: id => elements[id] ||= new Element(), createElement: () => new Element()},
  fetch: async () => ({ok: true, json: async () => JSON.parse(process.argv[2])}),
  setTimeout, clearTimeout, setInterval: () => 0, AbortController
});
(async () => {
  await new Promise(setImmediate);
  const text = elements['keyboard-live-content'].textContent;
  assert.match(text, /started from checkpoint 775/);
  assert.match(text, /reload are verified through checkpoint 777/);
  assert.match(text, /198,630 ticks/);
  assert.match(text, /Time reported since that save\s+At least 30 ticks/);
  assert.match(text, /full save-file and gameplay-trace audit is still pending/);
  assert.match(text, /Charges are unreported, not zero/);
  assert.doesNotMatch(text, /Unsaved time observed|saved memory|not for publication/);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    subprocess.run(["node", "-e", program, str(script), json.dumps(value)], check=True)
