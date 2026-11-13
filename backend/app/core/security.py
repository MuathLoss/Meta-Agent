import hmac
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.passwords import hash_password, verify_and_upgrade, verify_password  # noqa: F401 (re-exported)
from app.core.sessions import CSRF_HEADER, SAFE_METHODS, SESSION_COOKIE, csrf_token_for, load_active_session


def get_token_payload(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Resolve the signed-in user from the session cookie, and enforce CSRF on changes.

    Returns the same keys the old bearer token carried (sub, tenant_slug), plus the session.
    """
    session_row = load_active_session(db, request.cookies.get(SESSION_COOKIE))
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again")
    if request.method.upper() not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), csrf_token_for(session_row.token_hash).encode()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing or invalid CSRF token")
    return {"sub": str(session_row.user_id), "tenant_slug": session_row.tenant_slug, "session": session_row}
