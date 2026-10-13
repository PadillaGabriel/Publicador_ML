# Entrega 2 / incremento 6 — Propiedad y contratos de bloqueo (etapa de preparación)

## Alcance
- Migración reversible `0011_product_ownership`: `product_masters.created_by_user_id` nullable; registros históricos permanecen sin autor atribuido.
- `POST /api/products` asocia nuevas fichas al Administrador que las creó. Los Operadores siguen bloqueados en las rutas de fichas hasta completar la integración.
- API `GET/POST/PUT/DELETE /api/product-edit-leases/{product_id}`: consultar, adquirir, renovar y liberar un bloqueo por ficha. Para PUT/DELETE se exige `fencing_token` JSON. Los bloqueos vencen a los dos minutos; una sesión que pierde el token no puede renovar o liberar el bloqueo de otra sesión. La toma se serializa mediante `SELECT FOR UPDATE` en el registro maestro.
- Una ficha histórica sin propietario es accesible por esta API exclusivamente para Administradores; el Supervisor no puede editar fichas.
- Acceso a `/uploads/{image_id}` denegado temporalmente a Operadores, porque todavía no hay verificación de pertenencia para su lectura.

## Limitaciones (NO habilitar comercialmente a Operadores)
- Aún NO se exige el fencing token en los endpoints comerciales de guardado, subida de imágenes, atributos y generación de títulos. Adquirir un bloqueo NO impide todavía que un Administrador escriba por los flujos antiguos.
- Aún NO se incorporó renovación automática, UI de bloqueo, liberación en navegación ni control optimista de versión en frontend.
- Aún NO se ha implementado migración de propiedad sobre fichas históricas ni una interfaz de reasignación auditada.
- Aún NO hay pruebas integradas de contención con PostgreSQL real.

## Orden de instalación
1. Respaldar PostgreSQL y código; terminar trabajos activos.
2. Aplicar ZIP respetando rutas.
3. Ejecutar `python -m alembic upgrade head` desde `backend` (revision nueva `0011_product_ownership`).
4. Reiniciar FastAPI.
5. Probar sesión Administrador, guardado de nueva ficha e imágenes.
6. Ejecutar `python -m pytest tests/test_product_edit_lease_contract.py -v`.

## Contrato UI para futuro incremento
- Tomar bloqueo antes de editar una ficha existente: `POST /api/product-edit-leases/{product_id}`.
- Renovar mientras se edita cada <=60s: `PUT` body `{ "fencing_token": "<uuid>" }`.
- Liberar explícitamente `DELETE` con el mismo body, o dejar caducar cuando se pierda conectividad.
- Jamás dar por válida una edición por la sola existencia visual de un lock; la mutación debe comprobar el token en la misma transacción que la escritura.
