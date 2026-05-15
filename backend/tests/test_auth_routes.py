from fastapi import HTTPException

from app.api.routes_auth import delete_account, resolve_login_tenant_slug
from app.core.security import hash_password
from app.models.entities import Branch, FaqItem, Tenant, TenantBrand, TenantUserRole, User
from app.schemas.auth import DeleteAccountRequest


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


def test_delete_account_removes_tenant_and_related_data(db, tenant):
    user = User(email="owner@example.com", full_name="Owner", password_hash=hash_password("DeleteMe123!"))
    db.add(user)
    db.flush()
    db.add(TenantUserRole(tenant_id=tenant.id, user_id=user.id, role_code="BUSINESS_ADMIN"))
    db.add(TenantBrand(tenant_id=tenant.id, primary_color="#111111", support_phone="0500000000"))
    db.add(Branch(tenant_id=tenant.id, name="Temp Branch"))
    db.add(FaqItem(tenant_id=tenant.id, topic_key="temp", arabic_answer="temp", status="active"))
    db.commit()

    result = delete_account(
        payload=DeleteAccountRequest(password="DeleteMe123!"),
        user=user,
        tenant=tenant,
        db=db,
        ctx={"user": user, "tenant": tenant, "roles": ["BUSINESS_ADMIN"]},
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
        ctx={"user": user, "tenant": tenant, "roles": ["BUSINESS_ADMIN"]},
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
            ctx={"user": user, "tenant": tenant, "roles": ["BUSINESS_ADMIN"]},
        )
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Incorrect password"
    else:
        raise AssertionError("Expected HTTPException for incorrect password")
