"""FastAPI application entry point.

Run it with:
    poetry run uvicorn app.main:app --reload
Then open http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import settings

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
    yield
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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health lives at the root so probes don't depend on the API version.
    app.include_router(health.router)

    # Feature routers land here as each phase is built:
    #   app.include_router(auth.router,     prefix=settings.API_V1_PREFIX)
    #   app.include_router(projects.router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
