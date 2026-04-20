#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

# Load .env so PANTHEON_HOST / PANTHEON_PORT are available as shell variables
if [[ -f .env ]]; then
  # export only simple KEY=VALUE lines (skip comments and blanks)
  set -o allexport
  # shellcheck disable=SC1091
  source .env
  set +o allexport
fi

EDITION="${PANTHEON_EDITION:-crowpilot-developer}"
EDITION_ENV="../apps/${EDITION}/backend.env"
if [[ -f "${EDITION_ENV}" ]]; then
  set -o allexport
  # shellcheck disable=SC1090
  source "${EDITION_ENV}"
  set +o allexport
fi

HOST="${PANTHEON_HOST:-0.0.0.0}"
PORT="${PANTHEON_PORT:-8787}"

echo "Starting CrowPilot (${EDITION}) on ${HOST}:${PORT}"
uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload --timeout-graceful-shutdown 1 --reload-delay 2
