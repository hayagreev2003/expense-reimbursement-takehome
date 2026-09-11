#!/bin/sh
set -e

# Schema changes run here, never in the application lifespan. An app that migrates on boot
# races itself the moment it runs more than one worker.
if [ -f alembic.ini ]; then
  echo "Running migrations..."
  alembic upgrade head
fi

if [ "${SEED_ON_START:-true}" = "true" ]; then
  echo "Seeding reference data..."
  python -m expense_api.seed.cli || echo "Seed skipped (not yet available)."
fi

exec uvicorn expense_api.main:app --host 0.0.0.0 --port 8000 "$@"
