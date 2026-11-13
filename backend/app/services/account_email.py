"""Emails about accounts: verification, password reset and team invitations (spec v1.2, Section 13).

ACCOUNT_EMAIL_PROVIDER=log writes the message to the API log (development and local staging,
where there is no mail server); smtp sends it. Production refuses "log" (config check).
Sending never blocks sign-up: a failure is logged and the person can ask for the email again.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountEmail:
    to: str
    subject: str
    body: str


class AccountEmailSender(Protocol):
    def send(self, message: AccountEmail) -> None: ...


class LogEmailSender:
    def send(self, message: AccountEmail) -> None:
        logger.warning("account email (log provider, not sent) to=%s subject=%s\n%s", message.to, message.subject, message.body)


class SmtpEmailSender:
    def send(self, message: AccountEmail) -> None:
        mime = MimeMessage()
        mime["From"] = settings.smtp_from or ""
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(mime)


def get_sender() -> AccountEmailSender:
    return SmtpEmailSender() if settings.account_email_provider == "smtp" else LogEmailSender()


def send_account_email(message: AccountEmail) -> bool:
    try:
        get_sender().send(message)
        return True
    except Exception:
        logger.exception("account email could not be sent (subject=%s)", message.subject)
        return False


def link(path_query: str) -> str:
    return settings.frontend_url.rstrip("/") + "/" + path_query.lstrip("/")


def verification_email(to: str, token: str) -> AccountEmail:
    return AccountEmail(
        to=to,
        subject="Confirm your email address",
        body=f"Confirm your email address by opening this link (valid for 48 hours):\n\n{link('?verify_email=' + token)}\n\nIf you did not create an account, ignore this email.",
    )


def password_reset_email(to: str, token: str) -> AccountEmail:
    return AccountEmail(
        to=to,
        subject="Reset your password",
        body=f"Choose a new password with this link (valid for 1 hour):\n\n{link('?reset_password=' + token)}\n\nIf you did not ask for this, ignore this email; your password stays the same.",
    )


def invite_email(to: str, workspace_name: str, token: str) -> AccountEmail:
    return AccountEmail(
        to=to,
        subject=f"You are invited to {workspace_name}",
        body=f"You have been invited to join {workspace_name}. Accept the invitation with this link (valid for 7 days):\n\n{link('?invite=' + token)}",
    )
