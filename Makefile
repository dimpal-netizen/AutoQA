# TestPilot AI — common commands.
#
# `make` is not installed on Windows by default. If you don't have it, just run
# the commands shown under each target directly (see README.md).

.PHONY: help up down logs install migrate migration api worker lint format test clean

help:
	@echo "up         Start Postgres + Redis"
	@echo "down       Stop them"
	@echo "logs       Tail container logs"
	@echo "install    poetry install"
	@echo "migrate    Apply database migrations"
	@echo "migration  Create a migration:  make migration m='add users table'"
	@echo "api        Run the API with autoreload"
	@echo "worker     Run the Celery worker"
	@echo "lint       ruff check"
	@echo "format     ruff format"
	@echo "test       pytest"
	@echo "clean      Remove caches, storage, and workspaces"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

install:
	cd backend && poetry install

migrate:
	cd backend && poetry run alembic upgrade head

migration:
	cd backend && poetry run alembic revision --autogenerate -m "$(m)"

api:
	cd backend && poetry run uvicorn app.main:app --reload

worker:
	cd backend && poetry run celery -A app.core.celery_app worker \
		-Q codegen,execution,ai,reports --loglevel=info --pool=solo

lint:
	cd backend && poetry run ruff check .

format:
	cd backend && poetry run ruff format .

test:
	cd backend && poetry run pytest

clean:
	cd backend && rm -rf .pytest_cache .ruff_cache storage/* workspaces/*
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
