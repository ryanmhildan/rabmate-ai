"""AI runs: request, background execution, review, apply/discard (ADR-041).

Flow: a user with `ai.use` asks for a draft on a draft RAB version → the backend reads the data
the workflow is allowed to see through the tool registry and stores the run (queued) → a
background task calls the local model through the adapter, parses and validates the reply, and
stores the draft (or a user-safe error) → the user reviews, edits and applies selected items,
which go through the normal RAB rules (version must be draft, catalog prices resolved
server-side). Model failures only ever mark the run failed; business data is untouched.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.adapter import AgentAdapter, AgentError, AgentRequest, AgentState, Message
from app.ai.jsonout import first_json_object
from app.ai.numbers import NumberFormat
from app.ai.runtime import SessionFactory, agent_health
from app.api.deps import RequestContext
from app.core.config import Settings
from app.core.errors import (
    AppError,
    BusinessValidationError,
    ConflictError,
    NotFoundError,
)
from app.modules.assistant import tools
from app.modules.assistant.models import (
    ACTIVE_STATUSES,
    ITEM_KINDS,
    AiRun,
    AiRunKind,
    AiRunStatus,
)
from app.modules.assistant.schemas import ApplyIn, RunCreate
from app.modules.assistant.workflows import (
    DraftRaw,
    ExtractRaw,
    SourceLine,
    build_request,
    chunk_lines,
    document_lines,
    extraction_request,
    finish_draft,
    finish_extraction,
    merge_extractions,
    repair_message,
    text_lines,
)
from app.modules.audit import service as audit
from app.modules.intake import service as intake
from app.modules.intake.models import SourceKind
from app.modules.intake.ocr import OcrEngine, get_ocr
from app.modules.intake.sniff import UnsupportedFileError
from app.modules.pricing import service as pricing
from app.modules.pricing.units import same_unit
from app.modules.rab import service as rab_service
from app.modules.rab.models import PriceSourceType, RabItem, RabItemType, RabStatus, RabVersion

logger = logging.getLogger(__name__)

ENTITY = "ai_run"
KIND_LABELS = {
    AiRunKind.RAB_DRAFT: "Draft RAB dari deskripsi",
    AiRunKind.EXTRACT_ITEMS: "Ekstraksi item dari teks",
    AiRunKind.EXTRACT_DOCUMENT: "Ekstraksi item dari berkas",
    AiRunKind.CHAT_ANSWER: "Jawaban chat proyek",
}
LIST_LIMIT = 20
# One generation at a time on the local GPU, across all organizations served by this process.
_MODEL_LOCK = threading.Lock()


class AiDisabledError(AppError):
    status_code = 503
    code = "ai_disabled"
    message = "Asisten AI lokal belum diaktifkan. Fitur lain tetap dapat digunakan."


class AiNotReadyError(AppError):
    status_code = 503
    code = "ai_unavailable"


class AiBusyError(ConflictError):
    code = "ai_busy"
    message = (
        "Asisten AI sedang memproses permintaan lain di organisasi ini. Tunggu hingga selesai."
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: Session,
    ctx: RequestContext,
    action: str,
    run: AiRun,
    summary: str,
    changes: dict[str, Any] | None = None,
) -> None:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity_type=ENTITY,
        entity_id=run.id,
        summary=summary,
        changes=changes,
        ip_address=ctx.ip_address,
    )


# --------------------------------------------------------------------------- reading


def stale_after(settings: Settings, kind: AiRunKind | None = None) -> timedelta:
    """How long a queued/running run may stay active before it is considered interrupted."""
    calls = settings.ai_max_chunks if kind is AiRunKind.EXTRACT_DOCUMENT else 1
    budget = settings.ai_request_timeout_seconds * (settings.ai_max_retries + 1) * 2 * calls
    if kind is AiRunKind.EXTRACT_DOCUMENT and settings.ocr_enabled:
        budget += settings.ocr_timeout_seconds * settings.ocr_max_pages
    return timedelta(seconds=budget + 120)


def _expire_if_stale(db: Session, run: AiRun, settings: Settings) -> None:
    deadline = _now() - stale_after(settings, run.kind)
    if run.status in ACTIVE_STATUSES and run.created_at < deadline:
        run.status = AiRunStatus.FAILED
        run.error_code = "ai_interrupted"
        run.error_message = "Proses AI terhenti (server dimulai ulang atau melewati batas waktu)."
        run.finished_at = _now()
        db.commit()


def get_run(
    db: Session,
    ctx: RequestContext,
    run_id: uuid.UUID,
    settings: Settings,
    *,
    lock: bool = False,
    kinds: Sequence[AiRunKind] = ITEM_KINDS,
) -> AiRun:
    """A run of the organization. Chat answers are reachable only through their (private)
    conversation, so by default only item runs are returned."""
    stmt = (
        select(AiRun)
        .where(
            AiRun.id == run_id,
            AiRun.organization_id == ctx.organization_id,
            AiRun.kind.in_(kinds),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=AiRun)
    run = db.execute(stmt).unique().scalar_one_or_none()
    if run is None:
        raise NotFoundError("Permintaan AI tidak ditemukan.")
    if not lock:
        _expire_if_stale(db, run, settings)
    return run


def list_runs(
    db: Session, ctx: RequestContext, rab_id: uuid.UUID, version_no: int, settings: Settings
) -> list[AiRun]:
    version = rab_service.get_version(db, ctx, rab_id, version_no)
    runs = list(
        db.execute(
            select(AiRun)
            .where(
                AiRun.organization_id == ctx.organization_id,
                AiRun.rab_version_id == version.id,
                AiRun.kind.in_(ITEM_KINDS),
            )
            .order_by(AiRun.created_at.desc())
            .limit(LIST_LIMIT)
        )
        .unique()
        .scalars()
    )
    for run in runs:
        _expire_if_stale(db, run, settings)
    return runs


def item_count(run: AiRun) -> int:
    return len(run.result.get("items", [])) if run.result else 0


# --------------------------------------------------------------------------- creating


def expire_stale_runs(db: Session, ctx: RequestContext, settings: Settings) -> None:
    """Interrupted runs must not keep the organization's single model slot (they are only
    otherwise expired when someone opens them)."""
    for run in db.execute(
        select(AiRun).where(
            AiRun.organization_id == ctx.organization_id, AiRun.status.in_(ACTIVE_STATUSES)
        )
    ).scalars():
        _expire_if_stale(db, run, settings)


def ensure_ready(settings: Settings, adapter: AgentAdapter) -> None:
    """Refuses up front when AI is off or the agent is down or unsafe (the adapter re-checks
    before every call)."""
    if not settings.ai_enabled:
        raise AiDisabledError()
    health = agent_health(settings, adapter)
    if health.state is not AgentState.READY:
        error = AiNotReadyError(health.message)
        if health.state is AgentState.UNSAFE:
            error.code = "ai_unsafe_config"
        raise error


def create_run(
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    adapter: AgentAdapter,
    rab_id: uuid.UUID,
    version_no: int,
    payload: RunCreate,
) -> AiRun:
    ensure_ready(settings, adapter)
    version = rab_service.get_version(db, ctx, rab_id, version_no)
    if version.status is not RabStatus.DRAFT:
        raise ConflictError("Asisten AI hanya dapat menyiapkan item untuk versi RAB draft.")
    if (
        payload.kind is AiRunKind.EXTRACT_ITEMS
        and payload.text is not None
        and len(payload.text) > settings.ai_max_input_chars
    ):
        raise BusinessValidationError(
            f"Teks terlalu panjang (maks. {settings.ai_max_input_chars:,} karakter). "
            "Bagi menjadi beberapa bagian.".replace(",", "."),
            details=[{"loc": ["body", "text"], "msg": "Terlalu panjang."}],
        )

    # The data the model sees comes only through allowlisted, permission-checked tools.
    kind = payload.kind
    source_document_id: uuid.UUID | None = None
    rab = tools.call_tool(
        db, ctx, kind, "get_rab_version", {"rab_id": rab_id, "version_no": version_no}
    )
    context: dict[str, Any] = {"rab": rab.model_dump(mode="json")}
    if kind is AiRunKind.RAB_DRAFT:
        project = tools.call_tool(
            db, ctx, kind, "get_project_details", {"project_id": version.rab.project_id}
        )
        context["project"] = project.model_dump(mode="json")
        run_input: dict[str, Any] = {
            "description": payload.description,
            "number_format": payload.number_format.value,
        }
    elif kind is AiRunKind.EXTRACT_DOCUMENT:
        doc = cast(
            tools.SourceDocumentOut,
            tools.call_tool(
                db,
                ctx,
                kind,
                "get_source_document",
                {"source_document_id": payload.source_document_id},
            ),
        )
        if doc.project_id != version.rab.project_id:
            raise BusinessValidationError(
                "Dokumen sumber milik proyek lain. Unggah dokumen ke proyek RAB ini.",
                details=[{"loc": ["body", "source_document_id"], "msg": "Proyek berbeda."}],
            )
        source_document_id = doc.id
        context["document"] = doc.model_dump(mode="json")
        # Spreadsheet cells are written out in Indonesian notation by the reader, whatever the
        # file's locale; for PDF, CSV and scans the user says how the document writes numbers.
        number_format = (
            NumberFormat.ID if doc.kind == SourceKind.XLSX.value else payload.number_format
        )
        run_input = {
            "source_document_id": str(doc.id),
            "source_label": doc.filename,
            "number_format": number_format.value,
        }
    else:
        run_input = {
            "text": payload.text,
            "source_label": payload.source_label,
            "number_format": payload.number_format.value,
        }

    expire_stale_runs(db, ctx, settings)
    run = AiRun(
        organization_id=ctx.organization_id,
        rab_version_id=version.id,
        source_document_id=source_document_id,
        kind=kind,
        status=AiRunStatus.QUEUED,
        input=run_input,
        context=context,
        created_by_id=ctx.user_id,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AiBusyError() from None
    _audit(
        db,
        ctx,
        "ai_run.create",
        run,
        f"{KIND_LABELS[kind]} · {context['rab']['number']} v{version_no}",
        {"kind": {"from": None, "to": kind.value}},
    )
    db.commit()
    return get_run(db, ctx, run.id, settings)


# --------------------------------------------------------------------------- executing


@dataclass
class Outcome:
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    model: str | None = None
    attempts: int = 0
    duration_ms: int = 0


@dataclass
class DocumentText:
    """What was read from an uploaded file, ready to be sent to the model in chunks."""

    lines: list[SourceLine]
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    ocr_pages: int = 0


def document_text(extraction: dict[str, Any]) -> DocumentText:
    pages = extraction.get("pages", [])
    return DocumentText(
        lines=document_lines(extraction),
        warnings=list(extraction.get("warnings", [])),
        pages=len(pages),
        ocr_pages=sum(1 for p in pages if p.get("method") == "ocr"),
    )


def _finish(
    kind: AiRunKind, text: str, run_input: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    data = first_json_object(text)
    number_format = NumberFormat(run_input["number_format"])
    if kind is AiRunKind.RAB_DRAFT:
        return finish_draft(
            DraftRaw.model_validate(data),
            description=run_input["description"],
            existing=[i["name"] for i in context["rab"]["items"]],
            number_format=number_format,
        )
    return finish_extraction(
        ExtractRaw.model_validate(data),
        lines=text_lines(run_input["text"]),
        number_format=number_format,
    )


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "objek"
        return f"field '{where}': {first['msg']}"
    return str(exc)


def complete(
    adapter: AgentAdapter,
    request: AgentRequest,
    finish: Callable[[str], dict[str, Any]],
    settings: Settings,
    outcome: Outcome,
) -> dict[str, Any] | None:
    """One model request, retried with a repair message while the reply fails the checks.
    Returns None when every attempt was unusable; AgentError (agent down/unsafe) propagates."""
    messages = list(request.messages)
    tries = 0
    while True:
        tries += 1
        outcome.attempts += 1
        reply = adapter.complete(AgentRequest(request.instructions, tuple(messages)))
        outcome.duration_ms += reply.duration_ms
        outcome.model = reply.model
        try:
            return finish(reply.text)
        except (ValueError, ValidationError) as exc:
            logger.info("ai output rejected (attempt %d): %s", tries, type(exc).__name__)
            if tries > settings.ai_max_retries:
                return None
            messages += [Message("assistant", reply.text[:4000]), repair_message(_reason(exc))]


def _span(lines: Sequence[SourceLine]) -> str:
    where = f"baris {lines[0].no}-{lines[-1].no}" if len(lines) > 1 else f"baris {lines[0].no}"
    pages = list(dict.fromkeys(line.page for line in lines if line.page))
    if pages:
        where += f" ({pages[0]}" + (f" s.d. {pages[-1]})" if len(pages) > 1 else ")")
    return where


def _chunk_finisher(
    lines: list[SourceLine], number_format: NumberFormat
) -> Callable[[str], dict[str, Any]]:
    def finish(text: str) -> dict[str, Any]:
        return finish_extraction(
            ExtractRaw.model_validate(first_json_object(text)),
            lines=lines,
            number_format=number_format,
            warn_if_empty=False,
        )

    return finish


def _extract_document(
    document: DocumentText,
    run_input: dict[str, Any],
    adapter: AgentAdapter,
    settings: Settings,
    outcome: Outcome,
) -> dict[str, Any] | None:
    number_format = NumberFormat(run_input["number_format"])
    chunks, left_out = chunk_lines(
        document.lines, max_chars=settings.ai_chunk_chars, max_chunks=settings.ai_max_chunks
    )
    warnings = list(document.warnings)
    if left_out:
        warnings.append(
            f"Dokumen terlalu panjang untuk sekali proses: {_span(left_out)} tidak dibaca AI. "
            "Pisahkan dokumen, lalu proses bagian sisanya."
        )
    parts: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for n, chunk in enumerate(chunks, start=1):
        request = extraction_request(
            chunk.lines,
            source_label=run_input.get("source_label"),
            number_format=number_format,
            header=chunk.header,
            part=(n, len(chunks)),
        )
        part = complete(
            adapter, request, _chunk_finisher(chunk.lines, number_format), settings, outcome
        )
        if part is None:
            unreadable.append(_span(chunk.lines))
        else:
            parts.append(part)
    if not parts:
        return None
    warnings.extend(
        f"Jawaban AI untuk {where} tidak sesuai format; periksa bagian itu secara manual."
        for where in unreadable
    )
    result = merge_extractions(parts, warnings)
    result["document"] = {
        "pages": document.pages,
        "lines": len(document.lines),
        "chunks": len(chunks),
        "ocr_pages": document.ocr_pages,
        "lines_left_out": len(left_out),
    }
    return result


def with_model(settings: Settings, work: Callable[[Outcome], dict[str, Any] | None]) -> Outcome:
    """Runs `work` while holding the local model; turns every failure into a user-safe outcome."""
    outcome = Outcome()
    if not _MODEL_LOCK.acquire(timeout=settings.ai_request_timeout_seconds):
        outcome.error_code = "ai_busy"
        outcome.error_message = "AI lokal sedang melayani permintaan lain. Coba lagi nanti."
        return outcome
    try:
        outcome.result = work(outcome)
        if outcome.result is None:
            outcome.error_code = "ai_bad_output"
            outcome.error_message = (
                "Jawaban AI tidak sesuai format yang diminta setelah "
                f"{outcome.attempts} percobaan. Coba sederhanakan permintaan."
            )
        return outcome
    except AgentError as exc:
        outcome.result = None
        outcome.error_code = exc.code
        outcome.error_message = exc.message
        return outcome
    except Exception as exc:  # never let a model problem escape into business data
        logger.error("ai run crashed: %s", type(exc).__name__)
        outcome.result = None
        outcome.error_code = "ai_internal"
        outcome.error_message = "Terjadi kesalahan tak terduga saat memproses permintaan AI."
        return outcome
    finally:
        _MODEL_LOCK.release()


def run_model(
    kind: AiRunKind,
    run_input: dict[str, Any],
    context: dict[str, Any],
    adapter: AgentAdapter,
    settings: Settings,
    document: DocumentText | None = None,
) -> Outcome:
    def work(outcome: Outcome) -> dict[str, Any] | None:
        if kind is AiRunKind.EXTRACT_DOCUMENT:
            if document is None:
                raise ValueError("document text missing")
            return _extract_document(document, run_input, adapter, settings, outcome)
        request = build_request(kind, run_input, context)
        return complete(
            adapter,
            request,
            lambda text: _finish(kind, text, run_input, context),
            settings,
            outcome,
        )

    return with_model(settings, work)


def _read_document(
    run_input: dict[str, Any],
    session_factory: SessionFactory,
    ocr: OcrEngine,
    settings: Settings,
) -> DocumentText | Outcome:
    """Reads (and OCRs) the uploaded file before the model is involved; failures are final."""
    try:
        with session_factory() as db:
            extraction = intake.extraction_of(
                db, uuid.UUID(run_input["source_document_id"]), ocr, settings
            )
    except UnsupportedFileError as exc:
        return Outcome(error_code="document_unreadable", error_message=str(exc)[:500])
    except Exception as exc:
        logger.error("document read crashed: %s", type(exc).__name__)
        return Outcome(
            error_code="document_unreadable",
            error_message="Dokumen tidak dapat dibaca karena kesalahan tak terduga.",
        )
    document = document_text(extraction)
    if not document.lines:
        reasons = " ".join(document.warnings[:3])
        return Outcome(
            error_code="document_empty",
            error_message=f"Tidak ada teks yang dapat dibaca dari dokumen. {reasons}"[:500].strip(),
        )
    return document


def execute_run(
    run_id: uuid.UUID,
    session_factory: SessionFactory,
    adapter: AgentAdapter,
    settings: Settings,
    ocr: OcrEngine | None = None,
) -> None:
    """Background task. Holds no DB transaction while the model is working."""
    with session_factory() as db:
        run = db.execute(
            select(AiRun).where(AiRun.id == run_id).with_for_update(of=AiRun)
        ).scalar_one_or_none()
        if run is None or run.status is not AiRunStatus.QUEUED:
            return
        run.status = AiRunStatus.RUNNING
        run.started_at = _now()
        kind, run_input, context = run.kind, dict(run.input), dict(run.context)
        db.commit()

    document: DocumentText | None = None
    outcome: Outcome | None = None
    if kind is AiRunKind.EXTRACT_DOCUMENT:
        read = _read_document(run_input, session_factory, ocr or get_ocr(settings), settings)
        if isinstance(read, Outcome):
            outcome = read
        else:
            document = read
    if outcome is None:
        outcome = run_model(kind, run_input, context, adapter, settings, document)
    finish_run(run_id, session_factory, outcome)


def finish_run(
    run_id: uuid.UUID,
    session_factory: SessionFactory,
    outcome: Outcome,
    on_success: Callable[[Session, AiRun, dict[str, Any]], None] | None = None,
) -> bool:
    """Stores the outcome on a running run (and, in the same transaction, whatever
    `on_success` adds); False when the run was expired meanwhile."""
    with session_factory() as db:
        run = db.execute(
            select(AiRun).where(AiRun.id == run_id).with_for_update(of=AiRun)
        ).scalar_one_or_none()
        if run is None or run.status is not AiRunStatus.RUNNING:
            return False  # expired as interrupted meanwhile; keep that verdict
        run.status = AiRunStatus.SUCCEEDED if outcome.result is not None else AiRunStatus.FAILED
        run.result = outcome.result
        run.error_code = outcome.error_code
        run.error_message = outcome.error_message
        run.model = outcome.model[:100] if outcome.model else None
        run.attempts = min(outcome.attempts, 100)
        run.duration_ms = outcome.duration_ms
        run.finished_at = _now()
        if on_success is not None and outcome.result is not None:
            on_success(db, run, outcome.result)
        db.commit()
    logger.info("ai run %s finished: %s", run_id, outcome.error_code or "ok")
    return True


# --------------------------------------------------------------------------- applying


def _lock_version(db: Session, ctx: RequestContext, version_id: uuid.UUID) -> RabVersion:
    version = db.execute(
        select(RabVersion)
        .where(RabVersion.id == version_id, RabVersion.organization_id == ctx.organization_id)
        .options(selectinload(RabVersion.items))
        .with_for_update(of=RabVersion)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError("Versi RAB tidak ditemukan.")
    return version


def source_reference(run: AiRun, source: dict[str, Any]) -> str | None:
    """Where an extracted row came from, as a person would look it up."""
    if run.kind is AiRunKind.EXTRACT_DOCUMENT:
        parts = [f"Dokumen '{run.input.get('source_label') or 'berkas'}'"]
        if source.get("source_page"):
            parts.append(source["source_page"])
        if source.get("source_page_line"):
            parts.append(f"baris {source['source_page_line']}")
        return ", ".join(parts)
    if run.kind is AiRunKind.EXTRACT_ITEMS:
        label = run.input.get("source_label") or "teks tempelan"
        line = f", baris {source['source_line']}" if source.get("source_line") else ""
        return f"Teks dokumen '{label}'{line}"
    return None


def _document_source(run: AiRun, source: dict[str, Any]) -> str:
    return f"{source_reference(run, source)} — diekstrak AI lokal, belum diverifikasi"[:500]


def apply_run(
    db: Session, ctx: RequestContext, run_id: uuid.UUID, payload: ApplyIn, settings: Settings
) -> AiRun:
    run = get_run(db, ctx, run_id, settings)
    if run.rab_version_id is None:
        raise ConflictError("Hasil AI ini tidak terkait versi RAB.")
    # Lock order as every RAB item mutation: version first, then the run.
    version = _lock_version(db, ctx, run.rab_version_id)
    run = get_run(db, ctx, run_id, settings, lock=True)
    if run.status is AiRunStatus.APPLIED:
        return run  # a retried request must not add the items twice
    if run.status is not AiRunStatus.SUCCEEDED or run.result is None:
        raise ConflictError("Hanya hasil AI yang berhasil dan belum dipakai yang dapat diterapkan.")
    if version.status is not RabStatus.DRAFT:
        raise ConflictError("Versi RAB sudah tidak berstatus draft; item tidak dapat ditambahkan.")
    sources: list[dict[str, Any]] = run.result.get("items", [])
    indices = [item.index for item in payload.items]
    if len(set(indices)) != len(indices):
        raise BusinessValidationError("Setiap baris hasil AI hanya boleh dipilih sekali.")

    position = max((i.position for i in version.items), default=0)
    marker = f"Disusun dengan bantuan AI lokal ({KIND_LABELS[run.kind].lower()}); periksa kembali."
    for n, chosen in enumerate(payload.items):
        loc = ["body", "items", n]
        if chosen.index >= len(sources):
            raise BusinessValidationError(
                "Baris hasil AI tidak ditemukan.",
                details=[{"loc": [*loc, "index"], "msg": "Tidak ada."}],
            )
        source = sources[chosen.index]
        unit_price: Decimal | None = None
        price_source_type: PriceSourceType | None = None
        price_source: str | None = None
        observation_id: uuid.UUID | None = None
        if chosen.price == "catalog" and chosen.price_observation_id is not None:
            resolved = pricing.resolve_for_rab(
                db, ctx, chosen.price_observation_id, unit=chosen.unit, currency=version.currency
            )
            unit_price = resolved.observation.price
            price_source_type = PriceSourceType.CATALOG
            price_source = resolved.source_text
            observation_id = resolved.observation.id
        elif chosen.price == "document":
            stated = source.get("unit_price") if run.kind is not AiRunKind.RAB_DRAFT else None
            if stated is None:
                raise BusinessValidationError(
                    "Baris ini tidak memiliki harga satuan yang tertulis di dokumen.",
                    details=[{"loc": [*loc, "price"], "msg": "Tidak ada harga dokumen."}],
                )
            if not source.get("unit") or not same_unit(source["unit"], chosen.unit):
                raise BusinessValidationError(
                    "Harga dari dokumen hanya dapat dipakai dengan satuan yang sama "
                    f"({source.get('unit') or '—'}).",
                    details=[{"loc": [*loc, "unit"], "msg": "Satuan berbeda dari dokumen."}],
                )
            unit_price = Decimal(stated)
            price_source_type = PriceSourceType.IMPORT
            price_source = _document_source(run, source)
        item_type = chosen.item_type or RabItemType(source.get("item_type") or RabItemType.OTHER)
        reference = source_reference(run, source)
        origin = f"Sumber: {reference}." if reference else None
        notes = "\n".join(p for p in (marker, origin, source.get("notes")) if p)
        position += 1
        version.items.append(
            RabItem(
                organization_id=ctx.organization_id,
                version_id=version.id,
                position=position,
                name=chosen.name,
                category=source.get("category"),
                item_type=item_type,
                specification=source.get("specification"),
                quantity=chosen.quantity,
                unit=chosen.unit,
                unit_price=unit_price,
                price_source_type=price_source_type,
                price_source=price_source,
                price_observation_id=observation_id,
                notes=notes[:5000],
            )
        )
    rab_service.recalculate(version)
    run.status = AiRunStatus.APPLIED
    run.applied_at = _now()
    run.applied_by_id = ctx.user_id
    run.applied_count = len(payload.items)
    db.flush()
    rab_service._audit_version(
        db,
        ctx,
        version,
        "rab_item.ai_apply",
        {"items": {"from": None, "to": len(payload.items)}},
        summary_suffix=f"{len(payload.items)} item dari asisten AI",
    )
    _audit(
        db,
        ctx,
        "ai_run.apply",
        run,
        f"{KIND_LABELS[run.kind]} diterapkan ({len(payload.items)} item)",
        {"status": {"from": "succeeded", "to": "applied"}},
    )
    db.commit()
    return get_run(db, ctx, run_id, settings)


def discard_run(db: Session, ctx: RequestContext, run_id: uuid.UUID, settings: Settings) -> AiRun:
    run = get_run(db, ctx, run_id, settings, lock=True)
    if run.status not in (AiRunStatus.SUCCEEDED, AiRunStatus.FAILED):
        raise ConflictError("Hanya hasil yang sudah selesai dan belum dipakai yang dapat dibuang.")
    before = run.status
    run.status = AiRunStatus.DISCARDED
    _audit(
        db,
        ctx,
        "ai_run.discard",
        run,
        KIND_LABELS[run.kind],
        {"status": {"from": before.value, "to": "discarded"}},
    )
    db.commit()
    return get_run(db, ctx, run_id, settings)
