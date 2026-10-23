"""Review workflow shared by quotations and invoices (explicit transitions, checked server-side).

    draft ──submit──▶ in_review ──approve──▶ approved ──issue──▶ issued ──void──▶ void
      ▲                 │  └──reject──▶ rejected        │
      └──withdraw───────┘              └──reopen──┐     └──reopen (back to draft)
      ▲───────────────────────────────────────────┘

Issuing and voiding have their own endpoints (idempotent issuance, reason for void); this module
only answers "may this user do this now?".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.approvals.models import ApprovalAction
from app.modules.billing.models import DocStatus
from app.modules.identity.permissions import Permission

S = DocStatus


class Action(StrEnum):
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    APPROVE = "approve"
    REJECT = "reject"
    REOPEN = "reopen"


@dataclass(frozen=True)
class Transition:
    sources: tuple[DocStatus, ...]
    target: DocStatus
    approval: bool  # needs the approve permission (else the write permission)
    record: ApprovalAction
    note_required: bool = False


TRANSITIONS: dict[Action, Transition] = {
    Action.SUBMIT: Transition((S.DRAFT,), S.IN_REVIEW, False, ApprovalAction.SUBMITTED),
    Action.WITHDRAW: Transition((S.IN_REVIEW,), S.DRAFT, False, ApprovalAction.WITHDRAWN),
    Action.APPROVE: Transition((S.IN_REVIEW,), S.APPROVED, True, ApprovalAction.APPROVED),
    Action.REJECT: Transition(
        (S.IN_REVIEW,), S.REJECTED, True, ApprovalAction.REJECTED, note_required=True
    ),
    Action.REOPEN: Transition((S.REJECTED, S.APPROVED), S.DRAFT, False, ApprovalAction.REOPENED),
}

STATUS_LABELS: dict[DocStatus, str] = {
    S.DRAFT: "Draft",
    S.IN_REVIEW: "Menunggu review",
    S.APPROVED: "Disetujui",
    S.REJECTED: "Ditolak",
    S.ISSUED: "Terbit",
    S.VOID: "Dibatalkan",
}

EDITABLE = (S.DRAFT,)
DELETABLE = (S.DRAFT, S.REJECTED)


def allowed_actions(
    status: DocStatus,
    permissions: frozenset[Permission],
    *,
    write: Permission,
) -> list[Action]:
    actions = []
    for action, transition in TRANSITIONS.items():
        needed = Permission.DOCUMENTS_APPROVE if transition.approval else write
        if status in transition.sources and needed in permissions:
            actions.append(action)
    return actions
