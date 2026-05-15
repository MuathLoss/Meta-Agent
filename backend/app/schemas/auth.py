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

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    memberships: list[dict]
