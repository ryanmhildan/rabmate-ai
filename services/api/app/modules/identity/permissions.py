"""Roles and permissions.

Roles are fixed in code for the MVP (see docs/DECISIONS.md ADR-017): each membership has one role,
each role maps to a set of permission strings, and every endpoint checks a permission — never a
role name. Adding custom per-organization roles later only changes how a membership resolves to
a permission set.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    ORG_READ = "org.read"
    ORG_UPDATE = "org.update"
    USERS_READ = "users.read"
    USERS_MANAGE = "users.manage"
    AUDIT_READ = "audit.read"

    CLIENTS_READ = "clients.read"
    CLIENTS_WRITE = "clients.write"
    CLIENTS_DELETE = "clients.delete"

    PROJECTS_READ = "projects.read"
    PROJECTS_WRITE = "projects.write"
    PROJECTS_DELETE = "projects.delete"

    # Used from Phase 3 onwards; defined now so the role matrix is reviewed as a whole.
    RAB_READ = "rab.read"
    RAB_WRITE = "rab.write"
    RAB_APPROVE = "rab.approve"
    PRICING_READ = "pricing.read"
    PRICING_WRITE = "pricing.write"
    PRICING_VERIFY = "pricing.verify"
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_ISSUE = "documents.issue"
    # Approving quotations and invoices (and SPK/BAST later); separate from authoring them.
    DOCUMENTS_APPROVE = "documents.approve"
    FINANCE_READ = "finance.read"
    FINANCE_WRITE = "finance.write"
    # Asking the local AI assistant for drafts (results are only applied by a user with write
    # permission on the target, after review).
    AI_USE = "ai.use"


class Role(StrEnum):
    OWNER = "owner"
    PROJECT_MANAGER = "project_manager"
    ESTIMATOR = "estimator"
    FINANCE = "finance"
    APPROVER = "approver"
    VIEWER = "viewer"


ROLE_LABELS: dict[Role, str] = {
    Role.OWNER: "Owner/Admin",
    Role.PROJECT_MANAGER: "Project Manager",
    Role.ESTIMATOR: "Estimator",
    Role.FINANCE: "Finance",
    Role.APPROVER: "Approver",
    Role.VIEWER: "Viewer",
}

P = Permission

_VIEWER = frozenset(
    {
        P.ORG_READ,
        P.CLIENTS_READ,
        P.PROJECTS_READ,
        P.RAB_READ,
        P.PRICING_READ,
        P.DOCUMENTS_READ,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.PROJECT_MANAGER: _VIEWER
    | {
        P.USERS_READ,
        P.AUDIT_READ,
        P.CLIENTS_WRITE,
        P.PROJECTS_WRITE,
        P.PROJECTS_DELETE,
        P.RAB_WRITE,
        P.PRICING_WRITE,
        P.FINANCE_READ,
        P.AI_USE,
    },
    Role.ESTIMATOR: _VIEWER | {P.RAB_WRITE, P.PRICING_WRITE, P.AI_USE},
    Role.FINANCE: _VIEWER | {P.CLIENTS_WRITE, P.DOCUMENTS_ISSUE, P.FINANCE_READ, P.FINANCE_WRITE},
    Role.APPROVER: _VIEWER
    | {
        P.AUDIT_READ,
        P.RAB_APPROVE,
        P.PRICING_VERIFY,
        P.DOCUMENTS_ISSUE,
        P.DOCUMENTS_APPROVE,
        P.FINANCE_READ,
    },
    Role.VIEWER: _VIEWER,
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
