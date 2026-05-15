from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from app.models.entities import AuditLog, Conversation, Customer, Message, Tenant, Ticket
from app.services.customer_channel_identity_service import CustomerChannelIdentityService
from app.services.intent_rules import IntentRules, normalize_text
from app.services.language_service import LanguageService
from app.services.ollama_intelligence_service import OllamaIntelligenceService
from app.services.outbound_service import OutboundService
from app.services.response_engine import ResponseEngine
from app.services.routing_engine import RoutingEngine
from app.services.working_hours import is_inside_working_hours, should_auto_reply_out_of_hours

class ConversationOrchestrator:
    SPAM_HANDOFF_THRESHOLD = 5
    SPAM_HANDOFF_COOLDOWN_SECONDS = 60
    HANDOFF_AUTO_RETURN_SECONDS = 60
    HANDOFF_CONFIRMATION_STATE = "WAITING_FOR_HANDOFF_CONFIRMATION"

    def __init__(self):
        self.intent_rules = IntentRules()
        self.ollama_intelligence = OllamaIntelligenceService()
        self.response_engine = ResponseEngine()
        self.routing_engine = RoutingEngine()
        self.outbound_service = OutboundService()
        self.customer_identity = CustomerChannelIdentityService()
        self.language_service = LanguageService()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _add_audit(self, db: Session, *, tenant_id: int, action: str, entity_id: int, details: dict | None = None) -> None:
        db.add(AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,
            action=action,
            entity_type="conversation",
            entity_id=str(entity_id),
            details_json=details or {},
        ))

    def _normalized(self, text: str) -> str:
        return normalize_text(text)

    def _is_return_to_bot_request(self, text: str) -> bool:
        normalized = self._normalized(text)
        return normalized in {"رجعني للبوت", "ابغي البوت", "ابغى البوت", "ابدا من جديد", "ابدأ من جديد", "bot", "menu"}

    def _is_explicit_human_request(self, text: str) -> bool:
        normalized = self._normalized(text)
        return normalized in {"ابغي موظف", "ابغى موظف", "اكلم موظف", "ابغي انسان", "ابغى انسان", "ابغى موظف", "human", "representative"}

    def _is_explicit_complaint(self, text: str) -> bool:
        normalized = self._normalized(text)
        complaint_phrases = ["عندي شكوي", "شكوي", "شكوى", "ابي اشتكي", "ابغى اشتكي", "ارفع شكوي", "ارفع شكوى", "complaint"]
        return any(self._normalized(phrase) in normalized for phrase in complaint_phrases)

    def _is_confirmation_yes(self, text: str) -> bool:
        normalized = self._normalized(text)
        return normalized in {"yes", "yeah", "y", "نعم", "ايه", "يب", "تمام", "ok", "okay", "ابغى موظف", "ابغي موظف"}

    def _is_confirmation_no(self, text: str) -> bool:
        normalized = self._normalized(text)
        return normalized in {"no", "لا", "ما يحتاج", "شكرا", "no thanks"}

    def _conversation_metadata(self, conversation: Conversation) -> dict:
        if not isinstance(conversation.metadata_json, dict):
            return {}
        return dict(conversation.metadata_json)

    def _clear_pending_handoff_confirmation(self, conversation: Conversation) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata.pop("pending_handoff_confirmation", None)
        conversation.metadata_json = metadata

    def _mark_open_complaint(self, conversation: Conversation) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata["has_open_complaint"] = True
        conversation.metadata_json = metadata

    def _clear_open_complaint(self, conversation: Conversation) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata.pop("has_open_complaint", None)
        conversation.metadata_json = metadata

    def _set_last_customer_language(self, conversation: Conversation, lang: str) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata["last_customer_language"] = lang
        conversation.metadata_json = metadata

    def _set_handoff_timeout(self, conversation: Conversation) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata["handoff_auto_return_at"] = (
            self._now() + timedelta(seconds=self.HANDOFF_AUTO_RETURN_SECONDS)
        ).isoformat()
        conversation.metadata_json = metadata

    def _clear_handoff_timeout(self, conversation: Conversation) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata.pop("handoff_auto_return_at", None)
        conversation.metadata_json = metadata

    def _handoff_timeout_expired(self, conversation: Conversation) -> bool:
        value = self._conversation_metadata(conversation).get("handoff_auto_return_at")
        if not isinstance(value, str):
            return False
        try:
            auto_return_at = datetime.fromisoformat(value)
        except ValueError:
            return False
        if auto_return_at.tzinfo is None:
            auto_return_at = auto_return_at.replace(tzinfo=timezone.utc)
        return auto_return_at <= self._now()

    def _set_pending_handoff_confirmation(
        self,
        conversation: Conversation,
        *,
        intent_code: str,
        owner_role: str,
        ticket_type: str | None,
        priority: str,
        notify_roles: list[str],
        followup_question_ar: str | None,
        followup_question_en: str | None,
    ) -> None:
        metadata = self._conversation_metadata(conversation)
        metadata["pending_handoff_confirmation"] = {
            "intent_code": intent_code,
            "owner_role": owner_role,
            "ticket_type": ticket_type or "handoff",
            "priority": priority,
            "notify_roles": notify_roles,
            "followup_question_ar": followup_question_ar,
            "followup_question_en": followup_question_en,
            "clarification_count": 0,
            "offered_at": self._now().isoformat(),
        }
        conversation.metadata_json = metadata

    def _pending_handoff_confirmation(self, conversation: Conversation) -> dict | None:
        metadata = self._conversation_metadata(conversation)
        pending = metadata.get("pending_handoff_confirmation")
        return pending if isinstance(pending, dict) else None

    def _handoff_followup_text(self, tenant: Tenant, pending: dict, route, preferred_lang: str | None) -> str:
        return self.response_engine.select_localized_text(
            {
                "ar": str(pending["followup_question_ar"]) if pending.get("followup_question_ar") else route.followup_question_ar,
                "en": str(pending["followup_question_en"]) if pending.get("followup_question_en") else route.followup_question_en,
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or self.response_engine.select_localized_text(
            {
                "ar": "هل تحتاج تفاصيل إضافية من موظف؟",
                "en": "Would you like me to direct you to a human agent for extra help?",
            },
            preferred_lang=preferred_lang,
            tenant_default_lang=tenant.default_lang,
        ) or "Would you like me to direct you to a human agent for extra help?"

    def _create_or_update_open_ticket(
        self,
        db: Session,
        *,
        tenant_id: int,
        conversation_id: int,
        ticket_type: str,
        priority: str,
        assigned_to: str | None,
        details_json: dict,
    ) -> Ticket:
        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.tenant_id == tenant_id,
                Ticket.conversation_id == conversation_id,
                Ticket.ticket_type == ticket_type,
                Ticket.status == "open",
            )
            .order_by(Ticket.id.desc())
            .first()
        )
        if ticket:
            ticket.priority = priority
            ticket.assigned_to = assigned_to
            ticket.details_json = details_json
            return ticket

        ticket = Ticket(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ticket_type=ticket_type,
            priority=priority,
            assigned_to=assigned_to,
            details_json=details_json,
        )
        db.add(ticket)
        db.flush()
        return ticket

    def _last_spam_handoff_audit(self, db: Session, *, tenant_id: int, conversation_id: int) -> AuditLog | None:
        return (
            db.query(AuditLog)
            .filter(
                AuditLog.tenant_id == tenant_id,
                AuditLog.entity_type == "conversation",
                AuditLog.entity_id == str(conversation_id),
                AuditLog.action == "conversation.handoff_spam",
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )

    def _spam_cooldown_expired(self, db: Session, *, tenant_id: int, conversation_id: int) -> bool:
        row = self._last_spam_handoff_audit(db, tenant_id=tenant_id, conversation_id=conversation_id)
        if not row:
            return False
        value = (row.details_json or {}).get("cooldown_until")
        if not isinstance(value, str):
            return False
        try:
            cooldown_until = datetime.fromisoformat(value)
        except ValueError:
            return False
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
        return cooldown_until <= self._now()

    def _unknown_count_since_last_clarification(self, db: Session, *, tenant_id: int, conversation_id: int) -> int:
        clarification = (
            db.query(Message)
            .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id, Message.direction == "outbound")
            .order_by(Message.id.desc())
            .all()
        )
        marker = next((row for row in clarification if (row.payload_json or {}).get("system_event") == "clarification_prompt"), None)
        if not marker:
            return 0
        rows = (
            db.query(Message)
            .filter(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.direction == "inbound",
                Message.id > marker.id,
            )
            .all()
        )
        return sum(1 for row in rows if (row.payload_json or {}).get("unclear_message") is True)

    def _switch_to_handoff(self, db: Session, *, tenant_id: int, conversation: Conversation, owner_ref: str, action: str, details: dict | None = None) -> None:
        conversation.state = "HUMAN_HANDOFF"
        conversation.owner_type = "role"
        conversation.owner_ref = owner_ref
        self._clear_pending_handoff_confirmation(conversation)
        self._set_handoff_timeout(conversation)
        self._add_audit(db, tenant_id=tenant_id, action=action, entity_id=conversation.id, details=details)

    def _switch_to_bot(self, db: Session, *, tenant_id: int, conversation: Conversation, action: str, details: dict | None = None) -> None:
        conversation.state = "BOT_ACTIVE"
        conversation.owner_type = "BOT"
        conversation.owner_ref = "BOT"
        self._clear_pending_handoff_confirmation(conversation)
        self._clear_handoff_timeout(conversation)
        self._add_audit(db, tenant_id=tenant_id, action=action, entity_id=conversation.id, details=details)

    def _can_auto_return_from_handoff(self, conversation: Conversation) -> bool:
        return (conversation.last_intent or "UNKNOWN") == "UNKNOWN"

    def _resolve_intent(self, db: Session, *, tenant: Tenant, text: str, language_hint: str | None):
        rule_intent = self.intent_rules.classify(db, tenant.id, text, language_hint=language_hint)
        if not self.ollama_intelligence.should_attempt(
            rule_intent_code=rule_intent.intent_code,
            rule_confidence=rule_intent.confidence,
            mixed=rule_intent.mixed,
            needs_clarification=rule_intent.needs_clarification,
        ):
            return rule_intent, None

        ollama_result = self.ollama_intelligence.classify(db, tenant=tenant, text=text, language_hint=language_hint)
        if not ollama_result:
            return rule_intent, None

        resolved = rule_intent
        resolved.intent_code = ollama_result.intent_code
        resolved.confidence = ollama_result.confidence
        resolved.matched_phrases = []
        resolved.mixed = False
        resolved.source = "ollama"
        resolved.faq_topic_key = ollama_result.faq_topic_key
        resolved.needs_clarification = ollama_result.needs_clarification
        resolved.clarification_question = ollama_result.clarification_question
        resolved.reasoning_short = ollama_result.reasoning_short
        return resolved, {"rule_first_result": rule_intent, "ollama_result": ollama_result}

    def _try_dynamic_business_info_fallback(
        self,
        db: Session,
        *,
        tenant: Tenant,
        conversation: Conversation,
        customer: Customer,
        inbound: Message,
        text: str,
        channel_type: str,
        response_lang: str,
    ) -> dict | None:
        intent_code = self.response_engine.business_info.detect_dynamic_intent(text, response_lang)
        if not intent_code:
            return None
        reply = self.response_engine.build_response(
            db,
            tenant,
            intent_code,
            faq_topic_key=intent_code.lower(),
            preferred_lang=response_lang,
        )
        if not reply:
            return None
        inbound.intent_code = intent_code
        inbound.payload_json = {
            **(inbound.payload_json or {}),
            "classification": {
                "final_intent_code": intent_code,
                "final_confidence": 1.0,
                "classifier_source": "dynamic_business_info",
                "faq_topic_key": intent_code.lower(),
                "needs_clarification": False,
                "reasoning_short": "Matched live business settings response.",
            },
        }
        conversation.last_intent = intent_code
        out = self.outbound_service.send_or_store(
            db,
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            channel_type=channel_type,
            destination=self.customer_identity.delivery_address(customer, channel_type),
            text=reply,
            intent_code=intent_code,
        )
        self._switch_to_bot(
            db,
            tenant_id=tenant.id,
            conversation=conversation,
            action="conversation.dynamic_business_info_replied",
            details={"intent": intent_code, "channel_type": channel_type},
        )
        db.commit()
        return {
            "status": "answered",
            "intent": {
                "intent_code": intent_code,
                "confidence": 1.0,
                "matched_phrases": [],
                "mixed": False,
                "source": "dynamic_business_info",
                "faq_topic_key": intent_code.lower(),
                "needs_clarification": False,
                "clarification_question": None,
                "reasoning_short": "Matched live business settings response.",
            },
            "route": {"action": "AUTO_REPLY", "owner_role": "BOT"},
            "auto_reply": reply,
            "outbound_message_id": out.id,
        }

    def _latest_conversation(
        self,
        db: Session,
        *,
        tenant_id: int,
        customer_id: int,
        channel_type: str,
        include_closed: bool,
    ) -> Conversation | None:
        query = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant_id,
                Conversation.customer_id == customer_id,
                Conversation.channel_type == channel_type,
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        if not include_closed:
            query = query.filter(Conversation.state != "CLOSED")
        return query.first()

    def _load_or_create_conversation(
        self,
        db: Session,
        *,
        tenant: Tenant,
        customer: Customer,
        channel_type: str,
    ) -> Conversation:
        conversation = self._latest_conversation(
            db,
            tenant_id=tenant.id,
            customer_id=customer.id,
            channel_type=channel_type,
            include_closed=False,
        )
        if conversation:
            return conversation

        conversation = self._latest_conversation(
            db,
            tenant_id=tenant.id,
            customer_id=customer.id,
            channel_type=channel_type,
            include_closed=True,
        )
        if conversation:
            conversation.state = "BOT_ACTIVE"
            conversation.owner_type = "BOT"
            conversation.owner_ref = "BOT"
            conversation.metadata_json = {}
            return conversation

        conversation = Conversation(
            tenant_id=tenant.id,
            customer_id=customer.id,
            channel_type=channel_type,
            state="BOT_ACTIVE",
            owner_type="BOT",
            owner_ref="BOT",
            metadata_json={},
        )
        db.add(conversation)
        db.flush()
        return conversation

    def preview_classification(self, db: Session, *, tenant: Tenant, text: str) -> dict:
        language = self.language_service.resolve_runtime_language(
            text=text,
            customer_preferred_lang=None,
            tenant_default_lang=tenant.default_lang,
        )
        intent, fallback_meta = self._resolve_intent(
            db,
            tenant=tenant,
            text=text,
            language_hint=language.resolved_lang,
        )
        route = self.routing_engine.decide(db, tenant.id, intent.intent_code)
        return {
            "intent": intent.__dict__,
            "route": route.__dict__,
            "ollama_used": bool(fallback_meta),
            "language": {
                "detected_lang": language.detected_lang,
                "resolved_lang": language.resolved_lang,
                "source": language.source,
            },
        }

    def _handle_pending_handoff_confirmation(
        self,
        db: Session,
        *,
        tenant: Tenant,
        conversation: Conversation,
        customer: Customer,
        text: str,
        channel_type: str,
        response_lang: str,
    ) -> dict | None:
        pending = self._pending_handoff_confirmation(conversation)
        if conversation.state != self.HANDOFF_CONFIRMATION_STATE or not pending:
            return None

        if self._is_explicit_human_request(text) or self._is_explicit_complaint(text):
            return None

        if self._is_confirmation_yes(text):
            owner_role = str(pending.get("owner_role") or "OPERATIONS_STAFF")
            ticket = self._create_or_update_open_ticket(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                ticket_type=str(pending.get("ticket_type") or "handoff"),
                priority=str(pending.get("priority") or "normal"),
                assigned_to=owner_role,
                details_json={
                    "intent": pending.get("intent_code"),
                    "notify_roles": pending.get("notify_roles") or [],
                    "handoff_confirmation": True,
                    "channel_type": channel_type,
                },
            )
            self._switch_to_handoff(
                db,
                tenant_id=tenant.id,
                conversation=conversation,
                owner_ref=owner_role,
                action="conversation.handoff_confirmed",
                details={"intent": pending.get("intent_code"), "channel_type": channel_type},
            )
            db.commit()
            return {"status": "handoff", "ticket_id": ticket.id, "auto_reply": None, "reason": "handoff_confirmed"}

        if self._is_confirmation_no(text):
            self._switch_to_bot(
                db,
                tenant_id=tenant.id,
                conversation=conversation,
                action="conversation.handoff_declined",
                details={"intent": pending.get("intent_code"), "channel_type": channel_type},
            )
            reply = self.response_engine.handoff_declined_reply(tenant, preferred_lang=response_lang)
            out = self.outbound_service.send_or_store(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                channel_type=channel_type,
                destination=self.customer_identity.delivery_address(customer, channel_type),
                text=reply,
                intent_code="HANDOFF_DECLINED",
            )
            db.commit()
            return {"status": "answered", "auto_reply": reply, "outbound_message_id": out.id, "reason": "handoff_declined"}

        clarification_count = int(pending.get("clarification_count") or 0)
        if clarification_count < 1:
            pending = dict(pending)
            pending["clarification_count"] = clarification_count + 1
            metadata = self._conversation_metadata(conversation)
            metadata["pending_handoff_confirmation"] = pending
            conversation.metadata_json = metadata
            reply = self.response_engine.handoff_offer_clarification(tenant, preferred_lang=response_lang)
            out = self.outbound_service.send_or_store(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                channel_type=channel_type,
                destination=self.customer_identity.delivery_address(customer, channel_type),
                text=reply,
                intent_code="HANDOFF_CONFIRMATION_CLARIFY",
            )
            self._add_audit(
                db,
                tenant_id=tenant.id,
                action="conversation.handoff_confirmation_clarified",
                entity_id=conversation.id,
                details={"intent": pending.get("intent_code"), "channel_type": channel_type},
            )
            db.commit()
            return {"status": "clarify", "auto_reply": reply, "outbound_message_id": out.id, "reason": "handoff_confirmation_unclear"}

        self._switch_to_bot(
            db,
            tenant_id=tenant.id,
            conversation=conversation,
            action="conversation.handoff_confirmation_expired",
            details={"intent": pending.get("intent_code"), "channel_type": channel_type},
        )
        return None

    def handle_inbound(self, db: Session, *, tenant: Tenant, customer_phone: str, text: str, channel_type: str, provider_message_id: str | None = None, payload_json: dict | None = None) -> dict:
        if provider_message_id:
            existing = db.query(Message).filter(Message.tenant_id == tenant.id, Message.provider_message_id == provider_message_id).first()
            if existing:
                return {"status": "duplicate", "message_id": existing.id, "auto_reply": None}
        customer = self.customer_identity.lookup_customer(db, tenant_id=tenant.id, channel_type=channel_type, address=customer_phone)
        if not customer:
            customer = Customer(tenant_id=tenant.id, phone=self.customer_identity.normalize_inbound_address(channel_type, customer_phone), preferred_lang=tenant.default_lang)
            db.add(customer); db.flush()
        self.customer_identity.update_inbound_customer(customer, channel_type=channel_type, raw_address=customer_phone, payload_json=payload_json, default_lang=tenant.default_lang)
        conversation = self._load_or_create_conversation(db, tenant=tenant, customer=customer, channel_type=channel_type)
        language = self.language_service.resolve_runtime_language(
            text=text,
            customer_preferred_lang=customer.preferred_lang,
            tenant_default_lang=tenant.default_lang,
        )
        if language.is_confident and language.detected_lang:
            customer.preferred_lang = language.detected_lang
        elif not customer.preferred_lang:
            customer.preferred_lang = language.resolved_lang
        self._set_last_customer_language(conversation, language.resolved_lang)
        inbound = Message(tenant_id=tenant.id, conversation_id=conversation.id, direction="inbound", provider_message_id=provider_message_id, text=text, payload_json=payload_json or {})
        db.add(inbound); db.flush()
        inbound.payload_json = {
            **(inbound.payload_json or {}),
            "language": {
                "detected_lang": language.detected_lang,
                "resolved_lang": language.resolved_lang,
                "source": language.source,
            },
        }

        if self._is_return_to_bot_request(text):
            self._switch_to_bot(db, tenant_id=tenant.id, conversation=conversation, action="conversation.return_to_bot", details={"channel_type": channel_type})
            reply = self.response_engine.clarification_question(tenant, preferred_lang=language.resolved_lang)
            out = self.outbound_service.send_or_store(db, tenant_id=tenant.id, conversation_id=conversation.id, channel_type=channel_type, destination=self.customer_identity.delivery_address(customer, channel_type), text=reply, intent_code="RETURN_TO_BOT")
            db.commit()
            return {"status": "bot_active", "reason": "customer_return_to_bot", "auto_reply": reply, "outbound_message_id": out.id}

        if conversation.state == self.HANDOFF_CONFIRMATION_STATE:
            pending_confirmation_result = self._handle_pending_handoff_confirmation(
                db,
                tenant=tenant,
                conversation=conversation,
                customer=customer,
                text=text,
                channel_type=channel_type,
                response_lang=language.resolved_lang,
            )
            if pending_confirmation_result is not None:
                return pending_confirmation_result

        if conversation.state == "HUMAN_HANDOFF":
            if self._handoff_timeout_expired(conversation):
                reason = (
                    "conversation.spam_cooldown_expired"
                    if self._can_auto_return_from_handoff(conversation)
                    and self._spam_cooldown_expired(db, tenant_id=tenant.id, conversation_id=conversation.id)
                    else "conversation.handoff_auto_returned"
                )
                self._switch_to_bot(
                    db,
                    tenant_id=tenant.id,
                    conversation=conversation,
                    action=reason,
                    details={"channel_type": channel_type},
                )
            else:
                db.commit()
                return {"status": "stored", "state": conversation.state, "reason": "human_handoff_active", "auto_reply": None}

        if should_auto_reply_out_of_hours(db, tenant) and not is_inside_working_hours(db, tenant):
            reply = self.response_engine.out_of_hours_reply(tenant, preferred_lang=language.resolved_lang)
            out = self.outbound_service.send_or_store(db, tenant_id=tenant.id, conversation_id=conversation.id, channel_type=channel_type, destination=self.customer_identity.delivery_address(customer, channel_type), text=reply, intent_code="OUT_OF_HOURS")
            db.commit()
            return {"status": "out_of_hours", "auto_reply": reply, "outbound_message_id": out.id}

        intent, fallback_meta = self._resolve_intent(db, tenant=tenant, text=text, language_hint=language.resolved_lang)
        inbound.intent_code = intent.intent_code
        conversation.last_intent = intent.intent_code
        inbound.payload_json = {
            **(inbound.payload_json or {}),
            "classification": {
                "final_intent_code": intent.intent_code,
                "final_confidence": intent.confidence,
                "classifier_source": intent.source,
                "faq_topic_key": intent.faq_topic_key,
                "needs_clarification": intent.needs_clarification,
                "reasoning_short": intent.reasoning_short,
            },
        }
        if fallback_meta:
            rule_first_result = fallback_meta["rule_first_result"]
            inbound.payload_json["classification"]["rule_first_result"] = {
                "intent_code": rule_first_result.intent_code,
                "confidence": rule_first_result.confidence,
            }
            self._add_audit(
                db,
                tenant_id=tenant.id,
                action="conversation.ollama_fallback_used",
                entity_id=conversation.id,
                details={
                    "channel_type": channel_type,
                    "final_intent_code": intent.intent_code,
                    "confidence": intent.confidence,
                    "faq_topic_key": intent.faq_topic_key,
                    "needs_clarification": intent.needs_clarification,
                    "language": language.resolved_lang,
                },
            )

        if self._is_explicit_human_request(text) or (intent.intent_code == "HUMAN_REQUEST" and not intent.needs_clarification):
            self._switch_to_handoff(db, tenant_id=tenant.id, conversation=conversation, owner_ref="OPERATIONS_STAFF", action="conversation.handoff_human_request", details={"text": text, "channel_type": channel_type})
            ticket = self._create_or_update_open_ticket(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                ticket_type="handoff",
                priority="normal",
                assigned_to="OPERATIONS_STAFF",
                details_json={"text": text, "intent": "HUMAN_REQUEST"},
            )
            db.commit()
            return {"status": "handoff", "ticket_id": ticket.id, "auto_reply": None}

        if self._is_explicit_complaint(text) or (intent.intent_code == "COMPLAINT" and not intent.needs_clarification):
            self._switch_to_handoff(db, tenant_id=tenant.id, conversation=conversation, owner_ref="OPERATIONS_STAFF", action="conversation.handoff_complaint", details={"text": text, "channel_type": channel_type})
            self._mark_open_complaint(conversation)
            ticket = self._create_or_update_open_ticket(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                ticket_type="complaint",
                priority="high",
                assigned_to="OPERATIONS_STAFF",
                details_json={"text": text, "intent": "COMPLAINT"},
            )
            db.commit()
            return {"status": "handoff", "ticket_id": ticket.id, "auto_reply": None}

        if intent.intent_code == "UNKNOWN" or intent.mixed or intent.needs_clarification:
            dynamic_fallback = self._try_dynamic_business_info_fallback(
                db,
                tenant=tenant,
                conversation=conversation,
                customer=customer,
                inbound=inbound,
                text=text,
                channel_type=channel_type,
                response_lang=language.resolved_lang,
            )
            if dynamic_fallback is not None:
                return dynamic_fallback
            inbound.payload_json = {**(inbound.payload_json or {}), "unclear_message": True}
            first_clarification = conversation.state != "CLARIFYING"
            if conversation.state == "CLARIFYING":
                unclear_count = self._unknown_count_since_last_clarification(db, tenant_id=tenant.id, conversation_id=conversation.id)
                if unclear_count >= self.SPAM_HANDOFF_THRESHOLD:
                    cooldown_until = self._now() + timedelta(seconds=self.SPAM_HANDOFF_COOLDOWN_SECONDS)
                    self._switch_to_handoff(
                        db,
                        tenant_id=tenant.id,
                        conversation=conversation,
                        owner_ref="OPERATIONS_STAFF",
                        action="conversation.handoff_spam",
                        details={"text": text, "channel_type": channel_type, "unclear_count": unclear_count, "cooldown_until": cooldown_until.isoformat()},
                    )
                    ticket = self._create_or_update_open_ticket(
                        db,
                        tenant_id=tenant.id,
                        conversation_id=conversation.id,
                        ticket_type="unknown_followup",
                        priority="normal",
                        assigned_to="OPERATIONS_STAFF",
                        details_json={"text": text, "unclear_count": unclear_count, "cooldown_until": cooldown_until.isoformat()},
                    )
                    db.commit()
                    return {"status": "handoff", "ticket_id": ticket.id, "auto_reply": None, "reason": "spam_threshold_reached"}
            conversation.state = "CLARIFYING"
            reply = intent.clarification_question or self.response_engine.clarification_question(tenant, preferred_lang=language.resolved_lang)
            out = self.outbound_service.send_or_store(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                channel_type=channel_type,
                destination=self.customer_identity.delivery_address(customer, channel_type),
                text=reply,
                intent_code=intent.intent_code,
            )
            if first_clarification:
                out.payload_json = {**(out.payload_json or {}), "system_event": "clarification_prompt"}
                self._add_audit(db, tenant_id=tenant.id, action="conversation.clarification_requested", entity_id=conversation.id, details={"channel_type": channel_type})
            db.commit()
            return {"status": "clarify", "intent": intent.__dict__, "auto_reply": reply, "outbound_message_id": out.id}

        route = self.routing_engine.decide(db, tenant.id, intent.intent_code)
        if route.action == "OFFER_HANDOFF":
            reply = self.response_engine.build_response(
                db,
                tenant,
                intent.intent_code,
                faq_topic_key=intent.faq_topic_key,
                preferred_lang=language.resolved_lang,
            ) or self.response_engine.clarification_question(tenant, preferred_lang=language.resolved_lang)
            self._set_pending_handoff_confirmation(
                conversation,
                intent_code=intent.intent_code,
                owner_role=route.owner_role or "OPERATIONS_STAFF",
                ticket_type=route.ticket_type,
                priority=route.priority,
                notify_roles=route.notify_roles,
                followup_question_ar=route.followup_question_ar,
                followup_question_en=route.followup_question_en,
            )
            conversation.state = self.HANDOFF_CONFIRMATION_STATE
            conversation.owner_type = "BOT"
            conversation.owner_ref = "BOT"
            followup = self._handoff_followup_text(tenant, self._pending_handoff_confirmation(conversation) or {}, route, language.resolved_lang)
            combined_reply = f"{reply}\n\n{followup}"
            out = self.outbound_service.send_or_store(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                channel_type=channel_type,
                destination=self.customer_identity.delivery_address(customer, channel_type),
                text=combined_reply,
                intent_code=intent.intent_code,
            )
            out.payload_json = {**(out.payload_json or {}), "system_event": "handoff_offer"}
            self._add_audit(
                db,
                tenant_id=tenant.id,
                action="conversation.handoff_offered",
                entity_id=conversation.id,
                details={"intent": intent.intent_code, "owner_role": route.owner_role, "ticket_type": route.ticket_type, "channel_type": channel_type},
            )
            db.commit()
            return {"status": "answered", "intent": intent.__dict__, "route": route.__dict__, "auto_reply": combined_reply, "outbound_message_id": out.id, "state": conversation.state}

        if route.action in {"HANDOFF", "TICKET"}:
            self._switch_to_handoff(db, tenant_id=tenant.id, conversation=conversation, owner_ref=route.owner_role or "OPERATIONS_STAFF", action="conversation.handoff_route", details={"intent": intent.intent_code, "channel_type": channel_type})
            ticket = self._create_or_update_open_ticket(
                db,
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                ticket_type=route.ticket_type or "handoff",
                priority=route.priority,
                assigned_to=route.owner_role,
                details_json={"intent": intent.intent_code, "notify_roles": route.notify_roles},
            )
            db.commit()
            return {"status": "handoff", "intent": intent.__dict__, "route": route.__dict__, "ticket_id": ticket.id, "auto_reply": None}

        reply = self.response_engine.build_response(
            db,
            tenant,
            intent.intent_code,
            faq_topic_key=intent.faq_topic_key,
            preferred_lang=language.resolved_lang,
        ) or self.response_engine.clarification_question(tenant, preferred_lang=language.resolved_lang)
        out = self.outbound_service.send_or_store(db, tenant_id=tenant.id, conversation_id=conversation.id, channel_type=channel_type, destination=self.customer_identity.delivery_address(customer, channel_type), text=reply, intent_code=intent.intent_code)
        self._switch_to_bot(db, tenant_id=tenant.id, conversation=conversation, action="conversation.bot_replied", details={"intent": intent.intent_code, "channel_type": channel_type})
        db.commit()
        return {"status": "answered", "intent": intent.__dict__, "route": route.__dict__, "auto_reply": reply, "outbound_message_id": out.id}
