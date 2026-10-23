from __future__ import annotations

from app.modules.projects.models import ProjectStatus

S = ProjectStatus

# Explicit project lifecycle. Setting the current status again is a no-op and always allowed.
STATUS_TRANSITIONS: dict[ProjectStatus, frozenset[ProjectStatus]] = {
    S.PROSPECT: frozenset({S.ACTIVE, S.CANCELLED}),
    S.ACTIVE: frozenset({S.ON_HOLD, S.COMPLETED, S.CANCELLED}),
    S.ON_HOLD: frozenset({S.ACTIVE, S.CANCELLED}),
    S.COMPLETED: frozenset({S.ACTIVE}),  # reopen
    S.CANCELLED: frozenset({S.PROSPECT}),  # revive as a prospect
}


def allowed_transitions(status: ProjectStatus) -> list[ProjectStatus]:
    return sorted(STATUS_TRANSITIONS[status])


def can_transition(current: ProjectStatus, target: ProjectStatus) -> bool:
    return target == current or target in STATUS_TRANSITIONS[current]
