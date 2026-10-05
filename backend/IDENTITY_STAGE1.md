# Entrega 2 — Etapa 1: esquema de identidad

Este incremento es **solo la base persistente y la política RBAC**. No crea usuarios, no agrega login y **NO protege aún los endpoints operativos**. No usar el túnel ngrok como sustituto de autenticación. Mantener acceso externo restringido hasta completar la etapa de activación.

## Instalación

1. Realizar un respaldo consistente de PostgreSQL antes de migrar.
2. Copiar los archivos del parche respetando sus directorios.
3. Ejecutar `python -m alembic upgrade head` desde `backend` con el mismo `.env` de la aplicación.
4. Verificar `python -m alembic current` y que muestra `0010_operator_identity`.
5. Reiniciar el backend después de migrar. La aplicación actual mantiene su comportamiento; la autorización nueva todavía no está activa.

No ejecutar `downgrade` en producción sin un procedimiento de respaldo y restauración: elimina tablas de identidad y sus datos.

## Próximo incremento antes de habilitar el equipo

- Alta segura del primer administrador (sin contraseña predeterminada).
- Password hashing, cookies de sesión HttpOnly/Secure, CSRF y rate limiting de login.
- Dependencias RBAC y grants de cuentas para todas las rutas, incluidos archivos, streams y endpoints administrativos.
- Callback OAuth con estado ligado a sesión administrativa.
- Frontend de login/administración y errores 401/403.
- Lease de edición atómico, renovación y fencing token comprobado en **cada escritura**.
- Atribución del usuario que solicitó cada job y propagación de actor a auditoría.
- Migración/cutover controlado con pruebas de seguridad y sin cierre accidental de la aplicación.
