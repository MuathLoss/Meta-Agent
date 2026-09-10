"""Encrypted drafts and conflict-safe, transactional import undo."""
from __future__ import annotations
import json
from fastapi import HTTPException
from sqlalchemy import inspect
from app.core.crypto import encrypt_dict, decrypt_dict
from app.models.entities import ImportJob, TrainingExample, IntentKeyword, FaqItem, IntentDefinition, RoutingRule
from app.services.smart_import_service import SmartImportService

MODELS = {m.__tablename__: m for m in (TrainingExample, IntentKeyword, FaqItem, IntentDefinition, RoutingRule)}
parser = SmartImportService()


def snapshot(row):
    return {c.key: getattr(row, c.key) for c in inspect(type(row)).columns if c.key not in {"created_at", "updated_at"}}


def record_change(db, changes, row, before=None):
    db.flush()
    key = (row.__tablename__, row.id)
    # One record per entity even when several approved rows enrich the same intent.
    existing = next((c for c in changes if (c['table'], c['id']) == key), None)
    if existing:
        existing['after'] = snapshot(row)
    else:
        changes.append({'table': key[0], 'id': key[1], 'before': before, 'after': snapshot(row)})


def redact(value, depth=0):
    if depth > 12:
        raise HTTPException(400, "Import draft is too deeply nested.")
    if isinstance(value, str):
        return parser.redact_pii(value)[:4000]
    if isinstance(value, list):
        if len(value) > 500:
            raise HTTPException(400, "Imports are limited to 500 messages.")
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: redact(v, depth + 1) for k, v in value.items() if k not in {"password", "token", "secret", "raw_text", "raw_upload", "access_token"}}
    return value


def get_job(db, tenant_id, job_id, revision=None):
    row = db.query(ImportJob).filter(ImportJob.tenant_id == tenant_id, ImportJob.id == job_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Import not found.")
    if revision is not None and row.revision != revision:
        raise HTTPException(409, "This import changed in another session. Reopen it before saving.")
    return row


def summary(job):
    return {'id': job.id, 'title': job.title, 'source_type': job.source_type, 'status': job.status,
            'revision': job.revision, 'row_count': job.row_count, 'result': job.result_json,
            'updated_at': job.updated_at.isoformat() if job.updated_at else None}


def detail(job):
    payload = decrypt_dict(job.encrypted_payload)
    return {**summary(job), 'preview': payload.get('preview'), 'rows': payload.get('rows', [])}


def save_draft(db, tenant_id, actor_id, data, job_id=None):
    if len(json.dumps(data, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise HTTPException(413, "Review is too large. Import up to 500 messages at a time.")
    row = get_job(db, tenant_id, job_id, data.get('revision')) if job_id else ImportJob(tenant_id=tenant_id, created_by=actor_id, revision=1, status='draft')
    if row.status != 'draft':
        raise HTTPException(409, "Only draft imports can be edited.")
    rows = data.get('rows', [])
    row.title = parser.redact_pii(data.get('title') or 'Message import')[:160]
    row.source_type = data.get('source_type', 'paste')
    row.row_count = len(rows)
    row.encrypted_payload = encrypt_dict(redact({'preview': data.get('preview'), 'rows': rows}))
    row.result_json = {}
    if job_id:
        row.revision += 1
    db.add(row)
    db.flush()
    return row


def undo(db, tenant_id, job_id, revision):
    job = get_job(db, tenant_id, job_id, revision)
    if job.status == 'undone':
        return summary(job)
    if job.status != 'imported':
        raise HTTPException(409, "Only a completed import can be undone.")
    payload = decrypt_dict(job.encrypted_payload)
    changes = payload.get('changes', [])
    resolved = []
    for change in changes:
        model = MODELS[change['table']]
        row = db.query(model).filter(model.id == change['id'], model.tenant_id == tenant_id).with_for_update().first()
        if row is None or snapshot(row) != change['after']:
            raise HTTPException(409, "An imported item was edited or removed after this import. Nothing was undone; review its changes first.")
        resolved.append((row, change))
    owned = {(c['table'], c['id']) for c in changes}
    for row, change in resolved:
        if isinstance(row, IntentDefinition) and change['before'] is None:
            for model, column in ((IntentKeyword, 'intent_code'), (RoutingRule, 'intent_code'), (TrainingExample, 'labeled_intent')):
                refs = db.query(model).filter(model.tenant_id == tenant_id, getattr(model, column) == row.code).all()
                if any((r.__tablename__, r.id) not in owned for r in refs):
                    raise HTTPException(409, "A new topic is used by changes outside this import. Nothing was undone.")
        if isinstance(row, FaqItem) and change['before'] is None:
            refs = db.query(IntentDefinition).filter(IntentDefinition.tenant_id == tenant_id, IntentDefinition.default_response_topic_key == row.topic_key).all()
            other_answers = db.query(FaqItem).filter(FaqItem.tenant_id == tenant_id, FaqItem.topic_key == row.topic_key, FaqItem.id != row.id).count()
            if refs and not other_answers and any((r.__tablename__, r.id) not in owned for r in refs):
                raise HTTPException(409, "This answer is used by another topic. Nothing was undone.")
    # Children first, then newly created parent intents.
    resolved.sort(key=lambda pair: isinstance(pair[0], IntentDefinition))
    for row, change in resolved:
        if change['before'] is None:
            db.delete(row)
        else:
            for key, value in change['before'].items():
                if key not in {'id', 'tenant_id'}:
                    setattr(row, key, value)
    db.flush()
    job.status = 'undone'
    job.revision += 1
    return summary(job)
