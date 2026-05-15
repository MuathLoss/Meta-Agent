from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_EXACT_KEYS = {
    "access_token",
    "api_key",
    "app_secret",
    "authorization",
    "bot_token",
    "database_url",
    "key",
    "password",
    "phone_number_id",
    "refresh_token",
    "secret",
    "signature",
    "token",
    "verify_token",
    "waba_id",
    "webhook_url",
    "x-hub-signature-256",
}
SENSITIVE_KEY_PARTS = ("token", "secret", "password", "signature", "authorization")
SENSITIVE_QUERY_RE = re.compile(r"(?i)(access_token|refresh_token|token|api_key|key|signature|authorization|password|secret)=([^&\s]+)")
BEARER_RE = re.compile(r"(?i)bearer\s+([^\s,;]+)")
TELEGRAM_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
DATABASE_URL_RE = re.compile(r"(?i)\b(?:postgresql|postgres|mysql|mariadb|mongodb|redis)://[^\s]+")


def is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("_", "-")
    underscore = normalized.replace("-", "_")
    return underscore in SENSITIVE_EXACT_KEYS or any(part in underscore for part in SENSITIVE_KEY_PARTS)


def redact_string(value: str) -> str:
    redacted = DATABASE_URL_RE.sub(REDACTED, value)
    redacted = TELEGRAM_BOT_TOKEN_RE.sub("bot" + REDACTED, redacted)
    redacted = BEARER_RE.sub("Bearer " + REDACTED, redacted)
    redacted = SENSITIVE_QUERY_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)
    return redacted


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value
