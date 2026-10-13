# Etapa 2 / Incremento 13 — Propiedad de borradores y trabajos

- La cuenta ML asignada no basta: antes de crear/consultar/modificar borradores y consultar/publicar/exportar jobs de un Operador también se comprueba la propiedad de las fichas relacionadas.
- Fichas históricas sin creador identificado siguen restringidas a Administradores.
- La corrección de lote `POST /api/drafts/batches/{id}/product-correction` sigue creando versiones sin exigir fencing token; por seguridad se deniega para Operadores hasta integrar la validación transaccional del bloqueo.
- El Administrador conserva el comportamiento comercial anterior.
- Sin migraciones nuevas ni cambios del frontend.
- Pendiente: pruebas de integración con PostgreSQL, publicación real con imágenes (las URLs protegidas por cookies actualmente no son accesibles para Mercado Libre) y flujos de Operador con dos sesiones.

- Se conserva la ruta de reutilización de atributos técnicos, con propiedad y cuenta verificadas en su handler.
