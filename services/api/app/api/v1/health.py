from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.ai.adapter import AgentAdapter, AgentState
from app.ai.runtime import agent_health, get_agent_adapter
from app.core.config import Settings, get_settings
from app.db.session import check_database, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

ComponentStatus = Literal["ok", "error", "disabled"]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    time: datetime
    database: ComponentStatus
    ai: ComponentStatus


@router.get("/live", response_model=LiveResponse, summary="Liveness (tanpa cek dependensi)")
def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "",
    response_model=HealthResponse,
    summary="Readiness: status API dan koneksi database",
    responses={503: {"model": HealthResponse, "description": "Database tidak dapat dihubungi"}},
)
def health(
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    adapter: AgentAdapter = Depends(get_agent_adapter),
) -> HealthResponse:
    database: ComponentStatus = "ok"
    try:
        check_database(db)
    except SQLAlchemyError as exc:
        # Log the driver error class only; connection strings may appear in the message.
        logger.warning("database health check failed: %s", type(exc).__name__)
        database = "error"

    # AI is optional: its state never makes the API "degraded" (non-AI features keep working).
    ai: ComponentStatus = "disabled"
    if settings.ai_enabled:
        try:
            ready = agent_health(settings, adapter).state is AgentState.READY
        except Exception as exc:  # a broken probe must not break the health endpoint
            logger.warning("ai health probe failed: %s", type(exc).__name__)
            ready = False
        ai = "ok" if ready else "error"

    status: Literal["ok", "degraded"] = "ok" if database == "ok" else "degraded"
    if status != "ok":
        response.status_code = 503

    return HealthResponse(
        status=status,
        version=__version__,
        environment=settings.app_env.value,
        time=datetime.now(ZoneInfo(settings.timezone)),
        database=database,
        ai=ai,
    )
