# Apply Batch 4

Use the same safe replacement method as earlier batches.

```bash
cd /Users/fouad/Desktop
mv agent_SW_final_rebuild agent_SW_final_rebuild_batch3_backup
```

Unzip Batch 4 so this exists:

```text
/Users/fouad/Desktop/agent_SW_final_rebuild
```

Copy your working environment file:

```bash
cp /Users/fouad/Desktop/agent_SW_final_rebuild_batch3_backup/backend/.env /Users/fouad/Desktop/agent_SW_final_rebuild/backend/.env
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
