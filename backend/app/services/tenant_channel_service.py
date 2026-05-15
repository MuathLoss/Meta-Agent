from sqlalchemy.orm import Session
from app.core.crypto import decrypt_dict, encrypt_dict
from app.models.entities import ChannelConfig


class TenantChannelService:
    def list(self, db: Session, tenant_id: int):
        return (
            db.query(ChannelConfig)
            .filter(ChannelConfig.tenant_id == tenant_id)
            .order_by(ChannelConfig.channel_type)
            .all()
        )

    def get(self, db: Session, tenant_id: int, channel_type: str):
        return (
            db.query(ChannelConfig)
            .filter(
                ChannelConfig.tenant_id == tenant_id,
                ChannelConfig.channel_type == channel_type,
            )
            .first()
        )

    def encrypt_credentials(self, credentials: dict) -> str:
        return encrypt_dict(credentials or {})

    def decrypt_credentials(self, encrypted_credentials: str | None) -> dict:
        return decrypt_dict(encrypted_credentials)

    def upsert(
        self,
        db: Session,
        tenant_id: int,
        channel_type: str,
        status: str,
        public_config: dict,
        credentials: dict,
    ):
        row = self.get(db, tenant_id, channel_type)
        if not row:
            row = ChannelConfig(tenant_id=tenant_id, channel_type=channel_type)
            db.add(row)
        row.status = status
        row.public_config_json = public_config or {}
        if credentials:
            row.encrypted_credentials = self.encrypt_credentials(credentials)
        db.flush()
        return row

    def credentials(self, row: ChannelConfig) -> dict:
        return self.decrypt_credentials(row.encrypted_credentials)
