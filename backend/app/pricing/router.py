import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.core.db import get_db
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import MercadoLibreAccount
from app.pricing.application.calculator import PricingCalculatorService
from app.pricing.domain import PricingDomainError
from app.pricing.infrastructure.cache import PricingSimulationCache
from app.pricing.infrastructure.mercadolibre import MercadoLibrePricingProvider
from app.pricing.schemas import (
    ExistingListingPricingRequest,
    NewProductPricingRequest,
    PricingCalculatorResponse,
    PricingProfileUpsert,
    PricingSimulationRequest,
    QuantityPricingResponse,
    QuantityPricingSimulationRequest,
)
from app.pricing.service import (
    get_default_profile,
    serialize_profile,
    upsert_default_profile,
)

logger = logging.getLogger("pricing")
router = APIRouter(prefix="/api/pricing", tags=["pricing"])
_pricing_simulation_cache = PricingSimulationCache()


def build_calculator_service(db: Session, account_id: UUID | None) -> PricingCalculatorService:
    profile = get_default_profile(db)
    if profile is None:
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing default pricing profile.")
    if account_id is None:
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing Mercado Libre account.")
    account = db.get(MercadoLibreAccount, account_id)
    if account is None or not account.active or not account.seller_id:
        raise PricingDomainError(
            "SIN_CONTEXTO_LOGISTICO",
            "Missing Mercado Libre seller context for pricing.",
        )
    access_token = load_access_token(db, account_id)
    return PricingCalculatorService(
        profile=profile,
        provider=MercadoLibrePricingProvider(
            MercadoLibreClient(access_token),
            seller_id=account.seller_id,
            cache=_pricing_simulation_cache,
        ),
    )


def _calculator_error(exc: PricingDomainError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


def _marketplace_error(exc: MercadoLibreError) -> HTTPException:
    status_code = 503 if exc.retryable else 502
    message = (
        "Mercado Libre no está disponible temporalmente. Volvé a intentar en unos instantes."
        if exc.retryable
        else "Mercado Libre rechazó la consulta de pricing. Revisá el contexto informado."
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": "MERCADOLIBRE_PRICING_UNAVAILABLE", "message": message},
    )


def _log_pricing_rejection(endpoint: str, payload: object, exc: PricingDomainError) -> None:
    package = getattr(payload, "package", None)
    logger.warning(
        "pricing_request_rejected endpoint=%s code=%s category=%s listing_type=%s "
        "dimensions_present=%s weight_present=%s logistic_type=%s shipping_mode=%s "
        "free_shipping=%s",
        endpoint,
        exc.code,
        getattr(payload, "category_id", None),
        getattr(payload, "listing_type_id", None),
        bool(getattr(package, "dimensions", None)),
        getattr(package, "weight", None) is not None,
        getattr(package, "logistic_type", None),
        getattr(package, "shipping_mode", None),
        getattr(package, "free_shipping", None),
    )


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
                condition=payload.condition,
                currency_id=payload.currency_id,
            )
        )
    except PricingDomainError as exc:
        _log_pricing_rejection("simulate", payload, exc)
        raise _calculator_error(exc) from exc
    except MercadoLibreError as exc:
        raise _marketplace_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)


@router.post("/calculator/new", response_model=PricingCalculatorResponse)
def calculate_new_product(
    payload: NewProductPricingRequest, db: Session = Depends(get_db)
) -> PricingCalculatorResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_new_product(payload)
    except PricingDomainError as exc:
        _log_pricing_rejection("calculator/new", payload, exc)
        raise _calculator_error(exc) from exc
    except MercadoLibreError as exc:
        raise _marketplace_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)


@router.post("/calculator/existing", response_model=PricingCalculatorResponse)
def calculate_existing_listing(
    payload: ExistingListingPricingRequest, db: Session = Depends(get_db)
) -> PricingCalculatorResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_existing_listing(payload)
    except PricingDomainError as exc:
        _log_pricing_rejection("calculator/existing", payload, exc)
        raise _calculator_error(exc) from exc
    except MercadoLibreError as exc:
        raise _marketplace_error(exc) from exc
    return PricingCalculatorResponse.model_validate(calculation)


@router.post("/quantity-tiers", response_model=QuantityPricingResponse)
def calculate_quantity_tiers(
    payload: QuantityPricingSimulationRequest, db: Session = Depends(get_db)
) -> QuantityPricingResponse:
    try:
        service = build_calculator_service(db, payload.account_id)
        calculation = service.calculate_quantity_tiers(
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
                condition=payload.condition,
                currency_id=payload.currency_id,
            ),
            payload.tiers,
        )
    except PricingDomainError as exc:
        _log_pricing_rejection("quantity-tiers", payload, exc)
        raise _calculator_error(exc) from exc
    except MercadoLibreError as exc:
        raise _marketplace_error(exc) from exc
    return QuantityPricingResponse.model_validate(calculation)
