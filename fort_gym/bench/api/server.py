"""FastAPI server exposing admin and public fort-gym endpoints."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Callable, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from importlib import import_module

from ..agent.base import AGENT_FACTORIES, Agent, RandomAgent
from ..run.jobs import JOB_REGISTRY, JobInfo as RegistryJobInfo
from ..run.runner import run_once
from ..run.storage import RUN_REGISTRY, RunInfo as RegistryRunInfo, ShareToken
from .routes_step import router as step_router
from .schemas import (
    JobCreate,
    JobInfo,
    RunCreateRequest,
    RunInfo,
    RunInfoPublic,
    ShareCreate,
)
from .sse import ndjson_iter, sse_event, stream_queue

app = FastAPI(title="fort-gym API")
app.include_router(step_router)


ARTIFACTS_ROOT = Path(__file__).resolve().parents[2] / "artifacts"
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


# ---------------------------------------------------------------------------
# Static file serving for web UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=FileResponse)
async def serve_index():
    """Serve the public spectator UI."""
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")


@app.get("/admin", response_class=FileResponse)
async def serve_admin():
    """Serve the admin panel."""
    return FileResponse(WEB_ROOT / "admin.html", media_type="text/html")


def _artifacts_path(run_id: str) -> Path:
    return ARTIFACTS_ROOT / run_id / "trace.jsonl"


def _serialize(record: RegistryRunInfo) -> RunInfo:
    metadata = getattr(record, "metadata", {}) or {}
    summary = record.latest_summary or {}
    return RunInfo(
        id=record.run_id,
        backend=record.backend,
        model=record.model,
        status=record.status,
        step=record.step,
        max_steps=record.max_steps,
        ticks_per_step=record.ticks_per_step,
        started_at=record.started_at,
        finished_at=record.ended_at,
        score=summary.get("total_score") or metadata.get("last_score"),
    )


def _serialize_public(record: RegistryRunInfo, share: ShareToken) -> RunInfoPublic:
    metadata = getattr(record, "metadata", {}) or {}
    summary = record.latest_summary or {}
    return RunInfoPublic(
        run_id=record.run_id,
        model=record.model,
        backend=record.backend,
        status=record.status,
        step=record.step,
        started_at=record.started_at,
        finished_at=record.ended_at,
        score=summary.get("total_score") or metadata.get("last_score"),
        token=share.token,
        scopes=sorted(share.scope),
    )


def _serialize_job(job: RegistryJobInfo) -> JobInfo:
    data = job.model_dump() if hasattr(job, "model_dump") else job.dict()
    return JobInfo(**data)


def _require_share(token: str, *, scope: Optional[str] = None) -> ShareToken:
    share = RUN_REGISTRY.get_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="Not found")
    if scope and scope not in share.scope:
        raise HTTPException(status_code=404, detail="Not found")
    return share


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/runs", response_model=List[RunInfo])
async def list_runs() -> List[RunInfo]:
    return [_serialize(record) for record in RUN_REGISTRY.list()]


OPTIONAL_AGENT_MODULES = {
    "fake": "fort_gym.bench.agent.fake_llm",
    "openai": "fort_gym.bench.agent.llm_openai",
    "anthropic": "fort_gym.bench.agent.llm_anthropic",
}


def _get_agent_factory(model: str) -> Callable[[], Agent]:
    factory = AGENT_FACTORIES.get(model)
    if factory:
        return factory
    module_path = OPTIONAL_AGENT_MODULES.get(model)
    if module_path:
        import_module(module_path)
    factory = AGENT_FACTORIES.get(model)
    if not factory:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'")
    return factory


@app.post("/runs", response_model=RunInfo)
async def create_run(payload: RunCreateRequest) -> RunInfo:
    loop = asyncio.get_running_loop()

    agent_factory = _get_agent_factory(payload.model)

    record = RUN_REGISTRY.create(
        backend=payload.backend,
        model=payload.model,
        max_steps=payload.max_steps,
        ticks_per_step=payload.ticks_per_step,
        loop=loop,
    )

    def _target() -> None:
        agent = agent_factory()
        if isinstance(agent, RandomAgent) and payload.safe is not None:
            agent.set_safe(bool(payload.safe))
        run_once(
            agent,
            backend=payload.backend,
            model=payload.model,
            max_steps=payload.max_steps,
            ticks_per_step=payload.ticks_per_step,
            run_id=record.run_id,
            registry=RUN_REGISTRY,
            loop=loop,
        )

    thread = threading.Thread(target=_target, name=f"run-{record.run_id}", daemon=True)
    thread.start()

    return _serialize(record)


@app.get("/runs/{run_id}", response_model=RunInfo)
async def get_run(run_id: str) -> RunInfo:
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize(record)


@app.get("/runs/{run_id}/events/stream")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    queue = RUN_REGISTRY.get_queue(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Run not found")
    generator = stream_queue(request, queue)
    return StreamingResponse(generator, media_type="text/event-stream")


@app.post("/runs/{run_id}/pause")
async def pause_run(run_id: str) -> JSONResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    RUN_REGISTRY.set_status(run_id, status="paused")
    return JSONResponse({"status": "paused", "run_id": run_id})


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str) -> JSONResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    RUN_REGISTRY.set_status(run_id, status="running")
    return JSONResponse({"status": "running", "run_id": run_id})


@app.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> JSONResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    RUN_REGISTRY.set_status(run_id, status="stopped", ended_at=datetime.utcnow())
    return JSONResponse({"status": "stopped", "run_id": run_id})


@app.post("/runs/{run_id}/share")
async def create_share(run_id: str, body: ShareCreate) -> Dict[str, object]:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    scope = body.scope or ["live", "replay", "export"]
    try:
        share = RUN_REGISTRY.create_share(run_id, scope=scope, ttl_seconds=body.ttl_seconds)
    except KeyError as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return {
        "token": share.token,
        "expires_at": share.expires_at,
        "scope": sorted(share.scope),
    }


@app.get("/runs/{run_id}/export/trace")
async def export_trace(run_id: str) -> StreamingResponse:
    path = _artifacts_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Trace not available")

    def iterator() -> Iterable[bytes]:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                yield chunk

    return StreamingResponse(iterator(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# Public namespace
# ---------------------------------------------------------------------------


@app.get("/public/runs", response_model=List[RunInfoPublic])
async def public_runs() -> List[RunInfoPublic]:
    items = RUN_REGISTRY.list_public()
    return [_serialize_public(record, share) for record, share in items]


@app.get("/public/leaderboard")
async def public_leaderboard(limit: int = 50) -> List[Dict[str, object]]:
    return RUN_REGISTRY.public_leaderboard(limit)


@app.get("/public/runs/{token}", response_model=RunInfoPublic)
async def public_run(token: str) -> RunInfoPublic:
    share = _require_share(token)
    record = RUN_REGISTRY.get(share.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_public(record, share)


@app.get("/public/runs/{token}/events/stream")
async def public_stream(token: str, request: Request) -> StreamingResponse:
    share = _require_share(token, scope="live")
    queue = RUN_REGISTRY.get_queue(share.run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return StreamingResponse(stream_queue(request, queue), media_type="text/event-stream")


@app.get("/public/runs/{token}/events/replay")
async def public_replay(token: str, request: Request, speed: int = 4) -> StreamingResponse:
    share = _require_share(token, scope="replay")
    path = _artifacts_path(share.run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Replay not available")

    async def generator() -> AsyncGenerator[str, None]:
        for record in ndjson_iter(path):
            if await request.is_disconnected():
                break
            events = record.get("events") or []
            for event in events:
                event_type = event.get("type", "message")
                data = event.get("data", {})
                yield sse_event(event_type, data)
                await asyncio.sleep(max(0.01, 0.1 / max(1, speed)))
        yield sse_event("end", {"run_id": share.run_id})

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/public/runs/{token}/export/trace")
async def public_export(token: str) -> StreamingResponse:
    share = _require_share(token, scope="export")
    path = _artifacts_path(share.run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Trace not available")

    def iterator() -> Iterable[bytes]:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                yield chunk

    return StreamingResponse(iterator(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# Screenshot endpoints for live game visualization
# ---------------------------------------------------------------------------

_screenshot_client = None


def _get_screenshot_client():
    """Get or create a DFHack client for screenshot capture."""
    global _screenshot_client
    if _screenshot_client is not None:
        return _screenshot_client
    try:
        from ..env.dfhack_client import DFHackClient, DFHackUnavailableError
        client = DFHackClient()
        client.connect()
        _screenshot_client = client
        return client
    except Exception:
        return None


@app.get("/screenshot")
async def admin_screenshot() -> JSONResponse:
    """Capture the current DF screen (admin endpoint)."""
    client = _get_screenshot_client()
    if client is None:
        raise HTTPException(status_code=503, detail="DFHack not available")
    try:
        screen = client.get_screen()
        return JSONResponse(screen)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {exc}")


@app.get("/public/runs/{token}/screenshot")
async def public_screenshot(token: str) -> JSONResponse:
    """Capture the current DF screen for a public run (requires 'live' scope)."""
    _require_share(token, scope="live")
    client = _get_screenshot_client()
    if client is None:
        raise HTTPException(status_code=503, detail="DFHack not available")
    try:
        screen = client.get_screen()
        return JSONResponse(screen)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {exc}")


@app.post("/jobs", response_model=JobInfo)
async def create_job(payload: JobCreate) -> JobInfo:
    loop = asyncio.get_running_loop()

    agent_factory = _get_agent_factory(payload.model)

    job = JOB_REGISTRY.create(
        model=payload.model,
        backend=payload.backend,
        n=payload.n,
        parallelism=payload.parallelism,
    )

    def make_run() -> str:
        agent = agent_factory()
        if isinstance(agent, RandomAgent) and payload.safe is not None:
            agent.set_safe(bool(payload.safe))
        return run_once(
            agent,
            backend=payload.backend,
            model=payload.model,
            max_steps=payload.max_steps,
            ticks_per_step=payload.ticks_per_step,
            registry=RUN_REGISTRY,
            loop=loop,
        )

    JOB_REGISTRY.start(job.job_id, make_run)
    return _serialize_job(job)


@app.get("/jobs", response_model=List[JobInfo])
async def list_jobs() -> List[JobInfo]:
    return [_serialize_job(job) for job in JOB_REGISTRY.list()]


@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str) -> JobInfo:
    job = JOB_REGISTRY.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("fort_gym.bench.api.server:app", host="0.0.0.0", port=8000, reload=True)
