# Apply Batch 5

1. Stop backend and frontend servers.
2. Back up the current folder:

```bash
cd /Users/fouad/Desktop
mv agent_SW_final_rebuild agent_SW_final_rebuild_batch4_1_backup
```

3. Unzip Batch 5 to the Desktop.
4. Copy the working backend `.env` back:

```bash
cp /Users/fouad/Desktop/agent_SW_final_rebuild_batch4_1_backup/backend/.env /Users/fouad/Desktop/agent_SW_final_rebuild/backend/.env
```

5. Start backend:

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

6. Start frontend:

```bash
cd /Users/fouad/Desktop/agent_SW_final_rebuild/frontend
npm install
npm run dev
```

7. Open the dashboard and test the new **UAT Tests** tab.
