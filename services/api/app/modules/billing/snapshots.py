"""Frozen data for quotation and invoice documents (same principles as documents/snapshot.py).

Every figure is copied from stored, already-validated values and re-checked before rendering:
quotation totals must equal the approved RAB version they came from, a term invoice must equal
its payment term, and a manual invoice must equal a fresh calculation of its lines.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.modules.approvals.models import ApprovalRecord
from app.modules.billing.invoicing import manual_totals
from app.modules.billing.models import (
    Invoice,
    InvoiceKind,
    PaymentTerm,
    Quotation,
    TermBasis,
)
from app.modules.billing.workflow import STATUS_LABELS
from app.modules.documents.models import DocumentSettings, DocumentType
from app.modules.documents.snapshot import (
    APPROVAL_LABELS,
    PROJECT_TYPE_LABELS,
    SCHEMA_VERSION,
    Issuance,
    SnapshotIntegrityError,
    client_values,
    company_values,
    dec,
    iso,
    items_and_groups,
    settings_values,
)
from app.modules.documents.terbilang import rupiah_in_words
from app.modules.identity.models import Organization
from app.modules.rab.models import RabDocument, RabVersion

QUOTATION_TITLE = "Surat Penawaran Harga"
INVOICE_TITLE = "Invoice"


def document_values(
    doc_type: DocumentType,
    title: str,
    number: str | None,
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "type": doc_type.value,
        "title": title,
        "number": issuance.number if issuance else number,
        "issued_at": iso(issuance.issued_at) if issuance else None,
        "issued_by": issuance.issued_by if issuance else None,
        "preview": issuance is None,
        "generated_at": iso(generated_at),
    }


def approval_values(records: list[ApprovalRecord]) -> list[dict[str, Any]]:
    return [
        {
            "action": r.action.value,
            "label": APPROVAL_LABELS[r.action],
            "actor": r.actor.full_name if r.actor else None,
            "at": iso(r.created_at),
            "note": r.note,
        }
        for r in records
    ]


def amount_words(settings: dict[str, Any], currency: str, amount: Any) -> str | None:
    return (
        rupiah_in_words(amount) if settings["show_amount_in_words"] and currency == "IDR" else None
    )


def payment_term_values(terms: list[PaymentTerm]) -> list[dict[str, Any]]:
    return [
        {
            "no": index,
            "name": term.name,
            "basis": term.basis.value,
            "percent": dec(term.percent),
            "amount": dec(term.amount),
            "tax_amount": dec(term.tax_amount),
            "total_amount": dec(term.total_amount),
            "due_date": term.due_date.isoformat() if term.due_date else None,
            "description": term.description,
        }
        for index, term in enumerate(terms, start=1)
    ]


def build_quotation_snapshot(
    *,
    organization: Organization,
    settings_row: DocumentSettings | None,
    quotation: Quotation,
    rab: RabDocument,
    version: RabVersion,
    approvals: list[ApprovalRecord],
    issuance: Issuance | None,
    generated_at: datetime,
) -> dict[str, Any]:
    copied = (
        quotation.subtotal,
        quotation.taxable_base,
        quotation.tax_amount,
        quotation.grand_total,
    )
    source = (version.subtotal, version.taxable_base, version.tax_amount, version.grand_total)
    if copied != source:
        raise SnapshotIntegrityError("Nilai penawaran tidak sesuai dengan versi RAB sumbernya.")
    if quotation.payment_terms and (
        sum(t.total_amount for t in quotation.payment_terms) != quotation.grand_total
    ):
        raise SnapshotIntegrityError("Jumlah termin tidak sama dengan total penawaran.")

    settings = settings_values(settings_row)
    item_rows, groups = items_and_groups(version)
    project = quotation.project
    approved = quotation.status.value in ("approved", "issued")
    has_tax = quotation.tax_label is not None and quotation.tax_rate_percent is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "document": document_values(
            DocumentType.QUOTATION, QUOTATION_TITLE, quotation.number, issuance, generated_at
        ),
        "company": company_values(organization),
        "client": client_values(project.client),
        "project": {
            "number": project.number,
            "name": project.name,
            "type_label": PROJECT_TYPE_LABELS[project.project_type],
            "location": project.location,
        },
        "quotation": {
            "number": quotation.number,
            "subject": quotation.subject,
            "valid_until": quotation.valid_until.isoformat() if quotation.valid_until else None,
            "introduction": quotation.introduction,
            "scope": quotation.scope,
            "terms": quotation.terms,
            "notes": quotation.notes,
            "status_label": STATUS_LABELS[quotation.status],
            "prepared_by": quotation.submitted_by.full_name if quotation.submitted_by else None,
            "submitted_at": iso(quotation.submitted_at),
            "approved_by": quotation.decided_by.full_name
            if approved and quotation.decided_by
            else None,
            "approved_at": iso(quotation.decided_at) if approved else None,
            "rab_number": rab.number,
            "rab_title": rab.title,
            "rab_version_no": version.version_no,
        },
        "currency": quotation.currency,
        "items": item_rows,
        "groups": groups,
        "totals": {
            "subtotal": dec(quotation.subtotal),
            "discount_type": version.discount_type.value,
            "discount_value": dec(version.discount_value),
            "discount_amount": dec(quotation.discount_amount),
            "taxable_base": dec(quotation.taxable_base),
            "tax_label": quotation.tax_label if has_tax else None,
            "tax_rate_percent": dec(quotation.tax_rate_percent) if has_tax else None,
            "tax_amount": dec(quotation.tax_amount),
            "grand_total": dec(quotation.grand_total),
            "unpriced_items": 0,
            "amount_in_words": amount_words(settings, quotation.currency, quotation.grand_total),
        },
        "payment_terms": payment_term_values(quotation.payment_terms),
        "approvals": approval_values(approvals),
        "settings": settings,
    }


def _check_invoice_totals(invoice: Invoice) -> None:
    if invoice.kind is InvoiceKind.TERM:
        term = invoice.payment_term
        if term is None or (invoice.subtotal, invoice.tax_amount, invoice.grand_total) != (
            term.amount,
            term.tax_amount,
            term.total_amount,
        ):
            raise SnapshotIntegrityError("Nilai invoice tidak sesuai dengan termin pembayarannya.")
        return
    fresh = manual_totals(
        [(i.quantity, i.unit_price) for i in invoice.items], invoice.tax_rate_percent
    )
    if (fresh.subtotal, fresh.tax_amount, fresh.grand_total) != (
        invoice.subtotal,
        invoice.tax_amount,
        invoice.grand_total,
    ):
        raise SnapshotIntegrityError(
            "Total invoice tersimpan tidak sesuai dengan perhitungan ulang."
        )


def build_invoice_snapshot(
    *,
    organization: Organization,
    settings_row: DocumentSettings | None,
    invoice: Invoice,
    quotation: Quotation | None,
    approvals: list[ApprovalRecord],
    issuance: Issuance | None,
    issue_date: date | None,
    generated_at: datetime,
) -> dict[str, Any]:
    _check_invoice_totals(invoice)
    settings = settings_values(settings_row)
    approved = invoice.status.value in ("approved", "issued")
    has_tax = invoice.tax_label is not None and invoice.tax_rate_percent is not None
    term = invoice.payment_term
    return {
        "schema_version": SCHEMA_VERSION,
        "document": document_values(
            DocumentType.INVOICE, INVOICE_TITLE, None, issuance, generated_at
        ),
        "company": company_values(organization),
        "client": client_values(invoice.client),
        "project": {"number": invoice.project.number, "name": invoice.project.name},
        "invoice": {
            "kind": invoice.kind.value,
            "title": invoice.title,
            "issue_date": issue_date.isoformat() if issue_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "notes": invoice.notes,
            "status_label": STATUS_LABELS[invoice.status],
            "prepared_by": invoice.submitted_by.full_name if invoice.submitted_by else None,
            "submitted_at": iso(invoice.submitted_at),
            "approved_by": invoice.decided_by.full_name
            if approved and invoice.decided_by
            else None,
            "approved_at": iso(invoice.decided_at) if approved else None,
            "quotation_number": quotation.number if quotation else None,
            "term": {
                "name": term.name,
                "basis": term.basis.value,
                "percent": dec(term.percent) if term.basis is TermBasis.PERCENT else None,
            }
            if term
            else None,
        },
        "lines": [
            {
                "no": index,
                "description": line.description,
                "quantity": dec(line.quantity),
                "unit": line.unit,
                "unit_price": dec(line.unit_price),
                "amount": dec(line.amount),
            }
            for index, line in enumerate(invoice.items, start=1)
        ],
        "totals": {
            "subtotal": dec(invoice.subtotal),
            "tax_label": invoice.tax_label if has_tax else None,
            "tax_rate_percent": dec(invoice.tax_rate_percent) if has_tax else None,
            "tax_amount": dec(invoice.tax_amount),
            "grand_total": dec(invoice.grand_total),
            "amount_in_words": amount_words(settings, invoice.currency, invoice.grand_total),
        },
        "currency": invoice.currency,
        "payment_info": {
            "bank_name": settings_row.payment_bank_name if settings_row else None,
            "account_number": settings_row.payment_account_number if settings_row else None,
            "account_holder": settings_row.payment_account_holder if settings_row else None,
        },
        "approvals": approval_values(approvals),
        "settings": settings,
    }
