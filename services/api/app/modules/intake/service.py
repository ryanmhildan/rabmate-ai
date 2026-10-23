"""Uploading, listing and reading source documents (ADR-043)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.api.deps import RequestContext
from app.core.config import Settings
from app.core.errors import BusinessValidationError, NotFoundError
from app.modules.audit import service as audit
from app.modules.intake.models import SourceDocument
from app.modules.intake.ocr import OcrEngine
from app.modules.intake.readers import read_document
from app.modules.intake.sniff import UnsupportedFileError, safe_filename, sniff
from app.modules.projects import service as projects

ENTITY = "source_document"
LIST_LIMIT = 50


def _audit(db: Session, ctx: RequestContext, action: str, doc: SourceDocument) -> None:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=ENTITY,
        entity_id=doc.id,
        summary=f"{doc.filename} ({doc.kind.value}, {doc.size_bytes} byte)",
        ip_address=ctx.ip_address,
    )


def get(
    db: Session, ctx: RequestContext, document_id: uuid.UUID, *, with_content: bool = False
) -> SourceDocument:
    stmt = select(SourceDocument).where(
        SourceDocument.id == document_id, SourceDocument.organization_id == ctx.organization_id
    )
    if with_content:
        stmt = stmt.options(undefer(SourceDocument.content))
    doc = db.execute(stmt).unique().scalar_one_or_none()
    if doc is None:
        raise NotFoundError("Dokumen sumber tidak ditemukan.")
    return doc


def list_for_project(
    db: Session, ctx: RequestContext, project_id: uuid.UUID
) -> list[SourceDocument]:
    projects.get_project(db, ctx, project_id)
    return list(
        db.execute(
            select(SourceDocument)
            .where(
                SourceDocument.organization_id == ctx.organization_id,
                SourceDocument.project_id == project_id,
            )
            .order_by(SourceDocument.created_at.desc())
            .limit(LIST_LIMIT)
        )
        .unique()
        .scalars()
    )


def upload(
    db: Session,
    ctx: RequestContext,
    project_id: uuid.UUID,
    filename: str | None,
    content: bytes,
    settings: Settings,
) -> tuple[SourceDocument, bool]:
    """Stores the file (or returns the copy already uploaded to this project)."""
    project = projects.get_project(db, ctx, project_id)
    limit = settings.upload_max_mb * 1024 * 1024
    if len(content) > limit:
        raise BusinessValidationError(f"Ukuran file melebihi {settings.upload_max_mb} MB.")
    name = safe_filename(filename)
    try:
        sniffed = sniff(name, content)
    except UnsupportedFileError as exc:
        raise BusinessValidationError(str(exc)) from None
    digest = hashlib.sha256(content).hexdigest()
    existing = db.execute(
        select(SourceDocument).where(
            SourceDocument.organization_id == ctx.organization_id,
            SourceDocument.project_id == project.id,
            SourceDocument.sha256 == digest,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    doc = SourceDocument(
        organization_id=ctx.organization_id,
        project_id=project.id,
        filename=name,
        content_type=sniffed.content_type,
        kind=sniffed.kind,
        size_bytes=len(content),
        sha256=digest,
        content=content,
        uploaded_by_id=ctx.user_id,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:  # the same file raced in
        db.rollback()
        again = db.execute(
            select(SourceDocument).where(
                SourceDocument.organization_id == ctx.organization_id,
                SourceDocument.project_id == project.id,
                SourceDocument.sha256 == digest,
            )
        ).scalar_one()
        return again, False
    _audit(db, ctx, "source_document.upload", doc)
    db.commit()
    return get(db, ctx, doc.id), True


def cached_extraction(
    db: Session, ctx: RequestContext, document_id: uuid.UUID
) -> dict[str, Any] | None:
    doc = get(db, ctx, document_id)
    db.refresh(doc, ["extraction"])
    return doc.extraction


def extraction_of(
    db: Session, doc_id: uuid.UUID, ocr: OcrEngine, settings: Settings
) -> dict[str, Any]:
    """The cached page text of a document, reading (and OCR-ing) it on first use.

    Called from background work, so it takes the document by id within the caller's session.
    """
    doc = db.execute(
        select(SourceDocument)
        .where(SourceDocument.id == doc_id)
        .options(undefer(SourceDocument.content), undefer(SourceDocument.extraction))
    ).scalar_one()
    if doc.extraction is not None:
        return doc.extraction
    result = read_document(
        doc.kind,
        doc.content,
        ocr=ocr,
        max_pages=settings.intake_max_pages,
        ocr_max_pages=settings.ocr_max_pages,
    ).to_json()
    doc.extraction = result
    db.commit()
    return result
