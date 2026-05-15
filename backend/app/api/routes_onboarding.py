from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.tenancy import ROLE_BUSINESS_ADMIN, get_current_tenant, require_tenant_roles
from app.models.entities import Tenant
from app.schemas.onboarding import OnboardingStepRequest, ReadinessResponse
from app.services.onboarding_service import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
service = OnboardingService()

@router.post("/step/{step}")
def save_step(step: int, payload: OnboardingStepRequest, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    if step < 1 or step > 9:
        raise HTTPException(status_code=400, detail="Step must be between 1 and 9")
    return service.save_step(db, tenant, step, payload.data)

@router.get("/readiness", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return service.readiness(db, tenant)

@router.post("/publish")
def publish(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), _: dict = Depends(require_tenant_roles(ROLE_BUSINESS_ADMIN))):
    return service.publish(db, tenant)
