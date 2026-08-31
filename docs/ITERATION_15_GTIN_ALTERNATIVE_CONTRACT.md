# Iteration 15 — GTIN alternative contract

## Problema

Mercado Libre rechazó publicaciones de la categoría `MLA392279` cuando `GTIN=0` y,
tras eliminar correctamente ese valor inválido, volvió a rechazarlas porque el GTIN
faltaba. La evidencia del proveedor muestra que, cuando el producto no posee un GTIN
real, el contrato utiliza el atributo `EMPTY_GTIN_REASON` con un valor permitido por la
metadata de la categoría.

## Decisión

La aplicación modela el contrato como una alternativa exclusiva:

- informar un `GTIN` real; o
- informar `EMPTY_GTIN_REASON` utilizando exclusivamente una opción devuelta por
  `/categories/{category_id}/attributes`.

Nunca se inventa un GTIN, nunca se usa `0` como sentinel externo y nunca se hardcodea un
`value_id` de motivo.

## Implementación

- `catalog.normalization` expone un requirement group `GTIN_OR_EMPTY_REASON` cuando la
  metadata contiene ambos atributos.
- El frontend presenta una decisión explícita "Tengo código universal" / "No tiene
  código universal" y luego renderiza el campo oficial correspondiente.
- El motivo de ausencia utiliza los valores de la metadata de Mercado Libre.
- `PrePublicationValidator` exige exactamente una de las dos alternativas, valida el
  formato básico del GTIN y verifica que el motivo pertenezca al conjunto oficial.
- El payload conserva `EMPTY_GTIN_REASON` como atributo estándar de Mercado Libre.

## Invariantes

1. `GTIN=0` nunca llega al proveedor.
2. `GTIN` y `EMPTY_GTIN_REASON` no pueden coexistir.
3. Si ambos atributos existen en la metadata, debe existir exactamente uno antes de
   publicar.
4. El `value_id` de `EMPTY_GTIN_REASON` nunca se hardcodea: proviene del snapshot de
   metadata vigente.
5. La categoría sigue siendo metadata-driven; no existe lógica específica para
   `MLA392279`.
