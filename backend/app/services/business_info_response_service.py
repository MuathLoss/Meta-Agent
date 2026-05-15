from __future__ import annotations

from app.services.intent_rules import normalize_text
from sqlalchemy.orm import Session

from app.models.entities import Branch, Tenant, TenantBrand
from app.services.working_hours import _periods_from_hours_json


class BusinessInfoResponseService:
    LOCATION_INTENTS = {"LOCATION", "ADDRESS", "BRANCH", "DIRECTIONS"}
    HOURS_INTENTS = {"SCHEDULES", "HOURS", "WORKING_HOURS", "OPENING_HOURS", "CLOSING_TIME"}
    CONTACT_INTENTS = {"CONTACT", "SUPPORT_PHONE", "PHONE", "WHATSAPP"}
    LOCATION_PATTERNS = {
        "ar": ["وين موقعكم", "الموقع", "العنوان", "وين الفرع", "لوكيشن"],
        "en": ["where are you located", "location", "address", "where is your branch", "branch location"],
    }
    HOURS_PATTERNS = {
        "ar": ["متى تفتحون", "متى تقفلون", "اوقات العمل", "ساعات العمل", "الدوام", "مواعيدكم"],
        "en": ["what time do you open", "what time do you close", "working hours", "opening hours", "business hours", "when are you open"],
    }
    CONTACT_PATTERNS = {
        "ar": ["رقمكم", "رقم التواصل", "رقم الدعم", "واتساب", "رقم الهاتف"],
        "en": ["contact number", "support number", "phone number", "whatsapp number", "contact phone"],
    }

    def build_response(self, db: Session, *, tenant: Tenant, intent_code: str, preferred_lang: str | None) -> str | None:
        normalized_intent = (intent_code or "").strip().upper()
        lang = "en" if (preferred_lang or "").strip().lower() == "en" else "ar"

        if normalized_intent in self.LOCATION_INTENTS:
            return self._location_response(db, tenant=tenant, lang=lang)
        if normalized_intent in self.HOURS_INTENTS:
            return self._hours_response(db, tenant=tenant, lang=lang)
        if normalized_intent in self.CONTACT_INTENTS:
            return self._contact_response(db, tenant=tenant, lang=lang)
        return None

    def supports_intent(self, intent_code: str) -> bool:
        normalized_intent = (intent_code or "").strip().upper()
        return normalized_intent in self.LOCATION_INTENTS | self.HOURS_INTENTS | self.CONTACT_INTENTS

    def detect_dynamic_intent(self, text: str, preferred_lang: str | None) -> str | None:
        normalized = normalize_text(text)
        lang = "en" if (preferred_lang or "").strip().lower() == "en" else "ar"
        for phrase in self.LOCATION_PATTERNS.get(lang, []):
            if normalize_text(phrase) in normalized:
                return "LOCATION"
        for phrase in self.HOURS_PATTERNS.get(lang, []):
            if normalize_text(phrase) in normalized:
                return "SCHEDULES"
        for phrase in self.CONTACT_PATTERNS.get(lang, []):
            if normalize_text(phrase) in normalized:
                return "CONTACT"

        for phrase in self.LOCATION_PATTERNS["ar"] + self.LOCATION_PATTERNS["en"]:
            if normalize_text(phrase) in normalized:
                return "LOCATION"
        for phrase in self.HOURS_PATTERNS["ar"] + self.HOURS_PATTERNS["en"]:
            if normalize_text(phrase) in normalized:
                return "SCHEDULES"
        for phrase in self.CONTACT_PATTERNS["ar"] + self.CONTACT_PATTERNS["en"]:
            if normalize_text(phrase) in normalized:
                return "CONTACT"
        return None

    def _active_branches(self, db: Session, tenant: Tenant) -> list[Branch]:
        return (
            db.query(Branch)
            .filter(Branch.tenant_id == tenant.id, Branch.is_active.is_(True))
            .order_by(Branch.created_at.asc(), Branch.id.asc())
            .all()
        )

    def _location_response(self, db: Session, *, tenant: Tenant, lang: str) -> str | None:
        branches = self._active_branches(db, tenant)
        if not branches:
            return None

        if lang == "en":
            intro = "Our location:"
            lines = [f"{intro} {self._branch_location_line(branch, lang='en')}" for branch in branches]
        else:
            intro = "موقعنا:"
            lines = [f"{intro} {self._branch_location_line(branch, lang='ar')}" for branch in branches]
        return "\n".join(lines)

    def _hours_response(self, db: Session, *, tenant: Tenant, lang: str) -> str | None:
        branches = self._active_branches(db, tenant)
        if not branches:
            return None

        lines: list[str] = []
        for branch in branches:
            periods = _periods_from_hours_json(branch.hours_json or {})
            if not periods:
                continue
            formatted = ", ".join(self._format_period(start, end) for start, end in periods)
            if lang == "en":
                lines.append(f"{branch.name}: {formatted}")
            else:
                lines.append(f"{branch.name}: {formatted}")

        if not lines:
            return None

        if lang == "en":
            return "Our working hours:\n" + "\n".join(lines)
        return "أوقات العمل لدينا:\n" + "\n".join(lines)

    def _contact_response(self, db: Session, *, tenant: Tenant, lang: str) -> str | None:
        brand = db.query(TenantBrand).filter(TenantBrand.tenant_id == tenant.id).first()
        support_phone = (brand.support_phone or "").strip() if brand else ""
        if not support_phone:
            return None
        if lang == "en":
            return f"You can contact us on: {support_phone}"
        return f"يمكنك التواصل معنا على: {support_phone}"

    def _branch_location_line(self, branch: Branch, *, lang: str) -> str:
        parts = [branch.name]
        if branch.city:
            parts.append(branch.city)
        if branch.address:
            parts.append(branch.address)
        line = ", ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
        if branch.maps_url:
            if lang == "en":
                return f"{line}. Map: {branch.maps_url}" if line else f"Map: {branch.maps_url}"
            return f"{line}. رابط الموقع: {branch.maps_url}" if line else f"رابط الموقع: {branch.maps_url}"
        return line

    def _format_period(self, start, end) -> str:
        return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
