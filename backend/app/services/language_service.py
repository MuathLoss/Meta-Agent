from __future__ import annotations

import re
from dataclasses import dataclass


ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_CHAR_RE = re.compile(r"[A-Za-z]")


@dataclass
class LanguageDetectionResult:
    detected_lang: str | None
    resolved_lang: str
    source: str
    is_confident: bool


class LanguageService:
    SUPPORTED_LANGUAGE_CODES = {"ar", "en"}

    def detect_message_language(self, text: str) -> str | None:
        raw = text or ""
        arabic_count = len(ARABIC_CHAR_RE.findall(raw))
        latin_count = len(LATIN_CHAR_RE.findall(raw))

        if arabic_count == 0 and latin_count == 0:
            return None
        if arabic_count > 0 and latin_count == 0:
            return "ar"
        if latin_count > 0 and arabic_count == 0:
            return "en"
        if arabic_count >= latin_count * 1.5:
            return "ar"
        if latin_count >= arabic_count * 1.5:
            return "en"
        return None

    def resolve_runtime_language(
        self,
        *,
        text: str,
        customer_preferred_lang: str | None,
        tenant_default_lang: str | None,
    ) -> LanguageDetectionResult:
        detected = self.detect_message_language(text)
        if detected:
            return LanguageDetectionResult(
                detected_lang=detected,
                resolved_lang=detected,
                source="message_detected",
                is_confident=True,
            )

        preferred = self._normalized_lang(customer_preferred_lang)
        if preferred:
            return LanguageDetectionResult(
                detected_lang=None,
                resolved_lang=preferred,
                source="customer_preferred_lang",
                is_confident=False,
            )

        fallback = self._normalized_lang(tenant_default_lang) or "ar"
        return LanguageDetectionResult(
            detected_lang=None,
            resolved_lang=fallback,
            source="tenant_default_lang",
            is_confident=False,
        )

    def _normalized_lang(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

