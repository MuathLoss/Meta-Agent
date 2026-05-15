from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

class Base(DeclarativeBase):
    pass

class TimeMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class Tenant(Base, TimeMixin):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(80), default="SA")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Riyadh")
    default_lang: Mapped[str] = mapped_column(String(10), default="ar")
    status: Mapped[str] = mapped_column(String(40), default="draft")

class TenantBrand(Base, TimeMixin):
    __tablename__ = "tenant_brands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    primary_color: Mapped[str] = mapped_column(String(30), default="#5b0f20")
    support_email: Mapped[str | None] = mapped_column(String(255))
    support_phone: Mapped[str | None] = mapped_column(String(60))

class User(Base, TimeMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class TenantUserRole(Base, TimeMixin):
    __tablename__ = "tenant_user_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "role_code", name="uq_tenant_user_role"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_code: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Branch(Base, TimeMixin):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    maps_url: Mapped[str | None] = mapped_column(String(700))
    hours_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BusinessSetting(Base, TimeMixin):
    __tablename__ = "business_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_business_settings_tenant_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)

class FaqItem(Base, TimeMixin):
    __tablename__ = "faq_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    topic_key: Mapped[str] = mapped_column(String(120), index=True)
    question_ar: Mapped[str | None] = mapped_column(Text)
    english_question: Mapped[str | None] = mapped_column(Text)
    arabic_answer: Mapped[str] = mapped_column(Text)
    english_answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active")

class IntentDefinition(Base, TimeMixin):
    __tablename__ = "intent_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_intent_tenant_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(255))
    is_universal: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    supported_languages: Mapped[str] = mapped_column(String(20), default="ar")
    response_mode: Mapped[str] = mapped_column(String(20), default="faq")
    default_response_topic_key: Mapped[str | None] = mapped_column(String(120))
    custom_response_ar: Mapped[str | None] = mapped_column(Text)
    custom_response_en: Mapped[str | None] = mapped_column(Text)

class IntentKeyword(Base, TimeMixin):
    __tablename__ = "intent_keywords"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    intent_code: Mapped[str] = mapped_column(String(120), index=True)
    phrase: Mapped[str] = mapped_column(String(255))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    lang: Mapped[str] = mapped_column(String(10), default="ar")

class RoutingRule(Base, TimeMixin):
    __tablename__ = "routing_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "intent_code", name="uq_routing_tenant_intent"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    intent_code: Mapped[str] = mapped_column(String(120), index=True)
    primary_owner_role: Mapped[str] = mapped_column(String(80))
    notify_roles_json: Mapped[list] = mapped_column(JSON, default=list)
    escalation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    handoff_required: Mapped[bool] = mapped_column(Boolean, default=False)
    ticket_type: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(String(40), default="normal")

class TrainingExample(Base, TimeMixin):
    __tablename__ = "training_examples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    labeled_intent: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(80), default="manual")

class ChannelConfig(Base, TimeMixin):
    __tablename__ = "channel_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel_type", name="uq_channel_tenant_type"),
        Index(
            "uq_channel_configs_type_provider_channel_id",
            "channel_type",
            "provider_channel_id",
            unique=True,
            postgresql_where=text("provider_channel_id IS NOT NULL"),
            sqlite_where=text("provider_channel_id IS NOT NULL"),
        ),
        Index("ix_channel_configs_tenant_type_provider_channel", "tenant_id", "channel_type", "provider_channel_id"),
        Index("ix_channel_configs_type_status_provider_channel", "channel_type", "status", "provider_channel_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    channel_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="not_connected")
    provider_channel_id: Mapped[str | None] = mapped_column(String(255))
    provider_account_id: Mapped[str | None] = mapped_column(String(255))
    public_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Customer(Base, TimeMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_customer_tenant_phone"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(80))
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    preferred_lang: Mapped[str] = mapped_column(String(10), default="ar")
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Conversation(Base, TimeMixin):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_customer_channel", "tenant_id", "customer_id", "channel_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    channel_type: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(40), default="BOT_ACTIVE")
    owner_type: Mapped[str | None] = mapped_column(String(80))
    owner_ref: Mapped[str | None] = mapped_column(String(120))
    last_intent: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

class Message(Base, TimeMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_message_id", name="uq_messages_tenant_provider_message_id"), Index("ix_messages_conversation_created_at", "conversation_id", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    intent_code: Mapped[str | None] = mapped_column(String(120))

class Ticket(Base, TimeMixin):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    ticket_type: Mapped[str] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(String(40), default="normal")
    assigned_to: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="open")
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)

class Broadcast(Base, TimeMixin):
    __tablename__ = "broadcasts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    channel_type: Mapped[str] = mapped_column(String(80), default="whatsapp")
    template_ref: Mapped[str | None] = mapped_column(String(255))
    audience_type: Mapped[str] = mapped_column(String(80), default="selected")
    schedule_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)

class BroadcastRecipient(Base, TimeMixin):
    __tablename__ = "broadcast_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class WebhookEvent(Base, TimeMixin):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    provider_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)

class AuditLog(Base, TimeMixin):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(120))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
