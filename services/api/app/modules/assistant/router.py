from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from sqlalchemy.orm import Session

from app.ai.adapter import AgentAdapter
from app.ai.runtime import SessionFactory, agent_health, get_agent_adapter, get_session_factory
from app.api.deps import RequestContext, require
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse
from app.core.ratelimit import EXPENSIVE
from app.db.session import get_db
from app.modules.assistant import chat, service
from app.modules.assistant.models import AiConversation, AiRun, AiRunStatus, MessageRole
from app.modules.assistant.schemas import (
    AiStatusOut,
    ApplyIn,
    AskIn,
    ChatMessageOut,
    ChatRunOut,
    ChatSourceOut,
    ConversationListItem,
    ConversationOut,
    OcrStatusOut,
    RunCreate,
    RunListItem,
    RunOut,
)
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import UserBrief
from app.modules.intake.ocr import OcrEngine
from app.modules.intake.router import get_ocr_engine
from app.modules.intake.sniff import ACCEPTED

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
}
P = Permission

router = APIRouter(tags=["ai"], responses=ERRORS)


def _item(run: AiRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "created_by": UserBrief.model_validate(run.created_by),
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "item_count": service.item_count(run),
        "applied_count": run.applied_count,
        "error_message": run.error_message,
    }


def _out(ctx: RequestContext, run: AiRun) -> RunOut:
    can_use = ctx.can(P.AI_USE) and ctx.can(P.RAB_WRITE)
    return RunOut(
        **_item(run),
        rab_version_id=run.rab_version_id,
        source_document_id=run.source_document_id,
        input=run.input,
        context=run.context,
        result=run.result,
        error_code=run.error_code,
        model=run.model,
        attempts=run.attempts,
        duration_ms=run.duration_ms,
        started_at=run.started_at,
        applied_at=run.applied_at,
        can_apply=can_use and run.status is AiRunStatus.SUCCEEDED,
        can_discard=can_use and run.status in (AiRunStatus.SUCCEEDED, AiRunStatus.FAILED),
    )


@router.get("/ai/status", response_model=AiStatusOut, summary="Status asisten AI lokal")
def ai_status(
    fresh: bool = False,
    ctx: RequestContext = Depends(require(P.ORG_READ)),
    settings: Settings = Depends(get_settings),
    adapter: AgentAdapter = Depends(get_agent_adapter),
    ocr: OcrEngine = Depends(get_ocr_engine),
) -> AiStatusOut:
    health = agent_health(settings, adapter, fresh=fresh)
    ocr_status = ocr.status()
    return AiStatusOut(
        enabled=settings.ai_enabled,
        state=health.state,
        message=health.message,
        model=health.model,
        toolsets=list(health.toolsets),
        ocr=OcrStatusOut(available=ocr_status.available, message=ocr_status.message),
        upload_max_mb=settings.upload_max_mb,
        accepted_files=ACCEPTED,
    )


@router.post(
    "/rab/{rab_id}/versions/{version_no}/ai-runs",
    dependencies=EXPENSIVE,
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Minta draft dari asisten AI (diproses di latar belakang)",
)
def create_run(
    rab_id: uuid.UUID,
    version_no: int,
    payload: RunCreate,
    background: BackgroundTasks,
    ctx: RequestContext = Depends(require(P.AI_USE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    adapter: AgentAdapter = Depends(get_agent_adapter),
    session_factory: SessionFactory = Depends(get_session_factory),
    ocr: OcrEngine = Depends(get_ocr_engine),
) -> RunOut:
    ctx.require(P.RAB_WRITE)  # drafts are only useful to someone who may add them to the RAB
    run = service.create_run(db, ctx, settings, adapter, rab_id, version_no, payload)
    background.add_task(service.execute_run, run.id, session_factory, adapter, settings, ocr)
    return _out(ctx, run)


@router.get(
    "/rab/{rab_id}/versions/{version_no}/ai-runs",
    response_model=list[RunListItem],
    summary="Riwayat permintaan AI untuk versi RAB",
)
def list_runs(
    rab_id: uuid.UUID,
    version_no: int,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[RunListItem]:
    return [
        RunListItem(**_item(r)) for r in service.list_runs(db, ctx, rab_id, version_no, settings)
    ]


@router.get("/ai-runs/{run_id}", response_model=RunOut, summary="Status dan hasil permintaan AI")
def get_run(
    run_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.RAB_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunOut:
    return _out(ctx, service.get_run(db, ctx, run_id, settings))


@router.post(
    "/ai-runs/{run_id}/apply",
    response_model=RunOut,
    summary="Tambahkan item terpilih (sudah diperiksa pengguna) ke versi RAB draft",
)
def apply_run(
    run_id: uuid.UUID,
    payload: ApplyIn,
    ctx: RequestContext = Depends(require(P.AI_USE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunOut:
    ctx.require(P.RAB_WRITE)
    return _out(ctx, service.apply_run(db, ctx, run_id, payload, settings))


@router.post("/ai-runs/{run_id}/discard", response_model=RunOut, summary="Buang hasil AI")
def discard_run(
    run_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.AI_USE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunOut:
    return _out(ctx, service.discard_run(db, ctx, run_id, settings))


# --------------------------------------------------------------------------- project chat


def _conversation_out(
    db: Session, ctx: RequestContext, conversation: AiConversation, settings: Settings
) -> ConversationOut:
    messages = chat.messages_of(db, conversation)
    runs = chat.runs_by_id(db, messages)
    latest = chat.latest_run(db, ctx, conversation, settings)
    out = []
    for message in messages:
        run = runs.get(message.run_id) if message.run_id else None
        result = (run.result if run else None) or {}
        assistant = message.role is MessageRole.ASSISTANT
        out.append(
            ChatMessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                sources=[ChatSourceOut.model_validate(s) for s in message.sources],
                warnings=message.warnings,
                assumptions=result.get("assumptions", []) if assistant else [],
                questions=result.get("questions", []) if assistant else [],
                created_at=message.created_at,
            )
        )
    return ConversationOut(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=out,
        latest_run=ChatRunOut.model_validate(latest, from_attributes=True) if latest else None,
        unavailable=list(latest.context.get("unavailable", [])) if latest else [],
    )


@router.get(
    "/projects/{project_id}/ai-conversations",
    response_model=list[ConversationListItem],
    summary="Percakapan saya dengan asisten AI di proyek ini",
)
def list_conversations(
    project_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.AI_USE, P.PROJECTS_READ)),
    db: Session = Depends(get_db),
) -> list[ConversationListItem]:
    return [
        ConversationListItem(
            id=c.id,
            project_id=c.project_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=count,
        )
        for c, count in chat.list_conversations(db, ctx, project_id)
    ]


@router.post(
    "/projects/{project_id}/ai-conversations",
    dependencies=EXPENSIVE,
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Mulai percakapan: pertanyaan pertama (dijawab di latar belakang)",
)
def start_conversation(
    project_id: uuid.UUID,
    payload: AskIn,
    background: BackgroundTasks,
    ctx: RequestContext = Depends(require(P.AI_USE, P.PROJECTS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    adapter: AgentAdapter = Depends(get_agent_adapter),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> ConversationOut:
    conversation, run = chat.start_conversation(
        db, ctx, settings, adapter, project_id, payload.message
    )
    background.add_task(chat.execute_answer, run.id, session_factory, adapter, settings)
    return _conversation_out(db, ctx, conversation, settings)


@router.get(
    "/ai-conversations/{conversation_id}",
    response_model=ConversationOut,
    summary="Isi percakapan dan status jawaban terakhir",
)
def get_conversation(
    conversation_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.AI_USE, P.PROJECTS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationOut:
    conversation = chat.get_conversation(db, ctx, conversation_id)
    return _conversation_out(db, ctx, conversation, settings)


@router.post(
    "/ai-conversations/{conversation_id}/messages",
    dependencies=EXPENSIVE,
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ajukan pertanyaan lanjutan (dijawab di latar belakang)",
)
def ask(
    conversation_id: uuid.UUID,
    payload: AskIn,
    background: BackgroundTasks,
    ctx: RequestContext = Depends(require(P.AI_USE, P.PROJECTS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    adapter: AgentAdapter = Depends(get_agent_adapter),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> ConversationOut:
    conversation, run = chat.ask(db, ctx, settings, adapter, conversation_id, payload.message)
    background.add_task(chat.execute_answer, run.id, session_factory, adapter, settings)
    return _conversation_out(db, ctx, conversation, settings)


@router.delete(
    "/ai-conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus percakapan saya",
    response_class=Response,
)
def delete_conversation(
    conversation_id: uuid.UUID,
    ctx: RequestContext = Depends(require(P.AI_USE, P.PROJECTS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    chat.delete_conversation(db, ctx, conversation_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
