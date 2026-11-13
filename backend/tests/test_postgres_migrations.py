"""Migrations forward and back on real PostgreSQL with pgvector (spec v1.2, Phase 0).

Runs when POSTGRES_TEST_URL points at an empty, throwaway database (CI and the Docker test
command in docs/operations.md). Never point it at a database you care about.
"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="POSTGRES_TEST_URL not set")

BACKEND_DIR = Path(__file__).resolve().parents[1]


def vector_installed(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first() is not None
    finally:
        engine.dispose()


def test_migrations_upgrade_downgrade_and_upgrade_again(monkeypatch):
    monkeypatch.setattr(settings, "database_url", POSTGRES_TEST_URL)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.upgrade(config, "head")
    assert vector_installed(POSTGRES_TEST_URL)

    command.downgrade(config, "20260910_0007")
    assert not vector_installed(POSTGRES_TEST_URL)

    command.upgrade(config, "head")
    assert vector_installed(POSTGRES_TEST_URL)
