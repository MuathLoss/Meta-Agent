from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class MetaSocialInboundMessage:
    sender_id: str
    text: str
    display_name: str | None
    raw: dict[str, Any]


class MetaSocialAdapter:
    supported_channels = {"instagram", "facebook"}

    def _configured(self, value: object) -> bool:
        if value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        return text.lower() not in {"pending", "placeholder", "changeme", "replace-with", "replace_me"}

    def _safe_sender_id(self, value: object) -> str:
        text = str(value or "").strip()
        text = re.sub(r"[^A-Za-z0-9_.:-]", "", text)
        return text[:48]

    def graph_api_version(self, credentials: dict[str, Any]) -> str:
        raw = str(credentials.get("graph_api_version") or "v20.0").strip()
        if re.fullmatch(r"v\d+\.\d+", raw):
            return raw
        if re.fullmatch(r"\d+\.\d+", raw):
            return f"v{raw}"
        return "v20.0"

    def credentials_ready(self, channel_type: str, credentials: dict[str, Any]) -> tuple[bool, str | None]:
        if channel_type not in self.supported_channels:
            return False, "unsupported_channel"
        if not self._configured(credentials.get("page_access_token")):
            return False, "missing_page_access_token"
        if channel_type == "facebook" and not self._configured(credentials.get("page_id")):
            return False, "missing_page_id"
        if channel_type == "instagram" and not self._configured(credentials.get("instagram_business_account_id")):
            return False, "missing_instagram_business_account_id"
        return True, None

    def valid_signature(self, *, raw_body: bytes, signature_header: str | None, app_secret: object) -> bool:
        if not self._configured(app_secret) or not signature_header:
            return False
        header = signature_header.strip()
        if not header.startswith("sha256="):
            return False
        digest = hmac.new(str(app_secret).encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(header, f"sha256={digest}")

    def normalize_inbound_test(self, *, channel_type: str, payload: dict[str, Any]) -> MetaSocialInboundMessage | None:
        if channel_type not in self.supported_channels:
            return None
        sender_id = self._safe_sender_id(payload.get("sender_id"))
        text = str(payload.get("message") or "").strip()
        if not sender_id or not text:
            return None
        display_name = str(payload.get("display_name") or "").strip() or None
        return MetaSocialInboundMessage(
            sender_id=sender_id,
            text=text,
            display_name=display_name,
            raw={
                "source": f"{channel_type}_inbound_test",
                "sender_id": sender_id,
                "display_name_provided": bool(display_name),
            },
        )

    def send_text(
        self,
        *,
        channel_type: str,
        credentials: dict[str, Any],
        recipient_id: str,
        text: str,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        ready, reason = self.credentials_ready(channel_type, credentials)
        if not ready:
            raise ValueError(reason or "missing_meta_social_credentials")
        destination = str(recipient_id or "").strip()
        if not destination:
            raise ValueError("missing_provider_recipient")

        version = self.graph_api_version(credentials)
        token = str(credentials["page_access_token"]).strip()
        if channel_type == "instagram":
            account_id = str(credentials["instagram_business_account_id"]).strip()
            url = f"https://graph.facebook.com/{version}/{account_id}/messages"
            payload = {"recipient": {"id": destination}, "message": {"text": text}}
        else:
            url = f"https://graph.facebook.com/{version}/me/messages"
            payload = {"recipient": {"id": destination}, "message": {"text": text}}

        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, dict) else {"delivery": "meta_graph"}
