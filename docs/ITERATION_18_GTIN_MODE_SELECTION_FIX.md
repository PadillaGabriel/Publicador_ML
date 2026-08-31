# Iteration 18 — GTIN mode selection fix

## Problema

La selección visual entre `GTIN` y `NO_GTIN` se derivaba exclusivamente de los valores ya persistidos en `attributes`.
Al seleccionar "No tiene código universal", la app limpiaba `GTIN`, pero todavía no existía un valor de `EMPTY_GTIN_REASON`. Como consecuencia, el modo volvía inmediatamente a vacío y el radio button parecía no responder.

## Corrección

El modo de edición del identificador ahora tiene estado explícito en el frontend (`GTIN`, `NO_GTIN` o vacío), separado del estado de completitud de los datos.

- Elegir `GTIN` conserva la selección y limpia únicamente `EMPTY_GTIN_REASON`.
- Elegir `NO_GTIN` conserva la selección y limpia únicamente `GTIN`.
- El selector del motivo se renderiza inmediatamente al elegir `NO_GTIN`.
- El indicador "Completo" sólo aparece cuando existe un GTIN plausible o un motivo válido; elegir un modo por sí solo no completa el requisito.
- Al cambiar cuenta/categoría el modo se reinicia.
- Al restaurar una versión existente el modo se reconstruye a partir de datos previamente validados.

## Impacto arquitectónico

No se modifica el contrato backend ni el modelo persistente. El cambio corrige exclusivamente el estado de interacción del formulario y mantiene al backend como autoridad de validación.

## Validación

`npx tsc -b` ejecutado correctamente.
