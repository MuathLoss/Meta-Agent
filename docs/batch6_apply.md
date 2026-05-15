# Batch 6 Apply Guide

Use the same safe replacement method.

```bash
cd /Users/fouad/Desktop
mv agent_SW_final_rebuild agent_SW_final_rebuild_batch5_backup
```

Unzip Batch 6 to Desktop, then copy your working `.env`:

```bash
cp /Users/fouad/Desktop/agent_SW_final_rebuild_batch5_backup/backend/.env /Users/fouad/Desktop/agent_SW_final_rebuild/backend/.env
```

Backend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python -m app.seed.seed_academy
PYTHONPATH=. pytest -q
PYTHONPATH=. python -m uvicorn main:app --reload
```

Frontend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`, login, then test the new **Deployment** tab.
