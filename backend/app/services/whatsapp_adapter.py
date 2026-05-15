from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class NormalizedInboundMessage:
    provider_message_id: str
    customer_phone: str
    text: str
    phone_number_id: str
    raw: dict[str, Any]


class WhatsAppAdapter:
    provider = "whatsapp"

    def normalize_inbound(self, payload: dict[str, Any]) -> NormalizedInboundMessage | None:
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            phone_number_id = value["metadata"]["phone_number_id"]
            msg = value.get("messages", [None])[0]
            if not msg:
                return None
            text = msg.get("text", {}).get("body", "")
            return NormalizedInboundMessage(
                provider_message_id=str(msg.get("id")),
                customer_phone=str(msg.get("from")),
                text=text,
                phone_number_id=str(phone_number_id),
                raw=payload,
            )
        except Exception:
            return None

    def valid_signature(self, *, raw_body: bytes, signature_header: str | None, app_secret: str | None) -> bool:
        if not app_secret or app_secret == "pending":
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def send_text(self, *, access_token: str, phone_number_id: str, to_phone: str, text: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
        url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, headers=headers, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            response.raise_for_status()
            return response.json()
