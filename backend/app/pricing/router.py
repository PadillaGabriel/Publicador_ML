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
    simulate,
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


@router.post("/simulate")
def pricing_simulation(payload: PricingSimulationRequest, db: Session = Depends(get_db)):
    try:
        return simulate(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
