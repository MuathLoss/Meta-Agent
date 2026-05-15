import httpx

from app.models.entities import FaqItem, IntentDefinition, IntentKeyword, RoutingRule, Tenant
from app.services.ollama_intelligence_service import OllamaIntelligenceService


def test_ollama_context_uses_only_current_tenant_data(db, tenant):
    other = Tenant(slug="other-tenant", display_name="Other Tenant", timezone="Asia/Riyadh", default_lang="ar", status="active")
    db.add(other)
    db.flush()
    db.add(IntentDefinition(tenant_id=other.id, code="OTHER_ONLY", label="Other Only", enabled=True, is_universal=False, default_response_topic_key="other_only"))
    db.add(IntentKeyword(tenant_id=other.id, intent_code="OTHER_ONLY", phrase="سري", weight=9))
    db.add(FaqItem(tenant_id=other.id, topic_key="other_only", question_ar="?", arabic_answer="other-secret-answer", status="active"))
    db.add(RoutingRule(tenant_id=other.id, intent_code="OTHER_ONLY", primary_owner_role="BOT", handoff_required=False, priority="normal"))
    db.commit()

    payload = OllamaIntelligenceService()._tenant_context(db, tenant=tenant, text="bkm el akl?")

    serialized = str(payload)
    assert tenant.display_name in serialized
    assert other.display_name not in serialized
    assert "other-secret-answer" not in serialized
    assert "OTHER_ONLY" not in serialized


def test_ollama_timeout_returns_none(monkeypatch, db, tenant):
    service = OllamaIntelligenceService()
    monkeypatch.setattr("app.services.ollama_intelligence_service.settings.ollama_enabled", True)

    def fake_post(self, url, json):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = service.classify(db, tenant=tenant, text="bkm el akl?")
    assert result is None


def test_ollama_is_attempted_for_weak_rule_match(monkeypatch):
    service = OllamaIntelligenceService()
    monkeypatch.setattr("app.services.ollama_intelligence_service.settings.ollama_enabled", True)
    assert service.should_attempt(rule_intent_code="PRICING", rule_confidence=0.72, mixed=False, needs_clarification=True) is True
    assert service.should_attempt(rule_intent_code="PRICING", rule_confidence=0.95, mixed=False, needs_clarification=False) is False
