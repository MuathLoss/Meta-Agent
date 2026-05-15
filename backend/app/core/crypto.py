import json
from cryptography.fernet import Fernet
from app.core.config import settings

def _fernet() -> Fernet:
    return Fernet(settings.tenant_channel_secret_key.encode())

def encrypt_dict(value: dict) -> str:
    return _fernet().encrypt(json.dumps(value or {}, ensure_ascii=False).encode()).decode()

def decrypt_dict(token: str | None) -> dict:
    if not token:
        return {}
    return json.loads(_fernet().decrypt(token.encode()).decode())
