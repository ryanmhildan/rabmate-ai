"""Import every ORM model here so Alembic autogenerate sees the full metadata."""

from app.db.base import Base
from app.modules.approvals.models import ApprovalRecord
from app.modules.assistant.models import AiConversation, AiMessage, AiRun
from app.modules.audit.models import AuditLog
from app.modules.billing.models import (
    Invoice,
    InvoiceItem,
    Payment,
    PaymentAllocation,
    PaymentTerm,
    Quotation,
)
from app.modules.clients.models import Client
from app.modules.documents.models import DocumentFile, DocumentSettings, IssuedDocument
from app.modules.identity.models import LoginAttempt, Membership, Organization, User, UserSession
from app.modules.intake.models import SourceDocument
from app.modules.numbering.models import DocumentSequence
from app.modules.pricing.models import ImportJob, PriceCatalogItem, PriceObservation, Supplier
from app.modules.projects.models import Project, ProjectMember
from app.modules.rab.models import RabDocument, RabItem, RabVersion
from app.modules.workorders.models import Bast, BastItem, Spk

__all__ = [
    "AiConversation",
    "AiMessage",
    "AiRun",
    "ApprovalRecord",
    "AuditLog",
    "Base",
    "Bast",
    "BastItem",
    "Client",
    "DocumentFile",
    "DocumentSequence",
    "DocumentSettings",
    "ImportJob",
    "Invoice",
    "InvoiceItem",
    "IssuedDocument",
    "LoginAttempt",
    "Membership",
    "Organization",
    "Payment",
    "PaymentAllocation",
    "PaymentTerm",
    "PriceCatalogItem",
    "PriceObservation",
    "Project",
    "ProjectMember",
    "Quotation",
    "RabDocument",
    "RabItem",
    "RabVersion",
    "SourceDocument",
    "Spk",
    "Supplier",
    "User",
    "UserSession",
]
