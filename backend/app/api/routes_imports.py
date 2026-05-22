from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.routes_config import audit, normalize_intent_code, normalize_topic_key
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import FaqItem, IntentDefinition, IntentKeyword, Tenant, TrainingExample
from app.services.intent_rules import normalize_text
from app.services.smart_import_service import MAX_IMPORT_BYTES, SmartImportService

router = APIRouter(prefix="/imports/smart", tags=["smart imports"])
service = SmartImportService()


class SmartPreviewTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_IMPORT_BYTES)
    source_type: str = Field(default="paste", max_length=40)


class SmartImportApproveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str
    decision: str = "approved"
    redacted_excerpt: str = Field(default="", max_length=500)
    normalized_text: str = Field(default="", max_length=500)
    intent_code: str | None = None
    intent_label: str | None = None
    create_intent: bool = False
    training_example_text: str | None = None
    keyword_phrases: list[str] = Field(default_factory=list, max_length=10)
    create_faq: bool = False
    routing_behavior: str | None = None
    faq_topic_key: str | None = None
    faq_question: str | None = None
    faq_answer_ar: str | None = None
    faq_answer_en: str | None = None


class SmartImportApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = "preview"
    total_rows: int = 0
    items: list[SmartImportApproveItem] = Field(default_factory=list, max_length=500)


@router.post("/preview-text")
def preview_text(
    payload: SmartPreviewTextRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    try:
        return service.preview_text(db, tenant=tenant, text=payload.text, source_type=_safe_source_type(payload.source_type))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview-file")
async def preview_file(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    content = await file.read()
    try:
        return service.preview_file(db, tenant=tenant, filename=file.filename, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve")
def approve_import(
    payload: SmartImportApproveRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN)),
):
    counts = {
        "approved_training_examples": 0,
        "approved_keywords": 0,
        "approved_faq_items": 0,
        "approved_intents": 0,
        "skipped_rows": 0,
        "error_count": 0,
    }
    errors: list[dict[str, Any]] = []

    for item in payload.items:
        if item.decision != "approved":
            counts["skipped_rows"] += 1
            continue
        try:
            existing_intent = bool(
                item.intent_code
                and db.query(IntentDefinition)
                .filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == _safe_intent_code(item.intent_code))
                .first()
            )
            intent = _resolve_or_create_intent(db, tenant_id=tenant.id, item=item)
            if intent and item.create_intent and not existing_intent:
                counts["approved_intents"] += 1
            intent_code = intent.code if intent else _safe_intent_code(item.intent_code)

            training_text = _safe_text(item.training_example_text or item.redacted_excerpt or item.normalized_text, 500)
            if training_text:
                db.add(
                    TrainingExample(
                        tenant_id=tenant.id,
                        raw_text=training_text,
                        normalized_text=normalize_text(training_text),
                        labeled_intent=intent_code if intent_code != "UNKNOWN" else None,
                        source="smart_import",
                    )
                )
                counts["approved_training_examples"] += 1

            if intent and item.keyword_phrases:
                existing_keywords = {
                    normalize_text(row.phrase)
                    for row in db.query(IntentKeyword)
                    .filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == intent.code)
                    .all()
                }
                for phrase in item.keyword_phrases[:10]:
                    cleaned = _safe_text(phrase, 120)
                    if not cleaned:
                        continue
                    normalized_phrase = normalize_text(cleaned)
                    if not normalized_phrase or normalized_phrase in existing_keywords:
                        continue
                    db.add(
                        IntentKeyword(
                            tenant_id=tenant.id,
                            intent_code=intent.code,
                            phrase=cleaned,
                            weight=2,
                            lang=_lang_for_text(cleaned),
                        )
                    )
                    existing_keywords.add(normalized_phrase)
                    counts["approved_keywords"] += 1

            if item.create_faq:
                faq = _create_faq_if_confirmed(db, tenant_id=tenant.id, item=item, intent=intent)
                if faq:
                    counts["approved_faq_items"] += 1
        except Exception:
            counts["error_count"] += 1
            errors.append({"row_id": item.row_id, "detail": "Row could not be imported safely"})

    audit_details = {
        "import_type": "smart_import_phase_1",
        "source_type": _safe_source_type(payload.source_type),
        "total_rows": payload.total_rows,
        **counts,
    }
    audit(db, tenant.id, ctx["user"].id, "smart_import.approved", "smart_import", None, audit_details)
    db.commit()
    return {"status": "imported", **counts, "errors": errors[:20]}


def _resolve_or_create_intent(db: Session, *, tenant_id: int, item: SmartImportApproveItem) -> IntentDefinition | None:
    code = _safe_intent_code(item.intent_code)
    if not code or code == "UNKNOWN":
        return None
    row = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.code == code).first()
    if row:
        return row
    if not item.create_intent:
        return None
    label = _safe_text(item.intent_label or code.replace("_", " ").title(), 180) or code
    topic_key = normalize_topic_key(item.faq_topic_key or code.lower())
    row = IntentDefinition(
        tenant_id=tenant_id,
        code=code,
        label=label,
        enabled=False,
        is_universal=False,
        supported_languages="both",
        response_mode="faq",
        default_response_topic_key=topic_key,
    )
    db.add(row)
    db.flush()
    return row


def _create_faq_if_confirmed(db: Session, *, tenant_id: int, item: SmartImportApproveItem, intent: IntentDefinition | None) -> FaqItem | None:
    answer_ar = _safe_text(item.faq_answer_ar, 2000)
    answer_en = _safe_text(item.faq_answer_en, 2000)
    if not answer_ar and not answer_en:
        return None
    topic_key = normalize_topic_key(item.faq_topic_key or (intent.default_response_topic_key if intent else "") or (intent.code.lower() if intent else "imported_question"))
    question = _safe_text(item.faq_question or item.redacted_excerpt, 500)
    faq = FaqItem(
        tenant_id=tenant_id,
        topic_key=topic_key,
        question_ar=question if _lang_for_text(question) == "ar" else None,
        english_question=question if _lang_for_text(question) == "en" else None,
        arabic_answer=answer_ar or answer_en or "",
        english_answer=answer_en or None,
        status="active",
    )
    db.add(faq)
    return faq


def _safe_intent_code(value: str | None) -> str:
    if not value:
        return ""
    code = normalize_intent_code(value)
    return "".join(ch for ch in code if ch.isalnum() or ch == "_")[:120]


def _safe_text(value: str | None, limit: int) -> str:
    if not value:
        return ""
    redacted = service.redact_pii(str(value))
    cleaned = " ".join(redacted.replace("\x00", " ").split())
    return cleaned[:limit]


def _safe_source_type(value: str | None) -> str:
    normalized = (value or "preview").strip().lower().replace(" ", "_")
    return normalized if normalized in {"paste", "txt", "csv", "xlsx", "preview", "whatsapp_export"} else "preview"


def _lang_for_text(value: str) -> str:
    detected = service.detect_language(value)
    return "ar" if detected in {"ar", "mixed"} else "en"
