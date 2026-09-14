"""Native receipt validation and at-most-once dispatch of a selected job batch."""

from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.env import campaign_workshop_jobs as module
from fort_gym.bench.env.workshop_job_profile import RECEIPT_SCHEMA


def native():
    point = dict(dfroot="/isolated", year=30, year_tick=123, paused=True, save_name="fixture")
    return {
        "schema_version": RECEIPT_SCHEMA, "ok": True, "command_mutation": "completed",
        "item": "bed", "quantity": 2, "jobs_queued": 2, "created_job_ids": [100, 101],
        "workshop_id": 7, "queue_before": 0, "queue_after": 2,
        "before": point, "after": deepcopy(point),
    }


def execute(monkeypatch, receipt, params=None):
    calls = []
    monkeypatch.setattr(module, "read_binding_index", lambda root: None)
    monkeypatch.setattr(module, "execute_campaign_keys", lambda keys, **kw: {
        "accepted": True, "result": {"native_receipts": [{"after": {"save_name": "fixture"}}]},
    })

    def dispatch(*args, **kw):
        calls.append(args)
        if isinstance(receipt, Exception):
            raise receipt
        return receipt

    monkeypatch.setattr(module, "run_lua_file", dispatch)
    result = module.execute_workshop_job(
        params if params is not None else {"item": "bed", "quantity": 2},
        expected_dfroot=Path("/isolated"), year=30, year_tick=123,
    )
    return result, calls


def test_confirmed_queue_attests_exact_target_and_does_not_send_keys(monkeypatch):
    result, calls = execute(monkeypatch, native())
    assert result["accepted"] and result["result"]["jobs_queued"] == 2
    assert result["result"]["action_route"] == "selected_workshop_job"
    assert result["result"]["keys_confirmed"] == 0
    assert len(calls) == 1 and calls[0][1:] == ("/isolated", "30", "123", "fixture", "bed", "2")


@pytest.mark.parametrize("change", [
    {"ok": 1}, {"quantity": True}, {"jobs_queued": True},
    {"created_job_ids": [100, 100]}, {"created_job_ids": [100]},
    {"queue_after": 3}, {"queue_before": 9, "queue_after": 11},
    {"command_mutation": "not_attempted"}, {"item": "brew"},
    {"before": {**native()["before"], "year_tick": 124}},
    {"after": {**native()["after"], "save_name": "other"}},
])
def test_inconsistent_native_success_is_unknown_and_never_retried(monkeypatch, change):
    result, calls = execute(monkeypatch, {**native(), **change})
    assert not result["accepted"] and result["result"]["command_mutation"] == "unknown"
    assert result["result"]["jobs_queued"] is None and len(calls) == 1


@pytest.mark.parametrize("phase", ["not_attempted", "attempted"])
def test_rejected_or_partial_outcome_has_distinct_mutation_status(monkeypatch, phase):
    receipt = {
        "schema_version": RECEIPT_SCHEMA, "ok": False, "command_mutation": phase,
        "jobs_queued": 0 if phase == "not_attempted" else 1,
        "created_job_ids": [] if phase == "not_attempted" else [100], "error": "failure",
    }
    result, calls = execute(monkeypatch, receipt)
    assert not result["accepted"] and len(calls) == 1
    assert result["result"]["command_mutation"] == ("not_attempted" if phase == "not_attempted" else "unknown")


def test_transport_loss_never_replays_the_job(monkeypatch):
    result, calls = execute(monkeypatch, OSError("receipt lost"))
    assert not result["accepted"] and len(calls) == 1
    assert result["result"]["command_mutation"] == "unknown"


def test_malformed_request_has_no_native_dispatch(monkeypatch):
    result, calls = execute(monkeypatch, native(), {"item": "bed", "quantity": True})
    assert not result["accepted"] and not calls
    assert result["result"]["command_mutation"] == "not_attempted"
