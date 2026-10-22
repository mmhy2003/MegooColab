#!/usr/bin/env bash
# Generate an Alembic migration against the dev database: scripts/makemigration.sh "message"
set -euo pipefail
cd "$(dirname "$0")/.."
export SECRET_KEY="${SECRET_KEY:-dev}" DATABASE_URL="${DEV_DATABASE_URL:-postgresql+asyncpg://megoo:megoo@localhost:5433/megoo}"
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "$1"
uv run alembic upgrade head
