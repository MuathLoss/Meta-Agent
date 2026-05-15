from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Broadcast, BroadcastRecipient, Conversation, Customer, Tenant
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.outbound_service import OutboundService


@dataclass
class BroadcastSendResult:
    broadcast_id: int
    status: str
    total_recipients: int
    created_recipients: int
    failed_recipients: int = 0
    sent_recipients: int = 0
    channel_type: str | None = None


class BroadcastService:
    """Tenant-scoped broadcast execution."""

    def __init__(self) -> None:
        self.outbound_service = OutboundService()
        self.customer_identity = CustomerChannelIdentityService()

    def _resolve_audience(self, db: Session, tenant: Tenant, broadcast: Broadcast) -> list[Customer]:
        payload = broadcast.payload_json or {}
        explicit_ids = payload.get("recipient_customer_ids") or []
        q = db.query(Customer).filter(Customer.tenant_id == tenant.id, Customer.opt_in.is_(True))
        if broadcast.audience_type == "selected" and explicit_ids:
            q = q.filter(Customer.id.in_([int(x) for x in explicit_ids]))
        return q.order_by(Customer.id.asc()).all()

    def _resolve_text(self, broadcast: Broadcast) -> str:
        payload = broadcast.payload_json or {}
        for key in ["message_text", "message", "body", "text", "content"]:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if broadcast.template_ref and broadcast.template_ref.strip():
            return broadcast.template_ref.strip()
        return broadcast.title.strip()

    def _resolve_conversation(self, db: Session, *, tenant_id: int, customer_id: int, channel_type: str) -> Conversation:
        row = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant_id,
                Conversation.customer_id == customer_id,
                Conversation.channel_type == channel_type,
                Conversation.state != "CLOSED",
            )
            .order_by(Conversation.updated_at.desc())
            .first()
        )
        if row:
            return row
        row = Conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_type=channel_type,
            state="BOT_ACTIVE",
            owner_type="BOT",
            owner_ref="BROADCAST",
            last_intent="BROADCAST",
        )
        db.add(row)
        db.flush()
        return row

    def send_now(self, db: Session, *, tenant: Tenant, broadcast: Broadcast, actor_user_id: int | None = None) -> BroadcastSendResult:
        customers = self._resolve_audience(db, tenant, broadcast)
        requested_channel_type = broadcast.channel_type
        if not customers:
            broadcast.status = "failed"
            db.add(AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="broadcast.failed",
                entity_type="broadcast",
                entity_id=str(broadcast.id),
                details_json={"reason": "no_opt_in_recipients"},
            ))
            db.flush()
            raise ValueError("No opt-in recipients found for this tenant broadcast")

        message_text = self._resolve_text(broadcast)
        if not message_text:
            broadcast.status = "failed"
            db.add(AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="broadcast.failed",
                entity_type="broadcast",
                entity_id=str(broadcast.id),
                details_json={"reason": "empty_message_text"},
            ))
            db.flush()
            raise ValueError("Broadcast message text is empty")

        resolved_channel = self.outbound_service.resolve_send_channel(
            db,
            tenant_id=tenant.id,
            preferred_channel_type=requested_channel_type,
        )
        if not resolved_channel:
            broadcast.status = "failed"
            db.add(AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="broadcast.failed",
                entity_type="broadcast",
                entity_id=str(broadcast.id),
                details_json={"reason": "no_send_capable_channel", "requested_channel_type": requested_channel_type},
            ))
            db.flush()
            raise ValueError("No connected send-capable channel is enabled for this tenant")

        customers = [customer for customer in customers if self.customer_identity.is_reachable(customer, resolved_channel.channel_type)]
        if not customers:
            broadcast.status = "failed"
            db.add(AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="broadcast.failed",
                entity_type="broadcast",
                entity_id=str(broadcast.id),
                details_json={"reason": "no_reachable_recipients", "resolved_channel_type": resolved_channel.channel_type},
            ))
            db.flush()
            raise ValueError("No reachable recipients are available for this tenant broadcast")

        broadcast.status = "sending"
        broadcast.channel_type = resolved_channel.channel_type
        db.add(AuditLog(
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            action="broadcast.send_started",
            entity_type="broadcast",
            entity_id=str(broadcast.id),
            details_json={"requested_channel_type": requested_channel_type, "resolved_channel_type": resolved_channel.channel_type, "audience_type": broadcast.audience_type},
        ))
        db.flush()
        created = 0
        sent = 0
        failed = 0
        now = datetime.now(timezone.utc)
        for customer in customers:
            conversation = self._resolve_conversation(
                db,
                tenant_id=tenant.id,
                customer_id=customer.id,
                channel_type=resolved_channel.channel_type,
            )
            outbound = self.outbound_service.send_or_store(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                channel_type=resolved_channel.channel_type,
                destination=self.customer_identity.delivery_address(customer, resolved_channel.channel_type),
                text=message_text,
                intent_code="BROADCAST",
            )
            payload = outbound.payload_json or {}
            send_status = str(payload.get("send_status") or "send_failed")
            recipient_status = "sent" if send_status == "sent" else "failed"
            if recipient_status == "sent":
                self.customer_identity.mark_reachable(customer, resolved_channel.channel_type)
                sent += 1
            else:
                if self.outbound_service.is_unreachable_recipient_failure(channel_type=resolved_channel.channel_type, payload_json=payload):
                    self.customer_identity.mark_unreachable(customer, resolved_channel.channel_type)
                    db.add(AuditLog(
                        tenant_id=tenant.id,
                        actor_user_id=actor_user_id,
                        action="broadcast.recipient_unreachable",
                        entity_type="customer",
                        entity_id=str(customer.id),
                        details_json={"broadcast_id": broadcast.id, "channel_type": resolved_channel.channel_type, "error": payload.get("error")},
                    ))
                failed += 1
            db.add(BroadcastRecipient(
                tenant_id=tenant.id,
                broadcast_id=broadcast.id,
                customer_id=customer.id,
                status=recipient_status,
                provider_message_id=outbound.provider_message_id,
                delivered_at=now if recipient_status == "sent" else None,
            ))
            created += 1

        broadcast.status = "sent" if failed == 0 else "failed"
        db.add(AuditLog(
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            action="broadcast.sent" if failed == 0 else "broadcast.failed",
            entity_type="broadcast",
            entity_id=str(broadcast.id),
            details_json={
                "audience_type": broadcast.audience_type,
                "requested_channel_type": requested_channel_type,
                "resolved_channel_type": resolved_channel.channel_type,
                "created_recipients": created,
                "sent_recipients": sent,
                "failed_recipients": failed,
                "total_recipients": len(customers),
            },
        ))
        db.flush()
        return BroadcastSendResult(
            broadcast_id=broadcast.id,
            status=broadcast.status,
            total_recipients=len(customers),
            created_recipients=created,
            failed_recipients=failed,
            sent_recipients=sent,
            channel_type=resolved_channel.channel_type,
        )

    def schedule(self, db: Session, *, tenant: Tenant, broadcast: Broadcast, schedule_at: datetime, actor_user_id: int | None = None) -> BroadcastSendResult:
        broadcast.schedule_at = schedule_at
        broadcast.status = "scheduled"
        db.add(AuditLog(
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            action="broadcast.scheduled",
            entity_type="broadcast",
            entity_id=str(broadcast.id),
            details_json={"schedule_at": schedule_at.isoformat()},
        ))
        db.flush()
        return BroadcastSendResult(broadcast_id=broadcast.id, status=broadcast.status, total_recipients=0, created_recipients=0, channel_type=broadcast.channel_type)

    def cancel(self, db: Session, *, tenant: Tenant, broadcast: Broadcast, actor_user_id: int | None = None) -> BroadcastSendResult:
        if broadcast.status == "sent":
            return BroadcastSendResult(broadcast_id=broadcast.id, status=broadcast.status, total_recipients=0, created_recipients=0, channel_type=broadcast.channel_type)
        broadcast.status = "cancelled"
        db.add(AuditLog(
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            action="broadcast.cancelled",
            entity_type="broadcast",
            entity_id=str(broadcast.id),
            details_json={},
        ))
        db.flush()
        return BroadcastSendResult(broadcast_id=broadcast.id, status=broadcast.status, total_recipients=0, created_recipients=0, channel_type=broadcast.channel_type)

    def process_due_broadcasts(self, db: Session, *, now: datetime | None = None) -> list[BroadcastSendResult]:
        current = now or datetime.now(timezone.utc)
        rows = db.query(Broadcast).filter(
            Broadcast.status == "scheduled",
            Broadcast.schedule_at.is_not(None),
            Broadcast.schedule_at <= current,
        ).all()
        results: list[BroadcastSendResult] = []
        for broadcast in rows:
            tenant = db.get(Tenant, broadcast.tenant_id)
            if not tenant:
                continue
            try:
                results.append(self.send_now(db, tenant=tenant, broadcast=broadcast, actor_user_id=None))
            except ValueError:
                results.append(
                    BroadcastSendResult(
                        broadcast_id=broadcast.id,
                        status=broadcast.status,
                        total_recipients=0,
                        created_recipients=0,
                        failed_recipients=0,
                        sent_recipients=0,
                        channel_type=broadcast.channel_type,
                    )
                )
        return results
