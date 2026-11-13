from __future__ import annotations

from app.core.config import settings
from app.services.storage.base import ObjectStorage


def get_storage() -> ObjectStorage:
    if settings.storage_backend == "local":
        from app.services.storage.local_disk import LocalDiskStorage

        return LocalDiskStorage(settings.storage_local_root)
    raise RuntimeError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend}")
