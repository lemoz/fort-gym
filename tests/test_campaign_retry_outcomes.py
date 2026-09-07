"""Synthetic retry reporting, never a native-control or model-success verdict."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.eval.campaign_profile import COMMAND_RETRY_SCHEMA, command_retry_outcomes
from fort_gym.bench.eval.campaign_public import public_snapshot
from fort_gym.bench.run.campaign_feed import read_feed
from tests.test_campaign_feed import feed
from tests.test_campaign_profile import profile, row


def commands(*choices):
    rows = []
    for step, (kind, accepted, params) in enumerate(choices):
        item = row(step, step * 100, (step + 1) * 100, kind=kind, accepted=accepted)
        item["action"]["params"] = deepcopy(params)
        rows.append(item)
    return rows


def outcomes(accepted=0, rejected=0, unknown=0):
    return {
        "schema_version": COMMAND_RETRY_SCHEMA,
        "accepted": accepted,
        "rejected": rejected,
        "unknown": unknown,
    }


def test_retries_survive_wait_and_view_without_implying_recovery():
    params = {"kind": "dig", "area": [3, 8, 1], "size": [3, 3, 1]}
    rows = commands(
        ("DIG", False, params),
        ("WAIT", True, {}),
        ("DIG", False, params),
        ("VIEW", True, {"origin": [3, 8, 1]}),
        ("DIG", True, params),
    )
    original = deepcopy(rows)
    result = profile(rows)
    assert result["actions"]["command_retry_outcomes"] == outcomes(accepted=1, rejected=1)
    assert result["actions"]["changed_command_after_rejection"] == 2
    assert result["functioning_fortress"] == "not_assessed"
    assert result["metrics"]["completed_workshops"]["change"] == 0
    assert rows == original


def test_parameter_order_notes_and_wait_duration_do_not_create_a_new_command():
    rows = commands(
        ("BUILD", False, {"x": 3, "kind": "Bed"}), ("BUILD", False, {"kind": "Bed", "x": 3})
    )
    rows[0]["action"].update(advance_ticks=0, intent="first")
    rows[1]["action"].update(advance_ticks=2500, intent="second")
    assert command_retry_outcomes(rows) == outcomes(rejected=1)
    rows[1]["action"]["params"]["x"] = 4
    assert command_retry_outcomes(rows) == outcomes()
    rows[1]["action"] = {"type": "ORDER", "params": rows[0]["action"]["params"]}
    assert command_retry_outcomes(rows) == outcomes()


@pytest.mark.parametrize("end", [True, None, "true", 1])
def test_accepted_or_unknown_outcome_clears_that_command_sequence(end):
    rows = commands(("BUILD", False, {}), ("BUILD", end, {}), ("BUILD", True, {}))
    expected = outcomes(accepted=1) if end is True else outcomes(unknown=1)
    assert command_retry_outcomes(rows) == expected


def test_new_rejection_after_acceptance_starts_a_new_sequence():
    rows = commands(
        ("BUILD", False, {}), ("BUILD", True, {}), ("BUILD", False, {}), ("BUILD", False, {})
    )
    assert command_retry_outcomes(rows) == outcomes(accepted=1, rejected=1)


@pytest.mark.parametrize("steps", [[3], [0, 0], [0, 2], [True]])
def test_missing_origin_gaps_duplicates_or_boolean_steps_are_unknown(steps):
    rows = [row(step=step, accepted=False, kind="BUILD") for step in steps]
    assert command_retry_outcomes(rows) is None


@pytest.mark.parametrize(
    "action",
    [
        {"type": "FUTURE", "params": {}},
        {"type": "DIG", "params": []},
        {"type": "DIG", "params": {"x": float("nan")}},
    ],
)
def test_unrecognized_or_unmatchable_command_does_not_invent_zero(action):
    item = row()
    item["action"] = action
    assert command_retry_outcomes([item]) is None


def test_empty_observed_trace_has_no_observed_retries():
    assert command_retry_outcomes([]) == outcomes()


def snapshot(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    record = read_feed(publisher.root)["campaigns"][0]
    record["actions"] = {
        "committed_rows": 5,
        "accepted": 2,
        "rejected": 2,
        "unknown": 1,
        "command_retry_outcomes": outcomes(accepted=1, rejected=1),
    }
    return record


def test_public_projection_is_count_only_and_idempotent(tmp_path):
    record = snapshot(tmp_path)
    record["actions"]["command_retry_outcomes"]["params"] = "PRIVATE-COMMAND-CONTENT"
    result = public_snapshot(record)
    assert result["actions"]["command_retry_outcomes"] == outcomes(accepted=1, rejected=1)
    assert "PRIVATE-COMMAND-CONTENT" not in json.dumps(result)
    assert public_snapshot(result) == result


@pytest.mark.parametrize("bad", [None, True, False, -1, "1", 0.5, 3])
def test_missing_malformed_or_impossible_retry_counts_remain_unknown(tmp_path, bad):
    record = snapshot(tmp_path)
    record["actions"]["command_retry_outcomes"]["accepted"] = bad
    assert public_snapshot(record)["actions"]["command_retry_outcomes"] is None


def test_old_aggregate_and_unknown_schema_are_not_reconstructed(tmp_path):
    record = snapshot(tmp_path)
    record["actions"]["command_retry_outcomes"]["schema_version"] = "future/v2"
    assert public_snapshot(record)["actions"]["command_retry_outcomes"] is None
    del record["actions"]["command_retry_outcomes"]
    assert "command_retry_outcomes" not in public_snapshot(record)["actions"]


@pytest.mark.parametrize("committed", [None, True, -1, 1])
def test_retry_totals_require_a_consistent_committed_row_bound(tmp_path, committed):
    record = snapshot(tmp_path)
    record["actions"]["committed_rows"] = committed
    assert public_snapshot(record)["actions"]["command_retry_outcomes"] is None
