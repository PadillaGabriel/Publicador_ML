# Iteración 09 — Diagnóstico live y validación comercial temprana

## Objetivo

Cerrar dos fallas observadas durante la primera prueba live: los errores HTTP 400 de Mercado Libre no exponían su causa operativa y los borradores con cuotas no resueltas podían llegar a APPROVED/job para fallar recién en el worker.

## Cambios

- Normalización y sanitizado de errores de Mercado Libre, conservando `message`, `error`, `cause` y campos útiles sin registrar credenciales.
- Logs del worker con resumen del rechazo y una línea por cada causa devuelta por Mercado Libre.
- Persistencia del error estructurado en `JobItem.last_error` y `PublicationDraft.last_error`.
- El endpoint de jobs expone fallas individuales para que el frontend muestre el motivo real después de terminar el job.
- Configuraciones de cuotas `> 1` sin `financing_resolution=RESOLVED` pasan a ser error de validación, no warning.
- La creación de un publication job revalida los drafts seleccionados para impedir que drafts APPROVED antiguos o desactualizados entren a la cola si ya no son publicables.
- La pantalla de ejecución muestra HTTP, mensaje de Mercado Libre y causas por draft.

## Resultado esperado

Una publicación estándar rechazada por Mercado Libre debe dejar evidencia equivalente a:

```text
publication_request_failed ... http_status=400 api_error=... api_message=... cause_count=N
publication_rejection_cause ... code=... field=... message=...
```

Y el operador debe ver el mismo diagnóstico sanitizado en la sección de ejecución.

No se modificó el esquema PostgreSQL.
