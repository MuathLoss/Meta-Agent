# Deployment Runbook

## Local development

Backend:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python -m app.seed.seed_academy
PYTHONPATH=. python -m uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
```

## Due broadcast worker

Run manually for now:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/run_due_broadcasts.py
```

Later, run this command from a scheduler or worker process every minute.

## Docker database only

```bash
docker compose up -d postgres
```

## Docker full profile

Only use after `.env` is ready:

```bash
docker compose --profile full up --build
```

## Production rules

- Never commit `.env`.
- `TENANT_CHANNEL_SECRET_KEY` must be a valid Fernet key.
- Tenant WhatsApp credentials stay in tenant `channel_configs`, not global env.
- Use public HTTPS before connecting Meta webhooks.
- Keep staging before production go-live.
