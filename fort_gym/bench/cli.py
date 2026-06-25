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
DEFAULT_LIVE_AGENT_MODELS = "openrouter-keystroke-perception-review,openrouter-glm-5.2"
STATUS_MENU_KEYS = {"D_STATUS", "D_ANNOUNCE", "D_REPORTS", "STRING_A122"}
DESIGNATION_KEYS = {"D_DESIGNATE", "DESIGNATE_DIG"}


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


def _load_public_trace_records(public_base_url: str, token: str) -> tuple[list[dict[str, object]], str]:
    trace_url = f"{public_base_url.rstrip('/')}/public/runs/{token}/export/trace"
    with urlopen(Request(trace_url, headers={"User-Agent": "fort-gym-real-gameplay/1.0"}), timeout=90) as response:
        body = response.read().decode("utf-8")
    records = [json.loads(line) for line in body.splitlines() if line.strip()]
    return records, trace_url


def _public_run_result(
    *,
    public_base_url: str,
    token: str,
    records: list[dict[str, object]],
    run_payload: dict[str, object],
) -> dict[str, object]:
    actions = _summarize_actions(records)
    real_gameplay = _analyze_real_gameplay_trace(records, {})
    run_id = str(run_payload.get("run_id") or "")
    score = run_payload.get("score")
    if score is None:
        score = real_gameplay.get("final_trace_score")
    return {
        "run_id": run_id,
        "model": run_payload.get("model"),
        "backend": run_payload.get("backend"),
        "status": run_payload.get("status"),
        "score": score,
        "max_steps": run_payload.get("max_steps"),
        "step": run_payload.get("step"),
        "git_sha": run_payload.get("git_sha"),
        "public_token": token,
        "public_run_url": f"{public_base_url.rstrip('/')}/public/runs/{token}",
        "public_replay_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/events/replay",
        "public_trace_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/export/trace",
        "trace": f"{public_base_url.rstrip('/')}/public/runs/{token}/export/trace",
        "trace_steps": len(records),
        "actions": actions,
        "diagnostics": _diagnose_actions(actions, {}),
        "real_gameplay": real_gameplay,
    }


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


def _score_provenances(records: list[dict[str, object]]) -> list[str]:
    provenances: set[str] = set()
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        provenance = metrics.get("score_provenance")
        if provenance:
            provenances.add(str(provenance))
    return sorted(provenances)


PRODUCTIVE_STEP_FIELDS = (
    "ui_step_work_progress",
    "ui_step_excavation_progress",
    "ui_step_material_progress",
    "utility_action_progress",
)

CUMULATIVE_PROGRESS_FIELDS = (
    "completion_progress",
    "utility_progress",
    "production_progress",
    "complexity_progress",
    "ui_run_excavation_progress",
    "ui_run_material_progress",
    "ui_successful_targets",
    "manager_orders_count",
    "manager_orders_amount_left",
    "carpenter_workshops",
    "workshop_count",
)

SUMMARY_PROGRESS_DELTA_FIELDS = (
    "target_dig_designations_delta",
    "target_floor_tiles_delta",
    "target_wall_tiles_delta",
    "active_dig_jobs_delta",
    "manager_orders_delta",
    "manager_order_quantity_delta",
    "carpenter_workshops_delta",
    "production_workshops_delta",
    "complexity_floor_tiles_delta",
    "complexity_wall_tiles_delta",
    "complexity_spaces_delta",
)


def _record_tool_counts(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        events = record.get("events") if isinstance(record.get("events"), list) else []
        for event in events:
            if not isinstance(event, dict) or event.get("type") != "tool_call":
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            tool = str(data.get("tool") or "")
            if tool:
                counts[tool] = counts.get(tool, 0) + 1
    return counts


def _last_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    for record in reversed(records):
        metrics = record.get("metrics")
        if isinstance(metrics, dict):
            return metrics
    return {}


def _metric_max(records: list[dict[str, object]], field: str) -> int:
    value = 0
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        value = max(value, _as_int(metrics.get(field)))
    return value


def _metric_sum(records: list[dict[str, object]], field: str) -> int:
    total = 0
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        total += _as_int(metrics.get(field))
    return total


def _nested_metric_max(records: list[dict[str, object]], parent: str, field: str) -> int:
    value = 0
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        nested = metrics.get(parent)
        if isinstance(nested, dict):
            value = max(value, _as_int(nested.get(field)))
    return value


def _state_work_max(records: list[dict[str, object]], field: str) -> int:
    value = 0
    for record in records:
        for state_key in ("observation", "state_after_apply", "state_after_advance"):
            state = record.get(state_key)
            if not isinstance(state, dict):
                continue
            work = state.get("work")
            if isinstance(work, dict):
                value = max(value, _as_int(work.get(field)))
            ui_work = state.get("ui_work")
            if isinstance(ui_work, dict):
                value = max(value, _as_int(ui_work.get(field)))
    return value


def _final_stock(records: list[dict[str, object]], name: str) -> int:
    for record in reversed(records):
        state = record.get("state_after_advance")
        if isinstance(state, dict):
            stocks = state.get("stocks")
            if isinstance(stocks, dict) and name in stocks:
                return _as_int(stocks.get(name))
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        if name in metrics:
            return _as_int(metrics.get(name))
    return 0


def _record_action(record: dict[str, object]) -> dict[str, object]:
    action = record.get("action") if isinstance(record.get("action"), dict) else record.get("raw_action")
    return action if isinstance(action, dict) else {}


def _record_keys(record: dict[str, object]) -> set[str]:
    return _action_keys(_record_action(record))


def _record_intent(record: dict[str, object]) -> str:
    action = _record_action(record)
    intent = action.get("intent")
    return str(intent or "")


def _record_is_productive(
    record: dict[str, object],
    previous_metrics: dict[str, object] | None = None,
) -> bool:
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    if any(_as_int(metrics.get(field)) > 0 for field in PRODUCTIVE_STEP_FIELDS):
        return True
    previous_metrics = previous_metrics or {}
    for field in CUMULATIVE_PROGRESS_FIELDS:
        current = _as_int(metrics.get(field))
        previous = _as_int(previous_metrics.get(field))
        if current > previous:
            return True
    return False


def _record_is_workshop_attempt(record: dict[str, object]) -> bool:
    intent = _record_intent(record).lower()
    keys = _record_keys(record)
    return (
        "workshop" in intent
        or "leather works" in intent
        or "mason" in intent
        or "craftsdwarf" in intent
        or "carpenter" in intent
        or bool(keys.intersection({"HOTKEY_BUILDING_WORKSHOP", "HOTKEY_BUILDING_WORKSHOP_CARPENTER"}))
    )


def _record_is_menu_confused(record: dict[str, object]) -> bool:
    intent = _record_intent(record).lower()
    if "leather works" in intent and any(
        word in intent for word in ("craftsdwarf", "mason", "carpenter")
    ):
        return True
    if "craftsdwarf" in intent and "STRING_A114" in _record_keys(record):
        return True
    text = str(record.get("observation_text") or "").lower()
    return "leather works" in text and any(
        word in intent for word in ("craftsdwarf", "mason", "carpenter")
    )


def _longest_true_streak(values: list[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _analyze_real_gameplay_trace(
    records: list[dict[str, object]],
    summary: dict[str, object] | None = None,
) -> dict[str, object]:
    summary = summary or {}
    total_steps = len(records)
    productive_flags = []
    previous_metrics: dict[str, object] = {}
    for record in records:
        productive_flags.append(_record_is_productive(record, previous_metrics))
        metrics = record.get("metrics")
        previous_metrics = metrics if isinstance(metrics, dict) else {}
    workshop_flags = [_record_is_workshop_attempt(record) for record in records]
    no_progress_flags = [not productive for productive in productive_flags]
    workshop_no_progress_flags = [
        workshop and no_progress
        for workshop, no_progress in zip(workshop_flags, no_progress_flags)
    ]
    tool_counts = _record_tool_counts(records)
    final_metrics = _last_metrics(records)
    final_score = None
    for record in reversed(records):
        score = record.get("score")
        if isinstance(score, dict) and score.get("value") is not None:
            final_score = _as_float(score.get("value"))
            break
    if final_score is None:
        final_score = _as_float(summary.get("total_score"), default=0.0)

    positive_tick_steps = 0
    zero_tick_steps = 0
    ticks_advanced = 0
    for record in records:
        tick_advance = record.get("tick_advance")
        if isinstance(tick_advance, dict):
            ticks = _as_int(tick_advance.get("ticks_advanced"))
        else:
            action = _record_action(record)
            ticks = _as_int(action.get("advance_ticks"))
        ticks_advanced += ticks
        if ticks > 0:
            positive_tick_steps += 1
        else:
            zero_tick_steps += 1

    final_carpenter_workshops = max(
        _as_int(summary.get("carpenter_workshops")),
        _as_int(final_metrics.get("carpenter_workshops")),
        _metric_max(records, "carpenter_workshops"),
        _nested_metric_max(records, "work", "carpenter_workshops"),
        _nested_metric_max(records, "ui_work", "carpenter_workshops"),
        _state_work_max(records, "carpenter_workshops"),
    )
    final_completed_spaces = max(
        _as_int(summary.get("fortress_complexity_spaces_completed")),
        _as_int(final_metrics.get("fortress_complexity_spaces_completed")),
        _metric_max(records, "fortress_complexity_spaces_completed"),
        _nested_metric_max(records, "work", "fortress_complexity_spaces_completed"),
    )
    final_wood = max(_final_stock(records, "wood"), _as_int(summary.get("wood")))
    final_stone = max(_final_stock(records, "stone"), _as_int(summary.get("stone")))
    ui_material_progress = max(
        _as_int(summary.get("ui_material_progress")),
        _metric_max(records, "ui_run_material_progress"),
        _metric_sum(records, "ui_step_material_progress"),
    )
    ui_excavation_progress = max(
        _as_int(summary.get("ui_excavation_progress")),
        _metric_max(records, "ui_run_excavation_progress"),
        _metric_sum(records, "ui_step_excavation_progress"),
    )
    utility_progress = max(
        _as_int(summary.get("utility_progress")),
        _metric_max(records, "utility_progress"),
        _metric_sum(records, "utility_action_progress"),
    )
    production_progress = max(
        _as_int(summary.get("production_progress")),
        _metric_max(records, "production_progress"),
        _metric_sum(records, "production_workshops_delta"),
        _metric_sum(records, "carpenter_workshops_delta"),
    )
    completion_progress = max(
        _as_int(summary.get("completion_progress")),
        _metric_max(records, "completion_progress"),
        _metric_sum(records, "ui_step_work_progress"),
    )
    complexity_progress = max(
        _as_int(summary.get("complexity_progress")),
        _metric_max(records, "complexity_progress"),
        _metric_sum(records, "complexity_spaces_delta"),
    )
    chain = {
        "dug_or_designated": ui_excavation_progress > 0 or completion_progress > 0,
        "material_acquired": ui_material_progress > 0 or final_wood > 3 or final_stone > 0,
        "workshop_built": final_carpenter_workshops > 0 or production_progress > 0,
        "utility_created": utility_progress > 0,
        "fortress_space_completed": final_completed_spaces > 0 or complexity_progress > 0,
    }
    chain_stage_count = sum(1 for ok in chain.values() if ok)

    blockers: list[str] = []
    max_no_progress_streak = _longest_true_streak(no_progress_flags)
    max_workshop_loop_streak = _longest_true_streak(workshop_no_progress_flags)
    workshop_no_progress_steps = sum(1 for value in workshop_no_progress_flags if value)
    menu_confusion_steps = sum(1 for record in records if _record_is_menu_confused(record))
    screen_read_steps = sum(
        1 for record in records if isinstance(_record_action(record).get("screen_read"), dict)
    )
    last_action_review_steps = sum(
        1
        for record in records
        if isinstance(_record_action(record).get("last_action_review"), dict)
    )
    failed_attempt_writes = _as_int(tool_counts.get("remember_failed_attempt"))
    if max_no_progress_streak >= 5:
        blockers.append("repeated_no_progress_loop")
    if max_workshop_loop_streak >= 3 or workshop_no_progress_steps >= 5:
        blockers.append("workshop_placement_loop")
    if menu_confusion_steps:
        blockers.append("menu_key_confusion")
    if failed_attempt_writes == 0 and max_no_progress_streak >= 3:
        blockers.append("no_failed_attempt_memory")
    if not chain["material_acquired"]:
        blockers.append("no_material_acquired")
    if not chain["workshop_built"]:
        blockers.append("no_workshop_built")
    if not chain["fortress_space_completed"]:
        blockers.append("no_fortress_space_completed")

    productive_steps = sum(1 for value in productive_flags if value)
    return {
        "steps": total_steps,
        "final_trace_score": final_score,
        "productive_steps": productive_steps,
        "productive_action_rate": round(productive_steps / total_steps, 3) if total_steps else 0.0,
        "no_progress_steps": sum(1 for value in no_progress_flags if value),
        "max_no_progress_streak": max_no_progress_streak,
        "workshop_attempt_steps": sum(1 for value in workshop_flags if value),
        "workshop_no_progress_steps": workshop_no_progress_steps,
        "max_workshop_loop_streak": max_workshop_loop_streak,
        "menu_confusion_steps": menu_confusion_steps,
        "positive_tick_steps": positive_tick_steps,
        "zero_tick_steps": zero_tick_steps,
        "ticks_advanced": ticks_advanced,
        "tool_counts": tool_counts,
        "memory_review_calls": _as_int(tool_counts.get("query_memory")),
        "memory_review_rate": (
            round(_as_int(tool_counts.get("query_memory")) / total_steps, 3)
            if total_steps
            else 0.0
        ),
        "plan_writes": _as_int(tool_counts.get("write_gameplay_plan")),
        "plan_reviews": _as_int(tool_counts.get("review_gameplay_plan")),
        "plan_review_rate": (
            round(_as_int(tool_counts.get("review_gameplay_plan")) / total_steps, 3)
            if total_steps
            else 0.0
        ),
        "plan_gate_warnings": _as_int(tool_counts.get("plan_review_gate_warning")),
        "screen_read_steps": screen_read_steps,
        "screen_read_rate": round(screen_read_steps / total_steps, 3) if total_steps else 0.0,
        "last_action_review_steps": last_action_review_steps,
        "last_action_review_rate": (
            round(last_action_review_steps / total_steps, 3) if total_steps else 0.0
        ),
        "poi_writes": _as_int(tool_counts.get("remember_poi")),
        "failed_attempt_writes": failed_attempt_writes,
        "df_wiki_calls": _as_int(tool_counts.get("df_wiki")),
        "chain": chain,
        "chain_stage_count": chain_stage_count,
        "final_state": {
            "wood": final_wood,
            "stone": final_stone,
            "carpenter_workshops": final_carpenter_workshops,
            "completed_spaces": final_completed_spaces,
            "completion_progress": completion_progress,
            "utility_progress": utility_progress,
            "production_progress": production_progress,
            "complexity_progress": complexity_progress,
            "ui_excavation_progress": ui_excavation_progress,
            "ui_material_progress": ui_material_progress,
        },
        "blockers": blockers,
    }


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[midpoint], 2)
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2.0, 2)


def _split_models(models: str) -> list[str]:
    return [item.strip() for item in models.split(",") if item.strip()]


def _action_keys(action: dict[str, object]) -> set[str]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    keys = params.get("keys") if isinstance(params, dict) else None
    if not isinstance(keys, list):
        return set()
    return {str(key) for key in keys}


def _diagnose_actions(
    actions: list[dict[str, object]],
    summary: dict[str, object],
) -> dict[str, object]:
    total_actions = len(actions)
    invalid_actions = sum(1 for action in actions if action.get("valid") is False)
    accepted_actions = sum(1 for action in actions if action.get("accepted") is True)
    ticks_advanced = sum(_as_int(action.get("ticks_advanced")) for action in actions)
    designation_attempts = 0
    utility_attempts = 0
    production_attempts = 0
    complexity_attempts = 0
    status_menu_actions = 0
    for action in actions:
        action_type = action.get("type")
        keys = _action_keys(action)
        if action_type == "DIG" or keys.intersection(DESIGNATION_KEYS):
            designation_attempts += 1
        if action_type == "DIG":
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            area = params.get("area")
            if isinstance(area, (list, tuple)) and list(area[:3]) != [50, 35, 0]:
                complexity_attempts += 1
        if action_type in {"BUILD", "ORDER"}:
            utility_attempts += 1
        if action_type == "BUILD":
            production_attempts += 1
        if keys.intersection(STATUS_MENU_KEYS):
            status_menu_actions += 1

    blockers = []
    if invalid_actions:
        blockers.append("invalid_actions")
    if accepted_actions == 0 and total_actions:
        blockers.append("no_accepted_actions")
    if designation_attempts == 0:
        blockers.append("no_dig_designation")
    if designation_attempts and ticks_advanced == 0:
        blockers.append("designation_without_time")
    if status_menu_actions:
        blockers.append("status_menu_exploration")
    if _as_int(summary.get("duration_ticks")) > 0 and designation_attempts == 0:
        blockers.append("score_from_survival_without_work")
    work_progress = _as_int(summary.get("work_progress"))
    ui_work_progress = _as_int(summary.get("ui_work_progress"))
    ui_excavation_progress = _as_int(summary.get("ui_excavation_progress"))
    completion_progress = _as_int(summary.get("completion_progress"))
    utility_progress = _as_int(summary.get("utility_progress"))
    production_progress = _as_int(summary.get("production_progress"))
    complexity_progress = _as_int(summary.get("complexity_progress"))
    target_floor_tiles_delta = _as_int(summary.get("target_floor_tiles_delta"))
    target_wall_tiles_delta = _as_int(summary.get("target_wall_tiles_delta"))
    if _as_int(summary.get("duration_ticks")) > 0 and work_progress == 0:
        blockers.append("tick_only_score")
    if work_progress > 0 and completion_progress == 0:
        blockers.append("no_mining_progress")
    if work_progress > 0 and completion_progress == 0 and _as_int(summary.get("target_hidden_tiles")) > 0:
        blockers.append("target_tiles_hidden")
    if work_progress > 0 and completion_progress == 0 and _as_int(summary.get("citizens_on_target_z")) == 0:
        blockers.append("target_z_has_no_citizens")
    if completion_progress >= 25 and utility_attempts == 0:
        blockers.append("completed_room_without_utility_action")
    if completion_progress >= 25 and utility_progress == 0:
        blockers.append("completed_room_without_utility_progress")
    if completion_progress >= 25 and production_attempts == 0:
        blockers.append("completed_room_without_production_action")
    if completion_progress >= 25 and production_progress == 0:
        blockers.append("completed_room_without_production_progress")
    if production_progress > 0 and complexity_attempts == 0:
        blockers.append("production_without_complexity_action")
    if production_progress > 0 and complexity_progress == 0:
        blockers.append("production_without_complexity_progress")

    invalid_rate = round(invalid_actions / total_actions, 3) if total_actions else 0.0
    return {
        "steps": total_actions,
        "accepted_actions": accepted_actions,
        "invalid_actions": invalid_actions,
        "invalid_action_rate": invalid_rate,
        "ticks_advanced": ticks_advanced,
        "designation_attempts": designation_attempts,
        "utility_attempts": utility_attempts,
        "production_attempts": production_attempts,
        "complexity_attempts": complexity_attempts,
        "status_menu_actions": status_menu_actions,
        "work_score": _as_float(summary.get("work_score")),
        "completion_score": _as_float(summary.get("completion_score")),
        "utility_score": _as_float(summary.get("utility_score")),
        "production_score": _as_float(summary.get("production_score")),
        "complexity_score": _as_float(summary.get("complexity_score")),
        "work_progress": work_progress,
        "ui_work_progress": ui_work_progress,
        "ui_excavation_progress": ui_excavation_progress,
        "designation_progress": _as_int(summary.get("designation_progress")),
        "completion_progress": completion_progress,
        "utility_progress": utility_progress,
        "production_progress": production_progress,
        "complexity_progress": complexity_progress,
        "target_dig_designations_delta": _as_int(summary.get("target_dig_designations_delta")),
        "target_floor_tiles_delta": target_floor_tiles_delta,
        "target_wall_tiles_delta": target_wall_tiles_delta,
        "active_dig_jobs_delta": _as_int(summary.get("active_dig_jobs_delta")),
        "utility_action_progress": _as_int(summary.get("utility_action_progress")),
        "complexity_floor_tiles_delta": _as_int(summary.get("complexity_floor_tiles_delta")),
        "complexity_wall_tiles_delta": _as_int(summary.get("complexity_wall_tiles_delta")),
        "complexity_spaces_delta": _as_int(summary.get("complexity_spaces_delta")),
        "manager_orders_delta": _as_int(summary.get("manager_orders_delta")),
        "manager_order_quantity_delta": _as_int(summary.get("manager_order_quantity_delta")),
        "carpenter_workshops_delta": _as_int(summary.get("carpenter_workshops_delta")),
        "production_workshops_delta": _as_int(summary.get("production_workshops_delta")),
        "manager_orders_count": _as_int(summary.get("manager_orders_count")),
        "manager_orders_amount_left": _as_int(summary.get("manager_orders_amount_left")),
        "carpenter_workshops": _as_int(summary.get("carpenter_workshops")),
        "fortress_complexity_floor_tiles": _as_int(summary.get("fortress_complexity_floor_tiles")),
        "fortress_complexity_spaces_completed": _as_int(
            summary.get("fortress_complexity_spaces_completed")
        ),
        "target_hidden_tiles": _as_int(summary.get("target_hidden_tiles")),
        "citizens_total": _as_int(summary.get("citizens_total")),
        "miners_total": _as_int(summary.get("miners_total")),
        "citizens_on_target_z": _as_int(summary.get("citizens_on_target_z")),
        "blockers": blockers,
    }


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
    preserve_save: bool = False,
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
            "preserve_save": preserve_save,
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
    if not records and token:
        records, trace_path = _load_public_trace_records(public_base_url, str(token))
    summary, summary_path = _load_summary(run_id, server_artifacts_dir)
    actions = _summarize_actions(records)
    score_provenances = _score_provenances(records)
    real_gameplay = _analyze_real_gameplay_trace(records, summary)
    score = latest.get("score")
    if score is None:
        score = summary.get("total_score")
    return {
        "run_id": run_id,
        "model": model,
        "backend": backend,
        "preserve_save": preserve_save,
        "status": latest.get("status"),
        "score": score,
        "summary_total_score": summary.get("total_score"),
        "summary_steps": summary.get("steps"),
        "duration_ticks": summary.get("duration_ticks"),
        "survival_score": summary.get("survival_score"),
        "work_score": summary.get("work_score"),
        "completion_score": summary.get("completion_score"),
        "utility_score": summary.get("utility_score"),
        "production_score": summary.get("production_score"),
        "complexity_score": summary.get("complexity_score"),
        "work_progress": summary.get("work_progress"),
        "ui_work_progress": summary.get("ui_work_progress"),
        "ui_excavation_progress": summary.get("ui_excavation_progress"),
        "ui_score_provenance_seen": "keystroke_ui_work_rect" in score_provenances,
        "score_provenances": score_provenances,
        "designation_progress": summary.get("designation_progress"),
        "completion_progress": summary.get("completion_progress"),
        "utility_progress": summary.get("utility_progress"),
        "production_progress": summary.get("production_progress"),
        "complexity_progress": summary.get("complexity_progress"),
        "target_dig_designations_delta": summary.get("target_dig_designations_delta"),
        "ui_target_floor_removed_delta": summary.get("ui_target_floor_removed_delta"),
        "target_floor_tiles_delta": summary.get("target_floor_tiles_delta"),
        "target_wall_tiles_delta": summary.get("target_wall_tiles_delta"),
        "active_dig_jobs_delta": summary.get("active_dig_jobs_delta"),
        "utility_action_progress": summary.get("utility_action_progress"),
        "complexity_floor_tiles_delta": summary.get("complexity_floor_tiles_delta"),
        "complexity_wall_tiles_delta": summary.get("complexity_wall_tiles_delta"),
        "complexity_spaces_delta": summary.get("complexity_spaces_delta"),
        "manager_orders_delta": summary.get("manager_orders_delta"),
        "manager_order_quantity_delta": summary.get("manager_order_quantity_delta"),
        "carpenter_workshops_delta": summary.get("carpenter_workshops_delta"),
        "production_workshops_delta": summary.get("production_workshops_delta"),
        "manager_orders_count": summary.get("manager_orders_count"),
        "manager_orders_amount_left": summary.get("manager_orders_amount_left"),
        "carpenter_workshops": summary.get("carpenter_workshops"),
        "fortress_plan_name": summary.get("fortress_plan_name"),
        "fortress_connector_floor_tiles": summary.get("fortress_connector_floor_tiles"),
        "fortress_workshop_room_floor_tiles": summary.get("fortress_workshop_room_floor_tiles"),
        "fortress_complexity_floor_tiles": summary.get("fortress_complexity_floor_tiles"),
        "fortress_complexity_spaces_completed": summary.get(
            "fortress_complexity_spaces_completed"
        ),
        "target_hidden_tiles": summary.get("target_hidden_tiles"),
        "citizens_total": summary.get("citizens_total"),
        "miners_total": summary.get("miners_total"),
        "citizens_on_target_z": summary.get("citizens_on_target_z"),
        "public_token": token,
        "public_run_url": f"{public_base_url.rstrip('/')}/public/runs/{token}" if token else None,
        "public_replay_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/events/replay" if token else None,
        "public_trace_url": f"{public_base_url.rstrip('/')}/public/runs/{token}/export/trace" if token else None,
        "leaderboard_url": f"{public_base_url.rstrip('/')}/leaderboard",
        "trace": trace_path,
        "summary": summary_path,
        "trace_steps": len(records),
        "actions": actions,
        "diagnostics": _diagnose_actions(actions, summary),
        "real_gameplay": real_gameplay,
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


def _real_gameplay_metrics(run: dict[str, object]) -> dict[str, object]:
    value = run.get("real_gameplay")
    return value if isinstance(value, dict) else {}


def _build_real_gameplay_comparison(
    baseline: dict[str, object],
    variant: dict[str, object],
) -> dict[str, object]:
    base = _real_gameplay_metrics(baseline)
    new = _real_gameplay_metrics(variant)
    score_delta = round(_as_float(variant.get("score")) - _as_float(baseline.get("score")), 2)
    chain_delta = _as_int(new.get("chain_stage_count")) - _as_int(base.get("chain_stage_count"))
    productive_delta = _as_int(new.get("productive_steps")) - _as_int(base.get("productive_steps"))
    no_progress_delta = _as_int(new.get("no_progress_steps")) - _as_int(base.get("no_progress_steps"))
    workshop_loop_delta = _as_int(new.get("workshop_no_progress_steps")) - _as_int(
        base.get("workshop_no_progress_steps")
    )
    max_loop_delta = _as_int(new.get("max_no_progress_streak")) - _as_int(
        base.get("max_no_progress_streak")
    )
    improved = (
        chain_delta > 0
        or (
            chain_delta == 0
            and productive_delta > 0
            and no_progress_delta <= 0
            and workshop_loop_delta <= 0
        )
    )
    return {
        "baseline_score": _as_float(baseline.get("score")),
        "variant_score": _as_float(variant.get("score")),
        "score_delta": score_delta,
        "baseline_chain_stage_count": _as_int(base.get("chain_stage_count")),
        "variant_chain_stage_count": _as_int(new.get("chain_stage_count")),
        "chain_stage_delta": chain_delta,
        "productive_steps_delta": productive_delta,
        "no_progress_steps_delta": no_progress_delta,
        "workshop_no_progress_steps_delta": workshop_loop_delta,
        "max_no_progress_streak_delta": max_loop_delta,
        "baseline_blockers": base.get("blockers", []),
        "variant_blockers": new.get("blockers", []),
        "result": "variant_real_gameplay_higher" if improved else "needs_more_hardening",
    }


def _write_real_gameplay_experiment_artifacts(
    *,
    report: dict[str, object],
    packet_path: str | None,
    server_artifacts_dir: str | None,
) -> tuple[Path, Path]:
    runs = report.get("runs") if isinstance(report.get("runs"), dict) else {}
    variant = runs.get("variant") if isinstance(runs.get("variant"), dict) else {}
    run_id = str(variant.get("run_id") or "real-gameplay-experiment")
    if packet_path:
        markdown_path = Path(packet_path).expanduser().resolve()
        target_dir = markdown_path.parent
    elif server_artifacts_dir:
        target_dir = Path(server_artifacts_dir).expanduser().resolve() / str(run_id)
        markdown_path = target_dir / "real_gameplay_experiment.md"
    else:
        target_dir = Path.cwd() / str(run_id)
        markdown_path = target_dir / "real_gameplay_experiment.md"
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "real_gameplay_experiment.json"
    report["packet"] = str(markdown_path)
    report["json"] = str(json_path)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    baseline = runs.get("baseline") if isinstance(runs.get("baseline"), dict) else {}
    baseline_gameplay = _real_gameplay_metrics(baseline)
    variant_gameplay = _real_gameplay_metrics(variant)
    lines = [
        "# fort-gym real gameplay experiment",
        "",
        f"Generated: {generated_at}",
        f"Status: {'PASS' if report.get('ok') else 'FAIL'}",
        f"Result: `{comparison.get('result')}`",
        f"Score delta: `{comparison.get('score_delta')}`",
        f"Chain stage delta: `{comparison.get('chain_stage_delta')}`",
        f"Productive steps delta: `{comparison.get('productive_steps_delta')}`",
        f"No-progress steps delta: `{comparison.get('no_progress_steps_delta')}`",
        f"Workshop no-progress delta: `{comparison.get('workshop_no_progress_steps_delta')}`",
        "",
        "## Baseline",
        "",
        f"- Run: `{baseline.get('run_id')}`",
        f"- Model: `{baseline.get('model')}`",
        f"- Score: `{baseline.get('score')}`",
        f"- Replay: {baseline.get('public_replay_url')}",
        f"- Real gameplay: `{baseline_gameplay}`",
        "",
        "## Variant",
        "",
        f"- Run: `{variant.get('run_id')}`",
        f"- Model: `{variant.get('model')}`",
        f"- Score: `{variant.get('score')}`",
        f"- Replay: {variant.get('public_replay_url')}",
        f"- Real gameplay: `{variant_gameplay}`",
        "",
        "## JSON",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=True),
        "```",
        "",
    ]
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, json_path


def _score_values(runs: list[dict[str, object]]) -> list[float]:
    return [_as_float(run.get("score")) for run in runs if run.get("score") is not None]


def _completed_runs(runs: list[dict[str, object]]) -> int:
    return sum(1 for run in runs if run.get("status") == "completed")


def _public_url_for_extreme(
    runs: list[dict[str, object]],
    *,
    reverse: bool,
) -> str | None:
    scored = [run for run in runs if run.get("score") is not None]
    if not scored:
        return None
    chosen = sorted(scored, key=lambda run: _as_float(run.get("score")), reverse=reverse)[0]
    url = chosen.get("public_run_url")
    return str(url) if url else None


def _merge_diagnostics(runs: list[dict[str, object]]) -> dict[str, object]:
    totals = {
        "accepted_actions": 0,
        "invalid_actions": 0,
        "ticks_advanced": 0,
        "designation_attempts": 0,
        "utility_attempts": 0,
        "production_attempts": 0,
        "complexity_attempts": 0,
        "status_menu_actions": 0,
        "work_progress": 0,
        "ui_work_progress": 0,
        "designation_progress": 0,
        "completion_progress": 0,
        "utility_progress": 0,
        "production_progress": 0,
        "complexity_progress": 0,
        "target_dig_designations_delta": 0,
        "target_floor_tiles_delta": 0,
        "target_wall_tiles_delta": 0,
        "active_dig_jobs_delta": 0,
        "utility_action_progress": 0,
        "complexity_floor_tiles_delta": 0,
        "complexity_wall_tiles_delta": 0,
        "complexity_spaces_delta": 0,
        "manager_orders_delta": 0,
        "manager_order_quantity_delta": 0,
        "carpenter_workshops_delta": 0,
        "production_workshops_delta": 0,
        "manager_orders_count": 0,
        "manager_orders_amount_left": 0,
        "carpenter_workshops": 0,
        "fortress_complexity_floor_tiles": 0,
        "fortress_complexity_spaces_completed": 0,
        "target_hidden_tiles": 0,
        "citizens_total": 0,
        "miners_total": 0,
        "citizens_on_target_z": 0,
    }
    work_score_total = 0.0
    completion_score_total = 0.0
    utility_score_total = 0.0
    production_score_total = 0.0
    complexity_score_total = 0.0
    blockers: dict[str, int] = {}
    steps = 0
    for run in runs:
        diagnostics = run.get("diagnostics") if isinstance(run.get("diagnostics"), dict) else {}
        steps += _as_int(diagnostics.get("steps"))
        for key in totals:
            totals[key] += _as_int(diagnostics.get(key))
        work_score_total += _as_float(diagnostics.get("work_score"))
        completion_score_total += _as_float(diagnostics.get("completion_score"))
        utility_score_total += _as_float(diagnostics.get("utility_score"))
        production_score_total += _as_float(diagnostics.get("production_score"))
        complexity_score_total += _as_float(diagnostics.get("complexity_score"))
        for blocker in diagnostics.get("blockers", []) if isinstance(diagnostics.get("blockers"), list) else []:
            blocker_name = str(blocker)
            blockers[blocker_name] = blockers.get(blocker_name, 0) + 1
    invalid_rate = round(totals["invalid_actions"] / steps, 3) if steps else 0.0
    return {
        "steps": steps,
        **totals,
        "work_score_total": round(work_score_total, 2),
        "completion_score_total": round(completion_score_total, 2),
        "utility_score_total": round(utility_score_total, 2),
        "production_score_total": round(production_score_total, 2),
        "complexity_score_total": round(complexity_score_total, 2),
        "invalid_action_rate": invalid_rate,
        "blockers": blockers,
    }


def _merge_real_gameplay(runs: list[dict[str, object]]) -> dict[str, object]:
    analyses = [
        run.get("real_gameplay")
        for run in runs
        if isinstance(run.get("real_gameplay"), dict)
    ]
    if not analyses:
        return {}
    tool_counts: dict[str, int] = {}
    blockers: dict[str, int] = {}
    for analysis in analyses:
        counts = analysis.get("tool_counts") if isinstance(analysis.get("tool_counts"), dict) else {}
        for tool, count in counts.items():
            tool_counts[str(tool)] = tool_counts.get(str(tool), 0) + _as_int(count)
        for blocker in analysis.get("blockers", []) if isinstance(analysis.get("blockers"), list) else []:
            name = str(blocker)
            blockers[name] = blockers.get(name, 0) + 1
    return {
        "runs": len(analyses),
        "median_productive_action_rate": _median(
            [_as_float(analysis.get("productive_action_rate")) for analysis in analyses]
        ),
        "median_productive_steps": _median(
            [_as_float(analysis.get("productive_steps")) for analysis in analyses]
        ),
        "median_no_progress_steps": _median(
            [_as_float(analysis.get("no_progress_steps")) for analysis in analyses]
        ),
        "max_no_progress_streak": max(_as_int(analysis.get("max_no_progress_streak")) for analysis in analyses),
        "workshop_no_progress_steps": sum(_as_int(analysis.get("workshop_no_progress_steps")) for analysis in analyses),
        "menu_confusion_steps": sum(_as_int(analysis.get("menu_confusion_steps")) for analysis in analyses),
        "median_memory_review_rate": _median(
            [_as_float(analysis.get("memory_review_rate")) for analysis in analyses]
        ),
        "poi_writes": sum(_as_int(analysis.get("poi_writes")) for analysis in analyses),
        "failed_attempt_writes": sum(
            _as_int(analysis.get("failed_attempt_writes")) for analysis in analyses
        ),
        "best_chain_stage_count": max(_as_int(analysis.get("chain_stage_count")) for analysis in analyses),
        "tool_counts": tool_counts,
        "blockers": blockers,
    }


def _variant_scorecard(
    *,
    model: str,
    runs: list[dict[str, object]],
    baseline_median: float,
) -> dict[str, object]:
    scores = _score_values(runs)
    work_scores = [_as_float(run.get("work_score")) for run in runs if run.get("work_score") is not None]
    work_progress = [_as_float(run.get("work_progress")) for run in runs if run.get("work_progress") is not None]
    ui_work_progress = [
        _as_float(run.get("ui_work_progress"))
        for run in runs
        if run.get("ui_work_progress") is not None
    ]
    ui_score_provenance_runs = sum(1 for run in runs if run.get("ui_score_provenance_seen"))
    completion_scores = [
        _as_float(run.get("completion_score")) for run in runs if run.get("completion_score") is not None
    ]
    completion_progress = [
        _as_float(run.get("completion_progress")) for run in runs if run.get("completion_progress") is not None
    ]
    utility_scores = [
        _as_float(run.get("utility_score")) for run in runs if run.get("utility_score") is not None
    ]
    utility_progress = [
        _as_float(run.get("utility_progress")) for run in runs if run.get("utility_progress") is not None
    ]
    production_scores = [
        _as_float(run.get("production_score"))
        for run in runs
        if run.get("production_score") is not None
    ]
    production_progress = [
        _as_float(run.get("production_progress"))
        for run in runs
        if run.get("production_progress") is not None
    ]
    complexity_scores = [
        _as_float(run.get("complexity_score"))
        for run in runs
        if run.get("complexity_score") is not None
    ]
    complexity_progress = [
        _as_float(run.get("complexity_progress"))
        for run in runs
        if run.get("complexity_progress") is not None
    ]
    median_score = _median(scores)
    return {
        "model": model,
        "runs": len(runs),
        "completed_runs": _completed_runs(runs),
        "scores": scores,
        "median_score": median_score,
        "median_delta_vs_baseline": round(median_score - baseline_median, 2),
        "work_scores": work_scores,
        "median_work_score": _median(work_scores),
        "work_progress": work_progress,
        "median_work_progress": _median(work_progress),
        "ui_work_progress": ui_work_progress,
        "median_ui_work_progress": _median(ui_work_progress),
        "ui_score_provenance_runs": ui_score_provenance_runs,
        "completion_scores": completion_scores,
        "median_completion_score": _median(completion_scores),
        "completion_progress": completion_progress,
        "median_completion_progress": _median(completion_progress),
        "utility_scores": utility_scores,
        "median_utility_score": _median(utility_scores),
        "utility_progress": utility_progress,
        "median_utility_progress": _median(utility_progress),
        "production_scores": production_scores,
        "median_production_score": _median(production_scores),
        "production_progress": production_progress,
        "median_production_progress": _median(production_progress),
        "complexity_scores": complexity_scores,
        "median_complexity_score": _median(complexity_scores),
        "complexity_progress": complexity_progress,
        "median_complexity_progress": _median(complexity_progress),
        "best_run_url": _public_url_for_extreme(runs, reverse=True),
        "worst_run_url": _public_url_for_extreme(runs, reverse=False),
        "diagnostics": _merge_diagnostics(runs),
        "real_gameplay": _merge_real_gameplay(runs),
    }


def _build_suite_comparison(
    *,
    baseline_runs: list[dict[str, object]],
    variant_runs: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    baseline_scores = _score_values(baseline_runs)
    baseline_work_scores = [
        _as_float(run.get("work_score")) for run in baseline_runs if run.get("work_score") is not None
    ]
    baseline_work_progress = [
        _as_float(run.get("work_progress")) for run in baseline_runs if run.get("work_progress") is not None
    ]
    baseline_ui_work_progress = [
        _as_float(run.get("ui_work_progress"))
        for run in baseline_runs
        if run.get("ui_work_progress") is not None
    ]
    baseline_ui_score_provenance_runs = sum(
        1 for run in baseline_runs if run.get("ui_score_provenance_seen")
    )
    baseline_completion_scores = [
        _as_float(run.get("completion_score"))
        for run in baseline_runs
        if run.get("completion_score") is not None
    ]
    baseline_completion_progress = [
        _as_float(run.get("completion_progress"))
        for run in baseline_runs
        if run.get("completion_progress") is not None
    ]
    baseline_utility_scores = [
        _as_float(run.get("utility_score"))
        for run in baseline_runs
        if run.get("utility_score") is not None
    ]
    baseline_utility_progress = [
        _as_float(run.get("utility_progress"))
        for run in baseline_runs
        if run.get("utility_progress") is not None
    ]
    baseline_production_scores = [
        _as_float(run.get("production_score"))
        for run in baseline_runs
        if run.get("production_score") is not None
    ]
    baseline_production_progress = [
        _as_float(run.get("production_progress"))
        for run in baseline_runs
        if run.get("production_progress") is not None
    ]
    baseline_complexity_scores = [
        _as_float(run.get("complexity_score"))
        for run in baseline_runs
        if run.get("complexity_score") is not None
    ]
    baseline_complexity_progress = [
        _as_float(run.get("complexity_progress"))
        for run in baseline_runs
        if run.get("complexity_progress") is not None
    ]
    baseline_median = _median(baseline_scores)
    variants = [
        _variant_scorecard(
            model=model,
            runs=runs,
            baseline_median=baseline_median,
        )
        for model, runs in variant_runs.items()
    ]
    best_variant = None
    if variants:
        best_variant = sorted(
            variants,
            key=lambda item: _as_float(item.get("median_delta_vs_baseline")),
            reverse=True,
        )[0]
    best_delta = _as_float(best_variant.get("median_delta_vs_baseline")) if best_variant else 0.0
    return {
        "baseline": {
            "model": baseline_runs[0].get("model") if baseline_runs else None,
            "runs": len(baseline_runs),
            "completed_runs": _completed_runs(baseline_runs),
            "scores": baseline_scores,
            "median_score": baseline_median,
            "work_scores": baseline_work_scores,
            "median_work_score": _median(baseline_work_scores),
            "work_progress": baseline_work_progress,
            "median_work_progress": _median(baseline_work_progress),
            "ui_work_progress": baseline_ui_work_progress,
            "median_ui_work_progress": _median(baseline_ui_work_progress),
            "ui_score_provenance_runs": baseline_ui_score_provenance_runs,
            "completion_scores": baseline_completion_scores,
            "median_completion_score": _median(baseline_completion_scores),
            "completion_progress": baseline_completion_progress,
            "median_completion_progress": _median(baseline_completion_progress),
            "utility_scores": baseline_utility_scores,
            "median_utility_score": _median(baseline_utility_scores),
            "utility_progress": baseline_utility_progress,
            "median_utility_progress": _median(baseline_utility_progress),
            "production_scores": baseline_production_scores,
            "median_production_score": _median(baseline_production_scores),
            "production_progress": baseline_production_progress,
            "median_production_progress": _median(baseline_production_progress),
            "complexity_scores": baseline_complexity_scores,
            "median_complexity_score": _median(baseline_complexity_scores),
            "complexity_progress": baseline_complexity_progress,
            "median_complexity_progress": _median(baseline_complexity_progress),
            "best_run_url": _public_url_for_extreme(baseline_runs, reverse=True),
            "worst_run_url": _public_url_for_extreme(baseline_runs, reverse=False),
            "diagnostics": _merge_diagnostics(baseline_runs),
            "real_gameplay": _merge_real_gameplay(baseline_runs),
        },
        "variants": variants,
        "best_model": best_variant.get("model") if best_variant else None,
        "best_median_delta": best_delta,
        "result": "variant_higher" if best_delta > 0 else "no_variant_higher",
    }


def _suite_progress_gate(comparison: dict[str, object]) -> dict[str, object]:
    variants = comparison.get("variants") if isinstance(comparison.get("variants"), list) else []
    passing_models: list[str] = []
    model_progress: list[dict[str, object]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        completion_progress = _as_float(variant.get("median_completion_progress"))
        utility_progress = _as_float(variant.get("median_utility_progress"))
        production_progress = _as_float(variant.get("median_production_progress"))
        complexity_progress = _as_float(variant.get("median_complexity_progress"))
        model = str(variant.get("model") or "")
        passes = (
            completion_progress > 0
            and utility_progress > 0
            and production_progress > 0
            and complexity_progress > 0
        )
        if passes and model:
            passing_models.append(model)
        model_progress.append(
            {
                "model": model,
                "completion_progress": completion_progress,
                "utility_progress": utility_progress,
                "production_progress": production_progress,
                "complexity_progress": complexity_progress,
                "ok": passes,
            }
        )
    return {
        "ok": bool(passing_models),
        "required": {
            "median_completion_progress": "> 0",
            "median_utility_progress": "> 0",
            "median_production_progress": "> 0",
            "median_complexity_progress": "> 0",
        },
        "passing_models": passing_models,
        "models": model_progress,
    }


def _suite_ui_work_gate(comparison: dict[str, object]) -> dict[str, object]:
    variants = comparison.get("variants") if isinstance(comparison.get("variants"), list) else []
    passing_models: list[str] = []
    model_progress: list[dict[str, object]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        model = str(variant.get("model") or "")
        ui_work_progress = _as_float(variant.get("median_ui_work_progress"))
        provenance_runs = _as_int(variant.get("ui_score_provenance_runs"))
        passes = ui_work_progress > 0 and provenance_runs > 0
        if passes and model:
            passing_models.append(model)
        model_progress.append(
            {
                "model": model,
                "ui_work_progress": ui_work_progress,
                "ui_score_provenance_runs": provenance_runs,
                "ok": passes,
            }
        )
    return {
        "ok": bool(passing_models),
        "required": {
            "median_ui_work_progress": "> 0",
            "ui_score_provenance_runs": "> 0",
            "score_provenance": "keystroke_ui_work_rect",
        },
        "passing_models": passing_models,
        "models": model_progress,
    }


def _write_live_agent_suite_artifacts(
    *,
    report: dict[str, object],
    packet_path: str | None,
    server_artifacts_dir: str | None,
) -> tuple[Path, Path]:
    suite_id = str(report.get("suite_id") or "live-agent-suite")
    if packet_path:
        markdown_path = Path(packet_path).expanduser().resolve()
        target_dir = markdown_path.parent
    elif server_artifacts_dir:
        target_dir = Path(server_artifacts_dir).expanduser().resolve() / suite_id
        markdown_path = target_dir / "live_agent_suite_report.md"
    else:
        target_dir = Path.cwd() / suite_id
        markdown_path = target_dir / "live_agent_suite_report.md"

    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "scorecard.json"
    report["packet"] = str(markdown_path)
    report["scorecard_json"] = str(json_path)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    baseline = comparison.get("baseline") if isinstance(comparison.get("baseline"), dict) else {}
    variants = comparison.get("variants") if isinstance(comparison.get("variants"), list) else []
    progress_gate = report.get("progress_gate") if isinstance(report.get("progress_gate"), dict) else {}
    ui_work_gate = report.get("ui_work_gate") if isinstance(report.get("ui_work_gate"), dict) else {}

    lines = [
        "# fort-gym live agent suite",
        "",
        f"Generated: {generated_at}",
        f"Suite: `{suite_id}`",
        f"Status: {'PASS' if report.get('ok') else 'FAIL'}",
        f"Progress gate: {'PASS' if progress_gate.get('ok') else 'FAIL'}",
        f"Passing progress models: `{progress_gate.get('passing_models')}`",
        f"UI work gate: {'PASS' if ui_work_gate.get('ok') else 'FAIL'}",
        f"Passing UI work models: `{ui_work_gate.get('passing_models')}`",
        f"Result: `{comparison.get('result')}`",
        f"Best model: `{comparison.get('best_model')}`",
        f"Best median delta: `{comparison.get('best_median_delta')}`",
        "",
        "## Baseline",
        "",
        f"- Model: `{baseline.get('model')}`",
        f"- Scores: `{baseline.get('scores')}`",
        f"- Median: `{baseline.get('median_score')}`",
        f"- Work scores: `{baseline.get('work_scores')}`",
        f"- Median work progress: `{baseline.get('median_work_progress')}`",
        f"- Median UI work progress: `{baseline.get('median_ui_work_progress')}`",
        f"- Completion scores: `{baseline.get('completion_scores')}`",
        f"- Median completion progress: `{baseline.get('median_completion_progress')}`",
        f"- Utility scores: `{baseline.get('utility_scores')}`",
        f"- Median utility progress: `{baseline.get('median_utility_progress')}`",
        f"- Production scores: `{baseline.get('production_scores')}`",
        f"- Median production progress: `{baseline.get('median_production_progress')}`",
        f"- Complexity scores: `{baseline.get('complexity_scores')}`",
        f"- Median complexity progress: `{baseline.get('median_complexity_progress')}`",
        f"- Best run: {baseline.get('best_run_url')}",
        f"- Worst run: {baseline.get('worst_run_url')}",
        f"- Diagnostics: `{baseline.get('diagnostics')}`",
        f"- Real gameplay: `{baseline.get('real_gameplay')}`",
        "",
        "## Variants",
        "",
    ]
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        lines.extend(
            [
                f"### {variant.get('model')}",
                "",
                f"- Scores: `{variant.get('scores')}`",
                f"- Median: `{variant.get('median_score')}`",
                f"- Median delta vs baseline: `{variant.get('median_delta_vs_baseline')}`",
                f"- Work scores: `{variant.get('work_scores')}`",
                f"- Median work progress: `{variant.get('median_work_progress')}`",
                f"- Median UI work progress: `{variant.get('median_ui_work_progress')}`",
                f"- UI score provenance runs: `{variant.get('ui_score_provenance_runs')}`",
                f"- Completion scores: `{variant.get('completion_scores')}`",
                f"- Median completion progress: `{variant.get('median_completion_progress')}`",
                f"- Utility scores: `{variant.get('utility_scores')}`",
                f"- Median utility progress: `{variant.get('median_utility_progress')}`",
                f"- Production scores: `{variant.get('production_scores')}`",
                f"- Median production progress: `{variant.get('median_production_progress')}`",
                f"- Complexity scores: `{variant.get('complexity_scores')}`",
                f"- Median complexity progress: `{variant.get('median_complexity_progress')}`",
                f"- Best run: {variant.get('best_run_url')}",
                f"- Worst run: {variant.get('worst_run_url')}",
                f"- Diagnostics: `{variant.get('diagnostics')}`",
                f"- Real gameplay: `{variant.get('real_gameplay')}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Public Runs",
            "",
        ]
    )
    runs = report.get("runs") if isinstance(report.get("runs"), dict) else {}
    baseline_runs = runs.get("baseline") if isinstance(runs.get("baseline"), list) else []
    variant_runs = runs.get("variants") if isinstance(runs.get("variants"), dict) else {}
    for run in baseline_runs:
        if isinstance(run, dict):
            lines.append(
                f"- baseline trial {run.get('trial')}: score={run.get('score')} "
                f"run={run.get('public_run_url')} replay={run.get('public_replay_url')}"
            )
    for model, model_runs in variant_runs.items():
        if not isinstance(model_runs, list):
            continue
        for run in model_runs:
            if isinstance(run, dict):
                lines.append(
                    f"- {model} trial {run.get('trial')}: score={run.get('score')} "
                    f"run={run.get('public_run_url')} replay={run.get('public_replay_url')}"
                )
    lines.extend(
        [
            "",
            "## JSON",
            "",
            "```json",
            json.dumps(report, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, json_path


@app.command("real-gameplay-experiment")
def real_gameplay_experiment(
    baseline_token: str,
    model: str = "openrouter-keystroke-perception-review",
    backend: str = "dfhack",
    max_steps: int = 100,
    ticks_per_step: int = 10,
    api_base_url: str = "http://127.0.0.1:8000",
    public_base_url: str = "https://fortgym.live",
    admin_user: str | None = None,
    admin_password: str | None = None,
    server_artifacts_dir: str | None = "/opt/fort-gym/fort_gym/artifacts",
    timeout_seconds: int = 7200,
    poll_interval: float = 10.0,
    packet_path: str | None = None,
    preserve_save: bool = False,
) -> None:
    """Run a no-cheat keystroke variant and compare it to a public baseline trace."""

    resolved_user = admin_user or os.getenv("FORT_GYM_ADMIN_USER", "admin")
    resolved_password = admin_password or os.getenv("FORT_GYM_ADMIN_PASSWORD")
    if not resolved_password:
        typer.echo("FORT_GYM_ADMIN_PASSWORD or --admin-password is required.")
        raise typer.Exit(1)

    typer.echo(f"Loading baseline public run token {baseline_token}", err=True)
    baseline_payload = _json_request(
        method="GET",
        base_url=public_base_url,
        path=f"/public/runs/{baseline_token}",
    )
    if not isinstance(baseline_payload, dict):
        typer.echo("Could not load baseline public run.")
        raise typer.Exit(1)
    baseline_records, _ = _load_public_trace_records(public_base_url, baseline_token)
    baseline = _public_run_result(
        public_base_url=public_base_url,
        token=baseline_token,
        records=baseline_records,
        run_payload=baseline_payload,
    )

    typer.echo(f"Starting variant run: {model}", err=True)
    variant = _run_api_agent(
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
        preserve_save=preserve_save,
    )
    comparison = _build_real_gameplay_comparison(baseline, variant)
    report = {
        "ok": variant.get("status") == "completed",
        "baseline_token": baseline_token,
        "model": model,
        "backend": backend,
        "max_steps": max_steps,
        "ticks_per_step": ticks_per_step,
        "preserve_save": preserve_save,
        "comparison": comparison,
        "runs": {
            "baseline": baseline,
            "variant": variant,
        },
    }
    _write_real_gameplay_experiment_artifacts(
        report=report,
        packet_path=packet_path,
        server_artifacts_dir=server_artifacts_dir,
    )
    typer.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise typer.Exit(1)


@app.command("live-agent-report")
def live_agent_report(
    model: str = "openrouter-keystroke-perception-review",
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
    preserve_save: bool = False,
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
        preserve_save=preserve_save,
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
        preserve_save=preserve_save,
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


@app.command("live-agent-suite")
def live_agent_suite(
    models: str = DEFAULT_LIVE_AGENT_MODELS,
    baseline_model: str = "fake",
    trials: int = 2,
    backend: str = "dfhack",
    max_steps: int = 6,
    ticks_per_step: int = 10,
    api_base_url: str = "http://127.0.0.1:8000",
    public_base_url: str = "http://34.41.155.134",
    admin_user: str | None = None,
    admin_password: str | None = None,
    server_artifacts_dir: str | None = "/opt/fort-gym/fort_gym/artifacts",
    timeout_seconds: int = 600,
    poll_interval: float = 5.0,
    packet_path: str | None = None,
    preserve_save: bool = False,
) -> None:
    """Run a multi-trial live-agent scorecard through the public API."""

    model_names = _split_models(models)
    if not model_names:
        typer.echo("--models must include at least one model name.")
        raise typer.Exit(1)
    if trials < 1:
        typer.echo("--trials must be at least 1.")
        raise typer.Exit(1)

    resolved_user = admin_user or os.getenv("FORT_GYM_ADMIN_USER", "admin")
    resolved_password = admin_password or os.getenv("FORT_GYM_ADMIN_PASSWORD")
    if not resolved_password:
        typer.echo("FORT_GYM_ADMIN_PASSWORD or --admin-password is required.")
        raise typer.Exit(1)

    baseline_runs: list[dict[str, object]] = []
    variant_runs: dict[str, list[dict[str, object]]] = {model: [] for model in model_names}
    for trial in range(1, trials + 1):
        typer.echo(f"Starting baseline trial {trial}/{trials}: {baseline_model}", err=True)
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
            preserve_save=preserve_save,
        )
        baseline["trial"] = trial
        baseline_runs.append(baseline)

        for model in model_names:
            typer.echo(f"Starting model trial {trial}/{trials}: {model}", err=True)
            result = _run_api_agent(
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
                preserve_save=preserve_save,
            )
            result["trial"] = trial
            variant_runs[model].append(result)

    comparison = _build_suite_comparison(
        baseline_runs=baseline_runs,
        variant_runs=variant_runs,
    )
    progress_gate = _suite_progress_gate(comparison)
    ui_work_gate = _suite_ui_work_gate(comparison)
    all_runs = baseline_runs + [
        run
        for runs_for_model in variant_runs.values()
        for run in runs_for_model
    ]
    all_completed = all(run.get("status") == "completed" for run in all_runs)
    suite_id = f"live-agent-suite-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    report = {
        "ok": all_completed and (bool(progress_gate.get("ok")) or bool(ui_work_gate.get("ok"))),
        "suite_id": suite_id,
        "trials": trials,
        "backend": backend,
        "max_steps": max_steps,
        "ticks_per_step": ticks_per_step,
        "preserve_save": preserve_save,
        "baseline_model": baseline_model,
        "models": model_names,
        "all_runs_completed": all_completed,
        "progress_gate": progress_gate,
        "ui_work_gate": ui_work_gate,
        "comparison": comparison,
        "runs": {
            "baseline": baseline_runs,
            "variants": variant_runs,
        },
    }
    _write_live_agent_suite_artifacts(
        report=report,
        packet_path=packet_path,
        server_artifacts_dir=server_artifacts_dir,
    )
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
