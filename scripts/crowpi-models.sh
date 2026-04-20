#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_ROOT="${REPO_ROOT}/backend/models"
STATE_DIR="/tmp/pantheon-crowpi-models"

SCAN_MODEL="${MODEL_ROOT}/scan/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
EMBED_MODEL="${MODEL_ROOT}/embed/nomic-embed-text-v1.5.Q8_0.gguf"

SCAN_URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf?download=true"
EMBED_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf?download=true"

usage() {
  cat <<'EOF'
Usage:
  scripts/crowpi-models.sh status
  scripts/crowpi-models.sh download
  scripts/crowpi-models.sh start
  scripts/crowpi-models.sh restart
  scripts/crowpi-models.sh stop

Ports:
  8081  CrowPi embed  (nomic-embed-text-v1.5.Q8_0.gguf)
  8082  CrowPi local  (Llama-3.2-1B-Instruct-Q4_K_M.gguf)
  8083  CrowPi scan   (Llama-3.2-1B-Instruct-Q4_K_M.gguf)
EOF
}

ensure_state_dir() {
  mkdir -p "${STATE_DIR}" "${MODEL_ROOT}/scan" "${MODEL_ROOT}/embed"
}

download_if_missing() {
  local target="$1"
  local url="$2"

  if [[ -s "${target}" ]]; then
    echo "present: ${target}"
    return 0
  fi

  local tmp="${target}.part"
  rm -f "${tmp}"
  echo "downloading: ${target}"
  curl --fail --location --progress-bar "${url}" -o "${tmp}"
  mv "${tmp}" "${target}"
}

pid_for_port() {
  local port="$1"
  ss -ltnp "( sport = :${port} )" \
    | grep -o 'pid=[0-9]\+' \
    | head -n 1 \
    | cut -d= -f2 || true
}

wait_for_port_clear() {
  local port="$1"
  local max_loops="${2:-30}"
  local loops=0
  while [[ -n "$(pid_for_port "${port}")" ]]; do
    loops=$((loops + 1))
    if [[ "${loops}" -ge "${max_loops}" ]]; then
      echo "port ${port} did not clear in time" >&2
      return 1
    fi
    sleep 1
  done
}

stop_port() {
  local port="$1"
  local pid
  pid="$(pid_for_port "${port}")"
  if [[ -z "${pid}" ]]; then
    return 0
  fi

  echo "stopping port ${port} pid ${pid}"
  kill "${pid}"
  if wait_for_port_clear "${port}" 5; then
    return 0
  fi

  echo "force-stopping port ${port} pid ${pid}"
  kill -9 "${pid}"
  wait_for_port_clear "${port}" 10
}

start_server() {
  local name="$1"
  local port="$2"
  local model="$3"
  shift 3

  stop_port "${port}"

  local log_file="${STATE_DIR}/${name}.log"
  echo "starting ${name} on :${port}"
  nohup llama-server \
    --host 0.0.0.0 \
    --port "${port}" \
    --model "${model}" \
    "$@" > "${log_file}" 2>&1 &

  local pid=$!
  echo "${pid}" > "${STATE_DIR}/${name}.pid"

  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
      echo "${name} ready on :${port} (pid ${pid})"
      return 0
    fi
    sleep 1
  done

  echo "${name} failed to become ready; see ${log_file}" >&2
  return 1
}

download_models() {
  ensure_state_dir
  download_if_missing "${SCAN_MODEL}" "${SCAN_URL}"
  download_if_missing "${EMBED_MODEL}" "${EMBED_URL}"
}

start_models() {
  download_models
  start_server "embed" 8081 "${EMBED_MODEL}" --embedding
  start_server "local" 8082 "${SCAN_MODEL}" --ctx-size 4096
  start_server "scan" 8083 "${SCAN_MODEL}" --ctx-size 8192
}

stop_models() {
  stop_port 8083
  stop_port 8082
  stop_port 8081
}

status_models() {
  ensure_state_dir
  for file in "${SCAN_MODEL}" "${EMBED_MODEL}"; do
    if [[ -s "${file}" ]]; then
      ls -lh "${file}"
    else
      echo "missing: ${file}"
    fi
  done

  printf '\n'
  for port in 8081 8082 8083; do
    local_pid="$(pid_for_port "${port}")"
    if [[ -n "${local_pid}" ]]; then
      printf 'port %s pid %s ' "${port}" "${local_pid}"
      curl -fsS "http://127.0.0.1:${port}/v1/models" | tr '\n' ' '
      printf '\n'
    else
      printf 'port %s not listening\n' "${port}"
    fi
  done
}

command="${1:-status}"

case "${command}" in
  status)
    status_models
    ;;
  download)
    download_models
    ;;
  start)
    start_models
    ;;
  restart)
    stop_models
    start_models
    ;;
  stop)
    stop_models
    ;;
  *)
    usage
    exit 1
    ;;
esac
