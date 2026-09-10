#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Refresh activation scripts and interpreter paths after moving the project.
# No --clear: installed packages and project data are preserved.
python3 -m venv "$ROOT_DIR/backend/.venv"
"$ROOT_DIR/backend/.venv/bin/python" -m pip install -r "$ROOT_DIR/backend/requirements.txt"
(cd "$ROOT_DIR/frontend" && npm ci)
printf 'Dependencies ready. Configure backend/.env, then run start_all.sh. Existing data has not been changed.\n'
