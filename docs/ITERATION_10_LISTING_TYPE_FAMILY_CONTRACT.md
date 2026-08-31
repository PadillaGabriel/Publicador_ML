# Iteración 10 — listing_type_id y family_name

## Evidencia de Discovery

Para SILMAR BAZAR + MLA392279 el endpoint de disponibilidad devolvió `gold_pro / Premium` y `gold_special / Clásica`. Las muestras de publicaciones aceptadas muestran `gold_special` de forma consistente y, en publicaciones con User Product, un `family_name` estable que puede ser igual o más general que el título específico.

El intento de filtrar items del vendedor por `category` no produjo evidencia válida de la categoría exacta: la respuesta repitió items de otras categorías. Por lo tanto ese probe no se usa para inferir reglas de creación.

## Implementación

- `MercadoLibreClient.available_listing_types()` encapsula el GET externo.
- `publication/commercial.py` normaliza opciones y valida la selección.
- El frontend consulta opciones por cuenta + categoría y usa un selector real, no texto libre.
- `gold_special` se preselecciona sólo si aparece en la respuesta de disponibilidad.
- La generación de drafts vuelve a validar que el tipo seleccionado siga disponible.
- Los drafts conservan `listing_type_id` en `commercial_config`.
- El payload incluye `family_name` construido desde `ProductVersion.title_reference`, estable para todas las variantes de título del mismo lote.
- La validación impide publicar sin `listing_type_id` o sin nombre base estable.

## Alcance

No se resuelven todavía cuotas Premium/3/6/9/12. Esas intenciones siguen bloqueadas hasta mapearlas contra condiciones financieras reales de Mercado Libre.

## Migraciones

Ninguna.
