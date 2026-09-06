"""Self-hosted llama.cpp campaign transport with measured prompt-token preflight.

Reuse the campaign policy, memory, native grammar and checkpoint accounting. Only
the transport and its explicitly declared token/context rules differ from Ollama.
No hosted SDK, credential, proxy, redirect, retry, or automatic gameplay action.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from .campaign_llama_identity import BUILD, TOKEN_PROFILE, TRANSPORT, verify_llama_model
from .campaign_local import COST_BASIS, LocalCampaignAgent, LocalInferenceError, local_json
from .governed_llm import GovernedBudgetCapError

TOKEN_PATH = "/v1/chat/completions/input_tokens"
CHAT_PATH = "/v1/chat/completions"


class LlamaCampaignAgent(LocalCampaignAgent):
    def __init__(self, *, config: dict, model: str, endpoint: str, journal: Path) -> None:
        from ..run.campaign_config import validate_bounds

        validate_bounds(config, model, local=True)
        self._context_cache: dict[str, dict] = {}
        self._prepared_context: dict = {}
        super().__init__(config=config, model=model, endpoint=endpoint, journal=journal)
        if self.config["local_inference"]["transport"] != TRANSPORT:
            raise ValueError("The llama.cpp agent requires its own declared transport")

    def _checkpoint_configuration(self):
        return {**super()._checkpoint_configuration(), "transport": TRANSPORT}

    def _serialize_request(self, messages) -> bytes:
        local = self.config["local_inference"]
        if (
            not isinstance(messages, list)
            or not messages
            or any(
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or not isinstance(message["role"], str)
                or message["role"] not in {"system", "user", "assistant"}
                or not isinstance(message["content"], str)
                for message in messages
            )
        ):
            raise LocalInferenceError(
                "Local campaign messages must be plain text, not tool/media inputs"
            )
        if type(self._max_tokens) is not int or self._max_tokens <= 0:
            raise LocalInferenceError("Local inference requires a bounded output token count")
        return json.dumps(
            {
                "model": self._model,
                "messages": deepcopy(messages)
                + [{"role": "user", "content": self._response_instruction()}],
                "response_format": {
                    "type": "json_schema",
                    "schema": self._action_tool()["function"]["parameters"],
                },
                "stream": False,
                "max_tokens": self._max_tokens,
                "temperature": local["temperature"],
                "top_p": local["top_p"],
                "top_k": local["top_k"],
                "seed": local["seed"],
                "chat_template_kwargs": {"enable_thinking": False},
            },
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        ).encode()

    def _measure_context(self, body: bytes, *, refresh: bool = False) -> dict:
        digest = hashlib.sha256(body).hexdigest()
        if not refresh and digest in self._context_cache:
            return self._context_cache[digest]
        identity = verify_llama_model(self.endpoint, self.config, self._model)
        response = local_json(
            self.endpoint,
            TOKEN_PATH,
            body=body,
            timeout=self.config["local_inference"]["token_count_timeout_seconds"],
        )
        count = response.get("input_tokens")
        if response.get("object") != "response.input_tokens" or type(count) is not int or count < 1:
            raise LocalInferenceError("Local prompt token count is missing or invalid")
        measured = {
            "profile": TOKEN_PROFILE,
            "request_sha256": digest,
            "request_bytes": len(body),
            "prompt_tokens": count,
            "maximum_output_tokens": self._max_tokens,
            "context_headroom_tokens": self.config["local_inference"]["context_headroom_tokens"],
            "token_count_response_sha256": hashlib.sha256(
                json.dumps(response, sort_keys=True).encode()
            ).hexdigest(),
            "identity": identity,
            "generation_performed": False,
        }
        # Bounded transient memoization only. Refresh again immediately before dispatch;
        # cache contents are never checkpointed or treated as a generation receipt.
        if len(self._context_cache) >= 16:
            self._context_cache.clear()
        self._context_cache[digest] = measured
        return measured

    def _context_fits(self, measured: dict) -> bool:
        return (
            measured["prompt_tokens"] + self._max_tokens + measured["context_headroom_tokens"]
            <= self.config["local_inference"]["context_tokens"]
        )

    def _body_fits(self, body: bytes) -> bool:
        # Serialized JSON is an independent payload limit, not an estimate of tokens.
        return len(body) <= self.config["max_request_bytes"] and self._context_fits(
            self._measure_context(body)
        )

    def _request_body(self, messages) -> bytes:
        self._pre_dispatch_gate()
        body = self._serialize_request(messages)
        if len(body) > self.config["max_request_bytes"]:
            raise GovernedBudgetCapError("Local llama.cpp request exceeds its byte bound")
        measured = self._measure_context(body, refresh=True)
        if not self._context_fits(measured):
            raise GovernedBudgetCapError(
                "Measured prompt and output allowance exceed local context"
            )
        if (
            self._total_tokens + measured["prompt_tokens"] + self._max_tokens
            > self._max_total_tokens
        ):
            raise GovernedBudgetCapError(
                "Measured prompt and output allowance exceed cumulative tokens"
            )
        self._prepared_context = measured
        return body

    def _create_completion(self, messages):
        # Require initialized campaign identity before even the non-generating preflight.
        self.export_campaign_state()
        body = self._request_body(messages)
        measured = deepcopy(self._prepared_context)
        local = self.config["local_inference"]
        self.dispatches += 1
        self._journal(
            {
                "type": "dispatch_started",
                "dispatch": self.dispatches,
                "context": measured,
                "cost_basis": COST_BASIS,
            }
        )
        try:
            response = local_json(
                self.endpoint, CHAT_PATH, body=body, timeout=local["timeout_seconds"]
            )
            self._returned_response_count += 1
            # Preserve the original returned response even if its identity, usage or
            # action content is invalid. Failed diagnostics must not erase evidence.
            self._tool_events.append(
                {
                    "tool": "campaign_llama.chat",
                    "input": {"messages": deepcopy(messages), **measured},
                    "output": {
                        **response,
                        "declared_model_file_sha256": local["model_digests"][self._model],
                        "cost_basis": COST_BASIS,
                    },
                }
            )
            usage = response.get("usage")
            if not isinstance(usage, dict):
                raise LocalInferenceError("Local response has no token usage")
            counts = [
                usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            ]
            if any(type(value) is not int or value < 0 for value in counts):
                raise LocalInferenceError("Local response has invalid token usage")
            prompt_tokens, completion_tokens, total_tokens = cast(
                tuple[int, int, int], tuple(counts)
            )
            if total_tokens != prompt_tokens + completion_tokens:
                raise LocalInferenceError("Local response has invalid token usage")
            self._total_tokens += total_tokens
            self._accounted_response_count += 1
            verify_llama_model(self.endpoint, self.config, self._model)
            if response.get("model") != self._model or response.get("system_fingerprint") != BUILD:
                raise LocalInferenceError("Local response model or runtime identity differs")
            if (
                prompt_tokens != measured["prompt_tokens"]
                or completion_tokens > self.config["max_output_tokens"]
            ):
                raise LocalInferenceError(
                    "Returned usage differs from the measured prompt or output bound"
                )
            choices = response.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
            ):
                raise LocalInferenceError("Local response must contain one action completion")
            choice = choices[0]
            message = choice.get("message")
            if (
                choice.get("finish_reason") != "stop"
                or not isinstance(message, dict)
                or message.get("role") != "assistant"
                or not isinstance(message.get("content"), str)
                or message.get("tool_calls")
            ):
                raise LocalInferenceError("Local action completion is unfinished or malformed")
            return response
        finally:
            self._journal(
                {
                    "type": "dispatch_finished_or_failed",
                    "dispatch": self.dispatches,
                    "usage": self.export_campaign_state()["usage"],
                }
            )
