# Iteración 02 — cuentas, cuotas y exportación operativa

## Decisiones

### Cuentas

- Mantener `ml_accounts` como identidad interna estable.
- OAuth se encapsula en `MercadoLibreOAuthClient`.
- Tokens nunca se exponen al frontend.
- Access y refresh token se cifran con `APP_ENCRYPTION_KEY`.
- El refresh se intenta automáticamente cinco minutos antes del vencimiento.
- Mientras la Redirect URI configurada pertenece a otra aplicación desplegada, el frontend mantiene una conexión temporal por access token para desarrollo.

### Cuotas

- La cantidad de cuotas es una propiedad del `PublicationDraft`, no del `ProductMaster`, porque dos publicaciones del mismo producto pueden tener estrategias comerciales distintas.
- `DraftBatch.installment_distribution` conserva la intención agregada del lote.
- `PublicationDraft.installments` conserva la intención individual.
- `commercial_config` queda como punto de extensión para guardar la resolución real de Mercado Libre sin agregar columnas por cada cambio comercial.
- No se inventa una equivalencia fija entre cuotas y `listing_type_id`.
- Live publishing bloquea planes > 1 si no fueron resueltos.

### Exportación

- El Excel se genera desde un job terminado para reflejar el resultado efectivo, no la intención previa.
- El vínculo SKU → MLA se deriva de ProductMaster → ProductVersion → Draft → Publication.
- Se incluye una segunda hoja con no publicadas para cierre operativo y auditoría.

### Migraciones

- `0001_initial` se congeló como snapshot de esquema V1 para evitar que una base nueva dependa del ORM actual.
- `0002_accounts_financing_exports` contiene únicamente cambios incrementales.
