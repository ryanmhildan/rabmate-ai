"""Tools the assistant workflows may use to read business data (ADR-041).

Every tool has a Pydantic input and output schema (unknown fields rejected), a permission checked
against the requesting user, and appears in a per-workflow allowlist. All tools are read-only:
the assistant has no tool that writes, approves or issues anything — changes happen only when a
user applies a reviewed draft. Calls are logged by name, outcome and duration, never by content.

In the current `structured` mode the backend calls these tools itself to assemble the context it
sends to the model; the same registry is the contract for exposing tools to Hermes over MCP later.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import ColumnElement, case, literal, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext
from app.core.errors import AppError, BusinessValidationError, PermissionDeniedError
from app.core.pagination import escape_like
from app.modules.assistant.models import AiRunKind
from app.modules.billing.models import Invoice, Quotation
from app.modules.documents import formatting as fmt
from app.modules.documents.snapshot import PROJECT_TYPE_LABELS
from app.modules.identity.permissions import Permission
from app.modules.intake import service as intake
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceCatalogItem, VerificationStatus
from app.modules.projects import service as projects
from app.modules.rab import service as rab_service
from app.modules.rab.models import RabDocument, RabItem
from app.modules.workorders.models import Bast, Spk

logger = logging.getLogger(__name__)

MAX_LISTED_ITEMS = 200


class ToolNotAllowedError(AppError):
    status_code = 403
    code = "ai_tool_not_allowed"
    message = "Tool ini tidak diizinkan untuk alur asisten tersebut."


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- schemas


class ProjectDetailsIn(StrictInput):
    project_id: uuid.UUID


class ProjectDetailsOut(BaseModel):
    number: str
    name: str
    project_type: str
    project_type_label: str
    location: str | None
    currency: str
    tax_label: str | None
    tax_rate_percent: str | None
    description: str | None
    scope: str | None


class RabVersionIn(StrictInput):
    rab_id: uuid.UUID
    version_no: int = Field(ge=1)


class RabItemBrief(BaseModel):
    no: int
    name: str
    category: str | None
    quantity: str
    unit: str
    priced: bool


class RabVersionOut(BaseModel):
    number: str
    title: str
    version_no: int
    status: str
    currency: str
    item_count: int
    items: list[RabItemBrief]  # first MAX_LISTED_ITEMS, by position


class SourceDocumentIn(StrictInput):
    source_document_id: uuid.UUID


class SourceDocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    kind: str
    size_bytes: int
    sha256: str


# --------------------------------------------------------------------------- handlers


def _project_details(db: Session, ctx: RequestContext, args: ProjectDetailsIn) -> ProjectDetailsOut:
    project = projects.get_project(db, ctx, args.project_id)
    return ProjectDetailsOut(
        number=project.number,
        name=project.name,
        project_type=project.project_type.value,
        project_type_label=PROJECT_TYPE_LABELS[project.project_type],
        location=project.location,
        currency=project.currency,
        tax_label=project.tax_label,
        tax_rate_percent=format(project.tax_rate_percent, "f")
        if project.tax_rate_percent is not None
        else None,
        description=project.description[:1000] if project.description else None,
        scope=project.scope[:2000] if project.scope else None,
    )


def _rab_version(db: Session, ctx: RequestContext, args: RabVersionIn) -> RabVersionOut:
    version = rab_service.get_version(db, ctx, args.rab_id, args.version_no)
    items = sorted(version.items, key=lambda i: i.position)
    return RabVersionOut(
        number=version.rab.number,
        title=version.rab.title,
        version_no=version.version_no,
        status=version.status.value,
        currency=version.currency,
        item_count=len(items),
        items=[
            RabItemBrief(
                no=no,
                name=item.name,
                category=item.category,
                quantity=format(item.quantity.normalize(), "f"),
                unit=item.unit,
                priced=item.unit_price is not None,
            )
            for no, item in enumerate(items[:MAX_LISTED_ITEMS], start=1)
        ],
    )


def _source_document(db: Session, ctx: RequestContext, args: SourceDocumentIn) -> SourceDocumentOut:
    doc = intake.get(db, ctx, args.source_document_id)
    return SourceDocumentOut(
        id=doc.id,
        project_id=doc.project_id,
        filename=doc.filename,
        kind=doc.kind.value,
        size_bytes=doc.size_bytes,
        sha256=doc.sha256,
    )


# --------------------------------------------------------------------------- chat retrieval


class RabLine(BaseModel):
    no: int
    name: str
    quantity: str
    unit: str
    unit_price: str | None
    subtotal: str | None
    price_source: str | None


class RabSummary(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    version_no: int
    status: str
    subtotal: str
    tax: str | None
    grand_total: str
    item_count: int
    unpriced_items: int
    unpriced_names: list[str]  # every item still without a unit price (first 30)
    items: list[RabLine]  # first MAX_CHAT_RAB_ITEMS, by position


class ProjectRabsOut(BaseModel):
    rab_count: int
    rabs: list[RabSummary]  # latest version of the most recently updated MAX_CHAT_RABS


class CatalogSearchIn(StrictInput):
    query: str = Field(min_length=2, max_length=300)


class CatalogPrice(BaseModel):
    price: str
    unit: str
    observed_at: date
    status: str  # terverifikasi / belum diverifikasi
    supplier: str | None
    source_reference: str | None


class CatalogHit(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None
    brand: str | None
    unit: str
    specification: str | None
    price: CatalogPrice | None  # latest verified price, else the latest not rejected


class CatalogSearchOut(BaseModel):
    terms: list[str]
    items: list[CatalogHit]


class DocumentBrief(BaseModel):
    kind: str
    number: str | None
    title: str
    status: str
    amount: str | None
    details: str | None


class ProjectDocumentsOut(BaseModel):
    documents: list[DocumentBrief]


# --------------------------------------------------------------------------- chat handlers

MAX_CHAT_RABS = 3
MAX_CHAT_RAB_ITEMS = 60
MAX_CATALOG_HITS = 8
MAX_DOCUMENTS = 30
# Words that say nothing about which catalog item is meant.
_STOPWORD_TEXT = """
yang dan atau untuk dengan dari pada dalam akan ada apa apakah berapa bagaimana kapan mana siapa
bisa tolong mohon saya kami kita ini itu juga sudah belum harga biaya total proyek katalog item
barang per sebuah satu buah tersebut adalah jadi lebih kurang terbaru terakhir sekarang saja
punya masih semua setiap tiap kalau jika agar supaya berikan sebutkan tampilkan jelaskan daftar
rab grand subtotal pajak ppn status versi draft disetujui penawaran invoice spk bast dokumen
harganya biayanya verifikasi diverifikasi terverifikasi
the for and price cost
"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _source_text(item: RabItem) -> str | None:
    if item.price_source_type is None:
        return None
    label = item.price_source_type.value
    return f"{label}: {item.price_source}"[:300] if item.price_source else label


def _project_rabs(db: Session, ctx: RequestContext, args: ProjectDetailsIn) -> ProjectRabsOut:
    projects.get_project(db, ctx, args.project_id)
    rabs = list(
        db.execute(
            select(RabDocument)
            .where(
                RabDocument.organization_id == ctx.organization_id,
                RabDocument.project_id == args.project_id,
            )
            .order_by(RabDocument.updated_at.desc())
        )
        .unique()
        .scalars()
    )
    summaries: list[RabSummary] = []
    for rab in rabs[:MAX_CHAT_RABS]:
        version = max(rab.versions, key=lambda v: v.version_no, default=None)
        if version is None:
            continue
        items = sorted(version.items, key=lambda i: i.position)
        currency = version.currency
        summaries.append(
            RabSummary(
                id=rab.id,
                number=rab.number,
                title=rab.title,
                version_no=version.version_no,
                status=version.status.value,
                subtotal=fmt.money(version.subtotal, currency),
                tax=fmt.money(version.tax_amount, currency) if version.tax_amount else None,
                grand_total=fmt.money(version.grand_total, currency),
                item_count=len(items),
                unpriced_items=version.unpriced_items,
                unpriced_names=[i.name for i in items if i.unit_price is None][:30],
                items=[
                    RabLine(
                        no=no,
                        name=item.name,
                        quantity=fmt.number(item.quantity, max_places=4),
                        unit=item.unit,
                        unit_price=fmt.unit_price(item.unit_price, currency)
                        if item.unit_price is not None
                        else None,
                        subtotal=fmt.money(item.subtotal, currency)
                        if item.subtotal is not None
                        else None,
                        price_source=_source_text(item),
                    )
                    for no, item in enumerate(items[:MAX_CHAT_RAB_ITEMS], start=1)
                ],
            )
        )
    return ProjectRabsOut(rab_count=len(rabs), rabs=summaries)


def search_terms(query: str) -> list[str]:
    words = re.findall(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ\-/.]*", query.lower())
    terms = [w.strip(".-/") for w in words if len(w) >= 3 and w not in _STOPWORDS]
    return list(dict.fromkeys(t for t in terms if t))[:6]


def _catalog_search(db: Session, ctx: RequestContext, args: CatalogSearchIn) -> CatalogSearchOut:
    terms = search_terms(args.query)
    if not terms:
        return CatalogSearchOut(terms=[], items=[])
    columns = (
        PriceCatalogItem.name,
        PriceCatalogItem.code,
        PriceCatalogItem.brand,
        PriceCatalogItem.specification,
    )
    matches = [
        column.ilike(f"%{escape_like(term)}%", escape="\\") for term in terms for column in columns
    ]
    # Rank by how many search words the name itself contains.
    hits: ColumnElement[int] = literal(0)
    for term in terms:
        named = PriceCatalogItem.name.ilike(f"%{escape_like(term)}%", escape="\\")
        hits = hits + case((named, 1), else_=0)
    items = list(
        db.execute(
            select(PriceCatalogItem)
            .where(
                PriceCatalogItem.organization_id == ctx.organization_id,
                PriceCatalogItem.is_active.is_(True),
                or_(*matches),
            )
            .order_by(hits.desc(), PriceCatalogItem.name)
            .limit(MAX_CATALOG_HITS)
        ).scalars()
    )
    found = pricing.summaries(db, ctx, [i.id for i in items])
    out: list[CatalogHit] = []
    for item in items:
        summary = found[item.id]
        observation = summary.latest_verified or summary.latest_any
        price = None
        if observation is not None:
            verified = observation.verification_status is VerificationStatus.VERIFIED
            price = CatalogPrice(
                price=fmt.unit_price(observation.price, observation.currency),
                unit=observation.unit,
                observed_at=observation.observed_at,
                status="terverifikasi" if verified else "belum diverifikasi",
                supplier=observation.supplier.name if observation.supplier else None,
                source_reference=observation.source_reference,
            )
        out.append(
            CatalogHit(
                id=item.id,
                name=item.name,
                code=item.code,
                brand=item.brand,
                unit=item.unit,
                specification=item.specification[:300] if item.specification else None,
                price=price,
            )
        )
    return CatalogSearchOut(terms=terms, items=out)


def _project_documents(
    db: Session, ctx: RequestContext, args: ProjectDetailsIn
) -> ProjectDocumentsOut:
    projects.get_project(db, ctx, args.project_id)
    docs: list[DocumentBrief] = []
    org = ctx.organization_id
    if ctx.can(Permission.RAB_READ):  # quotations are read with the RAB they price
        for q in db.execute(
            select(Quotation)
            .where(Quotation.organization_id == org, Quotation.project_id == args.project_id)
            .order_by(Quotation.created_at.desc())
            .limit(MAX_DOCUMENTS)
        ).scalars():
            response = f"respons klien: {q.client_response.value}" if q.client_response else None
            valid = f"berlaku s.d. {q.valid_until.isoformat()}" if q.valid_until else None
            docs.append(
                DocumentBrief(
                    kind="penawaran",
                    number=q.number,
                    title=q.subject,
                    status=q.status.value,
                    amount=fmt.money(q.grand_total, q.currency),
                    details="; ".join(p for p in (response, valid) if p) or None,
                )
            )
    for spk in db.execute(
        select(Spk)
        .where(Spk.organization_id == org, Spk.project_id == args.project_id)
        .order_by(Spk.created_at.desc())
        .limit(MAX_DOCUMENTS)
    ).scalars():
        period = (
            f"{spk.start_date.isoformat()} s.d. {spk.end_date.isoformat()}"
            if spk.start_date and spk.end_date
            else None
        )
        docs.append(
            DocumentBrief(
                kind="spk",
                number=spk.number,
                title=spk.title,
                status=spk.status.value,
                amount=fmt.money(spk.contract_value, spk.currency),
                details=period,
            )
        )
        for bast in db.execute(
            select(Bast)
            .where(Bast.organization_id == org, Bast.spk_id == spk.id)
            .order_by(Bast.created_at.desc())
        ).scalars():
            docs.append(
                DocumentBrief(
                    kind=f"bast ({bast.kind.value})",
                    number=bast.number,
                    title=bast.title,
                    status=bast.status.value,
                    amount=None,
                    details=f"serah terima {bast.handover_date.isoformat()}"
                    if bast.handover_date
                    else None,
                )
            )
    if ctx.can(Permission.FINANCE_READ):  # payment state comes from recorded payments only
        for inv in db.execute(
            select(Invoice)
            .where(Invoice.organization_id == org, Invoice.project_id == args.project_id)
            .order_by(Invoice.created_at.desc())
            .limit(MAX_DOCUMENTS)
        ).scalars():
            due = f"jatuh tempo {inv.due_date.isoformat()}" if inv.due_date else None
            paid = f"terbayar {fmt.money(inv.amount_paid, inv.currency)} (dari catatan pembayaran)"
            docs.append(
                DocumentBrief(
                    kind="invoice",
                    number=inv.number,
                    title=inv.title,
                    status=inv.status.value,
                    amount=fmt.money(inv.grand_total, inv.currency),
                    details="; ".join(p for p in (paid, due) if p),
                )
            )
    return ProjectDocumentsOut(documents=docs[: MAX_DOCUMENTS * 2])


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permission: Permission
    input_model: type[StrictInput]
    output_model: type[BaseModel]
    handler: Callable[[Session, RequestContext, Any], BaseModel]
    access: Literal["read"] = "read"


REGISTRY: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            name="get_project_details",
            description="Data proyek: jenis, lokasi, mata uang, pajak, deskripsi, lingkup.",
            permission=Permission.PROJECTS_READ,
            input_model=ProjectDetailsIn,
            output_model=ProjectDetailsOut,
            handler=_project_details,
        ),
        Tool(
            name="get_rab_version",
            description="Ringkasan versi RAB: status dan daftar item (nama, volume, satuan).",
            permission=Permission.RAB_READ,
            input_model=RabVersionIn,
            output_model=RabVersionOut,
            handler=_rab_version,
        ),
        Tool(
            name="get_source_document",
            description="Identitas dokumen sumber yang diunggah ke proyek (nama, jenis, ukuran).",
            permission=Permission.RAB_READ,
            input_model=SourceDocumentIn,
            output_model=SourceDocumentOut,
            handler=_source_document,
        ),
        Tool(
            name="get_project_rabs",
            description="RAB proyek (versi terakhir): total, item, harga satuan, dan sumber harga.",
            permission=Permission.RAB_READ,
            input_model=ProjectDetailsIn,
            output_model=ProjectRabsOut,
            handler=_project_rabs,
        ),
        Tool(
            name="search_catalog",
            description="Cari katalog: harga terbaru beserta status verifikasi dan sumbernya.",
            permission=Permission.PRICING_READ,
            input_model=CatalogSearchIn,
            output_model=CatalogSearchOut,
            handler=_catalog_search,
        ),
        Tool(
            name="get_project_documents",
            description="Penawaran, SPK, BAST, dan (dengan izin keuangan) invoice proyek.",
            permission=Permission.PROJECTS_READ,
            input_model=ProjectDetailsIn,
            output_model=ProjectDocumentsOut,
            handler=_project_documents,
        ),
    )
}

ALLOWLIST: dict[AiRunKind, frozenset[str]] = {
    AiRunKind.RAB_DRAFT: frozenset({"get_project_details", "get_rab_version"}),
    AiRunKind.EXTRACT_ITEMS: frozenset({"get_rab_version"}),
    AiRunKind.EXTRACT_DOCUMENT: frozenset({"get_rab_version", "get_source_document"}),
    AiRunKind.CHAT_ANSWER: frozenset(
        {"get_project_details", "get_project_rabs", "search_catalog", "get_project_documents"}
    ),
}


def call_tool(
    db: Session,
    ctx: RequestContext,
    workflow: AiRunKind,
    name: str,
    args: Mapping[str, Any],
) -> BaseModel:
    """Runs one allowlisted tool for `ctx`'s user; never with more rights than the user has."""
    tool = REGISTRY.get(name)
    if tool is None or name not in ALLOWLIST.get(workflow, frozenset()):
        logger.warning("ai tool refused: %s (workflow %s)", name, workflow.value)
        raise ToolNotAllowedError(details={"tool": name, "workflow": workflow.value})
    if not ctx.can(tool.permission):
        logger.warning("ai tool denied: %s (missing %s)", name, tool.permission.value)
        raise PermissionDeniedError(details={"tool": name, "permission": tool.permission.value})
    try:
        parsed = tool.input_model.model_validate(dict(args))
    except ValidationError as exc:
        raise BusinessValidationError(
            "Parameter tool tidak valid.",
            details=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        ) from None
    started = time.perf_counter()
    try:
        output = tool.handler(db, ctx, parsed)
    except AppError:
        logger.info("ai tool %s failed in %d ms", name, (time.perf_counter() - started) * 1000)
        raise
    logger.info("ai tool %s ok in %d ms", name, (time.perf_counter() - started) * 1000)
    return tool.output_model.model_validate(output.model_dump())
