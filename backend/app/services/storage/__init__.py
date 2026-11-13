"""Private file storage behind one interface (spec v1.2, T06).

The pilot uses LocalDiskStorage on a backed-up Docker volume. A Garage (S3-compatible)
adapter can be added later with the same methods, without changing callers.

Files are never served straight from storage: the API checks that the signed-in user's
tenant owns a key (ensure_tenant_key) before reading it.
"""
from app.services.storage.base import (
    InvalidObjectKey,
    ObjectNotFound,
    ObjectStorage,
    StoredObject,
    ensure_tenant_key,
    safe_file_name,
    tenant_document_key,
    tenant_prefix,
    validate_key,
)
from app.services.storage.factory import get_storage
from app.services.storage.local_disk import LocalDiskStorage

__all__ = [
    "InvalidObjectKey",
    "LocalDiskStorage",
    "ObjectNotFound",
    "ObjectStorage",
    "StoredObject",
    "ensure_tenant_key",
    "get_storage",
    "safe_file_name",
    "tenant_document_key",
    "tenant_prefix",
    "validate_key",
]
