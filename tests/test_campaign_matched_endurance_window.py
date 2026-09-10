"""Real source lineage plus explicitly synthetic future/pause unit fixtures."""

import copy
import json
import subprocess
import sys

import pytest

from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.matched_result_chain import digest, encoded, totals
from scripts import campaign_matched_endurance_window as module

RECORDS = {
    "astra_r1": "2c8abe1f7135d94ed27aea51e18ebc59e0599205caf3f268f4480b0e377f3d29",
    "sol_r1": "a624a9687257157aa91029d950ca1735a0e8f1baaa224cb66bba7efac50a1dbd",
    "terra_r1": "e81a20836eb6959a529b657a72339bca2e299203c73188006fb32d682c734e11",
    "terra_r2": "1966bf1e8229e8fbfd7a161d84c78da272dd3f5c9aa86040f59a8baa415ef1b8",
}


def source_paths(identity="astra_r1"):
    evidence = module.initial.PROJECT / "experiments/evidence"
    first = evidence / f"keyboard_matched_{identity}_20260910.json"
    child = evidence / f"keyboard_matched_{identity}_continuation_32_64_20260910.json"
    return [(first, module.initial.sha(first)), (child, RECORDS[identity])]


def save(tmp_path, value, name="fixture.json"):
    path = tmp_path / name
    path.write_bytes(encoded(value))
    return path, module.initial.sha(path)


def synthetic_child(parent, window, responses=None):
    """Create unit data, not an experimental result or claimed model execution."""
    value = copy.deepcopy(json.loads(source_paths()[1][0].read_bytes()))
    cursor, tokens = totals(parent)
    limit = window["steps_per_segment"] * window["max_segments"]
    responses = limit if responses is None else responses
    value.update(
        {
            "campaign_id": parent["campaign_id"],
            "start_decision": cursor,
            "next_decision": cursor + responses,
            "response_limit": limit,
            "status": "completed" if responses == limit else "paused",
            "stop_reason": "segment_limit" if responses == limit else "budget_limited_pause",
            "new_responses": responses,
            "new_saved_ticks": responses,
            "saved_elapsed_ticks_before_window": parent["saved_elapsed_ticks"],
            "saved_elapsed_ticks": parent["saved_elapsed_ticks"] + responses,
            "prior_checkpoint_sha256": parent["checkpoint_sha256"],
            "checkpoint_sha256": digest({"synthetic_cursor": cursor + responses}),
            "source_result_sha256": window["source_result_sha256"],
            "initial_metrics": parent["saved_metrics"],
            "saved_metrics": parent["saved_metrics"],
            "new_window_clock_outcomes": {"no_error": responses},
        }
    )
    value["execution"]["window_sha256"] = digest(window)
    value["usage"].update(
        {
            "new_returned_tokens": responses * 100,
            "returned_tokens_before_window": tokens,
            "campaign_returned_tokens": tokens + responses * 100,
            "campaign_accounted_responses": cursor + responses,
        }
    )
    value["new_window_timeline"] = [
        {
            "decision": cursor + i,
            "campaign_elapsed_ticks": parent["saved_elapsed_ticks"] + i,
            "new_elapsed_ticks": i,
            "accepted": True,
            "metrics": parent["saved_metrics"],
        }
        for i in range(1, responses + 1)
    ]
    return value


@pytest.mark.parametrize("identity", RECORDS)
def test_actual_own_save_prepares_64_to_128_without_game_or_budget_change(tmp_path, identity):
    sources = source_paths(identity)
    parent = json.loads(sources[-1][0].read_bytes())
    original_hashes = {p: module.initial.sha(p) for p, _ in sources}
    window = module.prepare(sources)
    path, _ = save(tmp_path, window)
    condition, parsed = load_window(module.initial.PLAN / window["original_condition"], path)
    assert (parsed["continuation_from_next_step"], parsed["window_end_decision"]) == (64, 128)
    assert parsed["comparison_target_decision"] == 128
    assert (parsed["steps_per_segment"], parsed["max_segments"]) == (64, 1)
    assert parsed["source_result_chain_sha256"] == [sha for _, sha in sources]
    assert parsed["continuation_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert parsed["returned_tokens_before_window"] == parent["usage"]["campaign_returned_tokens"]
    assert parsed["saved_elapsed_ticks_before_window"] == parent["saved_elapsed_ticks"]
    assert condition["model"] == parent["model"]
    assert (condition["max_dispatches"], condition["max_total_tokens"]) == (1280, 40000000)
    assert all(parsed[k] is False for k in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert not {"budget_extension", "prompt_change", "restart"} & parsed.keys()
    assert {p: module.initial.sha(p) for p, _ in sources} == original_hashes
    assert list(tmp_path.iterdir()) == [path]
    declared = (
        module.initial.PROJECT
        / "experiments/keyboard_matched_endurance_20260910"
        / f"{identity}-64-128.json"
    )
    assert declared.read_bytes() == encoded(window)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "gpt-5.6-sol"),
        ("replicate", True),
        ("schema_version", "unknown"),
        ("prior_checkpoint_sha256", "a" * 64),
        ("source_result_sha256", "b" * 64),
        ("checkpoint_sha256", "unknown"),
        ("audit_sha256", None),
        ("start_decision", 31),
        ("next_decision", True),
        ("new_responses", 31),
        ("response_limit", 64),
        ("saved_elapsed_ticks_before_window", 0),
        ("saved_elapsed_ticks", 18201),
        ("new_saved_ticks", True),
        ("year_two_reached", True),
        ("source_checkpoint_fresh_load_verified", False),
        ("final_fresh_reload_verified", 0),
        ("checkpoint_verified", False),
        ("memory_preserved_at_start", False),
        ("human_gameplay_rescue", True),
        ("new_native_save_losses", 1),
        ("prompt_change", True),
        ("budget_extension", True),
        ("vm_teardown_verified", False),
        ("status", "failed"),
        ("stop_reason", "infrastructure_failure"),
        ("new_window_timeline", []),
        ("new_window_clock_outcomes", {"no_error": 33}),
    ],
)
def test_changed_or_unsettled_child_is_not_a_continuation(tmp_path, field, value):
    sources = source_paths()
    child = json.loads(sources[1][0].read_bytes())
    child[field] = value
    sources[1] = save(tmp_path, child)
    with pytest.raises(ValueError):
        module.prepare(sources)


@pytest.mark.parametrize(
    "container,key,value",
    [
        ("execution", "source_revision", "0" * 40),
        ("execution", "image_id", "wrong"),
        ("execution", "seed_receipt_sha256", "0" * 64),
        ("execution", "condition_file_sha256", "0" * 64),
        ("execution", "window_sha256", "0" * 64),
        ("execution", "data_disk_gib", True),
        ("execution", "binding_sha256", "0" * 64),
        ("execution", "declaration_revision", "x"),
        ("usage", "returned_tokens_before_window", 0),
        ("usage", "campaign_returned_tokens", 0),
        ("usage", "new_returned_tokens", True),
        ("usage", "campaign_accounted_responses", 63),
        ("usage", "reported_charge_usd", 0),
        ("usage", "cost_basis", "free"),
        ("saved_metrics", "population", True),
    ],
)
def test_receipt_or_usage_mutations_are_rejected(tmp_path, container, key, value):
    sources = source_paths()
    child = json.loads(sources[1][0].read_bytes())
    child[container][key] = value
    sources[1] = save(tmp_path, child)
    with pytest.raises(ValueError):
        module.prepare(sources)


def test_full_future_chain_uses_predeclared_boundaries_not_a_64_decision_cap(tmp_path):
    sources = source_paths()
    parent = json.loads(sources[-1][0].read_bytes())
    for end, segment_count in ((128, 1), (256, 2), (512, 4), (1024, 8), (1280, 4)):
        window = module.prepare(sources)
        assert (window["steps_per_segment"], window["max_segments"]) == (64, segment_count)
        assert window["window_end_decision"] == window["comparison_target_decision"] == end
        parent = synthetic_child(parent, window)
        sources.append(save(tmp_path, parent, f"synthetic-{end}.json"))
    with pytest.raises(ValueError, match="allowance is exhausted"):
        module.prepare(sources)


@pytest.mark.parametrize("responses", [0, 1, 31, 63])
def test_budget_pause_resumes_saved_cursor_without_restarting(tmp_path, responses):
    sources = source_paths()
    parent = json.loads(sources[-1][0].read_bytes())
    window = module.prepare(sources)
    child = synthetic_child(parent, window, responses)
    sources.append(save(tmp_path, child))
    resumed = module.prepare(sources)
    assert resumed["continuation_from_next_step"] == 64 + responses
    assert resumed["continuation_checkpoint_sha256"] == child["checkpoint_sha256"]
    assert resumed["window_end_decision"] == resumed["comparison_target_decision"] == 128
    assert resumed["accounted_responses_before_window"] == 64 + responses


def test_uneven_pause_finishes_a_fragment_then_rejoins_the_comparison_boundary(tmp_path):
    sources = source_paths()
    parent = synthetic_child(json.loads(sources[-1][0].read_bytes()), module.prepare(sources))
    sources.append(save(tmp_path, parent, "synthetic-128.json"))
    paused = synthetic_child(parent, module.prepare(sources), 31)
    sources.append(save(tmp_path, paused, "synthetic-159.json"))
    fragment = module.prepare(sources)
    assert fragment["continuation_from_next_step"] == 159
    assert fragment["comparison_target_decision"] == 256
    assert (
        fragment["steps_per_segment"],
        fragment["max_segments"],
        fragment["window_end_decision"],
    ) == (33, 1, 192)
    sources.append(save(tmp_path, synthetic_child(paused, fragment), "synthetic-192.json"))
    assert module.prepare(sources)["window_end_decision"] == 256


def test_complete_lineage_and_exact_file_bytes_are_required(tmp_path):
    sources = source_paths()
    for broken in (
        sources[:1],
        sources[::-1],
        [sources[0], source_paths("sol_r1")[1]],
        sources + sources[1:],
        [sources[0], (sources[1][0], "0" * 64)],
    ):
        with pytest.raises(ValueError):
            module.prepare(broken)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("response_count", [2, 6, 10, 22, 38, 62])
def test_pause_does_not_move_other_trials_standard_save_boundaries(tmp_path, response_count):
    sources = source_paths()
    parent = synthetic_child(json.loads(sources[-1][0].read_bytes()), module.prepare(sources))
    sources.append(save(tmp_path, parent, "synthetic-128.json"))
    child = synthetic_child(parent, module.prepare(sources), response_count)
    sources.append(save(tmp_path, child, "synthetic-paused.json"))
    window = module.prepare(sources)
    assert window["steps_per_segment"] == 64 - response_count
    assert window["max_segments"] == 1
    assert window["window_end_decision"] == 192
    assert window["comparison_target_decision"] == 256


@pytest.mark.parametrize("key", ["execution", "usage"])
def test_missing_structured_proof_fails_with_actionable_error(tmp_path, key):
    sources = source_paths()
    child = json.loads(sources[1][0].read_bytes())
    child[key] = None
    sources[1] = save(tmp_path, child)
    with pytest.raises(ValueError, match="must be explicit"):
        module.prepare(sources)


def test_token_ceiling_cannot_be_extended_by_a_followup_window(tmp_path):
    sources = source_paths()
    parent = json.loads(sources[-1][0].read_bytes())
    child = synthetic_child(parent, module.prepare(sources))
    child["usage"]["new_returned_tokens"] = 40000000 - totals(parent)[1]
    child["usage"]["campaign_returned_tokens"] = 40000000
    sources.append(save(tmp_path, child))
    with pytest.raises(ValueError, match="allowance is exhausted"):
        module.prepare(sources)


def test_cli_emits_only_reproducible_configuration():
    sources = source_paths()
    command = [sys.executable, "-m", "scripts.campaign_matched_endurance_window"]
    for path, sha in sources:
        command.extend(["--result", str(path), sha])
    result = subprocess.run(command, capture_output=True, check=True)
    assert result.stdout == encoded(module.prepare(sources))
    assert not result.stderr
