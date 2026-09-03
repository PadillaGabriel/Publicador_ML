# Title Intelligence — Diseño de Fase 1

## Objetivo

Generar títulos de Mercado Libre reproducibles y fieles al producto. El motor usa los datos reales del producto y señales de tendencias de la categoría como información secundaria; nunca incorpora una característica que no esté confirmada.

La Fase 1 entrega un motor determinístico, una integración con tendencias cacheadas, un endpoint interno y una acción explícita en el formulario para usar un título. Quedan fuera de alcance highlights, IA generativa, scraping, Redis, métricas y regeneración automática.

## Arquitectura

La implementación conserva las capas existentes:

- Dominio: normaliza contexto del producto, clasifica tendencias, filtra términos incompatibles, genera candidatos, puntúa y valida longitud.
- Aplicación: obtiene inteligencia de categoría, prioriza cache, aplica fallback y construye una respuesta auditable.
- Infraestructura: reutiliza el cliente de Mercado Libre y el cache de tendencias existente; no crea un cliente HTTP ni cache paralelos.
- Presentación: adapta el endpoint y muestra recomendación, alternativas y señales resumidas. No contiene reglas de títulos.

El módulo se ubica bajo `app/title_intelligence/` con submódulos por capa cuando sea necesario. El dominio no depende de FastAPI, SQLAlchemy ni del cliente HTTP.

## Datos y contratos

El request interno contiene `category_id`, título o tipo de producto, y atributos descriptivos confirmados. La restricción de longitud llega como configuración o contrato de categoría, no como constante dentro del generador.

La respuesta incluye:

- título recomendado;
- alternativas determinísticas;
- nivel de confianza;
- señales aplicadas, sin detalles técnicos para la UI final;
- indicador de fallback cuando no se utilizaron tendencias.

`Trend` conserva texto, posición y familia (`FASTEST_GROWING`, `MOST_WANTED`, `MOST_POPULAR`). Una sola función clasifica la respuesta de Mercado Libre por rangos para concentrar el contrato externo.

## Flujo

1. El frontend obtiene una categoría real del flujo actual.
2. La aplicación consulta la inteligencia de esa categoría en cache.
3. Ante un miss, el proveedor de Mercado Libre solicita tendencias y actualiza el cache existente.
4. El dominio normaliza el producto y las tendencias, descarta términos incompatibles y crea candidatos.
5. El dominio puntúa exactitud del producto antes que relevancia de tendencia, deduplica y aplica la restricción de longitud.
6. El endpoint devuelve el resultado.
7. El usuario elige explícitamente usar un título; esa acción sólo actualiza el formulario local.

## Fallback y errores

Una falla, timeout o respuesta inválida de tendencias no bloquea la generación. Si hay cache previa, se usa; de lo contrario, el dominio genera desde los datos reales del producto sin tendencias y expone `fallback_used`.

Sólo faltas esenciales —categoría, identidad del producto o restricción válida— devuelven un error de validación. No se estiman ni inventan atributos.

## Interfaz

Con categoría y datos descriptivos disponibles, el publicador muestra una acción “Generar título”. El resultado presenta título recomendado, alternativas y una explicación breve: categoría, datos del producto y tendencias relacionadas cuando se usaron. “Usar título” copia el valor al campo del formulario; no llama a borradores, jobs ni publicaciones.

## Pruebas

- Clasificación de tendencias por rango.
- Normalización, deduplicación, compatibilidad de atributos y longitud.
- Generación determinística con tendencias y sin tendencias.
- Tendencia incompatible que nunca se incorpora.
- Cache hit, miss y fallback ante error del proveedor.
- Endpoint con respuesta estable.
- Integración UI que copia el título sin crear borradores, jobs ni publicaciones.

## Criterios de aceptación

- El mismo contexto e inteligencia produce el mismo resultado.
- Un título válido se genera aun cuando tendencias no estén disponibles.
- Ningún atributo ausente o contradictorio se agrega al título.
- Las tendencias se consultan fuera de la ruta crítica cuando ya existen en cache.
- No se duplican cliente HTTP, cache ni lógica de generación.
