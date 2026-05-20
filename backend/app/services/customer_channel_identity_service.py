from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.entities import Customer


class CustomerChannelIdentityService:
    TELEGRAM_PREFIX = "tg:"
    WEB_CHAT_PREFIX = "webchat:"
    EMAIL_PREFIX = "email:"

    def _dedupe(self, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            if tag in seen:
                continue
            seen.add(tag)
            result.append(tag)
        return result

    def _replace_prefixed_tag(self, tags: list[str], prefix: str, value: str | None) -> list[str]:
        filtered = [tag for tag in tags if not tag.startswith(prefix)]
        if value is not None:
            filtered.append(f"{prefix}{value}")
        return self._dedupe(filtered)

    def _tag_value(self, customer: Customer, prefix: str) -> str | None:
        for tag in customer.tags_json or []:
            if isinstance(tag, str) and tag.startswith(prefix):
                return tag[len(prefix):]
        return None

    def normalize_inbound_address(self, channel_type: str, address: str) -> str:
        raw = str(address).strip()
        if channel_type == "telegram":
            return raw if raw.startswith(self.TELEGRAM_PREFIX) else f"{self.TELEGRAM_PREFIX}{raw}"
        if channel_type == "web_chat":
            return raw if raw.startswith(self.WEB_CHAT_PREFIX) else f"{self.WEB_CHAT_PREFIX}{raw}"
        if channel_type == "email":
            normalized_email = raw.lower()
            return normalized_email if normalized_email.startswith(self.EMAIL_PREFIX) else f"{self.EMAIL_PREFIX}{normalized_email}"
        return raw

    def lookup_customer(self, db: Session, *, tenant_id: int, channel_type: str, address: str) -> Customer | None:
        normalized = self.normalize_inbound_address(channel_type, address)
        if channel_type == "email":
            raw_email = normalized[len(self.EMAIL_PREFIX):] if normalized.startswith(self.EMAIL_PREFIX) else str(address).strip().lower()
            by_email = (
                db.query(Customer)
                .filter(Customer.tenant_id == tenant_id, func.lower(Customer.email) == raw_email)
                .order_by(Customer.id.asc())
                .first()
            )
            if by_email:
                return by_email
            return db.query(Customer).filter(Customer.tenant_id == tenant_id, Customer.phone == normalized).first()
        if channel_type == "web_chat":
            return db.query(Customer).filter(Customer.tenant_id == tenant_id, Customer.phone == normalized).first()
        if channel_type == "telegram":
            raw = normalized[len(self.TELEGRAM_PREFIX):] if normalized.startswith(self.TELEGRAM_PREFIX) else normalized
            row = (
                db.query(Customer)
                .filter(Customer.tenant_id == tenant_id, Customer.phone.in_([normalized, raw]))
                .order_by(Customer.id.asc())
                .first()
            )
            if row and row.phone != normalized:
                row.phone = normalized
            return row
        return db.query(Customer).filter(Customer.tenant_id == tenant_id, Customer.phone == normalized).first()

    def update_inbound_customer(self, customer: Customer, *, channel_type: str, raw_address: str, payload_json: dict | None, default_lang: str) -> None:
        customer.preferred_lang = customer.preferred_lang or default_lang
        if channel_type == "web_chat":
            customer.phone = self.normalize_inbound_address(channel_type, raw_address)
            tags = list(customer.tags_json or [])
            tags = self._replace_prefixed_tag(tags, "channel:", "web_chat")
            tags = self._replace_prefixed_tag(tags, "web_chat_visitor_id:", str(raw_address))
            customer.tags_json = tags
            return
        if channel_type == "email":
            normalized_address = self.normalize_inbound_address(channel_type, raw_address)
            customer.phone = normalized_address
            raw_email = normalized_address[len(self.EMAIL_PREFIX):] if normalized_address.startswith(self.EMAIL_PREFIX) else str(raw_address).strip().lower()
            customer.email = raw_email
            tags = list(customer.tags_json or [])
            tags = self._replace_prefixed_tag(tags, "channel:", "email")
            customer.tags_json = tags
            return
        if channel_type != "telegram":
            customer.phone = self.normalize_inbound_address(channel_type, raw_address)
            return

        customer.phone = self.normalize_inbound_address("telegram", raw_address)
        tags = list(customer.tags_json or [])
        tags = self._replace_prefixed_tag(tags, "channel:", "telegram")
        tags = self._replace_prefixed_tag(tags, "telegram_chat_id:", str(raw_address))
        tags = self._replace_prefixed_tag(tags, "telegram_reachable:", "true")
        customer.tags_json = tags

        payload = payload_json or {}
        message = payload.get("message") or payload.get("edited_message") or {}
        chat = message.get("chat") if isinstance(message, dict) else {}
        if isinstance(chat, dict):
            username = chat.get("username")
            first_name = chat.get("first_name")
            last_name = chat.get("last_name")
            display_name = ""
            if isinstance(username, str) and username.strip():
                display_name = f"@{username.strip()}"
            else:
                parts = [str(part).strip() for part in [first_name, last_name] if isinstance(part, str) and part.strip()]
                display_name = " ".join(parts)
            if display_name and not customer.name:
                customer.name = display_name

    def delivery_address(self, customer: Customer, channel_type: str) -> str:
        if channel_type == "email":
            return str(customer.email or "").strip()
        if channel_type == "web_chat":
            tagged = self._tag_value(customer, "web_chat_visitor_id:")
            if tagged:
                return tagged
            if customer.phone.startswith(self.WEB_CHAT_PREFIX):
                return customer.phone[len(self.WEB_CHAT_PREFIX):]
        if channel_type == "telegram":
            tagged = self._tag_value(customer, "telegram_chat_id:")
            if tagged:
                return tagged
            if customer.phone.startswith(self.TELEGRAM_PREFIX):
                return customer.phone[len(self.TELEGRAM_PREFIX):]
        return customer.phone

    def display_identity(self, customer: Customer) -> str:
        if customer.phone.startswith(self.EMAIL_PREFIX) and customer.email:
            return customer.email
        web_chat_tagged = self._tag_value(customer, "web_chat_visitor_id:")
        if web_chat_tagged:
            return f"web_chat:{web_chat_tagged}"
        if customer.phone.startswith(self.WEB_CHAT_PREFIX):
            return f"web_chat:{customer.phone[len(self.WEB_CHAT_PREFIX):]}"
        tagged = self._tag_value(customer, "telegram_chat_id:")
        if tagged:
            return f"telegram:{tagged}"
        if customer.phone.startswith(self.TELEGRAM_PREFIX):
            return f"telegram:{customer.phone[len(self.TELEGRAM_PREFIX):]}"
        return customer.phone

    def is_reachable(self, customer: Customer, channel_type: str) -> bool:
        if channel_type != "telegram":
            return True
        return self._tag_value(customer, "telegram_reachable:") != "false"

    def mark_unreachable(self, customer: Customer, channel_type: str) -> None:
        if channel_type != "telegram":
            return
        tags = list(customer.tags_json or [])
        customer.tags_json = self._replace_prefixed_tag(tags, "telegram_reachable:", "false")

    def mark_reachable(self, customer: Customer, channel_type: str) -> None:
        if channel_type != "telegram":
            return
        tags = list(customer.tags_json or [])
        customer.tags_json = self._replace_prefixed_tag(tags, "telegram_reachable:", "true")
