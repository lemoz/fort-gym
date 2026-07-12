#!/usr/bin/env python3
"""Probe the exact P1 OpenRouter request policy, including prompt-cache telemetry."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

from fort_gym.bench.agent.governed_llm import (
    GOVERNED_OBSERVATION_PREAMBLE,
    GOVERNED_SYSTEM_PROMPT,
    DFHackGovernedLLMAgent,
)
from fort_gym.bench.agent.minimap_render import minimap_data_url

ARMS = {
    "fable": {
        "model": "anthropic/claude-fable-5",
        "cache": "explicit_ephemeral",
        "omit_temperature": True,
    },
    "sol": {
        "model": "openai/gpt-5.6-sol",
        "cache": "automatic",
        "omit_temperature": False,
    },
}


def _messages(call_index: int) -> list[dict[str, Any]]:
    image = minimap_data_url(
        {
            "map_rows": ["..WWW..", "..W.W..", "..W@W..", "..WWW.."],
            "map_origin": [90, 92, 161],
        }
    )
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"P1 transport preflight call {call_index}. Submit one legal WAIT action with "
                "advance_ticks=2500. "
                "Use objective 'Verify transport', plan_step 'Wait once', expected result "
                "'Simulation advances', last_action_review verdict unknown with empty evidence, "
                "and plan_review decision establish with one step."
            ),
        }
    ]
    if image:
        content.append({"type": "image_url", "image_url": {"url": image}})
    return [
        {"role": "system", "content": GOVERNED_SYSTEM_PROMPT},
        {"role": "user", "content": GOVERNED_OBSERVATION_PREAMBLE},
        {"role": "user", "content": content},
    ]


def _probe(name: str) -> dict[str, Any]:
    arm = ARMS[name]
    agent = DFHackGovernedLLMAgent(
        model_override=str(arm["model"]),
        memory_path=None,
        vision=True,
        max_tokens=128000,
        reasoning_effort="max",
        prompt_cache=str(arm["cache"]),
        omit_temperature=bool(arm["omit_temperature"]),
        max_attempts=1,
        memory_window=0,
        max_advance_ticks=2500,
    )
    agent.set_run_context(run_id=f"p1-preflight-{name}-{uuid.uuid4().hex[:8]}")
    calls = []
    for index in range(2):
        response = agent._create_completion(_messages(index + 1))
        payload = agent._extract_tool_payload(response)
        usage_event = next(
            event
            for event in reversed(agent.pop_tool_events())
            if event.get("tool") == "openrouter.chat.completions.create"
        )
        output = usage_event.get("output") or {}
        calls.append(
            {
                "index": index + 1,
                "tool_payload_received": isinstance(payload, dict),
                "action_type": payload.get("type") if isinstance(payload, dict) else None,
                "advance_ticks": (
                    payload.get("advance_ticks") if isinstance(payload, dict) else None
                ),
                "generation_id": output.get("generation_id"),
                "resolved_model": output.get("resolved_model"),
                "finish_reasons": output.get("finish_reasons"),
                "prompt_tokens": output.get("prompt_tokens"),
                "completion_tokens": output.get("completion_tokens"),
                "cached_tokens": output.get("cached_tokens"),
                "cache_write_tokens": output.get("cache_write_tokens"),
                "reasoning_tokens": output.get("reasoning_tokens"),
                "cost": output.get("cost"),
                "generation": output.get("generation"),
            }
        )
        if index == 0:
            time.sleep(12.0)
    second_cached = int(calls[1].get("cached_tokens") or 0)
    return {
        "arm": name,
        "requested_model": arm["model"],
        "reasoning_effort": "max",
        "max_tokens": 128000,
        "vision": True,
        "memory": "off",
        "cache_policy": arm["cache"],
        "calls": calls,
        "cache_verified": second_cached > 0,
        "transport_verified": all(
            call["tool_payload_received"]
            and str(call["action_type"] or "").upper() == "WAIT"
            and call["advance_ticks"] == 2500
            for call in calls
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=[*ARMS, "all"], default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required")
    selected = list(ARMS) if args.arm == "all" else [args.arm]
    report = {
        "schema_version": "fort-eval.provider-preflight/v1",
        "results": [_probe(name) for name in selected],
    }
    report["ok"] = all(
        result["cache_verified"] and result["transport_verified"] for result in report["results"]
    )
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
