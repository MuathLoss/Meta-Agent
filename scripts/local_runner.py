"""Portable local supervisor. Uses explicit interpreters, never a moved activate script."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / '.dev-runner' / 'processes.json'


def say(message):
    print(f'[workspace] {message}', flush=True)


def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def stop(records):
    for record in reversed(records):
        pid = record['pid']
        if not record.get('identity') or identity(pid) != record['identity']:
            continue
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(identity(r['pid']) == r['identity'] for r in records):
        time.sleep(.1)
    for record in records:
        if record.get('identity') and identity(record['pid']) == record['identity']:
            try:
                os.killpg(record['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass


def reachable(url, ready=False):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200 and (not ready or json.load(response).get('status') == 'ready')
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'check'], nargs='?', default='start')
    parser.add_argument('--without-telegram', action='store_true')
    args = parser.parse_args()
    if args.action == 'stop':
        if MANIFEST.exists():
            saved = json.loads(MANIFEST.read_text())
            if saved.get('root') != str(ROOT):
                raise SystemExit('Runner record belongs to another folder; nothing was stopped.')
            saved['stopping'] = True
            MANIFEST.write_text(json.dumps(saved))
            stop(saved['processes'])
            MANIFEST.unlink(missing_ok=True)
        say('Project services stopped.')
        return
    python = ROOT / 'backend' / '.venv' / 'bin' / 'python'
    if not python.exists():
        raise SystemExit('Python environment missing. Run setup_local.sh first.')
    probe = subprocess.run([str(python), '-c', 'import fastapi,uvicorn,sqlalchemy,alembic,openpyxl'], capture_output=True)
    if probe.returncode:
        raise SystemExit('Backend dependencies are incomplete. Run setup_local.sh.')
    if not (ROOT / 'backend' / '.env').exists():
        raise SystemExit('Backend configuration is missing. Copy backend/.env.example to backend/.env and configure it.')
    if not (ROOT / 'frontend' / 'node_modules').is_dir():
        raise SystemExit('Frontend dependencies are missing. Run setup_local.sh.')
    say('Python and frontend dependencies found. This folder can be moved safely.')
    if args.action == 'check':
        return
    if MANIFEST.exists():
        saved = json.loads(MANIFEST.read_text())
        if any(r.get('identity') and identity(r['pid']) == r['identity'] for r in saved.get('processes', [])):
            raise SystemExit('This project is already running. Use stop_all.sh first.')
    for port in (8000, 5173):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} is already in use. Stop its server before starting this project.')
    records, children = [], []
    MANIFEST.parent.mkdir(exist_ok=True)
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend'), 'PYTHONUNBUFFERED': '1'}
    def launch(name, command, cwd):
        child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
        children.append(child)
        records.append({'name': name, 'pid': child.pid, 'identity': identity(child.pid)})
        MANIFEST.write_text(json.dumps({'root': str(ROOT), 'processes': records}))
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        launch('backend', [str(python), '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], ROOT / 'backend')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if children[0].poll() is not None:
                raise RuntimeError('Backend could not start; check the error above.')
            if reachable('http://127.0.0.1:8000/health/ready', ready=True):
                break
            time.sleep(.4)
        else:
            raise RuntimeError('Database is unavailable. Start PostgreSQL and check your backend configuration.')
        launch('frontend', ['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], ROOT / 'frontend')
        deadline = time.monotonic() + 30
        while not reachable('http://127.0.0.1:5173'):
            if time.monotonic() > deadline or children[1].poll() is not None:
                raise RuntimeError('Frontend could not start; check the error above.')
            time.sleep(.4)
        if not args.without_telegram:
            launch('telegram', [str(python), 'scripts/run_telegram_polling.py', '--loop', '--keep-webhook'], ROOT / 'backend')
        say('Ready: http://127.0.0.1:5173 — press Ctrl+C to stop.')
        while True:
            try:
                if json.loads(MANIFEST.read_text()).get('stopping'):
                    break
            except FileNotFoundError:
                break
            except json.JSONDecodeError:
                continue
            for child, record in zip(children, records):
                if child.poll() is not None:
                    raise RuntimeError(f"{record['name']} stopped unexpectedly; see its error above.")
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        # stop_all owns signaling after setting this flag. Reap our children
        # without racing it to signal the same (possibly exited) process group.
        try:
            external_stop = json.loads(MANIFEST.read_text()).get('stopping', False)
        except FileNotFoundError:
            external_stop = True
        except json.JSONDecodeError:
            external_stop = False
        if not external_stop:
            stop([record for child, record in zip(children, records) if child.poll() is None])
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise RuntimeError('A project service did not stop. Run stop_all.sh again.')
        MANIFEST.unlink(missing_ok=True)
        say('All project services stopped.')

if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        say(str(exc))
        sys.exit(1)
