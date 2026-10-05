# Entrega 2 — Atribución de trabajos y control de imágenes

## Dependencias

Aplicar encima de todos los parches previos, incluidos `0010_operator_identity` y `0011_product_ownership`.

## Orden

1. Respaldar PostgreSQL y detener operaciones comerciales activas.
2. Copiar los archivos del ZIP respetando directorios.
3. Desde `backend`, ejecutar `python -m alembic upgrade head`.
4. Comprobar `python -m alembic current`: `0012_job_requester`.
5. Reiniciar completamente FastAPI y probar en dos sesiones privadas independientes.

## Cambios

- La columna `jobs.requested_by_user_id` tiene FK `ON DELETE SET NULL` a `operator_users`.
- Los jobs históricos no reciben autor retroactivo.
- Al lanzar `POST /api/publication/jobs`, usuario y evento de auditoría se persistirán en la misma transacción que el job.
- La ruta `/uploads/{image_id}` exige autenticación y verifica propietario antes de enviar bytes; el middleware deja de rechazar indiscriminadamente a los Operadores.
- Rutas comerciales nuevas/no clasificadas denegadas por defecto para Operadores.

## Verificaciones pendientes en el entorno real

- Crear job con Administrador y otro con Operador; comprobar `jobs.requested_by_user_id` y `audit_events.actor_user_id`.
- Comprobar GET `/uploads/{image_id}` con propietario, operador ajeno y sin sesión (200, 403, 401 respectivamente).
- Comprobar todas las rutas comerciales operativas y OAuth en entorno de pruebas.
- **Nota:** la entrega de imágenes al propio Mercado Libre necesita un flujo de acceso externo controlado; si el marketplace descarga URLs `/uploads/` sin cookies, la autenticación puede impedir su lectura. No habilitar publicación masiva hasta validar este flujo de imágenes end-to-end.

## Alcance no incluido

No se cambian filtros de historial, `requested_by_user_id` no representa la autoría de cada acción del worker ni se reescriben los logs antiguos. No se declara habilitación multiusuario para producción.
