# Iteración 04 — categorización guiada, logs seguros y errores OpenAI

## Objetivo

Corregir el flujo operativo para que la categoría no se elija desde categorías padre. La información básica del producto alimenta el predictor oficial de Mercado Libre y el operador confirma una categoría final antes de cargar metadata y ficha técnica.

## Cambios

- Nuevo endpoint `GET /api/catalog/category-suggestions` sobre `sites/{site_id}/domain_discovery/search`.
- El frontend solicita primero cuenta + información básica del producto y recién después muestra categorías sugeridas.
- `GET /api/catalog/categories/{category_id}` exige `account_id`, usa el token de la cuenta y rechaza categorías no hoja/no publicables según metadata recibida.
- La ficha técnica deja de presentar el inventario completo de atributos opcionales. En la etapa manual se muestran los atributos obligatorios de la categoría final; atributos `hidden/read_only` no se fuerzan al operador.
- La lógica de carga/refresh de tokens salió de `accounts/router.py` y quedó en `accounts/service.py`.
- Los access logs de Uvicorn permanecen habilitados, pero `code`, `state`, `access_token`, `refresh_token` y `client_secret` se redactan en query strings.
- Los errores de OpenAI se clasifican. Saldo agotado se devuelve como `AI_PROVIDER_QUOTA_EXHAUSTED`, no retryable, sin traceback funcional hacia el frontend.

## Validación

- `python -m compileall backend/app`: OK.
- `pytest -q`: 14 tests OK.
- `tsc -b`: OK.
- `vite build`: no ejecutable en este entorno por la dependencia binaria opcional de Rollup/Linux ausente en el `node_modules` recibido; TypeScript sí compila.

## Nota contractual

La sugerencia usa el mecanismo de categorización documentado por Mercado Libre (`/sites/{site_id}/domain_discovery/search`). Mercado Libre continúa siendo la fuente de verdad; no interviene OpenAI en categorización.
