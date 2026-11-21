"""FastAPI application entry point."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()  # Load .env before any other imports

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import JSONResponse

from src.api.core.config import get_settings
from src.api.core.database import init_db, check_db_health
from src.api.observability import get_event_bus, EventLevel
from src.api.observability.handlers import ConsoleHandler
from src.api.routes import (
    agent_play,
    admin,
    auth,
    bevy_games,
    games,
    godot_games,
    plugin_jobs,
    provider_connection,
    voice,
)

settings = get_settings()
logger = logging.getLogger(__name__)


def _filter_provider_setup_events(event, hint):
    """Credential entry must never be captured in Sentry errors or transactions."""
    url = str((event.get("request") or {}).get("url") or "")
    if "/provider-connection" in url or "/provider-connection" in str(event.get("transaction") or ""):
        return None
    return event


def setup_observability():
    """Configure observability handlers for the application."""
    # Determine log level from environment
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    log_level = EventLevel.DEBUG if debug_mode else EventLevel.INFO

    # Configure Python logging
    logging.basicConfig(
        level=logging.DEBUG if debug_mode else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    # Set up console handler for observability events
    console_handler = ConsoleHandler(min_level=log_level)
    event_bus = get_event_bus()
    event_bus.subscribe(console_handler.handle)

    # Initialize Sentry if DSN is configured.
    # By default, FastAPI's HTTPException is caught by the framework and
    # never reaches Sentry — so 404s/400s/etc. are invisible. We opt into
    # the full 4xx + 5xx range via failed_request_status_codes so triage
    # has the same surface in Sentry as the docker logs.
    if settings.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.1,
            send_default_pii=True,  # include request path + query in events
            before_send=_filter_provider_setup_events,
            before_send_transaction=_filter_provider_setup_events,
            integrations=[
                StarletteIntegration(failed_request_status_codes={*range(400, 600)}),
                FastApiIntegration(failed_request_status_codes={*range(400, 600)}),
            ],
        )

    logging.getLogger("tinyworlds").info(
        f"Observability configured: log_level={log_level.value}, debug_mode={debug_mode}"
    )


def _restore_claude_cli_auth() -> None:
    """Restore the Claude CLI config file from the latest backup if missing.

    The named docker volume `claude-auth` mounts at `/root/.claude/` (a
    directory) — which preserves session caches, history, and the auto-
    written backups under `/root/.claude/backups/.claude.json.backup.*`.
    But Claude's actual login token lives in the sibling file
    `/root/.claude.json`, which is OUTSIDE the volume and gets wiped on
    every container rebuild.

    On startup, if the config file is missing, restore from the newest
    backup in the volume. This survives indefinite rebuilds — no
    interactive `claude login` needed unless the token actually expires.
    """
    from pathlib import Path

    # The root home is only valid inside the production backend container.
    # Non-root development and CI processes must use their own home directory.
    cfg = Path.home() / ".claude.json"
    if cfg.exists():
        return
    backups_dir = Path.home() / ".claude" / "backups"
    if not backups_dir.is_dir():
        return
    backups = sorted(
        backups_dir.glob(".claude.json.backup.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for b in backups:
        # Skip tiny files (50 bytes ≈ an empty/stub backup; Claude writes
        # a one-line placeholder before populating). Real configs are
        # ~20 KB.
        if b.stat().st_size < 1000:
            continue
        try:
            cfg.write_bytes(b.read_bytes())
            cfg.chmod(0o600)
            logging.getLogger("tinyworlds").info(
                "Restored Claude CLI auth from backup: %s", b.name
            )
            return
        except OSError as e:
            logging.getLogger("tinyworlds").warning(
                "Failed to restore Claude CLI auth from %s: %s", b.name, e
            )
    logging.getLogger("tinyworlds").warning(
        "No usable Claude CLI auth backup found — game generation will fail until `claude login` runs"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup: Initialize observability and database
    if settings.REQUIRE_PRODUCTION_SECRETS:
        from sqlalchemy.engine import make_url
        from urllib.parse import urlsplit

        play_origin = urlsplit(settings.GAME_PLAY_ORIGIN)
        if (
            play_origin.scheme != "https"
            or not play_origin.netloc
            or play_origin.path
            or play_origin.query
            or play_origin.fragment
            or play_origin.username
            or play_origin.password
            or play_origin.netloc == urlsplit(settings.FRONTEND_URL).netloc
        ):
            raise RuntimeError("Production requires a separate GAME_PLAY_ORIGIN")
        if len(settings.SECRET_KEY) < 32 or settings.SECRET_KEY.lower().startswith(
            ("your-", "change-me", "changeme")
        ):
            raise RuntimeError(
                "Production requires a unique signing secret of at least 32 characters"
            )
        if (
            len(settings.LAUNCHER_TOKEN) < 32
            or settings.LAUNCHER_TOKEN == "dev-launcher-token"
            or settings.LAUNCHER_TOKEN.lower().startswith(
                ("your-", "change-me", "changeme")
            )
        ):
            raise RuntimeError(
                "Production requires a unique launcher token of at least 32 characters"
            )
        password = make_url(settings.DATABASE_URL).password
        if not password or len(password) < 16 or password == "tinyworlds":
            raise RuntimeError(
                "Production requires a database password of at least 16 characters"
            )
    setup_observability()
    if settings.AGENT_EXECUTION_MODE == "local":
        _restore_claude_cli_auth()
    await init_db()

    from pathlib import Path
    from src.api.services.game_jobs import recover_jobs, stop_jobs

    recover_jobs(Path(settings.GODOT_GAMES_DIR))
    yield
    await stop_jobs()
    from src.api.services.personal_provider import close_personal_providers
    await close_personal_providers()
    import asyncio
    from src.api.observability.agent_traces import flush_agent_traces

    try:
        await asyncio.to_thread(flush_agent_traces, settings)
    except Exception:
        logger.warning("Agent trace flush failed during shutdown")


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="TinyWorlds API — text → playable Godot/Bevy games in the browser via Claude Code",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers + 4xx/5xx access logging.
# uvicorn's default INFO line shows status but only as a one-liner; on
# triage we also want method, path, query, and timing for failures
# specifically so docker-log greps for "ERROR" / "WARN" surface real
# request failures. 2xx/3xx stay quiet (uvicorn already logs them at INFO).
_access_logger = logging.getLogger("tinyworlds.access")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    import time

    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    status = response.status_code
    if status >= 400:
        log_fn = _access_logger.error if status >= 500 else _access_logger.warning
        query = f"?{request.url.query}" if request.url.query else ""
        log_fn(
            "http %s %s%s -> %s (%dms)",
            request.method,
            request.url.path,
            query,
            status,
            elapsed_ms,
        )

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "/play" not in request.url.path:
        response.headers["X-Frame-Options"] = "DENY"
    return response


# Include routers
app.include_router(provider_connection.router, prefix=f"{settings.API_V1_PREFIX}/provider-connection", tags=["personal setup"])
app.include_router(agent_play.router, prefix=settings.API_V1_PREFIX)

app.include_router(
    auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["authentication"]
)

app.include_router(
    voice.router, prefix=f"{settings.API_V1_PREFIX}/voice", tags=["voice"]
)

app.include_router(
    godot_games.router, prefix=f"{settings.API_V1_PREFIX}/godot", tags=["godot"]
)

app.include_router(
    games.router, prefix=f"{settings.API_V1_PREFIX}/games", tags=["games"]
)

app.include_router(
    plugin_jobs.router, prefix=f"{settings.API_V1_PREFIX}/plugin", tags=["plugin"]
)

app.include_router(
    bevy_games.router, prefix=f"{settings.API_V1_PREFIX}/bevy", tags=["bevy"]
)

app.include_router(
    admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["admin"]
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TinyWorlds API", "docs": "/docs", "version": "1.0.0"}


@app.get("/health")
async def health():
    """Health check endpoint with database connectivity verification."""
    db_ok, db_msg = await check_db_health()
    body = {"status": "healthy" if db_ok else "unhealthy", "db": db_msg}
    if not db_ok:
        return JSONResponse(content=body, status_code=503)
    return body


@app.get("/api/v1/agent-status")
async def agent_status(force: bool = False):
    """Report whether the Claude Code CLI ("the agent") is logged in and able
    to run generations. Backed by a cached live `claude -p` probe.

    Public (no auth) so the site footer can poll it without a token. The TTL
    cache bounds probe cost regardless of poll volume. Pass ?force=1 to bypass
    the cache (e.g. right after a re-login).
    """
    import time as _time

    from src.api.services.agent_status import get_agent_status

    status = await get_agent_status(force=force)
    return {
        "online": status["online"],
        "detail": status["detail"],
        "cached": status["cached"],
        "age_seconds": max(0.0, _time.monotonic() - status["checked_at"]),
    }
