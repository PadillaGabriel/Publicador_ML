# Iteración 08 — Operational hardening

## Alcance

- Objetivo de títulos cercano al límite contractual sin keyword stuffing.
- Ranking de candidatos antes de seleccionar los drafts.
- Logs sanitizados y estructurados para Keyword Intelligence, OpenAI, generación y worker.
- Selección explícita de drafts aprobados antes de crear un publication job.
- Progreso SSE enriquecido con etapa y borrador actual.
- Modal de actividad durante generación y publicación.
- Exposición resumida de las señales de Keyword Intelligence en revisión.
- Resolución de URLs públicas HTTPS para imágenes live mediante `APP_PUBLIC_BASE_URL` o el origen de `ML_REDIRECT_URI`.
- Checkpoint persistente antes del side effect externo de publicación.

## Seguridad y consistencia

No se registran access tokens, refresh tokens, secretos, prompts completos ni payloads de publicación en logs. El request payload continúa persistido en `PublicationAttempt` para auditoría interna existente.

Un timeout de red sin HTTP sigue clasificándose como `UNKNOWN_EXTERNAL_STATE` y no se reintenta ciegamente.

## Worker

El worker continúa desacoplado de FastAPI y debe ejecutarse mediante:

```powershell
python -m app.worker
```

La UI reporta `WAITING_WORKER` cuando un job fue creado pero ningún worker lo reclamó.

## Publicación selectiva

`POST /api/publication/jobs` acepta opcionalmente `draft_ids`. Cuando se envían, sólo drafts `APPROVED` pertenecientes al batch pueden incorporarse al job. Esto permite pruebas live de una sola publicación sin duplicar batches.
