from app.models.entities import IntentDefinition, IntentKeyword, RoutingRule
from app.services.intent_rules import IntentRules, normalize_text
from app.services.language_service import LanguageService
from app.services.routing_engine import RoutingEngine


def ensure_intent(db, tenant, *, code: str, topic_key: str, label: str):
    row = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).first()
    if row:
        return row
    row = IntentDefinition(
        tenant_id=tenant.id,
        code=code,
        label=label,
        enabled=True,
        is_universal=False,
        supported_languages="both",
        response_mode="faq",
        default_response_topic_key=topic_key,
    )
    db.add(row)
    db.add(RoutingRule(tenant_id=tenant.id, intent_code=code, primary_owner_role="BOT", handoff_required=False, priority="normal"))
    db.commit()
    return row


def test_arabic_normalization_handles_alef_variants():
    assert normalize_text("إستفسار عن الأسعار؟") == "استفسار عن الاسعار"


def test_pricing_intent_matches_tenant_keywords(db, tenant):
    result = IntentRules().classify(db, tenant.id, "السلام عليكم بكم السعر؟", language_hint="ar")
    assert result.intent_code == "PRICING"
    assert result.confidence >= 0.9
    assert result.source == "rules"


def test_english_pricing_intent_matches_english_keywords(db, tenant):
    result = IntentRules().classify(db, tenant.id, "hello, what is the price?", language_hint="en")
    assert result.intent_code == "PRICING"
    assert "price" in [phrase.lower() for phrase in result.matched_phrases]


def test_arabic_typo_matches_complaint_keyword(db, tenant):
    result = IntentRules().classify(db, tenant.id, "شكوا", language_hint="ar")
    assert result.intent_code == "COMPLAINT"
    assert result.confidence >= 0.74
    assert "fuzzy" in (result.reasoning_short or "")


def test_arabic_sentence_typo_matches_complaint_keyword(db, tenant):
    result = IntentRules().classify(db, tenant.id, "عندي شكوا", language_hint="ar")
    assert result.intent_code == "COMPLAINT"
    assert result.confidence >= 0.74


def test_pricing_paraphrase_matches_with_universal_hint(db, tenant):
    result = IntentRules().classify(db, tenant.id, "how much is it?", language_hint="en")
    assert result.intent_code == "PRICING"
    assert result.confidence >= 0.8


def test_pricing_typo_matches_with_fuzzy_scoring(db, tenant):
    result = IntentRules().classify(db, tenant.id, "prce", language_hint="en")
    assert result.intent_code == "PRICING"
    assert result.confidence >= 0.74
    assert "fuzzy" in (result.reasoning_short or "")


def test_location_matches_messy_english_phrasing(db, tenant):
    ensure_intent(db, tenant, code="LOCATION", topic_key="location", label="Location")
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="location", weight=2, lang="en"))
    db.commit()

    result = IntentRules().classify(db, tenant.id, "where r u located", language_hint="en")
    assert result.intent_code == "LOCATION"
    assert result.confidence >= 0.8


def test_location_matches_arabic_without_punctuation(db, tenant):
    ensure_intent(db, tenant, code="LOCATION", topic_key="location", label="Location")
    db.add(IntentKeyword(tenant_id=tenant.id, intent_code="LOCATION", phrase="وين موقعكم", weight=3, lang="ar"))
    db.commit()

    result = IntentRules().classify(db, tenant.id, "وين موقعكم؟", language_hint="ar")
    assert result.intent_code == "LOCATION"
    assert result.confidence >= 0.9


def test_random_nonsense_stays_unknown(db, tenant):
    result = IntentRules().classify(db, tenant.id, "zzq 7781 blrp", language_hint="en")
    assert result.intent_code == "UNKNOWN"
    assert result.needs_clarification is True


def test_language_service_prefers_detected_language_then_customer_then_tenant():
    service = LanguageService()
    detected = service.resolve_runtime_language(text="وين موقعكم", customer_preferred_lang="en", tenant_default_lang="ar")
    assert detected.detected_lang == "ar"
    assert detected.resolved_lang == "ar"

    preferred = service.resolve_runtime_language(text="12345", customer_preferred_lang="en", tenant_default_lang="ar")
    assert preferred.detected_lang is None
    assert preferred.resolved_lang == "en"

    fallback = service.resolve_runtime_language(text="12345", customer_preferred_lang=None, tenant_default_lang="ar")
    assert fallback.detected_lang is None
    assert fallback.resolved_lang == "ar"


def test_complaint_routes_to_high_priority_handoff(db, tenant):
    result = IntentRules().classify(db, tenant.id, "عندي شكوى", language_hint="ar")
    route = RoutingEngine().decide(db, tenant.id, result.intent_code)
    assert route.action == "TICKET"
    assert route.handoff_required is True
    assert route.priority == "high"
