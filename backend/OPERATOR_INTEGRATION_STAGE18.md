# Entrega 2 — Verificación integrada de aislamiento (etapa 18)

Se incorpora `scripts/verify_operator_isolation.py`. No modifica el sistema productivo;
es un verificador **contra el backend en ejecución**.

## Requisitos

- Instalar todos los parches previos, hasta auditoría de imágenes / cancelación de jobs.
- Tres usuarios existentes: un `ADMIN`, dos `OPERATOR`.
- Dos fichas **de prueba**, una creada por cada Operador; usar sus UUID reales de `product_masters`.
- Ejecutar cuando nadie esté editando la ficha del Operador A (el verificador toma y libera un bloqueo).
- URL HTTPS del origen público o HTTP en `localhost`.
- Opcional: UUID de un lote, job e imagen pertenecientes al Operador A.

## Ejecución desde backend

```powershell
.\.venv\Scripts\python.exe scripts\verify_operator_isolation.py `
  --base-url "https://TU_DOMINIO" `
  --admin "admin" --operator-a "operador_a" --operator-b "operador_b" `
  --product-a "UUID_FICHA_A" --product-b "UUID_FICHA_B"
```

El script solicita las contraseñas de manera interactiva y no las imprime ni persiste.
Para ampliar la prueba: `--batch-a UUID --job-a UUID --image-a UUID`.
Las pruebas opcionales requieren que esos recursos pertenezcan inequívocamente
al Operador A y estén disponibles. No se crean publicaciones ni se actualiza stock/precio.

## Límites

- El verificador comprueba respuestas HTTP, no aislamiento transaccional mediante carreras reales.
- Los bloqueos pueden quedar vigentes hasta su caducidad si el proceso termina abruptamente.
- No comprueba compatibilidad de `/items/validate` con la API real de Mercado Libre.
- No constituye auditoría de seguridad completa ni prueba de carga.
- El control de intentos repetidos de login sigue pendiente de implementación.

**No habilitar acceso general de operadores** hasta verificar resultados y revisar incidencias.
