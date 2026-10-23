from __future__ import annotations

from app.core.errors import VersionConflictError


def check_version(current: int, expected: int) -> None:
    """Optimistic locking: the client must send the version it last read.

    The ORM's version_id_col additionally guards the UPDATE itself (StaleDataError → 409 via the
    global handler), covering the window between this check and the write.
    """
    if current != expected:
        raise VersionConflictError(details={"current_version": current})
