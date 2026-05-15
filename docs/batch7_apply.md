# Apply Batch 7

1. Stop backend and frontend servers.
2. Rename the current project folder as a backup:

```bash
cd /Users/fouad/Desktop
mv agent_SW_final_rebuild agent_SW_final_rebuild_batch6_backup
```

3. Unzip Batch 7 to the Desktop.
4. Copy your working `.env`:

```bash
cp /Users/fouad/Desktop/agent_SW_final_rebuild_batch6_backup/backend/.env /Users/fouad/Desktop/agent_SW_final_rebuild/backend/.env
```

5. Run backend:

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

6. Run frontend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/frontend
npm install
npm run dev
```

7. Open the dashboard and check the new **Final Handoff** tab.
