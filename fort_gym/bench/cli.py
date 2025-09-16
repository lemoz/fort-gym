"""Command-line utilities for fort-gym."""

from __future__ import annotations

import uvicorn

from .agent.base import RandomAgent
from .api.server import app as fastapi_app
from .run.runner import run_once

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


@app.command()
def api(port: int = 8000, reload: bool = True) -> None:
    """Start the FastAPI development server."""

    uvicorn.run("fort_gym.bench.api.server:app", port=port, reload=reload)


@app.command("mock-run")
def mock_run(max_steps: int = 3, ticks_per_step: int = 10) -> None:
    """Run a short mock environment loop and print the run identifier."""

    run_id = run_once(RandomAgent(), env="mock", max_steps=max_steps, ticks_per_step=ticks_per_step)
    typer.echo(run_id)


@app.command()
def routes() -> None:
    """List API routes for sanity checking."""

    paths = sorted(route.path for route in fastapi_app.routes)
    for path in paths:
        typer.echo(path)


if __name__ == "__main__":  # pragma: no cover
    app()
