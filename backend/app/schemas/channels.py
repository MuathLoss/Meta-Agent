from pydantic import BaseModel

class ChannelConfigRequest(BaseModel):
    status: str = "not_connected"
    public_config: dict = {}
    credentials: dict = {}

class ChannelConfigResponse(BaseModel):
    channel_type: str
    status: str
    public_config: dict
    has_credentials: bool
