# Iteración 06 — Keyword Intelligence con tendencias + embeddings locales

## Objetivo

Reemplazar la extracción de keywords basada únicamente en la ficha por evidencia externa legítima de Mercado Libre, manteniendo `NO DATA = NO CLAIM` y sin scraping.

## Fuente verificada

Las pruebas controladas con la cuenta conectada devolvieron HTTP 200 para `GET /trends/MLA/{category_id}` y una lista de objetos con `keyword`/`url`. Se integra sólo `keyword`. No se asume volumen de búsquedas ni que la posición de la respuesta represente popularidad cuantitativa.

## Flujo

1. Al generar borradores se obtiene la categoría hoja y su metadata.
2. Se busca un `KeywordTrendSnapshot` vigente por `site_id + category_id`.
3. Cache miss: se consulta Mercado Libre y se persiste el snapshot con TTL.
4. Se arma evidencia del producto desde título, categoría, atributos y discovery context.
5. Sentence Transformers calcula similitud semántica local producto ↔ tendencias.
6. Una compuerta factual determinista excluye términos que introducen tokens no respaldados por la ficha.
7. Se rankean únicamente candidatos factualmente seguros y semánticamente relevantes.
8. `KeywordSnapshot` conserva términos seleccionados, scores, tokens no soportados, modelo y referencia al snapshot de tendencias.
9. Sólo las tendencias seleccionadas se envían a OpenAI.

## Modelo local

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, configurable por entorno. El modelo produce embeddings de 384 dimensiones y está preparado para múltiples idiomas. No se incorpora una base vectorial: el corpus es del orden de decenas de tendencias y la similitud se calcula en memoria.

## Seguridad factual

La similitud semántica no autoriza claims. Por ejemplo, `mate imperial algarrobo` puede ser semánticamente muy cercano a un mate imperial de calabaza; se descarta si `algarrobo` no está respaldado por la ficha.

## Caché y fallback

TTL por defecto: 24 horas. Si el refresh falla pero existe un snapshot anterior, se permite un fallback stale controlado y auditable. Si nunca hubo evidencia externa disponible, la generación se detiene con un error estructurado en lugar de degradarse silenciosamente a keywords inventadas.

## Migración

Ejecutar:

```powershell
cd backend
pip install -e ".[dev]"
alembic upgrade head
```

La primera generación que use embeddings puede descargar el modelo local si todavía no está en caché.
