"""Explicit RAB version workflow.

    draft ──submit──▶ in_review ──approve──▶ approved ──(newer version approved)──▶ archived
      ▲                 │   │
      └───withdraw──────┘   └──reject──▶ rejected ──reopen──▶ draft
    draft / rejected ──archive──▶ archived            (discard)

Approved versions are immutable; changing them means creating a new version (create_version).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.approvals.models import ApprovalAction
from app.modules.identity.permissions import Permission
from app.modules.rab.models import RabStatus

S = RabStatus


class RabAction(StrEnum):
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    APPROVE = "approve"
    REJECT = "reject"
    REOPEN = "reopen"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class Transition:
    sources: frozenset[RabStatus]
    target: RabStatus
    permission: Permission
    record: ApprovalAction
    note_required: bool = False


TRANSITIONS: dict[RabAction, Transition] = {
    RabAction.SUBMIT: Transition(
        frozenset({S.DRAFT}), S.IN_REVIEW, Permission.RAB_WRITE, ApprovalAction.SUBMITTED
    ),
    RabAction.WITHDRAW: Transition(
        frozenset({S.IN_REVIEW}), S.DRAFT, Permission.RAB_WRITE, ApprovalAction.WITHDRAWN
    ),
    RabAction.APPROVE: Transition(
        frozenset({S.IN_REVIEW}), S.APPROVED, Permission.RAB_APPROVE, ApprovalAction.APPROVED
    ),
    RabAction.REJECT: Transition(
        frozenset({S.IN_REVIEW}),
        S.REJECTED,
        Permission.RAB_APPROVE,
        ApprovalAction.REJECTED,
        note_required=True,
    ),
    RabAction.REOPEN: Transition(
        frozenset({S.REJECTED}), S.DRAFT, Permission.RAB_WRITE, ApprovalAction.REOPENED
    ),
    RabAction.ARCHIVE: Transition(
        frozenset({S.DRAFT, S.REJECTED}), S.ARCHIVED, Permission.RAB_WRITE, ApprovalAction.ARCHIVED
    ),
}

STATUS_LABELS: dict[RabStatus, str] = {
    S.DRAFT: "draft",
    S.IN_REVIEW: "menunggu review",
    S.APPROVED: "disetujui",
    S.REJECTED: "ditolak",
    S.ARCHIVED: "diarsipkan",
}


def allowed_actions(status: RabStatus, permissions: frozenset[Permission]) -> list[RabAction]:
    return [
        action
        for action, t in TRANSITIONS.items()
        if status in t.sources and t.permission in permissions
    ]
