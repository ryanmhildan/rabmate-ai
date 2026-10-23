"""Decimal input types for money, rates and quantities.

JSON numbers with a fraction are parsed as binary floats before reaching Pydantic, which silently
loses precision (12345678901234567.89 → 12345678901234568). Such values must therefore be sent
as decimal strings ("12345678901234567.89"); integers are exact and remain accepted.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

FLOAT_REJECTED = 'Kirim nilai desimal sebagai string, mis. "1250000.50", agar presisi tidak hilang.'


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError(FLOAT_REJECTED)
    return value


ExactDecimal = BeforeValidator(_reject_float)

Money = Annotated[Decimal, ExactDecimal, Field(ge=0, max_digits=20, decimal_places=2)]
Percent = Annotated[Decimal, ExactDecimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
