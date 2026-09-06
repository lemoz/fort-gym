"""FastAPI server exposing admin and public fort-gym endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import threading
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    NoReturn,
    Optional,
    Tuple,
)
from urllib.parse import quote

try:  # pragma: no cover - M1b API target is POSIX/Linux
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from ..agent.base import AGENT_FACTORIES, Agent, RandomAgent
from ..config import get_settings
from ..env.keystroke_exec import execute_keystroke_action
from ..eval.fort_eval_easy_p1 import P1_PROTOCOL, validate_p1_declaration
from ..eval.protocol import EVALUATION_PROTOCOL_PATTERN
from ..eval.public_protocols import get_public_protocol, list_public_protocols
from ..run.jobs import JOB_REGISTRY
from ..run.jobs import JobInfo as RegistryJobInfo
from ..run.runner import run_once
from ..run.runtime_contract import ProviderPolicy
from ..run.storage import RUN_REGISTRY, ShareToken
from ..run.storage import RunInfo as RegistryRunInfo
from ..run.supervision_service import (
    SUPERVISION_MODE,
    LaunchEvidenceError,
    RunNotOwnedError,
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionConfigurationError,
    SupervisionRequestError,
    SupervisionService,
    SupervisionServiceError,
)
from .auth import require_admin
from .campaign_catalog import campaign_catalog
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
from .sse import ndjson_iter, sse_event
from .trace_preview import read_trace_preview

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

    if path in {"/public/worlds", "/public/results"} or (
        path.startswith("/public/runs/") and path.endswith("/social-card.png")
    ):
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
PUBLIC_SITE_URL = os.getenv("FORT_GYM_PUBLIC_SITE_URL", "https://fortgym.live").rstrip(
    "/"
)
SOCIAL_META_START = "<!-- SOCIAL_META_START -->"
SOCIAL_META_END = "<!-- SOCIAL_META_END -->"
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "stopped"})
_SSE_EVENT_PAGE_SIZE = 100
_SSE_POLL_INTERVAL_SECONDS = 0.1
_SSE_HEARTBEAT_SECONDS = 5.0
_SUPERVISION_SERVICE: Optional[SupervisionService] = None
_SUPERVISION_SERVICE_REGISTRY_ID: Optional[int] = None
_SUPERVISION_SERVICE_LOCK = threading.Lock()
_SUPERVISION_OWNER_FD: Optional[int] = None


def _acquire_supervision_api_owner(config: ServiceConfig) -> None:
    """Hold a process-lifetime lock so multi-worker API startup fails closed."""

    global _SUPERVISION_OWNER_FD
    if _SUPERVISION_OWNER_FD is not None:
        return
    if fcntl is None:
        raise SupervisionConfigurationError(
            "M1b API ownership requires POSIX file locking"
        )
    config.control_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = config.control_root / "api-owner.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        payload = json.dumps(
            {
                "schema": "fortgym.m1b-api-owner/v1",
                "pid": os.getpid(),
                "acquired_at": datetime.utcnow().isoformat() + "Z",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, payload + b"\n")
        os.fsync(descriptor)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise SupervisionConfigurationError(
            "another API process already owns M1b supervision"
        ) from exc
    except Exception:
        os.close(descriptor)
        raise
    _SUPERVISION_OWNER_FD = descriptor


def _release_supervision_api_owner() -> None:
    global _SUPERVISION_OWNER_FD
    descriptor = _SUPERVISION_OWNER_FD
    _SUPERVISION_OWNER_FD = None
    if descriptor is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _get_supervision_service() -> SupervisionService:
    """Return the explicitly enabled single-owner M1b service."""

    global _SUPERVISION_SERVICE, _SUPERVISION_SERVICE_REGISTRY_ID
    if os.environ.get("FORT_GYM_M1B_API_SINGLE_OWNER") != "1":
        raise SupervisionConfigurationError(
            "M1b API requires FORT_GYM_M1B_API_SINGLE_OWNER=1"
        )
    registry_id = id(RUN_REGISTRY)
    with _SUPERVISION_SERVICE_LOCK:
        if (
            _SUPERVISION_SERVICE is None
            or _SUPERVISION_SERVICE_REGISTRY_ID != registry_id
        ):
            config = ServiceConfig.from_environment()
            _acquire_supervision_api_owner(config)
            try:
                _SUPERVISION_SERVICE = SupervisionService(
                    registry=RUN_REGISTRY,
                    config=config,
                )
            except Exception:
                _release_supervision_api_owner()
                raise
            _SUPERVISION_SERVICE_REGISTRY_ID = registry_id
        return _SUPERVISION_SERVICE


def _reset_supervision_service_for_tests() -> None:
    global _SUPERVISION_SERVICE, _SUPERVISION_SERVICE_REGISTRY_ID
    with _SUPERVISION_SERVICE_LOCK:
        _SUPERVISION_SERVICE = None
        _SUPERVISION_SERVICE_REGISTRY_ID = None
        _release_supervision_api_owner()


def _provider_policy_from_request(
    payload: Any, service: SupervisionService
) -> ProviderPolicy | None:
    provider = getattr(payload, "provider", None)
    if provider is None:
        return None
    key = service.config.openrouter_api_key
    if not key:
        raise SupervisionConfigurationError(
            "dedicated FORT_GYM_M1B_OPENROUTER_API_KEY is unavailable"
        )
    return ProviderPolicy.openrouter(
        model=provider.model,
        provider_name=provider.provider_name,
        api_key=key,
        max_total_tokens=provider.max_total_tokens,
        max_cost_usd=provider.max_cost_usd,
    )


def _raise_supervision_http(exc: SupervisionServiceError) -> NoReturn:
    if isinstance(exc, SupervisionRequestError):
        status = 400
    elif isinstance(exc, SupervisionConfigurationError):
        status = 503
    elif isinstance(exc, RunNotOwnedError):
        status = 404
    elif isinstance(exc, LaunchEvidenceError):
        status = 500
    else:
        status = 500
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _bounded_environment_identity(identity: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose attested run identity without nonce, credentials, or host paths."""

    def scalar(value: Any) -> Any:
        return (
            value if value is None or type(value) in {str, bool, int, float} else None
        )

    def selected(
        name: str,
        fields: tuple[str, ...],
        *,
        string_sequences: tuple[str, ...] = (),
    ) -> Dict[str, Any]:
        value = identity.get(name)
        if not isinstance(value, Mapping):
            return {}
        bounded: Dict[str, Any] = {}
        for field in fields:
            if field not in value:
                continue
            item = value[field]
            if field in string_sequences:
                if isinstance(item, (list, tuple)) and all(
                    isinstance(entry, str) for entry in item
                ):
                    bounded[field] = list(item)
            elif item is None or type(item) in {str, bool, int, float}:
                bounded[field] = item
        return bounded

    return {
        "schema": scalar(identity.get("schema")),
        "run_id": scalar(identity.get("run_id")),
        "contract_sha256": scalar(identity.get("contract_sha256")),
        "runtime": selected(
            "runtime",
            (
                "classification",
                "source_reproducible",
                "image_manifest_sha256",
                "image_config_sha256",
                "image_archive_sha256",
            ),
        ),
        "seed": selected(
            "seed",
            ("tree_sha256", "world_sha256", "seed_save", "runtime_save"),
        ),
        "code_sha256": scalar(identity.get("code_sha256")),
        "rpc": selected("rpc", ("host", "port", "nonce_attested")),
        "scripted": scalar(identity.get("scripted")),
        "provider": selected(
            "provider",
            (
                "enabled",
                "route",
                "model",
                "provider_name",
                "base_url",
                "max_total_tokens",
                "max_cost_usd",
                "credential_present",
                "strict_supervised",
            ),
        ),
        "cotenancy": selected(
            "cotenancy",
            (
                "schema",
                "cohort_sha256",
                "cohort_size",
                "slot",
                "peer_run_ids",
            ),
            string_sequences=("peer_run_ids",),
        ),
    }


async def _reconcile_supervised_runs_on_startup() -> None:
    if os.environ.get("FORT_GYM_M1B_SUPERVISION_ENABLED") != "1":
        return
    service = _get_supervision_service()
    await asyncio.to_thread(service.reconcile_all)


app.router.add_event_handler("startup", _reconcile_supervised_runs_on_startup)


def _requested_event_cursor(request: Request, after_sequence: int) -> int:
    """Combine an explicit start cursor with the standard SSE reconnect cursor."""

    last_event_id = request.headers.get("last-event-id")
    if last_event_id is None or not last_event_id.strip():
        return after_sequence
    try:
        reconnect_cursor = int(last_event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid Last-Event-ID cursor"
        ) from exc
    if reconnect_cursor < 0:
        raise HTTPException(status_code=400, detail="Invalid Last-Event-ID cursor")
    return max(after_sequence, reconnect_cursor)


def _durable_sse_event(sequence: int, event_type: str, data: Any) -> str:
    """Preserve the legacy event/data frame while adding an SSE replay cursor."""

    return f"id: {sequence}\n{sse_event(event_type, data)}"


async def _stream_run_events(
    request: Request,
    run_id: str,
    *,
    after_sequence: int = 0,
    heartbeat: float = _SSE_HEARTBEAT_SECONDS,
    poll_interval: float = _SSE_POLL_INTERVAL_SECONDS,
) -> AsyncGenerator[str, None]:
    """Relay durable run events across worker processes and API restarts."""

    cursor = after_sequence
    registry = RUN_REGISTRY
    loop = asyncio.get_running_loop()
    last_frame_at = loop.time()
    try:
        while True:
            if await request.is_disconnected():
                return

            events = await asyncio.to_thread(
                registry.read_events_since,
                run_id,
                after_sequence=cursor,
                limit=_SSE_EVENT_PAGE_SIZE,
            )
            if events:
                for event in events:
                    if await request.is_disconnected():
                        return
                    cursor = event.sequence
                    payload = event.payload
                    yield _durable_sse_event(
                        event.sequence,
                        payload.get("t", "message"),
                        payload.get("data", {}),
                    )
                    last_frame_at = loop.time()
                continue

            record = await asyncio.to_thread(registry.get, run_id)
            if record is None:
                return
            if record.status in _TERMINAL_RUN_STATUSES:
                # Close only after a final post-terminal read. This prevents an
                # event committed between the empty poll and terminal-row read
                # from being skipped, assuming producers publish before they
                # terminalize the run row.
                if await asyncio.to_thread(
                    registry.read_events_since,
                    run_id,
                    after_sequence=cursor,
                    limit=1,
                ):
                    continue
                return

            now = loop.time()
            if now - last_frame_at >= heartbeat:
                yield sse_event(
                    "heartbeat", {"ts": datetime.utcnow().isoformat() + "Z"}
                )
                last_frame_at = now
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        return


def _html_file_response(filename: str) -> FileResponse:
    return FileResponse(
        WEB_ROOT / filename, media_type="text/html", headers=HTML_CACHE_HEADERS
    )


def _social_meta_html(
    *,
    title: str,
    description: str,
    canonical_path: str,
    image_path: str,
    image_alt: str,
) -> str:
    """Build crawler-visible metadata from trusted public fields."""

    canonical_url = f"{PUBLIC_SITE_URL}{canonical_path}"
    image_url = f"{PUBLIC_SITE_URL}{image_path}"
    values = {
        "title": html.escape(title, quote=True),
        "description": html.escape(description, quote=True),
        "canonical_url": html.escape(canonical_url, quote=True),
        "image_url": html.escape(image_url, quote=True),
        "image_alt": html.escape(image_alt, quote=True),
    }
    return "\n".join(
        [
            SOCIAL_META_START,
            f"<title>{values['title']}</title>",
            f'<meta name="description" content="{values["description"]}">',
            f'<link rel="canonical" href="{values["canonical_url"]}">',
            '<meta name="theme-color" content="#071009">',
            '<meta property="og:site_name" content="Fort Labs">',
            '<meta property="og:type" content="website">',
            '<meta property="og:locale" content="en_US">',
            f'<meta property="og:title" content="{values["title"]}">',
            f'<meta property="og:description" content="{values["description"]}">',
            f'<meta property="og:url" content="{values["canonical_url"]}">',
            f'<meta property="og:image" content="{values["image_url"]}">',
            f'<meta property="og:image:secure_url" content="{values["image_url"]}">',
            '<meta property="og:image:type" content="image/png">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            f'<meta property="og:image:alt" content="{values["image_alt"]}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{values["title"]}">',
            f'<meta name="twitter:description" content="{values["description"]}">',
            f'<meta name="twitter:image" content="{values["image_url"]}">',
            f'<meta name="twitter:image:alt" content="{values["image_alt"]}">',
            '<link rel="icon" type="image/svg+xml" href="/static/brand/favicon.svg">',
            '<link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png">',
            '<link rel="apple-touch-icon" sizes="180x180" href="/static/brand/apple-touch-icon.png">',
            SOCIAL_META_END,
        ]
    )


def _html_with_social_meta(filename: str, metadata: str) -> HTMLResponse:
    document = (WEB_ROOT / filename).read_text(encoding="utf-8")
    start = document.find(SOCIAL_META_START)
    end = document.find(SOCIAL_META_END)
    if start < 0 or end < start:
        raise RuntimeError(f"{filename} is missing its social metadata markers")
    end += len(SOCIAL_META_END)
    return HTMLResponse(
        document[:start] + metadata + document[end:],
        headers=HTML_CACHE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Static file serving for web UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=FileResponse)
async def serve_landing():
    """Serve the environment-lab landing page."""
    return _html_file_response("landing.html")


@app.get("/favicon.ico", response_class=FileResponse, include_in_schema=False)
async def serve_favicon():
    return FileResponse(
        WEB_ROOT / "static" / "brand" / "favicon-32.png",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/live", response_class=FileResponse)
async def serve_index():
    """Serve the public spectator UI (live viewer)."""
    return _html_file_response("index.html")


@app.get("/replay/{token}", response_class=RedirectResponse)
async def serve_visual_replay(token: str):
    """Canonicalize the legacy replay URL onto the short public permalink."""
    share = _require_share(token, scope="replay")
    if "export" not in share.scope:
        raise HTTPException(status_code=404, detail="Not found")
    return RedirectResponse(url=f"/r/{quote(token, safe='')}", status_code=308)


@app.get("/r/{token}", response_class=HTMLResponse)
async def serve_short_visual_replay(token: str):
    """Serve crawler-visible metadata and the public replay application."""
    share = _require_share(token, scope="replay")
    if "export" not in share.scope:
        raise HTTPException(status_code=404, detail="Not found")
    record = RUN_REGISTRY.get(share.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    from .social_cards import CARD_VERSION, public_model_label

    model = public_model_label(record.model)
    status = str(record.status).replace("_", " ")
    seed = record.seed_save or "an undeclared seed"
    try:
        preview = read_trace_preview(_artifacts_path(share.run_id))
    except FileNotFoundError:
        preview = {"step": None, "screen_status": "not_reported"}
    frame_step = preview.get("step")
    run_step = (
        max(record.step, frame_step) if isinstance(frame_step, int) else record.step
    )
    run_progress = (
        f"{run_step}/{record.max_steps}" if record.max_steps else str(run_step)
    )
    frame_note = (
        f" The pictured recorded frame is step {frame_step}."
        if isinstance(frame_step, int)
        else ""
    )
    encoded_token = quote(token, safe="")
    metadata = _social_meta_html(
        title=f"{model} Dwarf Fortress Replay | Fort Labs",
        description=(
            f"Watch the recorded Fort-Eval run by {model}: {status}, "
            f"run progress {run_progress}, on {seed}.{frame_note}"
        ),
        canonical_path=f"/r/{encoded_token}",
        image_path=f"/public/runs/{encoded_token}/social-card.png?v={CARD_VERSION}",
        image_alt=f"Recorded Dwarf Fortress gameplay from the {model} Fort-Eval run",
    )
    return _html_with_social_meta("index.html", metadata)


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


@app.get("/findings", response_class=FileResponse)
async def serve_findings():
    """Serve the curated public research findings UI."""
    return _html_file_response("findings.html")


@app.get("/protocols", response_class=FileResponse)
async def serve_protocols():
    """Serve the public protocol catalog UI."""
    return _html_file_response("protocols.html")


@app.get("/campaigns", response_class=FileResponse)
async def serve_campaigns() -> FileResponse:
    """Serve the campaign experiment tracking surface."""
    return _html_file_response("campaigns.html")


@app.get("/public/campaign-experiments")
async def public_campaign_experiments() -> JSONResponse:
    try:
        data = campaign_catalog()
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Campaign evidence is unavailable") from None
    return JSONResponse(data, headers=HTML_CACHE_HEADERS)


@app.get("/public/campaign-feed")
async def public_campaign_feed() -> JSONResponse:
    from .campaign_records import campaign_feed

    location = get_settings().FORT_GYM_PUBLIC_CAMPAIGN_DIR
    try:
        data = campaign_feed(Path(location) if location else None)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Campaign tracking is unavailable") from None
    return JSONResponse(data, headers=HTML_CACHE_HEADERS)


@app.get("/protocols/{slug}", response_class=HTMLResponse)
async def serve_protocol_detail(slug: str):
    """Serve protocol-specific metadata while the client resolves the detail body."""
    protocol = get_public_protocol(slug)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    encoded_slug = quote(protocol.slug, safe="")
    metadata = _social_meta_html(
        title=f"{protocol.name} Protocol | Fort Labs",
        description=protocol.summary,
        canonical_path=f"/protocols/{encoded_slug}",
        image_path=f"/static/social/{encoded_slug}.png?v=1",
        image_alt=f"Fort Labs preview for the {protocol.name} protocol",
    )
    return _html_with_social_meta("protocols.html", metadata)


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


def _serialize(
    record: RegistryRunInfo,
    *,
    service: SupervisionService | None = None,
) -> RunInfo:
    metadata = getattr(record, "metadata", {}) or {}
    summary = record.latest_summary or {}
    environment: Dict[str, Any] | None = None
    if getattr(record, "supervision_mode", None) == SUPERVISION_MODE:
        try:
            resolved_service = service or _get_supervision_service()
            environment = _bounded_environment_identity(
                resolved_service.environment_identity(record.run_id)
            )
        except SupervisionServiceError as exc:
            _raise_supervision_http(exc)
    return RunInfo(
        id=record.run_id,
        backend=record.backend,
        model=record.model,
        git_sha=getattr(record, "git_sha", None),
        seed_save=getattr(record, "seed_save", None),
        runtime_save=getattr(record, "runtime_save", None),
        preserve_save=getattr(record, "preserve_save", False),
        evaluation_protocol=getattr(record, "evaluation_protocol", None),
        supervision_mode=getattr(record, "supervision_mode", None),
        status=record.status,
        step=record.step,
        max_steps=record.max_steps,
        ticks_per_step=record.ticks_per_step,
        started_at=record.started_at,
        finished_at=record.ended_at,
        score=summary.get("total_score") or metadata.get("last_score"),
        environment=environment,
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
    "public_eligibility",
    "publication_status",
    "public_label",
    "task_verdict",
    "gameplay_outcome",
    "evaluation_validity",
    "provenance_completeness",
    "terminal_class",
    "g7",
    "score_version",
    "total_score",
    "survival_score",
    "steps",
    "duration_ticks",
    "campaign_progress",
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
        if evaluation_protocol == P1_PROTOCOL:
            # G7-v5 is an outcome vector and is calibration-only until its
            # live evidence activation. It must never enter this legacy scalar
            # overview, even if an old/manual share token exists.
            continue
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
        groups.setdefault(key, {}).setdefault(record.model, []).append(
            (score, share.token)
        )

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
                                sum(score for score, _token in scored_runs)
                                / len(scored_runs),
                                2,
                            ),
                            best_score=round(
                                max(score for score, _token in scored_runs), 2
                            ),
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


def _protocol_is_calibration(slug: str | None) -> bool:
    definition = get_public_protocol(slug) if slug else None
    return bool(definition is not None and definition.status == "calibration")


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


_REPORTED_OUTCOMES = {"pass", "fail", "unknown"}


def _reported_outcome(value: Any) -> str | None:
    """Return a declared public outcome without promoting an unrecognized value."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in _REPORTED_OUTCOMES else None


def _reported_g7_outcome(summary: Dict[str, Any]) -> str | None:
    gate = summary.get("g7")
    if not isinstance(gate, dict):
        # Older public summaries used the pre-P1 field name.
        gate = summary.get("g7_gate")
    return _reported_outcome(gate.get("status")) if isinstance(gate, dict) else None


def _g7_evidence_is_complete(summary: Dict[str, Any]) -> bool:
    """Require the gate's evidence predicate without requiring a successful gate."""

    gate = summary.get("g7")
    if not isinstance(gate, dict):
        return False
    criteria = gate.get("criteria")
    evidence = criteria.get("evidence") if isinstance(criteria, dict) else None
    return isinstance(evidence, dict) and evidence.get("status") == "pass"


def _p1_integrity_is_complete(summary: Dict[str, Any]) -> bool:
    attestation = summary.get("integrity_attestation")
    return bool(isinstance(attestation, dict) and attestation.get("status") == "pass")


def _v5_publication_is_complete(summary: Dict[str, Any]) -> bool:
    """Accept valid task failures but never incomplete or calibration evidence."""

    publication = summary.get("publication_status")
    return bool(
        isinstance(publication, dict)
        and publication.get("status") == "eligible"
        and publication.get("evaluation_validity") == "pass"
        and publication.get("provenance_completeness") == "pass"
        and publication.get("provider_telemetry_complete") is True
        and _p1_integrity_is_complete(summary)
    )


def _public_label(summary: Dict[str, Any]) -> str | None:
    label = summary.get("public_label")
    if not isinstance(label, str) or not label.strip() or label != label.strip():
        return None
    return label


def _combined_outcome(outcomes: List[str]) -> str:
    """Keep mixed terminal outcomes visible instead of suppressing a failure."""

    return outcomes[0] if len(set(outcomes)) == 1 else "mixed"


def _protocol_comparison_groups(
    items: List[Tuple[RegistryRunInfo, ShareToken]],
    protocol_definition: Any,
) -> List[PublicComparisonGroup]:
    """Build comparisons only from complete declared protocol provenance."""

    if protocol_definition.status == "calibration":
        return []

    declared_fields = list(protocol_definition.comparability_fields)
    group_fields = [field for field in declared_fields if field != "model_digest"]
    non_scalar = str(protocol_definition.slug).endswith("g7-v5")
    response_fields = ["evaluation_protocol", *group_fields]
    if not non_scalar:
        response_fields.append("score_version")
    strict_publication = bool(protocol_definition.requires_public_eligibility)
    groups: Dict[Tuple[object, ...], Dict[Tuple[str, str], List[Tuple[Any, ...]]]] = {}

    for record, share in items:
        allowed_statuses = (
            {"completed", "failed"} if strict_publication else {"completed"}
        )
        if (
            record.status not in allowed_statuses
            or record.backend != "dfhack"
            or not {"replay", "export"}.issubset(share.scope)
            or not _has_replay_artifact(record.run_id)
        ):
            continue
        summary = record.latest_summary
        if (
            not isinstance(summary, dict)
            or summary.get("evaluation_protocol") != record.evaluation_protocol
        ):
            continue
        if strict_publication and summary.get("public_eligibility") != "eligible":
            continue
        score_version = summary.get("score_version")
        total_score = summary.get("total_score")
        values: Dict[str, str] = {}
        complete = non_scalar or (
            type(score_version) is int
            and score_version > 0
            and not isinstance(total_score, bool)
        )
        for field in declared_fields:
            value = summary.get(field)
            if not isinstance(value, str) or not value.strip():
                complete = False
                break
            value = value.strip()
            expected = protocol_definition.comparability_defaults.get(field)
            if (
                expected
                and expected not in _UNRESOLVED_PROTOCOL_VALUES
                and value != expected
            ):
                complete = False
                break
            if value in _UNRESOLVED_PROTOCOL_VALUES:
                complete = False
                break
            values[field] = value
        if not complete or values.get("fort_gym_commit") != record.git_sha:
            continue
        score: float | None = None
        if not non_scalar:
            try:
                score = float(total_score)
            except (TypeError, ValueError):
                continue
        key_values: Tuple[object, ...] = (
            record.evaluation_protocol,
            *(values[field] for field in group_fields),
            *(() if non_scalar else (score_version,)),
        )
        if strict_publication:
            public_label = _public_label(summary)
            g7_outcome = _reported_g7_outcome(summary)
            if (
                not (
                    _v5_publication_is_complete(summary)
                    if non_scalar
                    else _g7_evidence_is_complete(summary)
                )
                or not _p1_integrity_is_complete(summary)
                or public_label is None
                or g7_outcome is None
            ):
                continue
            task_verdict = _reported_outcome(summary.get("task_verdict")) or g7_outcome
            model_key = (values["model_digest"], public_label)
            scored_run: Tuple[Any, ...] = (
                score,
                share.token,
                task_verdict,
                g7_outcome,
            )
        else:
            model_key = (values["model_digest"], "")
            scored_run = (score, share.token)
        groups.setdefault(key_values, {}).setdefault(model_key, []).append(scored_run)

    response: List[PublicComparisonGroup] = []
    for key, scores_by_model in groups.items():
        response.append(
            PublicComparisonGroup(
                comparability=dict(zip(response_fields, key, strict=True)),
                model_results=sorted(
                    [
                        _public_model_result(
                            model_digest=model_digest,
                            public_label=public_label or None,
                            scored_runs=scored_runs,
                            strict_publication=strict_publication,
                            non_scalar=non_scalar,
                        )
                        for (
                            model_digest,
                            public_label,
                        ), scored_runs in scores_by_model.items()
                    ],
                    key=lambda result: (
                        result.public_label or "",
                        result.model_digest or "",
                        result.mean_score or 0.0,
                    ),
                    reverse=True,
                ),
            )
        )
    return sorted(
        response,
        key=lambda group: (
            group.comparability.get("score_version", 0),
            group.comparability["evaluation_protocol"],
        ),
        reverse=True,
    )


def _public_model_result(
    *,
    model_digest: str,
    public_label: str | None,
    scored_runs: List[Tuple[Any, ...]],
    strict_publication: bool,
    non_scalar: bool = False,
) -> PublicModelResult:
    """Serialize either a legacy P0 row or a strict P1 public report row."""

    numeric_runs = [run for run in scored_runs if run[0] is not None]
    scores = [float(run[0]) for run in numeric_runs]
    result = PublicModelResult(
        model=public_label or model_digest,
        run_count=len(scored_runs),
        result_kind="outcome_vector" if non_scalar else None,
    )
    if scores and not non_scalar:
        result.mean_score = round(sum(scores) / len(scores), 2)
        result.best_score = round(max(scores), 2)
        result.best_token = max(numeric_runs, key=lambda item: float(item[0]))[1]
    elif scored_runs:
        result.representative_token = str(scored_runs[0][1])
    if not strict_publication:
        return result
    outcomes = [str(run[3]) for run in scored_runs]
    result.model_digest = model_digest
    result.public_label = public_label
    result.task_verdict = _combined_outcome([str(run[2]) for run in scored_runs])
    result.g7_outcomes = {
        outcome: outcomes.count(outcome)
        for outcome in sorted(_REPORTED_OUTCOMES)
        if outcome in outcomes
    }
    return result


def _serialize_job(job: RegistryJobInfo) -> JobInfo:
    data = job.model_dump() if hasattr(job, "model_dump") else job.dict()
    return JobInfo(**data)


def _require_share(token: str, *, scope: Optional[str] = None) -> ShareToken:
    share = RUN_REGISTRY.get_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="Not found")
    record = RUN_REGISTRY.get(share.run_id)
    if record is None or _protocol_is_calibration(record.evaluation_protocol):
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
    "dfhack-governed-llm-fable5": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-gpt56-sol": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-glm5v": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-gpt55-vision": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-kimi-vision": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-minimax-vision": "fort_gym.bench.agent.governed_llm",
    "dfhack-governed-llm-minimax-canary": "fort_gym.bench.agent.governed_llm",
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
async def create_run(
    payload: RunCreateRequest, _: None = Depends(require_admin)
) -> RunInfo:
    if payload.publish and _protocol_is_calibration(payload.evaluation_protocol):
        raise HTTPException(
            status_code=400,
            detail="Calibration runs cannot be published; set publish=false",
        )

    try:
        validate_p1_declaration(
            protocol=payload.evaluation_protocol,
            backend=payload.backend,
            model=payload.model,
            seed_save=payload.seed_save,
            runtime_save=payload.runtime_save,
            preserve_save=payload.preserve_save,
            max_steps=payload.max_steps,
            ticks_per_step=payload.ticks_per_step,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.supervision_mode == SUPERVISION_MODE:
        try:
            service = _get_supervision_service()
            provider = _provider_policy_from_request(payload, service)
            launch = service.launch_async(
                SupervisedRunRequest(
                    backend=payload.backend,
                    model=payload.model,
                    max_steps=payload.max_steps,
                    ticks_per_step=payload.ticks_per_step,
                    cohort_size=1,
                    safe=payload.safe is True,
                    evaluation_protocol=payload.evaluation_protocol,
                    preserve_save=payload.preserve_save,
                    seed_save=payload.seed_save,
                    runtime_save_prefix=payload.runtime_save_prefix,
                    provider_policy=provider,
                )
            )
        except SupervisionServiceError as exc:
            _raise_supervision_http(exc)
        launch_ids = tuple(launch.run_ids)
        launch_records = tuple(launch.records)
        launch_record_ids = tuple(
            getattr(record, "run_id", None) for record in launch_records
        )
        launch_valid = (
            len(launch_ids) == 1
            and len(launch_records) == 1
            and isinstance(launch_ids[0], str)
            and launch_ids[0]
            and launch_record_ids == launch_ids
        )
        persisted = RUN_REGISTRY.get(launch_ids[0]) if launch_valid else None
        if (
            not launch_valid
            or persisted is None
            or persisted.supervision_mode != SUPERVISION_MODE
        ):
            invalid_launch = RuntimeError(
                "M1b single-run launch did not produce one matching persisted row"
            )
            candidate_ids = [
                run_id
                for run_id in (*launch_ids, *launch_record_ids)
                if isinstance(run_id, str) and run_id
            ]
            for run_id in dict.fromkeys(candidate_ids):
                record = RUN_REGISTRY.get(run_id)
                if (
                    record is not None
                    and record.status == "pending"
                    and record.supervision_mode == SUPERVISION_MODE
                ):
                    try:
                        service.terminalize_unstarted(
                            run_id,
                            invalid_launch,
                            code="api_single_launch_invalid",
                        )
                    except Exception:
                        pass
            raise HTTPException(
                status_code=500,
                detail="M1b single-run reservation returned an invalid cohort",
            )
        return _serialize(persisted, service=service)

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

    if payload.publish:
        # Permanent publication is an explicit per-request opt-in. Calibration
        # requests are rejected before run creation above.
        RUN_REGISTRY.create_share(
            record.run_id, scope=["live", "replay", "export"], ttl_seconds=None
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
    run_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    _: None = Depends(require_admin),
) -> StreamingResponse:
    if RUN_REGISTRY.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    cursor = _requested_event_cursor(request, after_sequence)
    generator = _stream_run_events(request, run_id, after_sequence=cursor)
    return StreamingResponse(generator, media_type="text/event-stream")


@app.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.supervision_mode == SUPERVISION_MODE:
        raise HTTPException(
            status_code=409,
            detail="Process-supervised runs do not support interactive pause",
        )
    RUN_REGISTRY.set_status(run_id, status="paused")
    return JSONResponse({"status": "paused", "run_id": run_id})


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, _: None = Depends(require_admin)) -> JSONResponse:
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.supervision_mode == SUPERVISION_MODE:
        raise HTTPException(
            status_code=409,
            detail="Process-supervised runs do not support interactive resume",
        )
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
    record = RUN_REGISTRY.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.supervision_mode == SUPERVISION_MODE:
        raise HTTPException(
            status_code=409,
            detail="M1b process-supervised runs cannot be published or shared",
        )
    if _protocol_is_calibration(record.evaluation_protocol):
        raise HTTPException(
            status_code=409,
            detail="Calibration runs cannot be shared on public surfaces",
        )
    scope = body.scope or ["live", "replay", "export"]
    try:
        share = RUN_REGISTRY.create_share(
            run_id, scope=scope, ttl_seconds=body.ttl_seconds
        )
    except KeyError as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return {
        "token": share.token,
        "expires_at": share.expires_at,
        "scope": sorted(share.scope),
    }


@app.get("/runs/{run_id}/export/trace")
async def export_trace(
    run_id: str, _: None = Depends(require_admin)
) -> StreamingResponse:
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
    return [
        _serialize_public(record, share)
        for record, share in items
        if not _protocol_is_calibration(record.evaluation_protocol)
    ]


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
        excluded_evaluation_protocols=(
            {P1_PROTOCOL} if _protocol_is_calibration(P1_PROTOCOL) else set()
        ),
    )
    return PublicRunsPage(
        items=[_serialize_public(record, share) for record, share in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/public/overview",
    response_model=PublicOverview,
    response_model_exclude_none=True,
)
async def public_overview(
    recent_limit: int = Query(default=20, ge=1, le=100),
) -> PublicOverview:
    active_items, recent_items, terminal_items = RUN_REGISTRY.public_overview_runs(
        recent_limit=recent_limit
    )
    active_items = [
        item
        for item in active_items
        if not _protocol_is_calibration(item[0].evaluation_protocol)
    ]
    recent_items = [
        item
        for item in recent_items
        if not _protocol_is_calibration(item[0].evaluation_protocol)
    ]
    return PublicOverview(
        generated_at=datetime.utcnow(),
        active_runs=[
            _serialize_public(record, share) for record, share in active_items
        ],
        recent_runs=[
            _serialize_public(record, share) for record, share in recent_items
        ],
        comparability_fields=_COMPARABILITY_FIELDS,
        comparison_groups=_comparison_groups(terminal_items),
    )


@app.get(
    "/public/results",
    response_model=PublicResults,
    response_model_exclude_none=True,
)
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
    if protocol_definition.status == "calibration":
        return PublicResults(
            generated_at=datetime.utcnow(),
            protocol=evaluation_protocol,
            publication_stage="calibration",
            comparability_fields=[
                "evaluation_protocol",
                *protocol_definition.comparability_fields,
            ],
            candidate_run_count=0,
            eligible_run_count=0,
            excluded_run_count=0,
            comparison_groups=[],
        )
    candidates, truncated = RUN_REGISTRY.list_public_for_protocol(evaluation_protocol)
    if truncated:
        raise HTTPException(
            status_code=503, detail="Protocol cohort exceeds publication limit"
        )
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
        publication_stage=(
            "P1 discovery" if protocol_definition.requires_public_eligibility else None
        ),
        comparability_fields=[
            "evaluation_protocol",
            *protocol_definition.comparability_fields,
            *([] if evaluation_protocol.endswith("g7-v5") else ["score_version"]),
        ],
        candidate_run_count=candidate_run_count,
        eligible_run_count=eligible_run_count,
        excluded_run_count=candidate_run_count - eligible_run_count,
        comparison_groups=comparison_groups,
    )


@app.get("/public/protocols", response_model=List[PublicProtocol])
async def public_protocols() -> List[PublicProtocol]:
    """List the public, allowlisted Fort-Eval profiles."""

    return [
        PublicProtocol(**entry.to_public_dict()) for entry in list_public_protocols()
    ]


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
    return RUN_REGISTRY.public_leaderboard(
        limit,
        excluded_evaluation_protocols=(
            {P1_PROTOCOL} if _protocol_is_calibration(P1_PROTOCOL) else set()
        ),
    )


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
        excluded_evaluation_protocols=(
            {P1_PROTOCOL} if _protocol_is_calibration(P1_PROTOCOL) else set()
        ),
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
    latest_summary = (
        record.latest_summary if isinstance(record.latest_summary, dict) else {}
    )
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


@app.get("/public/runs/{token}/social-card.png", response_class=Response)
async def public_run_social_card(token: str, request: Request) -> Response:
    """Render a shareable card from public metadata and the bounded replay frame."""

    share = _require_share(token, scope="replay")
    if "export" not in share.scope:
        raise HTTPException(status_code=404, detail="Not found")
    record = RUN_REGISTRY.get(share.run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        preview = read_trace_preview(_artifacts_path(share.run_id))
    except FileNotFoundError:
        preview = {
            "step": record.step,
            "screen_text": None,
            "screen_status": "not_reported",
            "inspected_records": 0,
        }

    from .social_cards import render_run_social_card

    payload = await asyncio.to_thread(render_run_social_card, record, preview)
    etag = f'"{hashlib.sha256(payload).hexdigest()}"'
    cache_control = "private, no-store, max-age=0"
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "Cache-Control": cache_control,
                "ETag": etag,
                "X-Content-Type-Options": "nosniff",
            },
        )
    return Response(
        content=payload,
        media_type="image/png",
        headers={
            "Cache-Control": cache_control,
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/public/runs/{token}/events/stream")
async def public_stream(
    token: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
) -> StreamingResponse:
    share = _require_share(token, scope="live")
    if RUN_REGISTRY.get(share.run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    cursor = _requested_event_cursor(request, after_sequence)
    return StreamingResponse(
        _stream_run_events(request, share.run_id, after_sequence=cursor),
        media_type="text/event-stream",
    )


@app.get("/public/runs/{token}/events/replay")
async def public_replay(
    token: str, request: Request, speed: int = 4
) -> StreamingResponse:
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


def _capture_screenshot(run_id: str | None = None) -> Dict[str, object]:
    """Capture the DF screen, reconnecting once when the cached socket is stale."""
    supervised_dfhack_active = any(
        record.supervision_mode == SUPERVISION_MODE
        and record.backend == "dfhack"
        and record.status not in _TERMINAL_RUN_STATUSES
        for record in RUN_REGISTRY.list()
    )
    if run_id is not None:
        record = RUN_REGISTRY.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if record.supervision_mode == SUPERVISION_MODE:
            try:
                return _get_supervision_service().capture_screen(run_id)
            except SupervisionRequestError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except SupervisionServiceError as exc:
                _raise_supervision_http(exc)
        if supervised_dfhack_active:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Global screenshots are disabled while a process-supervised "
                    "DFHack run is active"
                ),
            )
    elif supervised_dfhack_active:
        raise HTTPException(
            status_code=409,
            detail="run_id is required while a process-supervised DFHack run is active",
        )

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
async def admin_screenshot(
    run_id: Optional[str] = Query(default=None),
    _: None = Depends(require_admin),
) -> JSONResponse:
    """Capture the current DF screen (admin endpoint)."""
    return JSONResponse(await asyncio.to_thread(_capture_screenshot, run_id))


@app.get("/public/runs/{token}/screenshot")
async def public_screenshot(token: str) -> JSONResponse:
    """Capture the current DF screen for a public run (requires 'live' scope)."""
    share = _require_share(token, scope="live")
    return JSONResponse(await asyncio.to_thread(_capture_screenshot, share.run_id))


@app.post("/admin/keys")
async def admin_keys(
    payload: AdminKeysRequest, _: None = Depends(require_admin)
) -> JSONResponse:
    """Send raw DF interface keys for manual admin control."""
    if any(
        record.supervision_mode == SUPERVISION_MODE
        and record.backend == "dfhack"
        and record.status not in _TERMINAL_RUN_STATUSES
        for record in RUN_REGISTRY.list()
    ):
        raise HTTPException(
            status_code=409,
            detail="Global keystrokes are disabled during process-supervised runs",
        )
    from ..config import get_settings

    settings = get_settings()
    if not settings.DFHACK_ENABLED:
        raise HTTPException(status_code=400, detail="DFHack backend disabled")
    result = execute_keystroke_action(payload.keys)
    return JSONResponse(result)


@app.post("/jobs", response_model=JobInfo)
async def create_job(payload: JobCreate, _: None = Depends(require_admin)) -> JobInfo:
    if payload.supervision_mode == SUPERVISION_MODE:
        try:
            validate_p1_declaration(
                protocol=payload.evaluation_protocol,
                backend=payload.backend,
                model=payload.model,
                seed_save=payload.seed_save,
                runtime_save=payload.runtime_save_prefix,
                preserve_save=payload.preserve_save,
                max_steps=payload.max_steps,
                ticks_per_step=payload.ticks_per_step,
            )
            service = _get_supervision_service()
            provider = _provider_policy_from_request(payload, service)
            launch = service.reserve(
                SupervisedRunRequest(
                    backend=payload.backend,
                    model=payload.model,
                    max_steps=payload.max_steps,
                    ticks_per_step=payload.ticks_per_step,
                    cohort_size=payload.n,
                    safe=payload.safe is True,
                    evaluation_protocol=payload.evaluation_protocol,
                    preserve_save=payload.preserve_save,
                    seed_save=payload.seed_save,
                    runtime_save_prefix=payload.runtime_save_prefix,
                    provider_policy=provider,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SupervisionServiceError as exc:
            _raise_supervision_http(exc)

        launch_ids = tuple(launch.run_ids)
        launch_records = tuple(launch.records)
        launch_record_ids = tuple(
            getattr(record, "run_id", None) for record in launch_records
        )
        launch_shape_valid = (
            len(launch_ids) == payload.n
            and len(launch_records) == payload.n
            and all(isinstance(run_id, str) and run_id for run_id in launch_ids)
            and len(set(launch_ids)) == payload.n
            and launch_record_ids == launch_ids
        )
        persisted_records = (
            tuple(RUN_REGISTRY.get(run_id) for run_id in launch_ids)
            if launch_shape_valid
            else ()
        )
        launch_valid = launch_shape_valid and all(
            record is not None and record.supervision_mode == SUPERVISION_MODE
            for record in persisted_records
        )
        if not launch_valid:
            invalid_launch = RuntimeError(
                "M1b job reservation did not produce the requested persisted cohort"
            )
            candidate_ids = [
                run_id
                for run_id in (*launch_ids, *launch_record_ids)
                if isinstance(run_id, str) and run_id
            ]
            for run_id in dict.fromkeys(candidate_ids):
                record = RUN_REGISTRY.get(run_id)
                if (
                    record is not None
                    and record.status == "pending"
                    and record.supervision_mode == SUPERVISION_MODE
                ):
                    try:
                        service.terminalize_unstarted(
                            run_id,
                            invalid_launch,
                            code="api_job_launch_invalid",
                        )
                    except Exception:
                        pass
            raise HTTPException(
                status_code=500,
                detail="M1b job reservation returned an invalid cohort",
            )

        job: RegistryJobInfo | None = None
        try:
            job = JOB_REGISTRY.create(
                model=payload.model,
                backend=payload.backend,
                n=payload.n,
                parallelism=payload.parallelism,
                isolation_supervised=True,
            )

            def _terminalize_preclaim_execution_failure(
                run_id: str, exc: BaseException
            ) -> None:
                record = RUN_REGISTRY.get(run_id)
                if record is not None and record.status == "pending":
                    service.terminalize_unstarted(
                        run_id,
                        exc,
                        code="job_manager_execution_failed_before_claim",
                    )

            JOB_REGISTRY.start_reserved(
                job.job_id,
                launch.run_ids,
                lambda run_id: service.run_reserved(run_id).status,
                on_launch_failure=lambda run_id, exc: service.terminalize_unstarted(
                    run_id,
                    exc,
                    code="job_manager_thread_start_failed",
                ),
                on_execution_failure=_terminalize_preclaim_execution_failure,
                on_barrier_failure=lambda run_id, exc: service.terminalize_unstarted(
                    run_id,
                    exc,
                    code="job_cohort_start_barrier_failed",
                ),
                start_barrier=True,
            )
        except Exception as exc:  # noqa: BLE001 - compensate reserved rows
            if job is not None:
                try:
                    JOB_REGISTRY.fail_activation(job.job_id)
                except Exception:
                    pass
            for run_id in launch.run_ids:
                record = RUN_REGISTRY.get(run_id)
                if record is not None and record.status == "pending":
                    try:
                        service.terminalize_unstarted(
                            run_id,
                            exc,
                            code="job_activation_failed",
                        )
                    except Exception:
                        pass
            raise HTTPException(
                status_code=500,
                detail="M1b job activation failed after cohort reservation",
            ) from exc
        activated_job = JOB_REGISTRY.get(job.job_id)
        if activated_job is None:
            missing_job = RuntimeError(
                "M1b job metadata disappeared after scheduler activation"
            )
            for run_id in launch_ids:
                record = RUN_REGISTRY.get(run_id)
                if record is None or record.status in _TERMINAL_RUN_STATUSES:
                    continue
                if record.status == "pending":
                    try:
                        service.terminalize_unstarted(
                            run_id,
                            missing_job,
                            code="api_job_registry_missing",
                        )
                    except Exception:
                        pass
                else:
                    RUN_REGISTRY.request_stop(run_id)
            raise HTTPException(
                status_code=500,
                detail="M1b job activation lost its scheduler metadata",
            )
        return _serialize_job(activated_job)

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
