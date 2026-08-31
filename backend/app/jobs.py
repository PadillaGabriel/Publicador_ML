import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.enums import JobItemStatus, JobStatus
from app.core.time import utcnow
from app.core.config import get_settings
from app.persistence import Job, JobItem, PublicationAttempt, PublicationDraft
from app.worker_runtime import publication_worker_status

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
settings = get_settings()


def _current_execution(db, job: Job, worker: dict) -> dict:
    if job.status == JobStatus.PENDING:
        worker_online = bool(worker.get("online"))
        return {
            "current_stage": "WAITING_WORKER" if worker_online else "WORKER_OFFLINE",
            "current_message": (
                "Publicación en cola; esperando asignación automática."
                if worker_online
                else "El job está en cola, pero no hay un worker de publicación activo."
            ),
            "current_draft_id": None,
            "current_sequence": None,
            "current_title": None,
        }

    current_item = db.scalar(
        select(JobItem)
        .where(JobItem.job_id == job.id, JobItem.status == JobItemStatus.RUNNING)
        .order_by(JobItem.id)
        .limit(1)
    )
    if current_item:
        draft = db.get(PublicationDraft, current_item.draft_id)
        attempt = db.scalar(
            select(PublicationAttempt)
            .where(PublicationAttempt.draft_id == current_item.draft_id)
            .order_by(PublicationAttempt.attempt_number.desc())
            .limit(1)
        )
        stage = "PREPARING_PUBLICATION"
        message = "Preparando payload y validaciones finales."
        if attempt and attempt.outcome == "STARTED":
            stage = "SENDING_TO_MERCADOLIBRE"
            message = "Enviando la publicación a Mercado Libre."

        return {
            "current_stage": stage,
            "current_message": message,
            "current_draft_id": str(draft.id) if draft else str(current_item.draft_id),
            "current_sequence": draft.sequence_number if draft else None,
            "current_title": draft.title if draft else None,
        }

    if job.status == JobStatus.RUNNING and job.processed < job.total:
        return {
            "current_stage": "WAITING_NEXT_ITEM",
            "current_message": "Preparando el siguiente borrador del lote.",
            "current_draft_id": None,
            "current_sequence": None,
            "current_title": None,
        }

    return {
        "current_stage": "FINISHED",
        "current_message": "El job terminó.",
        "current_draft_id": None,
        "current_sequence": None,
        "current_title": None,
    }




def _job_failures(db, job: Job) -> list[dict]:
    rows = db.execute(
        select(JobItem, PublicationDraft)
        .join(PublicationDraft, PublicationDraft.id == JobItem.draft_id)
        .where(
            JobItem.job_id == job.id,
            JobItem.status.in_([JobItemStatus.FAILED, JobItemStatus.UNKNOWN]),
        )
        .order_by(PublicationDraft.sequence_number)
    ).all()

    failures: list[dict] = []
    for item, draft in rows:
        error = item.last_error or {}
        failures.append({
            "job_item_id": str(item.id),
            "draft_id": str(item.draft_id),
            "sequence_number": draft.sequence_number,
            "title": draft.title,
            "status": item.status,
            "error": {
                "code": error.get("code"),
                "message": error.get("message"),
                "http_status": error.get("http_status"),
                "provider_error": error.get("provider_error"),
                "causes": error.get("causes") or [],
            },
        })
    return failures


def _job_warnings(db, job: Job) -> list[dict]:
    rows = db.execute(
        select(JobItem, PublicationDraft)
        .join(PublicationDraft, PublicationDraft.id == JobItem.draft_id)
        .where(JobItem.job_id == job.id, JobItem.status == JobItemStatus.SUCCEEDED)
        .order_by(PublicationDraft.sequence_number)
    ).all()
    warnings: list[dict] = []
    for item, draft in rows:
        error = item.last_error or {}
        if error.get("code") != "QUANTITY_PRICE_SYNC_FAILED":
            continue
        warnings.append({
            "job_item_id": str(item.id),
            "draft_id": str(item.draft_id),
            "sequence_number": draft.sequence_number,
            "title": draft.title,
            "code": error.get("code"),
            "message": error.get("message"),
            "http_status": error.get("http_status"),
            "provider_error": error.get("provider_error"),
        })
    return warnings

def job_dict(db, job: Job) -> dict:
    pct = int((job.processed / job.total) * 100) if job.total else 100
    worker = publication_worker_status(
        db,
        stale_after_seconds=settings.worker_heartbeat_stale_seconds,
    )
    return {
        "id": str(job.id),
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "progress": pct,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "failures": _job_failures(db, job),
        "warnings": _job_warnings(db, job),
        "worker": worker,
        **_current_execution(db, job, worker),
    }


@router.get("/worker-status")
def get_worker_status():
    with SessionLocal() as db:
        return publication_worker_status(
            db,
            stale_after_seconds=settings.worker_heartbeat_stale_seconds,
        )


@router.get("/active/current")
def get_active_job():
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .where(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return {"job": job_dict(db, job) if job else None}


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job_dict(db, job)




@router.post("/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        if job.status != JobStatus.PENDING:
            raise HTTPException(status_code=409, detail="Sólo se puede cancelar un job que todavía está PENDING.")
        items = db.scalars(select(JobItem).where(JobItem.job_id == job.id)).all()
        for item in items:
            if item.status == JobItemStatus.PENDING:
                item.status = JobItemStatus.CANCELLED
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
        db.commit()
        return job_dict(db, job)


@router.get("/{job_id}/events")
async def job_events(job_id: uuid.UUID):
    async def stream():
        last = None
        while True:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if not job:
                    yield "event: error\ndata: {\"detail\":\"Job not found\"}\n\n"
                    return
                current = job_dict(db, job)
            raw = json.dumps(current)
            if raw != last:
                yield f"event: progress\ndata: {raw}\n\n"
                last = raw
            if current["status"] in {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
