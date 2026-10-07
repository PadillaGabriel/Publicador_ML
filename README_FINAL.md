# Publicador ML Enterprise — entrega consolidada

## Estado de esta entrega

Esta versión consolida los cambios funcionales solicitados sobre el ZIP base `Publicador_ML-master (1).zip`. Es una evolución brownfield del modular monolith existente; no introduce un sistema paralelo.

**Clasificación actual:** `READY FOR ENVIRONMENT QA` con una salvedad: el build oficial del frontend debe ejecutarse en un entorno con acceso al registro npm. En el entorno de generación no fue posible completar `npm ci`; por lo tanto el build oficial no se marca como PASS.

## Arquitectura

```text
React + TypeScript + Vite
          ↓
       FastAPI
          ↓
 SQLAlchemy / PostgreSQL
          ↓
        Worker
          ↓
 Mercado Libre API
```

Principios preservados:
- backend como autoridad de permisos y alcance de cuenta;
- PostgreSQL como fuente transaccional;
- Alembic para evolución de esquema;
- jobs persistidos para publicación asíncrona;
- leases con fencing token para edición concurrente;
- auditoría de operaciones relevantes;
- fallos explícitos, sin fallbacks silenciosos.

## Cambios funcionales consolidados

### Precio y logística
- El wizard muestra una única etapa **Precio y logística**.
- Dimensiones, peso, modalidad logística, costo de producto, precio y mayoristas conviven en la misma etapa.
- Se incorporó cotización separada de **Flex** y **Mercado Envíos / Colecta**.
- Si Mercado Libre no devuelve una cotización válida se informa `No disponible`; no se infieren costos.
- La modalidad usada para pricing continúa siendo explícita.
- Se preserva el cache TTL/LRU de simulaciones exactas y `solve_many()` para compartir probes entre objetivos de margen; CMV y margen se evalúan localmente sobre los probes económicos disponibles. El cache queda configurable (`pricing_cache_max_entries`, `pricing_cache_ttl_seconds`) y por defecto usa 2048 entradas / 600 s para reducir round-trips en uso multiusuario sin aproximar tarifas.

### Precio clásico, cuotas y overrides
- El precio clásico es la base compartida.
- Incremento de 3 cuotas y de 6 cuotas se configuran por separado.
- Cada incremento se aplica sobre el precio clásico; no se acumulan entre sí.
- Cada borrador admite override manual de precio.
- La validación y el worker resuelven el precio efectivo por borrador antes de publicar.

### Mayoristas B2B
- La sincronización PxQ ya no considera éxito un HTTP 200 por sí solo.
- Después del write se vuelve a consultar Mercado Libre y se verifica cantidad/descuento realmente aplicado.
- Estados persistidos: `NOT_REQUESTED`, `PENDING`, `SYNCING`, `PUBLISHED`, `FAILED`.
- Se registran detalle, timestamp, MLA y cuenta.
- Existe reintento B2B específico sin republicar el MLA.

### Imágenes
- `ProductImage.position` es el orden canónico.
- Se eliminó el shuffle/permutación de imágenes por publicación.
- Se incorporaron reorder y delete server-side con ownership, lease y auditoría.
- La UI identifica la primera imagen como principal, permite mover izquierda/derecha y eliminar.
- El orden persistido es el que reciben los drafts y la publicación.

### Multicuenta
- Una ficha puede seleccionar múltiples cuentas autorizadas.
- Se generan batches independientes por cuenta dentro de una sola operación.
- Los títulos se reservan durante toda la operación multicuenta para evitar duplicados entre cuentas.
- La generación se serializa por ficha durante la reserva para evitar colisiones concurrentes.
- Un único Job puede consolidar drafts de múltiples cuentas.
- El worker mantiene aislamiento por JobItem: el fallo de una cuenta/publicación no revierte las correctas.

### Correcciones de ficha multicuenta
- Una corrección puede rebasar varios batches sobre un único nuevo snapshot de `ProductVersion`.
- Se preservan drafts e imágenes y se resetean validaciones para revalidación.
- Se mantienen controles de lease, versión esperada y ownership.

### Gestor
- Búsqueda por SKU, MLA, User Product ID/variación y título.
- Update individual con flujo `preview → confirmación → write → read-back verification`.
- Update masivo con preview previo de cada publicación y resultados parciales independientes.
- Campos soportados actualmente: precio, stock y estado.
- Se auditan valor anterior, solicitado, resultado y discrepancias.
- No existe blind overwrite: si ML cambió desde el preview devuelve conflicto 409.
- La UI permite selección masiva y actualización individual.
- Se visualiza estado B2B y se ofrece reintento cuando corresponde.

### Seguridad
- El account scope de operadores cubre ahora también Pricing y Catalog.
- Las mutaciones del Gestor requieren permiso de publicación; Supervisor continúa sin permiso para modificar publicaciones.
- Los handlers del Gestor vuelven a resolver la publicación persistida antes de escribir.

## Ejecución local

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Worker

Usar la forma de arranque ya definida por el proyecto para `app.worker`, con el mismo `DATABASE_URL` y configuración de cuentas que la API.

### Frontend

```bash
cd frontend
npm ci
npm run build
```

FastAPI sirve el frontend compilado según la configuración existente.

## ngrok

Un solo origen HTTPS:

```bash
ngrok http 8000
```

Configurar las variables reales del proyecto (`FRONTEND_URL`, `APP_PUBLIC_BASE_URL`, `CORS_ORIGINS`, `ML_REDIRECT_URI`) con el host vigente. No copiar literalmente nombres o valores si el `.env.example` local difiere.

## Pruebas de esta entrega

- Backend pytest: **362 passed**.
- Compilación sintáctica Python: **PASS**.
- Alembic heads: **PASS**, único head `0013_operator_login_throttle`.
- Nueva migración: **no requerida**; los cambios no agregan columnas/tablas.
- Upgrade Alembic sobre SQLite: **no aplicable**, el baseline usa `JSONB` de PostgreSQL.
- PostgreSQL real / `alembic current`: **pendiente del entorno del usuario**.
- Frontend `npm run build`: **no verificado oficialmente** porque este entorno no pudo reconstruir dependencias npm. Se ejecutó un chequeo TypeScript estático de los archivos fuente con stubs temporales y no reportó errores propios del código.

## Seguridad de secretos

El ZIP final excluye `.env`, tokens, dumps, `node_modules`, `.venv`, caches, uploads temporales y artefactos de test.
