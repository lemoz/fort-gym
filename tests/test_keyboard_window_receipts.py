"""Synthetic receipt composition only, not provider or native gameplay proof."""

import json
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.keyboard_window_receipts import verify_window_receipts


def fixture(tmp_path, *, responses=6, paused=False, invalid_at=None):
    native, out = tmp_path / "native", tmp_path / "host"
    memory, summaries = "own-checkpoint-memory", []
    for index in range(responses + int(paused)):
        identifier = f"{index + 1:032x}"
        host, game = out / "model" / identifier, native / "exchange" / identifier
        host.mkdir(parents=True)
        game.mkdir(parents=True)
        request = {"memory": memory, "screen": {"width": 120, "height": 40}}
        dispatched, valid = index < responses, index != invalid_at
        valid = valid and dispatched
        action = {"memory_update": memory + f"/{index}"} if valid else None
        response = {"result": {"action": action, "action_grammar_valid": valid}}
        summary = {"decision_index": index, "model_dispatched": dispatched}
        summaries.append(summary)
        for path in (host, game):
            publish(path / "request.json", request)
            publish(path / "response.json", response)
        publish(host / "claim.json", {"fixture": True})
        publish(host / "summary.json", summary)
        if valid:
            memory = action["memory_update"]
    calls, pauses = [], []

    def review_response(path, condition):
        assert condition == {"screen_size": [120, 40]}
        index = read(path / "summary.json")["decision_index"]
        calls.append(index)
        return {"decision_index": index, "total_tokens": 10}

    def review_pause(path):
        pauses.append(read(path / "summary.json")["decision_index"])
        return {"dispatched": False}

    return SimpleNamespace(
        native=native,
        out=out,
        memory=memory,
        calls=calls,
        pauses=pauses,
        options={
            "condition": {"screen_size": [120, 40]},
            "control": {
                "model_decisions": summaries,
                "provider_calls": responses,
                "confirmed_model_calls": responses,
            },
            "initial_memory": "own-checkpoint-memory",
            "responses": responses,
            "status": "paused" if paused else "completed",
            "review_response": review_response,
            "review_pause": review_pause,
        },
    )


def audit(case):
    return verify_window_receipts(case.native, case.out, **case.options)


def test_global_receipt_order_preserves_memory_across_segment_boundary(tmp_path):
    case = fixture(tmp_path)
    report = audit(case)
    assert case.calls == list(range(6))
    assert report["new_responses"] == 6 and report["new_tokens"] == 60
    assert report["final_memory"] == case.memory
    assert len(report["actions"]) == 6 and report["admission_pauses"] == []


@pytest.mark.parametrize("responses", [0, 3])
def test_pre_dispatch_pause_preserves_completed_receipts(tmp_path, responses):
    case = fixture(tmp_path, responses=responses, paused=True)
    report = audit(case)
    assert case.calls == list(range(responses)) and case.pauses == [responses]
    assert report["new_responses"] == responses
    assert report["new_tokens"] == responses * 10
    assert report["final_memory"] == case.memory
    assert len(report["admission_pauses"]) == 1


def test_invalid_grammar_retains_usage_without_changing_memory(tmp_path):
    case = fixture(tmp_path, invalid_at=2)
    report = audit(case)
    assert report["new_responses"] == 6 and report["new_tokens"] == 60
    assert report["actions"][2] is None
    assert report["final_memory"] == case.memory


@pytest.mark.parametrize(
    "field,value", [("memory", "reset"), ("screen", {"width": 119, "height": 40})]
)
def test_second_segment_cannot_reset_memory_or_change_screen(tmp_path, field, value):
    case = fixture(tmp_path)
    identifier = f"{4:032x}"
    request = read(case.out / "model" / identifier / "request.json")
    request[field] = value
    for root in (case.out / "model", case.native / "exchange"):
        (root / identifier / "request.json").write_text(json.dumps(request))
    with pytest.raises(ValueError):
        audit(case)
    assert case.calls == [0, 1, 2]


@pytest.mark.parametrize("filename", ["request.json", "response.json"])
def test_native_and_host_exchange_copies_must_match(tmp_path, filename):
    case = fixture(tmp_path)
    (case.native / "exchange" / f"{4:032x}" / filename).write_text(
        json.dumps({"different": True})
    )
    with pytest.raises(ValueError):
        audit(case)


@pytest.mark.parametrize(
    "filename", ["request.json", "response.json", "claim.json", "summary.json"]
)
def test_missing_request_claim_or_response_is_not_a_completed_window(
    tmp_path, filename
):
    case = fixture(tmp_path)
    (case.out / "model" / f"{4:032x}" / filename).unlink()
    with pytest.raises(ValueError):
        audit(case)
    assert case.calls == []


def test_unsettled_extra_claim_is_not_ignored(tmp_path):
    case = fixture(tmp_path)
    extra = case.out / "model" / f"{99:032x}"
    extra.mkdir()
    publish(extra / "claim.json", {"unknown": True})
    with pytest.raises(ValueError):
        audit(case)


@pytest.mark.parametrize(
    "field,value",
    [("decision_index", True), ("decision_index", 0), ("model_dispatched", 1)],
)
def test_indices_and_dispatch_status_are_strict(tmp_path, field, value):
    case = fixture(tmp_path)
    summary = case.options["control"]["model_decisions"][3]
    summary[field] = value
    (case.out / "model" / f"{4:032x}" / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        audit(case)


@pytest.mark.parametrize(
    "field,value", [("provider_calls", 6.0), ("confirmed_model_calls", 5)]
)
def test_provider_counts_cannot_change_or_use_noninteger_values(tmp_path, field, value):
    case = fixture(tmp_path)
    case.options["control"][field] = value
    with pytest.raises(ValueError):
        audit(case)


@pytest.mark.parametrize("tokens", [-1, True, None])
def test_provider_review_requires_a_known_nonnegative_token_count(tmp_path, tokens):
    case = fixture(tmp_path)
    case.options["review_response"] = lambda *_: {"total_tokens": tokens}
    with pytest.raises(ValueError):
        audit(case)


def test_a_completed_window_cannot_hide_an_admission_pause(tmp_path):
    case = fixture(tmp_path, responses=3, paused=True)
    case.options["status"] = "completed"
    with pytest.raises(ValueError):
        audit(case)
