# AutoQA

AI-powered autonomous test automation platform. Lets Manual QA Engineers, QA Engineers, and
Test Managers automate web application testing **without writing code**.

## What it does

| Workflow | Flow |
|---|---|
| **1. Recorded automation** | Chrome extension records your clicks and typing → backend turns the recording into Python Playwright code → AI refactors it into test cases and page objects → runs on Chromium/Firefox/WebKit → AI explains any failures |
| **2. Autonomous agent** | Give it a URL and a module name → the agent explores the app itself, finds the workflows, writes the tests, and runs them |
| **3. AI failure analysis** | Feeds logs, errors, and screenshots to an LLM → root cause, suggested fix, severity, priority, confidence score |

## Tech stack

**Backend** Python 3.13 · FastAPI · PostgreSQL · SQLAlchemy · Alembic · Redis · Celery · JWT · Poetry
**Automation** Playwright · Pytest · Allure · HTML reports
**AI** Claude · Gemini · OpenAI (one interface, swap with one line in `.env`)
**Frontend** Next.js 16 · TypeScript · Tailwind v4 · ShadCN-style UI · Zustand
**Extension** Manifest V3 · TypeScript *(Phase 9)*
**Infra** Docker · Docker Compose

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | **3.13** | `winget install Python.Python.3.13` |
| Poetry | latest | `py -m pip install --user poetry` |
| Docker Desktop | any | must be **running** before `docker compose up` |
| Node.js | 20+ | only needed for Phases 8–9 |

### Windows gotchas

**The Microsoft Store `python` alias breaks Poetry.** If `python --version` opens the Store,
Poetry's environment detection fails with `exit status 9009`. Turn the alias off at
*Settings → Apps → Advanced app settings → App execution aliases* (switch off both
`python.exe` and `python3.exe`), or put the real interpreter first on PATH:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python313"
$env:PATH = "$py;$py\Scripts;$env:APPDATA\Python\Python313\Scripts;$env:PATH"
```

**Poetry's scripts are not on PATH** after `pip install --user poetry`. Either add
`%APPDATA%\Python\Python313\Scripts` to PATH, or call it as `py -3.13 -m poetry`.

**Ruff may be blocked by Windows Application Control** (`WinError 4551`). Linting is
optional — nothing else depends on it. If you hit this, skip `ruff check` or get the
binary allow-listed.

---

## Setup

```bash
# 1. Environment file
cp .env.example .env          # PowerShell: Copy-Item .env.example .env

# 2. Start Postgres + Redis
docker compose up -d

# 3. Install Python dependencies
cd backend
poetry install

# 4. Create the database schema
poetry run alembic upgrade head

# 5. Run the API
poetry run uvicorn app.main:app --reload --host 0.0.0.0
```

> **`--host 0.0.0.0` is worth using.** Uvicorn defaults to `127.0.0.1`, which
> works for `localhost` but not for your LAN IP — handy if you want to open the
> app from a phone or another machine. On Windows neither `0.0.0.0` (IPv4-only)
> nor `::` (IPv6-only) binds both stacks, so pick the one matching how you
> browse; `localhost` works either way.

### "Failed to fetch" in the browser

Almost always CORS, not the network. The API allows any local origin in
development (`localhost`, `127.0.0.1`, `[::1]`, and private LAN ranges, on any
port). If you see it anyway, check the browser console for the blocked origin
and add it to `CORS_ORIGINS` in `.env`.

Open <http://localhost:8000/docs> for the interactive API docs.

Check it's healthy:

```bash
curl http://localhost:8000/health         # liveness
curl http://localhost:8000/health/ready   # also checks Postgres + Redis
```

### Run the web app

```bash
cd frontend
cp .env.local.example .env.local   # PowerShell: Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. Register an account — **the first account created becomes
the admin** — then create a project.

### AI features — optional, and off until you add a key

AutoQA works **without an API key**. Nothing is blocked, no feature disappears,
no error is shown. This is deliberate: recordings are turned into Playwright
code by ordinary Python, not by AI, so the part that actually runs never depends
on a network call succeeding.

To switch AI on, fill in the key for whichever provider you have:

```ini
LLM_PROVIDER=gemini              # claude | openai | gemini
GEMINI_API_KEY=AIza...           # aistudio.google.com/apikey
# ANTHROPIC_API_KEY=sk-ant-...   # console.anthropic.com
# OPENAI_API_KEY=sk-...          # platform.openai.com
```

Restart the API — `.env` is read at startup and `--reload` does not watch it.

Then check it actually works before wondering why nothing changed:

```bash
cd backend
poetry run python scripts/check_ai.py
```

It reports the model in use, lists the models your key can reach, and sends one
small structured-output request. Everything downstream depends on that last
part, so it is worth proving directly.

> **If you get a 404 on the model**, your key cannot use the default. The check
> script prints the ids that *are* available — put one in `GEMINI_MODEL`.
> Model names change often; that is why it is a setting and not a constant.

| | Without a key | With a key |
|---|---|---|
| Recording → runnable script | ✅ | ✅ |
| Page objects, fallback selectors | ✅ | ✅ |
| Step list in the UI | ✅ | ✅ |
| Names like `sign_in_button` | ❌ `button_2` | ✅ |
| Readable step descriptions | ❌ `Click "Sign in"` | ✅ `Submit the sign-in form` |
| Failure analysis *(Phase 5+)* | ❌ | ✅ |

Roughly a fraction of a cent per recording. Every call records its own token
count and dollar cost, so spend is never a mystery.

### Background workers (from Phase 3 onward)

```bash
cd backend
poetry run celery -A app.core.celery_app worker -Q codegen,execution,ai,reports --loglevel=info
```

> On Windows, Celery needs `--pool=solo` (or run the workers inside WSL2).

---

## Project structure

Only folders that exist today are listed. Folders for later phases are created
when that phase starts, so an empty folder never means "something is missing".

```
AutoQA/
├── docker-compose.yml        # Postgres + Redis
├── .env                      # your settings and API keys (never committed)
├── docs/                     # the recording format the extension must match
├── generated/                # YOUR TEST SCRIPTS land here — open in VS Code
├── .autoqa/                  # screenshots, videos, run workspaces (disposable)
│
├── backend/                  # the API and all the logic
│   ├── alembic/              #   database migrations, in order
│   ├── tests/                #   tests for AutoQA itself
│   └── app/
│       ├── main.py           #   starts the API
│       ├── api/              #   the URLs the frontend calls (no logic here)
│       ├── services/         #   all the decisions and rules
│       ├── repositories/     #   all the database queries
│       ├── models/           #   what the database tables look like
│       ├── schemas/          #   what a request and response must contain
│       ├── codegen/          #   recording -> Playwright code (no AI)
│       ├── ai/               #   Claude / Gemini / OpenAI, prompts, polish
│       ├── core/             #   config, database connection, passwords, JWT
│       └── static/           #   recorder.js, injected into the browser
│
└── frontend/                 # the website you click on
    └── src/
        ├── app/              #   one folder per page (/login, /recordings, ...)
        ├── components/       #   reusable pieces of UI
        ├── lib/              #   API calls and shared types
        └── stores/           #   who is logged in
```

**The two folders that matter to you day to day:**

| Folder | What it is |
|---|---|
| `generated/` | The Playwright scripts AutoQA writes for you. This is what you open in VS Code. |
| `.env` | Your settings — database, API keys. The only file you normally edit by hand. |

Everything else is the application itself.

> **Why `generated/` and `.autoqa/` sit outside `backend/`, and why that must not
> change:** `uvicorn --reload` watches the folder it was started from for `.py`
> changes. Generating a suite and running a test both write `.py` files. Put
> them under `backend/` and every run restarts the server — killing the run that
> triggered it, with the unhelpful message *"pytest produced no report"*.
>
> `.env` is read at startup and is **not** watched. After changing it, restart
> the API; `--reload` will not notice on its own.

> **VS Code showing dozens of folders you didn't create?** `.venv`, `node_modules`,
> `__pycache__` and `.next` are installed packages and build caches — not your
> code. `.vscode/settings.json` hides them. Nothing is deleted; flip any entry to
> `false` to see it again.

### How the layers fit together

```
HTTP request  →  api/  →  services/  →  repositories/  →  database
Celery task   →           services/  →  repositories/  →  database
```

Three rules keep it maintainable:

1. **Routes contain no logic.** They parse input, call one service, return the result.
2. **Only repositories touch the database.** Services never build a query.
3. **Celery tasks are thin.** They open a session and call the same service a route would.

---

## Build phases

| Phase | What it delivers | Status |
|---|---|---|
| 0 | Project setup, Docker, config, health check | ✅ Done |
| 1 | Auth, users, roles, projects — backend **and** frontend | ✅ Done |
| 2 | Recording storage (+ freeze the recording JSON format) | ✅ Done — [format spec](docs/recording-format.md) |
| 3 | Recording → Playwright code, written to `backend/generated/` | ✅ Done |
| 4 | AI layer — better names and descriptions on generated code | ✅ Done |
| 5 | **Test execution** — Run button, cross-browser, screenshots, video | ✅ Done |
| 6 | AI test cases — positive, negative, edge and security *(needs an API key)* | ⬜ Next |
| 6b | AI failure analysis (Workflow 3) | ⬜ |
| 7 | HTML / Allure reports + bug reports | ⬜ |
| 8 | Autonomous agent (Workflow 2) + Jira / Azure DevOps | ⬜ |
| 9 | Chrome extension (Manifest V3) | ⬜ |

Each phase extends both the backend and the UI, so the app stays runnable throughout.

---

## Development

```bash
cd backend

poetry run ruff check .          # lint
poetry run ruff format .         # format
poetry run pytest                # tests
poetry run pytest -m "not integration"   # skip tests needing Postgres/Redis

poetry run alembic revision --autogenerate -m "add users table"
poetry run alembic upgrade head
poetry run alembic downgrade -1
```

## Not built yet (on purpose)

Deferred until the core works — add them when they're actually needed:
GitHub Actions CI, a Makefile, Dockerfiles for the API and worker.

## Useful URLs

| URL | What |
|---|---|
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/redoc> | ReDoc |
| <http://localhost:8000/health> | Liveness |
| <http://localhost:8000/health/ready> | Postgres + Redis check |
