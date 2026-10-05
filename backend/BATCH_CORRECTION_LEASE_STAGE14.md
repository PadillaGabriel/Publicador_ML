# Entrega 2 — Corrección transaccional de lotes

- `POST /api/drafts/batches/{batch_id}/product-correction` exige `X-Product-Lease-Token` y `X-Expected-Product-Version` para **todos** los roles, incluidos administradores. La interfaz adquiere el bloqueo automáticamente.
- El handler resuelve la identidad de la cookie y llama al servicio con callback de autorización. El servicio bloquea la fila `DraftBatch` y la fila `ProductMaster`, valida propietario y token vigente, exige que el batch todavía apunte a la versión esperada y comprueba que no existe una versión posterior. Se crea la nueva versión y se actualiza el lote en una única transacción.
- Respuestas previstas: 401 sesión ausente, 403 propiedad/cuenta, 428 precondición ausente, 409 token vencido/ocupado o versión desactualizada.
- No requiere migración. Para revalidar lotes antiguos tras una versión más reciente de la ficha, generar un nuevo lote.
- No cambia `/uploads/` ni crea URLs públicas. El worker ya sube imágenes directamente a `/pictures/items/upload`; el preflight sigue pasando URLs privadas y requiere un tratamiento separado antes de validar publicaciones reales.
- Pruebas pendientes: PostgreSQL transaccional con dos sesiones, npm run build en Windows y flujo de validación previa con ML.
