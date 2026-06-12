"""Command-line utilities for fort-gym."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import uvicorn

from .agent.base import RandomAgent
from .api.server import app as fastapi_app
from .config import get_settings
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

    paths = sorted(route.path for route in fastapi_app.routes)
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
