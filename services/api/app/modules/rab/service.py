"""RAB business logic. Every query is scoped to ctx.organization_id.

Concurrency: mutations of a version lock its row (SELECT … FOR UPDATE) so item edits, totals and
status transitions are serialized; version-creating operations also lock the parent RAB row.
Clients additionally send `lock_version` (header) / `row_version` (item) for optimistic checks.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext
from app.core.config import get_settings
from app.core.errors import (
    BusinessValidationError,
    ConflictError,
    NotFoundError,
    VersionConflictError,
)
from app.core.pagination import PageParams, apply_sort, count_rows, escape_like
from app.modules.approvals.models import ApprovalAction, ApprovalRecord
from app.modules.audit import service as audit
from app.modules.identity.permissions import Permission
from app.modules.numbering.service import format_number, next_value
from app.modules.pricing import service as pricing
from app.modules.projects.models import Project, ProjectStatus
from app.modules.rab import schemas
from app.modules.rab.calculation import (
    Adjustments,
    CalculationError,
    DiscountType,
    LineInput,
    calculate,
    line_subtotal,
)
from app.modules.rab.compare import CompareItem, compare_items
from app.modules.rab.lifecycle import STATUS_LABELS, TRANSITIONS, RabAction
from app.modules.rab.models import (
    OPEN_STATUSES,
    PriceSourceType,
    RabDocument,
    RabItem,
    RabStatus,
    RabVersion,
)
from app.modules.rab.validation import Issue, ItemFacts, has_errors, validate

ENTITY_VERSION = "rab_version"
NUMBER_KIND = "rab"
NUMBER_PREFIX = "RAB"
# A RAB is planning work: not started for finished or cancelled projects.
PROJECT_STATUSES_ACCEPTING_RAB = (
    ProjectStatus.PROSPECT,
    ProjectStatus.ACTIVE,
    ProjectStatus.ON_HOLD,
)

ITEM_FIELDS = (
    "code",
    "name",
    "category",
    "item_type",
    "specification",
    "quantity",
    "unit",
    "unit_price",
    "price_source_type",
    "price_source",
    "price_observation_id",
    "notes",
)
HEADER_FIELDS = (
    "tax_label",
    "tax_rate_percent",
    "discount_type",
    "discount_value",
    "notes",
    "assumptions",
)

SORTABLE = {
    "number": RabDocument.number,
    "title": RabDocument.title,
    "updated_at": RabVersion.updated_at,
    "grand_total": RabVersion.grand_total,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _label(status: RabStatus) -> str:
    return STATUS_LABELS[status]


# --------------------------------------------------------------------------- loading


def get_rab(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, *, lock: bool = False
) -> RabDocument:
    # populate_existing: responses always reflect what the database stored (normalized
    # NUMERIC scales, server defaults), not the Python values a request just assigned.
    stmt = (
        select(RabDocument)
        .where(RabDocument.id == rab_id, RabDocument.organization_id == ctx.organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=RabDocument)
    rab = db.execute(stmt.options(selectinload(RabDocument.versions))).unique().scalar_one_or_none()
    if rab is None:
        raise NotFoundError("RAB tidak ditemukan.")
    return rab


def get_version(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int, *, lock: bool = False
) -> RabVersion:
    stmt = (
        select(RabVersion)
        .where(
            RabVersion.organization_id == ctx.organization_id,
            RabVersion.rab_id == rab_id,
            RabVersion.version_no == version_no,
        )
        .options(selectinload(RabVersion.items))
        .execution_options(populate_existing=True)
    )
    if lock:
        # OF rab_versions: the eager outer joins (submitted_by, decided_by) must not be locked.
        stmt = stmt.with_for_update(of=RabVersion)
    version = db.execute(stmt).unique().scalar_one_or_none()
    if version is None:
        raise NotFoundError("Versi RAB tidak ditemukan.")
    return version


def _open_project(db: Session, ctx: RequestContext, project_id: uuid.UUID) -> Project:
    project = db.execute(
        select(Project).where(
            Project.id == project_id, Project.organization_id == ctx.organization_id
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Proyek tidak ditemukan.")
    if project.status not in PROJECT_STATUSES_ACCEPTING_RAB:
        raise ConflictError(
            "RAB baru tidak dapat dibuat untuk proyek yang selesai atau dibatalkan."
        )
    return project


# --------------------------------------------------------------------------- calculation


def adjustments_of(version: RabVersion) -> Adjustments:
    return Adjustments(
        discount_type=version.discount_type,
        discount_value=version.discount_value,
        tax_rate_percent=version.tax_rate_percent,
    )


def recalculate(version: RabVersion) -> None:
    """Refreshes every item subtotal and the version totals from the pure calculation module."""
    try:
        totals = calculate(
            (LineInput(i.quantity, i.unit_price) for i in version.items), adjustments_of(version)
        )
        for item in version.items:
            item.subtotal = line_subtotal(item.quantity, item.unit_price)
    except CalculationError as exc:
        raise BusinessValidationError(exc.message, details={"code": exc.code}) from None
    version.subtotal = totals.subtotal
    version.discount_amount = totals.discount_amount
    version.taxable_base = totals.taxable_base
    version.tax_amount = totals.tax_amount
    version.grand_total = totals.grand_total
    version.unpriced_items = totals.unpriced_items


def issues_of(version: RabVersion) -> list[Issue]:
    facts = [
        ItemFacts(
            i.id,
            index,
            i.code,
            i.name,
            i.quantity,
            i.unit_price,
            i.price_source,
            i.price_observation.verification_status.value if i.price_observation else None,
        )
        for index, i in enumerate(version.items, start=1)
    ]
    return validate(facts, adjustments_of(version), version.tax_label)


# --------------------------------------------------------------------------- RAB documents


def _latest_version_query(ctx: RequestContext) -> Select[RabDocument, RabVersion]:
    latest = (
        select(RabVersion.rab_id, func.max(RabVersion.version_no).label("version_no"))
        .where(RabVersion.organization_id == ctx.organization_id)
        .group_by(RabVersion.rab_id)
        .subquery()
    )
    return (
        select(RabDocument, RabVersion)
        .join(latest, latest.c.rab_id == RabDocument.id)
        .join(
            RabVersion,
            (RabVersion.rab_id == RabDocument.id) & (RabVersion.version_no == latest.c.version_no),
        )
        .join(Project, Project.id == RabDocument.project_id)
        .where(RabDocument.organization_id == ctx.organization_id)
    )


def list_rabs(
    db: Session,
    ctx: RequestContext,
    params: PageParams,
    *,
    q: str | None,
    status: RabStatus | None,
    project_id: uuid.UUID | None,
    sort: str | None,
) -> tuple[list[tuple[RabDocument, RabVersion]], int]:
    stmt = _latest_version_query(ctx)
    if q:
        term = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                RabDocument.number.ilike(term, escape="\\"),
                RabDocument.title.ilike(term, escape="\\"),
                Project.name.ilike(term, escape="\\"),
                Project.number.ilike(term, escape="\\"),
            )
        )
    if status is not None:
        stmt = stmt.where(RabVersion.status == status)
    if project_id is not None:
        stmt = stmt.where(RabDocument.project_id == project_id)
    stmt = apply_sort(stmt, sort, SORTABLE, default="-updated_at")
    total = count_rows(db, stmt)
    rows = db.execute(stmt.limit(params.page_size).offset(params.offset)).unique().all()
    return [(rab, version) for rab, version in rows], total


def _new_number(db: Session, ctx: RequestContext) -> str:
    year = datetime.now(ZoneInfo(get_settings().timezone)).year
    return format_number(
        NUMBER_PREFIX, year, next_value(db, ctx.organization_id, NUMBER_KIND, year)
    )


def create_rab(
    db: Session, ctx: RequestContext, project_id: uuid.UUID, payload: schemas.RabCreate
) -> RabDocument:
    project = _open_project(db, ctx, project_id)
    rab = RabDocument(
        organization_id=ctx.organization_id,
        project_id=project.id,
        number=_new_number(db, ctx),
        title=payload.title,
        created_by_id=ctx.user_id,
    )
    db.add(rab)
    db.flush()
    version = RabVersion(
        organization_id=ctx.organization_id,
        rab_id=rab.id,
        version_no=1,
        status=RabStatus.DRAFT,
        currency=project.currency,
        # The project's tax configuration is the starting point; it is never invented.
        tax_label=project.tax_label,
        tax_rate_percent=project.tax_rate_percent,
        discount_type=DiscountType.NONE,
        discount_value=Decimal("0"),
        notes=payload.notes,
        created_by_id=ctx.user_id,
    )
    db.add(version)
    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="rab.create",
        entity_type="rab",
        entity_id=rab.id,
        summary=f"{rab.number} {rab.title} ({project.number})",
        ip_address=ctx.ip_address,
    )
    db.commit()
    return get_rab(db, ctx, rab.id)


def update_rab(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, payload: schemas.RabUpdate
) -> RabDocument:
    rab = get_rab(db, ctx, rab_id, lock=True)
    if rab.title != payload.title:
        audit.record(
            db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="rab.update",
            entity_type="rab",
            entity_id=rab.id,
            summary=rab.number,
            changes={"title": {"from": rab.title, "to": payload.title}},
            ip_address=ctx.ip_address,
        )
        rab.title = payload.title
    db.commit()
    return get_rab(db, ctx, rab_id)


def delete_rab(db: Session, ctx: RequestContext, rab_id: uuid.UUID) -> None:
    rab = get_rab(db, ctx, rab_id, lock=True)
    version_ids = [v.id for v in rab.versions]
    ever_approved = db.execute(
        select(
            exists().where(
                ApprovalRecord.organization_id == ctx.organization_id,
                ApprovalRecord.entity_type == ENTITY_VERSION,
                ApprovalRecord.entity_id.in_(version_ids),
                ApprovalRecord.action == ApprovalAction.APPROVED,
            )
        )
    ).scalar_one()
    if ever_approved or any(v.status is RabStatus.IN_REVIEW for v in rab.versions):
        raise ConflictError(
            "RAB yang pernah disetujui atau sedang direview tidak dapat dihapus; arsipkan versinya."
        )
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="rab.delete",
        entity_type="rab",
        entity_id=rab.id,
        summary=f"{rab.number} {rab.title}",
        ip_address=ctx.ip_address,
    )
    db.delete(rab)
    db.commit()


# --------------------------------------------------------------------------- version header


def _require_draft(version: RabVersion) -> None:
    if version.status is not RabStatus.DRAFT:
        raise ConflictError(
            f"Versi {version.version_no} berstatus {_label(version.status)}; "
            "hanya draft yang dapat diubah. Buat versi baru untuk merevisi."
        )


def update_header(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    payload: schemas.VersionUpdate,
) -> RabVersion:
    version = get_version(db, ctx, rab_id, version_no, lock=True)
    _require_draft(version)
    if version.lock_version != payload.lock_version:
        raise VersionConflictError(details={"current_version": version.lock_version})

    data = payload.model_dump(exclude_unset=True, exclude={"lock_version"})
    # Validate the merged result before touching the ORM object.
    merged = {field: data.get(field, getattr(version, field)) for field in HEADER_FIELDS}
    if merged["discount_type"] is None:
        raise BusinessValidationError("Jenis diskon wajib diisi.")
    if merged["discount_type"] is DiscountType.NONE:
        merged["discount_value"] = Decimal("0")
    if merged["discount_value"] is None:
        raise BusinessValidationError("Nilai diskon wajib diisi.")
    if merged["discount_type"] is DiscountType.PERCENT and merged["discount_value"] > 100:
        raise BusinessValidationError("Diskon persen harus 0-100.")
    if (merged["tax_label"] is None) != (merged["tax_rate_percent"] is None):
        raise BusinessValidationError(
            "Label pajak dan tarif pajak harus diisi bersamaan atau dikosongkan."
        )

    before = audit.snapshot(version, HEADER_FIELDS)
    for field, value in merged.items():
        setattr(version, field, value)
    recalculate(version)

    changes = audit.diff(before, audit.snapshot(version, HEADER_FIELDS))
    if changes:
        db.flush()
        _audit_version(db, ctx, version, "rab_version.update", changes)
    db.commit()
    return get_version(db, ctx, rab_id, version_no)


# --------------------------------------------------------------------------- items


def _find_item(version: RabVersion, item_id: uuid.UUID) -> RabItem:
    for item in version.items:
        if item.id == item_id:
            return item
    raise NotFoundError("Item RAB tidak ditemukan.")


def _item_values(
    db: Session, ctx: RequestContext, version: RabVersion, payload: schemas.ItemBase
) -> dict[str, Any]:
    """Payload fields; a catalog reference is resolved server-side (price + provenance)."""
    values = payload.model_dump(exclude={"row_version"})
    if payload.price_observation_id is not None:
        resolved = pricing.resolve_for_rab(
            db,
            ctx,
            payload.price_observation_id,
            unit=payload.unit,
            currency=version.currency,
        )
        values |= {
            "unit_price": resolved.observation.price,
            "price_source_type": PriceSourceType.CATALOG,
            "price_source": resolved.source_text,
        }
    return values


def add_item(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    payload: schemas.ItemCreate,
) -> RabVersion:
    version = get_version(db, ctx, rab_id, version_no, lock=True)
    _require_draft(version)
    position = max((i.position for i in version.items), default=0) + 1
    item = RabItem(
        organization_id=ctx.organization_id,
        version_id=version.id,
        position=position,
        **_item_values(db, ctx, version, payload),
    )
    version.items.append(item)
    recalculate(version)
    db.flush()
    _audit_version(
        db,
        ctx,
        version,
        "rab_item.create",
        {f: {"from": None, "to": v} for f, v in audit.snapshot(item, ITEM_FIELDS).items() if v},
        summary_suffix=item.name,
    )
    db.commit()
    return get_version(db, ctx, rab_id, version_no)


def update_item(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    item_id: uuid.UUID,
    payload: schemas.ItemUpdate,
) -> RabVersion:
    version = get_version(db, ctx, rab_id, version_no, lock=True)
    _require_draft(version)
    item = _find_item(version, item_id)
    if item.row_version != payload.row_version:
        raise VersionConflictError(details={"current_version": item.row_version})

    before = audit.snapshot(item, ITEM_FIELDS)
    for field, value in _item_values(db, ctx, version, payload).items():
        setattr(item, field, value)
    after = audit.snapshot(item, ITEM_FIELDS)
    changes = audit.diff(before, after)
    if changes:
        recalculate(version)
        db.flush()
        _audit_version(db, ctx, version, "rab_item.update", changes, summary_suffix=item.name)
    db.commit()
    return get_version(db, ctx, rab_id, version_no)


def delete_item(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    item_id: uuid.UUID,
    row_version: int,
) -> RabVersion:
    version = get_version(db, ctx, rab_id, version_no, lock=True)
    _require_draft(version)
    item = _find_item(version, item_id)
    if item.row_version != row_version:
        raise VersionConflictError(details={"current_version": item.row_version})
    version.items.remove(item)
    recalculate(version)
    db.flush()
    _audit_version(
        db,
        ctx,
        version,
        "rab_item.delete",
        {f: {"from": v, "to": None} for f, v in audit.snapshot(item, ITEM_FIELDS).items() if v},
        summary_suffix=item.name,
    )
    db.commit()
    return get_version(db, ctx, rab_id, version_no)


# --------------------------------------------------------------------------- workflow


def _record(
    db: Session,
    ctx: RequestContext,
    version: RabVersion,
    action: ApprovalAction,
    from_status: RabStatus,
    note: str | None,
) -> None:
    db.add(
        ApprovalRecord(
            organization_id=ctx.organization_id,
            entity_type=ENTITY_VERSION,
            entity_id=version.id,
            action=action,
            from_status=from_status.value,
            to_status=version.status.value,
            actor_user_id=ctx.user_id,
            note=note,
        )
    )


def _audit_version(
    db: Session,
    ctx: RequestContext,
    version: RabVersion,
    action: str,
    changes: dict[str, Any] | None = None,
    *,
    summary_suffix: str | None = None,
) -> None:
    number = db.execute(
        select(RabDocument.number).where(RabDocument.id == version.rab_id)
    ).scalar_one()
    summary = f"{number} v{version.version_no}"
    if summary_suffix:
        summary = f"{summary} · {summary_suffix}"
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=ENTITY_VERSION,
        entity_id=version.id,
        summary=summary,
        changes=changes,
        ip_address=ctx.ip_address,
    )


def _open_version(
    versions: Sequence[RabVersion], *, exclude: uuid.UUID | None = None
) -> RabVersion | None:
    return next((v for v in versions if v.status in OPEN_STATUSES and v.id != exclude), None)


def transition(
    db: Session,
    ctx: RequestContext,
    rab_id: uuid.UUID,
    version_no: int,
    action: RabAction,
    note: str | None,
) -> RabVersion:
    rule = TRANSITIONS[action]
    ctx.require(rule.permission)
    rab = get_rab(db, ctx, rab_id, lock=True)  # serializes workflow changes per RAB
    version = get_version(db, ctx, rab_id, version_no, lock=True)

    if version.status not in rule.sources:
        raise ConflictError(
            f"Aksi '{action.value}' tidak berlaku untuk versi berstatus {_label(version.status)}."
        )
    if rule.note_required and not note:
        raise BusinessValidationError(
            "Alasan wajib diisi.", details=[{"loc": ["body", "note"], "msg": "Alasan wajib diisi."}]
        )
    if rule.target in OPEN_STATUSES:
        other = _open_version(rab.versions, exclude=version.id)
        if other is not None:
            raise ConflictError(
                f"Versi {other.version_no} masih {_label(other.status)}; "
                "hanya satu versi yang boleh terbuka."
            )

    now = _now()
    if action is RabAction.SUBMIT:
        issues = issues_of(version)
        if has_errors(issues):
            raise BusinessValidationError(
                "RAB belum dapat diajukan. Perbaiki kesalahan berikut terlebih dahulu.",
                details={"issues": [_issue_dict(i) for i in issues]},
            )
        version.submitted_at, version.submitted_by_id = now, ctx.user_id
    elif action in (RabAction.APPROVE, RabAction.REJECT):
        version.decided_at, version.decided_by_id = now, ctx.user_id
    elif action in (RabAction.WITHDRAW, RabAction.REOPEN):
        version.submitted_at = version.submitted_by_id = None
        version.decided_at = version.decided_by_id = None

    from_status = version.status
    version.status = rule.target
    _record(db, ctx, version, rule.record, from_status, note)

    if action is RabAction.APPROVE:
        # Only one approved version per RAB: the previous one is superseded (kept, read-only).
        for previous in rab.versions:
            if previous.id != version.id and previous.status is RabStatus.APPROVED:
                previous.status = RabStatus.ARCHIVED
                _record(
                    db,
                    ctx,
                    previous,
                    ApprovalAction.SUPERSEDED,
                    RabStatus.APPROVED,
                    f"Digantikan versi {version.version_no}",
                )

    db.flush()
    _audit_version(
        db,
        ctx,
        version,
        f"rab_version.{action.value}",
        {"status": {"from": from_status.value, "to": version.status.value}}
        | ({"note": {"from": None, "to": note}} if note else {}),
    )
    db.commit()
    return get_version(db, ctx, rab_id, version_no)


def _issue_dict(issue: Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "item_id": str(issue.item_id) if issue.item_id else None,
    }


def _copy_items(source: RabVersion, target: RabVersion, organization_id: uuid.UUID) -> None:
    for item in source.items:
        target.items.append(
            RabItem(
                organization_id=organization_id,
                position=item.position,
                **{field: getattr(item, field) for field in ITEM_FIELDS},
            )
        )


def create_version(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, from_version_no: int | None
) -> RabVersion:
    ctx.require(Permission.RAB_WRITE)
    rab = get_rab(db, ctx, rab_id, lock=True)
    open_version = _open_version(rab.versions)
    if open_version is not None:
        raise ConflictError(
            f"Versi {open_version.version_no} masih {_label(open_version.status)}. "
            "Selesaikan atau arsipkan versi tersebut sebelum membuat versi baru."
        )
    latest_no = max(v.version_no for v in rab.versions)
    source = get_version(db, ctx, rab_id, from_version_no or latest_no)
    version = RabVersion(
        organization_id=ctx.organization_id,
        rab_id=rab.id,
        version_no=latest_no + 1,
        status=RabStatus.DRAFT,
        based_on_version_id=source.id,
        currency=source.currency,
        tax_label=source.tax_label,
        tax_rate_percent=source.tax_rate_percent,
        discount_type=source.discount_type,
        discount_value=source.discount_value,
        notes=source.notes,
        assumptions=source.assumptions,
        created_by_id=ctx.user_id,
    )
    db.add(version)
    _copy_items(source, version, ctx.organization_id)
    recalculate(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Versi lain baru saja dibuat. Muat ulang halaman.") from None
    _audit_version(
        db,
        ctx,
        version,
        "rab_version.create",
        {"based_on_version": {"from": None, "to": source.version_no}},
    )
    db.commit()
    return get_version(db, ctx, rab_id, version.version_no)


def duplicate_rab(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, payload: schemas.DuplicateRequest
) -> RabDocument:
    ctx.require(Permission.RAB_WRITE)
    source_rab = get_rab(db, ctx, rab_id)
    source_no = payload.version_no or max(v.version_no for v in source_rab.versions)
    source = get_version(db, ctx, rab_id, source_no)
    project = _open_project(db, ctx, payload.project_id or source_rab.project_id)

    rab = RabDocument(
        organization_id=ctx.organization_id,
        project_id=project.id,
        number=_new_number(db, ctx),
        title=payload.title or f"{source_rab.title} (salinan)"[:200],
        created_by_id=ctx.user_id,
    )
    db.add(rab)
    db.flush()
    version = RabVersion(
        organization_id=ctx.organization_id,
        rab_id=rab.id,
        version_no=1,
        status=RabStatus.DRAFT,
        currency=source.currency,
        tax_label=source.tax_label,
        tax_rate_percent=source.tax_rate_percent,
        discount_type=source.discount_type,
        discount_value=source.discount_value,
        notes=source.notes,
        assumptions=source.assumptions,
        created_by_id=ctx.user_id,
    )
    db.add(version)
    _copy_items(source, version, ctx.organization_id)
    recalculate(version)
    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="rab.duplicate",
        entity_type="rab",
        entity_id=rab.id,
        summary=f"{rab.number} dari {source_rab.number} v{source.version_no}",
        ip_address=ctx.ip_address,
    )
    db.commit()
    return get_rab(db, ctx, rab.id)


# --------------------------------------------------------------------------- read models


def approvals_of(db: Session, ctx: RequestContext, version: RabVersion) -> list[ApprovalRecord]:
    return list(
        db.execute(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.organization_id == ctx.organization_id,
                ApprovalRecord.entity_type == ENTITY_VERSION,
                ApprovalRecord.entity_id == version.id,
            )
            .order_by(ApprovalRecord.created_at)
        ).scalars()
    )


def _compare_item(item: RabItem) -> CompareItem:
    return CompareItem(
        code=item.code,
        name=item.name,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        subtotal=item.subtotal,
        item_type=item.item_type.value,
        specification=item.specification,
    )


def compare_versions(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, from_no: int, to_no: int
) -> schemas.CompareOut:
    before = get_version(db, ctx, rab_id, from_no)
    after = get_version(db, ctx, rab_id, to_no)
    changes = compare_items(
        [_compare_item(i) for i in before.items], [_compare_item(i) for i in after.items]
    )
    lines = [
        schemas.CompareLine(
            kind=c.kind,
            code=c.current.code,
            name=c.current.name,
            unit=c.current.unit,
            before_quantity=c.before.quantity if c.before else None,
            after_quantity=c.after.quantity if c.after else None,
            before_unit_price=c.before.unit_price if c.before else None,
            after_unit_price=c.after.unit_price if c.after else None,
            before_subtotal=c.before.subtotal if c.before else None,
            after_subtotal=c.after.subtotal if c.after else None,
            subtotal_delta=c.subtotal_delta,
            changed_fields=c.changed_fields,
        )
        for c in changes
    ]
    return schemas.CompareOut(
        from_version_no=from_no,
        to_version_no=to_no,
        currency=after.currency,
        lines=lines,
        before_totals=schemas.Totals.model_validate(before),
        after_totals=schemas.Totals.model_validate(after),
        grand_total_delta=after.grand_total - before.grand_total,
    )


def pending_approvals(db: Session, ctx: RequestContext) -> list[tuple[RabDocument, RabVersion]]:
    rows = (
        db.execute(
            select(RabDocument, RabVersion)
            .join(RabVersion, RabVersion.rab_id == RabDocument.id)
            .where(
                RabDocument.organization_id == ctx.organization_id,
                RabVersion.status == RabStatus.IN_REVIEW,
            )
            .order_by(RabVersion.submitted_at)
        )
        .unique()
        .all()
    )
    return [(rab, version) for rab, version in rows]
