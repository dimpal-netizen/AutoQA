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
    # One of: claude, openai, gemini. Only the matching key is needed; every
    # AI feature talks to the LLMClient interface, never to a vendor SDK.
    LLM_PROVIDER: str = "claude"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Override when the default model is not available to your key. Gemini
    # model ids change often, so this is a setting rather than a constant.
    GEMINI_MODEL: str = ""
    # Same, for Claude - though the useful reason here is cost rather than
    # churn: dropping to Sonnet or Haiku for a week is a line in .env. Prices
    # and per-model request rules travel with it; see app/ai/claude.py.
    CLAUDE_MODEL: str = ""

    # --- Code generation ---
    # Generate a test suite the moment a recording stops. Deterministic and
    # fast, so there is no reason to make the user ask for it.
    AUTO_GENERATE_ON_STOP: bool = True
    # Where generated scripts are written for the user to open in VS Code.
    # The web app shows the path; reviewing and editing happens in the editor.
    #
    # NOTE THE `../`. Everything AutoQA writes at runtime lives OUTSIDE
    # `backend/`, and that is load-bearing rather than tidiness:
    # `uvicorn --reload` watches the directory it was started from for *.py
    # changes. Generated suites and run workspaces are full of .py files, so
    # writing them under backend/ restarts the server every time a recording
    # is generated or a test is run - killing the run that triggered it.
    GENERATED_PATH: str = "../generated"

    # --- Test execution (Phase 5) ---
    STORAGE_PATH: str = "../.autoqa/storage"
    WORKSPACE_PATH: str = "../.autoqa/workspaces"
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
    # Pause between actions when running headed, in milliseconds. Playwright
    # drives a browser far faster than anyone can follow, so watching a run
    # without this shows a window flickering open and shut.
    #
    # The single place this is decided. The browser sent its own number for a
    # while and the two drifted apart - 700 here, 2500 there - so every run took
    # three and a half times as long as this file claimed, and turning it down
    # meant knowing to look in the other one.
    #
    # 1500 is set by the hardest step to follow rather than the average one.
    # Playwright scrolls an element into view before it acts on it, and that
    # scroll is a jump, not a glide - the page is simply somewhere else on the
    # next frame, however low this is set. Nothing here can slow the movement
    # itself; what the pause buys is time to find your place again afterwards,
    # which is why the number that reads well for a click is still too quick
    # for a step that moved the page under you.
    #
    # At 600 steps ran together and 900 was still brisk through a scroll. 2500
    # was the other way wrong - a thirty-step test became a minute and a half
    # of watching.
    #
    # Headed runs only. Nobody is watching a headless one, so it stays at full
    # speed and this changes neither how long a normal run takes nor what it
    # reports: pacing the browser changes when things happen, never the verdict.
    WATCH_SLOWMO_MS: int = 1500
    # Open each page once before inventing test cases, to see what is actually
    # on it when you arrive cold. A recording shows one state - the cart had
    # something in it, the wizard was on step one - and without looking, cases
    # get written against elements that are only there in that state.
    #
    # Costs a browser launch and one page load per page, once per generation.
    # Turn off where generation runs somewhere the application is unreachable.
    PROBE_PAGES: bool = True
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
