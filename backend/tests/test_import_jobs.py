from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api.routes_imports import SmartImportApproveItem, SmartImportApproveRequest, approve_import
from app.models.entities import IntentDefinition, TrainingExample, IntentKeyword, RoutingRule
from app.services import import_job_service as jobs
from app.services.smart_import_service import SmartImportService
from app.services import import_grouping_service as grouping


def draft(db, tenant):
    preview = SmartImportService().preview_text(db, tenant=tenant, text='What is the price?\nCustomer: customer@example.com', source_type='paste')
    return jobs.save_draft(db, tenant.id, None, {'title':'September review','source_type':'paste','preview':preview,'rows':preview['rows']})


def apply(db, tenant, job, **values):
    item = SmartImportApproveItem(row_id='row_1', intent_code='PRICING', training_example_text='What is the latest course price?', keyword_phrases=['latest course price'], **values)
    payload = SmartImportApproveRequest(job_id=job.id, revision=job.revision, items=[item])
    return approve_import(payload, tenant=tenant, db=db, ctx={'user':SimpleNamespace(id=None)})


def test_draft_encrypted_resumable_revision_and_tenant_scoped(db, tenant):
    job=draft(db,tenant);db.commit()
    assert 'customer@example.com' not in job.encrypted_payload
    loaded=jobs.detail(job)
    assert '[email]' in str(loaded['rows'])
    assert loaded['rows'][0]['decision']=='pending'
    assert 'changes' not in loaded
    with pytest.raises(HTTPException) as exc:jobs.get_job(db,tenant.id+500,job.id)
    assert exc.value.status_code==404
    data={'revision':job.revision,'title':'Changed','rows':loaded['rows'],'preview':loaded['preview']}
    jobs.save_draft(db,tenant.id,None,data,job.id)
    assert job.revision==2
    with pytest.raises(HTTPException) as exc:jobs.save_draft(db,tenant.id,None,data,job.id)
    assert exc.value.status_code==409


def test_import_idempotent_undo_restores_routing_and_keeps_preexisting_data(db, tenant):
    job=draft(db,tenant)
    rule=db.query(RoutingRule).filter_by(tenant_id=tenant.id,intent_code='PRICING').one()
    before=jobs.snapshot(rule);keywords=db.query(IntentKeyword).count()
    result=apply(db,tenant,job,apply_routing=True,routing_behavior='immediate_handoff')
    assert result['approved_routing_rules']==1 and rule.handoff_required
    assert apply(db,tenant,job)==result
    assert db.query(TrainingExample).count()==1
    undo=jobs.undo(db,tenant.id,job.id,job.revision);db.commit()
    assert undo['status']=='undone'
    assert db.query(TrainingExample).count()==0
    assert db.query(IntentKeyword).count()==keywords
    assert jobs.snapshot(rule)==before
    assert db.query(IntentDefinition).filter_by(code='PRICING').count()==1


def test_undo_blocks_all_changes_when_one_item_was_edited(db, tenant):
    job=draft(db,tenant);apply(db,tenant,job)
    row=db.query(TrainingExample).one();row.raw_text='Later manual edit';db.commit()
    keywords=db.query(IntentKeyword).count()
    with pytest.raises(HTTPException) as exc:jobs.undo(db,tenant.id,job.id,job.revision)
    assert exc.value.status_code==409
    assert db.query(IntentKeyword).count()==keywords and job.status=='imported'


def test_routing_requires_explicit_opt_in(db,tenant):
    job=draft(db,tenant);rule=db.query(RoutingRule).filter_by(intent_code='PRICING').one()
    apply(db,tenant,job,routing_behavior='immediate_handoff')
    assert not rule.handoff_required


def test_protected_routing_cannot_be_downgraded(db,tenant):
    job=draft(db,tenant)
    item=SmartImportApproveItem(row_id='a',intent_code='COMPLAINT',routing_behavior='normal',apply_routing=True)
    with pytest.raises(HTTPException) as exc:
        approve_import(SmartImportApproveRequest(job_id=job.id,revision=job.revision,items=[item]),tenant=tenant,db=db,ctx={'user':SimpleNamespace(id=None)})
    assert exc.value.status_code==400
    db.rollback()
    assert db.query(RoutingRule).filter_by(intent_code='COMPLAINT').one().handoff_required


def test_grouping_falls_back_and_does_not_change_review(db,tenant,monkeypatch):
    monkeypatch.setattr(grouping.settings,'ollama_enabled',False)
    job=draft(db,tenant);before=job.encrypted_payload
    result=grouping.group_messages(db,tenant,jobs.detail(job)['rows'])
    assert result['assisted'] is False
    assert sum(len(g['row_ids']) for g in result['groups'])==job.row_count
    assert job.encrypted_payload==before
    monkeypatch.setattr(grouping.settings,'ollama_enabled',True)
    monkeypatch.setattr(grouping.httpx,'Client',lambda **kwargs: (_ for _ in ()).throw(RuntimeError('unavailable')))
    assert grouping.group_messages(db,tenant,jobs.detail(job)['rows'])['assisted'] is False


def test_preview_validates_for_saved_reviews(db,tenant):
    from app.schemas.import_drafts import ImportDraftRequest
    from pydantic import ValidationError
    preview=SmartImportService().preview_text(db,tenant=tenant,text='What is the price?',source_type='paste')
    payload=ImportDraftRequest(preview=preview,rows=preview['rows'])
    assert payload.rows[0].editable.apply_routing is False
    with pytest.raises(ValidationError):ImportDraftRequest(preview=preview,rows=[{'row_id':'broken'}])
    with pytest.raises(ValidationError):ImportDraftRequest(preview=preview,rows=preview['rows']*2)
