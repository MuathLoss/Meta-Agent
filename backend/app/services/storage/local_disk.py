from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from app.services.storage.base import InvalidObjectKey, ObjectNotFound, StoredObject, validate_key


class LocalDiskStorage:
    """Files on a local directory (a Docker volume in compose). Single-node pilot only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        # resolve() follows symlinks, so this also stops a planted link from leading outside.
        if not path.is_relative_to(self.root) or path == self.root:
            raise InvalidObjectKey("invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            # Readers see either the old file or the whole new one, never half a file.
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        self._remove_empty_parents(path.parent)
        return True

    def _remove_empty_parents(self, folder: Path) -> None:
        while folder != self.root and folder.is_relative_to(self.root):
            try:
                folder.rmdir()
            except OSError:
                return
            folder = folder.parent
