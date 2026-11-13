"""Website chat widget: settings, the embeddable frame's configuration, and visitor history.

The widget is a small script an institution pastes into its website. The script shows a
chat button and opens the conversation in a frame served by this platform. The frame may
only be displayed by the websites the institution lists (enforced by the browser through
Content-Security-Policy ``frame-ancestors``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import ChannelConfig, Conversation, Message, Tenant, TenantBrand

MAX_ALLOWED_WEBSITES = 20
MAX_WELCOME_LENGTH = 300
DEFAULT_COLOR = "#5b0f20"
SUPPORTED_LANGS = ("ar", "en")
HISTORY_PAGE_SIZE = 50
# Visitor ids that can read a conversation back must be long and random. Shorter ids
# (for example from older integrations) can still send messages but cannot read history.
HISTORY_VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,48}$")
HOST_RE = re.compile(
    r"^(\*\.)?(localhost|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)(?::(\d{1,5}))?$"
)
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DEFAULT_WELCOME = {
    "ar": "مرحباً! كيف نقدر نساعدك اليوم؟",
    "en": "Hi! How can we help you today?",
}
STRINGS = {
    "ar": {
        "launcher": "تحدث معنا",
        "subtitle": "نحن هنا لمساعدتك",
        "placeholder": "اكتب رسالتك…",
        "send": "إرسال",
        "close": "إغلاق المحادثة",
        "team": "الفريق",
        "handoff": "سيرد عليك أحد أعضاء الفريق هنا. يمكنك إغلاق النافذة، وستبقى رسائلك محفوظة في هذا المتصفح.",
        "error_send": "تعذّر إرسال الرسالة. تحقق من الاتصال وحاول مرة أخرى.",
        "error_rate": "أرسلت رسائل كثيرة بسرعة. انتظر قليلاً ثم حاول مرة أخرى.",
        "error_unavailable": "المحادثة غير متاحة حالياً.",
        "typing": "يكتب…",
    },
    "en": {
        "launcher": "Chat with us",
        "subtitle": "We're here to help",
        "placeholder": "Type your message…",
        "send": "Send",
        "close": "Close chat",
        "team": "Team",
        "handoff": "A team member will reply here. You can close this window; your messages stay in this browser.",
        "error_send": "Couldn't send your message. Check your connection and try again.",
        "error_rate": "You're sending messages too quickly. Please wait a moment and try again.",
        "error_unavailable": "Chat isn't available right now.",
        "typing": "Typing…",
    },
}


class InvalidWebsiteError(ValueError):
    def __init__(self, value: str):
        super().__init__(value)
        self.value = value


@dataclass
class WidgetSettings:
    allowed_websites: list[str]
    welcome_ar: str
    welcome_en: str
    language: str
    position: str

    def as_dict(self) -> dict:
        return {
            "allowed_websites": list(self.allowed_websites),
            "welcome_ar": self.welcome_ar,
            "welcome_en": self.welcome_en,
            "language": self.language,
            "position": self.position,
        }


def normalize_website(value: str) -> str | None:
    """Return ``scheme://host[:port]`` for a website entry, or None for a blank entry.

    Accepts "clinic.com", "https://www.clinic.com/contact" or "https://*.clinic.com".
    Anything that is not a plain web address is refused: the result is placed in a
    security header, so quotes, spaces, semicolons and other schemes must never pass.
    """
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text if "://" in text else f"https://{text}"
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise InvalidWebsiteError(text) from exc
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme not in {"http", "https"} or not netloc or "@" in netloc:
        raise InvalidWebsiteError(text)
    match = HOST_RE.match(netloc)
    if not match:
        raise InvalidWebsiteError(text)
    wildcard, host, port = match.groups()
    if wildcard and host == "localhost":
        raise InvalidWebsiteError(text)
    if port is not None and not 1 <= int(port) <= 65535:
        raise InvalidWebsiteError(text)
    return f"{scheme}://{netloc}"


def normalize_websites(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        normalized = normalize_website(value)
        if normalized and normalized not in result:
            result.append(normalized)
    if len(result) > MAX_ALLOWED_WEBSITES:
        raise ValueError(f"Add up to {MAX_ALLOWED_WEBSITES} websites.")
    return result


def _safe_websites(values: object) -> list[str]:
    """Re-check stored entries before they reach a header; silently drop anything unsafe."""
    if not isinstance(values, list):
        return []
    safe: list[str] = []
    for value in values[:MAX_ALLOWED_WEBSITES]:
        try:
            normalized = normalize_website(str(value))
        except InvalidWebsiteError:
            continue
        if normalized and normalized not in safe:
            safe.append(normalized)
    return safe


def read_settings(channel: ChannelConfig | None) -> WidgetSettings:
    raw = ((channel.public_config_json or {}).get("widget") if channel else None) or {}
    if not isinstance(raw, dict):
        raw = {}
    language = raw.get("language") if raw.get("language") in {"auto", *SUPPORTED_LANGS} else "auto"
    position = raw.get("position") if raw.get("position") in {"right", "left"} else "right"
    return WidgetSettings(
        allowed_websites=_safe_websites(raw.get("allowed_websites")),
        welcome_ar=str(raw.get("welcome_ar") or "")[:MAX_WELCOME_LENGTH],
        welcome_en=str(raw.get("welcome_en") or "")[:MAX_WELCOME_LENGTH],
        language=language,
        position=position,
    )


def web_chat_channel(db: Session, tenant_id: int) -> ChannelConfig | None:
    return db.query(ChannelConfig).filter(ChannelConfig.tenant_id == tenant_id, ChannelConfig.channel_type == "web_chat").first()


def channel_enabled(channel: ChannelConfig | None) -> bool:
    if not channel:
        return False
    if (channel.public_config_json or {}).get("enabled") is False:
        return False
    return channel.status in {"configured", "connected", "active"}


def _origin(url: str | None) -> str | None:
    try:
        return normalize_website(url or "")
    except InvalidWebsiteError:
        return None


def frame_ancestors(widget: WidgetSettings) -> str:
    sources = ["'self'"]
    dashboard = _origin(settings.frontend_url)
    if dashboard:
        sources.append(dashboard)
    for site in widget.allowed_websites:
        if site not in sources:
            sources.append(site)
    return " ".join(sources)


def frame_csp(widget: WidgetSettings) -> str:
    return "; ".join(
        [
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            f"frame-ancestors {frame_ancestors(widget)}",
        ]
    )


def preview_csp() -> str:
    dashboard = _origin(settings.frontend_url)
    ancestors = "'self'" + (f" {dashboard}" if dashboard else "")
    return "; ".join(
        [
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "frame-src 'self'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            f"frame-ancestors {ancestors}",
        ]
    )


def _readable_text_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    dark_luminance = 0.0056  # #111111
    contrast_white = 1.05 / (luminance + 0.05)
    contrast_dark = (luminance + 0.05) / (dark_luminance + 0.05)
    return "#ffffff" if contrast_white >= contrast_dark else "#111111"


def resolve_language(widget: WidgetSettings, tenant: Tenant, *, host_lang: str | None, accept_language: str | None) -> str:
    if widget.language in SUPPORTED_LANGS:
        return widget.language
    for candidate in (host_lang, accept_language):
        prefix = str(candidate or "").strip().lower()[:2]
        if prefix in SUPPORTED_LANGS:
            return prefix
    default = str(tenant.default_lang or "").lower()[:2]
    return default if default in SUPPORTED_LANGS else "ar"


def frame_config(db: Session, tenant: Tenant, widget: WidgetSettings, *, lang: str) -> dict:
    brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
    color = brand.primary_color if brand and HEX_COLOR_RE.match(brand.primary_color or "") else DEFAULT_COLOR
    logo = brand.logo_url if brand and (brand.logo_url or "").startswith("/uploads/tenant_logos/") else None
    welcome = (widget.welcome_ar if lang == "ar" else widget.welcome_en).strip() or DEFAULT_WELCOME[lang]
    return {
        "slug": tenant.slug,
        "title": tenant.display_name,
        "logo": logo,
        "color": color,
        "text_color": _readable_text_color(color),
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "position": widget.position,
        "welcome": welcome,
        "strings": STRINGS[lang],
    }


def json_for_html(data: dict) -> str:
    """JSON that is safe inside a <script type="application/json"> element."""
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def message_sender(message: Message) -> str:
    if message.direction == "inbound":
        return "visitor"
    if message.intent_code in {"MANUAL_REPLY", "BROADCAST"}:
        return "team"
    return "agent"


def visitor_history(db: Session, *, tenant_id: int, customer_id: int, after: int) -> tuple[list[dict], str | None]:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id, Conversation.customer_id == customer_id, Conversation.channel_type == "web_chat")
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )
    if not conversations:
        return [], None
    query = db.query(Message).filter(
        Message.tenant_id == tenant_id,
        Message.conversation_id.in_([row.id for row in conversations]),
        Message.direction.in_(["inbound", "outbound"]),
        Message.text.isnot(None),
        Message.id > after,
    )
    if after:
        rows = query.order_by(Message.id.asc()).limit(HISTORY_PAGE_SIZE).all()
    else:
        rows = list(reversed(query.order_by(Message.id.desc()).limit(HISTORY_PAGE_SIZE).all()))
    messages = [
        {
            "id": row.id,
            "from": message_sender(row),
            "text": row.text,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
        if (row.text or "").strip()
    ]
    return messages, conversations[0].state
