"""FastAPI application entry point.

Run it with (from backend/):
    poetry run python -m app
Then open http://localhost:5022/docs
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    analysis,
    auth,
    bugs,
    extension,
    health,
    projects,
    recordings,
    reports,
    sample_files,
    runs,
    test_cases,
)
from app.core.config import settings
from app.services import browser_recorder
from app.services.exceptions import ServiceError
from app.services.execution_service import ExecutionService

STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown. Later phases hook the Redis event subscriber in here."""
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    logger.info("%s starting (environment=%s)", settings.APP_NAME, settings.ENVIRONMENT)

    # A run lives in a thread, so a restart leaves it stuck at "running" and the
    # UI spins forever on something that is already dead.
    orphaned = ExecutionService.reap_orphans()
    if orphaned:
        logger.warning("Marked %d run(s) as interrupted by a restart", orphaned)
    yield
    # Never leave an orphan Chromium process behind on reload or shutdown.
    await browser_recorder.close_all()
    logger.info("%s shutting down", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="AI-powered autonomous test automation platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Dev only — see Settings.cors_origin_regex. Without it, opening the app
        # at 127.0.0.1 instead of localhost fails every request.
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Services raise ServiceError; this turns it into a proper HTTP response so
    # no service ever has to import fastapi.
    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.message}, headers=headers
        )

    # recorder.js lives here so Playwright can inject it and the web app can
    # load it — one copy, no drift between the two paths.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Health lives at the root so probes don't depend on the API version.
    app.include_router(health.router)

    app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
    app.include_router(projects.router, prefix=settings.API_V1_PREFIX)
    app.include_router(recordings.router, prefix=settings.API_V1_PREFIX)
    app.include_router(test_cases.router, prefix=settings.API_V1_PREFIX)
    app.include_router(runs.router, prefix=settings.API_V1_PREFIX)
    app.include_router(analysis.router, prefix=settings.API_V1_PREFIX)
    app.include_router(bugs.router, prefix=settings.API_V1_PREFIX)
    app.include_router(reports.router, prefix=settings.API_V1_PREFIX)
    app.include_router(sample_files.router, prefix=settings.API_V1_PREFIX)
    app.include_router(extension.router, prefix=settings.API_V1_PREFIX)

    # Later phases add: integrations, agent, websocket.

    return app


app = create_app()
