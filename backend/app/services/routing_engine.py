from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.entities import RoutingRule

@dataclass
class RouteDecision:
    action: str
    owner_role: str | None
    notify_roles: list[str]
    handoff_required: bool
    ticket_type: str | None
    priority: str
    response_behavior: str
    followup_question_ar: str | None
    followup_question_en: str | None

class RoutingEngine:
    def decide(self, db: Session, tenant_id: int, intent_code: str) -> RouteDecision:
        r = db.query(RoutingRule).filter(RoutingRule.tenant_id == tenant_id, RoutingRule.intent_code == intent_code).first()
        if not r:
            return RouteDecision("CLARIFY", "OPERATIONS_STAFF", [], False, None, "normal", "normal", None, None)

        escalation = r.escalation_json or {}
        response_behavior = str(escalation.get("response_behavior") or ("immediate_handoff" if r.handoff_required else "normal")).lower()

        if response_behavior == "offer_handoff":
            action = "OFFER_HANDOFF"
        else:
            action = "TICKET" if r.ticket_type and r.handoff_required else ("HANDOFF" if r.handoff_required else "AUTO_REPLY")

        return RouteDecision(
            action,
            r.primary_owner_role,
            r.notify_roles_json or [],
            r.handoff_required,
            r.ticket_type,
            r.priority,
            response_behavior,
            escalation.get("followup_question_ar"),
            escalation.get("followup_question_en"),
        )
