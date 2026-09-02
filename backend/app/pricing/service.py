from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.time import utcnow
from app.persistence import PricingCostComponent, PricingProfile
from app.pricing.schemas import PricingProfileUpsert


def get_default_profile(db: Session, channel: str = "MERCADOLIBRE") -> PricingProfile | None:
    return db.scalar(
        select(PricingProfile)
        .where(PricingProfile.channel == channel, PricingProfile.is_default.is_(True))
        .order_by(PricingProfile.updated_at.desc())
        .limit(1)
    )


def serialize_profile(profile: PricingProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "channel": profile.channel,
        "currency_id": profile.currency_id,
        "target_margin_pct": float(profile.target_margin_pct),
        "minimum_margin_pct": float(profile.minimum_margin_pct),
        "vat_rate_pct": float(profile.vat_rate_pct),
        "iibb_rate_pct": float(profile.iibb_rate_pct),
        "ads_rate_pct": float(profile.ads_rate_pct),
        "refund_rate_pct": float(profile.refund_rate_pct),
        "monthly_units_projection": profile.monthly_units_projection,
        "rounding_step": float(profile.rounding_step),
        "is_default": profile.is_default,
        "components": [
            {
                "id": str(component.id),
                "name": component.name,
                "kind": component.kind,
                "value": float(component.value),
                "basis": component.basis,
                "active": component.active,
            }
            for component in sorted(profile.components, key=lambda item: (item.sort_order, item.name))
        ],
        "updated_at": profile.updated_at.isoformat(),
    }


def upsert_default_profile(db: Session, payload: PricingProfileUpsert) -> PricingProfile:
    channel = payload.channel.strip().upper()
    profile = get_default_profile(db, channel)
    if profile is None:
        profile = PricingProfile(channel=channel, is_default=True)
        db.add(profile)
        db.flush()

    profile.name = payload.name.strip()
    profile.currency_id = payload.currency_id.strip().upper()
    profile.target_margin_pct = payload.target_margin_pct
    profile.minimum_margin_pct = payload.minimum_margin_pct
    profile.vat_rate_pct = payload.vat_rate_pct
    profile.iibb_rate_pct = payload.iibb_rate_pct
    profile.ads_rate_pct = payload.ads_rate_pct
    profile.refund_rate_pct = payload.refund_rate_pct
    profile.monthly_units_projection = payload.monthly_units_projection
    profile.rounding_step = payload.rounding_step
    profile.updated_at = utcnow()

    db.execute(delete(PricingCostComponent).where(PricingCostComponent.profile_id == profile.id))
    db.flush()
    for index, component in enumerate(payload.components):
        db.add(PricingCostComponent(
            profile_id=profile.id,
            name=component.name.strip(),
            kind=component.kind,
            value=component.value,
            basis=component.basis,
            active=component.active,
            sort_order=index,
        ))

    audit(db, "PRICING_PROFILE_UPDATED", "PricingProfile", str(profile.id), {
        "channel": channel,
        "component_count": len(payload.components),
        "target_margin_pct": float(payload.target_margin_pct),
        "minimum_margin_pct": float(payload.minimum_margin_pct),
    })
    db.commit()
    db.refresh(profile)
    return profile
