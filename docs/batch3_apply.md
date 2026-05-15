# Batch 3 apply guide

Batch 3 upgrades Batch 2 with onboarding wizard UI, runtime classification testing, tenant-scoped WhatsApp webhook hardening, idempotency behavior, and an outbound adapter boundary.

## Apply safely

1. Stop backend and frontend servers.
2. Rename the current folder as a backup:

```bash
cd /Users/fouad/Desktop
mv agent_SW_final_rebuild agent_SW_final_rebuild_batch2_backup
```

3. Unzip Batch 3 to Desktop.
4. Copy your working backend `.env` back:

```bash
cp /Users/fouad/Desktop/agent_SW_final_rebuild_batch2_backup/backend/.env /Users/fouad/Desktop/agent_SW_final_rebuild/backend/.env
```

5. Backend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python -m app.seed.seed_academy
PYTHONPATH=. python -m uvicorn main:app --reload
```

6. Frontend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/frontend
npm install
npm run dev
```

## What to test

1. Login at `http://127.0.0.1:5173`.
2. Open the Onboarding tab and save a step draft.
3. Use the Runtime engine proof classifier.
4. Use Overview runtime preview.
5. Confirm Inbox creates conversation history.
6. In Swagger, test `POST /runtime/classify` and `POST /runtime/scenario` with `X-Tenant-Slug: sarh-almarifah`.

## Notes

- Live WhatsApp sending is disabled unless a tenant channel config has `public_config.live_send_enabled = true` and real tenant credentials.
- WhatsApp credentials remain tenant-scoped and encrypted in `channel_configs`.
- Webhook retries are deduplicated by provider message ID.
