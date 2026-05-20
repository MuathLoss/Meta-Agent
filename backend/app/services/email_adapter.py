from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any
from uuid import uuid4


@dataclass
class EmailSendResult:
    message_id: str
    provider_response: dict[str, Any]


class EmailAdapter:
    provider = "email"

    def _bool_value(self, value: object, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _port_value(self, value: object) -> int | None:
        try:
            port = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return port if 0 < port < 65536 else None

    def smtp_ready(self, credentials: dict[str, Any]) -> tuple[bool, str | None]:
        required = ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from_email"]
        for key in required:
            value = credentials.get(key)
            if value is None or not str(value).strip() or str(value).strip().lower() == "pending":
                return False, f"missing_{key}"
        if self._port_value(credentials.get("smtp_port")) is None:
            return False, "invalid_smtp_port"
        return True, None

    def imap_ready(self, credentials: dict[str, Any]) -> tuple[bool, str | None]:
        required = ["imap_host", "imap_port", "imap_username", "imap_password"]
        for key in required:
            value = credentials.get(key)
            if value is None or not str(value).strip() or str(value).strip().lower() == "pending":
                return False, f"missing_{key}"
        if self._port_value(credentials.get("imap_port")) is None:
            return False, "invalid_imap_port"
        return True, None

    def send_text(self, *, credentials: dict[str, Any], to_email: str, subject: str, text: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
        ready, reason = self.smtp_ready(credentials)
        if not ready:
            raise ValueError(reason or "missing_email_credentials")
        destination = to_email.strip()
        if not destination:
            raise ValueError("missing_email_recipient")

        host = str(credentials["smtp_host"]).strip()
        port = self._port_value(credentials["smtp_port"])
        username = str(credentials["smtp_username"]).strip()
        password = str(credentials["smtp_password"])
        from_email = str(credentials["smtp_from_email"]).strip()
        from_name = str(credentials.get("smtp_from_name") or "").strip()
        use_ssl = self._bool_value(credentials.get("use_ssl"), default=False)
        use_tls = self._bool_value(credentials.get("use_tls"), default=not use_ssl)

        msg = EmailMessage()
        msg["Subject"] = subject.strip() or "Message from support"
        msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        msg["To"] = destination
        msg.set_content(text)

        if use_ssl:
            client_context = smtplib.SMTP_SSL(host, port, timeout=timeout_seconds)
        else:
            client_context = smtplib.SMTP(host, port, timeout=timeout_seconds)

        with client_context as smtp:
            if use_tls and not use_ssl:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)

        return {
            "message_id": f"email-local-{uuid4()}",
            "delivery": "smtp",
        }
