# Entrega 2: hardening de autenticación y criterios de aceptación

Se limita el login por usuario normalizado con estado persistido en PostgreSQL (5 intentos fallidos en 15 minutos; 429 con Retry-After). Las sesiones existentes no se alteran. La tabla solo almacena SHA-256 del usuario y no contraseñas ni IPs. Transacciones por usuario se serializan con advisory lock; la solución requiere PostgreSQL. Para no generar un bloqueo global cuando los usuarios comparten un proxy ngrok, este incremento no aplica un límite por IP. Un tercero que conozca un nombre de usuario puede provocar un bloqueo temporal de esa cuenta: es un riesgo residual que requiere mitigación operativa.

## Instalación

1. Terminar trabajos, respaldar PostgreSQL y los archivos.
2. Aplicar archivos del parche sobre el último estado acumulado; ejecutar `python -m alembic upgrade head` desde `backend`; el objetivo es `0013_operator_login_throttle`.
3. Reiniciar API; probar login correcto e incorrecto en una cuenta de **prueba** (5 fallos, sexto intento → 429, Retry-After; luego esperar 15 minutos). No bloquear al Administrador principal durante las pruebas.
4. Ejecutar `python -m pytest tests/test_operator_login_throttle_stage19.py -v`.

## Criterios de aceptación aún pendientes

- Salida **real** de `scripts/verify_operator_isolation.py` con administrador, dos operadores y dos fichas propias, con las pruebas opcionales de lote/job/imagen si hay fixtures seguros.
- Verificar que los límites del login sean persistentes **entre reinicios de FastAPI** y procesen solicitudes concurrentes sin inconsistencias.
- Verificar en la API de ML que la prevalidación acepte picture IDs, seguida de una publicación controlada con imágenes privadas, sin abrir `/uploads/` públicamente.
- Repetir pruebas de regresión del pipeline comercial normal como ADMIN y como operador con cuenta autorizada, incluidas imágenes, lotes y corrección bajo lease.
- Revisar errores, auditoría, reversión de cambios y respaldo ante fallo de los endpoints comerciales.

**No dar por aprobada la entrega ni abrir el acceso general hasta recibir evidencia de esas pruebas.**
