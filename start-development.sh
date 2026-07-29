#!/usr/bin/env sh
set -eu
export ELEGANCE_ENV=development
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
