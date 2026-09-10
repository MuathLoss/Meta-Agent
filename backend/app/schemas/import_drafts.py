"""Validate resumable review shapes before they can be stored and opened by the UI."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class DraftEditable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    training_example_text: str = Field(max_length=4000)
    intent_code: str = Field(max_length=120)
    keyword_phrases: list[str] = Field(max_length=10)
    faq_topic_key: str = Field(max_length=160)
    faq_question: str = Field(max_length=4000)
    faq_answer: str = Field(max_length=4000)
    routing_behavior: Literal['normal','offer_handoff','immediate_handoff','clarify']
    create_intent: bool
    create_faq: bool
    apply_routing: bool = False

class SuggestedIntent(BaseModel):
    code: str
    label: str
    existing: bool

class RoutingHint(BaseModel):
    behavior: str
    owner_role: str | None = None
    reason: str

class SuggestedFaq(BaseModel):
    topic_key: str
    question: str
    answer: str
    existing: bool
    confidence: float

class DraftRow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    row_id: str = Field(min_length=1, max_length=80)
    source_index: int
    source_type: str
    redacted_excerpt: str = Field(max_length=4000)
    normalized_text: str = Field(max_length=4000)
    detected_language: str
    suggested_intent: SuggestedIntent
    confidence: float = Field(ge=0, le=1)
    suggested_keywords: list[str] = Field(max_length=10)
    suggested_faq_topic: SuggestedFaq | None = None
    routing_hint: RoutingHint
    warnings: list[str] = Field(max_length=50)
    decision: Literal['approved','pending','rejected']
    editable: DraftEditable

class DraftPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_type: str
    total_rows: int = Field(ge=0)
    previewed_rows: int = Field(ge=0, le=500)
    duplicate_rows: int = Field(ge=0)
    max_rows: int = Field(ge=1, le=500)
    rows: list[DraftRow] = Field(max_length=500)
    notes: list[str]

class ImportDraftRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='Message import', max_length=160)
    source_type: Literal['paste','txt','csv','xlsx','preview','whatsapp_export'] = 'paste'
    revision: int | None = Field(default=None, ge=1)
    preview: DraftPreview
    rows: list[DraftRow] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def consistent_rows(self):
        ids = [r.row_id for r in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError('Each review message must have a unique row ID.')
        self.preview.rows = self.rows
        self.preview.previewed_rows = len(self.rows)
        return self
