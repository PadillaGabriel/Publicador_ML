# Iteration 19 — Worker liveness and progress recovery

## Problema observado

Un publication job podía permanecer indefinidamente en `PENDING` y la UI mostraba que el supervisor lo procesaría automáticamente aunque no existiera evidencia de un worker activo. Además, si SSE se cortaba, el frontend informaba el problema pero no activaba el polling de respaldo definido por la arquitectura V1.

## Solución

- Se agregó `worker_heartbeats`, una tabla operativa mínima para liveness del worker de publicación.
- `app.worker` registra una instancia, actualiza su heartbeat durante idle y entre items, y elimina su registro en un cierre limpio.
- `/api/jobs/{job_id}` y SSE exponen `worker.online` y distinguen `WAITING_WORKER` de `WORKER_OFFLINE`.
- Se agregó `GET /api/jobs/worker-status` para diagnóstico explícito.
- La UI ya no afirma que el supervisor está activo sin evidencia. Si el worker está offline, explica que el job permanece durablemente en PostgreSQL y señala el arranque canónico `python -m app.run`.
- Si SSE falla, el frontend cambia automáticamente a polling cada 1.5 segundos hasta que el job alcanza un estado terminal.
- El README elimina la ambigüedad entre el arranque manual del worker y el supervisor local recomendado.

## Persistencia

La migración `0006_worker_heartbeat` crea exclusivamente estado operacional de liveness. No modifica el dominio de publicaciones ni mezcla el ciclo de vida del worker con FastAPI.

## Configuración

`WORKER_HEARTBEAT_STALE_SECONDS=30` controla cuánto tiempo puede pasar sin heartbeat antes de considerar al worker offline.
