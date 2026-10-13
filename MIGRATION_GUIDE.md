# MIGRATION GUIDE

## 1. Backup

- Backup completo de PostgreSQL.
- Copia íntegra de la versión actualmente desplegada.
- Conservar `.env` y secretos fuera del ZIP.

## 2. Copiar archivos

Descomprimir la entrega en un directorio nuevo. No mezclar manualmente archivos con una versión vieja.

## 3. Dependencias

Backend:
```bash
cd backend
pip install -e .[dev]
```

Frontend:
```bash
cd frontend
npm ci
```

## 4. Alembic

```bash
cd backend
alembic heads
alembic current
alembic upgrade head
```

Head esperado por esta entrega: `0013_operator_login_throttle`.

## 5. Build

```bash
cd frontend
npm run build
```

Debe finalizar `tsc -b && vite build` sin errores. Si falla, NO desplegar.

## 6. Tests

```bash
cd backend
python -m pytest -q
```

Debe finalizar sin `failed` ni `errors`.

## 7. Arranque controlado

- `ML_LIVE_PUBLICATION_ENABLED=false` para staging inicial.
- Arrancar API.
- Arrancar workers.
- Verificar heartbeat.
- Exponer con un único ngrok si corresponde.

## 8. QA funcional

Ejecutar `QA_CHECKLIST.md`. Prioridad: autenticación/permisos, leases, imágenes, pricing/logística, B2B, multicuenta y publicación real controlada.

## 9. Promoción

Solo habilitar producción después de:

- build frontend PASS en entorno limpio;
- pytest PASS;
- migraciones verificadas sobre PostgreSQL real;
- OAuth real;
- publicación real controlada;
- B2B real verificado;
- multicuenta con fallo parcial;
- concurrencia con dos operadores;
- aprobación de todos los P0.
