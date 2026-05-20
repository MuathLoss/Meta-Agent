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


class ChannelTestConsoleRequest(BaseModel):
    channel_type: str
    session_id: str | None = Field(default=None, max_length=80)
    message: str = Field(min_length=1, max_length=4000)


class ChannelTestConsoleResponse(BaseModel):
    session_id: str
    channel_type: str
    conversation_id: str | None = None
    reply: str | None = None
    state: str | None = None
    handoff: bool
    intent: str | None = None
    notes: list[str] = Field(default_factory=list)
