"""Frozen data for SPK and BAST documents (same principles as documents/snapshot.py).

Every value is copied from stored records and re-checked before rendering: the SPK's contract
value must equal its (issued, accepted) quotation, and a BAST's cumulative volumes may not exceed
the contract. Signatory names and terms are only what users typed — nothing is generated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.modules.approvals.models import ApprovalRecord
from app.modules.billing.models import Quotation
from app.modules.billing.snapshots import (
    amount_words,
    approval_values,
    document_values,
    payment_term_values,
)
from app.modules.billing.workflow import STATUS_LABELS
from app.modules.documents.models import DocumentSettings, DocumentType
from app.modules.documents.snapshot import (
    PROJECT_TYPE_LABELS,
    SCHEMA_VERSION,
    Issuance,
    SnapshotIntegrityError,
    client_values,
    company_values,
    dec,
    iso,
    settings_values,
)
from app.modules.identity.models import Organization
from app.modules.rab.models import RabDocument, RabVersion
from app.modules.workorders.models import Bast, BastKind, Spk
from app.modules.workorders.progress import ZERO, ContractItem

SPK_TITLE = "Surat Perintah Kerja"
BAST_TITLE = "Berita Acara Serah Terima"
BAST_KIND_LABELS = {
    BastKind.PARTIAL: "Serah terima sebagian",
    BastKind.FINAL: "Serah terima akhir",
}


def _approved(status_value: str) -> bool:
    return status_value in ("approved", "issued")


def _project(spk: Spk) -> dict[str, Any]:
    project = spk.project
    return {
        "number": project.number,
        "name": project.name,
        "type_label": PROJECT_TYPE_LABELS[project.project_type],
        "location": project.location,
    }


def build_spk_snapshot(
    *,
    organization: Organization,
    settings_row: DocumentSettings | None,
    spk: Spk,
    quotation: Quotation,
    rab: RabDocument,
    version: RabVersion,
    approvals: list[ApprovalRecord],
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    if spk.contract_value != quotation.grand_total or spk.currency != quotation.currency:
        raise SnapshotIntegrityError("Nilai SPK tidak sesuai dengan penawaran sumbernya.")
    if quotation.taxable_base + quotation.tax_amount != quotation.grand_total:
        raise SnapshotIntegrityError("Total penawaran sumber tidak konsisten.")
    if quotation.payment_terms and (
        sum(t.total_amount for t in quotation.payment_terms) != quotation.grand_total
    ):
        raise SnapshotIntegrityError("Jumlah termin tidak sama dengan nilai kontrak.")

    settings = settings_values(settings_row)
    approved = _approved(spk.status.value)
    has_tax = quotation.tax_label is not None and quotation.tax_rate_percent is not None
    items = sorted(version.items, key=lambda i: i.position)
    return {
        "schema_version": SCHEMA_VERSION,
        "document": document_values(DocumentType.SPK, SPK_TITLE, None, issuance, generated_at),
        "company": company_values(organization),
        "client": client_values(spk.client),
        "project": _project(spk),
        "spk": {
            "title": spk.title,
            "issue_date": spk.issue_date.isoformat() if spk.issue_date else None,
            "start_date": spk.start_date.isoformat() if spk.start_date else None,
            "end_date": spk.end_date.isoformat() if spk.end_date else None,
            "location": spk.location,
            "scope": spk.scope,
            "terms": spk.terms,
            "notes": spk.notes,
            "status_label": STATUS_LABELS[spk.status],
            "client_signatory": {
                "name": spk.client_signatory_name,
                "title": spk.client_signatory_title,
            },
            "company_signatory": {
                "name": spk.company_signatory_name,
                "title": spk.company_signatory_title,
            },
            "prepared_by": spk.submitted_by.full_name if spk.submitted_by else None,
            "submitted_at": iso(spk.submitted_at),
            "approved_by": spk.decided_by.full_name if approved and spk.decided_by else None,
            "approved_at": iso(spk.decided_at) if approved else None,
            "quotation_number": quotation.number,
            "quotation_subject": quotation.subject,
            "rab_number": rab.number,
            "rab_version_no": version.version_no,
        },
        "currency": spk.currency,
        "contract": {
            "taxable_base": dec(quotation.taxable_base),
            "tax_label": quotation.tax_label if has_tax else None,
            "tax_rate_percent": dec(quotation.tax_rate_percent) if has_tax else None,
            "tax_amount": dec(quotation.tax_amount),
            "contract_value": dec(spk.contract_value),
            "amount_in_words": amount_words(settings, spk.currency, spk.contract_value),
        },
        # The approved scope as volumes (prices are in the quotation it refers to).
        "items": [
            {
                "no": no,
                "code": item.code,
                "name": item.name,
                "category": item.category,
                "specification": item.specification,
                "quantity": dec(item.quantity),
                "unit": item.unit,
            }
            for no, item in enumerate(items, start=1)
        ],
        "payment_terms": payment_term_values(quotation.payment_terms),
        "approvals": approval_values(approvals),
        "settings": settings,
    }


def build_bast_snapshot(
    *,
    organization: Organization,
    settings_row: DocumentSettings | None,
    bast: Bast,
    spk: Spk,
    contract: dict[uuid.UUID, ContractItem],
    delivered_before: dict[uuid.UUID, Decimal],
    approvals: list[ApprovalRecord],
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(bast.items, start=1):
        ref: dict[str, Any] | None = None
        if line.rab_item_id is not None:
            c = contract.get(line.rab_item_id)
            if c is None:
                raise SnapshotIntegrityError("Baris BAST merujuk item di luar kontrak SPK.")
            before = delivered_before.get(line.rab_item_id, ZERO)
            cumulative = before + line.quantity
            if cumulative > c.item.quantity:
                raise SnapshotIntegrityError(
                    f"Volume kumulatif item kontrak no. {c.no} melebihi volume kontrak."
                )
            ref = {
                "no": c.no,
                "code": c.item.code,
                "contract_quantity": dec(c.item.quantity),
                "delivered_before": dec(before),
                "cumulative": dec(cumulative),
            }
        lines.append(
            {
                "no": index,
                "description": line.description,
                "quantity": dec(line.quantity),
                "unit": line.unit,
                "condition": line.condition,
                "contract": ref,
            }
        )

    settings = settings_values(settings_row)
    approved = _approved(bast.status.value)
    return {
        "schema_version": SCHEMA_VERSION,
        "document": document_values(DocumentType.BAST, BAST_TITLE, None, issuance, generated_at),
        "company": company_values(organization),
        "client": client_values(spk.client),
        "project": _project(spk),
        "bast": {
            "kind": bast.kind.value,
            "kind_label": BAST_KIND_LABELS[bast.kind],
            "title": bast.title,
            "handover_date": bast.handover_date.isoformat() if bast.handover_date else None,
            "location": bast.location,
            "delivered_by": {"name": bast.delivered_by_name, "title": bast.delivered_by_title},
            "received_by": {"name": bast.received_by_name, "title": bast.received_by_title},
            "terms": bast.terms,
            "notes": bast.notes,
            "status_label": STATUS_LABELS[bast.status],
            "prepared_by": bast.submitted_by.full_name if bast.submitted_by else None,
            "submitted_at": iso(bast.submitted_at),
            "approved_by": bast.decided_by.full_name if approved and bast.decided_by else None,
            "approved_at": iso(bast.decided_at) if approved else None,
            "spk_number": spk.number,
            "spk_title": spk.title,
            "quotation_number": spk.quotation.number,
        },
        "lines": lines,
        "approvals": approval_values(approvals),
        "settings": settings,
    }
