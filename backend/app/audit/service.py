from sqlalchemy.orm import Session

from app.persistence import AuditEvent


def audit(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )
