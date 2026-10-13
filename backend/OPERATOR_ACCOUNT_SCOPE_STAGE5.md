# Entrega 2, incremento: alcance efectivo por cuenta en publicaciones

## Objetivo y alcance

- El Administrador conserva acceso global; el Supervisor conserva su política RBAC anterior.
- Un Operador consulta únicamente cuentas asignadas mediante `GET /api/accounts`.
- Para un Operador se resuelve `account_id` desde las tablas persistidas cuando la solicitud llega por `batch_id`, `draft_id` o `job_id`. Un trabajo con varias cuentas exige permisos para **todas**.
- Se verifica `account_id` de las consultas de logística/comercial, importación MLA y generación de borradores.
- Se deniega el seguimiento global `/api/jobs/active/current` a Operadores: dicho endpoint expone información de múltiples cuentas.
- Se deniegan operaciones desconocidas dentro de las familias de publicación para los Operadores (fail closed).
- Mientras no se haya incorporado propiedad de fichas, se bloquea a los Operadores el acceso a `/api/products`, `/api/title-intelligence` y `/uploads/`. La función de creación no estará disponible a ese rol hasta el siguiente incremento.

## Limitaciones conocidas / no habilitar a todo el equipo

- **No implementa propiedad de producto, leasing de edición, ni auditoría por operador.**
- Algunas rutas existentes pueden depender del estado de trabajo global. No habilitar la operación general del equipo hasta integrar esas rutas con el usuario y su ficha.
- No cambia la estructura de PostgreSQL ni los workers.
- Las rutas de administración de cuentas ML se rigen por las reglas de Administrador/Supervisor existentes.
- Los Operadores no deben recibir acceso productivo hasta completar la propiedad de fichas y la autorización de imágenes/archivos.

## Validación sugerida

1. Instalar ZIP sobre la base con todos los incrementos anteriores de Entrega 2. Reiniciar FastAPI.
2. Probar Administrador: `GET /api/accounts` y flujo habitual de ficha/borradores.
3. Probar Operador con una única cuenta asignada: lista filtrada, crear lote para cuenta propia y comprobar `403` con cuenta ajena.
4. Con ese Operador, intentar recuperar batch, draft, job y exportación de una cuenta ajena: `403`.
5. Verificar que `/api/jobs/active/current`, `/api/products` y `/uploads/{image_id}` están denegadas para Operadores de forma transitoria.
6. Verificar que las llamadas `POST` procedentes de la interfaz conservan sus cuerpos JSON.

Si aparecen discrepancias, revertir **los archivos del parche**, sin alterar los datos. No se requiere migración.
