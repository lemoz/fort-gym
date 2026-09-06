"""Synthetic local action-format check. Never loads or executes a native game.

Preserve request/response and usage evidence in a new private output directory.
The supplied actions test transport fidelity, not autonomous gameplay ability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from fort_gym.bench.agent.campaign_local import LocalCampaignAgent
from fort_gym.bench.run.campaign_config import LOCAL_SCHEMA, load_segment_config
from scripts.campaign_segment import write_result

CASES = (
    {"type": "WAIT", "params": {}, "advance_ticks": 2000},
    {
        "type": "LABOR",
        "params": {"unit_id": 123, "labor": "masonry", "enable": False},
        "advance_ticks": 128,
    },
    {
        "type": "DIG",
        "params": {"area": [12, 34, 56], "size": [2, 3, 1], "kind": "gather"},
        "advance_ticks": 37,
    },
)


def probe(agent: LocalCampaignAgent, output: Path) -> dict:
    # Prove accounting is initialized before any request can leave this process.
    agent.export_campaign_state()
    result: dict = {
        "schema_version": "fortgym.local-contract-probe/v1",
        "scope": "synthetic_action_format_only",
        "native_game_loaded": False,
        "native_actions_executed": 0,
        "model": agent._model,
        "configuration_sha256": hashlib.sha256(
            json.dumps(agent.config, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "cases": [],
    }
    for expected in CASES:
        messages = [
            {"role": "system", "content": "Copy the supplied synthetic JSON object exactly."},
            {"role": "user", "content": json.dumps(expected, sort_keys=True)},
        ]
        case = {"expected": expected, "messages": messages, "exact_match": False}
        try:
            response = agent._create_completion(messages)
            actual = agent._extract_tool_payload(response)
            case.update(actual=actual, exact_match=actual == expected)
        except Exception as error:
            case.update(error_type=type(error).__name__, error=str(error))
        finally:
            case["events"] = agent.pop_tool_events()
            case["cumulative_usage"] = agent.export_campaign_state()["usage"]
            write_result(output / f"case-{len(result['cases'])}.json", case)
        result["cases"].append(case)
        if "error_type" in case:
            break  # Do not silently retry an unresolved transport failure.
    result["all_cases_exact"] = len(result["cases"]) == len(CASES) and all(
        case["exact_match"] for case in result["cases"]
    )
    result["usage"] = agent.export_campaign_state()["usage"]
    write_result(output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_segment_config(args.config, args.model)
    if config["schema_version"] != LOCAL_SCHEMA or config["max_advance_ticks"] < 2000:
        raise ValueError("This fixed diagnostic requires a local condition supporting 2000 ticks")
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    from scripts.campaign_development import make_agent

    agent = make_agent(
        config,
        args.model,
        args.output / "spend.jsonl",
        persist_dispatches=True,
        local_endpoint=args.endpoint,
    )
    agent.set_campaign_context(campaign_id="synthetic-contract-" + args.output.name)
    result = probe(agent, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}))


if __name__ == "__main__":
    main()
