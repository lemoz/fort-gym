"""Compare two declared output allowances on one retained private prompt.

No remote reads, native game, action execution, retries or campaign continuation.
The caller supplies an authorized local source and owns temporary server teardown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from copy import deepcopy
from pathlib import Path

from fort_gym.bench.agent.campaign_llama_identity import TRANSPORT
from fort_gym.bench.agent.campaign_local import LocalOutputLimitPause, local_endpoint
from fort_gym.bench.run.campaign_config import LOCAL_SCHEMA, load_segment_config
from scripts.campaign_development import make_agent
from scripts.campaign_segment import write_result

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "fortgym.output-budget-diagnostic/v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bounded(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Replay inputs must be bounded regular local files")
    return path.read_bytes()


def load_inputs(
    plan_path: Path, base_path: Path, source_path: Path
) -> tuple[dict, dict, dict, str]:
    plan_bytes = read_bounded(plan_path)
    plan = json.loads(plan_bytes)
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported output-budget diagnostic")
    base_bytes, source_bytes = read_bounded(base_path), read_bounded(source_path)
    if digest(base_bytes) != plan.get("baseline_condition_file_sha256"):
        raise ValueError("Baseline condition differs from the declared diagnostic")
    if digest(source_bytes) != plan.get("source_failure_file_sha256"):
        raise ValueError("Private source differs from the retained failure file")
    base = json.loads(base_bytes)
    if not isinstance(base, dict) or len(base.get("models", [])) != 1:
        raise ValueError("The diagnostic requires one declared local model")
    base = load_segment_config(base_path, base["models"][0])
    if read_bounded(base_path) != base_bytes:
        raise ValueError("Baseline condition changed during validation")
    if base["schema_version"] != LOCAL_SCHEMA or base["local_inference"]["transport"] != TRANSPORT:
        raise ValueError("Replay supports only the declared local llama.cpp transport")
    allowances = plan.get("output_token_allowances")
    if (
        not isinstance(allowances, list)
        or len(allowances) != 2
        or any(type(value) is not int or not 1 <= value <= 16384 for value in allowances)
        or allowances[0] != base["max_output_tokens"]
        or allowances[1] <= allowances[0]
        or type(plan.get("max_dispatches")) is not int
        or plan["max_dispatches"] != 2
        or type(plan.get("max_total_tokens")) is not int
        or not 1 <= plan["max_total_tokens"] <= 30000
        or type(plan.get("source_prompt_tokens")) is not int
        or plan["source_prompt_tokens"] < 1
        or plan["source_prompt_tokens"] * 2 + sum(allowances) > plan["max_total_tokens"]
        or plan.get("native_game_loaded") is not False
        or type(plan.get("native_actions_executed")) is not int
        or plan["native_actions_executed"] != 0
    ):
        raise ValueError("Diagnostic allowances must bound exactly two non-gameplay requests")
    if not source_bytes.endswith(b"\n"):
        raise ValueError("Private failure file is incomplete")
    rows = [json.loads(line) for line in source_bytes.splitlines()]
    if len(rows) != 1 or rows[0].get("step") != plan.get("source_step"):
        raise ValueError("Private failure cursor differs from the diagnostic")
    events = [event for event in rows[0]["events"] if event.get("tool") == "campaign_llama.chat"]
    if len(events) != 1:
        raise ValueError("The source must retain exactly one llama.cpp response")
    event = events[0]
    response = event["output"]
    if (
        response.get("model") != base["models"][0]
        or response["choices"][0]["finish_reason"] != "length"
        or response.get("usage")
        != {
            "prompt_tokens": plan["source_prompt_tokens"],
            "completion_tokens": allowances[0],
            "total_tokens": plan["source_prompt_tokens"] + allowances[0],
        }
    ):
        raise ValueError("Source response does not match the declared output-limit case")
    return plan, base, event, digest(plan_bytes)


def replay(
    plan_path: Path,
    base_path: Path,
    source_path: Path,
    *,
    endpoint: str,
    output: Path,
    revision: str,
) -> dict:
    plan, base, source, plan_digest = load_inputs(plan_path, base_path, source_path)
    endpoint = local_endpoint(endpoint)
    if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise ValueError("Replay requires a full execution revision")
    output.mkdir(mode=0o700, exist_ok=False)
    result = {
        "schema_version": "fortgym.output-budget-result/v1",
        "experiment_id": plan["experiment_id"],
        "code_revision": revision,
        "plan_sha256": plan_digest,
        "source_failure_file_sha256": plan["source_failure_file_sha256"],
        "source_request_sha256": source["input"]["request_sha256"],
        "native_game_loaded": False,
        "native_actions_executed": 0,
        "native_legality": "not_checked",
        "model": base["models"][0],
        "cases": [],
        "dispatched_requests": 0,
        "returned_responses": 0,
        "accounted_responses": 0,
        "total_tokens": 0,
        "total_tokens_scope": "accounted_returned_usage",
        "usage_complete": False,
        "server_teardown": "not_verified_by_diagnostic",
        "metered_provider_charge_usd": "0",
        "infrastructure_cost_usd": None,
        "status": "prepared",
    }
    baseline_body = None
    # Prepare BOTH requests before any identity check, token count or generation.
    prepared = []
    for allowance in plan["output_token_allowances"]:
        config = deepcopy(base)
        config.update(
            max_output_tokens=allowance,
            max_dispatches=1,
            max_total_tokens=plan["source_prompt_tokens"] + allowance,
        )
        case_root = output / f"output-{allowance}"
        case_root.mkdir(mode=0o700)
        agent = make_agent(
            config,
            result["model"],
            case_root / "spend.jsonl",
            persist_dispatches=True,
            local_endpoint=endpoint,
        )
        agent.set_campaign_context(campaign_id=plan["experiment_id"] + f"-{allowance}")
        body = agent._serialize_request(source["input"]["messages"])
        decoded = json.loads(body)
        if baseline_body is None:
            if digest(body) != result["source_request_sha256"]:
                raise ValueError("Current serializer cannot reproduce the exact retained request")
            baseline_body = decoded
        elif {**decoded, "max_tokens": baseline_body["max_tokens"]} != baseline_body:
            raise ValueError("Comparison request changes more than the output allowance")
        write_result(case_root / "request.json", decoded)
        prepared.append((allowance, case_root, agent, digest(body)))
    write_result(output / "prepared.json", result)
    for allowance, case_root, agent, request_digest in prepared:
        case = {
            "output_token_allowance": allowance,
            "request_sha256": request_digest,
            "status": "failed",
            "action_syntax_valid": False,
            "action_type": None,
        }
        private = {}
        started = time.monotonic()
        try:
            response = agent._create_completion(source["input"]["messages"])
            action = agent._campaign_action(agent._extract_tool_payload(response))
            private["action"] = action
            case.update(
                status="action_returned", action_syntax_valid=True, action_type=action["type"]
            )
        except LocalOutputLimitPause:
            case["status"] = "output_limit"
        except Exception as error:
            case["error_type"] = type(error).__name__
            private["error"] = str(error)
        finally:
            usage = agent.export_campaign_state()["usage"]
            events = agent.pop_tool_events()
            case.update(elapsed_seconds=time.monotonic() - started, usage=usage)
            chats = [event for event in events if event.get("tool") == "campaign_llama.chat"]
            case["prompt_count_matches_source"] = bool(chats) and all(
                event["output"].get("usage", {}).get("prompt_tokens")
                == plan["source_prompt_tokens"]
                for event in chats
            )
            if not case["prompt_count_matches_source"]:
                case["status"] = "failed"
            for field in (
                "dispatched_requests",
                "returned_responses",
                "accounted_responses",
                "total_tokens",
            ):
                result[field] += usage[field]
            write_result(case_root / "private-response.json", {**private, "events": events})
            result["cases"].append(case)
            write_result(case_root / "result.json", case)
        if (
            case["status"] == "failed"
            or usage["dispatched_requests"] != usage["accounted_responses"]
        ):
            break
    result["status"] = (
        "two_cases_completed"
        if len(result["cases"]) == 2 and all(case["status"] != "failed" for case in result["cases"])
        else "stopped_without_retry"
    )
    result["usage_complete"] = (
        result["dispatched_requests"]
        == result["returned_responses"]
        == result["accounted_responses"]
    )
    write_result(output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(read_bounded(args.plan))
    base = (ROOT / plan["baseline_condition_file"]).resolve(strict=True)
    base.relative_to(ROOT)
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT):
        raise ValueError("Commit tracked implementation changes before a real replay")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(
        json.dumps(
            replay(
                args.plan,
                base,
                args.source,
                endpoint=args.endpoint,
                output=args.output,
                revision=revision,
            )
        )
    )


if __name__ == "__main__":
    main()
