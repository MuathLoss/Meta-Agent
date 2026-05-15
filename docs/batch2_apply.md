# Batch 2 apply notes

Batch 2 builds on Batch 1. It adds tenant configuration CRUD APIs and a functional React dashboard shell.

## What changed

Backend:
- Added `/tenants/current`
- Added business profile update
- Added business settings CRUD
- Added branches CRUD
- Added staff/user role creation
- Added FAQ CRUD
- Added intent and keyword CRUD
- Added routing rule upsert
- Added training examples API
- Added conversation handoff/resolve/reopen
- Added customer update
- Added ticket create/update
- Added audit log listing
- Improved dashboard inbox/conversation payloads
- Fixed `scripts/init_db.py` so it works without manually setting `PYTHONPATH`
- Pinned `bcrypt==4.0.1` to avoid the passlib/bcrypt issue on Python 3.12

Frontend:
- Added maroon-to-black dashboard tabs
- Added overview/readiness/runtime preview
- Added inbox and conversation view
- Added settings + branches
- Added staff
- Added FAQ
- Added intents + routing view
- Added tenant-scoped channel settings
- Added tickets/customers/broadcasts/audit views
- Added create-business signup path

## Apply

Copy the new files over your current `agent_SW_final_rebuild` folder. Do not delete your `.env`.

Then run:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/backend
source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
python -m app.seed.seed_academy
PYTHONPATH=. python -m uvicorn main:app --reload
```

In another terminal:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Login:

```text
academy.admin@example.com
ChangeMe123!
sarh-almarifah
```

## Important

This is still not final production. It is Batch 2: configuration CRUD + frontend operations shell. Next batch should harden the runtime engine, WhatsApp adapter, idempotency tests, onboarding wizard step screens, and deployment files.
