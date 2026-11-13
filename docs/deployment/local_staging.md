# Local staging and recovery

Local staging uses its own PostgreSQL database and uploads volume. It does not read the development database or provider credentials. Only the web interface is exposed, on `http://127.0.0.1:8088`. No public hosting has been selected.

From the project folder:

```sh
bash scripts/staging.sh init
bash scripts/staging.sh start
bash scripts/staging.sh check
```

`init` generates private random secrets in `.env.staging` and refuses to overwrite an existing file. `start` builds the interface and backend, waits for PostgreSQL, applies migrations, and waits for backend health before exposing the interface. Create a test workspace using the signup screen. Provider workers are off by default.

```sh
bash scripts/staging.sh status
bash scripts/staging.sh logs
bash scripts/staging.sh backup
bash scripts/staging.sh restore-check .staging-backups/database-TIMESTAMP.dump
bash scripts/staging.sh stop
```

Backups include the database and uploads. The restore check imports the database archive into a temporary database, verifies its schema, and deletes only that temporary database. Keep `.env.staging` in secure backup too: its encryption key is required to open saved credentials and import reviews. Protect backups as carefully as live customer data. The local backup command is manual; retention, off-device storage, and scheduling must be configured when hosting is chosen.

The backend runs as an unprivileged user; only its uploads folder is writable. The API reference is off in staging (see `API_DOCS_ENABLED` in [environment](environment.md)). Staging uses a fixed private network, `172.28.88.0/24`, so the backend can trust the visitor addresses its proxy forwards. If that range clashes with another network on the machine, set `STAGING_SUBNET` in `.env.staging` to a free private range.

Container health checks run automatically, and logs rotate at 10 MB with three files per service. `scripts/staging_smoke.py` checks the UI, API liveness, and database readiness and exits unsuccessfully if any check fails. It can be connected to a host's monitor later. No external alert service is configured yet.

## Preparing for a hosted pilot

Before exposing staging publicly: choose hosting and a domain; configure HTTPS and the real frontend/CORS origins; preserve the database, upload volume, and encryption keys; configure off-device backups and alerts; and complete the production checklist. `staging/Caddyfile.example` is an HTTPS proxy template for that later step. The current Compose binding is intentionally local.

For each real provider account, save its details in **Channels**, run **Check saved connection**, and test both inbound delivery and a reply using an account you control. A connection check confirms authentication; the virtual reply tests only knowledge and handoff behavior. Neither proves real delivery.

Telegram's local polling worker is started by `start_all.sh`. It preserves existing webhooks. A bot already using a webhook requires an explicit decision to switch to polling; do not run two polling workers for one token. For staging, start the `provider-workers` profile only after intentionally configuring a test bot. Email polling is off in staging; enable `EMAIL_POLLING_ENABLED` on one backend instance when its test mailbox is ready. Meta channels need public HTTPS webhooks and app permissions, which are deferred until hosting is chosen. Set the supported Graph API version in advanced provider settings; existing accounts retain their previous default until changed.

Sources: [Compose startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/), [PostgreSQL backup and restoration](https://www.postgresql.org/docs/16/backup-dump.html), [Telegram Bot API](https://core.telegram.org/bots/api).
