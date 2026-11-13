from types import SimpleNamespace

from fastapi import HTTPException, Response

from app.api.routes_auth import delete_account, login, me, resolve_login_tenant_slug
from app.core.security import get_token_payload, hash_password
from app.core.sessions import SESSION_COOKIE
from app.core.tenancy import get_current_user
from app.models.entities import Branch, FaqItem, Tenant, TenantBrand, TenantUserRole, User, UserSession
from app.schemas.auth import DeleteAccountRequest, LoginRequest


class FakeRequest:
    client = SimpleNamespace(host="127.0.0.1")


def test_resolve_login_tenant_slug_defaults_to_first_membership():
    memberships = [
        {"tenant_slug": "tenant-a"},
        {"tenant_slug": "tenant-b"},
    ]

    assert resolve_login_tenant_slug(None, memberships) == "tenant-a"


def test_resolve_login_tenant_slug_accepts_membership_match():
    memberships = [
        {"tenant_slug": "tenant-a"},
        {"tenant_slug": "tenant-b"},
    ]

    assert resolve_login_tenant_slug("tenant-b", memberships) == "tenant-b"


def test_resolve_login_tenant_slug_rejects_unknown_slug():
    memberships = [{"tenant_slug": "tenant-a"}]

    try:
        resolve_login_tenant_slug("missing-tenant", memberships)
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Tenant not found"
    else:
        raise AssertionError("Expected HTTPException for unknown tenant slug")


def test_login_sets_an_httponly_session_cookie_and_returns_no_token(db, tenant):
    user = User(email="login-token@example.com", full_name="Login Token", password_hash=hash_password("Secret123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()

    http_response = Response()
    result = login(
        LoginRequest(email="login-token@example.com", password="Secret123!", tenant_slug=tenant.slug),
        request=FakeRequest(),
        response=http_response,
        db=db,
    )
    data = result.model_dump()
    cookie = http_response.headers["set-cookie"]

    assert "access_token" not in data and "refresh_token" not in data
    assert data["csrf_token"] and data["tenant_slug"] == tenant.slug
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert db.query(UserSession).filter(UserSession.user_id == user.id).count() == 1


def test_auth_me_works_with_the_session_cookie(db, tenant):
    user = User(email="me-token@example.com", full_name="Me Token", password_hash=hash_password("Secret123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()

    http_response = Response()
    login(
        LoginRequest(email="me-token@example.com", password="Secret123!", tenant_slug=tenant.slug),
        request=FakeRequest(),
        response=http_response,
        db=db,
    )
    raw = http_response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    payload = get_token_payload(SimpleNamespace(cookies={SESSION_COOKIE: raw}, method="GET", headers={}), db=db)
    resolved_user = get_current_user(payload=payload, db=db)
    result = me(user=resolved_user, payload=payload, db=db)

    assert result["email"] == "me-token@example.com"
    assert result["memberships"][0]["tenant_slug"] == tenant.slug
    assert result["csrf_token"]


def test_delete_account_removes_tenant_and_related_data(db, tenant):
    user = User(email="owner@example.com", full_name="Owner", password_hash=hash_password("DeleteMe123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="OWNER"))
    db.add(TenantBrand(tenant_id=tenant.id, primary_color="#111111", support_phone="0500000000"))
    db.add(Branch(tenant_id=tenant.id, name="Temp Branch"))
    db.add(FaqItem(tenant_id=tenant.id, topic_key="temp", arabic_answer="temp", status="active"))
    db.commit()

    result = delete_account(
        payload=DeleteAccountRequest(password="DeleteMe123!"),
        user=user,
        tenant=tenant,
        db=db,
        ctx={"user": user, "tenant": tenant, "roles": ["OWNER", "BUSINESS_ADMIN"]},
    )

    assert result["status"] == "deleted"
    assert result["deleted_tenant"]["slug"] == tenant.slug
    assert result["deleted_user"] is True
    assert db.query(Tenant).filter(Tenant.id == tenant.id).count() == 0
    assert db.query(Branch).filter(Branch.tenant_id == tenant.id).count() == 0
    assert db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id).count() == 0
    assert db.query(User).filter(User.id == user.id).count() == 0


def test_delete_account_keeps_user_if_other_memberships_exist(db, tenant):
    user = User(email="multi@example.com", full_name="Multi", password_hash=hash_password("DeleteMe123!"))
    db.add(user)
    db.flush()
    other_tenant = Tenant(slug="other-tenant-delete", display_name="Other Tenant", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other_tenant)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.add(TenantUserRole(tenant_id=other_tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()

    result = delete_account(
        payload=DeleteAccountRequest(password="DeleteMe123!"),
        user=user,
        tenant=tenant,
        db=db,
        ctx={"user": user, "tenant": tenant, "roles": ["OWNER", "BUSINESS_ADMIN"]},
    )

    assert result["status"] == "deleted"
    assert result["deleted_user"] is False
    assert db.query(Tenant).filter(Tenant.id == tenant.id).count() == 0
    assert db.query(User).filter(User.id == user.id).count() == 1
    assert db.query(TenantUserRole).filter(TenantUserRole.tenant_id == other_tenant.id, TenantUserRole.user_id == user.id).count() == 1


def test_delete_account_rejects_incorrect_password(db, tenant):
    user = User(email="owner2@example.com", full_name="Owner Two", password_hash=hash_password("DeleteMe123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()

    try:
        delete_account(
            payload=DeleteAccountRequest(password="wrong-password"),
            user=user,
            tenant=tenant,
            db=db,
            ctx={"user": user, "tenant": tenant, "roles": ["OWNER", "BUSINESS_ADMIN"]},
        )
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Incorrect password"
    else:
        raise AssertionError("Expected HTTPException for incorrect password")


def test_delete_account_needs_the_owner_role(db, tenant):
    user = User(email="admin-only@example.com", full_name="Admin Only", password_hash=hash_password("DeleteMe123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.commit()

    try:
        delete_account(
            payload=DeleteAccountRequest(password="DeleteMe123!"),
            user=user,
            tenant=tenant,
            db=db,
            ctx={"user": user, "tenant": tenant, "roles": ["BUSINESS_ADMIN"]},
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("An admin who is not the owner must not delete the workspace")
    assert db.query(Tenant).filter(Tenant.id == tenant.id).count() == 1
