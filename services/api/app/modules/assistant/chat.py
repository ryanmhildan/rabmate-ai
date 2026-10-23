"""Project chat with the local assistant (ADR-044).

A question is answered from data gathered by the backend through the read-only tool registry,
with the asking user's permissions: the project, its RABs (rab.read), catalog prices matching
the question (pricing.read), and its documents (invoices only with finance.read). Each piece is
a numbered source ([S1], [S2], …) the model must cite. The answer is checked by code — citations
to unknown sources are removed, amounts found in no source are flagged — and stored with the
sources it cited, so the user sees what it was based on. Answers are advisory only: the chat has
no tool that changes anything. Conversations are private to the user who started them.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.adapter import AgentAdapter
from app.ai.jsonout import first_json_object
from app.ai.runtime import SessionFactory
from app.api.deps import RequestContext
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.modules.assistant import service, tools
from app.modules.assistant.models import (
    ACTIVE_STATUSES,
    AiConversation,
    AiMessage,
    AiRun,
    AiRunKind,
    AiRunStatus,
    MessageRole,
)
from app.modules.assistant.workflows import ChatRaw, chat_request, finish_answer
from app.modules.identity.permissions import Permission
from app.modules.projects import service as projects

logger = logging.getLogger(__name__)

KIND = AiRunKind.CHAT_ANSWER
LIST_LIMIT = 30
MESSAGES_LIMIT = 100
HISTORY_MESSAGES = 6
HISTORY_MESSAGE_CHARS = 800
MAX_CONTEXT_CHARS = 16_000
MIN_RAB_ITEMS = 5
_CITE = re.compile(r"\s*\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- reading


def get_conversation(
    db: Session, ctx: RequestContext, conversation_id: uuid.UUID, *, lock: bool = False
) -> AiConversation:
    stmt = select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.organization_id == ctx.organization_id,
        AiConversation.created_by_id == ctx.user_id,  # private to its author
    )
    if lock:
        stmt = stmt.with_for_update()
    conversation = db.execute(stmt).scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("Percakapan tidak ditemukan.")
    return conversation


def list_conversations(
    db: Session, ctx: RequestContext, project_id: uuid.UUID
) -> list[tuple[AiConversation, int]]:
    projects.get_project(db, ctx, project_id)
    counts = (
        select(AiMessage.conversation_id, func.count().label("n"))
        .where(AiMessage.organization_id == ctx.organization_id)
        .group_by(AiMessage.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(AiConversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == AiConversation.id)
        .where(
            AiConversation.organization_id == ctx.organization_id,
            AiConversation.project_id == project_id,
            AiConversation.created_by_id == ctx.user_id,
        )
        .order_by(AiConversation.updated_at.desc())
        .limit(LIST_LIMIT)
    ).all()
    return [(conversation, int(count)) for conversation, count in rows]


def messages_of(db: Session, conversation: AiConversation) -> list[AiMessage]:
    latest = list(
        db.execute(
            select(AiMessage)
            .where(
                AiMessage.organization_id == conversation.organization_id,
                AiMessage.conversation_id == conversation.id,
            )
            .order_by(AiMessage.created_at.desc())
            .limit(MESSAGES_LIMIT)
        ).scalars()
    )
    return latest[::-1]


def runs_by_id(db: Session, messages: list[AiMessage]) -> dict[uuid.UUID, AiRun]:
    ids = [m.run_id for m in messages if m.role is MessageRole.ASSISTANT and m.run_id]
    if not ids:
        return {}
    return {r.id: r for r in db.execute(select(AiRun).where(AiRun.id.in_(ids))).unique().scalars()}


def latest_run(
    db: Session, ctx: RequestContext, conversation: AiConversation, settings: Settings
) -> AiRun | None:
    run = (
        db.execute(
            select(AiRun)
            .where(
                AiRun.organization_id == ctx.organization_id,
                AiRun.conversation_id == conversation.id,
            )
            .order_by(AiRun.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one_or_none()
    )
    if run is not None:
        service._expire_if_stale(db, run, settings)
    return run


# --------------------------------------------------------------------------- sources


class _Sources:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.unavailable: list[str] = []

    def add(self, kind: str, label: str, ref: dict[str, str] | None, data: dict[str, Any]) -> None:
        self.items.append(
            {
                "id": f"S{len(self.items) + 1}",
                "kind": kind,
                "label": label[:200],
                "ref": ref,
                "data": data,
            }
        )


def _without_ids(data: dict[str, Any]) -> dict[str, Any]:
    """Database ids mean nothing to the model; links keep them in `ref`."""
    return {k: v for k, v in data.items() if k not in ("id", "project_id")}


def _fit(sources: list[dict[str, Any]]) -> None:
    """Keeps the data within the model's budget by showing fewer RAB items (noted in the data)."""

    def size() -> int:
        return len(json.dumps([s["data"] for s in sources], ensure_ascii=False, default=str))

    while size() > MAX_CONTEXT_CHARS:
        rabs = [
            s for s in sources if s["kind"] == "rab" and len(s["data"]["items"]) > MIN_RAB_ITEMS
        ]
        if not rabs:
            break
        largest = max(rabs, key=lambda s: len(s["data"]["items"]))
        data = largest["data"]
        data["items"] = data["items"][: max(MIN_RAB_ITEMS, len(data["items"]) // 2)]
        data["catatan"] = (
            f"Hanya {len(data['items'])} dari {data['item_count']} item yang ditampilkan."
        )
    while size() > MAX_CONTEXT_CHARS and any(s["kind"] == "katalog" for s in sources):
        last = max(i for i, s in enumerate(sources) if s["kind"] == "katalog")
        sources.pop(last)


def gather_sources(
    db: Session, ctx: RequestContext, project_id: uuid.UUID, question: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """The data for one answer, read with the asking user's permissions."""
    found = _Sources()
    project = cast(
        tools.ProjectDetailsOut,
        tools.call_tool(db, ctx, KIND, "get_project_details", {"project_id": project_id}),
    )
    found.add(
        "proyek",
        f"Proyek {project.number} — {project.name}",
        {"type": "project", "id": str(project_id)},
        project.model_dump(mode="json"),
    )
    if ctx.can(Permission.RAB_READ):
        rabs = cast(
            tools.ProjectRabsOut,
            tools.call_tool(db, ctx, KIND, "get_project_rabs", {"project_id": project_id}),
        )
        for rab in rabs.rabs:
            found.add(
                "rab",
                f"{rab.number} v{rab.version_no} ({rab.status}) — {rab.title}",
                {"type": "rab", "id": str(rab.id)},
                _without_ids(rab.model_dump(mode="json")),
            )
        if rabs.rab_count == 0:
            found.unavailable.append("Proyek ini belum memiliki RAB.")
        elif rabs.rab_count > len(rabs.rabs):
            found.unavailable.append(
                f"Hanya {len(rabs.rabs)} dari {rabs.rab_count} RAB terbaru yang disertakan."
            )
    else:
        found.unavailable.append("Data RAB (Anda tidak memiliki izin melihat RAB).")
    if ctx.can(Permission.PRICING_READ):
        catalog = cast(
            tools.CatalogSearchOut,
            tools.call_tool(db, ctx, KIND, "search_catalog", {"query": question[:300]}),
        )
        for hit in catalog.items:
            found.add(
                "katalog",
                f"Katalog: {hit.name}",
                {"type": "catalog_item", "id": str(hit.id)},
                _without_ids(hit.model_dump(mode="json")),
            )
        if catalog.terms and not catalog.items and asks_about_prices(question):
            found.unavailable.append(
                f"Katalog harga: tidak ada item yang cocok dengan kata '{' '.join(catalog.terms)}'."
            )
    else:
        found.unavailable.append("Katalog harga (Anda tidak memiliki izin melihat katalog).")
    documents = cast(
        tools.ProjectDocumentsOut,
        tools.call_tool(db, ctx, KIND, "get_project_documents", {"project_id": project_id}),
    )
    if documents.documents:
        found.add(
            "dokumen",
            "Dokumen proyek (penawaran, SPK, BAST, invoice)",
            {"type": "project_documents", "id": str(project_id)},
            documents.model_dump(mode="json"),
        )
    if not ctx.can(Permission.FINANCE_READ):
        found.unavailable.append("Invoice dan pembayaran (Anda tidak memiliki izin keuangan).")
    _fit(found.items)
    return found.items, found.unavailable


_PRICE_WORDS = re.compile(
    r"\b(harga|katalog|biaya|tarif|price|pemasok|supplier)(nya)?\b", re.IGNORECASE
)


def asks_about_prices(question: str) -> bool:
    """Only then is "nothing in the catalog matched" worth telling the model and the user."""
    return _PRICE_WORDS.search(question) is not None


def _history(db: Session, conversation: AiConversation) -> list[dict[str, str]]:
    """The last turns, without citation markers (they pointed at an earlier set of sources)."""
    turns = []
    for message in messages_of(db, conversation)[-HISTORY_MESSAGES:]:
        text = _CITE.sub("", message.content)[:HISTORY_MESSAGE_CHARS]
        turns.append({"role": message.role.value, "content": text})
    return turns


# --------------------------------------------------------------------------- asking


def _ask(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    conversation: AiConversation,
    question: str,
) -> AiRun:
    history = _history(db, conversation)
    sources, unavailable = gather_sources(db, ctx, conversation.project_id, question)
    service.expire_stale_runs(db, ctx, settings)
    run = AiRun(
        organization_id=ctx.organization_id,
        conversation_id=conversation.id,
        kind=KIND,
        status=AiRunStatus.QUEUED,
        input={"question": question, "history": history},
        context={"sources": sources, "unavailable": unavailable},
        created_by_id=ctx.user_id,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise service.AiBusyError() from None
    db.add(
        AiMessage(
            organization_id=ctx.organization_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=question,
            run_id=run.id,
        )
    )
    conversation.updated_at = _now()
    service._audit(
        db,
        ctx,
        "ai_run.create",
        run,
        f"{service.KIND_LABELS[KIND]} · {len(sources)} sumber",  # never the question itself
        {"kind": {"from": None, "to": KIND.value}},
    )
    db.commit()
    return run


def start_conversation(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    adapter: AgentAdapter,
    project_id: uuid.UUID,
    question: str,
) -> tuple[AiConversation, AiRun]:
    service.ensure_ready(settings, adapter)
    project = projects.get_project(db, ctx, project_id)
    title = " ".join(question.split())
    conversation = AiConversation(
        organization_id=ctx.organization_id,
        project_id=project.id,
        title=title if len(title) <= 80 else title[:79].rstrip() + "…",
        created_by_id=ctx.user_id,
    )
    db.add(conversation)
    db.flush()
    run = _ask(db, ctx, settings, conversation, question)
    return conversation, run


def ask(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    adapter: AgentAdapter,
    conversation_id: uuid.UUID,
    question: str,
) -> tuple[AiConversation, AiRun]:
    service.ensure_ready(settings, adapter)
    conversation = get_conversation(db, ctx, conversation_id, lock=True)
    current = latest_run(db, ctx, conversation, settings)
    if current is not None and current.status in ACTIVE_STATUSES:
        raise ConflictError("Pertanyaan sebelumnya masih diproses. Tunggu jawabannya dulu.")
    return conversation, _ask(db, ctx, settings, conversation, question)


def delete_conversation(
    db: Session, ctx: RequestContext, conversation_id: uuid.UUID, settings: Settings
) -> None:
    conversation = get_conversation(db, ctx, conversation_id, lock=True)
    current = latest_run(db, ctx, conversation, settings)
    if current is not None and current.status in ACTIVE_STATUSES:
        raise ConflictError("Tunggu hingga jawaban selesai sebelum menghapus percakapan.")
    db.delete(conversation)
    db.commit()


# --------------------------------------------------------------------------- answering


def _shown_sources(context: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """The cited sources, then those the answer's numbers really came from (marked uncited)."""
    by_id = {s["id"]: s for s in context.get("sources", [])}
    cited = [by_id[i] | {"cited": True} for i in result["cited"] if i in by_id]
    related = [by_id[i] | {"cited": False} for i in result.get("related", []) if i in by_id]
    return cited + related


def execute_answer(
    run_id: uuid.UUID,
    session_factory: SessionFactory,
    adapter: AgentAdapter,
    settings: Settings,
) -> None:
    """Background task: answers one question; holds no DB transaction while the model works."""
    with session_factory() as db:
        run = db.execute(
            select(AiRun).where(AiRun.id == run_id).with_for_update(of=AiRun)
        ).scalar_one_or_none()
        if run is None or run.status is not AiRunStatus.QUEUED or run.kind is not KIND:
            return
        run.status = AiRunStatus.RUNNING
        run.started_at = _now()
        run_input, context = dict(run.input), dict(run.context)
        db.commit()

    sources: list[dict[str, Any]] = context.get("sources", [])
    request = chat_request(
        run_input["question"],
        history=run_input.get("history", []),
        sources=sources,
        unavailable=context.get("unavailable", []),
    )

    def finish(text: str) -> dict[str, Any]:
        return finish_answer(
            ChatRaw.model_validate(first_json_object(text)),
            sources=sources,
            question=run_input["question"],
        )

    outcome = service.with_model(
        settings, lambda o: service.complete(adapter, request, finish, settings, o)
    )

    def store(db: Session, run: AiRun, result: dict[str, Any]) -> None:
        db.add(
            AiMessage(
                organization_id=run.organization_id,
                conversation_id=run.conversation_id,
                role=MessageRole.ASSISTANT,
                content=result["answer"],
                sources=_shown_sources(context, result),
                warnings=result["warnings"],
                run_id=run.id,
            )
        )

    service.finish_run(run_id, session_factory, outcome, on_success=store)
