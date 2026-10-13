from pathlib import Path

from app.pricing.schemas import PricingProfileUpsert


ROOT = Path(__file__).resolve().parents[2]


def test_pricing_profile_accepts_installment_markups():
    payload = PricingProfileUpsert(
        installment_3_markup_pct="12.5",
        installment_6_markup_pct="20",
    )
    assert str(payload.installment_3_markup_pct) == "12.5"
    assert str(payload.installment_6_markup_pct) == "20"


def test_unified_publisher_pricing_ui_contract():
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    editor = (ROOT / "frontend" / "src" / "pricing" / "PricingProfileEditor.tsx").read_text(encoding="utf-8")

    for text in (
        "Calculá tus costos, compará logística y definí el precio de venta.",
        "Mercado Envíos / Colecta",
        "Calcular precio 3 cuotas",
        "Calcular precio 6 cuotas",
        "MC 25%",
        "MC 35%",
        "Autocompletado desde ficha técnica",
        "Precios mayoristas",
        "Pendiente definir operación exacta en Mercado Libre",
    ):
        assert text in main

    assert "installment_3_markup_pct" in editor
    assert "installment_6_markup_pct" in editor
    assert "publisherPricingUnified" in styles
    assert "publisherPriceSummary" in styles


def test_publication_flex_and_pricing_logistics_are_separate():
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "pricingLogisticType" in main
    assert "pricing_logistic_type" in main
    assert "Flex se ofrece siempre" in main
    assert "capabilities.flex_available" in main


def test_installment_migration_follows_current_head():
    migration = (ROOT / "backend" / "migrations" / "versions" / "0014_pricing_installment_markups.py").read_text(encoding="utf-8")
    assert 'revision = "0014_pricing_installment_markups"' in migration
    assert 'down_revision = "0013_operator_login_throttle"' in migration
    assert '"installment_3_markup_pct"' in migration
    assert '"installment_6_markup_pct"' in migration


def test_installment_profile_contract_is_strict_and_persisted_by_service():
    schema = (ROOT / "backend" / "app" / "pricing" / "schemas.py").read_text(encoding="utf-8")
    service = (ROOT / "backend" / "app" / "pricing" / "service.py").read_text(encoding="utf-8")
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert 'model_config = ConfigDict(extra="forbid")' in schema
    assert "profile.installment_3_markup_pct = payload.installment_3_markup_pct" in service
    assert "profile.installment_6_markup_pct = payload.installment_6_markup_pct" in service
    assert "0014_pricing_installment_markups" in main
    assert "persisted3" in main and "persisted6" in main


def test_shipping_defaults_to_explicit_buyer_paid_policy_for_pricing():
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    calculator = (ROOT / "frontend" / "src" / "pricing" / "PriceCalculator.tsx").read_text(encoding="utf-8")
    assert 'freeShipping: "false"' in main
    assert 'freeShipping: "false"' in calculator
    assert 'free_shipping: simulationPackage.freeShipping === "true"' in main
    assert 'free_shipping: form.freeShipping === "true"' in calculator
    assert 'simulationPackage.freeShipping === ""' not in main


def test_calculator_installment_buttons_recalculate_marketplace_economics():
    calculator = (ROOT / "frontend" / "src" / "pricing" / "PriceCalculator.tsx").read_text(encoding="utf-8")
    assert "async function activateInstallmentVariant" in calculator
    assert "const financedPrice = installmentPrice" in calculator
    assert "salePrice: financedPrice" in calculator
    assert 'setPriceVariant(variant)' in calculator
    assert 'variant !== "base" || scenario === "custom"' in calculator
