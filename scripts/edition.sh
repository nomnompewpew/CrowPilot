#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
LOG_DIR="/tmp"

usage() {
  cat <<'EOF'
Usage:
  scripts/edition.sh status
  scripts/edition.sh run <edition>
  scripts/edition.sh switch <edition>

Editions:
  crowpilot-developer
  crowpi
  crowpilot-lite
  crowpilot
EOF
}

assert_edition_exists() {
  local edition="$1"
  if [[ ! -f "${REPO_ROOT}/apps/${edition}/backend.env" ]]; then
    echo "Unknown edition: ${edition}" >&2
    exit 1
  fi
}

current_listener_pid() {
  ss -tlnp | awk '/:8787 / {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1
}

show_status() {
  local pid
  pid="$(current_listener_pid || true)"
  if [[ -z "${pid}" ]]; then
    echo "edition server not running"
    return 0
  fi
  echo "port 8787 pid: ${pid}"
  ps eww -p "${pid}" | tr ' ' '\n' | grep '^PANTHEON_EDITION=' || echo "PANTHEON_EDITION not present in process environment"
}

run_edition() {
  local edition="$1"
  assert_edition_exists "${edition}"
  cd "${BACKEND_DIR}"
  export PANTHEON_EDITION="${edition}"
  exec bash run.sh
}

switch_edition() {
  local edition="$1"
  local pid
  assert_edition_exists "${edition}"
  pid="$(current_listener_pid || true)"
  if [[ -n "${pid}" ]]; then
    kill "${pid}" || true
    pkill -f 'uvicorn app.main:app' || true
  fi
  cd "${BACKEND_DIR}"
  nohup env PANTHEON_EDITION="${edition}" bash run.sh > "${LOG_DIR}/crowpilot-${edition}.log" 2>&1 &
  echo "started ${edition}; log: ${LOG_DIR}/crowpilot-${edition}.log"
}

command="${1:-status}"
edition="${2:-crowpilot-developer}"

case "${command}" in
  status)
    show_status
    ;;
  run)
    run_edition "${edition}"
    ;;
  switch)
    switch_edition "${edition}"
    ;;
  *)
    usage
    exit 1
    ;;
esac