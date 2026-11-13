from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

MAX_KEY_LENGTH = 512
MAX_FILE_NAME_LENGTH = 120
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class InvalidObjectKey(ValueError):
    """The key could point outside storage or outside its tenant."""


class ObjectNotFound(LookupError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes) -> StoredObject: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> bool: ...
    def exists(self, key: str) -> bool: ...


def validate_key(key: str) -> str:
    if not key or len(key) > MAX_KEY_LENGTH or key.startswith("/") or key.endswith("/") or "\\" in key:
        raise InvalidObjectKey("invalid storage key")
    for segment in key.split("/"):
        if segment in {"", ".", ".."} or not _SEGMENT_RE.match(segment):
            raise InvalidObjectKey("invalid storage key")
    return key


def safe_file_name(name: str) -> str:
    """A storage-safe version of an uploaded file name. Keep the original name in the database."""
    base = unicodedata.normalize("NFKC", name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, extension = base.rpartition(".")
    if not dot:
        stem, extension = base, ""
    clean_stem = _UNSAFE_NAME_CHARS.sub("_", stem).strip("._-")
    clean_extension = _UNSAFE_NAME_CHARS.sub("", extension).lower()[:10]
    if not any(ch.isalnum() for ch in clean_stem):
        clean_stem = "file"
    room = MAX_FILE_NAME_LENGTH - (len(clean_extension) + 1 if clean_extension else 0)
    clean_stem = clean_stem[:room]
    return f"{clean_stem}.{clean_extension}" if clean_extension else clean_stem


def tenant_prefix(tenant_id: int) -> str:
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise InvalidObjectKey("invalid tenant id")
    return f"tenant/{tenant_id}/"


def tenant_document_key(tenant_id: int, document_id: str, file_name: str) -> str:
    # Spec v1.2, Section 7.3: tenant/{tenant_id}/documents/{document_id}/{safe_name}
    return validate_key(f"{tenant_prefix(tenant_id)}documents/{document_id}/{safe_file_name(file_name)}")


def ensure_tenant_key(tenant_id: int, key: str) -> str:
    """Refuse a key that belongs to another tenant (or to no tenant)."""
    validate_key(key)
    if not key.startswith(tenant_prefix(tenant_id)):
        raise InvalidObjectKey("storage key belongs to another tenant")
    return key
