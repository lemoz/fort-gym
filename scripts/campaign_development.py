"""Run one inexpensive model-selected development probe in an isolated real fort.

The parent owns runtime lifetime; a separate worker imports the harness with the
copied DFROOT and RPC port. No production registry, seed reset, or service restart.
This is an executable experiment configuration, not a frozen benchmark protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from fort_gym.bench.run.campaign_config import read_config, validate_bounds
from scripts.campaign_load_smoke import run_isolated


def load_config(path: Path, model: str) -> dict:
    return validate_bounds(read_config(path), model)


def append_event(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_local_transport(endpoint: str, config: dict, model: str) -> None:
    """Verify the declared transport before allocating an isolated game runtime."""
    from fort_gym.bench.agent.campaign_llama_identity import TRANSPORT, verify_llama_model
    from fort_gym.bench.agent.campaign_local import verify_local_model

    validate_bounds(config, model, local=True)
    if config["local_inference"]["transport"] == TRANSPORT:
        verify_llama_model(endpoint, config, model)
    else:
        verify_local_model(endpoint, config, model)


def make_agent(
    config: dict,
    model: str,
    journal: Path,
    *,
    persist_dispatches: bool = False,
    local_endpoint: str | None = None,
):
    from fort_gym.bench.run.campaign_config import LOCAL_SCHEMA

    if config.get("schema_version") == LOCAL_SCHEMA:
        from fort_gym.bench.agent.campaign_local import LocalCampaignAgent
        from fort_gym.bench.agent.campaign_llama import LlamaCampaignAgent
        from fort_gym.bench.agent.campaign_llama_identity import TRANSPORT

        validate_bounds(config, model, local=True)
        if not persist_dispatches or local_endpoint is None:
            raise ValueError(
                "Local campaigns require a dedicated endpoint and persistent accounting"
            )
        local_agent_class = (
            LlamaCampaignAgent
            if config["local_inference"]["transport"] == TRANSPORT
            else LocalCampaignAgent
        )
        return local_agent_class(
            config=config, model=model, endpoint=local_endpoint, journal=journal
        )
    from fort_gym.bench.agent.campaign_llm import CampaignLLMAgent
    from fort_gym.bench.agent.governed_llm import DFHackGovernedLLMAgent, GovernedBudgetCapError

    profile = config.get("decision_profile", "governed_review/v1")
    if not isinstance(profile, str) or profile not in {"governed_review/v1", "campaign_action/v1"}:
        raise ValueError("Unknown development decision profile")
    if profile == "campaign_action/v1" and not persist_dispatches:
        raise ValueError("Exploratory campaigns require persistent dispatch accounting")

    class DevelopmentAgent(DFHackGovernedLLMAgent):
        dispatches = 0

        def _dispatch_completion(self, completion_kwargs):
            request = dict(completion_kwargs)
            extra = dict(request.get("extra_body") or {})
            provider = dict(extra.get("provider") or {})
            provider["max_price"] = dict(config["provider_max_price"])
            extra["provider"] = provider
            request["extra_body"] = extra
            size = len(json.dumps(request, ensure_ascii=True).encode())
            if self.dispatches >= config["max_dispatches"] or size > config["max_request_bytes"]:
                raise GovernedBudgetCapError("Development dispatch or request-size bound reached")
            self._pre_dispatch_gate()
            self.dispatches += 1
            append_event(
                journal,
                {
                    "type": "dispatch_started",
                    "dispatch": self.dispatches,
                    "request_bytes": size,
                    "model": model,
                    "provider_price_ceiling": config["provider_max_price"],
                    "note": "Dispatch intent is not a charge or proof of a returned response",
                },
            )
            try:
                return super()._dispatch_completion(request)
            finally:
                append_event(
                    journal,
                    {
                        "type": "dispatch_finished_or_failed",
                        "dispatch": self.dispatches,
                        "usage": self._budget_snapshot(),
                    },
                )

        def _checkpoint_configuration(self):
            configuration = {**super()._checkpoint_configuration(), "development_bounds": config}
            if persist_dispatches:
                configuration["campaign_dispatch_accounting"] = "v1"
            return configuration

        def export_campaign_state(self):
            state = super().export_campaign_state()
            if persist_dispatches:
                state["usage"]["dispatched_requests"] = self.dispatches
            return state

        def restore_campaign_state(self, data: dict, *, campaign_id: str) -> None:
            state = deepcopy(data)
            dispatches = 0
            if persist_dispatches:
                dispatches = state["usage"].pop("dispatched_requests", None)
                if type(dispatches) is not int or dispatches < 0:
                    raise ValueError("Campaign checkpoint lacks a valid dispatch counter")
                if dispatches < state["usage"]["returned_responses"]:
                    raise ValueError("Dispatch count is below returned response count")
                if self.dispatches:
                    raise ValueError("Restore into a fresh agent without prior dispatches")
            super().restore_campaign_state(state, campaign_id=campaign_id)
            if persist_dispatches:
                self.dispatches = dispatches

    class CampaignDevelopmentAgent(DevelopmentAgent, CampaignLLMAgent):
        """Compose the campaign policy with the same bounded, journaled transport."""

    agent_class = DevelopmentAgent
    options = {}
    if profile == "campaign_action/v1":
        agent_class = CampaignDevelopmentAgent
        options["schema_attempts"] = config["schema_attempts"]
    return agent_class(
        **options,
        model_override=model,
        memory_path=None,
        provider_name=None,
        strict_supervised=False,
        max_attempts=config["max_attempts"],
        max_tokens=config["max_output_tokens"],
        max_advance_ticks=config["max_advance_ticks"],
        max_total_tokens=config["max_total_tokens"],
        max_cost_usd=config["max_cost_usd"],
    )


def worker(args, config):
    # Imports occur only after the parent has supplied isolated runtime settings.
    from fort_gym.bench.run.runner import run_once
    from fort_gym.bench.run.campaign_save import NativeSaveSnapshotter, native_save_status

    output = args.output.resolve()
    native = dict(native_save_status())
    if Path(os.environ["DFROOT"]).resolve() != output / "runtime":
        raise ValueError("Worker DFROOT does not identify its isolated runtime")
    if native.get("save_name") != "campaign-resume" or native.get("paused") is not True:
        raise ValueError("Worker did not find the loaded paused experiment save")
    agent = make_agent(config, args.model, output / "spend.jsonl")
    run_id = output.name
    agent.set_campaign_context(campaign_id=run_id)
    result = {
        "schema_version": "fortgym.development-probe-result/v1",
        "model": args.model,
        "run_id": run_id,
        "config": config,
        "native_start": native,
        "campaign_recovery_verified": False,
        "status": "started",
    }
    try:
        result["run_result"] = run_once(
            agent,
            backend="dfhack",
            model="dfhack-governed-llm",
            run_id=run_id,
            max_steps=config["max_steps"],
            ticks_per_step=config["ticks_per_step"],
            preserve_save=True,
            runtime_save="campaign-resume",
            evaluation_protocol=None,
        )
        result["status"] = "returned"
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        result["dispatches"] = agent.dispatches
        result["usage"] = agent._budget_snapshot()
        with (output / "agent-final.json").open("x") as handle:
            json.dump(agent.export_campaign_state(), handle, indent=2)
        try:
            result["native_final"] = dict(native_save_status())
            result["final_save"] = NativeSaveSnapshotter(dfroot=output / "runtime").capture(
                output / "final-save"
            )
        except Exception as error:
            result["final_save_error"] = type(error).__name__ + ": " + str(error)
        with (output / "experiment.json").open("x") as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps({key: value for key, value in result.items() if key != "final_save"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--port", type=int, default=5501)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config, args.model)
    if "runner" in config or "decision_profile" in config or "observation_profile" in config:
        raise ValueError("Campaign conditions must use scripts.campaign_segment")
    if args.worker:
        worker(args, config)
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError("The existing project provider credential must be supplied")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise ValueError("Development experiments require a clean committed checkout")

    def play(runtime, environment, loaded):
        worker_env = {
            **environment,
            "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
            "FORT_GYM_DISABLE_DOTENV": "1",
            "DFROOT": str(runtime.resolve()),
            "DFHACK_ENABLED": "1",
            "DF_PROTO_ENABLED": "1",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(args.port),
            "ARTIFACTS_DIR": str(args.output.resolve() / "segments"),
            "FORT_GYM_DB_PATH": str(args.output.resolve() / "registry.sqlite"),
            "FORT_GYM_DFHACK_COMPLETE_DIG": "0",
            "OPENROUTER_TIMEOUT_SECONDS": "60",
        }
        command = [
            sys.executable,
            "-m",
            "scripts.campaign_development",
            "--worker",
            "--config",
            str(args.config.resolve()),
            "--model",
            args.model,
            "--output",
            str(args.output.resolve()),
        ]
        with (args.output / "worker.log").open("xb") as log:
            completed = subprocess.run(
                command, env=worker_env, stdout=log, stderr=subprocess.STDOUT, timeout=900
            )
        if not (args.output / "experiment.json").is_file():
            raise RuntimeError(f"Development worker exited {completed.returncode} without a result")
        result = json.loads((args.output / "experiment.json").read_text())
        return {key: result.get(key) for key in ("model", "status", "dispatches", "usage")}

    result = run_isolated(
        source=args.source,
        snapshot=args.snapshot,
        digest=args.snapshot_sha256,
        output=args.output,
        port=args.port,
        revision=revision,
        work=play,
        hook_source=Path(__file__).resolve().parents[1] / "hook",
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
