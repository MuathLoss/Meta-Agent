"""Server-side sign-in sessions behind an HttpOnly cookie (spec v1.2, Sections 10 and 13).

The browser holds a random token it cannot read from JavaScript; the database holds only its
SHA-256. A session ends after SESSION_IDLE_MINUTES without use, after SESSION_MAX_DAYS in all,
on sign-out, or when the password changes. Changing requests also need the X-CSRF-Token
header, a value derived from the session that the page receives at sign-in and from /auth/me.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import UserSession

SESSION_COOKIE = "agent_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Avoid a database write on every request; idle timing is accurate to this many minutes.
LAST_SEEN_RESOLUTION = timedelta(minutes=5)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes; PostgreSQL returns aware ones.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def csrf_token_for(token_hash: str) -> str:
    return hmac.new(settings.app_secret_key.encode(), b"csrf:" + token_hash.encode(), hashlib.sha256).hexdigest()


def create_session(db: Session, *, user_id: int, tenant_slug: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    raw, token_hash = new_token()
    now = utcnow()
    row = UserSession(
        token_hash=token_hash,
        user_id=user_id,
        tenant_slug=tenant_slug,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_max_days),
        user_agent=(user_agent or "")[:200] or None,
    )
    db.add(row)
    db.flush()
    return raw, row


def load_active_session(db: Session, raw: str | None) -> UserSession | None:
    if not raw or len(raw) > 200:
        return None
    row = db.query(UserSession).filter(UserSession.token_hash == hash_token(raw)).first()
    if row is None or row.revoked_at is not None:
        return None
    now = utcnow()
    if now >= aware(row.expires_at) or now - aware(row.last_seen_at) > timedelta(minutes=settings.session_idle_minutes):
        return None
    if now - aware(row.last_seen_at) > LAST_SEEN_RESOLUTION:
        row.last_seen_at = now
        db.commit()
    return row


def revoke_session(db: Session, row: UserSession) -> None:
    row.revoked_at = utcnow()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).update(
        {UserSession.revoked_at: utcnow()}, synchronize_session=False
    )


def set_session_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=settings.session_max_days * 86400,
        httponly=True,
        secure=settings.session_cookie_secure_effective,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=settings.session_cookie_secure_effective, samesite="lax")
