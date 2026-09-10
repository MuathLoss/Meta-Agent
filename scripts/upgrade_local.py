"""Back up an existing PostgreSQL workspace before the additive September upgrade."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.chdir(ROOT / 'backend')
from app.core.config import settings
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply the additive migration after a verified backup.')
    args = parser.parse_args()
    engine = create_engine(settings.database_url)
    if engine.dialect.name != 'postgresql':
        raise SystemExit('This upgrade helper requires the existing PostgreSQL workspace.')
    with engine.connect() as conn:
        revision = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        if revision == '20260910_0007':
            print('Database is already up to date. No changes needed.')
            return
        if revision != '20260515_0006':
            raise SystemExit('Unexpected schema revision. Review migration history before upgrading.')
        names = [name for name in inspect(conn).get_table_names() if name != 'alembic_version']
        quote = engine.dialect.identifier_preparer.quote
        before = {name: conn.execute(text(f'SELECT count(*) FROM {quote(name)}')).scalar_one() for name in names}
    candidates = [shutil.which('pg_dump'), '/Library/PostgreSQL/18/bin/pg_dump', '/opt/homebrew/opt/postgresql@16/bin/pg_dump']
    binary = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if not binary:
        raise SystemExit('Install PostgreSQL client tools (pg_dump and pg_restore) before upgrading.')
    restore = binary.with_name('pg_restore')
    if not restore.is_file():
        raise SystemExit('pg_restore is required to verify the backup archive.')
    os.umask(0o077)
    destination = ROOT / '.local-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination.mkdir(parents=True, mode=0o700)
    url = make_url(settings.database_url)
    env = {**os.environ, 'PGHOST': url.host or 'localhost', 'PGPORT': str(url.port or 5432), 'PGUSER': url.username or '', 'PGPASSWORD': url.password or '', 'PGDATABASE': url.database or ''}
    archive = destination / 'database.dump'
    with archive.open('xb') as output:
        result = subprocess.run([str(binary), '-Fc', '--no-owner'], env=env, stdout=output, stderr=subprocess.PIPE)
    if result.returncode:
        raise SystemExit('Database backup failed. No migration was applied; check PostgreSQL client compatibility and access.')
    verified = subprocess.run([str(restore), '--list', str(archive)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if verified.returncode:
        raise SystemExit('Backup archive verification failed. No migration was applied.')
    shutil.copyfile(ROOT / 'backend' / '.env', destination / 'backend.env')
    if (ROOT / 'backend' / 'uploads').is_dir():
        shutil.make_archive(str(destination / 'uploads'), 'gztar', ROOT / 'backend', 'uploads')
    print('Verified private backup:', destination)
    if not args.apply:
        print('Backup complete. Run with --apply to add import history.')
        return
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
    with engine.connect() as conn:
        after = {name: conn.execute(text(f'SELECT count(*) FROM {quote(name)}')).scalar_one() for name in names}
        head = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    if before != after or head != '20260910_0007':
        raise SystemExit('Upgrade verification needs review. Keep the backup; no automatic restore was attempted.')
    print('Upgrade verified. Existing table row counts are unchanged.')

if __name__ == '__main__':
    main()
