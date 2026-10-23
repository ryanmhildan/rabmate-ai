"""External price search: provider abstraction, no provider configured yet.

Nothing here fabricates prices. When a real provider is added it must return candidates with
source URL, access date, unit and specification; they are stored as `external` observations that
start unverified and are only used in a RAB after a user picks them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.modules.pricing.matching import Query
from app.modules.pricing.schemas import ExternalStatus


@dataclass(frozen=True)
class ExternalCandidate:
    name: str
    price: Decimal
    currency: str
    unit: str
    source_url: str
    accessed_at: date
    specification: str | None = None
    location: str | None = None


class ExternalPriceProvider(Protocol):
    name: str

    def search(self, query: Query) -> list[ExternalCandidate]: ...


class ExternalSearchNotConfiguredError(ServiceUnavailableError):
    code = "external_search_not_configured"
    message = (
        "Pencarian harga eksternal belum dikonfigurasi. Catat harga dari sumber eksternal secara "
        "manual (jenis sumber 'Sumber eksternal' + URL); statusnya tetap belum terverifikasi."
    )


def get_provider(settings: Settings) -> ExternalPriceProvider | None:
    """Only "none" exists today; a real provider is selected here by PRICE_SEARCH_PROVIDER."""
    match settings.price_search_provider:
        case "none":
            return None


def status(settings: Settings) -> ExternalStatus:
    provider = get_provider(settings)
    if provider is None:
        return ExternalStatus(
            configured=False, provider=None, message=ExternalSearchNotConfiguredError.message
        )
    return ExternalStatus(configured=True, provider=provider.name, message="Siap digunakan.")


def search(settings: Settings, query: Query) -> list[ExternalCandidate]:
    provider = get_provider(settings)
    if provider is None:
        raise ExternalSearchNotConfiguredError()
    return provider.search(query)
