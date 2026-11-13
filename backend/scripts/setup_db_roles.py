"""Create or update the application's own database login (spec v1.2, Section 8).

Run by the migrate service after `alembic upgrade head`, connected as the database owner.
The API and worker then connect as APP_DB_USER, which can read and write rows but owns no
table, is not a superuser and cannot bypass row-level security, so the policies apply to it.
Safe to run repeatedly; changing APP_DB_PASSWORD and re-running rotates the password.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.core.config import settings


def main() -> None:
    role = os.environ.get("APP_DB_USER", "agent_app")
    password = os.environ.get("APP_DB_PASSWORD", "")
    owner_url = os.environ.get("MIGRATION_DATABASE_URL") or settings.database_url
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise SystemExit("APP_DB_USER must be a plain lower-case identifier")
    if not owner_url.startswith("postgresql"):
        print("setup_db_roles: not PostgreSQL, nothing to do")
        return
    if len(password) < 16:
        raise SystemExit("APP_DB_PASSWORD must be set (16+ characters) to create the application role")
    engine = create_engine(owner_url)
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
        verb = "ALTER" if exists else "CREATE"
        # Identifiers cannot be bound parameters; the role name is validated above and the
        # password is passed through format() with literal quoting by PostgreSQL itself.
        quoted_password = conn.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar_one()
        conn.execute(text(f"{verb} ROLE {role} LOGIN PASSWORD {quoted_password} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"))
        database = conn.execute(text("SELECT current_database()")).scalar_one()
        owner = conn.execute(text("SELECT current_user")).scalar_one()
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {role}'))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
        conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
        # The migration history is the owner's business only.
        conn.execute(text(f"REVOKE ALL ON TABLE alembic_version FROM {role}"))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}'))
        conn.execute(text(f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}'))
    print(f"setup_db_roles: {'updated' if exists else 'created'} role {role}; row-level security applies to it")


if __name__ == "__main__":
    main()
