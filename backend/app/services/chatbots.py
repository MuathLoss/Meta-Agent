"""The one chatbot each institution gets (spec v1.2, P03 and journey step 4)."""
from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.models.entities import Chatbot, Tenant


def ensure_chatbot(db: Session, tenant: Tenant) -> Chatbot:
    """Return the tenant's chatbot, creating it the first time. The database refuses a second one."""
    existing = db.query(Chatbot).filter(Chatbot.tenant_id == tenant.id).first()
    if existing:
        return existing
    bot = Chatbot(
        tenant_id=tenant.id,
        display_name=tenant.display_name,
        status="draft",
        public_widget_id="wb_" + secrets.token_urlsafe(16),
        language_mode="auto",
    )
    db.add(bot)
    db.flush()
    return bot
