#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
if [[ "${1:-}" == init ]]; then
  if [[ -e .env.staging ]]; then echo 'Staging configuration already exists; kept unchanged.'; exit 0; fi
  python3 - <<'PY'
import base64, os, secrets
from pathlib import Path
p=Path('.env.staging')
with p.open('x') as f:
 f.write('POSTGRES_PASSWORD='+secrets.token_hex(24)+'\nAPP_SECRET_KEY='+secrets.token_hex(32)+'\nTENANT_CHANNEL_SECRET_KEY='+base64.urlsafe_b64encode(os.urandom(32)).decode()+'\n')
p.chmod(0o600)
print('Created private local staging configuration.')
PY
  exit 0
fi
if [[ ! -f .env.staging ]]; then echo 'Run scripts/staging.sh init first.'; exit 1; fi
compose=(docker compose --env-file .env.staging -f docker-compose.staging.yml)
case "${1:-status}" in
  start) "${compose[@]}" up -d --build ;;
  stop) "${compose[@]}" stop ;;
  status) "${compose[@]}" ps ;;
  logs) "${compose[@]}" logs --tail 100 ;;
  check) python3 scripts/staging_smoke.py ;;
  backup)
    mkdir -p .staging-backups
    archive=".staging-backups/database-$(date -u +%Y%m%dT%H%M%SZ).dump"
    "${compose[@]}" exec -T postgres pg_dump -U agent_staging -d agent_staging -Fc > "$archive.partial"
    mv "$archive.partial" "$archive"
    "${compose[@]}" run --rm --no-deps -T --entrypoint tar backend czf - -C /app uploads > "${archive%.dump}-uploads.tar.gz"
    echo "Database backup: $archive. Keep .env.staging in a secure backup too; it holds the encryption key."
    ;;
  restore-check)
    archive="${2:?Provide a database backup path}"
    [[ -f "$archive" ]] || { echo 'Backup not found.'; exit 1; }
    scratch="restore_check_$(date +%s)_$$"
    "${compose[@]}" exec -T postgres createdb -U agent_staging "$scratch"
    trap '"${compose[@]}" exec -T postgres dropdb -U agent_staging "$scratch" >/dev/null' EXIT
    "${compose[@]}" exec -T postgres pg_restore -U agent_staging -d "$scratch" --no-owner --exit-on-error < "$archive"
    "${compose[@]}" exec -T postgres psql -U agent_staging -d "$scratch" -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;' -c 'SELECT count(*) AS import_jobs FROM import_jobs;'
    echo 'Restore verified in a disposable database. Staging data was not replaced.'
    ;;
  *) echo 'Use init, start, stop, status, logs, check, backup, or restore-check PATH.'; exit 2 ;;
esac
