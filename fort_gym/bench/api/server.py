"""FastAPI server exposing admin and public fort-gym endpoints."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, Iterable, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..agent.base import AGENT_FACTORIES, Agent, RandomAgent
from ..config import get_settings
from ..env.keystroke_exec import execute_keystroke_action
from ..eval.protocol import EVALUATION_PROTOCOL_PATTERN
from ..eval.public_protocols import get_public_protocol, list_public_protocols
from ..run.jobs import JOB_REGISTRY
from ..run.jobs import JobInfo as RegistryJobInfo
from ..run.runner import run_once
from ..run.storage import RUN_REGISTRY
from ..run.storage import RunInfo as RegistryRunInfo
from ..run.storage import ShareToken
from .auth import require_admin
from .rate_limit import RateLimiter, get_rate_limit_client_id, get_rate_limit_config
from .routes_step import router as step_router
from .schemas import (
    AdminKeysRequest,
    JobCreate,
    JobInfo,
    PublicComparisonGroup,
    PublicModelResult,
    PublicOverview,
    PublicProtocol,
    PublicResults,
    PublicRunPreview,
    PublicRunsPage,
    PublicRunSummary,
    RunCreateRequest,
    RunInfo,
    RunInfoPublic,
    ShareCreate,
)
from .trace_preview import read_trace_preview
from .sse import ndjson_iter, sse_event, stream_queue

app = FastAPI(title="fort-gym API")
app.include_router(step_router)

_RATE_LIMITER = RateLimiter()


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if os.getenv("FORT_GYM_RATE_LIMIT_ENABLED", "1") != "1":
        return await call_next(request)

    path = request.url.path
    bucket: Optional[str] = None

    # Admin panel + admin-only endpoints (HTML + screenshot + key injection).
    if path == "/admin" or path.startswith("/admin/") or path == "/screenshot":
        bucket = "admin"

    # Run management endpoints are admin-only but high-impact, so rate limit separately.
    if path == "/runs" or path.startswith("/runs/"):
        bucket = "runs"

    if path in {"/public/worlds", "/public/results"}:
        bucket = "public_worlds"

    if bucket:
        admin_rpm, runs_rpm = get_rate_limit_config()
        if bucket == "admin":
            rpm = admin_rpm
        elif bucket == "runs":
            rpm = runs_rpm
        else:
            rpm = max(1, int(os.getenv("FORT_GYM_RATE_LIMIT_PUBLIC_RPM", "120")))
        client_id = get_rate_limit_client_id(request)
        ok, retry_after = _RATE_LIMITER.allow(
            bucket, client_id, capacity=rpm, refill_per_s=rpm / 60.0
        )
        if not ok:
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after": round(retry_after, 2)},
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    return await call_next(request)


ARTIFACTS_ROOT = Path(get_settings().ARTIFACTS_DIR).resolve()
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
HTML_CACHE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}


def _html_file_response(filename: str) -> FileResponse:
    return FileResponse(WEB_ROOT / filename, media_type="text/html", headers=HTML_CACHE_HEADERS)


# ---------------------------------------------------------------------------
# Static file serving for web UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=FileResponse)
async def serve_landing():
    """Serve the environment-lab landing page."""
    return _html_file_response("landing.html")


@app.get("/live", response_class=FileResponse)
async def serve_index():
    """Serve the public spectator UI (live viewer)."""
    return _html_file_response("index.html")


@app.get("/replay/{token}", response_class=FileResponse)
async def serve_visual_replay(token: str):
    """Serve the public spectator UI for a specific shared run token."""
    return _html_file_response("index.html")


@app.get("/r/{token}", response_class=FileResponse)
async def serve_short_visual_replay(token: str):
    """Serve the public spectator UI at the short shared-run URL."""
    return _html_file_response("index.html")


@app.get("/admin", response_class=FileResponse)
async def serve_admin(_: None = Depends(require_admin)):
    """Serve the admin panel."""
    return _html_file_response("admin.html")


@app.get("/leaderboard", response_class=FileResponse)
async def serve_leaderboard():
    """Serve the public leaderboard UI."""
    return _html_file_response("leaderboard.html")


@app.get("/worlds", response_class=FileResponse)
async def serve_worlds():
    """Serve the public runs library."""
    return _html_file_response("worlds.html")


@app.get("/results", response_class=FileResponse)
async def serve_results():
    """Serve the public results UI."""
    return _html_file_response("results.html")


@app.get("/protocols", response_class=FileResponse)
async def serve_protocols():
    """Serve the public protocol catalog UI."""
    return _html_file_response("protocols.html")


@app.get("/protocols/{slug}", response_class=FileResponse)
async def serve_protocol_detail(slug: str):
    """Serve the protocol detail UI; the client resolves the path slug."""
    if get_public_protocol(slug) is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return _html_file_response("protocols.html")


# Bundled static assets (e.g. the CC BY 4.0 Oddball tileset used by the
# replay UI's Graphical glyph mode). check_dir=False so the API still boots
# if a checkout is missing the directory.
app.mount(
    "/static",
    StaticFiles(directory=str(WEB_ROOT / "static"), check_dir=False),
    name="static",
)


def _artifacts_path(run_id: str) -> Path:
    return ARTIFACTS_ROOT / run_id / "trace.jsonl"


def _serialize(record: RegistryRunInfo) -> RunInfo:
    metadata = getattr(record, "metadata", {}) or {}
    summary = record.latest_summary or {}
    return RunInfo(
        id=record.run_id,
        backend=record.backend,
        model=record.model,
        git_sha=getattr(record, "git_sha", None),
        seed_save=getattr(record, "seed_save", None),
        runtime_save=getattr(record, "runtime_save", None),
        preserve_save=getattr(record, "preserve_save", False),
        evaluation_protocol=getattr(record, "evaluation_protocol", None),
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
        git_sha=getattr(record, "git_sha", None),
        backend=record.backend,
        status=record.status,
        step=record.step,
        max_steps=record.max_steps,
        ticks_per_step=record.ticks_per_step,
        seed_save=getattr(record, "seed_save", None),
        runtime_save=getattr(record, "runtime_save", None),
        preserve_save=getattr(record, "preserve_save", False),
        evaluation_protocol=getattr(record, "evaluation_protocol", None),
        started_at=record.started_at,
        finished_at=record.ended_at,
        score=summary.get("total_score") or metadata.get("last_score"),
        token=share.token,
        scopes=sorted(share.scope),
    )


_COMPARABILITY_FIELDS = [
    "evaluation_protocol",
    "backend",
    "git_sha",
    "score_version",
    "seed_save",
    "max_steps",
    "ticks_per_step",
]
_PUBLIC_SUMMARY_FIELDS = {
    "evaluation_protocol",
    "score_version",
    "total_score",
    "survival_score",
    "steps",
    "duration_ticks",
    "peak_pop",
    "end_pop",
    "rubric",
    "milestones",
    "scenario_assertions",
}


def _compact_public_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Keep persisted score and evaluation fields without deriving new data."""

    result = {key: summary[key] for key in _PUBLIC_SUMMARY_FIELDS if key in summary}
    result.update(
        {
            key: value
            for key, value in summary.items()
            if "gate" in key.lower() and key not in result
        }
    )
    return result


def _comparison_groups(
    items: List[Tuple[RegistryRunInfo, ShareToken]],
) -> List[PublicComparisonGroup]:
    """Return model rows only for runs with complete comparison provenance."""

    groups: Dict[
        Tuple[str, str, str, int, str, int, int], Dict[str, List[Tuple[float, str]]]
    ] = {}
    for record, share in items:
        if (
            record.status != "completed"
            or record.backend != "dfhack"
            or not {"replay", "export"}.issubset(share.scope)
            or not _has_replay_artifact(record.run_id)
        ):
            continue
        summary = record.latest_summary
        if not isinstance(summary, dict):
            continue
        evaluation_protocol = record.evaluation_protocol
        summary_evaluation_protocol = summary.get("evaluation_protocol")
        score_version = summary.get("score_version")
        total_score = summary.get("total_score")
        if (
            not isinstance(evaluation_protocol, str)
            or not evaluation_protocol.strip()
            or summary_evaluation_protocol != evaluation_protocol
            or not isinstance(record.git_sha, str)
            or not record.git_sha.strip()
            or type(score_version) is not int
            or score_version <= 0
            or not record.seed_save
            or isinstance(total_score, bool)
        ):
            continue
        try:
            score = float(total_score)
        except (TypeError, ValueError):
            continue
        key = (
            evaluation_protocol,
            record.backend,
            record.git_sha.strip(),
            score_version,
            record.seed_save,
            record.max_steps,
            record.ticks_per_step,
        )
        groups.setdefault(key, {}).setdefault(record.model, []).append((score, share.token))

    response: List[PublicComparisonGroup] = []
    for key, scores_by_model in groups.items():
        response.append(
            PublicComparisonGroup(
                comparability=dict(zip(_COMPARABILITY_FIELDS, key, strict=True)),
                model_results=sorted(
                    [
                        PublicModelResult(
                            model=model,
                            run_count=len(scored_runs),
                            mean_score=round(
                                sum(score for score, _token in scored_runs) / len(scored_runs), 2
                            ),
                            best_score=round(max(score for score, _token in scored_runs), 2),
                            best_token=max(scored_runs, key=lambda item: item[0])[1],
                        )
                        for model, scored_runs in scores_by_model.items()
                    ],
                    key=lambda result: (result.mean_score, result.model),
                    reverse=True,
                ),
            )
        )
    return sorted(
        response,
        key=lambda group: (
            group.comparability["score_version"],
            group.comparability["evaluation_protocol"],
        ),
        reverse=True,
    )


_UNRESOLVED_PROTOCOL_VALUES = {
    "resolved_at_run",
    "unresolved_before_run",
    "memory_window_variant",
}


def _has_replay_artifact(run_id: str) -> bool:
    """Require a non-empty recorded trace before publishing result evidence."""

    try:
        return _artifacts_path(run_id).stat().st_size > 0
    except OSError:
        return False


def _protocol_comparison_groups(
    items: List[Tuple[RegistryRunInfo, ShareToken]],
    protocol_definition: Any,
) -> List[PublicComparisonGroup]:
    """Build comparisons only from complete declared protocol provenance."""

    declared_fields = list(protocol_definition.comparability_fields)
    group_fields = [field for field in declared_fields if field != "model_digest"]
    response_fields = ["evaluation_protocol", *group_fields, "score_version"]
    groups: Dict[Tuple[object, ...], Dict[str, List[Tuple[float, str]]]] = {}

    for record, share in items:
        if (
            record.status != "completed"
            or record.backend != "dfhack"
            or not {"replay", "export"}.issubset(share.scope)
            or not _has_replay_artifact(record.run_id)
        ):
            continue
        summary = record.latest_summary
        if not isinstance(summary, dict) or summary.get("evaluation_protocol") != record.evaluation_protocol:
            continue
        score_version = summary.get("score_version")
        total_score = summary.get("total_score")
        values: Dict[str, str] = {}
        complete = type(score_version) is int and score_version > 0 and not isinstance(total_score, bool)
        for field in declared_fields:
            value = summary.get(field)
            if not isinstance(value, str) or not value.strip():
                complete = False
                break
            value = value.strip()
            expected = protocol_definition.comparability_defaults.get(field)
            if expected and expected not in _UNRESOLVED_PROTOCOL_VALUES and value != expected:
                complete = False
                break
            if value in _UNRESOLVED_PROTOCOL_VALUES:
                complete = False
                break
            values[field] = value
        if not complete or values.get("fort_gym_commit") != record.git_sha:
            continue
        try:
            score = float(total_score)
        except (TypeError, ValueError):
            continue
        key_values: Tuple[object, ...] = (
            record.evaluation_protocol,
            *(values[field] for field in group_fields),
            score_version,
        )
        groups.setdefault(key_values, {}).setdefault(values["model_digest"], []).append(
            (score, share.token)
        )

    response: List[PublicComparisonGroup] = []
    for key, scores_by_model in groups.items():
        response.append(
            PublicComparisonGroup(
                comparability=dict(zip(response_fields, key, strict=True)),
                model_results=sorted(
                    [
                        PublicModelResult(
                            model=model_digest,
                            run_count=len(scored_runs),
                            mean_score=round(
                                sum(score for score, _token in scored_runs) / len(scored_runs), 2
                            ),
                            best_score=round(max(score for score, _token in scored_runs), 2),
                            best_token=max(scored_runs, key=lambda item: item[0])[1],
                        )
                        for model_digest, scored_runs in scores_by_model.items()
                    ],
                    key=lambda result: (result.mean_score, result.model),
                    reverse=True,
                ),
            )
        )
    return sorted(
        response,
        key=lambda group: (
            group.comparability["score_version"],
            group.comparability["evaluation_protocol"],
        ),
        reverse=True,
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
async def list_runs(_: None = Depends(require_admin)) -> List[RunInfo]:
    return [_serialize(record) for record in RUN_REGISTRY.list()]


OPTIONAL_AGENT_MODULES = {
    "fake": "fort_gym.bench.agent.fake_llm",
    "dfhack-governed-scripted": "fort_gym.bench.agent.governed",
    "dfhack-governed-llm": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-glm52": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-deepseek-v4": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-gpt55": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-glm5v": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-gpt55-vision": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-kimi-vision": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-minimax-vision": "fort_gym.bench.agent.governed_llm",
    "openai": "fort_gym.bench.agent.llm_openai",
    "openai-keystroke-perception-review": "fort_gym.bench.agent.llm_openai",
    "openrouter-keystroke": "fort_gym.bench.agent.llm_openrouter",
    "openrouter-keystroke-perception-review": "fort_gym.bench.agent.llm_openrouter",
    "openrouter-glm-5.2": "fort_gym.bench.agent.llm_openrouter",
    "anthropic": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-dig-first": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-fortress-plan": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-keystroke": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-keystroke-poi-review": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-keystroke-plan-review": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-keystroke-perception-review": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-keystroke-perception-review-opus": "fort_gym.bench.agent.llm_anthropic",
    "anthropic-research": "fort_gym.bench.agent.llm_anthropic_research",
}


def _anthropic_enabled() -> bool:
    return os.getenv("FORT_GYM_ENABLE_ANTHROPIC", "0").lower() in {"1", "true", "yes"}


def _get_agent_factory(model: str) -> Callable[[], Agent]:
    if model.startswith("anthropic") and not _anthropic_enabled():
        raise HTTPException(
            status_code=400,
            detail=(
                "Anthropic models are disabled for this deployment. Use "
                "openrouter-keystroke-perception-review or openrouter-glm-5.2."
            ),
        )
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
async def create_run(payload: RunCreateRequest, _: None = Depends(require_admin)) -> RunInfo:
    loop = asyncio.get_running_loop()

    agent_factory = _get_agent_factory(payload.model)

    record = RUN_REGISTRY.create(
        backend=payload.backend,
        model=payload.model,
        max_steps=payload.max_steps,
        ticks_per_step=payload.ticks_per_step,
        preserve_save=payload.preserve_save,
        seed_save=payload.seed_save,
        runtime_save=payload.runtime_save,
        evaluation_protocol=payload.evaluation_protocol,
        loop=loop,
    )

    # Auto-create share token so run appears in public spectator view
    # Benchmark runs are public evidence: their share links must never rot.
    RUN_REGISTRY.create_share(record.run_id, scope=["live", "replay", "export"], ttl_seconds=None)

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
            preserve_save=payload.preserve_save,
            seed_save=payload.seed_save,
            runtime_save=payload.runtime_save,
            evaluation_protocol=payload.evaluation_protocol,
        )

    thread = threading.Thread(target=_target, name=f"run-{record.run_id}", daemon=True)
    thread.start()

    return _serialize(record)


@app.get("/runs/{run_id}", response_model=RunInfo)
async def get_run(run_id: str, _: None = Depends(require_admin)) -> RunInfo:
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize(record)


@app.get("/runs/{run_id}/events/stream")
async def stream_events(
    run_id: str, request: Request, _: None = Depends(require_admin)
) -> StreamingResponse:
    queue = RUN_REGISTRY.get_queue(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Run not found")
    generator = stream_queue(request, queue)
    return StreamingResponse(generator, media_type="text/event-stream")


@app.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    RUN_REGISTRY.set_status(run_id, status="paused")
    return JSONResponse({"status": "paused", "run_id": run_id})


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    RUN_REGISTRY.set_status(run_id, status="running")
    return JSONResponse({"status": "running", "run_id": run_id})


@app.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not RUN_REGISTRY.request_stop(run_id):
        latest = RUN_REGISTRY.get(run_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return JSONResponse({"status": latest.status, "run_id": run_id})
    return JSONResponse({"status": "stop_requested", "run_id": run_id})


@app.post("/runs/{run_id}/share")
async def create_share(
    run_id: str, body: ShareCreate, _: None = Depends(require_admin)
) -> Dict[str, object]:
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
async def export_trace(run_id: str, _: None = Depends(require_admin)) -> StreamingResponse:
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


@app.get("/public/worlds", response_model=PublicRunsPage)
async def public_worlds(
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    status: Optional[str] = Query(default=None, max_length=32),
    model: Optional[str] = Query(default=None, max_length=200),
    evaluation_protocol: Optional[str] = Query(default=None, max_length=100),
    seed_save: Optional[str] = Query(default=None, max_length=200),
    q: Optional[str] = Query(default=None, max_length=100),
) -> PublicRunsPage:
    """List public run metadata without opening trace artifacts."""

    items, total = RUN_REGISTRY.list_public_page(
        limit=limit,
        offset=offset,
        status=status,
        model=model,
        evaluation_protocol=evaluation_protocol,
        seed_save=seed_save,
        query=q,
    )
    return PublicRunsPage(
        items=[_serialize_public(record, share) for record, share in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/public/overview", response_model=PublicOverview)
async def public_overview(
    recent_limit: int = Query(default=20, ge=1, le=100),
) -> PublicOverview:
    active_items, recent_items, terminal_items = RUN_REGISTRY.public_overview_runs(
        recent_limit=recent_limit
    )
    return PublicOverview(
        generated_at=datetime.utcnow(),
        active_runs=[_serialize_public(record, share) for record, share in active_items],
        recent_runs=[_serialize_public(record, share) for record, share in recent_items],
        comparability_fields=_COMPARABILITY_FIELDS,
        comparison_groups=_comparison_groups(terminal_items),
    )


@app.get("/public/results", response_model=PublicResults)
async def public_results(
    evaluation_protocol: str = Query(
        ...,
        min_length=1,
        max_length=64,
        pattern=EVALUATION_PROTOCOL_PATTERN,
    ),
) -> PublicResults:
    """Return experimental, provenance-gated comparisons for one protocol."""

    protocol_definition = get_public_protocol(evaluation_protocol)
    if protocol_definition is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    candidates, truncated = RUN_REGISTRY.list_public_for_protocol(evaluation_protocol)
    if truncated:
        raise HTTPException(status_code=503, detail="Protocol cohort exceeds publication limit")
    comparison_groups = _protocol_comparison_groups(candidates, protocol_definition)
    eligible_run_count = sum(
        result.run_count
        for group in comparison_groups
        for result in group.model_results
    )
    candidate_run_count = len(candidates)
    return PublicResults(
        generated_at=datetime.utcnow(),
        protocol=evaluation_protocol,
        comparability_fields=[
            "evaluation_protocol",
            *protocol_definition.comparability_fields,
            "score_version",
        ],
        candidate_run_count=candidate_run_count,
        eligible_run_count=eligible_run_count,
        excluded_run_count=candidate_run_count - eligible_run_count,
        comparison_groups=comparison_groups,
    )


@app.get("/public/protocols", response_model=List[PublicProtocol])
async def public_protocols() -> List[PublicProtocol]:
    """List the public, allowlisted Fort-Eval profiles."""

    return [PublicProtocol(**entry.to_public_dict()) for entry in list_public_protocols()]


@app.get("/public/protocols/{slug}", response_model=PublicProtocol)
async def public_protocol(slug: str) -> PublicProtocol:
    """Return one public-safe protocol definition."""

    entry = get_public_protocol(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return PublicProtocol(**entry.to_public_dict())


@app.get("/public/leaderboard")
async def public_leaderboard(
    limit: int = Query(default=50, ge=1, le=5000),
) -> List[Dict[str, object]]:
    return RUN_REGISTRY.public_leaderboard(limit)


@app.get("/public/leaderboard/best-over-time")
async def public_best_over_time(
    days: int = 30,
    backend: Optional[str] = None,
    model: Optional[str] = None,
    max_steps: Optional[int] = None,
    limit_per_series: int = 500,
) -> List[Dict[str, object]]:
    return RUN_REGISTRY.best_scores_over_time(
        days=days,
        backend=backend,
        model=model,
        max_steps=max_steps,
        limit_per_series=limit_per_series,
    )


@app.get("/public/runs/{token}", response_model=RunInfoPublic)
async def public_run(token: str) -> RunInfoPublic:
    share = _require_share(token)
    record = RUN_REGISTRY.get(share.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_public(record, share)


@app.get("/public/runs/{token}/summary", response_model=PublicRunSummary)
async def public_run_summary(token: str) -> PublicRunSummary:
    share = _require_share(token)
    record = RUN_REGISTRY.get(share.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    latest_summary = record.latest_summary if isinstance(record.latest_summary, dict) else {}
    cost = latest_summary.get("cost")
    return PublicRunSummary(
        run=_serialize_public(record, share),
        summary=_compact_public_summary(latest_summary),
        usage=latest_summary.get("usage"),
        cost=cost,
        cost_status="reported" if cost is not None else "not_reported",
    )


@app.get("/public/runs/{token}/preview", response_model=PublicRunPreview)
async def public_run_preview(token: str) -> PublicRunPreview:
    share = _require_share(token, scope="replay")
    path = _artifacts_path(share.run_id)
    try:
        preview = read_trace_preview(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Trace not available") from exc
    return PublicRunPreview(**preview)


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
        from ..env.dfhack_client import DFHackClient

        client = DFHackClient()
        client.connect()
        _screenshot_client = client
        return client
    except Exception:
        return None


def _reset_screenshot_client() -> None:
    """Drop a cached DFHack screenshot connection after a transport failure."""
    global _screenshot_client
    client = _screenshot_client
    _screenshot_client = None
    if client is not None:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _capture_screenshot() -> Dict[str, object]:
    """Capture the DF screen, reconnecting once when the cached socket is stale."""
    last_error: Optional[Exception] = None
    for _attempt in range(2):
        client = _get_screenshot_client()
        if client is None:
            raise HTTPException(status_code=503, detail="DFHack not available")
        try:
            return client.get_screen()
        except Exception as exc:
            last_error = exc
            _reset_screenshot_client()

    raise HTTPException(status_code=500, detail=f"Screenshot failed: {last_error}")


@app.get("/screenshot")
async def admin_screenshot(_: None = Depends(require_admin)) -> JSONResponse:
    """Capture the current DF screen (admin endpoint)."""
    return JSONResponse(_capture_screenshot())


@app.get("/public/runs/{token}/screenshot")
async def public_screenshot(token: str) -> JSONResponse:
    """Capture the current DF screen for a public run (requires 'live' scope)."""
    _require_share(token, scope="live")
    return JSONResponse(_capture_screenshot())


@app.post("/admin/keys")
async def admin_keys(payload: AdminKeysRequest, _: None = Depends(require_admin)) -> JSONResponse:
    """Send raw DF interface keys for manual admin control."""
    from ..config import get_settings

    settings = get_settings()
    if not settings.DFHACK_ENABLED:
        raise HTTPException(status_code=400, detail="DFHack backend disabled")
    result = execute_keystroke_action(payload.keys)
    return JSONResponse(result)


@app.post("/jobs", response_model=JobInfo)
async def create_job(payload: JobCreate, _: None = Depends(require_admin)) -> JobInfo:
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
async def list_jobs(_: None = Depends(require_admin)) -> List[JobInfo]:
    return [_serialize_job(job) for job in JOB_REGISTRY.list()]


@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str, _: None = Depends(require_admin)) -> JobInfo:
    job = JOB_REGISTRY.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("fort_gym.bench.api.server:app", host="0.0.0.0", port=8000, reload=True)
