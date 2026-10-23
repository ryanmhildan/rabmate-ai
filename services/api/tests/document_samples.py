"""Hand-built snapshots for renderer tests (same shape as documents/snapshot.py produces)."""

from __future__ import annotations

import copy
from typing import Any


def _item(
    no: int,
    name: str,
    quantity: str,
    unit: str,
    price: str | None,
    subtotal: str | None,
    **extra: Any,
) -> dict[str, Any]:
    item = {
        "no": no,
        "code": f"IT-{no:02d}",
        "name": name,
        "category": None,
        "item_type": "material",
        "item_type_label": "Material/barang",
        "specification": None,
        "quantity": quantity,
        "unit": unit,
        "unit_price": price,
        "subtotal": subtotal,
        "price_source_type": "manual" if price else None,
        "price_source_label": "Input manual" if price else None,
        "price_source": "Toko Komputer Jaya" if price else None,
        "notes": None,
    }
    item.update(extra)
    return item


BASE: dict[str, Any] = {
    "schema_version": 1,
    "document": {
        "type": "rab",
        "title": "Rencana Anggaran Biaya",
        "number": "RAB-2026-0001/V1",
        "issued_at": "2026-10-19T03:00:00+00:00",
        "issued_by": "Dewi Approver",
        "preview": False,
        "generated_at": "2026-10-19T03:00:00+00:00",
    },
    "company": {
        "name": "PT Contoh Teknik",
        "legal_name": "PT Contoh Teknik Nusantara",
        "tax_id": "01.234.567.8-901.000",
        "address": "Jl. Merdeka No. 1",
        "city": "Bogor",
        "phone": "0251-123456",
        "email": "halo@contoh.test",
        "website": None,
    },
    "client": {
        "name": "CV Klien Makmur",
        "code": "KL-01",
        "contact_person": "Budi",
        "address": "Jl. Pahlawan 5",
        "city": "Jakarta",
        "phone": None,
        "email": None,
        "tax_id": None,
    },
    "project": {
        "number": "PRJ-2026-0005",
        "name": "Instalasi Jaringan Kantor Cabang",
        "type_label": "IT & perangkat lunak",
        "location": "Bogor",
        "start_date": "2026-11-01",
        "end_date": "2026-11-30",
    },
    "rab": {
        "id": "00000000-0000-0000-0000-000000000001",
        "number": "RAB-2026-0001",
        "title": "RAB Instalasi Jaringan Tahap 1",
        "version_id": "00000000-0000-0000-0000-000000000002",
        "version_no": 1,
        "status": "approved",
        "status_label": "Disetujui",
        "currency": "IDR",
        "notes": "Harga berlaku 30 hari.",
        "assumptions": "Akses lokasi tersedia jam kerja.",
        "prepared_by": "Eko Estimator",
        "submitted_at": "2026-10-18T09:00:00+00:00",
        "approved_by": "Dewi Approver",
        "approved_at": "2026-10-18T10:00:00+00:00",
    },
    "items": [
        _item(
            1,
            "Kabel UTP Cat6",
            "305.0000",
            "m",
            "4300.0000",
            "1311500.00",
            category="Material",
            specification="Belden, 305 m/roll",
        ),
        _item(
            2,
            "Jasa instalasi titik jaringan",
            "48.0000",
            "titik",
            "175000.0000",
            "8400000.00",
            category="Jasa",
            item_type="service",
            item_type_label="Jasa",
        ),
    ],
    "groups": [
        {"title": "Material", "subtotal": "1311500.00", "item_numbers": [1]},
        {"title": "Jasa", "subtotal": "8400000.00", "item_numbers": [2]},
    ],
    "totals": {
        "subtotal": "9711500.00",
        "discount_type": "percent",
        "discount_value": "5.00",
        "discount_amount": "485575.00",
        "taxable_base": "9225925.00",
        "tax_label": "PPN",
        "tax_rate_percent": "11.00",
        "tax_amount": "1014851.75",
        "grand_total": "10240776.75",
        "unpriced_items": 0,
        "amount_in_words": "Sepuluh juta dua ratus empat puluh ribu tujuh ratus tujuh puluh enam "
        "rupiah tujuh puluh lima sen",
    },
    "approvals": [],
    "settings": {
        "tagline": "Solusi jaringan & listrik",
        "accent_color": "#1F4E79",
        "footer_text": "Terima kasih atas kepercayaan Anda.",
        "terms": "Pembayaran 30% di muka.",
        "show_item_codes": True,
        "show_price_sources": False,
        "show_amount_in_words": True,
    },
}


def sample_snapshot(**sections: Any) -> dict[str, Any]:
    """Deep copy of BASE with top-level sections shallow-merged, e.g. settings={...}."""
    snapshot = copy.deepcopy(BASE)
    for key, values in sections.items():
        if isinstance(values, dict):
            snapshot[key].update(values)
        else:
            snapshot[key] = values
    return snapshot


def many_items(count: int) -> dict[str, Any]:
    items = [
        _item(
            n,
            f"Item nomor {n} dengan uraian yang cukup panjang",
            "1.0000",
            "unit",
            "1000.0000",
            "1000.00",
        )
        for n in range(1, count + 1)
    ]
    return {
        "items": items,
        "groups": [
            {
                "title": None,
                "subtotal": f"{count * 1000}.00",
                "item_numbers": list(range(1, count + 1)),
            }
        ],
    }


def quotation_snapshot(**sections: Any) -> dict[str, Any]:
    """A quotation snapshot built on the RAB sample (same items and totals)."""
    base = copy.deepcopy(BASE)
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "document": {
            **base["document"],
            "type": "quotation",
            "title": "Surat Penawaran Harga",
            "number": "PNW-2026-0001",
        },
        "company": base["company"],
        "client": base["client"],
        "project": {k: base["project"][k] for k in ("number", "name", "type_label", "location")},
        "quotation": {
            "number": "PNW-2026-0001",
            "subject": "Penawaran instalasi jaringan kantor cabang",
            "valid_until": "2026-11-18",
            "introduction": None,
            "scope": "Pengadaan dan pemasangan jaringan LAN 48 titik.",
            "terms": "Harga belum termasuk rak server.",
            "notes": None,
            "status_label": "Terbit",
            "prepared_by": "Eko Estimator",
            "submitted_at": "2026-10-18T09:00:00+00:00",
            "approved_by": "Dewi Approver",
            "approved_at": "2026-10-18T10:00:00+00:00",
            "rab_number": "RAB-2026-0001",
            "rab_title": "RAB Instalasi Jaringan Tahap 1",
            "rab_version_no": 1,
        },
        "currency": "IDR",
        "items": base["items"],
        "groups": base["groups"],
        "totals": base["totals"],
        "payment_terms": [
            {
                "no": 1,
                "name": "Uang muka",
                "basis": "percent",
                "percent": "30.00",
                "amount": "2767777.50",
                "tax_amount": "304455.53",
                "total_amount": "3072233.03",
                "due_date": "2026-11-01",
                "description": "Saat SPK",
            },
            {
                "no": 2,
                "name": "Termin 2",
                "basis": "percent",
                "percent": "40.00",
                "amount": "3690370.00",
                "tax_amount": "405940.70",
                "total_amount": "4096310.70",
                "due_date": None,
                "description": "Progres 70%",
            },
            {
                "no": 3,
                "name": "Pelunasan",
                "basis": "percent",
                "percent": "30.00",
                "amount": "2767777.50",
                "tax_amount": "304455.52",
                "total_amount": "3072233.02",
                "due_date": None,
                "description": "Setelah BAST",
            },
        ],
        "approvals": [],
        "settings": base["settings"],
    }
    for key, values in sections.items():
        if isinstance(values, dict):
            snapshot[key].update(values)
        else:
            snapshot[key] = values
    return snapshot


def invoice_snapshot(**sections: Any) -> dict[str, Any]:
    base = copy.deepcopy(BASE)
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "document": {
            **base["document"],
            "type": "invoice",
            "title": "Invoice",
            "number": "INV-2026-0001",
        },
        "company": base["company"],
        "client": {**base["client"], "tax_id": "02.345.678.9-012.000"},
        "project": {"number": "PRJ-2026-0005", "name": "Instalasi Jaringan Kantor Cabang"},
        "invoice": {
            "kind": "term",
            "title": "Uang muka — Penawaran instalasi jaringan",
            "issue_date": "2026-10-19",
            "due_date": "2026-11-02",
            "notes": "Mohon konfirmasi setelah transfer.",
            "status_label": "Terbit",
            "prepared_by": "Fina Finance",
            "submitted_at": "2026-10-19T02:00:00+00:00",
            "approved_by": "Dewi Approver",
            "approved_at": "2026-10-19T02:30:00+00:00",
            "quotation_number": "PNW-2026-0001",
            "term": {"name": "Uang muka", "basis": "percent", "percent": "30.00"},
        },
        "lines": [
            {
                "no": 1,
                "description": "Uang muka (30% dari nilai kontrak sebelum pajak)",
                "quantity": "1.0000",
                "unit": "ls",
                "unit_price": "2767777.5000",
                "amount": "2767777.50",
            },
        ],
        "totals": {
            "subtotal": "2767777.50",
            "tax_label": "PPN",
            "tax_rate_percent": "11.00",
            "tax_amount": "304455.53",
            "grand_total": "3072233.03",
            "amount_in_words": "Tiga juta tujuh puluh dua ribu dua ratus tiga puluh tiga rupiah "
            "tiga sen",
        },
        "currency": "IDR",
        "payment_info": {
            "bank_name": "Bank Contoh",
            "account_number": "123-456-7890",
            "account_holder": "PT Contoh Teknik Nusantara",
        },
        "approvals": [],
        "settings": base["settings"],
    }
    for key, values in sections.items():
        if isinstance(values, dict):
            snapshot[key].update(values)
        else:
            snapshot[key] = values
    return snapshot


def _merge(snapshot: dict[str, Any], sections: dict[str, Any]) -> dict[str, Any]:
    for key, values in sections.items():
        if isinstance(values, dict):
            snapshot[key].update(values)
        else:
            snapshot[key] = values
    return snapshot


def spk_snapshot(**sections: Any) -> dict[str, Any]:
    base = copy.deepcopy(BASE)
    quotation = quotation_snapshot()
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "document": {
            **base["document"],
            "type": "spk",
            "title": "Surat Perintah Kerja",
            "number": "SPK-2026-0001",
        },
        "company": base["company"],
        "client": base["client"],
        "project": quotation["project"],
        "spk": {
            "title": "Instalasi jaringan kantor cabang",
            "issue_date": "2026-10-19",
            "start_date": "2026-10-26",
            "end_date": "2026-11-25",
            "location": "Jl. Contoh No. 1, Bandung",
            "scope": "Pengadaan dan pemasangan jaringan LAN 48 titik.",
            "terms": None,
            "notes": None,
            "status_label": "Terbit",
            "client_signatory": {"name": "Budi Santoso", "title": "Direktur"},
            "company_signatory": {"name": "Sari Wulandari", "title": "Manajer Proyek"},
            "prepared_by": "Pia Manajer",
            "submitted_at": "2026-10-19T02:00:00+00:00",
            "approved_by": "Dewi Approver",
            "approved_at": "2026-10-19T02:30:00+00:00",
            "quotation_number": "PNW-2026-0001",
            "quotation_subject": "Penawaran instalasi jaringan kantor cabang",
            "rab_number": "RAB-2026-0001",
            "rab_version_no": 1,
        },
        "currency": "IDR",
        "contract": {
            "taxable_base": "9225925.00",
            "tax_label": "PPN",
            "tax_rate_percent": "11.00",
            "tax_amount": "1014851.75",
            "contract_value": "10240776.75",
            "amount_in_words": base["totals"]["amount_in_words"],
        },
        "items": [
            {
                "no": item["no"],
                "code": item["code"],
                "name": item["name"],
                "category": item["category"],
                "specification": item["specification"],
                "quantity": item["quantity"],
                "unit": item["unit"],
            }
            for item in base["items"]
        ],
        "payment_terms": quotation["payment_terms"],
        "approvals": [],
        "settings": base["settings"],
    }
    return _merge(snapshot, sections)


def bast_snapshot(**sections: Any) -> dict[str, Any]:
    base = copy.deepcopy(BASE)
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "document": {
            **base["document"],
            "type": "bast",
            "title": "Berita Acara Serah Terima",
            "number": "BAST-2026-0001",
        },
        "company": base["company"],
        "client": base["client"],
        "project": spk_snapshot()["project"],
        "bast": {
            "kind": "partial",
            "kind_label": "Serah terima sebagian",
            "title": "Serah terima tahap 1",
            "handover_date": "2026-11-05",
            "location": "Jl. Contoh No. 1, Bandung",
            "delivered_by": {"name": "Sari Wulandari", "title": "Manajer Proyek"},
            "received_by": {"name": "Budi Santoso", "title": "Direktur"},
            "terms": None,
            "notes": None,
            "status_label": "Terbit",
            "prepared_by": "Pia Manajer",
            "submitted_at": "2026-11-05T02:00:00+00:00",
            "approved_by": "Dewi Approver",
            "approved_at": "2026-11-05T02:30:00+00:00",
            "spk_number": "SPK-2026-0001",
            "spk_title": "Instalasi jaringan kantor cabang",
            "quotation_number": "PNW-2026-0001",
        },
        "lines": [
            {
                "no": 1,
                "description": "Kabel UTP Cat6",
                "quantity": "200.0000",
                "unit": "m",
                "condition": "Terpasang",
                "contract": {
                    "no": 1,
                    "code": "MAT-001",
                    "contract_quantity": "305.0000",
                    "delivered_before": "50.0000",
                    "cumulative": "250.0000",
                },
            },
            {
                "no": 2,
                "description": "Patch panel tambahan",
                "quantity": "1.0000",
                "unit": "unit",
                "condition": None,
                "contract": None,
            },
        ],
        "approvals": [],
        "settings": base["settings"],
    }
    return _merge(snapshot, sections)
