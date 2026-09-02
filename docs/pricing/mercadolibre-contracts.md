# Contratos de Mercado Libre para pricing

Fecha de relevamiento: 2026-09-01.

Las solicitudes de descubrimiento se limitaron a `GET`. Con autorización explícita se usó
la ruta existente `load_access_token()` para una cuenta activa con un ítem MLA publicado;
la renovación OAuth y las escrituras locales asociadas quedaron limitadas a esa operación.
No se creó publicación, borrador ni job. Las fixtures eliminan identificadores internos de
precio, `seller_id`, tokens, datos personales y el identificador real del ítem.

| Recurso | Solicitud comprobada en el transporte | Campos usados o preservados | Campos no disponibles o dudosos |
| --- | --- | --- | --- |
| Listing prices | `GET /sites/MLA/listing_prices?category_id=MLA412517&listing_type_id=gold_special&price=20000&currency_id=ARS&logistic_type=drop_off&shipping_mode=me2` | `currency_id`, `listing_type_id`, `listing_fee_amount`, `listing_fee_details.fixed_fee`, `listing_fee_details.gross_amount`, `sale_fee_amount`, `sale_fee_details.financing_add_on_fee`, `sale_fee_details.fixed_fee`, `sale_fee_details.gross_amount`, `sale_fee_details.meli_percentage_fee`, `sale_fee_details.percentage_fee`, `free_relist`, `listing_exposure`, `requires_picture`, `stop_time`. | Impuestos, costo de envío y cualquier campo ausente del payload capturado. |
| Item detail | `GET /items/{item_id}` mediante `MercadoLibreClient.item(item_id)` | `id` sanitizado, `price`, `currency_id`, `listing_type_id`, y `shipping.mode`, `shipping.methods`, `shipping.tags`, `shipping.dimensions`, `shipping.local_pick_up`, `shipping.free_shipping`, `shipping.logistic_type`, `shipping.store_pick_up`. | Vendedor, atributos, descripciones, imágenes y los restantes nodos no consumidos por pricing. |
| Item prices | `GET /items/{item_id}/prices` con header `show-all-prices: true` en `MercadoLibreClient.item_prices()` existente | `prices.type`, `prices.amount`, `prices.regular_amount`, `prices.currency_id`, `prices.conditions.context_restrictions`, `prices.conditions.start_time`, `prices.conditions.end_time`. | Identificadores internos de precio y `last_updated`, eliminados por no ser necesarios para el parser de costos. |
| Logística prospectiva | No se confirmó un endpoint logístico dedicado. El contexto utilizado se obtuvo del nodo `shipping` de `GET /items/{item_id}`. | Los ocho campos `shipping.*` listados en item detail, reproducidos en `shipping_context.json`. | Cotización de flete, SLA, cobertura y cualquier costo de envío: no inferir ni sustituir por cero. |

## Fixtures

Las respuestas reales sanitizadas están en `backend/tests/fixtures/ml/`. Los valores se
mantienen sólo como contrato de parser; no son valores por defecto ni deben reemplazar una
respuesta ausente del proveedor.
