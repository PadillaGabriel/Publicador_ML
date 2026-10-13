# Publicador ML Enterprise — Estado de consolidación y QA

**Clasificación: candidato técnico PRELIMINAR; NO ES ENTREGA FINAL NI ESTÁ APROBADO PARA PRODUCCIÓN.**

## Procedencia y límites

- Código base: archivo facilitado por el usuario `Publicador_ML-master(3).zip`.
- Mantiene las migraciones existentes hasta `0013_operator_login_throttle`.
- Los cambios de esta revisión NO requieren migración adicional.
- Se conservan la publicación, precios, OAuth, roles, fichas y worker existentes.
- No incluye `.env`, secretos OAuth, bases de datos, subidas del usuario ni dependencias de Node.

## Completado en esta revisión

1. Nuevo módulo **Gestor e historial** de **solo lectura**. API paginada para publicaciones registradas en la base local (`/api/manager/publications`), jobs (`/api/manager/jobs`) y auditoría (`/api/manager/audit`).
2. Filtros de SKU, MLA, título, cuenta y estado sobre publicaciones de esta aplicación. No consulta un catálogo externo ni importa automáticamente todas las publicaciones históricas de las cuentas ML.
3. Restricciones SQL antes de paginar: un Operador ve únicamente sus fichas, sus cuentas autorizadas y jobs íntegramente autorizados (no jobs mixtos). Administradores y Supervisores acceden al historial del equipo; solo ellos ven auditoría. El backend valida la sesión.
4. Panel React desacoplado del formulario de publicación, con búsqueda, paginación y descarga de resultados de jobs concluidos a través del endpoint ya existente.
5. Corregida la falta de `actor_user_id` en eventos de creación/versión de ficha.
6. Contratos de tests antiguos adaptados para probar los handlers sin suprimir el middleware de autenticación de producción. Pruebas de seguridad del middleware y nuevas pruebas relacionales del gestor.

## Evidencia automatizada

- `DATABASE_URL=sqlite+pysqlite:////tmp/ml-qa-not-production.db python -m pytest -q --disable-warnings` en `backend`: **351 pruebas aprobadas** en el sandbox.
- El grupo del gestor usa SQLAlchemy en memoria SQLite con representación local de JSONB. **No sustituye** PostgreSQL de producción, una prueba real de concurrencia ni Mercado Libre.
- `main.tsx`, `PublicationManager.tsx` y `OperatorUsers.tsx`: TSX analizado por TypeScript sin errores sintácticos.
- **NO se ejecutó `npm run build`** porque no se pudieron instalar íntegramente las dependencias de npm en el sandbox.

## No implementado / no aprobado para entrega final

- Actualización individual de MLA con preview de diferencias, versión esperada, confirmación y auditoría.
- Actualización masiva sobre MLA seleccionados con ejecución parcial controlada y reintentos.
- Orquestación multicuenta desde una sola ficha; el publicador conserva su flujo por cuenta existente.
- Modelo comercial de precio clásico común, recargos configurables de 3/6 cuotas, y excepciones por MLA con sincronización por cuenta.
- Búsqueda integral por variación y conciliación con publicaciones de Mercado Libre **externas** a esta aplicación.
- Regresión integral en Windows con PostgreSQL real, OAuth ML, prevalidación de imágenes y publicación controlada.
- Pruebas de carga, RTO/RPO, SLO, restauración de backups y verificación de costos/precios contra API ML actual.

## Instalación exclusiva en ambiente de pruebas

1. Respaldar el proyecto y PostgreSQL. Nunca sobrescribir el sistema comercial activo con un candidato no aceptado.
2. Instalar en un clon aislado del proyecto. Ejecutar `python -m alembic current` y verificar `0013_operator_login_throttle`.
3. En `frontend`: ejecutar `npm ci` y `npm run build`. Si falla, registrar el mensaje y **no desplegar**.
4. En `backend`: ejecutar `python -m pytest -q`; si falla, registrar la prueba y **no desplegar**.
5. Iniciar API y worker en staging, sin habilitar `ML_LIVE_PUBLICATION_ENABLED`.
6. Ejecutar los casos de `CHECKLIST_QA_PUBLICADOR_ML_ENTERPRISE.md` y registrar evidencia.
7. No abrir acceso general ni publicar productos reales hasta cerrar todos los casos P0.

## Pruebas manuales nuevas para el gestor

- **MAN-01**: sin sesión, `GET /api/manager/publications` devuelve 401.
- **MAN-02**: usuario A con acceso a cuenta ML-A ve únicamente sus fichas/publicaciones.
- **MAN-03**: usuario B en la **misma** cuenta ML-A no ve fichas de A.
- **MAN-04**: revocar ML-A de A y verificar que el gestor deja de listar publicaciones y jobs de esa cuenta.
- **MAN-05**: job con fichas de A y B: A no puede verlo mediante el gestor ni descargarlo usando `job_id`.
- **MAN-06**: Administrador ve ambas fichas y jobs; Supervisor ve historial de equipo.
- **MAN-07**: Operador intenta `GET /api/manager/audit`; devuelve 403. Administrador y Supervisor pueden verlo.
- **MAN-08**: búsquedas de SKU exacto, fragmento SKU, MLA y título devuelven resultados esperados sin información de otras cuentas.
- **MAN-09**: paginación de 25, avance/retroceso; comprobar total y ausencia de duplicados.
- **MAN-10**: cambio de pestaña entre gestor y nueva ficha no descarta los datos en edición.
- **MAN-11**: descarga de Excel solo para trabajo terminal propio; un trabajo de otra ficha/cuenta responde 403.
- **MAN-12**: comprobar en Network que las respuestas del gestor no contienen tokens, contraseñas ni payloads completos de auditoría.

**Gate final:** BLOQUEADO mientras exista alguna capacidad requerida no implementada o algún caso P0 sin aprobar con evidencia.
