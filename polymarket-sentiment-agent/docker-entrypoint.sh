#!/bin/sh
set -e
cd /app
python -c "from app.database import init_db; init_db()"
# Seed clearly-labeled demo data (demo=true on every row) unless disabled.
# Set SEED_DEMO=false for a clean production database.
if [ "${SEED_DEMO:-true}" = "true" ]; then
  python seed_demo.py
  python seed_history.py
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
