# Configurable Multi-Tenant Business Agent Platform

> **Current direction (2026-11-13):** this codebase is being evolved into the Institution AI
> Chatbot SaaS described in spec v1.2 (website widget + WhatsApp, knowledge answers from each
> institution's own documents). Start with `docs/operations.md` (run and test),
> `docs/architecture.md`, `docs/decisions.md` and `docs/remaining-launch-blockers.md`.
> Broadcasts, Ollama, Telegram, email and Meta social channels are switched off for this
> product; the sections below describe the original platform.

Production-bound rebuild for a configurable multi-tenant business agent platform.

- Academy = Tenant #1 only.
- WhatsApp = Channel #1 only.
- Future channels must plug into the same channel-agnostic core.
- Business-specific behavior comes from tenant-scoped configuration, not hardcoded logic.
- Tenant channel credentials are stored encrypted in `channel_configs`, not as one global WhatsApp config in `.env`.

## Local run

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python -m app.seed.seed_academy
PYTHONPATH=. pytest -q
PYTHONPATH=. python -m uvicorn main:app --reload
```

Optional Ollama fallback:

```bash
ollama serve
ollama pull gemma4:e4b
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

All-in-one local dev runner:

```bash
chmod +x start_all.sh stop_all.sh
./start_all.sh
```

More local runner notes:

- [docs/local-dev.md](/Users/fouad/Desktop/agent_SW_final_rebuild/docs/local-dev.md)

Login:

```text
email: academy.admin@example.com
password: ChangeMe123!
tenant slug: sarh-almarifah
```

## Final local checks

- `/health`
- `/health/ready`
- Swagger `/docs`
- Dashboard Overview
- UAT Tests tab
- Deployment tab
- Final Handoff tab

## Remaining external blocker

The academy cannot go live on WhatsApp until its tenant-specific WhatsApp package is provided: business number, WABA ID, PHONE_NUMBER_ID, production token, app secret, verify token, approved templates, and public HTTPS callback URL.
