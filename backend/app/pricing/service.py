from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.time import utcnow
from app.persistence import PricingCostComponent, PricingProfile
from app.pricing.calculator import CostComponentValue, PricingInputs, calculate_pricing
from app.pricing.schemas import PricingProfileUpsert, PricingSimulationRequest


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


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
        "monthly_units_projection": profile.monthly_units_projection,
        "rounding_step": float(profile.rounding_step),
        "is_default": profile.is_default,
        "components": [
            {
                "id": str(component.id),
                "name": component.name,
                "kind": component.kind,
                "value": float(component.value),
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


def simulate(db: Session, payload: PricingSimulationRequest) -> dict:
    profile = get_default_profile(db, payload.channel.strip().upper())
    if profile is None:
        raise ValueError("Configurá primero el perfil de costos y rentabilidad del canal.")

    components = tuple(
        CostComponentValue(component.name, component.kind, _decimal(component.value))
        for component in profile.components
        if component.active
    )
    target = payload.target_margin_pct if payload.target_margin_pct is not None else _decimal(profile.target_margin_pct)
    result = calculate_pricing(PricingInputs(
        product_cost=payload.product_cost,
        additional_unit_costs=tuple((item.name, item.amount) for item in payload.additional_unit_costs),
        components=components,
        monthly_units_projection=profile.monthly_units_projection,
        units_per_order=payload.units_per_order,
        target_margin_pct=target,
        minimum_margin_pct=_decimal(profile.minimum_margin_pct),
        rounding_step=_decimal(profile.rounding_step),
        sale_price=payload.sale_price,
    ))
    result["profile_id"] = str(profile.id)
    result["profile_name"] = profile.name
    result["currency_id"] = profile.currency_id
    result["calculation_version"] = "pricing_v1_contribution"
    return result
