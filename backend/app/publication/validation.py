from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.catalog.service import get_category_metadata
from app.core.config import get_settings
from app.drafts.intelligence import jaccard, title_target_min_length
from app.integrations.mercadolibre.attribute_contracts import (
    EMPTY_GTIN_REASON_ATTRIBUTE_ID,
    GTIN_ALTERNATIVE_ATTRIBUTE_IDS,
    GTIN_ATTRIBUTE_ID,
)
from app.integrations.mercadolibre.product_identifiers import (
    attribute_has_value,
    is_product_identifier,
    is_valid_identifier_format,
    value_matches_allowed_option,
)
from app.persistence import DraftBatch, ProductVersion, PublicationDraft
from app.products.image_policy import ImagePolicyError, validate_stored_image
from app.publication.commercial import listing_type_for_intent
from app.publication.quantity_pricing import normalize_b2b_quantity_prices


@dataclass(frozen=True, slots=True)
class DraftValidationContext:
    """Batch-scoped validation data shared by every draft in the same product snapshot."""

    batch: DraftBatch
    version: ProductVersion
    metadata: Any
    shared_errors: tuple[dict, ...]
    shared_warnings: tuple[dict, ...]


def build_validation_context(db: Session, batch: DraftBatch) -> DraftValidationContext:
    """Load provider/category state once and validate product-level invariants once."""

    version = db.get(ProductVersion, batch.product_version_id)
    if version is None:
        raise RuntimeError("Product version not found during draft validation.")

    access_token = load_access_token(db, batch.account_id)
    metadata = get_category_metadata(
        db,
        version.category_id,
        get_settings().ml_site_id,
        access_token=access_token,
    )

    errors: list[dict] = []
    warnings: list[dict] = []

    if float(version.price) <= 0:
        errors.append({"code": "INVALID_PRICE", "field": "price", "message": "Price must be > 0."})
    if version.quantity < 0:
        errors.append({"code": "INVALID_QUANTITY", "field": "quantity", "message": "Quantity cannot be negative."})
    if not version.images:
        errors.append({"code": "NO_IMAGES", "field": "images", "message": "At least one image is required."})
    else:
        for image in version.images:
            try:
                validate_stored_image(image.storage_path)
            except (ImagePolicyError, OSError) as exc:
                errors.append({
                    "code": "INVALID_IMAGE",
                    "field": "images",
                    "message": f"{image.original_name}: {exc}",
                })

    if not (version.description or "").strip():
        errors.append({
            "code": "DESCRIPTION_REQUIRED",
            "field": "description",
            "message": "Completá la descripción antes de publicar.",
        })

    attributes = version.attributes or {}
    for attr_id, value in attributes.items():
        if is_product_identifier(attr_id) and not is_valid_identifier_format(value):
            errors.append({
                "code": "INVALID_PRODUCT_IDENTIFIER",
                "field": f"attributes.{attr_id}",
                "message": f"{attr_id} contiene un formato inválido.",
            })

    fields_by_id = {
        field.get("id"): field
        for field in metadata.normalized_schema.get("fields", [])
        if field.get("id")
    }
    for attr_id, field in fields_by_id.items():
        if field.get("value_type") != "number_unit":
            continue
        value = attributes.get(attr_id)
        if not attribute_has_value(value):
            continue
        if not isinstance(value, dict):
            errors.append({
                "code": "MEASUREMENT_UNIT_REQUIRED",
                "field": f"attributes.{attr_id}",
                "message": f"{field.get('label') or attr_id} requiere un valor numérico y una unidad válida.",
            })
            continue
        value_struct = value.get("value_struct") or value.get("struct")
        number = value_struct.get("number") if isinstance(value_struct, dict) else None
        unit = str(value_struct.get("unit") or "").strip() if isinstance(value_struct, dict) else ""
        allowed_units = {
            str(option.get("id") or option.get("name") or "").strip()
            for option in (field.get("allowed_units") or [])
            if option.get("id") or option.get("name")
        }
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not unit:
            errors.append({
                "code": "INVALID_MEASUREMENT_VALUE",
                "field": f"attributes.{attr_id}",
                "message": f"{field.get('label') or attr_id} requiere un número y una unidad.",
            })
        elif allowed_units and unit not in allowed_units:
            errors.append({
                "code": "INVALID_MEASUREMENT_UNIT",
                "field": f"attributes.{attr_id}",
                "message": (
                    f"La unidad '{unit}' no es válida para {field.get('label') or attr_id}. "
                    "Usá una unidad informada por Mercado Libre."
                ),
            })

    has_gtin_alternative_contract = GTIN_ALTERNATIVE_ATTRIBUTE_IDS.issubset(fields_by_id)
    if has_gtin_alternative_contract:
        gtin_present = attribute_has_value(attributes.get(GTIN_ATTRIBUTE_ID))
        empty_reason = attributes.get(EMPTY_GTIN_REASON_ATTRIBUTE_ID)
        empty_reason_present = attribute_has_value(empty_reason)

        if gtin_present and empty_reason_present:
            errors.append({
                "code": "GTIN_AND_EMPTY_REASON_CONFLICT",
                "field": "attributes.GTIN",
                "message": "Informá un GTIN real o un motivo de GTIN vacío, no ambos.",
            })
        elif not gtin_present and not empty_reason_present:
            errors.append({
                "code": "GTIN_OR_EMPTY_REASON_REQUIRED",
                "field": "attributes.GTIN",
                "message": (
                    "Mercado Libre requiere un GTIN real o el motivo oficial por el que "
                    "el producto no tiene GTIN."
                ),
            })
        elif empty_reason_present:
            allowed_reasons = fields_by_id[EMPTY_GTIN_REASON_ATTRIBUTE_ID].get("values") or []
            if not value_matches_allowed_option(empty_reason, allowed_reasons):
                errors.append({
                    "code": "INVALID_EMPTY_GTIN_REASON",
                    "field": f"attributes.{EMPTY_GTIN_REASON_ATTRIBUTE_ID}",
                    "message": "Seleccioná un motivo de GTIN vacío informado por Mercado Libre.",
                })

    warranty = (version.commercial or {}).get("warranty") or {}
    warranty_type = str(warranty.get("type") or "NONE").strip().upper()
    if warranty_type not in {"NONE", "SELLER"}:
        errors.append({
            "code": "INVALID_WARRANTY_TYPE",
            "field": "commercial.warranty.type",
            "message": "La garantía debe ser del vendedor o sin garantía.",
        })
    if warranty_type == "SELLER":
        duration = int(warranty.get("duration") or 0)
        unit = str(warranty.get("unit") or "").strip().lower()
        if duration <= 0 or unit not in {"days", "months", "years"}:
            errors.append({
                "code": "INVALID_SELLER_WARRANTY",
                "field": "commercial.warranty",
                "message": "La garantía del vendedor requiere duración positiva y unidad válida.",
            })

    try:
        normalize_b2b_quantity_prices(version.commercial, base_price=version.price)
    except ValueError as exc:
        errors.append({
            "code": "INVALID_QUANTITY_PRICING",
            "field": "commercial.quantity_prices",
            "message": str(exc),
        })

    required_ids = {
        field["id"]
        for field in metadata.normalized_schema.get("fields", [])
        if (field.get("required") or field.get("catalog_required")) and field.get("id")
    }
    if has_gtin_alternative_contract:
        required_ids -= GTIN_ALTERNATIVE_ATTRIBUTE_IDS
    for attr_id in required_ids:
        if not attribute_has_value(attributes.get(attr_id)):
            errors.append({
                "code": "REQUIRED_ATTRIBUTE_MISSING",
                "field": f"attributes.{attr_id}",
                "message": f"Required category attribute {attr_id} is missing.",
            })

    return DraftValidationContext(
        batch=batch,
        version=version,
        metadata=metadata,
        shared_errors=tuple(errors),
        shared_warnings=tuple(warnings),
    )


def validate_draft_with_context(
    draft: PublicationDraft,
    context: DraftValidationContext,
) -> tuple[list[dict], list[dict]]:
    """Validate one draft using immutable batch-scoped context."""

    errors = [dict(item) for item in context.shared_errors]
    warnings = [dict(item) for item in context.shared_warnings]
    metadata = context.metadata

    category_settings = metadata.raw_category.get("settings") or {}
    max_title = category_settings.get("max_title_length")
    if isinstance(max_title, int) and len(draft.title) > max_title:
        errors.append({
            "code": "TITLE_TOO_LONG",
            "field": "title",
            "message": f"Title exceeds category max length ({max_title}).",
        })
    elif len(draft.title) > 60 and max_title is None:
        warnings.append({
            "code": "TITLE_LENGTH_UNCONFIRMED",
            "field": "title",
            "message": "Category did not expose max_title_length; confirm current ML contract.",
        })

    effective_max = max_title if isinstance(max_title, int) and max_title > 0 else 60
    target_min = title_target_min_length(effective_max)
    if len(draft.title) < target_min:
        warnings.append({
            "code": "TITLE_CAPACITY_UNDERUSED",
            "field": "title",
            "message": (
                f"El título usa {len(draft.title)}/{effective_max} caracteres. "
                f"Si existe información factual útil, conviene acercarse al rango {target_min}-{effective_max}."
            ),
        })

    commercial = draft.commercial_config or {}
    commercial_intent = str(commercial.get("commercial_intent") or "").strip()
    resolved_listing_type = str(commercial.get("listing_type_id") or "").strip()
    if not commercial_intent:
        errors.append({
            "code": "COMMERCIAL_INTENT_NOT_RESOLVED",
            "field": "commercial_intent",
            "message": "Elegí si la publicación agrega cuotas o no agrega cuotas.",
        })
    if not resolved_listing_type:
        errors.append({
            "code": "LISTING_TYPE_NOT_RESOLVED",
            "field": "listing_type_id",
            "message": "El backend no pudo resolver la modalidad de cuotas contra Mercado Libre.",
        })
    elif commercial_intent:
        expected = listing_type_for_intent(commercial_intent, site_id=get_settings().ml_site_id)
        if expected and resolved_listing_type != expected:
            errors.append({
                "code": "COMMERCIAL_CONTRACT_MISMATCH",
                "field": "listing_type_id",
                "message": (
                    f"La intención {commercial_intent} requiere {expected} en MLA, "
                    f"pero el borrador tiene {resolved_listing_type}."
                ),
            })

    if commercial.get("financing_resolution") != "RESOLVED":
        errors.append({
            "code": "FINANCING_PLAN_NOT_RESOLVED",
            "field": "commercial_intent",
            "message": "La modalidad de cuotas todavía no fue resuelta contra el contrato vigente de Mercado Libre.",
        })

    if not " ".join((draft.title or "").split()).strip():
        errors.append({
            "code": "PUBLICATION_NAME_NOT_RESOLVED",
            "field": "title",
            "message": "El borrador necesita un título/intención de nombre antes de publicar.",
        })

    sibling_titles = [
        item.title
        for item in context.batch.drafts
        if item.id != draft.id and item.status != "EXCLUDED"
    ]
    if any(jaccard(draft.title, sibling) > 0.90 for sibling in sibling_titles):
        errors.append({
            "code": "TITLE_TOO_SIMILAR",
            "field": "title",
            "message": "Title is too similar to another draft in the same batch.",
        })

    return errors, warnings


def validate_draft(db: Session, draft: PublicationDraft) -> tuple[list[dict], list[dict]]:
    """Compatibility wrapper for single-draft validation."""

    batch = db.get(DraftBatch, draft.batch_id)
    if batch is None:
        raise RuntimeError("Draft batch not found during draft validation.")
    return validate_draft_with_context(draft, build_validation_context(db, batch))
