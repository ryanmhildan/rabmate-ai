"""Payment schedule (termin) allocation. Pure functions, Decimal only.

Rules (ADR-035):
- A term is either a percentage of the contract value or a fixed amount; both are amounts
  *before tax* (the quotation's taxable base, DPP). Percent terms are computed with round2.
- All-percent schedules must total exactly 100%; the last term absorbs the cent remainder so the
  amounts sum to the DPP exactly. Schedules with fixed amounts must sum to the DPP exactly —
  no silent adjustment of what the user typed.
- Tax is allocated in proportion to each term's amount (round2), the last term taking the
  remainder, so the term totals add up to the quotation grand total to the cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from app.modules.billing.models import TermBasis
from app.modules.rab.calculation import round2

HUNDRED = Decimal(100)
ZERO = Decimal("0.00")
MAX_TERMS = 20


class TermsError(ValueError):
    def __init__(self, message: str, *, index: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.index = index  # 0-based term the error is about, when it is about one


@dataclass(frozen=True)
class TermSpec:
    name: str
    basis: TermBasis
    value: Decimal  # percent (0 < p <= 100) or amount (> 0) before tax
    due_date: date | None = None
    description: str | None = None


@dataclass(frozen=True)
class TermAmounts:
    spec: TermSpec
    percent: Decimal | None
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


def allocate(taxable_base: Decimal, tax: Decimal, specs: list[TermSpec]) -> list[TermAmounts]:
    """Amounts per term for a contract of `taxable_base` (DPP) plus `tax`."""
    if not specs:
        raise TermsError("Jadwal pembayaran minimal satu termin.")
    if len(specs) > MAX_TERMS:
        raise TermsError(f"Maksimal {MAX_TERMS} termin.")
    if taxable_base <= 0:
        raise TermsError("Nilai penawaran sebelum pajak harus lebih dari 0.")

    for index, spec in enumerate(specs):
        if spec.basis is TermBasis.PERCENT:
            if not ZERO < spec.value <= HUNDRED:
                raise TermsError("Persentase termin harus lebih dari 0 dan maks. 100.", index=index)
            if spec.value != spec.value.quantize(Decimal("0.01")):
                raise TermsError("Persentase termin maks. 2 desimal.", index=index)
        else:
            if spec.value <= 0:
                raise TermsError("Nilai termin harus lebih dari 0.", index=index)
            if spec.value != round2(spec.value):
                raise TermsError("Nilai termin maks. 2 desimal.", index=index)

    with localcontext() as ctx:
        ctx.prec = 60
        all_percent = all(s.basis is TermBasis.PERCENT for s in specs)
        if all_percent:
            total_percent = sum((s.value for s in specs), ZERO)
            if total_percent != HUNDRED:
                raise TermsError(
                    f"Total persentase termin harus 100% (saat ini {total_percent.normalize():f}%)."
                )
        amounts = [
            round2(taxable_base * s.value / HUNDRED) if s.basis is TermBasis.PERCENT else s.value
            for s in specs
        ]
        if all_percent:
            amounts[-1] = taxable_base - sum(amounts[:-1], ZERO)
        difference = taxable_base - sum(amounts, ZERO)
        if difference != 0:
            direction = "kurang" if difference > 0 else "lebih"
            raise TermsError(
                f"Jumlah termin {direction} {abs(difference):f} dari nilai sebelum pajak "
                f"({taxable_base:f})."
            )
        if any(a <= 0 for a in amounts):
            raise TermsError("Setiap termin harus bernilai lebih dari 0 setelah pembulatan.")

        taxes = [round2(tax * a / taxable_base) for a in amounts[:-1]]
        taxes.append(tax - sum(taxes, ZERO))
        if taxes[-1] < 0:  # only possible with pathological rounding; refuse rather than guess
            raise TermsError("Alokasi pajak termin tidak valid.")

    return [
        TermAmounts(
            spec=spec,
            percent=spec.value if spec.basis is TermBasis.PERCENT else None,
            amount=amount,
            tax_amount=term_tax,
            total_amount=amount + term_tax,
        )
        for spec, amount, term_tax in zip(specs, amounts, taxes, strict=True)
    ]
