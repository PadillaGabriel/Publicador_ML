# Publicador Mercado Libre Enterprise

Aplicación para preparar, revisar y ejecutar lotes de publicaciones independientes en Mercado Libre desde una ficha maestra.

## Stack

- FastAPI + PostgreSQL + SQLAlchemy 2 + Alembic.
- React + TypeScript + Vite.
- Sentence Transformers local para ranking semántico de tendencias + OpenAI Structured Outputs para títulos.
- Worker persistido en PostgreSQL + SSE para progreso.
- Auditoría e idempotencia interna.

## Funcionalidad incluida

- Cuentas Mercado Libre cifradas en base.
- Infraestructura OAuth (authorization code + refresh token) preparada para callback propio.
- Conexión temporal por access token mientras se reutiliza la aplicación ML existente.
- Categorías y atributos dinámicos consultados desde Mercado Libre.
- Ficha técnica enfocada: sólo los atributos obligatorios se muestran para carga manual por defecto; los opcionales quedan disponibles en un bloque desplegable.
- Ficha maestra y versiones.
- Imágenes y orden reproducible por borrador.
- Keyword Intelligence: tendencias oficiales observadas por categoría, caché PostgreSQL, filtro factual y ranking semántico local.
- Generación masiva de títulos y borradores independientes.
- Distribución exacta del lote por intención comercial oficial de MLA: `No agregar cuotas` / `Agregar cuotas`. El backend resuelve automáticamente `gold_special` / `gold_pro` sólo cuando Mercado Libre los informa disponibles para la cuenta/categoría.
- Validación, aprobación y publication jobs.
- Progreso en tiempo real.
- Exportación Excel al finalizar con SKU + MLA y hoja de no publicadas.
- Publicación real deshabilitada por defecto.

## Seguridad

`ML_LIVE_PUBLICATION_ENABLED=false` debe mantenerse durante desarrollo.

Los planes de cuotas se guardan como intención comercial por borrador. Para planes mayores a 1, el worker exige que el plan haya sido resuelto contra la condición comercial real habilitada por Mercado Libre antes de publicar live. Esto evita hardcodear reglas comerciales que pueden variar por cuenta/categoría.

No commitear `.env`. El ZIP distribuible tampoco debe contener `.env`, `.venv` ni `node_modules`.

## Variables nuevas

Además de las variables V1:

```env
FRONTEND_URL=http://localhost:5173
ML_AUTH_BASE_URL=https://auth.mercadolibre.com.ar
ML_CLIENT_ID=
ML_CLIENT_SECRET=
ML_REDIRECT_URI=
ML_KEYWORD_TRENDS_TTL_SECONDS=86400
KEYWORD_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
KEYWORD_MAX_TRENDS=50
KEYWORD_MAX_SELECTED_TERMS=12
KEYWORD_MIN_SEMANTIC_SIMILARITY=0.35
```

`ML_REDIRECT_URI` debe corresponder al callback configurado en la aplicación de Mercado Libre. Mientras la URI apunte a la aplicación de despacho existente, el publicador local puede usar la conexión temporal por access token. El callback definitivo de este backend está disponible en:

```text
/api/accounts/oauth/callback
```

## Actualizar una instalación V1 existente

Desde `backend` con el entorno virtual activo:

```powershell
pip install -e ".[dev]"
alembic upgrade head
```

Las migraciones se aplican secuencialmente. `0004_keyword_trend_snapshots` agrega el caché persistente de tendencias por sitio/categoría.

## Backend local

El modo de desarrollo recomendado ejecuta FastAPI y el worker en Windows y utiliza únicamente PostgreSQL desde Docker. `docker-compose.yml` publica PostgreSQL en `localhost:5432`; la URL local debe apuntar a ese host. Los servicios `api` y `worker` del Compose reemplazan internamente `DATABASE_URL` para utilizar el hostname `postgres`, por lo que el mismo archivo `.env` sirve para ambos modos sin convertir `localhost` en una dependencia dentro de los contenedores.

Desde la raíz del proyecto, iniciar PostgreSQL:

```powershell
docker compose up -d postgres
docker compose ps postgres
```

En `.env`, para la base local provista por este Compose:

```env
DATABASE_URL=postgresql+psycopg://ml:ml@localhost:5432/ml_enterprise
```

Luego, desde `backend`:

```powershell
pip install -e ".[dev]"
alembic current
alembic heads
alembic history
alembic upgrade head
uvicorn app.main:app --reload
```

Para ejecutar todo el stack dentro de Docker en lugar del backend local:

```powershell
docker compose up --build
```

En ese modo no hay que cambiar `DATABASE_URL` manualmente: Compose configura `api` y `worker` para conectarse a `postgres:5432`.

## Frontend local

```powershell
cd frontend
npm install
npm run dev
```

Abrir:

```text
http://localhost:5173
```

## Worker

En otra terminal, desde `backend`:

```powershell
python -m app.worker
```

## Flujo del operador

1. Conectar o seleccionar cuenta Mercado Libre.
2. Elegir categoría.
3. Completar los datos generales y los atributos obligatorios informados por Mercado Libre. Los opcionales se muestran sólo bajo demanda para enriquecer la ficha sin sobrecargar al operador.
4. Guardar la ficha maestra.
5. Cargar imágenes.
6. Elegir cantidad total de publicaciones.
7. Distribuir cuántas publicaciones se solicitan con `Agregar cuotas` y cuántas con `No agregar cuotas`; el backend resuelve el `listing_type_id` real.
8. Generar borradores. En ese momento se recuperan/cachan las tendencias de la categoría, se filtran contra la ficha y se rankean localmente con embeddings antes de llamar a OpenAI.
9. Revisar títulos, plan comercial, imágenes y validaciones.
10. Aprobar.
11. Ejecutar el job de publicación.
12. Al finalizar, descargar el Excel `MLA + SKU`.

## Excel final

Endpoint:

```text
GET /api/publication/jobs/{job_id}/export.xlsx
```

Incluye:

- `Publicaciones`: SKU, MLA, título solicitado, título devuelto por Mercado Libre, modalidad de cuotas, listing type, User Product ID, cuenta, estado y fecha.
- `No publicadas`: SKU, borrador, título, modalidad de cuotas, listing type, cuenta, estado y detalle del error.

## Publicación real

La publicación live continúa protegida por feature flag y por validaciones de imágenes públicas. En MLA la intención `No agregar cuotas` se resuelve a `gold_special` y `Agregar cuotas` a `gold_pro`, siempre condicionada a que Mercado Libre informe ese listing type como disponible para el vendedor/categoría.

## Flujo de categorización actual

El flujo principal ya no comienza navegando categorías padre. El operador selecciona una cuenta, completa información básica del producto y solicita sugerencias mediante el predictor oficial de Mercado Libre. Sólo después de confirmar una categoría final se recupera su metadata y se habilita la ficha técnica dinámica. Los atributos opcionales masivos no se muestran como carga manual primaria.

En desarrollo se recomienda iniciar Uvicorn con access logs normales. La aplicación instala un filtro que redacta parámetros sensibles del callback OAuth (`code`, `state` y tokens) sin ocultar el resto del ciclo de vida HTTP.

## Reutilización por SKU

Un SKU existente no bloquea un nuevo flujo de publicación. El frontend puede recuperar de forma opcional la última ficha guardada y el backend crea una nueva versión inmutable al volver a guardar. La categoría se conserva por `ProductVersion`, no por `ProductMaster`, por lo que un mismo SKU puede utilizar títulos de discovery diferentes y terminar en categorías hoja distintas cuando corresponda. Después de actualizar a esta versión ejecutar `alembic upgrade head` para aplicar `0003_product_reuse_by_sku`.

## Keyword Intelligence

La generación de borradores usa `GET /trends/{site_id}/{category_id}`, endpoint verificado empíricamente con la cuenta conectada para MLA. La respuesta aporta términos de tendencia, no volumen exacto de búsquedas. El sistema no interpreta la posición de la respuesta como cantidad de búsquedas ni inventa métricas de popularidad.

Las tendencias se cachean por `site_id + category_id` con TTL configurable. Cada producto construye su propia evidencia factual desde título, categoría, atributos y contexto de discovery. Un modelo local `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` calcula similitud semántica; luego una compuerta determinista descarta cualquier tendencia con tokens no respaldados por la ficha. Sólo los términos elegibles llegan a OpenAI.

El modelo se descarga/cacha localmente la primera vez que Sentence Transformers lo necesita. No se usa vector DB: para aproximadamente 50 tendencias se calcula similitud en memoria.


## Operación del worker y publicación live

La creación de un job no ejecuta publicaciones dentro del request HTTP. En desarrollo local el arranque canónico es el supervisor, que inicia FastAPI y el worker como procesos separados:

```powershell
cd backend
python -m app.run
```

`python -m app.worker` queda reservado para diagnóstico o para despliegues donde la infraestructura supervise ese rol por separado. La UI consulta un heartbeat persistido en PostgreSQL: `WAITING_WORKER` significa que existe un consumidor activo; `WORKER_OFFLINE` significa que el job está durablemente en cola pero no hay un worker disponible. El progreso usa SSE y cambia automáticamente a polling si el stream se interrumpe.

La publicación live sube cada imagen directamente a Mercado Libre mediante `/pictures/items/upload` y luego crea el ítem con los `picture_id` devueltos. Ya no depende de URLs públicas propias ni de ngrok para la ingestión de imágenes.

`ML_LIVE_PUBLICATION_ENABLED=false` sigue siendo el valor seguro por defecto. La grilla permite seleccionar explícitamente qué drafts `APPROVED` entran al job; no es necesario publicar todo el batch.

## Títulos y Keyword Intelligence

El generador apunta a utilizar aproximadamente el 90-100% del límite contractual del título cuando existe información factual útil, sin agregar relleno ni términos irrelevantes. El ranking prioriza cobertura de tendencias válidas, claridad y uso eficiente de longitud. La revisión expone las señales de Keyword Intelligence utilizadas para generar el lote, sin presentar similitud semántica como volumen de búsquedas.

### Live publication diagnostics

Los rechazos de Mercado Libre se conservan de forma estructurada y sanitizada. El worker registra `http_status`, `api_error`, `api_message` y las causas de validación sin imprimir credenciales; el mismo detalle queda disponible en el estado del job y en la UI.

Los drafts sólo pueden quedar listos cuando `commercial_config.commercial_intent`, `listing_type_id` y `financing_resolution=RESOLVED` son coherentes. La creación del job revalida los drafts seleccionados para evitar encolar aprobaciones antiguas que ya no cumplen las reglas live.

### Resolución contractual de publicación (V1.17)

La condición comercial no se escribe como texto libre. Para cada cuenta/categoría el backend consulta los listing types disponibles y traduce la intención del operador a la semántica oficial de Argentina: `No agregar cuotas` → `gold_special`; `Agregar cuotas` → `gold_pro`. La UI no expone Classic/Premium como concepto de negocio ni inventa 3/6/9/12 cuotas.

Cada `PublicationDraft` conserva un título independiente. El adaptador de creación mantiene `title` como concepto interno y, mientras el contrato live observado exija `family_name` y rechace `title`, traduce ese título de borrador al campo `family_name` únicamente en el borde de integración. El título devuelto por Mercado Libre se persiste en `external_response`, se registra en logs y se exporta para comparar el resultado real.


## Arranque backend supervisado (recomendado)

En desarrollo local no es necesario abrir una terminal separada para el worker. Desde `backend/` ejecutá:

```powershell
python -m app.run
```

El supervisor inicia FastAPI y el worker de publicación, reinicia el worker si termina inesperadamente y apaga ambos procesos en conjunto. En el despliegue single-service de Render, este mismo supervisor mantiene ambos roles dentro del modular monolith.

### Distribución comercial

La aplicación consulta `available_listing_types` para la cuenta/categoría, pero la UI muestra la intención comercial oficial de MLA: `No agregar cuotas` y `Agregar cuotas`. Internamente, `No agregar cuotas` resuelve a `gold_special` y `Agregar cuotas` a `gold_pro`; una opción sólo aparece si el listing type correspondiente está disponible para ese vendedor/categoría.

### Contrato de nombre en creación

La evidencia live de la cuenta utilizada en Discovery primero exigió `family_name` y luego rechazó `title` en el mismo `POST /items`. Por eso el dominio conserva `PublicationDraft.title` como intención independiente, mientras `payload.py` aísla la traducción al contrato actual (`family_name`). El worker registra las keys exactas del payload y compara el título devuelto por Mercado Libre con el título solicitado, sin mezclar `family_name` con la identidad interna del producto.

## Publication data integrity (V1.21)

Live publication now validates product identifiers and image dimensions before enqueueing, supports local pickup and seller warranty as structured product-version configuration, synchronizes descriptions after item creation, and exports publication timestamps using `APP_TIMEZONE`. Image policy values are configurable with `ML_IMAGE_MIN_SIDE_PX`, `ML_IMAGE_RECOMMENDED_SIDE_PX` and `ML_IMAGE_ALLOWED_FORMATS_CSV`.

## Deploy en Render — un único Web Service

El despliegue productivo recomendado para esta versión mantiene el **modular monolith** en un solo Web Service de Render:

```text
Render Web Service
├── FastAPI
├── publication worker
└── React/Vite compilado y servido por FastAPI
        ↓
PostgreSQL externo
```

El `Dockerfile` de la raíz usa un build multistage: Node compila `frontend/dist` y la imagen final contiene sólo Python, el backend y los estáticos compilados. `python -m app.run` sigue siendo el único supervisor de runtime y escucha en `0.0.0.0:$PORT`, como requiere Render.

Configuración del servicio en Render:

```text
Language / Runtime: Docker
Dockerfile Path: ./Dockerfile
Health Check Path: /health
Persistent Disk: ninguno
```

El contenedor ejecuta automáticamente `python -m alembic upgrade head` antes de iniciar el supervisor.

### Variables de entorno mínimas en Render

No subir `.env` al repositorio. Configurar los secretos desde el dashboard de Render:

```env
APP_ENV=production
APP_SECRET_KEY=<secreto largo y aleatorio>
APP_ENCRYPTION_KEY=<clave Fernet>
DATABASE_URL=<postgresql+psycopg://...>
FRONTEND_URL=https://<servicio>.onrender.com
CORS_ORIGINS=https://<servicio>.onrender.com
ML_CLIENT_ID=<...>
ML_CLIENT_SECRET=<...>
ML_REDIRECT_URI=https://<servicio>.onrender.com/api/accounts/oauth/callback
ML_LIVE_PUBLICATION_ENABLED=true
OPENAI_API_KEY=<...>
OPENAI_MODEL=<modelo configurado>
HF_TOKEN=<opcional pero recomendado>
```

`PORT` lo provee Render y no debe fijarse manualmente. El frontend usa el mismo origen que FastAPI en producción, por lo que no necesita `VITE_API_URL` en Render.

Para generar `APP_ENCRYPTION_KEY` localmente:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Uploads temporales

Render no usa Persistent Disk para imágenes. El contenedor configura:

```text
UPLOAD_DIR=/tmp/ml-enterprise/uploads
CLEANUP_UPLOADS_AFTER_SUCCESS=true
```

Las imágenes se guardan sólo mientras se prepara/publica el lote. El worker las sube directamente a Mercado Libre mediante `/pictures/items/upload`; cuando un job termina completamente en `COMPLETED`, elimina los bytes locales y conserva únicamente la metadata de auditoría en PostgreSQL. Los jobs `FAILED` o `PARTIAL` conservan temporalmente los archivos para permitir correcciones y reintentos mientras la instancia siga viva.

Como el filesystem de Render es efímero, un restart o redeploy puede descartar uploads pendientes. Las imágenes originales deben conservarse fuera del servicio, por ejemplo en la PC del operador.
