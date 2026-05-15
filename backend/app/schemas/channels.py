from pydantic import BaseModel, Field

class ChannelConfigRequest(BaseModel):
    status: str = "not_connected"
    public_config: dict = Field(default_factory=dict)
    credentials: dict = Field(default_factory=dict)

class ChannelConfigResponse(BaseModel):
    channel_type: str
    status: str
    public_config: dict
    provider_channel_id: str | None = None
    provider_account_id: str | None = None
    has_credentials: bool
