#!/usr/bin/env bash

# Stops services previously started by ./start_all.sh.
# This is handy if the runner terminal was closed unexpectedly
# and you want to clean up the background processes manually.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_DIR="$ROOT_DIR/.dev-runner"
PID_FILE="$RUNNER_DIR/pids"

log() {
  printf '[local-dev] %s\n' "$1"
}

stop_process_tree() {
  local pid="$1"

  [[ -n "$pid" ]] || return 0

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  pkill -TERM -P "$pid" >/dev/null 2>&1 || true
  kill -TERM "$pid" >/dev/null 2>&1 || true

  sleep 1

  if kill -0 "$pid" >/dev/null 2>&1; then
    pkill -KILL -P "$pid" >/dev/null 2>&1 || true
    kill -KILL "$pid" >/dev/null 2>&1 || true
  fi
}

main() {
  if [[ ! -f "$PID_FILE" ]]; then
    log "No runner pid file found at $PID_FILE. Nothing to stop."
    exit 0
  fi

  while IFS=: read -r service pid; do
    if [[ -n "${pid:-}" ]]; then
      log "Stopping $service (pid $pid)..."
      stop_process_tree "$pid"
    fi
  done < "$PID_FILE"

  rm -f "$PID_FILE"
  log "Runner cleanup complete."
}

main "$@"
