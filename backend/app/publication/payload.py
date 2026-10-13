from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.integrations.mercadolibre.product_identifiers import is_product_identifier, normalized_identifier_value
from app.publication.shipping import publication_shipping_payload

if TYPE_CHECKING:
    from app.persistence import ProductVersion, PublicationDraft
else:
    ProductVersion = Any
    PublicationDraft = Any


NAMING_CONTRACT_FAMILY_NAME_FROM_TITLE_INTENT = "FAMILY_NAME_FROM_TITLE_INTENT"


def attribute_payload(attributes: dict) -> list[dict]:
    result = []
    for attr_id, value in attributes.items():
        if is_product_identifier(attr_id):
            value = normalized_identifier_value(value)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            item = {"id": attr_id}
            if value.get("value_id"):
                item["value_id"] = value["value_id"]
            if value.get("value_name"):
                item["value_name"] = value["value_name"]
            elif value.get("name"):
                item["value_name"] = value["name"]
            value_struct = value.get("value_struct") or value.get("struct")
            if isinstance(value_struct, dict) and value_struct:
                item["value_struct"] = value_struct
                number = value_struct.get("number")
                unit = str(value_struct.get("unit") or "").strip()
                if number is not None and unit:
                    item["value_name"] = f"{number} {unit}"
            result.append(item)
        else:
            result.append({"id": attr_id, "value_name": str(value)})
    return result


def ordered_image_urls(
    version: ProductVersion,
    draft: PublicationDraft,
    resolve_image_url: Callable[[str], str],
) -> list[str]:
    """Resolve draft image order to public URLs used by ML create/preflight payloads."""

    images = {str(image.id): image for image in version.images}
    return [
        resolve_image_url(str(image.id))
        for image_id in draft.image_order
        if (image := images.get(str(image_id))) is not None
    ]


def publication_title_intent(draft: PublicationDraft) -> str:
    """Return the independent title chosen for this publication draft.

    This remains our domain-level value regardless of how Mercado Libre currently
    requires the create request to encode the product/publication name.
    """
    return " ".join((draft.title or "").split()).strip()


def family_name_for_draft(version: ProductVersion, draft: PublicationDraft) -> str:
    """Translate the independent title intent to the current ML create contract.

    Live evidence for this seller/category showed that POST /items requires
    ``family_name`` and rejects ``title`` in the same call. The official bulk-upload
    UX still treats Title as a per-publication input, so the application keeps title
    as the business concept and isolates this translation here instead of making
    family_name part of ProductMaster/ProductVersion.

    The returned ML item title is persisted/compared after creation so this adapter
    can be revised if Mercado Libre changes the contract.
    """
    title_intent = publication_title_intent(draft)
    if title_intent:
        return title_intent
    return " ".join((version.title_reference or "").split()).strip()


def family_name_for_version(version: ProductVersion) -> str:
    """Diagnostic helper for the stable descriptive product reference."""
    return " ".join((version.title_reference or "").split()).strip()


def build_item_payload(
    version: ProductVersion,
    draft: PublicationDraft,
    pictures: list[str | dict],
    *,
    seller_sku: str,
) -> dict:
    normalized_sku = seller_sku.strip()
    if not normalized_sku:
        raise ValueError("seller_sku is required to build a Mercado Libre item payload.")

    normalized_attributes = dict(getattr(version, "attributes", None) or {})
    normalized_attributes["SELLER_SKU"] = normalized_sku

    picture_payload: list[dict] = []
    for picture in pictures:
        if isinstance(picture, str):
            source = picture.strip()
            if source:
                picture_payload.append({"source": source})
            continue
        if not isinstance(picture, dict):
            raise ValueError("pictures must contain Mercado Libre picture ids or source URLs.")
        picture_id = str(picture.get("id") or "").strip()
        source = str(picture.get("source") or "").strip()
        if picture_id:
            picture_payload.append({"id": picture_id})
        elif source:
            picture_payload.append({"source": source})
        else:
            raise ValueError("Each picture requires either id or source.")

    payload: dict = {
        # Deliberately omit ``title``: the live create contract rejected it when
        # family_name was required. The independent title remains on PublicationDraft.
        "family_name": family_name_for_draft(version, draft),
        "category_id": version.category_id,
        "price": float(version.price),
        "currency_id": version.currency_id,
        "available_quantity": version.quantity,
        "buying_mode": version.commercial.get("buying_mode", "buy_it_now"),
        "condition": version.condition,
        "seller_custom_field": normalized_sku,
        "attributes": attribute_payload(normalized_attributes),
        "pictures": picture_payload,
    }
    resolved_listing_type = (draft.commercial_config or {}).get("listing_type_id")
    if resolved_listing_type:
        payload["listing_type_id"] = resolved_listing_type

    logistics = getattr(version, "logistics", None) or {}
    shipping = publication_shipping_payload(logistics)
    if shipping is not None:
        payload["shipping"] = shipping

    warranty = (getattr(version, "commercial", None) or {}).get("warranty") or {}
    warranty_type = str(warranty.get("type") or "").strip().upper()
    if warranty_type == "SELLER":
        duration = int(warranty.get("duration") or 0)
        unit = str(warranty.get("unit") or "days").strip().lower()
        unit_label = {"days": "días", "months": "meses", "years": "años"}.get(unit, unit)
        payload["sale_terms"] = [
            {"id": "WARRANTY_TYPE", "value_name": "Garantía del vendedor"},
            {"id": "WARRANTY_TIME", "value_name": f"{duration} {unit_label}"},
        ]
    elif warranty_type == "NONE":
        payload["sale_terms"] = [
            {"id": "WARRANTY_TYPE", "value_name": "Sin garantía"},
        ]
    return payload
