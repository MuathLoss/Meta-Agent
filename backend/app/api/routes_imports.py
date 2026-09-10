from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.routes_config import audit, normalize_intent_code, normalize_topic_key
from app.schemas.import_drafts import ImportDraftRequest
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import FaqItem, IntentDefinition, IntentKeyword, Tenant, TrainingExample, RoutingRule, ImportJob
from app.core.crypto import encrypt_dict, decrypt_dict
from app.services import import_job_service as jobs
from app.services.onboarding_service import default_routing_payload
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
    decision: Literal["approved", "pending", "rejected"] = "approved"
    redacted_excerpt: str = Field(default="", max_length=500)
    normalized_text: str = Field(default="", max_length=500)
    intent_code: str | None = None
    intent_label: str | None = None
    create_intent: bool = False
    training_example_text: str | None = None
    keyword_phrases: list[str] = Field(default_factory=list, max_length=10)
    create_faq: bool = False
    routing_behavior: Literal["normal", "offer_handoff", "immediate_handoff", "clarify"] | None = None
    apply_routing: bool = False
    faq_topic_key: str | None = None
    faq_question: str | None = None
    faq_answer_ar: str | None = None
    faq_answer_en: str | None = None


class SmartImportApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int | None = None
    revision: int | None = None
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
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        return service.preview_file(db, tenant=tenant, filename=file.filename, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve")
def approve_import(payload: SmartImportApproveRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    if payload.job_id:
        job = jobs.get_job(db, tenant.id, payload.job_id)
        if job.status == "imported":
            return {**job.result_json, "job_id": job.id, "revision": job.revision}
        if payload.revision is None or job.revision != payload.revision or job.status != "draft":
            raise HTTPException(409, "Reopen the latest draft before importing.")
    else:
        job = ImportJob(tenant_id=tenant.id, created_by=ctx["user"].id, title="Message import", source_type=_safe_source_type(payload.source_type), status="draft", revision=1, row_count=len(payload.items), encrypted_payload=encrypt_dict({}))
        db.add(job)
        db.flush()
    changes = []
    counts = {key: 0 for key in ("approved_training_examples", "approved_keywords", "approved_faq_items", "approved_intents", "approved_routing_rules", "skipped_rows", "skipped_duplicates", "error_count")}
    routing_choices = {}
    for item in payload.items:
        if item.decision != "approved":
            counts["skipped_rows"] += 1
            continue
        code = _safe_intent_code(item.intent_code)
        intent_before = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant.id, IntentDefinition.code == code).first()
        intent = _resolve_or_create_intent(db, tenant_id=tenant.id, item=item)
        if intent and not intent_before:
            jobs.record_change(db, changes, intent)
            counts["approved_intents"] += 1
        training_text = _safe_text(item.training_example_text or item.redacted_excerpt or item.normalized_text, 500)
        label = intent.code if intent else None
        if training_text:
            normalized = normalize_text(training_text)
            duplicate = db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id, TrainingExample.normalized_text == normalized, TrainingExample.labeled_intent == label).first()
            if duplicate:
                counts["skipped_duplicates"] += 1
            else:
                row = TrainingExample(tenant_id=tenant.id, raw_text=training_text, normalized_text=normalized, labeled_intent=label, source="smart_import")
                db.add(row); jobs.record_change(db, changes, row)
                counts["approved_training_examples"] += 1
        if intent:
            existing = {normalize_text(r.phrase) for r in db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.intent_code == intent.code).all()}
            for phrase in item.keyword_phrases:
                cleaned = _safe_text(phrase, 120)
                normalized = normalize_text(cleaned)
                if not cleaned or not service._useful_keyword(cleaned):
                    continue
                if normalized in existing:
                    counts["skipped_duplicates"] += 1
                    continue
                row = IntentKeyword(tenant_id=tenant.id, intent_code=intent.code, phrase=cleaned, weight=2, lang=_lang_for_text(cleaned))
                db.add(row); jobs.record_change(db, changes, row)
                existing.add(normalized); counts["approved_keywords"] += 1
        if item.create_faq:
            topic = normalize_topic_key(item.faq_topic_key or (intent.default_response_topic_key if intent else "") or (code.lower() if code else "imported_question"))
            duplicate = db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == topic).first()
            if duplicate:
                counts["skipped_duplicates"] += 1
            else:
                faq = _create_faq_if_confirmed(db, tenant_id=tenant.id, item=item, intent=intent)
                if faq:
                    jobs.record_change(db, changes, faq); counts["approved_faq_items"] += 1
        if item.apply_routing:
            if not intent or item.routing_behavior not in {"normal", "offer_handoff", "immediate_handoff"}:
                raise HTTPException(400, "Choose an existing or newly created topic before saving handoff behavior.")
            if code in routing_choices and routing_choices[code] != item.routing_behavior:
                raise HTTPException(400, "Suggestions for the same topic have conflicting handoff choices.")
            routing_choices[code] = item.routing_behavior
            if code in {"COMPLAINT", "HUMAN_REQUEST", "PAYMENT_TRANSFER", "CERTIFICATES"} and item.routing_behavior != "immediate_handoff":
                raise HTTPException(400, "Protected topics must keep immediate handoff.")
            rule = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant.id, RoutingRule.intent_code == code).first()
            before = jobs.snapshot(rule) if rule else None
            if not rule:
                rule = RoutingRule(tenant_id=tenant.id, **default_routing_payload(intent))
                db.add(rule)
            behavior = item.routing_behavior
            rule.escalation_json = {**(rule.escalation_json or {}), "response_behavior": behavior}
            rule.handoff_required = behavior == "immediate_handoff"
            if behavior == "normal":
                rule.primary_owner_role, rule.ticket_type = "BOT", None
            elif rule.primary_owner_role == "BOT":
                rule.primary_owner_role = "OPERATIONS_STAFF"
            if code == "COMPLAINT":
                rule.priority, rule.ticket_type = "high", "complaint"
            jobs.record_change(db, changes, rule, before)
            counts["approved_routing_rules"] = len(routing_choices)
    result = {"status": "imported", **counts, "errors": []}
    stored = decrypt_dict(job.encrypted_payload)
    stored["changes"] = changes
    job.encrypted_payload = encrypt_dict(stored)
    job.result_json, job.status = result, "imported"
    job.revision += 1
    audit(db, tenant.id, ctx["user"].id, "smart_import.approved", "smart_import", str(job.id), {"import_type": "smart_import", "source_type": _safe_source_type(payload.source_type), "total_rows": payload.total_rows, **counts})
    db.commit()
    return {**result, "job_id": job.id, "revision": job.revision}


class ImportRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


@router.get("/jobs")
def list_import_jobs(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return [jobs.summary(row) for row in db.query(ImportJob).filter(ImportJob.tenant_id == tenant.id).order_by(ImportJob.updated_at.desc(), ImportJob.id.desc()).limit(100)]


@router.post("/jobs")
def create_import_job(payload: ImportDraftRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    row = jobs.save_draft(db, tenant.id, ctx["user"].id, payload.model_dump())
    db.commit()
    return jobs.detail(row)


@router.get("/jobs/{job_id}")
def get_import_job(job_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return jobs.detail(jobs.get_job(db, tenant.id, job_id))


@router.put("/jobs/{job_id}")
def update_import_job(job_id: int, payload: ImportDraftRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    if payload.revision is None:
        raise HTTPException(400, "Draft revision is required.")
    row = jobs.save_draft(db, tenant.id, ctx["user"].id, payload.model_dump(), job_id)
    db.commit()
    return jobs.detail(row)


@router.post("/jobs/{job_id}/undo")
def undo_import_job(job_id: int, payload: ImportRevisionRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), ctx: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    result = jobs.undo(db, tenant.id, job_id, payload.revision)
    audit(db, tenant.id, ctx["user"].id, "smart_import.undone", "smart_import", str(job_id), {"job_id": job_id})
    db.commit()
    return result


@router.post("/jobs/{job_id}/assist")
def assist_import_job(job_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    from app.services.import_grouping_service import group_messages
    job = jobs.get_job(db, tenant.id, job_id)
    if job.status != "draft":
        raise HTTPException(409, "Only draft reviews can be grouped.")
    enforce_rate_limit(f"import_assist:{tenant.id}", max_requests=10, window_seconds=60)
    return group_messages(db, tenant, jobs.detail(job)["rows"])


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
