from __future__ import annotations

import re
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any


VISITOR_ID_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")


@dataclass
class WebChatInboundMessage:
    visitor_id: str
    text: str
    display_name: str | None
    raw: dict[str, Any]


class WebChatAdapter:
    provider = "web_chat"
    VISITOR_PREFIX = "wc_"
    MAX_VISITOR_ID_LENGTH = 48

    def normalize_visitor_id(self, visitor_id: str | None) -> str:
        raw = str(visitor_id or "").strip()
        if not raw:
            return f"{self.VISITOR_PREFIX}{token_urlsafe(16)}"
        normalized = VISITOR_ID_RE.sub("-", raw).strip("-._:")
        if not normalized:
            return f"{self.VISITOR_PREFIX}{token_urlsafe(16)}"
        return normalized[: self.MAX_VISITOR_ID_LENGTH]

    def normalize_inbound(self, payload: dict[str, Any]) -> WebChatInboundMessage | None:
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return None
        display_name = payload.get("display_name")
        visitor_id = self.normalize_visitor_id(payload.get("visitor_id"))
        return WebChatInboundMessage(
            visitor_id=visitor_id,
            text=message.strip(),
            display_name=display_name.strip()[:120] if isinstance(display_name, str) and display_name.strip() else None,
            raw={
                "source": "web_chat",
                "visitor_id": visitor_id,
                "display_name_provided": isinstance(display_name, str) and bool(display_name.strip()),
            },
        )
