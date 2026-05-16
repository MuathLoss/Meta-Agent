#!/usr/bin/env bash

# Simple local development runner for macOS/Linux shells.
# It starts PostgreSQL (when we can detect and start it safely),
# then launches the backend, frontend, and Telegram polling worker
# from the project root so you do not need three separate terminals.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_DIR="$ROOT_DIR/.dev-runner"
PID_FILE="$RUNNER_DIR/pids"

BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_VENV="$BACKEND_DIR/.venv"

FRONTEND_URL="http://localhost:5173"
BACKEND_DOCS_URL="http://127.0.0.1:8000/docs"

mkdir -p "$RUNNER_DIR"

SERVICE_NAMES=()
SERVICE_PIDS=()

log() {
  printf '[local-dev] %s\n' "$1"
}

fail() {
  printf '[local-dev] ERROR: %s\n' "$1" >&2
  exit 1
}

require_path() {
  local path="$1"
  local message="$2"
  [[ -e "$path" ]] || fail "$message"
}

port_in_use() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

ensure_port_free() {
  local port="$1"
  local service_name="$2"

  if port_in_use "$port"; then
    log "Port $port is already in use, so $service_name cannot start."
    log "Stop the other process first, or free the port and run ./start_all.sh again."
    exit 1
  fi
}

postgres_ready() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready >/dev/null 2>&1
  elif lsof -nP -iTCP:5432 -sTCP:LISTEN >/dev/null 2>&1; then
    # Fallback for machines where PostgreSQL client tools are not on PATH,
    # but the server is already listening on the default local port.
    return 0
  else
    return 1
  fi
}

try_start_postgres_with_brew() {
  local candidate
  local candidates=(
    postgresql
    postgresql@17
    postgresql@16
    postgresql@15
    postgresql@14
    postgresql@13
  )

  if [[ "${START_POSTGRES_WITH_BREW:-0}" != "1" ]]; then
    log "Skipping Homebrew PostgreSQL auto-start. Set START_POSTGRES_WITH_BREW=1 to enable it."
    return 1
  fi

  command -v brew >/dev/null 2>&1 || return 1

  for candidate in "${candidates[@]}"; do
    if brew services list 2>/dev/null | awk '{print $1}' | grep -Fx "$candidate" >/dev/null 2>&1; then
      log "PostgreSQL does not look ready. Trying: brew services start $candidate"
      brew services start "$candidate"
      return 0
    fi
  done

  return 1
}

ensure_postgres() {
  if postgres_ready; then
    log "PostgreSQL is already accepting connections."
    return
  fi

  log "PostgreSQL is not ready yet."

  if try_start_postgres_with_brew; then
    local attempt
    for attempt in {1..15}; do
      if postgres_ready; then
        log "PostgreSQL is now accepting connections."
        return
      fi
      sleep 1
    done
  fi

  log "Could not confirm PostgreSQL automatically."
  log "Continuing anyway in case PostgreSQL is managed outside Homebrew or pg_isready is unavailable."
  log "If the backend exits with a database connection error, start PostgreSQL manually and run ./start_all.sh again."
}

stop_process_tree() {
  local pid="$1"

  [[ -n "$pid" ]] || return 0

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  # Ask child processes to stop first, then stop the parent.
  pkill -TERM -P "$pid" >/dev/null 2>&1 || true
  kill -TERM "$pid" >/dev/null 2>&1 || true

  sleep 1

  if kill -0 "$pid" >/dev/null 2>&1; then
    pkill -KILL -P "$pid" >/dev/null 2>&1 || true
    kill -KILL "$pid" >/dev/null 2>&1 || true
  fi
}

cleanup() {
  local exit_code="${1:-0}"
  local index

  trap - INT TERM EXIT

  log "Stopping local development services..."

  for (( index=${#SERVICE_PIDS[@]}-1; index>=0; index-- )); do
    stop_process_tree "${SERVICE_PIDS[$index]}"
  done

  rm -f "$PID_FILE"
  wait >/dev/null 2>&1 || true

  log "All local development services have been stopped."
  exit "$exit_code"
}

handle_signal() {
  printf '\n'
  cleanup 0
}

start_service() {
  local name="$1"
  local command="$2"
  local pid

  log "Starting $name..."

  (
    bash -lc "$command" 2>&1 | sed -u "s/^/[$name] /"
  ) &
  pid=$!

  sleep 1
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    log "$name exited immediately."
    cleanup 1
  fi

  SERVICE_NAMES+=("$name")
  SERVICE_PIDS+=("$pid")
  printf '%s:%s\n' "$name" "$pid" >> "$PID_FILE"
}

main() {
  trap handle_signal INT TERM
  trap 'cleanup $?' EXIT

  require_path "$BACKEND_DIR" "Missing backend directory at $BACKEND_DIR"
  require_path "$FRONTEND_DIR" "Missing frontend directory at $FRONTEND_DIR"
  require_path "$BACKEND_VENV/bin/activate" "Missing backend virtualenv. Expected $BACKEND_VENV/bin/activate"
  require_path "$FRONTEND_DIR/package.json" "Missing frontend/package.json"

  : > "$PID_FILE"

  ensure_port_free 8000 "the backend"
  ensure_port_free 5173 "the frontend"
  ensure_postgres

  start_service \
    "backend" \
    "cd \"$BACKEND_DIR\" && source .venv/bin/activate && PYTHONPATH=. python scripts/init_db.py && PYTHONPATH=. python -m uvicorn main:app --reload"

  start_service \
    "frontend" \
    "cd \"$FRONTEND_DIR\" && npm run dev"

  start_service \
    "telegram" \
    "cd \"$BACKEND_DIR\" && source .venv/bin/activate && PYTHONPATH=. python scripts/run_telegram_polling.py --loop"

  log "Local development stack is running."
  log "Frontend: $FRONTEND_URL"
  log "Backend docs: $BACKEND_DOCS_URL"
  log "Press Ctrl+C to stop everything."
  log "If this terminal closes unexpectedly, run ./stop_all.sh before starting again."

  wait
}

main "$@"
