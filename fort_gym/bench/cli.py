"""Command-line utilities for fort-gym."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import uvicorn

from .agent.base import RandomAgent
from .api.server import app as fastapi_app
from .config import get_settings
from .env.scenarios import get_mock_scenario
from .run.runner import run_once
from .run.storage import RUN_REGISTRY, RunRegistry

try:  # pragma: no cover - exercised in runtime environments
    import typer
except ImportError:  # pragma: no cover - fallback when typer missing
    class _TyperPlaceholder:
        def __init__(self, name: str = "fort-gym") -> None:
            self.name = name

        def command(self, name: str | None = None):
            def decorator(func):
                return func

            return decorator

        def __call__(self, *args, **kwargs) -> None:
            raise RuntimeError("Typer is required. Install it with `pip install typer`.")

    class _TyperModule:
        Typer = _TyperPlaceholder

        @staticmethod
        def echo(message: str) -> None:
            print(message)

    typer = _TyperModule()


app = typer.Typer(name="fort-gym")


def _available_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No available localhost port found from {start} to {start + 49}")


@app.command()
def api(port: int = 8000, reload: bool = True, memory_window: int | None = None) -> None:
    """Start the FastAPI development server."""

    if memory_window is not None:
        os.environ["FORT_GYM_MEMORY_WINDOW"] = str(memory_window)
        get_settings.cache_clear()  # type: ignore[attr-defined]
    uvicorn.run("fort_gym.bench.api.server:app", port=port, reload=reload)


def _run_quickstart_mock(
    *,
    max_steps: int = 3,
    ticks_per_step: int = 10,
    registry: RunRegistry | None = None,
) -> tuple[str, Path, Path, str, list[dict[str, object]]]:
    resolved_registry = registry or RUN_REGISTRY
    record = resolved_registry.create(
        backend="mock",
        model="random",
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
    )
    run_id = run_once(
        RandomAgent(safe=True),
        backend="mock",
        model="random",
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
        run_id=record.run_id,
        registry=resolved_registry,
    )
    share = resolved_registry.create_share(run_id, scope=["live", "replay", "export"])
    leaderboard = resolved_registry.best_scores_over_time(
        days=30,
        backend="mock",
        model="random",
        max_steps=max_steps,
    )
    artifacts_dir = Path(get_settings().ARTIFACTS_DIR).resolve() / run_id
    return run_id, artifacts_dir / "trace.jsonl", artifacts_dir / "summary.json", share.token, leaderboard


@app.command()
def quickstart(
    max_steps: int = 3,
    ticks_per_step: int = 10,
    serve: bool = True,
    port: int = 8000,
) -> None:
    """Run a local mock benchmark and open a ready leaderboard server."""

    run_id, trace_path, summary_path, token, leaderboard = _run_quickstart_mock(
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
    )

    typer.echo("Mock run complete.")
    typer.echo(f"  run_id: {run_id}")
    typer.echo(f"  trace: {trace_path}")
    typer.echo(f"  summary: {summary_path}")
    typer.echo(f"  public token: {token}")
    typer.echo(f"  leaderboard series: {len(leaderboard)}")

    if not serve:
        typer.echo("")
        typer.echo(
            "Start the leaderboard server with: FORT_GYM_INSECURE_ADMIN=1 "
            f"fort-gym api --port {port} --no-reload"
        )
        typer.echo(f"Then open: http://127.0.0.1:{port}/leaderboard")
        return

    resolved_port = _available_port(port)
    os.environ.setdefault("FORT_GYM_INSECURE_ADMIN", "1")
    typer.echo("")
    if resolved_port != port:
        typer.echo(f"Port {port} is already in use; using {resolved_port}.")
    typer.echo(f"Serving http://127.0.0.1:{resolved_port}/leaderboard")
    typer.echo("Press Ctrl+C to stop.")
    uvicorn.run("fort_gym.bench.api.server:app", host="127.0.0.1", port=resolved_port, reload=False)


@app.command("mock-run")
def mock_run(
    max_steps: int = 3,
    ticks_per_step: int = 10,
    safe: bool = True,
) -> None:
    """Run a short mock environment loop and print the run identifier."""

    run_id = run_once(
        RandomAgent(safe=safe),
        env="mock",
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
    )
    typer.echo(run_id)


@app.command("scenario-run")
def scenario_run(
    name: str,
    max_steps: int = 3,
    ticks_per_step: int = 10,
) -> None:
    """Run a built-in mock scenario pack and report assertion results."""

    scenario = get_mock_scenario(name)
    run_id = run_once(
        RandomAgent(safe=True),
        backend="mock",
        model="random",
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
        scenario=scenario.name,
    )
    summary_path = Path(get_settings().ARTIFACTS_DIR).resolve() / run_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assertions = summary.get("scenario_assertions") or []
    failures = [item for item in assertions if not item.get("ok")]

    typer.echo(f"Scenario: {scenario.name}")
    typer.echo(f"Run: {run_id}")
    typer.echo(f"Summary: {summary_path}")
    for item in assertions:
        status = "PASS" if item.get("ok") else "FAIL"
        typer.echo(
            f"  [{status}] {item.get('path')} {item.get('op')} "
            f"{item.get('expected')} (actual: {item.get('actual')})"
        )
    if failures:
        raise typer.Exit(1)


@app.command("live-smoke")
def live_smoke(
    ticks: int = 10,
    run_id: str | None = None,
    check_manager_order: bool = True,
    auto_proto: bool = True,
    install_hooks: bool = True,
) -> None:
    """Run a small end-to-end DFHack smoke test and print artifact paths."""

    from .agent.base import Agent
    from .dfhack_backend import designate_rect, queue_manager_order
    from .env.actions import parse_action
    from .env.dfhack_client import DFHackClient
    from .config import DFROOT

    settings = get_settings()
    from .env.remote_proto import ProtoLoadError, ensure_proto_modules

    if not settings.DFHACK_ENABLED:
        typer.echo("DFHACK_ENABLED=1 is required for live smoke tests.")
        raise typer.Exit(1)

    try:
        modules = ensure_proto_modules()
    except ProtoLoadError:
        if not auto_proto:
            raise
        from importlib import invalidate_caches

        from .env.remote_proto.fetch_proto import generate_bindings

        generate_bindings()
        invalidate_caches()
        modules = ensure_proto_modules()
    if not modules:
        typer.echo("DF_PROTO_ENABLED=1 is required for live smoke tests.")
        raise typer.Exit(1)

    client = DFHackClient(host=settings.DFHACK_HOST, port=settings.DFHACK_PORT)
    client.connect()
    client.close()

    if install_hooks:
        repo_root = Path(__file__).resolve().parents[2]
        source_hook_dir = repo_root / "hook"
        target_hook_dir = DFROOT / "hook"
        try:
            target_hook_dir.mkdir(parents=True, exist_ok=True)
            for source in source_hook_dir.glob("*.lua"):
                shutil.copy2(source, target_hook_dir / source.name)
        except PermissionError:
            subprocess.check_call(["sudo", "-n", "mkdir", "-p", str(target_hook_dir)])
            for source in source_hook_dir.glob("*.lua"):
                subprocess.check_call(
                    ["sudo", "-n", "cp", str(source), str(target_hook_dir / source.name)]
                )

    hook_checks: dict[str, object] = {
        "invalid_order": queue_manager_order("sword_of_gods", 1),
        "oversized_designation": designate_rect("dig", 0, 0, 0, 200, 200, 0),
    }
    if check_manager_order:
        hook_checks["manager_order_bed"] = queue_manager_order("bed", 1)

    class LiveSmokeAgent(Agent):
        def __init__(self) -> None:
            self._step = 0

        def decide(self, obs_text, obs_json):  # type: ignore[no-untyped-def]
            self._step += 1
            if self._step == 1:
                return parse_action(
                    {
                        "type": "DIG",
                        "params": {"area": [0, 0, 0], "size": [1, 1, 1]},
                        "intent": "live smoke dig designation",
                        "advance_ticks": 0,
                    }
                )
            return parse_action(
                {
                    "type": "WAIT",
                    "params": {},
                    "intent": "live smoke tick advancement",
                    "advance_ticks": ticks,
                }
            )

    resolved_run_id = run_id or "live-dfhack-smoke"
    result_run_id = run_once(
        LiveSmokeAgent(),
        backend="dfhack",
        model="live-smoke",
        max_steps=2,
        ticks_per_step=ticks,
        run_id=resolved_run_id,
    )
    artifacts_dir = Path(settings.ARTIFACTS_DIR).resolve() / result_run_id
    trace_path = artifacts_dir / "trace.jsonl"
    summary_path = artifacts_dir / "summary.json"
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dig_record = next(
        (record for record in records if record.get("action", {}).get("type") == "DIG"),
        {},
    )
    wait_record = next(
        (record for record in records if record.get("action", {}).get("type") == "WAIT"),
        {},
    )
    wait_tick_info = wait_record.get("tick_advance") or {}

    checks = {
        "dfhack_connect": True,
        "invalid_order_rejected": hook_checks["invalid_order"].get("error") == "invalid_item"
        if isinstance(hook_checks["invalid_order"], dict)
        else False,
        "oversized_designation_rejected": hook_checks["oversized_designation"].get("error")
        == "rect_too_large"
        if isinstance(hook_checks["oversized_designation"], dict)
        else False,
        "manager_order_bed_ok": (
            hook_checks.get("manager_order_bed", {"ok": True}).get("ok") is True
            if isinstance(hook_checks.get("manager_order_bed", {"ok": True}), dict)
            else False
        ),
        "dig_accepted": (dig_record.get("execute") or {}).get("accepted") is True,
        "wait_ticks_advanced": int(wait_tick_info.get("ticks_advanced") or 0) >= ticks,
        "trace_written": trace_path.is_file(),
        "summary_written": summary_path.is_file(),
    }
    report = {
        "ok": all(checks.values()),
        "checks": checks,
        "hook_checks": hook_checks,
        "run_id": result_run_id,
        "trace": str(trace_path),
        "summary": str(summary_path),
        "wait_tick_advance": wait_tick_info,
    }
    typer.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise typer.Exit(1)


@app.command()
def experiment(config: str) -> None:
    """Run an experiment from a YAML configuration file."""

    from .experiment.runner import ExperimentRunner

    runner = ExperimentRunner()
    result = runner.run_from_path(config)
    typer.echo(result.experiment_id)
    typer.echo(result.artifacts_dir)


@app.command()
def routes() -> None:
    """List API routes for sanity checking."""

    paths = sorted(route.path for route in fastapi_app.routes if hasattr(route, "path"))
    for path in paths:
        typer.echo(path)


@app.command()
def analyze(
    run_id: str,
    artifacts_dir: str | None = None,
    output: str | None = None,
) -> None:
    """Analyze a run trace using LLM-based analysis (Gemini 3.0 Pro Preview).

    Args:
        run_id: The run ID to analyze
        artifacts_dir: Override artifacts directory (default: fort_gym/artifacts)
        output: Output directory for analysis files (default: same as trace)
    """
    from .eval.analyzer import TraceAnalyzer, save_analysis

    # Determine paths
    if artifacts_dir:
        base_dir = Path(artifacts_dir)
    else:
        base_dir = Path(__file__).parent.parent / "artifacts"

    trace_path = base_dir / run_id / "trace.jsonl"
    if not trace_path.exists():
        typer.echo(f"Error: Trace not found at {trace_path}")
        raise typer.Exit(1)

    typer.echo(f"Analyzing run {run_id}...")

    try:
        analyzer = TraceAnalyzer()
        report = analyzer.analyze(trace_path)

        # Save results
        output_dir = Path(output) if output else trace_path.parent
        json_path, text_path = save_analysis(report, output_dir)

        typer.echo(f"\nAnalysis complete!")
        typer.echo(f"  JSON: {json_path}")
        typer.echo(f"  Text: {text_path}")
        typer.echo("")
        typer.echo("=== Summary ===")
        typer.echo(report.summary or "No summary generated")
        typer.echo("")
        typer.echo(f"Anomalies found: {len(report.anomalies)}")
        typer.echo(f"Patterns found: {len(report.patterns)}")
        typer.echo(f"Recommendations: {len(report.recommendations)}")

        # Show critical/warning anomalies
        critical = [a for a in report.anomalies if a.severity == "critical"]
        warning = [a for a in report.anomalies if a.severity == "warning"]

        if critical:
            typer.echo("\n=== Critical Anomalies ===")
            for a in critical[:3]:
                typer.echo(f"  [{a.type}] {a.description}")

        if warning:
            typer.echo("\n=== Warnings ===")
            for a in warning[:3]:
                typer.echo(f"  [{a.type}] {a.description}")

    except ValueError as e:
        typer.echo(f"Error: {e}")
        typer.echo("Set GOOGLE_API_KEY environment variable for LLM-based analysis")
        raise typer.Exit(1)
    except RuntimeError as e:
        typer.echo(f"API Error: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
