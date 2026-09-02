from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.core.db import get_db
from app.integrations.mercadolibre.client import MercadoLibreClient
from app.pricing.application.calculator import PricingCalculatorService
from app.pricing.domain import PricingDomainError
from app.pricing.infrastructure.mercadolibre import MercadoLibrePricingProvider
from app.pricing.schemas import (
    ExistingListingPricingRequest,
    NewProductPricingRequest,
    PricingCalculatorResponse,
    PricingProfileUpsert,
    PricingSimulationRequest,
)
from app.pricing.service import (
    get_default_profile,
    serialize_profile,
    upsert_default_profile,
)

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


def build_calculator_service(db: Session, account_id: UUID | None) -> PricingCalculatorService:
    profile = get_default_profile(db)
    if profile is None:
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing default pricing profile.")
    if account_id is None:
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing Mercado Libre account.")
    access_token = load_access_token(db, account_id)
    return PricingCalculatorService(
        profile=profile,
        provider=MercadoLibrePricingProvider(MercadoLibreClient(access_token)),
    )


def _calculator_error(exc: PricingDomainError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@router.get("/profile")
def profile(channel: str = Query(default="MERCADOLIBRE"), db: Session = Depends(get_db)):
    current = get_default_profile(db, channel.strip().upper())
    return {
        "configured": current is not None,
        "profile": serialize_profile(current) if current else None,
    }


@router.put("/profile")
def save_profile(payload: PricingProfileUpsert, db: Session = Depends(get_db)):
    return serialize_profile(upsert_default_profile(db, payload))


@router.post("/simulate", response_model=PricingCalculatorResponse)
def pricing_simulation(
    payload: PricingSimulationRequest, db: Session = Depends(get_db)
) -> PricingCalculatorResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_new_product(
            NewProductPricingRequest(
                account_id=payload.account_id,
                category_id=payload.category_id,
                listing_type_id=payload.listing_type_id,
                gross_cmv=payload.product_cost,
                additional_unit_cost_net=sum(
                    (item.amount for item in payload.additional_unit_costs), start=0
                ),
                sale_price=payload.sale_price,
                target_margin_pct=payload.target_margin_pct,
                overrides={
                    "vat_rate_pct": payload.vat_rate_pct,
                    "iibb_rate_pct": payload.iibb_rate_pct,
                    "ads_rate_pct": payload.ads_rate_pct,
                    "refund_rate_pct": payload.refund_rate_pct,
                },
                package=payload.package,
                currency_id=payload.currency_id,
            )
        )
    except PricingDomainError as exc:
        raise _calculator_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)


@router.post("/calculator/new", response_model=PricingCalculatorResponse)
def calculate_new_product(
    payload: NewProductPricingRequest, db: Session = Depends(get_db)
) -> PricingCalculatorResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_new_product(payload)
    except PricingDomainError as exc:
        raise _calculator_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)


@router.post("/calculator/existing", response_model=PricingCalculatorResponse)
def calculate_existing_listing(
    payload: ExistingListingPricingRequest, db: Session = Depends(get_db)
) -> PricingCalculatorResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_existing_listing(payload)
    except PricingDomainError as exc:
        raise _calculator_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)
