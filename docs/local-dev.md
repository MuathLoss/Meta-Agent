# Local Development Runner

Use the root helper when you want the backend, frontend, and Telegram polling worker in one terminal.

## Run everything

From the project root:

```bash
chmod +x start_all.sh stop_all.sh
./start_all.sh
```

What it does:

- Checks that ports `8000` and `5173` are free before starting.
- Checks whether PostgreSQL is ready.
- Tries to start PostgreSQL with Homebrew if it can detect a local `brew services` PostgreSQL install.
- If PostgreSQL cannot be confirmed automatically, the runner prints a warning and still tries to start the app services.
- Starts:
  - FastAPI backend on `http://127.0.0.1:8000`
  - Vite frontend on `http://localhost:5173`
  - Telegram polling worker in loop mode

Useful URLs:

- Frontend: `http://localhost:5173`
- Backend docs: `http://127.0.0.1:8000/docs`

## Stop everything

If `./start_all.sh` is running in your terminal, press `Ctrl+C`.

If that terminal was closed or interrupted unexpectedly, run:

```bash
./stop_all.sh
```

## If port 8000 or 5173 is already in use

The runner will stop before launching services if either port is busy.

To see what is using a port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

Then either:

- stop the old process that is already using the port, or
- run `./stop_all.sh` if it was started by this runner, or
- close the terminal/session that is still holding the process open

After the port is free, run `./start_all.sh` again.

## When pgAdmin is needed

pgAdmin is **not** required to run the app locally.

You only need PostgreSQL itself running so the backend can connect to the database.

Use pgAdmin only when you want a GUI to inspect tables, run SQL manually, or troubleshoot database contents. For normal local development startup, PostgreSQL is enough and pgAdmin can stay closed.

## If PostgreSQL is not auto-detected

Some macOS setups do not expose `pg_isready` on `PATH`, and some local PostgreSQL installs are not managed by `brew services`.

In that case, `./start_all.sh` will warn and continue. If the backend then exits with a database connection error, start PostgreSQL manually using your usual method and run:

```bash
./start_all.sh
```
