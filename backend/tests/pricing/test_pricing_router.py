from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pricing.application.calculator import (
    PricingAudit,
    PricingCalculationResponse,
    PricingCalculatorService,
)
from app.pricing.application.optimizer import PriceTargetResult
from app.pricing.domain import PricingDomainError
from app.pricing.domain.models import EconomicResult
from app.pricing.router import router


class PublicationSpy:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, *args, **kwargs) -> None:
        self.calls += 1


class CalculatorServiceStub:
    def __init__(self) -> None:
        self.requests = []

    def calculate_new_product(self, request):
        self.requests.append(request)
        result = EconomicResult(
            gross_price=Decimal("24200"), net_price=Decimal("20000"), vat_debit=Decimal("4200"),
            gross_cmv=Decimal("12100"), net_cmv=Decimal("10000"), cmv_vat_credit=Decimal("2100"),
            taxable_revenue=Decimal("20000"), percentage_fee=Decimal("16"),
            meli_percentage_fee=Decimal("16"), financing_add_on_fee=Decimal("0"),
            ml_commission_net=Decimal("3200"), financing_net=Decimal("0"), fixed_fee=Decimal("0"),
            ml_fixed_fee_net=Decimal("0"), shipping_cost=Decimal("0"),
            shipping_subsidy=Decimal("0"),
            buyer_shipping_amount=Decimal("0"), net_logistic_cost=Decimal("0"), iibb=Decimal("600"),
            ads_expected=Decimal("1000"), refunds_expected=Decimal("200"),
            additional_unit_cost_net=Decimal("0"), contribution_margin=Decimal("5000"),
            contribution_margin_pct=Decimal("25"),
        )
        target = PriceTargetResult(
            target_margin_pct=Decimal("20"), gross_price=Decimal("24200"),
            achieved_margin_pct=Decimal("25"), probes=1,
        )
        return PricingCalculationResponse(
            scenario="NEW_PRODUCT", scenario_units=1, analyzed=result, mc0=target, mc15=target,
            mc20=target, minimum=target, target=target, custom=None, recommended_price=Decimal("24200"),
            breakdowns={
                "mc0": result, "mc15": result, "mc20": result, "minimum": result,
                "target": result, "recommended": result,
            },
            audit=PricingAudit(
                parameter_sources={"vat_rate_pct": "GLOBAL_PROFILE"}, overrides={},
                marketplace_context={"category_id": "MLA412517"}, analyzed_price=Decimal("24200"),
                scenario_units=1, target_margin_pct=Decimal("20"),
                target_margin_source="GLOBAL_PROFILE", minimum_margin_pct=Decimal("10"),
                recommended_target_margin_pct=Decimal("20"), rounding_step=Decimal("1"),
            ),
        )


def test_new_calculator_endpoint_returns_calculation_without_publication_side_effects(monkeypatch):
    """Catches a calculator request being wired to a publication workflow."""
    from app.pricing import router as pricing_router

    publication = PublicationSpy()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[pricing_router.get_db] = lambda: object()
    monkeypatch.setattr(
        pricing_router,
        "build_calculator_service",
        lambda db, account_id: CalculatorServiceStub(),
    )
    monkeypatch.setattr(pricing_router, "publication", publication, raising=False)

    response = TestClient(app).post(
        "/api/pricing/calculator/new",
        json={
            "account_id": str(uuid4()),
            "category_id": "MLA412517",
            "listing_type_id": "gold_special",
            "gross_cmv": "12100", "package": {
                "dimensions": "10x10x10,450", "weight": "0.45",
                "logistic_type": "cross_docking", "shipping_mode": "me2", "free_shipping": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["scenario"] == "NEW_PRODUCT"
    assert response.json()["minimum"]["gross_price"] == "24200"
    assert response.json()["target"]["gross_price"] == "24200"
    assert response.json()["recommended_price"] == "24200"
    assert response.json()["breakdowns"]["mc20"]["gross_price"] == "24200"
    assert response.json()["breakdowns"]["recommended"]["contribution_margin"] == "5000"
    assert publication.calls == 0


def test_calculator_domain_errors_are_returned_as_stable_422_details(monkeypatch):
    """Catches missing CMV leaking an unstructured 500 or HTTP detail string."""
    from app.pricing import router as pricing_router

    class MissingCmvService:
        def calculate_new_product(self, request):
            raise PricingDomainError("SIN_CMV", "Missing gross CMV.")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[pricing_router.get_db] = lambda: object()
    monkeypatch.setattr(
        pricing_router,
        "build_calculator_service",
        lambda db, account_id: MissingCmvService(),
    )

    response = TestClient(app).post(
        "/api/pricing/calculator/new",
        json={
            "account_id": str(uuid4()),
            "category_id": "MLA412517",
            "listing_type_id": "gold_special",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SIN_CMV"


def test_legacy_simulation_endpoint_uses_the_pricing_calculator_service(monkeypatch):
    """Catches the publisher compatibility endpoint keeping a second economic engine."""
    from app.pricing import router as pricing_router

    service = CalculatorServiceStub()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[pricing_router.get_db] = lambda: object()
    monkeypatch.setattr(pricing_router, "build_calculator_service", lambda db, account_id: service)

    response = TestClient(app).post(
        "/api/pricing/simulate",
        json={
            "account_id": str(uuid4()),
            "category_id": "MLA412517",
            "listing_type_id": "gold_special",
            "product_cost": "12100",
            "sale_price": "18000",
            "additional_unit_costs": [{"name": "Packing", "amount": "300"}],
            "package": {
                "dimensions": "10x10x10", "weight": "0.45",
                "logistic_type": "cross_docking", "shipping_mode": "me2", "free_shipping": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["recommended_price"] == "24200"
    assert service.requests[0].gross_cmv == Decimal("12100")
    assert service.requests[0].additional_unit_cost_net == Decimal("300")
    assert service.requests[0].sale_price == Decimal("18000")


def test_quantity_tiers_endpoint_uses_pricing_service_without_publication_side_effects(monkeypatch):
    """Catches B2B tier economics being implemented as a publication-side formula."""
    from app.pricing import router as pricing_router

    class QuantityTierServiceStub(CalculatorServiceStub):
        def calculate_quantity_tiers(self, request, tiers):
            self.requests.append((request, tiers))
            base = self.calculate_new_product(request)
            from app.pricing.application.calculator import QuantityPricingResponse, QuantityTierAnalysis
            return QuantityPricingResponse(
                minimum=base.minimum,
                target=base.target,
                retail_price=request.sale_price or base.target.gross_price,
                tiers=tuple(
                    QuantityTierAnalysis(
                        min_purchase_unit=tier.min_purchase_unit,
                        amount=base.minimum.gross_price,
                        analyzed=base.analyzed,
                        status="OPTIMO",
                        minimum_price=base.minimum.gross_price,
                        retail_price=request.sale_price or base.target.gross_price,
                        discount_pct=Decimal("12"),
                    )
                    for tier in tiers
                ),
            )

    service = QuantityTierServiceStub()
    publication = PublicationSpy()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[pricing_router.get_db] = lambda: object()
    monkeypatch.setattr(pricing_router, "build_calculator_service", lambda db, account_id: service)
    monkeypatch.setattr(pricing_router, "publication", publication, raising=False)

    response = TestClient(app).post(
        "/api/pricing/quantity-tiers",
        json={
            "account_id": str(uuid4()),
            "category_id": "MLA412517",
            "listing_type_id": "gold_special",
            "product_cost": "12100",
            "sale_price": "25000",
            "package": {
                "dimensions": "10x10x10", "weight": "0.45",
                "logistic_type": "cross_docking", "shipping_mode": "me2", "free_shipping": False,
            },
            "tiers": [
                {"min_purchase_unit": 3},
                {"min_purchase_unit": 6},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["tiers"][0]["min_purchase_unit"] == 3
    assert response.json()["tiers"][0]["status"] == "OPTIMO"
    assert response.json()["retail_price"] == "25000"
    assert publication.calls == 0


def test_build_calculator_service_reuses_process_pricing_cache(monkeypatch):
    """Catches constructing production pricing providers without the shared TTL/LRU cache."""
    from types import SimpleNamespace

    from app.pricing import router as pricing_router

    account_id = uuid4()
    profile = SimpleNamespace()
    captured = {}

    class FakeDb:
        def get(self, model, key):
            assert key == account_id
            return SimpleNamespace(active=True, seller_id="244878077")

    class FakeClient:
        def __init__(self, access_token):
            captured["token"] = access_token

    class FakeProvider:
        def __init__(self, client, *, seller_id=None, cache=None):
            captured["client"] = client
            captured["seller_id"] = seller_id
            captured["cache"] = cache

    monkeypatch.setattr(pricing_router, "get_default_profile", lambda db: profile)
    monkeypatch.setattr(pricing_router, "load_access_token", lambda db, key: "token")
    monkeypatch.setattr(pricing_router, "MercadoLibreClient", FakeClient)
    monkeypatch.setattr(pricing_router, "MercadoLibrePricingProvider", FakeProvider)

    service = pricing_router.build_calculator_service(FakeDb(), account_id)

    assert isinstance(service, PricingCalculatorService)
    assert captured["seller_id"] == "244878077"
    assert captured["cache"] is pricing_router._pricing_simulation_cache
