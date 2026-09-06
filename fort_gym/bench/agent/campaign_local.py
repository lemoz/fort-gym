"""Self-hosted Ollama transport for the same exploratory campaign policy.

Only a literal loopback endpoint is accepted. No hosted client, credential lookup,
redirect, proxy or fallback is used. Identity and local cost basis are checkpointed.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import copy, deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .campaign_context import CORRECTION_PACKING, PACKING, pack_messages
from .campaign_action_reference import action_reference
from .campaign_action_schema import LEGACY, action_tool
from .campaign_llm import CAMPAIGN_SYSTEM_PROMPT, CampaignLLMAgent
from .governed_llm import GovernedBudgetCapError, GovernedDecisionError

COST_BASIS = "self_hosted_no_metered_provider"
LEGACY_RESPONSE_INSTRUCTION = "Return the submit_action object as JSON, without Markdown."


class LocalInferenceError(GovernedDecisionError):
    terminal_code = "campaign_local_inference_error"


def local_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Local inference requires an explicit literal loopback HTTP endpoint")
    return f"http://{parsed.netloc}"


def local_json(endpoint: str, path: str, *, body: bytes | None = None, timeout: int = 3) -> dict:
    address = local_endpoint(endpoint) + path
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
            with client.stream(
                "GET" if body is None else "POST",
                address,
                content=body,
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 262144:
                        raise LocalInferenceError("Local response exceeded its byte limit")
                    chunks.append(chunk)
        value = json.loads(b"".join(chunks))
    except (httpx.HTTPError, json.JSONDecodeError) as error:
        raise LocalInferenceError(
            "Local inference transport failed", error_type=type(error).__name__
        ) from error
    if not isinstance(value, dict):
        raise LocalInferenceError("Local inference did not return an object")
    return value


def verify_local_model(endpoint: str, config: dict, model: str) -> None:
    local = config["local_inference"]
    version = local_json(endpoint, "/api/version")
    tags = local_json(endpoint, "/api/tags").get("models")
    if version.get("version") != local["server_version"] or not isinstance(tags, list):
        raise LocalInferenceError("Local inference server identity differs from the condition")
    matches = [item for item in tags if isinstance(item, dict) and item.get("name") == model]
    if len(matches) != 1 or matches[0].get("digest") != local["model_digests"][model]:
        raise LocalInferenceError("Local model manifest differs from the declared condition")


class LocalCampaignAgent(CampaignLLMAgent):
    def __init__(self, *, config: dict, model: str, endpoint: str, journal: Path):
        self.config = deepcopy(config)
        self.endpoint = local_endpoint(endpoint)
        self.journal = journal
        self.dispatches = 0
        super().__init__(
            model_override=model,
            memory_path=None,
            schema_attempts=config["schema_attempts"],
            max_attempts=1,
            max_tokens=config["max_output_tokens"],
            max_advance_ticks=config["max_advance_ticks"],
            max_total_tokens=config["max_total_tokens"],
            max_cost_usd=0,
            strict_supervised=False,
            provider_name=None,
        )

    def _action_tool(self) -> dict:
        return action_tool(
            super()._action_tool(), self.config["local_inference"].get("action_schema", LEGACY)
        )

    def _resolve_transport_key(self, api_key):
        if api_key is not None:
            raise ValueError("Local inference does not accept a hosted credential")
        return None

    @staticmethod
    def _validate_max_cost_usd(value):
        if type(value) not in (int, float) or value != 0:
            raise ValueError("Self-hosted model API charges must remain zero")
        return 0.0

    def _client_instance(self):
        raise LocalInferenceError("A hosted client is unavailable in the local adapter")

    def _dispatch_completion(self, completion_kwargs):
        raise LocalInferenceError("Hosted dispatch is unavailable in the local adapter")

    def _pre_dispatch_gate(self):
        if (
            self.dispatches >= self.config["max_dispatches"]
            or self._total_tokens >= self._max_total_tokens
        ):
            raise GovernedBudgetCapError("Cumulative local inference allowance reached")
        if self._total_cost_usd != 0:
            raise LocalInferenceError("Local usage unexpectedly contains a metered provider charge")

    def _checkpoint_configuration(self):
        inherited = super()._checkpoint_configuration()
        return {
            **{
                key: inherited[key]
                for key in (
                    "model",
                    "max_tokens",
                    "max_advance_ticks",
                    "prompt_sha256",
                    "action_tool_sha256",
                    "decision_profile",
                    "schema_attempts",
                )
            },
            "local_condition": self.config,
            "prompt_sha256": hashlib.sha256(self._campaign_system_prompt().encode()).hexdigest(),
            "transport": "ollama-local/v1",
            "endpoint_sha256": hashlib.sha256(self.endpoint.encode()).hexdigest(),
            "cost_basis": COST_BASIS,
        }

    def export_campaign_state(self):
        state = super().export_campaign_state()
        state["usage"].update(dispatched_requests=self.dispatches, cost_basis=COST_BASIS)
        return state

    def restore_campaign_state(self, data, *, campaign_id):
        state = deepcopy(data)
        dispatches = state["usage"].pop("dispatched_requests", None)
        if (
            self.dispatches
            or state["usage"].pop("cost_basis", None) != COST_BASIS
            or type(dispatches) is not int
            or dispatches < state["usage"]["returned_responses"]
            or self._nonnegative_decimal(state["usage"].get("total_cost_usd")) != 0
        ):
            raise ValueError("Local checkpoint usage identity or dispatch count is invalid")
        super().restore_campaign_state(state, campaign_id=campaign_id)
        self.dispatches = dispatches

    def _journal(self, event):
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _response_instruction(self) -> str:
        contract = self.config["local_inference"].get("prompt_contract", "grammar_only/v1")
        if contract == "grammar_only/v1":
            return LEGACY_RESPONSE_INSTRUCTION
        if contract != "visible_action_contract/v1":
            raise ValueError("Unsupported local prompt contract")
        # The native format field constrains decoding; it is not a tool message.
        # Explicitly present the same contract, including its runtime tick bound,
        # without recommending an action, tick count, strategy, or build order.
        return (
            LEGACY_RESPONSE_INSTRUCTION
            + " The action response contract is supplied below. Its advance_ticks bounds "
            "are inclusive; choose the value yourself. Planning notes are optional.\n"
            + json.dumps(self._action_tool()["function"]["parameters"], sort_keys=True)
        )

    def _campaign_system_prompt(self) -> str:
        reference = action_reference(self.config["local_inference"].get("action_reference", "none"))
        return CAMPAIGN_SYSTEM_PROMPT + ("\n" + reference if reference else "")

    def preflight_decision(self, obs_text: str, obs_json: dict) -> None:
        # Preview the next memory review on independent state, not the live agent.
        # The same serializer/bounds are used by the actual first dispatch below.
        preview = copy(self)
        preview._memory = deepcopy(self._memory)
        preview._pending = deepcopy(self._pending)
        preview._record_previous_outcome(obs_text)
        self._request_body(preview._campaign_messages(obs_text, obs_json))

    def _campaign_messages(self, obs_text: str, obs_json: dict | None = None) -> list[dict]:
        packing = self.config["local_inference"].get("prompt_packing", "none")
        if packing == "none":
            messages = super()._campaign_messages(obs_text, obs_json)
            messages[0]["content"] = self._campaign_system_prompt()
            return messages
        if packing not in {PACKING, CORRECTION_PACKING} or obs_json is None:
            raise ValueError("Unsupported campaign prompt packing or missing observation")
        return self._packed_messages(obs_json)

    def _correction_messages(
        self, messages: list[dict], obs_json: dict, correction: dict
    ) -> list[dict]:
        if self.config["local_inference"].get("prompt_packing") != CORRECTION_PACKING:
            return super()._correction_messages(messages, obs_json, correction)
        # All attempts in one decision observe the same paused native state.
        # Repack only its old history, keeping every correction and current fact.
        return self._packed_messages(obs_json, corrections=[*messages[2:], correction])

    def _packed_messages(
        self, obs_json: dict, *, corrections: list[dict] | None = None
    ) -> list[dict]:
        self._pre_dispatch_gate()
        messages = pack_messages(
            obs_json,
            system_prompt=self._campaign_system_prompt(),
            memory_context=self._memory.get_context(include_recent=False),
            fits=lambda candidate: self._body_fits(self._serialize_request(candidate)),
            packing=self.config["local_inference"]["prompt_packing"],
            corrections=corrections,
        )
        if messages is None:
            subject = (
                "Current native facts and corrections" if corrections else "Current native facts"
            )
            raise GovernedBudgetCapError(f"{subject} exceed the declared context bound")
        return messages

    def _serialize_request(self, messages) -> bytes:
        local = self.config["local_inference"]
        max_output_tokens = self._max_tokens
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise LocalInferenceError("Local inference requires a bounded output token count")
        return json.dumps(
            {
                "model": self._model,
                "messages": [{**message} for message in messages]
                + [
                    {
                        "role": "user",
                        "content": self._response_instruction(),
                    }
                ],
                "format": self._action_tool()["function"]["parameters"],
                "stream": False,
                "keep_alive": "30s",
                "options": {
                    "num_ctx": local["context_tokens"],
                    "num_predict": max_output_tokens,
                    "temperature": local["temperature"],
                    "seed": local["seed"],
                },
            },
            ensure_ascii=True,
            allow_nan=False,
        ).encode()

    def _body_fits(self, body: bytes) -> bool:
        # Conservatively budget serialized bytes plus template/output headroom.
        # This is a request allowance, not a claim of measured tokenizer fullness.
        return (
            len(body) <= self.config["max_request_bytes"]
            and len(body) + self.config["max_output_tokens"] + 1024
            <= self.config["local_inference"]["context_tokens"]
        )

    def _request_body(self, messages) -> bytes:
        body = self._serialize_request(messages)
        if not self._body_fits(body):
            raise GovernedBudgetCapError("Local request no longer fits its declared context bound")
        self._pre_dispatch_gate()
        return body

    def _create_completion(self, messages):
        local = self.config["local_inference"]
        body = self._request_body(messages)
        verify_local_model(self.endpoint, self.config, self._model)
        self.dispatches += 1
        self._journal(
            {
                "type": "dispatch_started",
                "dispatch": self.dispatches,
                "request_bytes": len(body),
                "cost_basis": COST_BASIS,
            }
        )
        try:
            response = local_json(
                self.endpoint, "/api/chat", body=body, timeout=local["timeout_seconds"]
            )
            self._returned_response_count += 1
            counts = [response.get(key) for key in ("prompt_eval_count", "eval_count")]
            if any(type(value) is not int or value < 0 for value in counts):
                raise LocalInferenceError("Local response has incomplete token telemetry")
            self._total_tokens += sum(counts)
            self._accounted_response_count += 1
            verify_local_model(self.endpoint, self.config, self._model)
            if response.get("model") != self._model or response.get("done") is not True:
                raise LocalInferenceError("Local response identity or completion is unverified")
            message = response.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise LocalInferenceError("Local response contains no action content")
            self._tool_events.append(
                {
                    "tool": "campaign_local.chat",
                    "input": {
                        "request_bytes": len(body),
                        "request_sha256": hashlib.sha256(body).hexdigest(),
                        **(
                            {"messages": deepcopy(messages)}
                            if self.config["local_inference"].get("prompt_packing")
                            in {PACKING, CORRECTION_PACKING}
                            else {}
                        ),
                    },
                    "output": {
                        **response,
                        "model_manifest_sha256": local["model_digests"][self._model],
                        "cost_basis": COST_BASIS,
                    },
                }
            )
            return {"choices": [{"message": {"content": message["content"]}}]}
        finally:
            self._journal(
                {
                    "type": "dispatch_finished_or_failed",
                    "dispatch": self.dispatches,
                    "usage": self.export_campaign_state()["usage"],
                }
            )
