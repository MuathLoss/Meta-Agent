from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import FaqItem, IntentDefinition, Tenant
from app.services.business_info_response_service import BusinessInfoResponseService


class ResponseEngine:
    def __init__(self):
        self.business_info = BusinessInfoResponseService()

    def build_response(
        self,
        db: Session,
        tenant: Tenant,
        intent_code: str,
        faq_topic_key: str | None = None,
        preferred_lang: str | None = None,
    ) -> str | None:
        intent = (
            db.query(IntentDefinition)
            .filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == intent_code)
            .first()
        )
        if self.business_info.supports_intent(intent_code) or (intent and intent.response_mode == "business_settings"):
            dynamic = self.business_info.build_response(
                db,
                tenant=tenant,
                intent_code=intent_code,
                preferred_lang=preferred_lang,
            )
            if dynamic:
                return dynamic
        if intent and intent.response_mode == "custom":
            return self.select_localized_text(
                {
                    "ar": intent.custom_response_ar,
                    "en": intent.custom_response_en,
                },
                preferred_lang=preferred_lang,
                tenant_default_lang=tenant.default_lang,
            )
        keys = []
        if faq_topic_key:
            keys.append(faq_topic_key)
        if intent and intent.default_response_topic_key:
            keys.append(intent.default_response_topic_key)
        keys += [intent_code.lower(), "faq_general"]
        faq_rows = (
            db.query(FaqItem)
            .filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key.in_(keys), FaqItem.status == "active")
            .order_by(FaqItem.id.desc())
            .all()
        )
        if not faq_rows:
            return None
        return self._select_faq_response(
            faq_rows,
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        )

    def clarification_question(self, tenant: Tenant, preferred_lang: str | None = None) -> str:
        return self.select_localized_text(
            {
                "ar": "ممكن توضح طلبك أكثر؟",
                "en": "Could you clarify your request?",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "Could you clarify your request?"

    def out_of_hours_reply(self, tenant: Tenant, preferred_lang: str | None = None) -> str:
        return self.select_localized_text(
            {
                "ar": "أهلاً بك. وصلت رسالتك خارج أوقات الدوام، وسيتم الرد عليك خلال وقت العمل. يمكنك ترك استفسارك الآن وسنساعدك قريباً.",
                "en": "Thanks for your message. We received it outside working hours and will reply during business hours.",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "Thanks for your message. We received it outside working hours and will reply during business hours."

    def handoff_acknowledgement(self, tenant: Tenant, preferred_lang: str | None = None) -> str:
        return self.select_localized_text(
            {
                "ar": "تم تحويل طلبك إلى فريقنا، وسيرد عليك أحد الموظفين في أقرب وقت ممكن.",
                "en": "I've passed your request to our team. A team member will reply as soon as possible.",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "I've passed your request to our team. A team member will reply as soon as possible."

    def handoff_offer_clarification(self, tenant: Tenant, preferred_lang: str | None = None) -> str:
        return self.select_localized_text(
            {
                "ar": "إذا رغبت بالتحويل إلى موظف اكتب نعم، وإذا لا اكتفِ بذلك اكتب لا.",
                "en": "If you want me to connect you with a human agent, reply yes. If not, reply no.",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "If you want me to connect you with a human agent, reply yes. If not, reply no."

    def handoff_declined_reply(self, tenant: Tenant, preferred_lang: str | None = None) -> str:
        return self.select_localized_text(
            {
                "ar": "تمام، سأبقى معك هنا. إذا احتجت موظف لاحقاً فقط اكتب: أبغى موظف.",
                "en": "No problem, I can keep helping here. If you want a human later, just say: I want a human agent.",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "No problem, I can keep helping here. If you want a human later, just say: I want a human agent."

    def select_localized_text(
        self,
        values_by_lang: dict[str, str | None],
        *,
        preferred_lang: str | None,
        tenant_default_lang: str | None,
    ) -> str | None:
        normalized = {
            (key or "").strip().lower(): (value.strip() if isinstance(value, str) else None)
            for key, value in values_by_lang.items()
        }
        available = {key: value for key, value in normalized.items() if value}
        if not available:
            return None

        preferred = self._normalized_lang(preferred_lang)
        default = self._normalized_lang(tenant_default_lang)
        for candidate in [preferred, default]:
            if candidate and available.get(candidate):
                return available[candidate]
        return next(iter(available.values()))

    def _select_faq_response(
        self,
        faq_rows: list[FaqItem],
        *,
        preferred_lang: str | None,
        tenant_default_lang: str | None,
    ) -> str | None:
        preferred = self._normalized_lang(preferred_lang)
        default = self._normalized_lang(tenant_default_lang)

        for candidate in [preferred, default]:
            if not candidate:
                continue
            for row in faq_rows:
                text = self.select_localized_text(
                    {"ar": row.arabic_answer, "en": row.english_answer},
                    preferred_lang=candidate,
                    tenant_default_lang=candidate,
                )
                if text:
                    selected = {"ar": row.arabic_answer, "en": row.english_answer}.get(candidate)
                    if selected and selected.strip():
                        return selected.strip()

        for row in faq_rows:
            text = self.select_localized_text(
                {"ar": row.arabic_answer, "en": row.english_answer},
                preferred_lang=preferred_lang,
                tenant_default_lang=tenant_default_lang,
            )
            if text:
                return text
        return None

    def _normalized_lang(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = str(value).strip().lower()
        return normalized or None
