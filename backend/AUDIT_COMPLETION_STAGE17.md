# Incremento 17 — Trazabilidad de carga de imágenes y cancelación de jobs

Los eventos `PRODUCT_IMAGE_UPLOADED` y `PUBLICATION_JOB_CANCELLED` registran `actor_user_id` tomado de la sesión autenticada. La auditoría de imágenes se inserta antes de la confirmación de la misma transacción que persiste su registro, y la cancelación se registra antes del commit del job. Los eventos históricos permanecen sin atribución retroactiva.

Sin migraciones nuevas. No cambia la autorización efectiva ni los permisos por cuenta; las comprobaciones de integración con PostgreSQL y dos sesiones permanecen pendientes. Los métodos de persistencia de imágenes aceptan un actor opcional por compatibilidad con llamadas existentes de pruebas: los endpoints HTTP proporcionan explícitamente el actor autenticado.
