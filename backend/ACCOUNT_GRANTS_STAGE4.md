# Entrega 2: asignaciones administrativas de cuentas ML

Este incremento permite consultar y guardar asignaciones usuario-cuenta ML mediante:

- `GET /api/operator-account-grants/accounts`
- `GET /api/operator-account-grants/{user_id}`
- `PUT /api/operator-account-grants/{user_id}` con `{ "account_ids": ["UUID", ...] }`

La API y el panel requieren una sesión de Administrador o Supervisor. Los Supervisores no pueden gestionar asignaciones de un Administrador; la regla se comprueba del lado del backend. Se verifica existencia de usuario y de cuentas. Sustituir con una lista vacía elimina todas las asignaciones de ese usuario. La tabla `operator_account_grants` ya existe desde la migración `0010_operator_identity`.

## Alcance y limitaciones de seguridad

**Estas asignaciones son configuración administrativa, NO autorizaciones comerciales efectivas todavía.** El sistema actual resuelve cuentas en varias rutas indirectas mediante `account_id`, `batch_id`, `draft_id` y `job_id` (también SSE/descargas). Hasta que todas esas rutas apliquen filtro o comprobación de alcance en backend, NO se debe permitir uso comercial por operadores. El Administrador puede probar y configurar asignaciones; se mantienen los endpoints comerciales previos sin alterar.

Antes de activar operadores faltan: alcance de cuenta en todas las rutas de lectura y escritura, ownership de fichas nuevas y antiguas, leases/fencing, atribución persistente de jobs y auditoría, y pruebas de integración negativas entre operadores/cuentas. Tampoco hubo pruebas de integración con PostgreSQL ni compilación completa de React en el entorno de creación de este parche.

## Validación en el servidor

1. Confirmar `alembic current` = `0010_operator_identity`.
2. Aplicar este parche tras todos los incrementos anteriores de Entrega 2, con backup y FastAPI detenido.
3. `npm run build` desde `frontend` y reiniciar FastAPI.
4. Login Administrador, seleccionar un usuario en «Usuarios y permisos» y asignar cuentas. Refrescar y comprobar persistencia.
5. Supervisor: comprobar que no puede consultar o modificar asignaciones de Administradores (HTTP 403).
6. Operador: comprobar que PUT de asignaciones devuelve HTTP 403.
7. No habilitar todavía las cuentas de operadores para publicaciones reales.
