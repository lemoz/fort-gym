"""Projection and lineage tests for failed attempts and non-gameplay save fixes."""
import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root  # noqa: F401


def publication(root, name):
    path = root / "experiments/evidence" / name
    return path, json.loads(path.read_text())


def test_failed_attempt_does_not_advance_checkpoint_and_diagnostic_does_not_clear_failure():
    data = records.keyboard_campaign_records()
    failure, fix = data["presave_failures"][-1], data["save_acceptances"][-1]
    parent = next(row for row in data["continuations"] if row["continuation_id"] == failure["parent_record"])
    assert parent["checkpoint_cursor"] == failure["checkpoint_cursor"] == 631
    assert failure["progress"]["observed_trace_next_step"] == 695
    assert failure["progress"]["checkpointed_elapsed_ticks"] == 143400
    assert failure["progress"]["unsaved_new_native_ticks"] == 21200
    assert failure["progress"]["accounted_model_responses"] == 711
    assert failure["usage"]["campaign_tokens"] == 22819077
    assert failure["usage"]["reported_charge_usd"] is None
    assert failure["status"] == "failed" and failure["new_checkpoint_created"] is False
    assert fix["original_failure"] == failure["failure_id"]
    assert fix["save_verified"] is fix["fresh_reload_verified"] is True
    assert fix["gameplay_ticks"] == fix["model_calls"] == 0
    assert fix["new_campaign_checkpoint_created"] is False
    offset = data["continuation_events"].index({"kind": "presave_failure", "id": failure["failure_id"]})
    assert data["continuation_events"][offset + 1]["kind"] == "restart"


@pytest.mark.parametrize("path,value", [
    (("status",), "completed"),
    (("new_checkpoint_created",), True),
    (("new_restart_performed",), True),
    (("last_verified_checkpoint_cursor",), 695),
    (("last_verified_checkpoint_sha256",), "a" * 64),
    (("private_failure_audit_sha256",), "bad"),
    (("original_failure_preserved",), False),
    (("teardown_verified",), 1),
    (("failure", "native_save_requested"), True),
    (("failure", "underlying_stack_cause"), "confirmed"),
    (("progress", "accounted_model_responses"), 647),
    (("progress", "observed_trace_next_step"), 631),
    (("progress", "checkpointed_elapsed_ticks"), 164600),
    (("progress", "unsaved_new_native_ticks"), 0),
    (("progress", "new_model_calls"), True),
    (("progress", "new_rejected_decisions"), 1),
    (("usage", "new_tokens"), 0),
    (("usage", "campaign_tokens"), 20850223),
    (("usage", "all_attempt_tokens"), 20919227),
    (("usage", "reported_charge_usd"), 0),
    (("observed_unsaved_outcomes", "food_unknown_measurements"), 0),
    (("observed_unsaved_outcomes", "food_final_observation_is_saved"), True),
    (("observed_unsaved_outcomes", "counts", "food_stock", "end"), None),
])
def test_failed_attempt_cannot_hide_usage_or_claim_saved_progress(evidence_root, path, value):  # noqa: F811
    file, source = publication(evidence_root, records.PRESAVE_FAILURES[0])
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("path,value", [
    (("status",), "completed_campaign"),
    (("independent_audit_passed",), False),
    (("independent_audit_sha256",), "bad"),
    (("parent_checkpoint", "cursor"), 695),
    (("parent_failure_record",), "unknown"),
    (("acceptance", "fresh_reload_verified"), False),
    (("acceptance", "full_stack_identity_unchanged"), False),
    (("acceptance", "gameplay_ticks"), 1),
    (("acceptance", "model_calls"), False),
    (("acceptance", "teardown_verified"), False),
    (("campaign", "new_checkpoint_created"), True),
    (("campaign", "new_restart_performed"), True),
    (("campaign", "accounted_model_responses"), 647),
    (("campaign", "retained_elapsed_ticks"), 164600),
    (("campaign", "unsaved_window_o_ticks"), 0),
    (("cost", "other_cost_usd"), 0),
])
def test_save_diagnostic_cannot_become_gameplay_success(evidence_root, path, value):  # noqa: F811
    file, source = publication(evidence_root, records.SAVE_ACCEPTANCES[0])
    target = source
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    file.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_new_publication_private_fields_are_not_projected(evidence_root):  # noqa: F811
    for name in (*records.PRESAVE_FAILURES, *records.SAVE_ACCEPTANCES):
        file, source = publication(evidence_root, name)
        source["raw_screen"] = "private-marker"
        source["source_path"] = "/private-marker/file"
        file.write_text(json.dumps(source))
    file, source = publication(evidence_root, records.PRESAVE_FAILURES[0])
    source["usage"]["account"] = "private-marker"
    source["observed_unsaved_outcomes"]["counts"]["food_stock"]["raw"] = "private-marker"
    file.write_text(json.dumps(source))
    assert "private-marker" not in json.dumps(records.keyboard_campaign_records(evidence_root))
