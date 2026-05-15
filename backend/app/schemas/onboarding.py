from pydantic import BaseModel, Field

class OnboardingStepRequest(BaseModel):
    data: dict = Field(default_factory=dict)

class ReadinessItem(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str | None = None

class ReadinessResponse(BaseModel):
    is_ready: bool
    items: list[ReadinessItem]
