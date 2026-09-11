from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol


class PricingCostComponentSource(Protocol):
    name: str
    kind: str
    value: Decimal
    basis: str
    active: bool


class PricingProfileSource(Protocol):
    target_margin_pct: Decimal
    minimum_margin_pct: Decimal
    rounding_step: Decimal
    monthly_units_projection: int | None
    vat_rate_pct: Decimal
    iibb_rate_pct: Decimal
    ads_rate_pct: Decimal
    refund_rate_pct: Decimal
    components: Iterable[PricingCostComponentSource]


@dataclass(frozen=True, slots=True)
class EffectiveCostComponent:
    name: str
    kind: str
    value: Decimal
    basis: str


@dataclass(frozen=True, slots=True)
class EffectiveEconomicParameters:
    vat_rate_pct: Decimal
    iibb_rate_pct: Decimal
    ads_rate_pct: Decimal
    refund_rate_pct: Decimal
    sources: Mapping[str, str]
    components: tuple[EffectiveCostComponent, ...]


def resolve_effective_economic_parameters(
    profile: PricingProfileSource,
    overrides: Mapping[str, Decimal | None],
) -> EffectiveEconomicParameters:
    fields = (
        "vat_rate_pct",
        "iibb_rate_pct",
        "ads_rate_pct",
        "refund_rate_pct",
    )
    unknown = set(overrides).difference(fields)
    if unknown:
        raise ValueError(f"Unsupported economic overrides: {', '.join(sorted(unknown))}")

    values: dict[str, Decimal] = {}
    sources: dict[str, str] = {}
    for field in fields:
        override = overrides.get(field)
        if override is None:
            values[field] = getattr(profile, field)
            sources[field] = "GLOBAL_PROFILE"
        else:
            values[field] = override
            sources[field] = "SIMULATION_OVERRIDE"

    components = tuple(
        EffectiveCostComponent(
            name=component.name,
            kind=component.kind,
            value=component.value,
            basis=component.basis,
        )
        for component in profile.components
        if component.active
    )
    return EffectiveEconomicParameters(
        sources=MappingProxyType(sources),
        components=components,
        **values,
    )
