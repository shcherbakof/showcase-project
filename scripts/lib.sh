#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.2. Compose базовый каркас.md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd_root() {
  cd "${PROJECT_ROOT}"
}

compose_file_arg() {
  if [[ -f compose.yml ]]; then
    printf -- "-f compose.yml"
  elif [[ -f compose.yaml ]]; then
    printf -- "-f compose.yaml"
  else
    printf -- ""
  fi
}

dc() {
  local file_arg
  file_arg="$(compose_file_arg)"
  if [[ -n "$file_arg" ]]; then
    # shellcheck disable=SC2086
    docker compose $file_arg "$@"
  else
    docker compose "$@"
  fi
}

env_file_arg() {
  if [[ -f .env ]]; then
    printf -- "--env-file .env"
  elif [[ -f .env.example ]]; then
    printf -- "--env-file .env.example"
  else
    printf -- ""
  fi
}

dcf() {
  local arg
  local file_arg
  arg="$(env_file_arg)"
  file_arg="$(compose_file_arg)"
  if [[ -n "$arg" || -n "$file_arg" ]]; then
    # shellcheck disable=SC2086
    docker compose $file_arg $arg "$@"
  else
    docker compose "$@"
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }
}

require_compose() {
  need_cmd docker
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required: docker compose ..." >&2; exit 2; }
}

service_exists() {
  local svc="$1"
  dcf --profile db --profile db-init --profile airflow --profile superset config --services | grep -qx "$svc"
}

wait_healthy() {
  local svc="$1"
  local tries="${2:-60}"
  local sleep_s="${3:-2}"

  for _ in $(seq 1 "$tries"); do
    local id
    id="$(dcf ps -q "$svc" || true)"
    if [[ -n "${id}" ]]; then
      local status
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || true)"
      if [[ "${status}" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep "$sleep_s"
  done

  echo "Service '$svc' did not become healthy in time" >&2
  dcf ps
  exit 3
}
