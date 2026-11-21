#!/bin/sh
# Bring the schema up to date before the API starts. The seed (RBAC catalogue, new permissions for
# built-in roles) is run by hand: docker compose exec api python -m app.utils.seed
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

exec "$@"
