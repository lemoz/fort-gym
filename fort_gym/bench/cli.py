"""Command-line utilities for fort-gym."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import base64
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

PUBLIC_REHEARSAL_PATHS = (
    "/health",
    "/leaderboard",
    "/public/leaderboard/best-over-time",
)
TERMINAL_RUN_STATUSES = {"completed", "failed", "stopped"}


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


def _run_live_smoke(
    ticks: int = 10,
    run_id: str | None = None,
    check_manager_order: bool = True,
    auto_proto: bool = True,
    install_hooks: bool = True,
) -> dict[str, object]:
    """Run a small end-to-end DFHack smoke test and return artifact paths."""

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
    return report


@app.command("live-smoke")
def live_smoke(
    ticks: int = 10,
    run_id: str | None = None,
    check_manager_order: bool = True,
    auto_proto: bool = True,
    install_hooks: bool = True,
) -> None:
    """Run a small end-to-end DFHack smoke test and print artifact paths."""

    report = _run_live_smoke(
        ticks=ticks,
        run_id=run_id,
        check_manager_order=check_manager_order,
        auto_proto=auto_proto,
        install_hooks=install_hooks,
    )
    typer.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise typer.Exit(1)


def _check_public_endpoint(base_url: str, path: str, timeout: float = 5.0) -> dict[str, object]:
    normalized_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        normalized_url,
        headers={"User-Agent": "fort-gym-live-demo-rehearsal/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(2048)
            status = int(response.status)
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        return {
            "ok": False,
            "url": normalized_url,
            "status": exc.code,
            "error": str(exc),
        }
    except (OSError, TimeoutError, URLError) as exc:
        return {
            "ok": False,
            "url": normalized_url,
            "error": str(exc),
        }
    return {
        "ok": 200 <= status < 400,
        "url": normalized_url,
        "status": status,
        "content_type": content_type,
        "bytes_read": len(body),
    }


def _write_live_demo_packet(
    *,
    report: dict[str, object],
    endpoint_checks: list[dict[str, object]],
    public_base_url: str,
    packet_path: str | None = None,
) -> Path:
    summary_path = Path(str(report["summary"])).resolve()
    trace_path = Path(str(report["trace"])).resolve()
    target_path = Path(packet_path).expanduser().resolve() if packet_path else summary_path.parent / "live_demo_packet.md"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    tick_info = report.get("wait_tick_advance") if isinstance(report.get("wait_tick_advance"), dict) else {}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    lines = [
        "# fort-gym live demo rehearsal",
        "",
        f"Generated: {generated_at}",
        f"Status: {'PASS' if report.get('ok') and all(check.get('ok') for check in endpoint_checks) else 'FAIL'}",
        f"Run ID: `{report.get('run_id')}`",
        f"Public base URL: `{public_base_url.rstrip('/')}`",
        "",
        "## One-command rehearsal",
        "",
        "```bash",
        "make vm-live-demo VM_LIVE_DEMO_REF=<branch-or-main>",
        "```",
        "",
        "## Live DFHack checks",
        "",
    ]
    for name, ok in sorted(checks.items()):
        marker = "x" if ok else " "
        lines.append(f"- [{marker}] `{name}`")
    lines.extend(
        [
            "",
            "## Public endpoint checks",
            "",
        ]
    )
    for check in endpoint_checks:
        marker = "x" if check.get("ok") else " "
        status = check.get("status", "error")
        lines.append(f"- [{marker}] GET `{check.get('url')}` -> `{status}`")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Trace: `{trace_path}`",
            f"- Summary: `{summary_path}`",
            f"- Packet: `{target_path}`",
            "",
            "## Expected output shape",
            "",
            "```json",
            json.dumps(
                {
                    "ok": True,
                    "live_smoke": {
                        "ok": True,
                        "run_id": report.get("run_id"),
                        "trace": str(trace_path),
                        "summary": str(summary_path),
                        "wait_tick_advance": {
                            "requested": tick_info.get("requested"),
                            "ticks_advanced": tick_info.get("ticks_advanced"),
                        },
                    },
                    "public_endpoint_checks": [
                        {"ok": check.get("ok"), "url": check.get("url"), "status": check.get("status")}
                        for check in endpoint_checks
                    ],
                    "packet": str(target_path),
                },
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Talk track",
            "",
            "The live path now proves the same harness loop against DFHack: connect, validate safety rails, run a DIG action, advance live ticks with WAIT, and write trace artifacts. The public endpoint checks prove the deployed spectator surface is reachable before the demo starts.",
            "",
        ]
    )
    target_path.write_text("\n".join(lines), encoding="utf-8")
    return target_path


@app.command("live-demo-rehearsal")
def live_demo_rehearsal(
    ticks: int = 10,
    run_id: str | None = None,
    public_base_url: str = "http://34.41.155.134",
    public_paths: str = ",".join(PUBLIC_REHEARSAL_PATHS),
    endpoint_timeout: float = 5.0,
    packet_path: str | None = None,
) -> None:
    """Run live DFHack smoke plus public endpoint checks and write a demo packet."""

    report = _run_live_smoke(
        ticks=ticks,
        run_id=run_id or "live-dfhack-demo-rehearsal",
        check_manager_order=True,
        auto_proto=True,
        install_hooks=True,
    )
    paths = [path.strip() for path in public_paths.split(",") if path.strip()]
    endpoint_checks = [
        _check_public_endpoint(public_base_url, path, timeout=endpoint_timeout)
        for path in paths
    ]
    packet = _write_live_demo_packet(
        report=report,
        endpoint_checks=endpoint_checks,
        public_base_url=public_base_url,
        packet_path=packet_path,
    )
    rehearsal = {
        "ok": bool(report.get("ok")) and all(check.get("ok") for check in endpoint_checks) and packet.is_file(),
        "live_smoke": report,
        "packet": str(packet),
        "public_endpoint_checks": endpoint_checks,
    }
    typer.echo(json.dumps(rehearsal, indent=2, sort_keys=True))
    if not rehearsal["ok"]:
        raise typer.Exit(1)


def _json_request(
    *,
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, object] | None = None,
    admin_user: str | None = None,
    admin_password: str | None = None,
    timeout: float = 30.0,
) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=data,
        method=method,
        headers={"User-Agent": "fort-gym-live-agent-report/1.0"},
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if admin_password:
        user = admin_user or "admin"
        token = base64.b64encode(f"{user}:{admin_password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _find_public_run(public_base_url: str, run_id: str) -> dict[str, object] | None:
    payload = _json_request(method="GET", base_url=public_base_url, path="/public/runs")
    if not isinstance(payload, list):
        return None
    for item in payload:
        if isinstance(item, dict) and item.get("run_id") == run_id:
            return item
    return None


def _load_trace_records(run_id: str, server_artifacts_dir: str | None) -> tuple[list[dict[str, object]], str | None]:
    if not server_artifacts_dir:
        return [], None
    trace_path = Path(server_artifacts_dir).expanduser().resolve() / run_id / "trace.jsonl"
    if not trace_path.is_file():
        return [], str(trace_path)
    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return records, str(trace_path)


def _load_summary(run_id: str, server_artifacts_dir: str | None) -> tuple[dict[str, object], str | None]:
    if not server_artifacts_dir:
        return {}, None
    summary_path = Path(server_artifacts_dir).expanduser().resolve() / run_id / "summary.json"
    if not summary_path.is_file():
        return {}, str(summary_path)
    return json.loads(summary_path.read_text(encoding="utf-8")), str(summary_path)


def _summarize_actions(records: list[dict[str, object]]) -> list[dict[str, object]]:
    actions = []
    for record in records:
        action = record.get("action") if isinstance(record.get("action"), dict) else record.get("raw_action")
        if not isinstance(action, dict):
            action = {}
        validation = record.get("validation") if isinstance(record.get("validation"), dict) else {}
        execute = record.get("execute") if isinstance(record.get("execute"), dict) else {}
        score = record.get("score") if isinstance(record.get("score"), dict) else {}
        tick_advance = record.get("tick_advance") if isinstance(record.get("tick_advance"), dict) else {}
        actions.append(
            {
                "step": record.get("step"),
                "type": action.get("type"),
                "intent": action.get("intent"),
                "params": action.get("params"),
                "advance_ticks": action.get("advance_ticks"),
                "valid": validation.get("valid"),
                "accepted": execute.get("accepted", execute.get("ok")),
                "ticks_advanced": tick_advance.get("ticks_advanced"),
                "score": score.get("value"),
            }
        )
    return actions


def _run_api_agent(
    *,
    api_base_url: str,
    public_base_url: str,
    admin_user: str,
    admin_password: str,
    model: str,
    backend: str,
    max_steps: int,
    ticks_per_step: int,
    server_artifacts_dir: str | None,
    poll_interval: float,
    timeout_seconds: int,
) -> dict[str, object]:
    created = _json_request(
        method="POST",
        base_url=api_base_url,
        path="/runs",
        payload={
            "backend": backend,
            "model": model,
            "max_steps": max_steps,
            "ticks_per_step": ticks_per_step,
        },
        admin_user=admin_user,
        admin_password=admin_password,
    )
    if not isinstance(created, dict) or not created.get("id"):
        raise RuntimeError(f"Run creation failed for {model}: {created}")

    run_id = str(created["id"])
    deadline = time.monotonic() + timeout_seconds
    latest = dict(created)
    while time.monotonic() < deadline:
        latest_payload = _json_request(
            method="GET",
            base_url=api_base_url,
            path=f"/runs/{run_id}",
            admin_user=admin_user,
            admin_password=admin_password,
        )
        if isinstance(latest_payload, dict):
            latest = latest_payload
        if latest.get("status") in TERMINAL_RUN_STATUSES:
            break
        time.sleep(poll_interval)

    public_run = _find_public_run(public_base_url, run_id) or {}
    token = public_run.get("token")
    records, trace_path = _load_trace_records(run_id, server_artifacts_dir)
    summary, summary_path = _load_summary(run_id, server_artifacts_dir)
    score = latest.get("score")
    if score is None:
        score = summary.get("total_score")
    return {
        "run_id": run_id,
        "model": model,
        "backend": backend,
        "status": latest.get("status"),
        "score": score,
        "summary_total_score": summary.get("total_score"),
        "summary_steps": summary.get("steps"),
        "duration_ticks": summary.get("duration_ticks"),
        "survival_score": summary.get("survival_score"),
        "public_token": token,
        "public_run_url": f"{public_base_url.rstrip('/')}/public/runs/{token}" if token else None,
        "public_replay_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/events/replay" if token else None,
        "public_trace_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/export/trace" if token else None,
        "leaderboard_url": f"{public_base_url.rstrip('/')}/leaderboard",
        "trace": trace_path,
        "summary": summary_path,
        "trace_steps": len(records),
        "actions": _summarize_actions(records),
    }


def _write_live_agent_packet(
    *,
    report: dict[str, object],
    packet_path: str | None,
    server_artifacts_dir: str | None,
) -> Path:
    runs = report.get("runs") if isinstance(report.get("runs"), dict) else {}
    model_run = runs.get("model") if isinstance(runs, dict) and isinstance(runs.get("model"), dict) else {}
    run_id = model_run.get("run_id") or "live-agent-report"
    if packet_path:
        target_path = Path(packet_path).expanduser().resolve()
    elif server_artifacts_dir:
        target_path = Path(server_artifacts_dir).expanduser().resolve() / str(run_id) / "live_agent_report.md"
    else:
        target_path = Path.cwd() / "live_agent_report.md"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    lines = [
        "# fort-gym live agent report",
        "",
        f"Generated: {generated_at}",
        f"Status: {'PASS' if report.get('ok') else 'FAIL'}",
        f"Result: `{comparison.get('result')}`",
        f"Score delta: `{comparison.get('score_delta')}`",
        "",
        "## Public URLs",
        "",
    ]
    for label in ("baseline", "model"):
        run = runs.get(label) if isinstance(runs, dict) and isinstance(runs.get(label), dict) else {}
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Run: `{run.get('run_id')}`",
                f"- Model: `{run.get('model')}`",
                f"- Status: `{run.get('status')}`",
                f"- Score: `{run.get('score')}`",
                f"- Public run: {run.get('public_run_url')}",
                f"- Public replay: {run.get('public_replay_url')}",
                f"- Trace export: {run.get('public_trace_url')}",
                f"- Local trace: `{run.get('trace')}`",
                f"- Local summary: `{run.get('summary')}`",
                "",
                "Actions:",
            ]
        )
        actions = run.get("actions") if isinstance(run.get("actions"), list) else []
        if not actions:
            lines.append("- none captured")
        for action in actions:
            if not isinstance(action, dict):
                continue
            lines.append(
                f"- step {action.get('step')}: {action.get('type')} "
                f"ticks={action.get('ticks_advanced')} score={action.get('score')} "
                f"intent={action.get('intent')!r}"
            )
        lines.append("")

    lines.extend(
        [
            "## JSON",
            "",
            "```json",
            json.dumps(report, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    target_path.write_text("\n".join(lines), encoding="utf-8")
    return target_path


@app.command("live-agent-report")
def live_agent_report(
    model: str = "anthropic-keystroke",
    baseline_model: str = "fake",
    backend: str = "dfhack",
    max_steps: int = 4,
    ticks_per_step: int = 10,
    api_base_url: str = "http://127.0.0.1:8000",
    public_base_url: str = "http://34.41.155.134",
    admin_user: str | None = None,
    admin_password: str | None = None,
    server_artifacts_dir: str | None = "/opt/fort-gym/fort_gym/artifacts",
    timeout_seconds: int = 600,
    poll_interval: float = 5.0,
    packet_path: str | None = None,
) -> None:
    """Run a baseline and real model through the public API, then compare scores."""

    resolved_user = admin_user or os.getenv("FORT_GYM_ADMIN_USER", "admin")
    resolved_password = admin_password or os.getenv("FORT_GYM_ADMIN_PASSWORD")
    if not resolved_password:
        typer.echo("FORT_GYM_ADMIN_PASSWORD or --admin-password is required.")
        raise typer.Exit(1)

    baseline = _run_api_agent(
        api_base_url=api_base_url,
        public_base_url=public_base_url,
        admin_user=resolved_user,
        admin_password=resolved_password,
        model=baseline_model,
        backend=backend,
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
        server_artifacts_dir=server_artifacts_dir,
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
    )
    model_result = _run_api_agent(
        api_base_url=api_base_url,
        public_base_url=public_base_url,
        admin_user=resolved_user,
        admin_password=resolved_password,
        model=model,
        backend=backend,
        max_steps=max_steps,
        ticks_per_step=ticks_per_step,
        server_artifacts_dir=server_artifacts_dir,
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
    )

    baseline_score = float(baseline.get("score") or 0.0)
    model_score = float(model_result.get("score") or 0.0)
    score_delta = round(model_score - baseline_score, 2)
    comparison = {
        "baseline_score": baseline_score,
        "model_score": model_score,
        "score_delta": score_delta,
        "result": "model_higher" if score_delta > 0 else "model_not_higher",
    }
    report = {
        "ok": baseline.get("status") == "completed" and model_result.get("status") == "completed",
        "comparison": comparison,
        "runs": {
            "baseline": baseline,
            "model": model_result,
        },
    }
    packet = _write_live_agent_packet(
        report=report,
        packet_path=packet_path,
        server_artifacts_dir=server_artifacts_dir,
    )
    report["packet"] = str(packet)
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
