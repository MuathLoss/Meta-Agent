from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class TelegramInboundMessage:
    provider_message_id: str
    customer_address: str
    text: str
    chat_id: str
    raw: dict[str, Any]


class TelegramAdapter:
    provider = "telegram"

    def normalize_inbound(self, payload: dict[str, Any]) -> TelegramInboundMessage | None:
        message = payload.get("message") or payload.get("edited_message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        update_id = payload.get("update_id")
        if not text or chat_id is None or update_id is None:
            return None
        return TelegramInboundMessage(
            provider_message_id=f"telegram-update-{update_id}",
            customer_address=str(chat_id),
            text=str(text),
            chat_id=str(chat_id),
            raw=payload,
        )

    def valid_secret_token(self, secret_token: str | None, expected_secret_token: str | None) -> bool:
        if not expected_secret_token or expected_secret_token == "pending":
            return True
        return bool(secret_token) and secret_token == expected_secret_token

    def expected_verification_token(self, credentials: dict[str, Any]) -> str | None:
        secret_token = credentials.get("secret_token")
        if secret_token and secret_token != "pending":
            return str(secret_token)
        bot_token = credentials.get("bot_token")
        if bot_token and bot_token != "pending":
            return str(bot_token)
        return None

    def send_text(self, *, bot_token: str, chat_id: str, text: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            return response.json()

    def get_updates(self, *, bot_token: str, offset: int | None = None, timeout_seconds: int = 20) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        payload: dict[str, Any] = {"timeout": timeout_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        with httpx.Client(timeout=timeout_seconds + 5) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    def delete_webhook(self, *, bot_token: str, drop_pending_updates: bool = False, timeout_seconds: float = 10.0) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, json={"drop_pending_updates": drop_pending_updates})
            response.raise_for_status()
            return response.json()
