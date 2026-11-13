from pydantic import BaseModel, EmailStr, Field

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = None

class SignupBusinessRequest(BaseModel):
    business_name: str = Field(min_length=2)
    tenant_slug: str = Field(min_length=2, pattern=r"^[a-z0-9-]+$")
    admin_name: str = Field(min_length=2)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    timezone: str = "Asia/Riyadh"
    default_lang: str = "ar"
    support_email: EmailStr | None = None
    support_phone: str | None = None


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1)


class SessionResponse(BaseModel):
    """Sign-in result. The session itself is in an HttpOnly cookie; nothing here is a credential."""
    user: dict
    memberships: list[dict]
    tenant_slug: str | None = None
    # Send back in the X-CSRF-Token header on every changing request.
    csrf_token: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class InviteCreate(BaseModel):
    email: EmailStr
    role_code: str


class InviteAccept(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    # New people choose a name and password. People who already have an account confirm
    # with their existing password instead.
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=200)
