# Entrega 2 — Incremento 7: integración de bloqueo y escritura

## Dependencias
Instalar después del incremento `0011_product_ownership` y los anteriores. No incluye nueva migración.

## Comportamiento
- Una ficha existente se guarda únicamente con `X-Product-Lease-Token` (fencing token activo de la sesión) y `X-Expected-Version` (última versión leída por el editor).
- La transacción de guardado bloquea la fila maestra `FOR UPDATE`, comprueba propiedad, sesión, token, vencimiento y versión esperada, y crea una nueva versión atómicamente.
- La creación de un SKU completamente nuevo no requiere un bloqueo previo, pero después de guardar se adquiere el bloqueo para permitir la carga de imágenes.
- Las cargas de imágenes existentes exigen bloqueo válido antes de escribir archivos. La comprobación comparte transacción con la persistencia del lote.
- El navegador toma el bloqueo al abrir una ficha existente, lo renueva cada 50 segundos, lo libera al iniciar otra ficha o cambiar SKU, y advierte de la pérdida del bloqueo.
- `GET /api/products`, `GET /api/products/lookup` y `GET /api/products/versions/{id}` filtran o comprueban propiedad de fichas para Operadores.
- Las fichas históricas sin autor siguen reservadas al Administrador.
- El read-only de atributos reutilizables también valida propiedad y cuenta autorizada, aunque la capa global sigue negando esta ruta a Operadores hasta el siguiente incremento.

## Respuestas previstas
- 428: falta el bloqueo o la versión esperada.
- 409: bloqueo ocupado, vencido, ajeno, o guardado basado en versión desactualizada.
- 403: ficha no perteneciente al operador.
- 404: ficha o versión inexistente.

## Limitaciones
- No habilitar aún a todos los operadores: `/uploads/` sigue restringido para Operadores y falta auditar los endpoints de títulos, atributos y todos los recorridos comerciales de principio a fin.
- Faltan pruebas de contención reales contra PostgreSQL y compilación completa del frontend. Estas validaciones se deben ejecutar antes de generalizar acceso multiusuario.
- Si un navegador cierra abruptamente, el bloqueo se libera por vencimiento de 2 minutos.
- El control de versión evita sobrescritura de fichas guardadas; no conserva automáticamente los cambios locales ante conflictos.

## Instalación y pruebas
1. Completar trabajos, respaldar archivos y PostgreSQL, y aplicar solo los archivos del ZIP.
2. No hay migración adicional. `alembic current` debe seguir en `0011_product_ownership`.
3. Ejecutar `npm run build` dentro de `frontend` y reiniciar FastAPI después de actualizar backend/frontend.
4. Administrador: crear ficha nueva y cargar imágenes; recuperar SKU guardado, editar, guardar nueva versión y cargar imágenes.
5. Desde sesión B: intentar adquirir bloqueo mientras A lo tiene (esperado 409). Desde A, liberar; desde B adquirir y editar.
6. Probar edición con token incorrecto y versión obsoleta (esperado 409), y sin token (428).
7. Tests locales: `python -m pytest tests/test_product_edit_lease_contract.py tests/test_operator_account_scope.py -q`.
