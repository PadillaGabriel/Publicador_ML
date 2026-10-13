# Entrega 2 / Etapa 15 — imágenes privadas en validación previa

## Contrato

- `/uploads/{image_id}` conserva autenticación y controles de propiedad; **no** se vuelve público.
- `POST /api/drafts/batches/{batch_id}/validate` y `POST /api/drafts/{draft_id}/validate` ya no entregan URLs de ese endpoint a Mercado Libre.
- La validación local precede a la subida. Solo cuando existen borradores localmente válidos se suben las imágenes referenciadas directamente a `/pictures/items/upload` de Mercado Libre.
- Cada imagen distinta se sube una sola vez por llamada de validación de lote (máximo cuatro solicitudes de imagen en paralelo). Cada borrador conserva el orden propio de imágenes y el payload usa `{"id": picture_id}`.
- Si el lote referencia una imagen que no pertenece a la versión actual, se responde 422. Los errores del proveedor siguen atravesando el tratamiento existente del router.
- **No hay almacenamiento persistente de los IDs de prevalidación**: cada nueva invocación vuelve a subir las imágenes. La publicación final conserva su mecanismo independiente de subida y caché por job.

## Instalación

Aplicar el ZIP sobre todos los incrementos anteriores hasta Etapa 14; respaldar archivos reemplazados, finalizar jobs y reiniciar FastAPI. Sin migraciones y sin cambios en React.

## Verificación

`python -m pytest tests/test_preflight_private_pictures_stage15.py -v`
`python -m pytest tests/test_validation_performance.py -v`

La segunda prueba requiere dependencias completas del backend. Probar además validación real en una cuenta autorizada: confirmar que la API de Mercado Libre acepta picture IDs para `/items/validate`; verificar persistencia de los resultados y publicar un borrador aprobado con imágenes. Si el proveedor rechaza picture IDs en preflight, **no volver a abrir `/uploads/`**: reevaluar el contrato del proveedor y agregar una alternativa segura.

## Limitaciones

Probadas localmente las funciones de subida/orden con cliente simulado, sin integración a PostgreSQL ni Mercado Libre. No se ha medido el efecto de subidas por cada intento de validación sobre latencia y consumo de red. No declarar Entrega 2 cerrada ni habilitar usuarios generales antes de la prueba end-to-end y de dos sesiones.
