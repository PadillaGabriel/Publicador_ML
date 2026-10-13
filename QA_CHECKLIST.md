# QA CHECKLIST — PUBLICADOR ML ENTERPRISE

Estados permitidos: `NO EJECUTADO`, `PASS`, `FAIL`, `BLOQUEADO`, `NO IMPLEMENTADO`, `NO APLICA`.

| ID | Pri. | Módulo | Precondición | Pasos | Resultado esperado | Resultado obtenido | Estado | Evidencia / Observaciones |
|---|---|---|---|---|---|---|---|---|
| QA-001 | P0 | Login | Usuario activo | Login correcto | Sesión válida y `/me` devuelve identidad/rol |  | NO EJECUTADO |  |
| QA-002 | P0 | Login | Usuario activo | Password incorrecta | Rechazo sin enumeración de usuario |  | NO EJECUTADO |  |
| QA-003 | P0 | Login | 5 fallos/15 min | Repetir login inválido | HTTP 429 según política |  | NO EJECUTADO | PostgreSQL real |
| QA-004 | P0 | Login | Sesión activa | Logout y reutilizar cookie | Sesión revocada |  | NO EJECUTADO |  |
| QA-005 | P0 | Login | Sesión expirada | Llamar recurso protegido | 401 |  | NO EJECUTADO |  |
| QA-010 | P0 | Roles | Supervisor | Crear/promover ADMIN por API | 403 |  | NO EJECUTADO |  |
| QA-011 | P0 | Roles | Operador | Configuración global | 403 |  | NO EJECUTADO |  |
| QA-012 | P0 | Roles | Admin | Editar ficha ajena | Permitido |  | NO EJECUTADO |  |
| QA-020 | P0 | Cuentas | Operador con grant A | Operar cuenta A | Permitido |  | NO EJECUTADO |  |
| QA-021 | P0 | Cuentas | Operador sin grant B | Forzar account_id/batch/draft/job de B | 403 |  | NO EJECUTADO |  |
| QA-030 | P0 | Fichas | Operador | Crear ficha | created_by_user_id correcto |  | NO EJECUTADO |  |
| QA-031 | P0 | Fichas | Ficha propia | Nueva versión | Guarda con control de versión |  | NO EJECUTADO |  |
| QA-032 | P0 | Fichas | Ficha ajena | Operador intenta editar | 403 |  | NO EJECUTADO |  |
| QA-040 | P0 | Locks | Dos operadores | Ambos abren misma ficha | Segundo recibe conflicto/lease inválido |  | NO EJECUTADO | Concurrencia real |
| QA-041 | P0 | Locks | Token vencido | Guardar | 409/rechazo |  | NO EJECUTADO |  |
| QA-042 | P0 | Locks | Lease liberado | Reusar token | Rechazo |  | NO EJECUTADO |  |
| QA-043 | P0 | Locks | Versión vieja | Guardar | Rechazo por optimistic concurrency |  | NO EJECUTADO |  |
| QA-050 | P0 | Imágenes | Lease válido | Subir JPG/PNG | Miniatura visible y metadata persistida |  | NO EJECUTADO |  |
| QA-051 | P0 | Imágenes | 3 imágenes | Mover 3 -> 1 | position=1 y badge Principal |  | NO EJECUTADO |  |
| QA-052 | P0 | Imágenes | 3 imágenes | Eliminar imagen 2 | Archivo/row eliminados, posiciones normalizadas |  | NO EJECUTADO |  |
| QA-053 | P0 | Imágenes | Sin lease/propiedad | Reordenar/eliminar por API | Rechazo |  | NO EJECUTADO |  |
| QA-054 | P0 | Imágenes | Orden guardado | Generar 2 drafts | Ambos usan exactamente el orden persistido |  | NO EJECUTADO | Unit contract cubierto |
| QA-060 | P0 | Pricing | Contexto válido | Abrir Precio y logística | Dimensiones/peso/logística antes del cálculo |  | NO EJECUTADO |  |
| QA-061 | P0 | Pricing | Flex + Colecta disponibles | Calcular | Costos separados |  | NO EJECUTADO | ML real |
| QA-062 | P0 | Pricing | Colecta no cotizable | Calcular | `No disponible`, sin usar Flex como fallback |  | NO EJECUTADO | ML real |
| QA-063 | P1 | Pricing | Mismo contexto/precio | Repetir cálculo | Cache exacto reutilizable |  | NO EJECUTADO | Revisar logs performance |
| QA-064 | P1 | Pricing | Cambiar CMV | Recalcular | No pierde exactitud ni inventa tarifas |  | NO EJECUTADO |  |
| QA-070 | P0 | B2B | Tabla completa | Publicar MLA | Estado pasa Pending/Sync -> Published tras relectura |  | NO EJECUTADO | ML real |
| QA-071 | P0 | B2B | API write 2xx pero lectura no coincide | Sincronizar | Debe quedar FAILED |  | NO EJECUTADO | Unit contract cubierto |
| QA-072 | P1 | B2B | Configuración incompleta | Publicar | No enviar; estado explícito |  | NO EJECUTADO |  |
| QA-073 | P1 | B2B | Falla ML | Reintentar | Error visible y reintento controlado |  | NO IMPLEMENTADO | Falta UI dedicada |
| QA-080 | P0 | Multicuenta | 2 cuentas con grants | Seleccionar ambas y generar | Batch independiente por cuenta |  | NO EJECUTADO |  |
| QA-081 | P0 | Multicuenta | 6 x 2 | Generar | 12 títulos sin repetidos en operación |  | NO EJECUTADO |  |
| QA-082 | P0 | Multicuenta | Drafts aprobados en 2 cuentas | Publicar seleccionados | Un job consolidado |  | NO EJECUTADO |  |
| QA-083 | P0 | Multicuenta | Cuenta A OK, B falla | Ejecutar job | A permanece publicada; job PARTIAL |  | NO EJECUTADO | ML real |
| QA-084 | P0 | Multicuenta | Operador sin grant B | Forzar draft B en `/jobs/multi` | 403 |  | NO EJECUTADO |  |
| QA-090 | P0 | Publicación | Draft válido | Prevalidar/aprobar/publicar | MLA creado, imágenes privadas subidas a ML |  | NO EJECUTADO | ML real |
| QA-091 | P0 | Publicación | Worker activo | Job | Progreso y resultado coherentes |  | NO EJECUTADO |  |
| QA-100 | P0 | Auditoría | Acciones ejecutadas | Consultar audit | quién/qué/cuándo/recurso/resultado |  | NO EJECUTADO |  |
| QA-110 | P0 | Build | npm deps instaladas | `npm run build` | PASS sin errores TS | Dependencias no instalables en sandbox | BLOQUEADO | npm registry/cache |
| QA-111 | P0 | Backend | Entorno aislado | `pytest -q` | 0 fallos | 351 passed | PASS | Sandbox SQLite de tests |
| QA-112 | P0 | Python | Código final | `compileall` | PASS | PASS |  |
| QA-113 | P0 | Alembic | Proyecto final | `alembic heads` | un único head | 0013_operator_login_throttle | PASS | `current` requiere BD real migrada |
| QA-120 | P1 | Updates | MLA existente | Preview diff -> confirmar -> ejecutar | Before/after auditado |  | NO IMPLEMENTADO | Base no lo tenía completo |
| QA-121 | P1 | Updates | Múltiples MLA | Update masivo campos elegidos | Sin blind overwrite |  | NO IMPLEMENTADO | Base no lo tenía completo |
