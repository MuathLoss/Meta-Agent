# Decisions

Implementation decisions made while following spec v1.2. Product decisions live in the spec.

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 2026-11-13 | Build the product on Agent SW, not a new repository | Spec v1.2, Section 2.1 |
| D2 | 2026-11-13 | Keep Agent SW's `tenant` naming; spec `institution` = `tenant`, `institution_id` = `tenant_id` | Renaming working tables adds risk and no value |
| D3 | 2026-11-13 | PostgreSQL image = official `postgres:16.15-trixie` + PGDG `postgresql-16-pgvector` 0.8.x (`infra/postgres/Dockerfile`), not `pgvector/pgvector:*-pg16` | The default pgvector tag runs Debian bookworm (glibc 2.36). The staging database was created on trixie (glibc 2.41); switching gave "collation version mismatch", which can corrupt text indexes (Arabic included). Postgres ran on the wrong image for about 10 seconds, read-only, before being stopped |
| D4 | 2026-11-13 | Redis `7.4-alpine`, `noeviction`, append-only file, password in production | Queue jobs must never be evicted or lost on restart. Redis 7.4 is licensed RSALv2/SSPL, which allows internal use as a queue; Valkey is a drop-in BSD alternative if the team prefers |
| D5 | 2026-11-13 | `rq==2.12.0`, not 3.0.0 | 3.0.0 is a new major version released 2026-10-28 |
| D6 | 2026-11-13 | Periodic jobs run inside the one worker: each run books the next time slot under a slot-based job id | Spec: no separate scheduler container. Same slot = same id, so restarts never run a slot twice |
| D7 | 2026-11-13 | Storage = local disk on a Docker volume (`STORAGE_BACKEND=local`); Garage later | Spec v1.2, T06 |
| D8 | 2026-11-13 | Switched-off channels and broadcasts answer 404; production refuses `BROADCASTS_ENABLED`/`OLLAMA_ENABLED`; code kept | Spec v1.2, Section 2.1 and acceptance criterion 16 |
| D9 | 2026-11-13 | Readiness fails on database always, on Redis only in staging/production; worker status is reported, not required | A stopped worker must not take the API down; local development may run without Redis |
| D10 | 2026-11-13 | Caddy sends `/api/*` straight to the backend instead of through the frontend's nginx | One proxy hop, so forwarded client address and HTTPS scheme reach the API correctly |
| D11 | 2026-11-13 | Seed and test data: use synthetic `School A`/`School B`, not `seed_academy` | `seed_academy` holds a real-looking institution name and phone number (spec Section 2.1) |

## Must handle in Phase 1

- **The app connects to PostgreSQL as the database owner** (the `POSTGRES_USER` superuser in
  the Docker image). Row-level security does not apply to superusers or table owners by
  default, so RLS (spec Section 8) needs a separate non-owner application role, with
  migrations still run as the owner.
- `APP_SECRET_KEY` in the local `backend/.env` is 31 bytes; PyJWT warns below 32. Staging and
  production already require 32+.
