from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.enums import DraftStatus
from app.persistence import DraftBatch, PublicationDraft, ValidationResult
from app.publication.payload import ordered_image_urls
from app.publication.preflight import (
    build_preflight_context,
    build_preflight_payload,
    validate_preflight_payloads,
)
from app.publication.validation import build_validation_context, validate_draft_with_context

logger = logging.getLogger("draft-validation-performance")


@dataclass(slots=True)
class DraftValidationOutcome:
    draft: PublicationDraft
    errors: list[dict]
    warnings: list[dict]

    @property
    def valid(self) -> bool:
        return not self.errors


def _persist_outcomes(db: Session, outcomes: list[DraftValidationOutcome]) -> None:
    if not outcomes:
        return
    draft_ids = [outcome.draft.id for outcome in outcomes]
    db.execute(delete(ValidationResult).where(ValidationResult.draft_id.in_(draft_ids)))
    db.add_all([
        ValidationResult(
            draft_id=outcome.draft.id,
            valid=outcome.valid,
            errors=outcome.errors,
            warnings=outcome.warnings,
        )
        for outcome in outcomes
    ])
    for outcome in outcomes:
        outcome.draft.status = DraftStatus.READY if outcome.valid else DraftStatus.INVALID


def validate_batch_drafts(
    db: Session,
    *,
    batch: DraftBatch,
    image_url_for: Callable[[str], str],
) -> list[DraftValidationOutcome]:
    """Validate a batch while sharing product/category work across all drafts."""

    candidates = [
        draft
        for draft in sorted(batch.drafts, key=lambda item: item.sequence_number)
        if draft.status not in {
            DraftStatus.PUBLISHING,
            DraftStatus.PUBLISHED,
            DraftStatus.EXCLUDED,
            DraftStatus.CANCELLED,
            DraftStatus.UNKNOWN_EXTERNAL_STATE,
        }
    ]
    if not candidates:
        return []

    started = time.perf_counter()
    local_started = time.perf_counter()
    local_context = build_validation_context(db, batch)
    outcomes: list[DraftValidationOutcome] = []
    for draft in candidates:
        errors, warnings = validate_draft_with_context(draft, local_context)
        outcomes.append(DraftValidationOutcome(draft=draft, errors=errors, warnings=warnings))

    local_ms = round((time.perf_counter() - local_started) * 1000)
    provider_candidates = [outcome for outcome in outcomes if outcome.valid]
    provider_ms = 0
    if provider_candidates:
        preflight_context = build_preflight_context(db, batch)
        payloads: dict[uuid.UUID, dict] = {}
        by_id = {outcome.draft.id: outcome for outcome in provider_candidates}

        for outcome in provider_candidates:
            image_urls = ordered_image_urls(
                local_context.version,
                outcome.draft,
                image_url_for,
            )
            payload, payload_errors = build_preflight_payload(
                preflight_context,
                outcome.draft,
                image_urls,
            )
            if payload_errors:
                outcome.errors.extend(payload_errors)
            elif payload is not None:
                payloads[outcome.draft.id] = payload

        if payloads:
            provider_started = time.perf_counter()
            provider_results = validate_preflight_payloads(preflight_context, payloads)
            provider_ms = round((time.perf_counter() - provider_started) * 1000)
            for draft_id, provider_errors in provider_results.items():
                by_id[draft_id].errors.extend(provider_errors)

    _persist_outcomes(db, outcomes)
    logger.info(
        "draft_batch_validation_completed batch=%s drafts=%d provider_calls=%d local_ms=%d provider_ms=%d total_ms=%d",
        batch.id,
        len(outcomes),
        len(provider_candidates),
        local_ms,
        provider_ms,
        round((time.perf_counter() - started) * 1000),
    )
    return outcomes


def validate_single_draft(
    db: Session,
    *,
    draft: PublicationDraft,
    image_url_for: Callable[[str], str],
) -> DraftValidationOutcome:
    batch = db.get(DraftBatch, draft.batch_id)
    if batch is None:
        raise RuntimeError("Draft batch not found during validation.")

    local_context = build_validation_context(db, batch)
    errors, warnings = validate_draft_with_context(draft, local_context)
    outcome = DraftValidationOutcome(draft=draft, errors=errors, warnings=warnings)

    if outcome.valid:
        preflight_context = build_preflight_context(db, batch)
        image_urls = ordered_image_urls(local_context.version, draft, image_url_for)
        payload, payload_errors = build_preflight_payload(preflight_context, draft, image_urls)
        outcome.errors.extend(payload_errors)
        if not outcome.errors and payload is not None:
            outcome.errors.extend(validate_preflight_payloads(
                preflight_context,
                {draft.id: payload},
            )[draft.id])

    _persist_outcomes(db, [outcome])
    return outcome


def approve_ready_drafts(db: Session, *, batch_id: uuid.UUID) -> list[PublicationDraft]:
    """Approve all READY drafts in one transaction instead of one HTTP commit each."""

    drafts = db.scalars(
        select(PublicationDraft)
        .where(
            PublicationDraft.batch_id == batch_id,
            PublicationDraft.status == DraftStatus.READY,
        )
        .order_by(PublicationDraft.sequence_number)
    ).all()
    for draft in drafts:
        draft.status = DraftStatus.APPROVED
        audit(db, "DRAFT_APPROVED", "PublicationDraft", str(draft.id))
    return drafts
