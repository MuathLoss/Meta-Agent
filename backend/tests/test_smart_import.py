from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes_imports import SmartImportApproveItem, SmartImportApproveRequest, SmartPreviewTextRequest, approve_import
from app.models.entities import AuditLog, FaqItem, IntentKeyword, Tenant, TrainingExample
from app.services.smart_import_service import SmartImportService


def test_preview_text_parses_messy_whatsapp_and_redacts_pii(db, tenant):
    text = """
[5/20/26, 9:01 AM] Customer One: السلام عليكم
[5/20/26, 9:02 AM] Customer One: كم السعر؟
هذا سطر ثاني
[5/20/26, 9:03 AM] Customer One: my email is customer@example.com and phone +966 55 123 4567
[5/20/26, 9:04 AM] Customer One: <Media omitted>
"""

    result = SmartImportService().preview_text(db, tenant=tenant, text=text, source_type="paste")

    assert result["total_rows"] == 3
    assert result["previewed_rows"] == 3
    joined = " ".join(row["redacted_excerpt"] for row in result["rows"])
    assert "customer@example.com" not in joined
    assert "+966" not in joined
    assert "[email]" in joined
    assert "[phone]" in joined
    assert any(row["suggested_intent"]["code"] == "PRICING" for row in result["rows"])


def test_preview_csv_one_column_messages_and_dedupes(db, tenant):
    content = "message\nhow much is the price?\nhow much is the price?\nI want a human\n".encode()

    result = SmartImportService().preview_file(db, tenant=tenant, filename="messages.csv", content=content)

    assert result["source_type"] == "csv"
    assert result["previewed_rows"] == 2
    assert result["duplicate_rows"] == 1
    assert {row["suggested_intent"]["code"] for row in result["rows"]} >= {"PRICING", "HUMAN_REQUEST"}


def test_preview_txt_upload_detects_protected_payment_and_complaint(db, tenant):
    content = "I paid yesterday but have a payment problem\nعندي شكوى من الخدمة\n".encode()

    result = SmartImportService().preview_file(db, tenant=tenant, filename="chat.txt", content=content)

    intents = [row["suggested_intent"]["code"] for row in result["rows"]]
    assert "PAYMENT_TRANSFER" in intents
    assert "COMPLAINT" in intents
    protected = [row for row in result["rows"] if row["suggested_intent"]["code"] == "COMPLAINT"][0]
    assert "protected_handoff_intent" in protected["warnings"]
    assert protected["routing_hint"]["behavior"] == "immediate_handoff"


def test_preview_xlsx_upload_when_openpyxl_available(db, tenant):
    openpyxl = pytest.importorskip("openpyxl")
    from io import BytesIO

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["message"])
    sheet.append(["where are you located"])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    result = SmartImportService().preview_file(db, tenant=tenant, filename="messages.xlsx", content=buffer.getvalue())

    assert result["source_type"] == "xlsx"
    assert result["previewed_rows"] == 1
    assert result["rows"][0]["suggested_intent"]["code"] == "LOCATION"


def test_preview_rejects_tenant_id_in_text_payload():
    with pytest.raises(ValidationError):
        SmartPreviewTextRequest(text="hello", tenant_id=123)  # type: ignore


def test_approval_writes_only_selected_rows_and_stays_tenant_scoped(db, tenant):
    other = Tenant(slug="other-smart-import", display_name="Other", timezone="Asia/Riyadh", default_lang="en", status="active")
    db.add(other)
    db.commit()

    payload = SmartImportApproveRequest(
        source_type="paste",
        total_rows=2,
        items=[
            SmartImportApproveItem(
                row_id="row_1",
                decision="approved",
                redacted_excerpt="what is the price",
                training_example_text="what is the price",
                intent_code="PRICING",
                keyword_phrases=["price question"],
                create_faq=True,
                faq_topic_key="pricing_followup",
                faq_question="what is the price",
                faq_answer_en="Confirmed answer from admin",
            ),
            SmartImportApproveItem(row_id="row_2", decision="rejected", redacted_excerpt="ignore me", intent_code="PRICING"),
        ],
    )

    result = approve_import(payload, tenant=tenant, db=db, ctx={"user": type("User", (), {"id": 10})()})

    assert result["approved_training_examples"] == 1
    assert result["approved_keywords"] == 1
    assert result["approved_faq_items"] == 1
    assert result["skipped_rows"] == 1
    assert db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id).count() == 1
    assert db.query(TrainingExample).filter(TrainingExample.tenant_id == other.id).count() == 0
    assert db.query(IntentKeyword).filter(IntentKeyword.tenant_id == tenant.id, IntentKeyword.phrase == "price question").count() == 1
    assert db.query(FaqItem).filter(FaqItem.tenant_id == tenant.id, FaqItem.topic_key == "pricing_followup").count() == 1


def test_approval_redacts_pii_and_audit_logs_counts_only(db, tenant):
    payload = SmartImportApproveRequest(
        source_type="paste",
        total_rows=1,
        items=[
            SmartImportApproveItem(
                row_id="row_1",
                decision="approved",
                redacted_excerpt="email customer@example.com phone +966551234567",
                training_example_text="email customer@example.com phone +966551234567",
                intent_code="PRICING",
            )
        ],
    )

    approve_import(payload, tenant=tenant, db=db, ctx={"user": type("User", (), {"id": 11})()})

    example = db.query(TrainingExample).filter(TrainingExample.tenant_id == tenant.id, TrainingExample.source == "smart_import").one()
    assert "customer@example.com" not in example.raw_text
    assert "+966" not in example.raw_text
    audit = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id, AuditLog.action == "smart_import.approved").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    details = audit.details_json
    assert details["approved_training_examples"] == 1
    assert "customer@example.com" not in str(details)
    assert "+966" not in str(details)
