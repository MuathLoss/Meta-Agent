# VPS sizing (pilot target: 4 shared vCPU / 8 GB RAM / 100 GB SSD)

Spec v1.2, Section 14.1. Nothing has been bought. Contabo Cloud VPS 4 is a candidate, not a commitment.

## Memory limits in `docker-compose.prod.yml`

| Service | Limit | CPU limit | Note |
|---|---:|---:|---|
| postgres | 1536 MB | 2.0 | `shared_buffers=384MB`, `effective_cache_size=2GB`, `max_connections=40` |
| worker | 768 MB | 1.0 | One job at a time; headroom for PDF parsing in Phase 2 |
| backend | 512 MB | 1.0 | One uvicorn process |
| redis | 256 MB | 0.5 | `maxmemory 192mb`, `noeviction` |
| caddy | 128 MB | 0.5 | |
| frontend | 64 MB | 0.25 | Static files only |
| **Total** | **3.3 GB** | | Leaves about 4.7 GB for Linux, the page cache and PostgreSQL's file cache |

## Measured on 2026-11-13 (local staging, Docker Desktop on Windows)

These numbers are from the developer's computer, **not** a VPS, and before any AI or document
work exists. Re-measure on the real server and after Phase 2.

| Measure | Result |
|---|---|
| Idle memory, all 5 services | about 190 MB (backend 95, worker 45, postgres 30, frontend 13, redis 6) |
| After 1,500 requests, 20 at a time (health, features, dashboard page) | about 200 MB; 357 requests/s; median 40 ms, p95 72 ms; 0 errors |
| Images on disk | about 1.4 GB (postgres 741 MB, backend 386 MB, frontend 93 MB, caddy 83 MB, redis 59 MB) |
| Data volumes | database 50 MB (test data), redis < 1 MB, storage empty |

## What will change these numbers

Phase 2 adds PDF/DOCX parsing in the worker, Gemini calls, and vector indexes in PostgreSQL. At
768 dimensions one stored chunk vector is about 3 KB plus index overhead. Measure the worker's
peak memory while parsing a 10 MB PDF before trusting the 768 MB limit.

## Upgrade triggers (to set from real measurements)

Write the thresholds here after a week on the pilot server, for example: sustained memory above
80% of 8 GB, PostgreSQL cache hit ratio below 99%, p95 chat latency above an agreed target, disk
above 70%, or ingestion queue waits above an agreed time.

## Pre-purchase checklist

- [ ] Local stack boots and all tests pass (`scripts/staging.sh start`, `scripts/test_backend.sh`)
- [ ] HTTPS/webhook testing is actually needed now (Meta test number, or a real domain to show)
- [ ] Owner approves the purchase explicitly; short-term (monthly) contract, **no 24-month term**
- [ ] Data-center country recorded, and what the product says about data location matches it (spec criterion 14)
- [ ] Real checkout price including setup fee, VAT and renewal price recorded in `docs/monthly-cost-assumptions.md`
- [ ] Off-server backup target chosen and its price recorded
- [ ] Domain bought and DNS access available
