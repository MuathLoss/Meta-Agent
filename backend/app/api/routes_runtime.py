from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.services.orchestrator import ConversationOrchestrator
from app.services.working_hours import is_inside_working_hours

router = APIRouter(prefix="/runtime", tags=["runtime"])
orchestrator = ConversationOrchestrator()


class ScenarioRequest(BaseModel):
    message: str
    customer_phone: str = "0550000000"
    channel_type: str = "whatsapp"


@router.post("/classify")
def classify(payload: ScenarioRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    result = orchestrator.preview_classification(db, tenant=tenant, text=payload.message)
    return {**result, "inside_working_hours": is_inside_working_hours(db, tenant)}


@router.post("/scenario")
def scenario(payload: ScenarioRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    decision = orchestrator.handle_inbound(db, tenant=tenant, customer_phone=payload.customer_phone, text=payload.message, channel_type=payload.channel_type, provider_message_id=None, payload_json={"source": "runtime_scenario"})
    return {"decision": decision}
