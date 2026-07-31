"""Health checks.

/health        — is the process alive? (never touches the database)
/health/ready  — are Postgres and Redis reachable? Returns 503 if not.
"""

import redis
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness. Always 200 while the app is running."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    """Readiness. 200 only when every dependency answers."""
    checks = {"database": _check_database(), "redis": _check_redis()}
    healthy = all(v == "ok" for v in checks.values())

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if healthy else "degraded", "checks": checks}


def _check_database() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


def _check_redis() -> str:
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        client.close()
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"
