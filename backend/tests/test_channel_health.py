from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from app.core.tenancy import require_internal_access
from app.services import channel_health_service as health
from app.services.tenant_channel_service import TenantChannelService
from app.services.telegram_polling_service import TelegramPollingService


def test_partial_credentials_preserved_and_client_cannot_forge_verification(db,tenant):
    svc=TenantChannelService()
    row=svc.upsert(db,tenant.id,'telegram','configured',{'enabled':True},{'bot_token':'old','secret_token':'keep-this'})
    row.public_config_json={**row.public_config_json,'connection_check':{'status':'credentials_verified'}};db.commit()
    svc.upsert(db,tenant.id,'telegram','configured',{'enabled':True,'connection_check':{'status':'credentials_verified'}},{'bot_token':'new','secret_token':''})
    assert svc.credentials(row)=={'bot_token':'new','secret_token':'keep-this'}
    assert 'connection_check' not in row.public_config_json


def test_missing_details_not_ready_or_verified(db,tenant):
    row=TenantChannelService().get(db,tenant.id,'whatsapp')
    assert health.readiness(row)['ready'] is False
    assert health.verify(row)['status']=='missing_details'
    assert 'pending' not in str(health.readiness(row))


def test_token_rejection_returns_no_secret_and_does_not_send(db,tenant,monkeypatch):
    row=TenantChannelService().upsert(db,tenant.id,'telegram','configured',{'enabled':True},{'bot_token':'never-show-this-token'})
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            calls.append(url)
            return httpx.Response(401,request=httpx.Request('GET',url),json={'description':'secret provider body'})
    monkeypatch.setattr(health.httpx,'Client',Client)
    result=health.verify(row)
    assert result['status']=='credentials_rejected'
    assert 'never-show' not in str(result) and 'secret provider' not in str(result)
    assert len(calls)==1 and calls[0].endswith('/getMe')


def test_telegram_failure_cools_down_until_credentials_change(db,tenant,monkeypatch):
    svc=TenantChannelService();svc.upsert(db,tenant.id,'telegram','configured',{'enabled':True},{'bot_token':'bad'})
    db.commit();poller=TelegramPollingService();calls=[]
    def fail(db,row,**kwargs):
        calls.append(row.id)
        response=httpx.Response(401,request=httpx.Request('GET','https://example.com'))
        raise httpx.HTTPStatusError('secret',request=response.request,response=response)
    monkeypatch.setattr(poller,'_poll_one',fail)
    assert poller.poll_once(db,disable_webhook=False)[0].error=='credentials_rejected'
    assert poller.poll_once(db,disable_webhook=False)==[]
    svc.upsert(db,tenant.id,'telegram','configured',{'enabled':True},{'bot_token':'replacement'});db.commit()
    assert poller.poll_once(db,disable_webhook=False)[0].error=='credentials_rejected'
    assert len(calls)==2


def test_customer_admin_cannot_access_internal_tools():
    with pytest.raises(HTTPException) as exc:require_internal_access(SimpleNamespace(is_platform_admin=False))
    assert exc.value.status_code==403
    assert require_internal_access(SimpleNamespace(is_platform_admin=True)).is_platform_admin


def test_phone_routing_uses_preserved_or_replaced_credentials(db,tenant):
    svc=TenantChannelService()
    row=svc.upsert(db,tenant.id,'whatsapp','configured',{'enabled':True},{'phone_number_id':'1234567890'})
    assert row.provider_channel_id=='1234567890'
    svc.upsert(db,tenant.id,'whatsapp','configured',{'enabled':True},{'access_token':'rotated-token'})
    assert row.provider_channel_id=='1234567890'


def test_rejected_telegram_account_does_not_stop_another_workspace(db,tenant,monkeypatch):
    from app.models.entities import Tenant
    from app.services.telegram_polling_service import TelegramPollResult
    svc=TenantChannelService()
    first=svc.upsert(db,tenant.id,'telegram','configured',{'enabled':True},{'bot_token':'bad'})
    other=Tenant(slug='another-workspace',display_name='Another',status='active')
    db.add(other);db.flush()
    svc.upsert(db,other.id,'telegram','configured',{'enabled':True},{'bot_token':'valid'})
    db.commit();poller=TelegramPollingService()
    def poll(db,row,**kwargs):
        if row.tenant_id==tenant.id:raise RuntimeError('Provider failed')
        return TelegramPollResult(row.tenant_id,row.id,1,1,10)
    monkeypatch.setattr(poller,'_poll_one',poll)
    results=poller.poll_once(db,disable_webhook=False)
    assert len(results)==2
    assert any(r.error=='provider_unavailable' for r in results)
    assert any(r.tenant_id==other.id and r.updates_processed==1 for r in results)
