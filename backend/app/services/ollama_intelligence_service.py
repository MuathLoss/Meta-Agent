import json
import logging
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Branch, FaqItem, IntentDefinition, IntentKeyword, RoutingRule, Tenant, TrainingExample
from app.services.intent_rules import normalize_text

logger = logging.getLogger(__name__)


class OllamaClassificationPayload(BaseModel):
    intent_code: str
    confidence: float = Field(ge=0.0, le=1.0)
    faq_topic_key: str | None = None
    needs_clarification: bool
    clarification_question: str | None = None
    route_owner_role: str | None = None
    reasoning_short: str = ""


@dataclass
class OllamaDecision:
    intent_code: str
    confidence: float
    faq_topic_key: str | None
    needs_clarification: bool
    clarification_question: str | None
    route_owner_role: str | None
    reasoning_short: str
    raw_response: dict = field(default_factory=dict)


class OllamaIntelligenceService:
    CONFIDENCE_FLOOR = 0.55
    RULE_CONFIDENCE_THRESHOLD = 0.75
    TRAINING_EXAMPLE_LIMIT = 25

    def is_enabled(self) -> bool:
        return settings.ollama_enabled

    def should_attempt(self, *, rule_intent_code: str, rule_confidence: float, mixed: bool, needs_clarification: bool) -> bool:
        if not self.is_enabled():
            return False
        if rule_intent_code == "UNKNOWN":
            return True
        if mixed:
            return True
        if needs_clarification:
            return True
        return rule_confidence < self.RULE_CONFIDENCE_THRESHOLD

    def classify(self, db: Session, *, tenant: Tenant, text: str, language_hint: str | None = None) -> OllamaDecision | None:
        if not self.is_enabled():
            return None

        request_payload = self._build_request_payload(db, tenant=tenant, text=text, language_hint=language_hint)
        try:
            with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
                response = client.post(self._chat_url(), json=request_payload)
                response.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out for tenant_id=%s", tenant.id)
            return None
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed for tenant_id=%s: %s", tenant.id, exc)
            return None

        body = response.json()
        content = ((body.get("message") or {}).get("content") or "").strip()
        if not content:
            logger.warning("Ollama returned empty content for tenant_id=%s", tenant.id)
            return None

        try:
            parsed = OllamaClassificationPayload.model_validate_json(content)
        except ValidationError as exc:
            logger.warning("Ollama returned invalid JSON for tenant_id=%s: %s", tenant.id, exc)
            return None

        return self._sanitize_decision(db, tenant=tenant, parsed=parsed, raw_response=body)

    def _chat_url(self) -> str:
        base_url = settings.ollama_base_url.rstrip("/")
        if base_url.endswith("/api"):
            return f"{base_url}/chat"
        return f"{base_url}/api/chat"

    def _build_request_payload(self, db: Session, *, tenant: Tenant, text: str, language_hint: str | None = None) -> dict:
        schema = OllamaClassificationPayload.model_json_schema()
        tenant_context = self._tenant_context(db, tenant=tenant, text=text, language_hint=language_hint)
        context_json = json.dumps(tenant_context, ensure_ascii=False)
        schema_json = json.dumps(schema, ensure_ascii=False)
        system_prompt = (
            "You are a strict intent classifier for one tenant in a multi-tenant business agent platform. "
            "Use only the provided tenant context. Do not invent products, policies, FAQs, or intents. "
            "Return only valid JSON matching the provided schema."
        )
        user_prompt = (
            "Classify the customer message using only this tenant data.\n"
            "Rules:\n"
            "- Choose exactly one enabled intent_code or UNKNOWN.\n"
            "- faq_topic_key must be one of the provided active FAQ topic keys or null.\n"
            "- If the message is ambiguous or weakly supported, set needs_clarification=true.\n"
            "- Keep clarification_question short and only when clarification is needed.\n"
            "- route_owner_role should align with the provided routing rules when clear, otherwise null.\n"
            "- Never invent business facts or new FAQ content.\n"
            "- Use the provided keywords, examples, and FAQ topics only as classification evidence.\n"
            "- reasoning_short must be brief.\n\n"
            f"JSON schema:\n{schema_json}\n\n"
            f"Tenant context:\n{context_json}"
        )
        return {
            "model": settings.ollama_model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def _tenant_context(self, db: Session, *, tenant: Tenant, text: str, language_hint: str | None = None) -> dict:
        intents = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.enabled.is_(True)).order_by(IntentDefinition.code).all()
        allowed_intents = {row.code for row in intents}
        keywords = db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id).order_by(IntentKeyword.intent_code, IntentKeyword.id).all()
        faqs = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.status == "active").order_by(FaqItem.topic_key, FaqItem.id).all()
        routes = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id).order_by(RoutingRule.intent_code).all()
        examples = (
            db.query(TrainingExample)
            .filter(TrainingExample.tenant_id == tenant.id, TrainingExample.labeled_intent.is_not(None))
            .order_by(TrainingExample.id.desc())
            .limit(self.TRAINING_EXAMPLE_LIMIT)
            .all()
        )
        branches = db.query(Branch).filter(Branch.tenant_id == tenant.id, Branch.is_active.is_(True)).order_by(Branch.id).all()

        return {
            "tenant": {
                "id": tenant.id,
                "slug": tenant.slug,
                "display_name": tenant.display_name,
                "country": tenant.country,
                "default_lang": tenant.default_lang,
                "branches": [{"name": row.name, "city": row.city} for row in branches],
            },
            "customer_message": text,
            "customer_message_language": language_hint,
            "enabled_intents": [
                {
                    "code": row.code,
                    "label": row.label,
                    "default_response_topic_key": row.default_response_topic_key,
                }
                for row in intents
            ],
            "intent_keywords": [
                {
                    "intent_code": row.intent_code,
                    "phrase": row.phrase,
                    "normalized_phrase": normalize_text(row.phrase),
                    "weight": row.weight,
                    "lang": row.lang,
                }
                for row in keywords
                if row.intent_code in allowed_intents
            ],
            "active_faq_items": [
                {
                    "topic_key": row.topic_key,
                    "question_ar": row.question_ar,
                    "english_question": row.english_question,
                }
                for row in faqs
            ],
            "routing_rules": [
                {
                    "intent_code": row.intent_code,
                    "primary_owner_role": row.primary_owner_role,
                    "handoff_required": row.handoff_required,
                    "ticket_type": row.ticket_type,
                    "priority": row.priority,
                }
                for row in routes
                if row.intent_code in allowed_intents
            ],
            "training_examples": [
                {
                    "raw_text": row.raw_text,
                    "normalized_text": row.normalized_text,
                    "labeled_intent": row.labeled_intent,
                }
                for row in reversed(examples)
                if row.labeled_intent in allowed_intents
            ],
        }

    def _sanitize_decision(
        self,
        db: Session,
        *,
        tenant: Tenant,
        parsed: OllamaClassificationPayload,
        raw_response: dict,
    ) -> OllamaDecision:
        enabled_intents = {
            row.code
            for row in db.query(IntentDefinition).filter(
                IntentDefinition.tenant_id == tenant.id,
                IntentDefinition.enabled.is_(True),
            ).all()
        }
        faq_topics = {
            row.topic_key
            for row in db.query(FaqItem).filter(
                FaqItem.tenant_id == tenant.id,
                FaqItem.status == "active",
            ).all()
        }
        route_roles = {
            row.intent_code: row.primary_owner_role
            for row in db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id).all()
        }

        intent_code = parsed.intent_code if parsed.intent_code in enabled_intents else "UNKNOWN"
        faq_topic_key = parsed.faq_topic_key if parsed.faq_topic_key in faq_topics else None
        confidence = min(max(parsed.confidence, 0.0), 1.0)
        needs_clarification = bool(parsed.needs_clarification or intent_code == "UNKNOWN" or confidence < self.CONFIDENCE_FLOOR)
        clarification_question = (parsed.clarification_question or "").strip() or None
        if not needs_clarification:
            clarification_question = None
        route_owner_role = route_roles.get(intent_code)
        reasoning_short = (parsed.reasoning_short or "").strip()[:240]

        return OllamaDecision(
            intent_code=intent_code,
            confidence=confidence,
            faq_topic_key=faq_topic_key,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            route_owner_role=route_owner_role,
            reasoning_short=reasoning_short,
            raw_response=raw_response,
        )
