# AutoQA

AI-powered test automation. Record yourself using a web application, and AutoQA
writes real Playwright tests, runs them across Chrome, Firefox and Safari, and
explains anything that breaks.

Built for Manual QA Engineers, QA Engineers and Test Managers — **no code
required**, and no code hidden from you either: what it produces is an ordinary
pytest project you own and can edit.

---

## Contents

1. [What you need installed](#1-what-you-need-installed)
2. [Windows: read this first](#2-windows-read-this-first)
3. [Full setup, step by step](#3-full-setup-step-by-step)
4. [Check it actually works](#4-check-it-actually-works)
5. [Starting it again tomorrow](#5-starting-it-again-tomorrow)
6. [Turning on the AI features](#6-turning-on-the-ai-features-optional)
7. [Using it](#7-using-it)
8. [When something goes wrong](#8-when-something-goes-wrong)
9. [Project layout](#9-project-layout)
10. [Everyday commands](#10-everyday-commands)

---

## 1. What you need installed

| Tool | Version | Install |
|---|---|---|
| **Python** | 3.13 | `winget install Python.Python.3.13` |
| **Poetry** | latest | `py -m pip install --user poetry` |
| **Node.js** | 20+ | <https://nodejs.org> |
| **Docker Desktop** | any | Must be **running** before you start |

Docker supplies PostgreSQL and Redis. You do not install those yourself.

---

## 2. Windows: read this first

Three things bite on Windows, all before you write a line of code.

**The Microsoft Store `python` alias breaks Poetry.** If typing `python --version`
opens the Store, Poetry fails with `exit status 9009`. Turn the alias off at
*Settings → Apps → Advanced app settings → App execution aliases* — switch off
both `python.exe` and `python3.exe`. Or put the real interpreter first on PATH:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python313"
$env:PATH = "$py;$py\Scripts;$env:APPDATA\Python\Python313\Scripts;$env:PATH"
```

**Poetry's scripts are not on PATH** after `pip install --user poetry`. Either add
`%APPDATA%\Python\Python313\Scripts` to PATH, or call it as `py -3.13 -m poetry`.

**Ruff may be blocked by Windows Application Control** (`WinError 4551`). Linting
is optional and nothing depends on it — skip `ruff check` if you hit this.

---

## 3. Full setup, step by step

Do these once, in order. Every command's working directory is stated.

### Step 1 — Settings file

From the project root:

```bash
cp .env.example .env
```

```powershell
# PowerShell
Copy-Item .env.example .env
```

The defaults work as-is. You do not need to edit anything yet — API keys are
optional and covered in [section 6](#6-turning-on-the-ai-features-optional).

### Step 2 — Start the database

Docker Desktop must be running first. From the project root:

```bash
docker compose up -d
```

This starts PostgreSQL on port 5432 and Redis on 6379. Leave it running — it
survives reboots of the app and does not need restarting between sessions.

### Step 3 — Install the backend

```bash
cd backend
poetry install
```

### Step 4 — Install the browsers

**Do not skip this.** Playwright needs its own browser binaries; they are not
your installed Chrome. Without them, recording and every test run fail.

```bash
# still in backend/
poetry run playwright install chromium firefox webkit
```

This downloads a few hundred MB once. If you only care about Chrome,
`poetry run playwright install chromium` is enough to get started.

### Step 5 — Create the database tables

```bash
# still in backend/
poetry run alembic upgrade head
```

### Step 6 — Start the API

```bash
# still in backend/
poetry run uvicorn app.main:app --reload --host 0.0.0.0
```

Leave this terminal running. The API is now at <http://localhost:8000>.

> **Always start uvicorn from `backend/`, never from the project root.**
> `--reload` watches the folder it was started in. Generating a suite and running
> a test both write `.py` files into `generated/`, which sits *outside*
> `backend/` for exactly this reason. Start it from the root and every test run
> restarts the server, killing the run that triggered it — with the unhelpful
> message *"pytest produced no report"*.

> **Why `--host 0.0.0.0`:** uvicorn defaults to `127.0.0.1`, which works for
> `localhost` but not for your LAN IP — handy if you want to open the app from a
> phone. On Windows neither `0.0.0.0` (IPv4-only) nor `::` (IPv6-only) binds both
> stacks, so pick the one matching how you browse. `localhost` works either way.

### Step 7 — Start the web app

Open a **second terminal**. From the project root:

```bash
cd frontend
cp .env.local.example .env.local     # PowerShell: Copy-Item .env.local.example .env.local
npm install
npm run dev
```

### Step 8 — Create your account

Open <http://localhost:3000> and register.

**The first account created becomes the admin.** Make it yours.

---

## 4. Check it actually works

```bash
curl http://localhost:8000/health          # is the API alive?
curl http://localhost:8000/health/ready    # are Postgres and Redis reachable?
```

`/health/ready` returns `503` and names the failing dependency if Docker is not
running. That is the fastest way to tell an app problem from an infrastructure
one.

Interactive API docs: <http://localhost:8000/docs>

---

## 5. Starting it again tomorrow

Setup is done. From then on it is two terminals:

```bash
# Terminal 1 — API
cd backend
poetry run uvicorn app.main:app --reload --host 0.0.0.0

# Terminal 2 — web app
cd frontend
npm run dev
```

Docker keeps running in the background. If you restarted your machine, run
`docker compose up -d` from the project root first.

---

## 6. Turning on the AI features (optional)

**AutoQA works without an API key.** Nothing is blocked and no error is shown.
This is deliberate: recordings become Playwright code through ordinary Python,
not through a model, so the part that actually runs never depends on a network
call succeeding.

|  | Without a key | With a key |
|---|---|---|
| Recording → runnable test | ✅ | ✅ |
| Page objects, fallback selectors | ✅ | ✅ |
| Cross-browser runs, screenshots, video | ✅ | ✅ |
| HTML reports, CSV test-case sheet | ✅ | ✅ |
| Readable names (`sign_in_button` vs `button_2`) | ❌ | ✅ |
| Extra cases: negative, edge, security | ❌ | ✅ |
| Failure analysis — root cause and fix | ❌ | ✅ |
| Drafted bug reports | ❌ | ✅ |

To switch it on, edit `.env` in the project root:

```ini
LLM_PROVIDER=gemini              # claude | openai | gemini
GEMINI_API_KEY=AIza...           # aistudio.google.com/apikey
# ANTHROPIC_API_KEY=sk-ant-...   # console.anthropic.com
# OPENAI_API_KEY=sk-...          # platform.openai.com
```

**Restart the API afterwards.** `.env` is read at startup and `--reload` does not
watch it — this is the single most common reason people think their key "didn't
work".

Then prove it before wondering why nothing changed:

```bash
cd backend
poetry run python scripts/check_ai.py
```

It reports the model in use, lists the models your key can reach, and sends one
small structured-output request. Everything downstream depends on that last part.

> **A 404 on the model** means your key cannot use the default. The script prints
> the ids that *are* available — put one in `GEMINI_MODEL`. Model names change
> often, which is why it is a setting and not a constant.

Cost is roughly a fraction of a cent per recording. Every call records its own
token count and dollar cost, so spend is never a mystery.

---

## 7. Using it

1. **Projects → New project.** One project is one web application.
2. Open it and press **Record a session.** A browser opens on your app with the
   recorder already running — there is nothing to install in your application.
3. Use the site normally: log in, fill the form, click through the flow.
4. Close the browser. **The test is already written.**
5. **Run tests.** Pick your browsers; they run at the same time. Tick
   *Watch it run* to see it drive the browser at a readable speed.
6. Failures come back with a screenshot, video and stack trace — plus root cause
   and a drafted bug report if you added an AI key.

Your scripts are written to `generated/`. Open that folder in VS Code and edit
anything; it runs with plain `pytest`, with or without AutoQA.

**Export for your team:** *Test cases → Export CSV* produces the standard QA
test-case sheet — ID, pre-requisites, priority, positive/negative, steps,
expected results — with the Actual Results, Status and Execution Date columns
filled in from the latest run.

---

## 8. When something goes wrong

| Symptom | Cause and fix |
|---|---|
| `Executable doesn't exist` / `playwright install` in an error | You skipped [step 4](#step-4--install-the-browsers). Run `poetry run playwright install chromium firefox webkit` from `backend/`. |
| **"Failed to fetch"** in the browser | Almost always CORS, not the network. The API allows any local origin in development. Check the browser console for the blocked origin and add it to `CORS_ORIGINS` in `.env`. |
| `/health/ready` returns 503 | Docker is not running, or the containers are stopped. `docker compose up -d`. |
| **"pytest produced no report"**, runs finish in milliseconds | uvicorn was started from the project root instead of `backend/`, so `--reload` restarts on every generated file. See [step 6](#step-6--start-the-api). |
| Added an API key, nothing changed | `.env` is only read at startup. Restart the API. |
| Poetry fails with `exit status 9009` | The Microsoft Store Python alias. See [section 2](#2-windows-read-this-first). |
| A test fails with `strict mode violation … resolved to 2 elements` | The recorded selector matches more than one element on the page the test reaches. Re-record, or edit the locator in the generated page object. |
| VS Code shows dozens of folders you did not create | `.venv`, `node_modules`, `__pycache__`, `.next` are installed packages and build caches. `.vscode/settings.json` hides them; nothing is deleted. |

---

## 9. Project layout

```
AutoQA/
├── docker-compose.yml        # Postgres + Redis
├── .env                      # your settings and API keys (never committed)
├── docs/                     # the recording format specification
├── generated/                # YOUR TEST SCRIPTS land here — open in VS Code
├── .autoqa/                  # screenshots, videos, run workspaces (disposable)
│
├── backend/                  # the API and all the logic
│   ├── alembic/              #   database migrations, in order
│   ├── scripts/              #   check_ai.py, seed_recording.py
│   ├── tests/                #   tests for AutoQA itself
│   └── app/
│       ├── main.py           #   starts the API
│       ├── api/              #   the URLs the frontend calls (no logic here)
│       ├── services/         #   all the decisions and rules
│       ├── repositories/     #   all the database queries
│       ├── models/           #   what the database tables look like
│       ├── schemas/          #   what a request and response must contain
│       ├── codegen/          #   recording -> Playwright code (no AI involved)
│       ├── runner/           #   runs pytest, parses results, kills cancelled runs
│       ├── reports/          #   HTML run reports, CSV test-case sheets
│       ├── ai/               #   Gemini / Claude / OpenAI, prompts, analysis
│       ├── core/             #   config, database, passwords, JWT
│       └── static/           #   recorder.js, injected into the browser
│
└── frontend/                 # the website you click on
    └── src/
        ├── app/              #   one folder per page (/login, /dashboard, ...)
        ├── components/       #   reusable pieces of UI
        ├── lib/              #   API calls and shared types
        └── stores/           #   who is logged in
```

**The two that matter day to day:**

| Path | What it is |
|---|---|
| `generated/` | The Playwright scripts AutoQA writes for you. Open this in VS Code. |
| `.env` | Your settings — database, API keys. The only file you normally edit by hand. |

### How the layers fit together

```
HTTP request  →  api/  →  services/  →  repositories/  →  database
```

Three rules keep it maintainable:

1. **Routes contain no logic.** They parse input, call one service, return the result.
2. **Only repositories touch the database.** Services never build a query.
3. **AI never writes executable code.** The recording-to-Playwright conversion is
   deterministic Python, so the same recording always produces the same test.

---

## 10. Everyday commands

```bash
cd backend

poetry run pytest                        # all tests (307 at last count)
poetry run pytest -m "not integration"   # skip those needing Postgres/Redis
poetry run ruff check .                  # lint
poetry run ruff format .                 # format

poetry run alembic revision --autogenerate -m "add users table"
poetry run alembic upgrade head
poetry run alembic downgrade -1
```

```bash
cd frontend

npm run dev            # development server
npm run build          # production build
npx tsc --noEmit       # typecheck
npx eslint src         # lint
```

### Useful URLs

| URL | What |
|---|---|
| <http://localhost:3000> | The app |
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/redoc> | ReDoc |
| <http://localhost:8000/health> | Liveness |
| <http://localhost:8000/health/ready> | Postgres + Redis check |

---

## Build status

| Phase | What it delivers | Status |
|---|---|---|
| 0 | Project setup, Docker, config, health check | ✅ |
| 1 | Auth, users, roles, projects | ✅ |
| 2 | Recording storage ([format spec](docs/recording-format.md)) | ✅ |
| 3 | Recording → Playwright code | ✅ |
| 4 | AI layer — better names and descriptions | ✅ |
| 5 | Test execution — cross-browser, screenshots, video | ✅ |
| 6 | AI test cases — positive, negative, edge, security | ✅ |
| 7 | AI failure analysis | ✅ |
| 8 | AI bug reports drafted from failures | ✅ |
| 9 | Shareable HTML run reports | ✅ |
| 10 | CSV test-case sheet export | ✅ |
| 11 | Autonomous agent + Jira / Azure DevOps | ⬜ Next |
| 12 | Chrome extension (Manifest V3) | ⬜ |

Recording currently works through a browser AutoQA launches for you, with the
recorder injected — the Chrome extension in phase 12 is an alternative entry
point, not a prerequisite.

### Tech stack

**Backend** Python 3.13 · FastAPI · PostgreSQL · SQLAlchemy · Alembic · Redis · JWT · Poetry
**Automation** Playwright · pytest · HTML reports
**AI** Gemini · Claude · OpenAI — one interface, swapped with one line in `.env`
**Frontend** Next.js 16 · TypeScript · Tailwind v4 · Zustand
**Infra** Docker Compose
