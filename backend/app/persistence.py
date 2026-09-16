import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.time import utcnow


class MercadoLibreAccount(Base):
    __tablename__ = "ml_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nickname: Mapped[str] = mapped_column(String(120))
    seller_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    site_id: Mapped[str] = mapped_column(String(10), default="MLA")
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_status: Mapped[str] = mapped_column(String(40), default="CONNECTED", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CategoryMetadataSnapshot(Base):
    __tablename__ = "category_metadata_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(10))
    category_id: Mapped[str] = mapped_column(String(40))
    category_name: Mapped[str] = mapped_column(String(255))
    raw_category: Mapped[dict] = mapped_column(JSONB)
    raw_attributes: Mapped[list] = mapped_column(JSONB)
    normalized_schema: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_category_metadata_latest", "site_id", "category_id", "fetched_at"),
    )


class ProductMaster(Base):
    __tablename__ = "product_masters"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    internal_sku: Mapped[str] = mapped_column(String(120), unique=True)
    internal_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    versions: Mapped[list["ProductVersion"]] = relationship(
        back_populates="master", cascade="all, delete-orphan"
    )


class ProductTechnicalAttribute(Base):
    __tablename__ = "product_technical_attributes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_masters.id", ondelete="CASCADE"), index=True
    )
    attribute_id: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[dict] = mapped_column(JSONB)
    source_category_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    __table_args__ = (
        UniqueConstraint(
            "product_master_id",
            "attribute_id",
            name="uq_product_technical_attribute",
        ),
    )


class ProductVersion(Base):
    __tablename__ = "product_versions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_masters.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[str] = mapped_column(String(40))
    title_reference: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(40), default="new")
    currency_id: Mapped[str] = mapped_column(String(10), default="ARS")
    listing_type_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    commercial: Mapped[dict] = mapped_column(JSONB, default=dict)
    logistics: Mapped[dict] = mapped_column(JSONB, default=dict)
    discovery_context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    master: Mapped["ProductMaster"] = relationship(back_populates="versions")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("product_master_id", "version_number", name="uq_product_version"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_versions.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped["ProductVersion"] = relationship(back_populates="images")


class KeywordTrendSnapshot(Base):
    __tablename__ = "keyword_trend_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(10))
    category_id: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(80), default="mercadolibre_category_trends")
    terms: Mapped[list] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_keyword_trends_latest", "site_id", "category_id", "fetched_at"),
    )


class KeywordSnapshot(Base):
    __tablename__ = "keyword_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_versions.id", ondelete="CASCADE"), index=True
    )
    strategy_version: Mapped[str] = mapped_column(String(40), default="own-data-v1")
    keywords: Mapped[list] = mapped_column(JSONB)
    evidence: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TitleGenerationRun(Base):
    __tablename__ = "title_generation_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keyword_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("keyword_snapshots.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(50))
    requested_count: Mapped[int] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DraftBatch(Base):
    __tablename__ = "draft_batches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_versions.id", ondelete="RESTRICT"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ml_accounts.id", ondelete="RESTRICT"), index=True
    )
    requested_count: Mapped[int] = mapped_column(Integer)
    commercial_distribution: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    drafts: Mapped[list["PublicationDraft"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class PublicationDraft(Base):
    __tablename__ = "publication_drafts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("draft_batches.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    title_score: Mapped[int] = mapped_column(Integer, default=0)
    commercial_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="GENERATED", index=True)
    image_order: Mapped[list] = mapped_column(JSONB, default=list)
    title_generation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("title_generation_runs.id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    last_error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    batch: Mapped["DraftBatch"] = relationship(back_populates="drafts")
    __table_args__ = (UniqueConstraint("batch_id", "sequence_number", name="uq_draft_sequence"),)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication_drafts.id", ondelete="CASCADE"), index=True
    )
    valid: Mapped[bool] = mapped_column(Boolean)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication_drafts.id", ondelete="RESTRICT"), unique=True, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ml_accounts.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(40))
    item_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    user_product_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    external_response: Mapped[dict] = mapped_column(JSONB, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication_drafts.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(50), default="PUBLICATION")
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    total: Mapped[int] = mapped_column(Integer)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobItem(Base):
    __tablename__ = "job_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publication_drafts.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    __table_args__ = (UniqueConstraint("job_id", "draft_id", name="uq_job_draft"),)


class PricingProfile(Base):
    __tablename__ = "pricing_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), default="Mercado Libre")
    channel: Mapped[str] = mapped_column(String(40), default="MERCADOLIBRE", index=True)
    currency_id: Mapped[str] = mapped_column(String(10), default="ARS")
    target_margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("20"))
    minimum_margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("10"))
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("21"))
    iibb_rate_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    ads_rate_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    refund_rate_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    monthly_units_projection: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rounding_step: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("1"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    components: Mapped[list["PricingCostComponent"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("ix_pricing_profile_default_channel", "channel", "is_default"),
    )


class PricingCostComponent(Base):
    __tablename__ = "pricing_cost_components"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    basis: Mapped[str] = mapped_column(String(50), default="PRODUCT_COST")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    profile: Mapped["PricingProfile"] = relationship(back_populates="components")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
