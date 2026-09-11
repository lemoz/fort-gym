"""Reconcile a declared model's actual subscription events, without calling it."""

# ruff: noqa: E402 -- Read receipts with the declared native harness.

import hashlib
import json
from pathlib import Path
import sys

WORKTREE = (
    Path(__file__).resolve().parents[2]
    / "fort_gym/artifacts/worktrees/campaign-dismissed-screen-restart"
)
sys.path.insert(0, str(WORKTREE))
from fort_gym.bench.agent.codex_protocol import decode_events
from fort_gym.bench.agent.keyboard_exchange import digest, read, validate_request
from fort_gym.bench.agent.keyboard_prompt import MEMORY_CONTRACT
from fort_gym.bench.agent.keyboard_decision import BINDING_INSTRUCTIONS
from fort_gym.bench.agent.standard_input import parse_response
from fort_gym.bench.env.screen_observation import encode_screen, TEXT_PROFILE


def review_request(directory, condition):
    request = read(directory / "request.json")
    validate_request(request)
    assert request["request_id"] == directory.name
    assert request["schema_version"] == "fortgym.keyboard-exchange-request/v4"
    assert (
        request["control_profile"]
        == condition["control_profile"]
        == "native_keyboard_bindings/v1"
    )
    assert request["bindings_sha256"] == condition["bindings_sha256"]
    assert request["model"] == condition["model"]
    assert request["reasoning_effort"] == condition["reasoning_effort"] == "medium"
    assert request["prompt_profile"] == condition["prompt_profile"]
    response, claim = read(directory / "response.json"), read(directory / "claim.json")
    assert response["request_sha256"] == claim["request_sha256"] == digest(request)
    assert claim["dispatch_outcome"] == "unknown_until_response"
    summary, courier = (
        read(directory / "summary.json"),
        read(directory / "courier-summary.json"),
    )
    assert {k: v for k, v in summary.items() if k != "decision_index"} == courier
    decision = response["result"]
    receipt = decision["transport_receipt"]
    run = Path(receipt["run_directory"])
    assert run.parent == directory and not run.is_symlink()
    assert read(run / "result.json") == receipt
    assert read(run / "keyboard-decision.json") == decision
    assert decision["native_action_dispatched"] is False
    assert courier["model_dispatched"] is receipt["dispatched"] is True
    assert courier["action_grammar_valid"] is decision["action_grammar_valid"]
    assert courier["total_tokens"] == receipt["total_tokens"]
    assert courier["reported_charge_usd"] is receipt["reported_charge_usd"] is None
    assert receipt["model_requested"] == condition["model"]
    assert receipt["reasoning_effort_requested"] == condition["reasoning_effort"]
    assert (
        receipt["transport"] == "codex-exec-chatgpt/v1"
        and receipt["auth_mode"] == "chatgpt"
    )
    assert receipt["api_credentials_inherited"] is False
    assert receipt["accepted"] is receipt["usage_complete"] is True
    assert receipt["interrupted"] is receipt["timed_out"] is False
    assert receipt["exit_code"] == 0 and receipt["launch_error"] is None
    metadata = read(run / "request.json")
    assert metadata["dispatch_outcome"] == "unknown_until_result_receipt"
    assert all(receipt[k] == v for k, v in metadata.items() if k != "dispatch_outcome")
    prompt = (run / "prompt.txt").read_bytes()
    assert hashlib.sha256(prompt).hexdigest() == receipt["prompt_sha256"]
    assert prompt.decode().count(MEMORY_CONTRACT) == 1
    assert prompt.decode().count(BINDING_INSTRUCTIONS) == 1
    assert "private_food_measurement" not in prompt.decode()
    screen = json.dumps(
        encode_screen(request["screen"], TEXT_PROFILE),
        allow_nan=False,
        sort_keys=True,
        ensure_ascii=False,
    )
    assert prompt.decode().endswith(screen)
    assert decision["screen_sha256"] == hashlib.sha256(screen.encode()).hexdigest()
    schema = (run / "output-schema.json").read_bytes()
    assert schema.endswith(b"\n")
    assert hashlib.sha256(schema[:-1]).hexdigest() == receipt["output_schema_sha256"]
    events = (run / "events.jsonl").read_bytes()
    assert len(events) <= 16 * 1024 * 1024
    decoded = decode_events(events.decode(), exit_code=0, timed_out=False)
    assert all(receipt[k] == v for k, v in decoded.items())
    if decision["action_grammar_valid"]:
        assert (
            parse_response(
                receipt["response"],
                max_advance_ticks=condition["max_advance_ticks"],
                control_profile=condition["control_profile"],
            )
            == decision["action"]
        )
    admission = receipt["admission"]
    assert admission["allowed"] is True and admission["auth_mode"] == "chatgpt"
    assert admission["basis"] == "fresh_codex_app_server_account_read/v1"
    assert (
        admission["maximum_used_percent"]
        == condition["maximum_included_usage_percent"]
        == 98
    )
    assert (
        admission["reported_charge_usd"] is None
        and admission["atomic_account_reservation"] is False
    )
    assert admission["windows"] and all(
        0 <= r["used_percent"] < 98 for r in admission["windows"]
    )
    return {
        "decision_index": summary["decision_index"],
        "request_sha256": digest(request),
        "events_sha256": hashlib.sha256(events).hexdigest(),
        "total_tokens": receipt["total_tokens"],
        "admission_captured_at_unix": admission["captured_at_unix"],
    }
