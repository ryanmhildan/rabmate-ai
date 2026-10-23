"""Builds the frozen data of a RAB document (the "snapshot").

Everything a rendered document shows comes from this dict: values, names, and even display
labels, so an issued document keeps meaning the same thing after code or data changes. Money stays
as decimal strings. The only arithmetic here is summing already-rounded item subtotals per
category, and the totals are re-derived with the RAB calculation module and must match what the
version stored — a mismatch aborts issuance instead of printing inconsistent numbers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.modules.approvals.models import ApprovalAction, ApprovalRecord
from app.modules.clients.models import Client
from app.modules.documents.models import DEFAULT_ACCENT_COLOR, DocumentSettings, DocumentType
from app.modules.documents.terbilang import rupiah_in_words
from app.modules.identity.models import Organization
from app.modules.projects.models import Project, ProjectType
from app.modules.rab.calculation import Adjustments, LineInput, calculate
from app.modules.rab.models import (
    PriceSourceType,
    RabDocument,
    RabItemType,
    RabStatus,
    RabVersion,
)

SCHEMA_VERSION = 1
RAB_TITLE = "Rencana Anggaran Biaya"
UNCATEGORIZED = "Lain-lain"

# Display labels (capitalized), as on screen; lifecycle.STATUS_LABELS are in-sentence words.
STATUS_LABELS: dict[RabStatus, str] = {
    RabStatus.DRAFT: "Draft",
    RabStatus.IN_REVIEW: "Menunggu review",
    RabStatus.APPROVED: "Disetujui",
    RabStatus.REJECTED: "Ditolak",
    RabStatus.ARCHIVED: "Diarsipkan",
}

ITEM_TYPE_LABELS: dict[RabItemType, str] = {
    RabItemType.MATERIAL: "Material/barang",
    RabItemType.LABOR: "Tenaga kerja",
    RabItemType.SERVICE: "Jasa",
    RabItemType.EQUIPMENT: "Peralatan",
    RabItemType.TRANSPORT: "Transportasi",
    RabItemType.OVERHEAD: "Overhead",
    RabItemType.OTHER: "Lain-lain",
}

PRICE_SOURCE_LABELS: dict[PriceSourceType, str] = {
    PriceSourceType.MANUAL: "Input manual",
    PriceSourceType.CATALOG: "Katalog internal",
    PriceSourceType.HISTORY: "Riwayat proyek",
    PriceSourceType.VENDOR_QUOTE: "Penawaran vendor",
    PriceSourceType.IMPORT: "Impor spreadsheet/dokumen",
    PriceSourceType.EXTERNAL: "Sumber eksternal",
}

PROJECT_TYPE_LABELS: dict[ProjectType, str] = {
    ProjectType.CONSTRUCTION: "Konstruksi & renovasi",
    ProjectType.FABRICATION: "Fabrikasi & mekanik",
    ProjectType.PROCUREMENT: "Pengadaan barang",
    ProjectType.IT: "IT & perangkat lunak",
    ProjectType.PROFESSIONAL_SERVICES: "Jasa profesional",
    ProjectType.OPERATIONS: "Operasional",
    ProjectType.OTHER: "Lainnya",
}

APPROVAL_LABELS: dict[ApprovalAction, str] = {
    ApprovalAction.SUBMITTED: "Diajukan untuk review",
    ApprovalAction.WITHDRAWN: "Pengajuan ditarik",
    ApprovalAction.APPROVED: "Disetujui",
    ApprovalAction.REJECTED: "Ditolak",
    ApprovalAction.REOPENED: "Dibuka kembali",
    ApprovalAction.ARCHIVED: "Diarsipkan",
    ApprovalAction.SUPERSEDED: "Digantikan versi baru",
}


class SnapshotIntegrityError(RuntimeError):
    """Stored totals disagree with a fresh calculation; the document must not be produced."""


@dataclass(frozen=True)
class Issuance:
    number: str
    issued_at: datetime
    issued_by: str


def settings_values(row: DocumentSettings | None) -> dict[str, Any]:
    """Template settings as plain values (defaults when the organization never saved any)."""
    return {
        "tagline": row.tagline if row else None,
        "accent_color": row.accent_color if row else DEFAULT_ACCENT_COLOR,
        "footer_text": row.footer_text if row else None,
        "terms": row.rab_terms if row else None,
        "show_item_codes": row.show_item_codes if row else True,
        "show_price_sources": row.show_price_sources if row else False,
        "show_amount_in_words": row.show_amount_in_words if row else True,
    }


def dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def company_values(org: Organization) -> dict[str, Any]:
    return {
        "name": org.name,
        "legal_name": org.legal_name,
        "tax_id": org.tax_id,
        "address": org.address,
        "city": org.city,
        "phone": org.phone,
        "email": org.email,
        "website": org.website,
    }


def client_values(client: Client | None) -> dict[str, Any] | None:
    if client is None:
        return None
    return {
        "name": client.name,
        "code": client.code,
        "contact_person": client.contact_person,
        "address": client.address,
        "city": client.city,
        "phone": client.phone,
        "email": client.email,
        "tax_id": client.tax_id,
    }


def _check_totals(version: RabVersion) -> None:
    fresh = calculate(
        (LineInput(i.quantity, i.unit_price) for i in version.items),
        Adjustments(
            discount_type=version.discount_type,
            discount_value=version.discount_value,
            tax_rate_percent=version.tax_rate_percent,
        ),
    )
    stored = (
        version.subtotal,
        version.discount_amount,
        version.taxable_base,
        version.tax_amount,
        version.grand_total,
        version.unpriced_items,
    )
    computed = (
        fresh.subtotal,
        fresh.discount_amount,
        fresh.taxable_base,
        fresh.tax_amount,
        fresh.grand_total,
        fresh.unpriced_items,
    )
    if stored != computed:
        raise SnapshotIntegrityError("Total RAB tersimpan tidak sesuai dengan perhitungan ulang.")


def items_and_groups(
    version: RabVersion,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Item rows (numbered by position) and category groups summing already-rounded subtotals."""
    items = sorted(version.items, key=lambda i: i.position)

    item_rows: list[dict[str, Any]] = []
    for number, item in enumerate(items, start=1):
        item_rows.append(
            {
                "no": number,
                "code": item.code,
                "name": item.name,
                "category": item.category,
                "item_type": item.item_type.value,
                "item_type_label": ITEM_TYPE_LABELS[item.item_type],
                "specification": item.specification,
                "quantity": dec(item.quantity),
                "unit": item.unit,
                "unit_price": dec(item.unit_price),
                "subtotal": dec(item.subtotal),
                "price_source_type": item.price_source_type.value
                if item.price_source_type
                else None,
                "price_source_label": PRICE_SOURCE_LABELS[item.price_source_type]
                if item.price_source_type
                else None,
                "price_source": item.price_source,
                "notes": item.notes,
            }
        )

    # Category groups in order of first appearance; uncategorized items share one group, which is
    # only titled when other categories exist.
    categorized = any(row["category"] for row in item_rows)
    groups: list[dict[str, Any]] = []
    by_title: dict[str | None, dict[str, Any]] = {}
    for row in item_rows:
        title = row["category"] or (UNCATEGORIZED if categorized else None)
        group = by_title.get(title)
        if group is None:
            group = {"title": title, "items": [], "subtotal": Decimal("0.00")}
            by_title[title] = group
            groups.append(group)
        group["items"].append(row)
        if row["subtotal"] is not None:
            group["subtotal"] += Decimal(row["subtotal"])
    return item_rows, [
        {
            "title": g["title"],
            "subtotal": dec(g["subtotal"]),
            "item_numbers": [i["no"] for i in g["items"]],
        }
        for g in groups
    ]


def build_rab_snapshot(
    *,
    organization: Organization,
    settings: dict[str, Any],
    rab: RabDocument,
    project: Project,
    version: RabVersion,
    approvals: list[ApprovalRecord],
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    _check_totals(version)
    item_rows, groups = items_and_groups(version)

    decided = version.decided_by.full_name if version.decided_by else None
    approved_at = (
        version.decided_at if version.status in (RabStatus.APPROVED, RabStatus.ARCHIVED) else None
    )
    has_tax = version.tax_label is not None and version.tax_rate_percent is not None
    words = None
    if settings["show_amount_in_words"] and version.currency == "IDR":
        words = rupiah_in_words(version.grand_total)

    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "type": DocumentType.RAB.value,
            "title": RAB_TITLE,
            "number": issuance.number if issuance else None,
            "issued_at": iso(issuance.issued_at) if issuance else None,
            "issued_by": issuance.issued_by if issuance else None,
            "preview": issuance is None,
            "generated_at": iso(generated_at),
        },
        "company": company_values(organization),
        "client": client_values(project.client),
        "project": {
            "number": project.number,
            "name": project.name,
            "type_label": PROJECT_TYPE_LABELS[project.project_type],
            "location": project.location,
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "end_date": project.end_date.isoformat() if project.end_date else None,
        },
        "rab": {
            "id": str(rab.id),
            "number": rab.number,
            "title": rab.title,
            "version_id": str(version.id),
            "version_no": version.version_no,
            "status": version.status.value,
            "status_label": STATUS_LABELS[version.status],
            "currency": version.currency,
            "notes": version.notes,
            "assumptions": version.assumptions,
            "prepared_by": version.submitted_by.full_name if version.submitted_by else None,
            "submitted_at": iso(version.submitted_at),
            "approved_by": decided if approved_at else None,
            "approved_at": iso(approved_at),
        },
        "items": item_rows,
        "groups": groups,
        "totals": {
            "subtotal": dec(version.subtotal),
            "discount_type": version.discount_type.value,
            "discount_value": dec(version.discount_value),
            "discount_amount": dec(version.discount_amount),
            "taxable_base": dec(version.taxable_base),
            "tax_label": version.tax_label if has_tax else None,
            "tax_rate_percent": dec(version.tax_rate_percent) if has_tax else None,
            "tax_amount": dec(version.tax_amount),
            "grand_total": dec(version.grand_total),
            "unpriced_items": version.unpriced_items,
            "amount_in_words": words,
        },
        "approvals": [
            {
                "action": record.action.value,
                "label": APPROVAL_LABELS[record.action],
                "actor": record.actor.full_name if record.actor else None,
                "at": iso(record.created_at),
                "note": record.note,
            }
            for record in approvals
        ],
        "settings": settings,
    }


def canonical_json(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot)).hexdigest()
