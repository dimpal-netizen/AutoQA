#!/usr/bin/env bash
#
# Pull and redeploy. Run from the repo root on the server:
#
#   ./docker/deploy.sh
#
# Everything the server needs comes from git except .env.production, which
# holds the secrets and stays on the machine.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.production -p autoqa)

if [ ! -f .env.production ]; then
    echo "No .env.production. Copy .env.production.example and fill it in." >&2
    exit 1
fi

# A run is a thread inside the API process, not queued work, so rebuilding
# kills anything executing with no retry and no record beyond the run being
# left marked "running". Worth a look before pulling the rug.
running=$("${COMPOSE[@]}" exec -T -e PGPASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env.production | cut -d= -f2-)" \
    postgres psql -qtAX -U "$(grep -E '^POSTGRES_USER=' .env.production | cut -d= -f2-)" \
    -d "$(grep -E '^POSTGRES_DB=' .env.production | cut -d= -f2-)" \
    -c "select count(*) from test_runs where status = 'running'" 2>/dev/null || echo "?")

if [ "${running}" != "0" ] && [ "${running}" != "?" ]; then
    echo "WARNING: ${running} run(s) are executing. Rebuilding will kill them."
    read -r -p "Continue? [y/N] " reply
    [ "${reply}" = "y" ] || exit 1
fi

echo "==> pulling"
git pull --ff-only

echo "==> building and restarting"
"${COMPOSE[@]}" up -d --build

echo "==> waiting for the API"
for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:29381/health >/dev/null 2>&1; then
        echo "==> healthy"
        "${COMPOSE[@]}" ps
        exit 0
    fi
    sleep 2
done

echo "The API did not come back. Recent logs:" >&2
"${COMPOSE[@]}" logs --tail 40 api >&2
exit 1
