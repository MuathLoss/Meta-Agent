"""Password hashing (spec v1.2, Section 13): Argon2id for every new hash.

Older bcrypt hashes still verify, and are replaced with Argon2id at the next successful
sign-in (verify_and_upgrade). Parameters follow OWASP's Argon2id minimum (19 MiB, 2 passes,
1 lane), which keeps a burst of sign-ins inside the API's 512 MB memory limit.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from passlib.context import CryptContext

_argon2 = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_legacy = CryptContext(schemes=["bcrypt"])


def hash_password(password: str) -> str:
    return _argon2.hash(password)


_dummy_hash: str | None = None


def _argon2_dummy_check(password: str) -> None:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _argon2.hash("timing-equaliser")
    try:
        _argon2.verify(_dummy_hash, password)
    except VerificationError:
        pass


def _is_legacy(hashed: str) -> bool:
    return hashed.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(password: str, hashed: str | None) -> bool:
    return verify_and_upgrade(password, hashed)[0]


def verify_and_upgrade(password: str, hashed: str | None) -> tuple[bool, str | None]:
    """Return (matches, new_hash). new_hash is set when the stored hash should be replaced."""
    if not hashed:
        # Spend the same time as a real check, so response time does not reveal unknown emails.
        _argon2_dummy_check(password)
        return False, None
    if _is_legacy(hashed):
        try:
            ok = _legacy.verify(password, hashed)
        except ValueError:
            return False, None
        return ok, (hash_password(password) if ok else None)
    try:
        _argon2.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, None
    return True, (hash_password(password) if _argon2.check_needs_rehash(hashed) else None)
