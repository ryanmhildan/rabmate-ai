from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.identity.schemas import UserBrief
from app.modules.intake.models import SourceKind


class SourceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    content_type: str
    kind: SourceKind
    size_bytes: int
    sha256: str
    uploaded_by: UserBrief
    created_at: datetime


class UploadOut(SourceDocumentOut):
    duplicate: bool  # the same file was already uploaded to this project; that copy is returned


class PageText(BaseModel):
    no: int
    label: str
    method: str
    lines: list[str]


class SourceTextOut(BaseModel):
    """What was read from the file — for checking extraction results against the source."""

    read: bool
    pages: list[PageText] = []
    warnings: list[str] = []
