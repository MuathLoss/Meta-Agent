"""Product scope switches (spec v1.2, Section 2.1).

The product sells one thing: a knowledge chatbot on the institution's website and its
WhatsApp number. Agent SW also contains broadcasts and other channels. Their code stays,
but their routes answer 404 and nothing is sent through them unless the owner lists them
in ENABLED_CHANNELS / sets BROADCASTS_ENABLED (both refused in production, see config).
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.config import KNOWN_CHANNELS, settings


def channel_enabled(channel_type: str | None) -> bool:
    return settings.channel_enabled(channel_type)


def enabled_channels() -> list[str]:
    return [channel for channel in KNOWN_CHANNELS if channel_enabled(channel)]


def channel_named_in_path(path: str) -> str | None:
    """Return the channel a /channels/<type>/... path belongs to, or None.

    Works whether or not a proxy prefix such as /api is still on the path.
    """
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part == "channels":
            candidate = parts[index + 1].replace("-", "_").lower()
            return candidate if candidate in KNOWN_CHANNELS else None
    return None


def require_channel_route_enabled(request: Request) -> None:
    channel = channel_named_in_path(request.url.path)
    if channel and not channel_enabled(channel):
        # 404 rather than 403: a switched-off channel should look like it does not exist.
        raise HTTPException(status_code=404, detail="Not Found")


def require_broadcasts_enabled() -> None:
    if not settings.broadcasts_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def public_features() -> dict:
    # Safe to show anyone: it only says which parts of the product are switched on.
    return {"enabled_channels": enabled_channels(), "broadcasts": settings.broadcasts_enabled}
