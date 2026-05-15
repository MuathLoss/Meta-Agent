from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.schemas.channels import ChannelConfigRequest, ChannelConfigResponse
from app.services.tenant_channel_service import DuplicateProviderChannelError, TenantChannelService, UnsafePublicConfigError, sanitize_public_config

router = APIRouter(prefix="/channels", tags=["channels"])
service = TenantChannelService()

def ser(r):
    return ChannelConfigResponse(
        channel_type=r.channel_type,
        status=r.status,
        public_config=sanitize_public_config(r.public_config_json),
        provider_channel_id=r.provider_channel_id,
        provider_account_id=r.provider_account_id,
        has_credentials=bool(r.encrypted_credentials),
    )

@router.get("")
def list_channels(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return [ser(r) for r in service.list(db, tenant.id)]

@router.put("/{channel_type}/settings", response_model=ChannelConfigResponse)
def update(channel_type: str, payload: ChannelConfigRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    try:
        row = service.upsert(db, tenant.id, channel_type, payload.status, payload.public_config, payload.credentials)
    except UnsafePublicConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateProviderChannelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ser(row)
