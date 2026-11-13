# Architecture

Product contract: `Institution_AI_Chatbot_SaaS_Claude_Code_Spec_v1.2.md` (kept on the owner's Desktop).
This file describes what is built today. Last updated 2026-11-13, after Phase 0.

## Services

One Linux server running Docker Compose (`docker-compose.prod.yml`). Local staging
(`docker-compose.staging.yml`) runs the same services, minus Caddy, on http://127.0.0.1:8088.

| Service | What it does | Network |
|---|---|---|
| `caddy` | HTTPS certificates, routes `/api/*` to `backend` and everything else to `frontend` | edge (ports 80/443) |
| `frontend` | Static React build served by nginx; no Node.js at runtime | edge |
| `backend` | FastAPI, one process: dashboard API, website widget, Meta webhooks | edge + data |
| `worker` | One RQ worker, one job at a time; also runs periodic jobs | edge + data |
| `migrate` | Runs Alembic migrations, then exits | data |
| `postgres` | PostgreSQL 16 + pgvector; all lasting data | data only |
| `redis` | Job queue only (no billing or usage state) | data only |

The `data` network is `internal`: it has no internet access and Caddy cannot reach it. Only
Caddy publishes ports. `backend/tests/test_compose_exposure.py` checks this on every test run.

## Request paths

```text
Visitor / admin / Meta ──HTTPS──> caddy ─┬─ /api/*  ──> backend ──> postgres, redis, storage volume
                                          └─ /*      ──> frontend (static files)
backend ──enqueue──> redis ──> worker ──> postgres, storage volume (Gemini and Meta from Phase 2/6)
```

Meta's WhatsApp webhook URL is `https://APP_DOMAIN/api/channels/whatsapp/webhook`.

## Building blocks added in Phase 0

- **Product scope switches** (`backend/app/core/features.py`): only `web_chat` and `whatsapp`
  are on. Routes for other channels and for broadcasts answer 404, outbound sends refuse them,
  and the dashboard hides them (it reads `GET /api/features`). Production refuses to start with
  broadcasts or Ollama switched on.
- **Job queue** (`backend/app/jobs/`): `get_queue()` for enqueueing; periodic jobs in
  `periodic.py` (today only a heartbeat; retention, reconciliation and alerts come later).
- **Private storage** (`backend/app/services/storage/`): `ObjectStorage` interface with a
  local-disk adapter on the `app_storage` volume. Keys follow
  `tenant/{tenant_id}/documents/{document_id}/{safe_name}`; `ensure_tenant_key()` refuses
  another tenant's key. Files are never served straight from disk.
- **pgvector**: migration `20261113_0008` enables the extension. No vector columns yet (Phase 2).
- **Health**: `GET /health/ready` reports `database`, `queue` and `worker`. Database is
  always required; the queue is required on staging/production; the worker is reported only.

## Naming

Agent SW says `tenant` where the spec says `institution`. They are the same thing; see
`docs/decisions.md`.

## Not built yet

RAG ingestion and answers (Phase 2), cookie sessions + Argon2id + RLS (Phase 1), billing and
quotas (Phase 5), WhatsApp quota/window logic (Phase 6), off-server backups (see
`docs/remaining-launch-blockers.md`).
