"""Spec v1.2, Section 8 and Phase 1: tenant isolation enforced by PostgreSQL itself.

Connects as the limited application login (scripts/setup_db_roles.py), never as the owner, and
shows that queries WITHOUT any tenant filter still only reach the current tenant's rows. Then
runs sign-up, sign-in and invitations through the real API on the same database. Runs when
POSTGRES_TEST_URL points at a throwaway database (CI and scripts/test_backend.sh).
"""
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="POSTGRES_TEST_URL not set")

APP_ROLE = "agent_app_test"
APP_PASSWORD = "test-only-app-password-1"
BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pg():
    from app.core.config import settings
    from scripts import setup_db_roles

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "database_url", POSTGRES_TEST_URL)
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        command.upgrade(config, "head")
        mp.setenv("APP_DB_USER", APP_ROLE)
        mp.setenv("APP_DB_PASSWORD", APP_PASSWORD)
        mp.setenv("MIGRATION_DATABASE_URL", POSTGRES_TEST_URL)
        setup_db_roles.main()
    app_url = make_url(POSTGRES_TEST_URL).set(username=APP_ROLE, password=APP_PASSWORD)
    app_engine = create_engine(app_url)
    owner_engine = create_engine(POSTGRES_TEST_URL)
    yield SimpleNamespace(app_engine=app_engine, Session=sessionmaker(bind=app_engine), owner_engine=owner_engine)
    app_engine.dispose()
    owner_engine.dispose()


@pytest.fixture()
def two_tenants(pg):
    from app.models.entities import FaqItem, Tenant

    suffix = uuid.uuid4().hex[:8]
    with pg.Session() as db:  # no tenant bound = trusted system work
        a = Tenant(slug=f"rls-a-{suffix}", display_name="RLS A", status="active")
        b = Tenant(slug=f"rls-b-{suffix}", display_name="RLS B", status="active")
        db.add_all([a, b])
        db.flush()
        fa = FaqItem(tenant_id=a.id, topic_key="fees", arabic_answer="A fees", status="active")
        fb = FaqItem(tenant_id=b.id, topic_key="fees", arabic_answer="B fees", status="active")
        db.add_all([fa, fb])
        db.commit()
        ids = SimpleNamespace(a=a.id, b=b.id, faq_a=fa.id, faq_b=fb.id)
    yield ids
    with pg.owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": ids.a, "b": ids.b})


def test_the_app_login_cannot_skip_row_level_security(pg):
    import main

    with pg.Session() as db:
        assert main.row_level_security_status(db) == "enforced"


def test_unfiltered_queries_only_see_the_bound_tenant(pg, two_tenants):
    from app.core.db import bind_tenant
    from app.models.entities import FaqItem, Tenant

    with pg.Session() as db:
        bind_tenant(db, two_tenants.a)
        assert {row.tenant_id for row in db.query(FaqItem).all()} == {two_tenants.a}
        assert db.get(FaqItem, two_tenants.faq_b) is None  # a guessed id from tenant B
        assert [t.id for t in db.query(Tenant).all()] == [two_tenants.a]
        db.commit()  # the scope survives a commit: the next transaction is bound again
        assert db.get(FaqItem, two_tenants.faq_b) is None


def test_writes_into_another_tenant_are_refused(pg, two_tenants):
    from app.core.db import bind_tenant
    from app.models.entities import FaqItem

    with pg.Session() as db:
        bind_tenant(db, two_tenants.a)
        changed = db.query(FaqItem).filter(FaqItem.id == two_tenants.faq_b).update({FaqItem.arabic_answer: "hacked"})
        deleted = db.query(FaqItem).filter(FaqItem.id == two_tenants.faq_b).delete()
        assert (changed, deleted) == (0, 0)
        db.add(FaqItem(tenant_id=two_tenants.b, topic_key="planted", arabic_answer="x", status="active"))
        with pytest.raises(DBAPIError, match="row-level security"):
            db.commit()
    with pg.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT arabic_answer FROM faq_items WHERE id = :i"), {"i": two_tenants.faq_b}).scalar() == "B fees"


def test_without_any_scope_nothing_is_visible(pg, two_tenants):
    # A raw connection that never says which tenant it works for sees no tenant data at all.
    with pg.app_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM faq_items")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM tenants")).scalar() == 0


def test_system_scope_is_temporary(pg, two_tenants):
    from app.core.db import bind_tenant, system_scope
    from app.models.entities import FaqItem

    with pg.Session() as db:
        bind_tenant(db, two_tenants.a)
        with system_scope(db):
            assert db.query(FaqItem).filter(FaqItem.id == two_tenants.faq_b).first() is not None
        db.expunge_all()
        assert db.query(FaqItem).filter(FaqItem.id == two_tenants.faq_b).first() is None


def test_sign_up_sign_in_and_invitations_work_under_row_level_security(pg, monkeypatch):
    import main
    from app.core.config import settings
    from app.core.db import get_db
    from app.services import account_email

    sent: list = []
    monkeypatch.setattr(account_email, "get_sender", lambda: SimpleNamespace(send=sent.append))
    monkeypatch.setattr(settings, "session_cookie_secure", False)

    def override_db():
        db = pg.Session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_db
    suffix = uuid.uuid4().hex[:8]
    slug_a, slug_b = f"pg-a-{suffix}", f"pg-b-{suffix}"
    try:
        a, b = TestClient(main.app), TestClient(main.app)
        session_a = a.post("/auth/signup-business", json={"business_name": "PG A", "tenant_slug": slug_a, "admin_name": "Owner A", "admin_email": f"a-{suffix}@example.com", "admin_password": "Correct-horse-9"}).json()
        b.post("/auth/signup-business", json={"business_name": "PG B", "tenant_slug": slug_b, "admin_name": "Owner B", "admin_email": f"b-{suffix}@example.com", "admin_password": "Correct-horse-9"})

        assert a.get("/chatbot", headers={"X-Tenant-Slug": slug_a}).status_code == 200
        assert a.get("/chatbot", headers={"X-Tenant-Slug": slug_b}).status_code == 404

        login = TestClient(main.app).post("/auth/login", json={"email": f"b-{suffix}@example.com", "password": "Correct-horse-9"})
        assert login.status_code == 200 and login.json()["tenant_slug"] == slug_b

        created = a.post("/tenants/current/invites", headers={"X-CSRF-Token": session_a["csrf_token"], "X-Tenant-Slug": slug_a}, json={"email": f"staff-{suffix}@example.com", "role_code": "OPERATIONS_STAFF"})
        assert created.status_code == 200
        token = sent[-1].body.split("invite=")[1].split()[0]
        joined = TestClient(main.app).post("/auth/invites/accept", json={"token": token, "full_name": "Staff", "password": "Correct-horse-9"})
        assert joined.status_code == 200 and joined.json()["memberships"][0]["tenant_slug"] == slug_a
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        with pg.owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM tenants WHERE slug IN (:a, :b)"), {"a": slug_a, "b": slug_b})
            conn.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"%-{suffix}@example.com"})
