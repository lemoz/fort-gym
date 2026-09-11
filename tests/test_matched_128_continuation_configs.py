"""Actual audited decision-128 parents; no future gameplay is synthesized."""

import json
from pathlib import Path

import pytest

from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.matched_result_chain import encoded
from scripts.campaign_matched_endurance_window import prepare
from scripts.campaign_matched_window import sha

ROOT = Path(__file__).resolve().parents[1]
PARENTS = {
    "astra_r1": "cb9cc0c5af8f158848493b1e7b3bb79f4f4736f185fbf7ce96fb157095e1d145",
    "sol_r1": "a155f9c940e242de32d216e9795291dc2093299b64ce57760b722ee7a0a33491",
    "terra_r1": "3e833f88a813192f3c3190847e551439c34c7741d5bb87443d156cd244fc0b4f",
    "terra_r2": "858276b6da253f86d08f6ee8fba4ce6cd7eb28cce2005f3c6fbb67aa7b2bf3a6",
    "sol_r2": "0bff8ed59f1fd011db53ffca63c8e39f323f747cb512231b4560f8f176cbd3a8",
    "astra_r2": "f0b40ab005e0dfdd38a4285fd14c4e098cd5da8ea92e507943ab99c3aea2ad1d",
}


@pytest.mark.parametrize("identity,expected", PARENTS.items())
def test_next_two_segment_window_reproduces_from_exact_audited_parent(
    identity, expected
):
    sources = [
        ROOT / "experiments/evidence" / f"keyboard_matched_{identity}{suffix}.json"
        for suffix in (
            "_20260910",
            "_continuation_32_64_20260910",
            "_continuation_64_128_20260911",
        )
    ]
    assert sha(sources[-1]) == expected
    parent = json.loads(sources[-1].read_bytes())
    digests = [(path, sha(path)) for path in sources]
    generated = prepare(digests)
    path = (
        ROOT
        / "experiments/keyboard_matched_endurance_20260911"
        / f"{identity}-128-256.json"
    )
    assert path.read_bytes() == encoded(generated)
    condition, window = load_window(
        ROOT
        / "experiments/keyboard_matched_pilot_20260910"
        / generated["original_condition"],
        path,
    )
    assert (window["continuation_from_next_step"], window["window_end_decision"]) == (
        128,
        256,
    )
    assert (window["steps_per_segment"], window["max_segments"]) == (64, 2)
    assert window["comparison_target_decision"] == 256
    assert window["continuation_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert window["source_result_chain_sha256"] == [digest for _, digest in digests]
    assert window["source_audit_sha256"] == parent["audit_sha256"]
    assert (
        window["returned_tokens_before_window"]
        == parent["usage"]["campaign_returned_tokens"]
    )
    assert window["saved_elapsed_ticks_before_window"] == parent["saved_elapsed_ticks"]
    assert condition["model"] == parent["model"]
    assert (
        condition["max_dispatches"] == 1280
        and condition["max_total_tokens"] == 40000000
    )
    assert {
        key: window[key]
        for key in ("reset_memory", "reset_usage", "strategy_intervention")
    } == {"reset_memory": False, "reset_usage": False, "strategy_intervention": False}
    assert not {"restart", "prompt_change", "budget_extension"} & window.keys()
    assert [(path, sha(path)) for path in sources] == digests


def test_no_unfinished_replicate_is_given_an_invented_128_parent():
    directory = ROOT / "experiments/keyboard_matched_endurance_20260911"
    assert {path.stem for path in directory.glob("*.json")} == {
        f"{identity}-128-256" for identity in PARENTS
    }
