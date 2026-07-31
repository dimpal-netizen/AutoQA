"""Application settings, loaded from environment variables / .env.

Everything configurable lives here. Import the singleton:

    from app.core.config import settings
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[0]=core, [1]=app, [2]=backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Reads .env from the repo root, then backend/.env (the latter wins)."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "TestPilot AI"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    POSTGRES_USER: str = "testpilot"
    POSTGRES_PASSWORD: str = "testpilot"
    POSTGRES_DB: str = "testpilot"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # --- Security ---
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: str = ""

    # --- AI providers (Phase 4) ---
    LLM_PROVIDER: str = "claude"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # --- Test execution (Phase 5) ---
    STORAGE_PATH: str = "./storage"
    WORKSPACE_PATH: str = "./workspaces"
    TEST_TIMEOUT_SECONDS: int = 600
    # Comma-separated. Read it through `default_browsers`, not directly:
    # pydantic-settings tries to JSON-parse list-typed fields, which chokes on "a,b".
    DEFAULT_BROWSERS: str = "chromium,firefox,webkit"

    # --- CORS (Phase 8) ---
    CORS_ORIGINS: str = "http://localhost:3000"

    # ----------------------------------------------------------------
    # Derived values
    # ----------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """Sync SQLAlchemy URL (psycopg 3 driver)."""
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def default_browsers(self) -> list[str]:
        return [b.strip() for b in self.DEFAULT_BROWSERS.split(",") if b.strip()]

    @property
    def storage_dir(self) -> Path:
        """Absolute path for artifacts, regardless of the current working directory."""
        return self._resolve(self.STORAGE_PATH)

    @property
    def workspace_dir(self) -> Path:
        """Absolute path for per-run test workspaces."""
        return self._resolve(self.WORKSPACE_PATH)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
