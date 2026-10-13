# Publicador ML Enterprise — Entrega consolidada

## Estado de esta compilación

**Candidato técnico consolidado. No está aprobado para producción.**

La base recibida ya incluía React/TypeScript/Vite, FastAPI, PostgreSQL/Alembic, worker Python, autenticación por sesión, roles ADMIN/SUPERVISOR/OPERATOR, grants por cuenta, leases de edición, pricing, preflight privado, auditoría y gestor de solo lectura. Esta entrega modifica esa misma arquitectura; no crea un segundo publicador.

### Cambios consolidados de esta revisión

- Flujo del wizard: `Producto y categoría -> Ficha técnica -> Precio y logística -> Imágenes -> Revisión -> Publicación`.
- Precio y logística comparten el mismo contexto antes del cálculo.
- Cotizaciones separadas para **Mercado Envíos/Colecta** y **Flex**. Si ML no devuelve una cotización válida se muestra `No disponible`; no existe fallback Flex->Colecta.
- El pricing sigue utilizando la modalidad explícitamente seleccionada por el operador.
- Se conserva el cache TTL/LRU exacto de simulaciones de Mercado Libre; no se introdujeron aproximaciones silenciosas.
- Precios B2B: la escritura se vuelve a leer desde ML y se compara con lo solicitado antes de marcarla `PUBLISHED`.
- Gestor visual de imágenes con miniaturas, principal explícita, mover izquierda/derecha, eliminar y persistir posición.
- Todos los borradores usan el orden persistido de imágenes; se eliminó la permutación automática por publicación.
- Multicuenta: selección de cuentas destino, batches independientes por cuenta, reserva de títulos ya usados durante la misma operación y job consolidado para borradores de distintas cuentas.
- Los fallos siguen aislados por `JobItem`; un fallo de una cuenta no revierte publicaciones correctas de otra.

## Arquitectura

```text
React + TypeScript + Vite
          |
        FastAPI
          |
     SQLAlchemy 2
          |
      PostgreSQL
          |
   Worker Python
          |
 Mercado Libre API
```

Módulos relevantes:

- `backend/app/operator_*`: identidad, sesiones, permisos, account scope y login throttle.
- `backend/app/products`: ficha maestra, versiones, imágenes y leases.
- `backend/app/pricing`: dominio económico, optimizador, adapter ML y cache.
- `backend/app/drafts`: generación, títulos, validación y lotes.
- `backend/app/publication`: payload, preflight, shipping, B2B y jobs.
- `backend/app/worker.py`: publicación y sincronizaciones posteriores.
- `backend/app/manager_router.py`: gestor/historial local.
- `frontend/src/main.tsx`: publicador y flujo operativo.
- `frontend/src/PublicationManager.tsx`: gestor/historial.

## Ejecución local

1. Copiar `.env.example` a `.env` fuera del ZIP de distribución y completar credenciales reales.
2. PostgreSQL: crear/restaurar la base correspondiente.
3. Backend:
   ```bash
   cd backend
   pip install -e .[dev]
   alembic upgrade head
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. Worker:
   ```bash
   cd backend
   python -m app.worker
   ```
5. Frontend:
   ```bash
   cd frontend
   npm ci
   npm run build
   ```
6. FastAPI sirve `frontend/dist` cuando el build está disponible.

## ngrok

Usar un único origen HTTPS:

```bash
ngrok http 8000
```

Variables habituales (verificar nombres reales en `.env.example`): `FRONTEND_URL`, `APP_PUBLIC_BASE_URL`, `CORS_ORIGINS`, `ML_REDIRECT_URI`.

## Evidencia obtenida en este entorno

- Backend: `351 passed` con `DATABASE_URL=sqlite+pysqlite:////tmp/ml-qa-current.db`.
- Python `compileall`: PASS.
- Alembic heads: `0013_operator_login_throttle`.
- TSX modificado: análisis sintáctico con TypeScript: PASS.
- `npm ci`: NO COMPLETADO por falta de paquete en cache / acceso al registry dentro del sandbox.
- `npm run build`: NO VALIDADO en instalación limpia por la causa anterior.
- PostgreSQL real / OAuth / publicación real / B2B real / concurrencia: NO EJECUTADOS.

## Capacidades todavía no cerradas

No se marcan como terminadas porque el código base no las tenía completas y esta revisión no las implementa de punta a punta:

- actualización individual de MLA con diff/versionado/confirmación;
- actualización masiva con selección de campos y auditoría before/after;
- override de precio individual por MLA;
- esquema configurable específico de recargos 3/6 cuotas independiente del listing type;
- búsqueda integral por variación y conciliación de publicaciones externas no registradas localmente;
- botón UI dedicado para reintento B2B (existe script backend de reintento, pero no se presenta como flujo UI completo).

Por lo anterior, el estado correcto es **CANDIDATO PARA QA PARCIAL / NO READY FOR PRODUCTION** hasta cerrar los P0/P1 pendientes y ejecutar el QA real.
