"""Development launcher: `poetry run python -m app` from backend/.

Exists so the port lives in settings (API_PORT, default 4000) rather than in
whoever remembered to type `--port`. Plain `uvicorn app.main:app` does not
read .env and falls back to uvicorn's own 8000, which the web app is not
pointed at.

Reload watches only app/, not the working directory. Generating a suite and
running a test both write .py files into generated/, and a watcher on the
whole tree restarts the server mid-run - killing the run that triggered it.
"""

from pathlib import Path

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )
