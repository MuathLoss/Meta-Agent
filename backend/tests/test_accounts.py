"""Spec v1.2, Phase 1: sign-in sessions, CSRF, email links, password reset, invitations,
roles and workspace isolation in the application code. Runs the real API with an in-memory
database; tests/test_row_level_security.py repeats the isolation checks on PostgreSQL."""
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from app.core.config import settings
from app.core.db import get_db
from app.core.sessions import SESSION_COOKIE, utcnow
from app.models.entities import Base, Chatbot, TenantInvite, TenantUserRole, User, UserSession
from app.services import account_email

PASSWORD = "Correct-horse-9"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    sent: list = []
    monkeypatch.setattr(account_email, "get_sender", lambda: SimpleNamespace(send=sent.append))
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    main.app.dependency_overrides[get_db] = override_db
    yield SimpleNamespace(Session=Session, sent=sent)
    main.app.dependency_overrides.pop(get_db, None)


def client() -> TestClient:
    return TestClient(main.app)


def signup(c: TestClient, slug: str, email: str) -> dict:
    response = c.post("/auth/signup-business", json={
        "business_name": f"School {slug}", "tenant_slug": slug, "admin_name": "Owner Person",
        "admin_email": email, "admin_password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response.json()


def headers(session: dict, slug: str | None = None) -> dict:
    h = {"X-CSRF-Token": session["csrf_token"]}
    if slug:
        h["X-Tenant-Slug"] = slug
    return h


def link_token(env, key: str) -> str:
    return re.search(rf"[?&]{key}=([A-Za-z0-9_-]+)", env.sent[-1].body).group(1)


# --- sessions ------------------------------------------------------------------------------

def test_signup_gives_an_httponly_cookie_owner_role_and_one_chatbot(env):
    c = client()
    response = c.post("/auth/signup-business", json={
        "business_name": "School A", "tenant_slug": "school-a", "admin_name": "Owner A",
        "admin_email": "owner-a@example.com", "admin_password": PASSWORD,
    })
    body = response.json()
    cookie = response.headers["set-cookie"].lower()

    assert response.status_code == 200
    assert "access_token" not in body and body["csrf_token"]
    assert cookie.startswith(SESSION_COOKIE) and "httponly" in cookie and "samesite=lax" in cookie
    assert set(body["memberships"][0]["roles"]) == {"OWNER", "BUSINESS_ADMIN"}
    assert body["user"]["email_verified"] is False
    with env.Session() as db:
        assert db.query(Chatbot).count() == 1
    assert env.sent and env.sent[-1].subject == "Confirm your email address"


def test_requests_without_a_session_are_refused(env):
    assert client().get("/auth/me").status_code == 401
    assert client().get("/chatbot", headers={"X-Tenant-Slug": "anything"}).status_code == 401


def test_changing_requests_need_the_csrf_token(env):
    c = client()
    session = signup(c, "school-a", "owner-a@example.com")
    assert c.get("/auth/me").status_code == 200  # reading needs no token
    assert c.post("/auth/verify-email/resend").status_code == 403
    assert c.post("/auth/verify-email/resend", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert c.post("/auth/verify-email/resend", headers=headers(session)).status_code == 200


def test_sign_out_ends_the_session_even_if_the_cookie_is_replayed(env):
    c = client()
    session = signup(c, "school-a", "owner-a@example.com")
    stolen = c.cookies.get(SESSION_COOKIE)
    assert c.post("/auth/logout", headers=headers(session)).status_code == 200
    assert c.get("/auth/me").status_code == 401
    replay = client()
    replay.cookies.set(SESSION_COOKIE, stolen)
    assert replay.get("/auth/me").status_code == 401


@pytest.mark.parametrize("field,age", [("last_seen_at", timedelta(minutes=481)), ("expires_at", timedelta(seconds=-1))])
def test_idle_and_old_sessions_expire(env, field, age):
    c = client()
    signup(c, "school-a", "owner-a@example.com")
    with env.Session() as db:
        row = db.query(UserSession).one()
        setattr(row, field, utcnow() - age if field == "last_seen_at" else utcnow() + age)
        db.commit()
    assert c.get("/auth/me").status_code == 401


def test_each_sign_in_starts_a_new_session(env):
    c = client()
    signup(c, "school-a", "owner-a@example.com")
    first = c.cookies.get(SESSION_COOKIE)
    c.post("/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
    assert c.cookies.get(SESSION_COOKIE) != first


# --- passwords -----------------------------------------------------------------------------

def test_new_passwords_use_argon2id_and_old_bcrypt_hashes_are_upgraded(env):
    with env.Session() as db:
        db.add(User(email="legacy@example.com", full_name="Legacy", password_hash=CryptContext(schemes=["bcrypt"]).hash(PASSWORD)))
        db.commit()
    c = client()
    assert c.post("/auth/login", json={"email": "legacy@example.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/auth/login", json={"email": "legacy@example.com", "password": PASSWORD}).status_code == 200
    signup(client(), "school-a", "owner-a@example.com")
    with env.Session() as db:
        assert db.query(User).filter_by(email="legacy@example.com").one().password_hash.startswith("$argon2id$")
        assert db.query(User).filter_by(email="owner-a@example.com").one().password_hash.startswith("$argon2id$")


def test_email_verification_link_works_once(env):
    c = client()
    signup(c, "school-a", "owner-a@example.com")
    token = link_token(env, "verify_email")
    assert client().post("/auth/verify-email", json={"token": token}).status_code == 200
    assert c.get("/auth/me").json()["email_verified"] is True
    assert client().post("/auth/verify-email", json={"token": token}).status_code == 400


def test_password_reset_does_not_reveal_accounts_and_signs_everyone_out(env):
    c = client()
    signup(c, "school-a", "owner-a@example.com")
    before = len(env.sent)
    unknown = client().post("/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert unknown.status_code == 200 and len(env.sent) == before
    known = client().post("/auth/password-reset/request", json={"email": "owner-a@example.com"})
    assert known.json() == unknown.json() and len(env.sent) == before + 1

    token = link_token(env, "reset_password")
    assert client().post("/auth/password-reset/confirm", json={"token": token, "new_password": "New-password-42"}).status_code == 200
    assert c.get("/auth/me").status_code == 401  # the old session ended
    assert client().post("/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD}).status_code == 401
    assert client().post("/auth/login", json={"email": "owner-a@example.com", "password": "New-password-42"}).status_code == 200
    assert client().post("/auth/password-reset/confirm", json={"token": token, "new_password": "Another-pass-43"}).status_code == 400


# --- workspace isolation (application code) ------------------------------------------------

def test_a_user_cannot_open_another_workspace(env):
    a, b = client(), client()
    session_a = signup(a, "school-a", "owner-a@example.com")
    signup(b, "school-b", "owner-b@example.com")
    own = a.get("/chatbot", headers={"X-Tenant-Slug": "school-a"})
    other = a.get("/chatbot", headers={"X-Tenant-Slug": "school-b"})
    assert own.status_code == 200
    assert other.status_code == 404 and other.json()["detail"] == "Tenant not found"
    assert a.post("/tenants/current/invites", headers=headers(session_a, "school-b"), json={"email": "x@example.com", "role_code": "OPERATIONS_STAFF"}).status_code == 404


def test_guessed_ids_from_another_workspace_are_not_found(env):
    a, b = client(), client()
    session_a = signup(a, "school-a", "owner-a@example.com")
    session_b = signup(b, "school-b", "owner-b@example.com")
    invite = a.post("/tenants/current/invites", headers=headers(session_a, "school-a"), json={"email": "staff@example.com", "role_code": "OPERATIONS_STAFF"}).json()
    response = b.delete(f"/tenants/current/invites/{invite['id']}", headers=headers(session_b, "school-b"))
    assert response.status_code == 404
    assert [row["status"] for row in a.get("/tenants/current/invites", headers={"X-Tenant-Slug": "school-a"}).json()] == ["pending"]


def test_only_one_chatbot_per_workspace(env):
    signup(client(), "school-a", "owner-a@example.com")
    with env.Session() as db:
        bot = db.query(Chatbot).one()
        db.add(Chatbot(tenant_id=bot.tenant_id, display_name="Second", public_widget_id="wb_second"))
        with pytest.raises(IntegrityError):
            db.commit()


# --- invitations and roles -----------------------------------------------------------------

def invite(c, session, email, role, slug="school-a"):
    return c.post("/tenants/current/invites", headers=headers(session, slug), json={"email": email, "role_code": role})


def test_invited_person_creates_an_account_and_joins_with_that_role(env):
    owner = client()
    session = signup(owner, "school-a", "owner-a@example.com")
    assert invite(owner, session, "Staff@Example.com", "OPERATIONS_STAFF").status_code == 200
    token = link_token(env, "invite")

    newcomer = client()
    missing_name = newcomer.post("/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert missing_name.status_code == 422
    joined = newcomer.post("/auth/invites/accept", json={"token": token, "full_name": "Staff Member", "password": PASSWORD})
    assert joined.status_code == 200
    assert joined.json()["memberships"][0]["roles"] == ["OPERATIONS_STAFF"]
    assert joined.json()["user"]["email_verified"] is True
    assert newcomer.get("/chatbot", headers={"X-Tenant-Slug": "school-a"}).status_code == 200
    # Used once only.
    assert client().post("/auth/invites/accept", json={"token": token, "full_name": "Again", "password": PASSWORD}).status_code == 400


def test_existing_account_joins_only_with_its_own_password(env):
    owner = client()
    session = signup(owner, "school-a", "owner-a@example.com")
    signup(client(), "school-b", "owner-b@example.com")
    invite(owner, session, "owner-b@example.com", "SUPERVISOR")
    token = link_token(env, "invite")
    assert client().post("/auth/invites/accept", json={"token": token, "password": "Wrong-password-1"}).status_code == 401
    accepted = client().post("/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert accepted.status_code == 200
    assert {m["tenant_slug"] for m in accepted.json()["memberships"]} == {"school-a", "school-b"}


def test_role_rules_for_invitations(env):
    owner = client()
    session = signup(owner, "school-a", "owner-a@example.com")
    assert invite(owner, session, "boss@example.com", "OWNER").status_code == 403
    assert invite(owner, session, "admin@example.com", "BUSINESS_ADMIN").status_code == 200

    admin = client()
    admin_session = admin.post("/auth/invites/accept", json={"token": link_token(env, "invite"), "full_name": "Admin", "password": PASSWORD}).json()
    assert invite(admin, admin_session, "staff@example.com", "FINANCE").status_code == 200
    assert invite(admin, admin_session, "admin2@example.com", "BUSINESS_ADMIN").status_code == 403

    staff = client()
    staff_session = staff.post("/auth/invites/accept", json={"token": link_token(env, "invite"), "full_name": "Staff", "password": PASSWORD}).json()
    assert invite(staff, staff_session, "anyone@example.com", "FINANCE").status_code == 403


def test_revoked_and_expired_invitations_cannot_be_used(env):
    owner = client()
    session = signup(owner, "school-a", "owner-a@example.com")
    first = invite(owner, session, "one@example.com", "FINANCE").json()
    revoked_token = link_token(env, "invite")
    assert owner.delete(f"/tenants/current/invites/{first['id']}", headers=headers(session, "school-a")).json()["status"] == "revoked"
    assert client().post("/auth/invites/accept", json={"token": revoked_token, "full_name": "One", "password": PASSWORD}).status_code == 400

    invite(owner, session, "two@example.com", "FINANCE")
    expired_token = link_token(env, "invite")
    with env.Session() as db:
        row = db.query(TenantInvite).filter_by(email="two@example.com").one()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client().post("/auth/invites/accept", json={"token": expired_token, "full_name": "Two", "password": PASSWORD}).status_code == 400
    with env.Session() as db:
        assert db.query(TenantUserRole).join(User, User.id == TenantUserRole.user_id).filter(User.email.in_(["one@example.com", "two@example.com"])).count() == 0
