# Iteración 13 — Alineación con publicación masiva oficial de Mercado Libre

## Objetivo

Alinear el modelo de negocio del publicador con las dos planillas oficiales analizadas para MLA: alta masiva y modificación de publicaciones, sin acoplar el dominio interno a nombres técnicos del backend de Mercado Libre.

## Decisiones

### 1. Cuotas como intención de negocio

En Argentina, Mercado Libre documenta que las publicaciones se diferencian en frontend por:

- `No agregar cuotas` → backend `gold_special`.
- `Agregar cuotas` → backend `gold_pro`.

La aplicación vuelve a exponer exactamente esa intención. No muestra Classic/Premium como decisión de negocio y no inventa cantidades fijas 3/6/9/12.

El resolver comercial consulta primero `available_listing_types` para vendedor + categoría y sólo ofrece una intención si el listing type correspondiente está disponible.

### 2. Título independiente por borrador

`PublicationDraft.title` sigue siendo la intención de título individual de cada publicación. El dominio no usa `family_name` como identidad de `ProductMaster` ni de `ProductVersion`.

El contrato live observado para el POST de creación exigió `family_name` y rechazó `title`. Esa particularidad queda aislada en `publication/payload.py`: mientras ese contrato siga vigente, el título del borrador se traduce a `family_name` únicamente al construir el request externo.

Después del alta, el worker compara el `title` devuelto por Mercado Libre contra el título solicitado y deja evidencia en logs y en el Excel final.

### 3. Auditoría del request real

Antes de `POST /items`, el worker registra sólo las keys del payload:

- no imprime tokens;
- permite verificar si `title` fue enviado o no;
- registra la intención comercial resuelta;
- al éxito registra `item_id`, `user_product_id`, título devuelto y si coincide con la intención.

### 4. Excel final

La hoja `Publicaciones` distingue:

- título solicitado;
- título devuelto por Mercado Libre;
- modalidad de cuotas;
- listing type técnico;
- User Product ID.

Esto permite validar empíricamente el contrato de creación sin inferir comportamiento interno de Mercado Libre.

## Migración

La migración `0005_commercial_intent_alignment` elimina la columna histórica `PublicationDraft.installments` y renombra `DraftBatch.installment_distribution` a `commercial_distribution`. La fuente de verdad comercial queda en `commercial_config.commercial_intent` y en la distribución del lote.
