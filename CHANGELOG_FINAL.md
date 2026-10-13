# CHANGELOG FINAL

## Frontend

- Unificadas las etapas `Precios` y `Logística` en `Precio y logística`.
- Eliminada la etapa visual separada de logística.
- Agregado panel de cotizaciones separadas Colecta/ME y Flex.
- Agregado selector multicuenta para generación de lotes.
- Generación secuencial por cuenta con reserva de títulos ya utilizados.
- Revisión consolidada con columna Cuenta.
- Job consolidado multicuenta para borradores seleccionados.
- Agregado gestor de imágenes con miniaturas, principal, mover y eliminar.
- Ajustado orden/numeración del wizard.

## Backend

- `pricing/logistics-quotes`: cotiza por separado logística base y Flex usando respuestas reales de ML.
- `ProductImage.position` se usa como orden editorial autoritativo para todos los borradores.
- Nuevos endpoints de reordenamiento y eliminación de imágenes con lease y auditoría.
- `GenerateRequest.reserved_titles` evita reutilización de títulos reservados en la misma operación multicuenta.
- Nuevo `POST /api/publication/jobs/multi` para un job con drafts de distintos batches/cuentas.
- Account scope de Operador ampliado de forma explícita para las nuevas rutas.
- Sincronización B2B ahora relee `item_prices` y verifica exactamente cantidades/porcentajes antes de éxito.
- Estado B2B exitoso normalizado a `PUBLISHED`, con `verified`, versión verificada y timestamp.

## Base de datos

- No se agregaron tablas ni columnas.
- No se creó nueva migración; el head continúa en `0013_operator_login_throttle`.

## Tests

- Suite backend final: 351 PASS.
- Test de orden de imágenes actualizado al nuevo contrato de orden persistido.
- Test B2B actualizado para exigir verificación posterior a la escritura.
