# Entrega 2 / Etapa 16 — Atribución de eventos de borradores

## Contrato

- Los endpoints de generación, edición de títulos, validación, aprobación y exclusión resuelven la sesión autenticada y escriben `actor_user_id` en eventos de auditoría nuevos.
- La generación y la aprobación masiva transfieren explícitamente la identidad al servicio; no utilizan variables globales ni contexto de petición implícito.
- La validación de un lote genera un evento resumen con recuentos; la validación individual genera un evento con el resultado. No se registran títulos completos ni contenidos de formularios en estos eventos.
- Los eventos se insertan mediante el mismo `Session` y se confirman conjuntamente con las mutaciones que describen.
- Los registros históricos con actor nulo permanecen sin autor conocido. No hay migración nueva.

## Instalación

Aplicar después de la etapa 15, detener trabajos activos y reemplazar únicamente los archivos contenidos en el ZIP. Reiniciar FastAPI. No requiere compilación del frontend.

## Validación

`python -m pytest tests/test_draft_operator_audit_stage16.py -v`

Comprobar en PostgreSQL, con dos operadores autorizados, que la fila de `audit_events.actor_user_id` corresponda al usuario autenticado y que cada evento se asocie a la misma operación confirmada. Verificar también permisos de acceso cruzado y validación real de imágenes con Mercado Libre.

## Pendiente antes de habilitar el equipo

No da por aprobadas las pruebas end-to-end de la etapa 15 ni los flujos de dos sesiones en PostgreSQL. Debe revisarse la cobertura restante de auditoría (usuarios, cuentas, fichas e importaciones) y la operatividad del worker con sesiones revocadas.
