from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from app.ai.adapter import AgentState
from app.ai.numbers import NumberFormat
from app.modules.assistant.models import ITEM_KINDS, AiRunKind, AiRunStatus, MessageRole
from app.modules.identity.schemas import UserBrief, blank_to_none
from app.modules.rab.models import RabItemType
from app.modules.rab.schemas import Quantity

MIN_INPUT_CHARS = 10


class OcrStatusOut(BaseModel):
    available: bool
    message: str


class AiStatusOut(BaseModel):
    enabled: bool
    state: AgentState
    message: str
    model: str | None
    toolsets: list[str]
    ocr: OcrStatusOut
    upload_max_mb: int
    accepted_files: str


class RunCreate(BaseModel):
    kind: AiRunKind
    # rab_draft
    description: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=4000)
    ] = None
    # extract_items (the server also enforces AI_MAX_INPUT_CHARS)
    text: Annotated[str | None, StringConstraints(max_length=100_000)] = None
    source_label: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=200),
        AfterValidator(blank_to_none),
    ] = None
    # extract_document: a file uploaded to the RAB's project (POST /projects/{id}/source-documents)
    source_document_id: uuid.UUID | None = None
    number_format: NumberFormat = NumberFormat.ID

    @model_validator(mode="after")
    def _input_for_kind(self) -> Self:
        if self.kind not in ITEM_KINDS:
            raise ValueError("Jenis permintaan ini tidak tersedia di sini.")
        if self.kind is AiRunKind.RAB_DRAFT:
            if not self.description or len(self.description) < MIN_INPUT_CHARS:
                raise ValueError("Deskripsi pekerjaan minimal 10 karakter.")
        elif self.kind is AiRunKind.EXTRACT_DOCUMENT:
            if self.source_document_id is None:
                raise ValueError("Pilih dokumen sumber yang sudah diunggah.")
        elif not self.text or len(self.text.strip()) < MIN_INPUT_CHARS:
            raise ValueError("Teks dokumen minimal 10 karakter.")
        return self


class ApplyItem(BaseModel):
    index: Annotated[int, Field(ge=0)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    quantity: Quantity
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    item_type: RabItemType | None = None
    # none: leave unpriced; catalog: price resolved server-side from the catalog observation;
    # document: the unit price read from the source text (extraction runs only).
    price: Literal["none", "catalog", "document"] = "none"
    price_observation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _catalog_needs_observation(self) -> Self:
        if (self.price == "catalog") != (self.price_observation_id is not None):
            raise ValueError("Pilih harga katalog atau ubah pilihan harga.")
        return self


class ApplyIn(BaseModel):
    items: Annotated[list[ApplyItem], Field(min_length=1, max_length=200)]


class RunListItem(BaseModel):
    id: uuid.UUID
    kind: AiRunKind
    status: AiRunStatus
    created_by: UserBrief
    created_at: datetime
    finished_at: datetime | None
    item_count: int
    applied_count: int | None
    error_message: str | None


class RunOut(RunListItem):
    rab_version_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    input: dict[str, Any]
    context: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    model: str | None
    attempts: int
    duration_ms: int | None
    started_at: datetime | None
    applied_at: datetime | None
    can_apply: bool
    can_discard: bool


# --------------------------------------------------------------------------- project chat


class AskIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]


class ChatSourceOut(BaseModel):
    id: str  # S1, S2 ... as cited in the answer
    kind: str
    label: str
    ref: dict[str, str] | None  # {"type": "rab" | "catalog_item" | "project" | ..., "id": ...}
    data: dict[str, Any]  # exactly what the assistant was given
    cited: bool = True  # False: not cited, but where a number in the answer actually came from


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    sources: list[ChatSourceOut]
    warnings: list[str]
    assumptions: list[str]
    questions: list[str]
    created_at: datetime


class ChatRunOut(BaseModel):
    id: uuid.UUID
    status: AiRunStatus
    error_code: str | None
    error_message: str | None
    model: str | None
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None


class ConversationListItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageOut]
    latest_run: ChatRunOut | None
    unavailable: list[str]  # data left out of the latest answer (permissions, no matches)
