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
    APP_NAME: str = "AutoQA"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    POSTGRES_USER: str = "autoqa"
    POSTGRES_PASSWORD: str = "autoqa"
    POSTGRES_DB: str = "autoqa"
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

    # --- Code generation ---
    # Generate a test suite the moment a recording stops. Deterministic and
    # fast, so there is no reason to make the user ask for it.
    AUTO_GENERATE_ON_STOP: bool = True
    # Where generated scripts are written for the user to open in VS Code.
    # The web app shows the path; reviewing and editing happens in the editor.
    GENERATED_PATH: str = "./generated"

    # --- Test execution (Phase 5) ---
    STORAGE_PATH: str = "./storage"
    WORKSPACE_PATH: str = "./workspaces"
    TEST_TIMEOUT_SECONDS: int = 600
    # Wall-clock ceiling for one browser's pytest process. A generated test can
    # hang on a page that never loads, and without this the run never finishes.
    RUN_TIMEOUT_SECONDS: int = 900
    # Delete each run's workspace afterwards. Turn off to inspect exactly what
    # was executed when a run behaves strangely.
    CLEAN_WORKSPACES: bool = True
    # How many browsers may run at once. Each is a browser plus a Python
    # process, so this is a memory ceiling as much as a speed setting.
    MAX_PARALLEL_BROWSERS: int = 3
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
    def cors_origin_regex(self) -> str | None:
        """In development, accept the app on any local address and port.

        CORS matches the Origin header as an exact string, so a list containing
        only "http://localhost:3000" rejects the very same app opened at
        127.0.0.1, [::1], or a LAN IP — which surfaces in the browser as an
        unhelpful "Failed to fetch". Production still uses the explicit list.
        """
        if self.is_production:
            return None
        return (
            r"http://(localhost|127\.0\.0\.1|\[::1\]"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?"
        )

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
    def generated_dir(self) -> Path:
        """Absolute path where generated scripts land for editing in VS Code."""
        return self._resolve(self.GENERATED_PATH)

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
