# Incremento 2 — Login visual + barrera inicial de autenticación

## Requisitos previos

- Aplicar **primero** los ZIP anteriores: base de identidad y autenticación base.
- Ejecutar `alembic upgrade head` y confirmar `0010_operator_identity`.
- Crear el administrador inicial **antes** de iniciar la API protegida: `python scripts/bootstrap_operator_admin.py`.
- Configurar `APP_PUBLIC_BASE_URL=https://<subdominio-actual>.ngrok-free.app`, `FRONTEND_URL` y `CORS_ORIGINS` con la URL HTTPS actual. En este incremento, probar con el origen HTTPS público y no mezclarlo con `localhost`.
- Desplegar backend y frontend compilado de manera coordinada, con los trabajos actuales terminados.

## Alcance efectivo

- Todas las rutas `/api/*` exigen sesión salvo login, consulta/control de sesión (que ya se protegen en sus handlers) y el callback OAuth firmado.
- `/uploads/*` exige sesión; `/health` y los archivos estáticos del frontend continúan públicos.
- Las operaciones protegidas comprueban roles generales. Las funciones de consulta siguen accesibles para usuarios autenticados.
- El login no es todavía un módulo multiusuario completo: **faltan asignaciones por cuenta ML, comprobación de propiedad de fichas, bloqueo de edición, auditoría por actor y limitación distribuida de intentos de login**. No habilitar operadores adicionales hasta completar esos controles.
- El callback OAuth preserva el state firmado actual, pero todavía no está ligado criptográficamente al usuario interno que inició la vinculación. Completar esa vinculación antes de abrir la administración de cuentas a varios administradores.
- La caducidad de sesión muestra de nuevo el login y deja el formulario montado en el navegador. No sustituye el guardado persistente de borradores.

## Prueba de humo

1. Sin sesión: `GET /api/accounts` → 401, `GET /uploads/<uuid>` → 401, `GET /health` → 200.
2. Login desde el navegador en el origen configurado → cookie HttpOnly y vista del Publicador.
3. `GET /api/operator-auth/me` → identidad del operador.
4. Probar creación y consulta de ficha, subida de imagen y consulta del job existente.
5. Logout → sesión revocada; `GET /api/accounts` → 401.
6. La sesión caducada solicita credenciales, sin mezclar un trabajo anterior con uno nuevo.
7. El flujo OAuth sigue teniendo callback exento de cookie interna; verificar siempre el origen correcto de redirección.

## Reversión

Restaurar `app/main.py`, `operator_auth_router.py` y `frontend/src/main.tsx`, `api.ts`, `styles.css` de la copia anterior, además de retirar `operator_access.py` del despliegue. **No revertir las migraciones de usuarios ni borrar sus datos**. Realizar la reversión durante una ventana controlada; no dejar la aplicación sin protección detrás del túnel público.
