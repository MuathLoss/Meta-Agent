# Operations

How to run, test, deploy and check the platform. Commands run from the repository root in Git
Bash (Windows) or a Linux shell. Docker Desktop must be running locally.

## Local staging (the single-command local boot)

```bash
scripts/staging.sh init      # once: writes .env.staging with random secrets (git-ignored)
scripts/staging.sh start     # build and start everything at http://127.0.0.1:8088
scripts/staging.sh status    # every service should be "running (healthy)"
scripts/staging.sh logs
scripts/staging.sh stop
```

On this Windows machine, building every image at once has crashed Docker Desktop before. If
that happens, build one at a time and then start:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml build backend
docker compose --env-file .env.staging -f docker-compose.staging.yml build frontend
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d
```

The first start after the Phase 0 change builds `infra/postgres` (PostgreSQL + pgvector) and
runs migration `20261113_0008`.

After the Phase 1 change, run `scripts/staging.sh init` once more: it adds `APP_DB_PASSWORD`
(the limited database login the API uses) to the existing `.env.staging` without touching the
other values. Then start as usual; the migrate service creates the login.

**Account emails on staging** (verification, password reset, invitations) are not sent; they
are written to the API log. Find the link with:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml logs backend | grep -E "verify_email=|reset_password=|invite="
```

Replace `localhost` with `127.0.0.1` in the link if the browser is open on `127.0.0.1`
(the session cookie belongs to the address you signed in on).

## Tests

```bash
scripts/test_backend.sh                # every backend test, with throwaway Redis + PostgreSQL
scripts/test_backend.sh -k storage     # a subset
```

The Redis and PostgreSQL tests skip themselves when `REDIS_TEST_URL` / `POSTGRES_TEST_URL` are
not set; the script and CI set both. CI (`.github/workflows/ci.yml`) also runs `pip-audit`,
the frontend type check/build and `npm audit`.

## Health

| Check | Healthy answer |
|---|---|
| `GET /api/health` | `{"status": "ok"}` (process is up) |
| `GET /api/health/ready` | `"status": "ready"`, `"database": "ok"`, `"row_level_security": "enforced"`, `"queue": "ok"`, `"worker": "ok"` |
| `GET /api/features` | `{"enabled_channels": ["web_chat", "whatsapp"], "broadcasts": false}` |

`worker` reads `unknown` for up to a minute after start (first heartbeat) and `stale` if the
worker stopped; the API keeps serving either way. Docker restarts unhealthy containers that
have `restart: unless-stopped`.

## Backups (current state)

`scripts/staging.sh backup` writes a database dump plus an archive of uploads and private
storage to `.staging-backups/`; `scripts/staging.sh restore-check PATH` restores a dump into a
throwaway database to prove it works. **Production backups that leave the server are not built
yet**; they are required before any real institution's data goes in (spec Sections 14 and 17).
Back up `.env.production` separately: `TENANT_CHANNEL_SECRET_KEY` decrypts stored channel
credentials and must not sit inside the database backup.

## Production deployment (pilot server)

Do not buy a server until the steps in `docs/vps-sizing.md` say it is time.

1. Ubuntu LTS server with Docker Engine + Compose plugin. Firewall: allow 80, 443 and SSH (key only).
2. Point the domain's DNS `A` record at the server.
3. Copy the repository, then `cp .env.example .env.production`, fill every value, and
   `chmod 600 .env.production`.
4. Start:
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
   docker compose --env-file .env.production -f docker-compose.prod.yml ps
   ```
5. Check `https://APP_DOMAIN/api/health/ready`.

Upgrades: back up first, then `git pull` and the same `up -d --build`. `migrate` runs before the
new API starts; if a migration fails, Compose stops with an error and the new API does not start
(`depends_on ... service_completed_successfully`). Fix the migration or restore the backup.
