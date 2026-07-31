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
**AI** Claude API · OpenAI API · LangChain
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
poetry run uvicorn app.main:app --reload
```

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

### Background workers (from Phase 3 onward)

```bash
cd backend
poetry run celery -A app.core.celery_app worker -Q codegen,execution,ai,reports --loglevel=info
```

> On Windows, Celery needs `--pool=solo` (or run the workers inside WSL2).

---

## Project structure

```
AutoQA/
├── docker-compose.yml        # Postgres + Redis
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/              # database migrations
│   ├── storage/              # screenshots, videos, logs, reports (gitignored)
│   ├── workspaces/           # one temp dir per test run (gitignored)
│   ├── tests/
│   └── app/
│       ├── main.py           # FastAPI app
│       ├── core/             # config, database, security, celery, events
│       ├── models/           # SQLAlchemy tables
│       ├── schemas/          # Pydantic request/response models
│       ├── repositories/     # ALL database queries live here
│       ├── services/         # ALL business logic lives here
│       ├── api/              # HTTP routes (thin — no logic)
│       ├── codegen/          # recording JSON → Playwright code
│       ├── ai/               # Claude / OpenAI clients + prompts
│       ├── runner/           # runs pytest, parses results
│       ├── agent/            # autonomous crawler
│       └── tasks/            # Celery tasks (thin wrappers over services)
├── frontend/                 # Phase 8 — Next.js 15
└── extension/                # Phase 9 — Manifest V3
```

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
| 2 | Recording storage (+ freeze the recording JSON format) | ⬜ |
| 3 | Recording → Playwright code generation | ⬜ |
| 4 | AI layer + failure analysis (Workflow 3) | ⬜ |
| 5 | Test execution + live WebSocket updates | ⬜ |
| 6 | HTML / Allure reports + bug reports | ⬜ |
| 7 | Autonomous agent (Workflow 2) + Jira / Azure DevOps | ⬜ |
| 8 | Chrome extension (Manifest V3) | ⬜ |

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
