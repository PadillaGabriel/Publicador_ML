"""Publication worker liveness persisted in PostgreSQL.

The API and worker are separate processes by design. This module provides the
small shared contract required to distinguish a healthy queue from a queue that
has no active consumer, without coupling FastAPI to the worker lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.persistence import WorkerHeartbeat

PUBLICATION_WORKER_ROLE = "PUBLICATION"


def heartbeat_is_fresh(heartbeat_at, *, now, stale_after_seconds: float) -> bool:
    if heartbeat_at is None:
        return False
    threshold = now - timedelta(seconds=max(1.0, stale_after_seconds))
    return heartbeat_at >= threshold


def register_worker(db: Session, *, instance_id: uuid.UUID) -> None:
    """Register a publication worker instance and remove stale runtime rows."""
    now = utcnow()
    db.execute(
        delete(WorkerHeartbeat).where(
            WorkerHeartbeat.role == PUBLICATION_WORKER_ROLE,
            WorkerHeartbeat.heartbeat_at < now - timedelta(days=1),
        )
    )
    db.add(
        WorkerHeartbeat(
            instance_id=instance_id,
            role=PUBLICATION_WORKER_ROLE,
            started_at=now,
            heartbeat_at=now,
        )
    )
    db.commit()


def heartbeat_worker(db: Session, *, instance_id: uuid.UUID) -> None:
    """Refresh the liveness timestamp for one worker instance."""
    heartbeat = db.scalar(
        select(WorkerHeartbeat).where(WorkerHeartbeat.instance_id == instance_id)
    )
    if heartbeat is None:
        register_worker(db, instance_id=instance_id)
        return
    heartbeat.heartbeat_at = utcnow()
    db.commit()


def unregister_worker(db: Session, *, instance_id: uuid.UUID) -> None:
    """Remove the runtime row on a clean worker shutdown."""
    db.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.instance_id == instance_id))
    db.commit()


def publication_worker_status(db: Session, *, stale_after_seconds: float) -> dict:
    """Return current publication-worker availability from persisted heartbeats."""
    now = utcnow()
    latest = db.scalar(
        select(WorkerHeartbeat)
        .where(WorkerHeartbeat.role == PUBLICATION_WORKER_ROLE)
        .order_by(WorkerHeartbeat.heartbeat_at.desc())
        .limit(1)
    )
    online = bool(
        latest
        and heartbeat_is_fresh(
            latest.heartbeat_at,
            now=now,
            stale_after_seconds=stale_after_seconds,
        )
    )
    return {
        "online": online,
        "role": PUBLICATION_WORKER_ROLE,
        "last_heartbeat_at": latest.heartbeat_at.isoformat() if latest else None,
        "started_at": latest.started_at.isoformat() if latest else None,
        "stale_after_seconds": int(max(1.0, stale_after_seconds)),
    }
