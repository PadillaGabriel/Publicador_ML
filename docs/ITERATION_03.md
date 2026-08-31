# Iteración 03 — ficha técnica enfocada

## Problema detectado

La ficha técnica renderizaba de forma plana todos los atributos devueltos por la categoría de Mercado Libre. Esto obligaba al operador a recorrer y completar manualmente una cantidad innecesaria de campos opcionales.

## Decisión

La metadata de Mercado Libre continúa siendo la fuente de verdad. La UI ahora separa:

- **Obligatorios**: atributos marcados por Mercado Libre como `required` o `catalog_required`.
- **Opcionales**: permanecen disponibles, pero colapsados por defecto.

No se hardcodean categorías ni listas de atributos por rubro. Tampoco se usa OpenAI para decidir atributos.

## Comportamiento

1. Al seleccionar una categoría se carga la metadata dinámica.
2. La ficha muestra primero únicamente los atributos obligatorios.
3. Se muestra progreso de obligatorios completos.
4. No se permite guardar la ficha mientras falte un atributo obligatorio.
5. Los atributos opcionales pueden desplegarse cuando el operador conoce el dato y quiere enriquecer la publicación.
6. Al cambiar cuenta o categoría se limpian los atributos previamente cargados para evitar contaminación entre fichas.

## Backend

`catalog.normalization.normalize_attributes` centraliza la normalización de atributos y considera obligatorio un atributo cuando Mercado Libre informa `required` o `catalog_required`.

La validación previa a publicación aplica el mismo criterio, incluyendo snapshots de metadata generados por versiones anteriores.

## Tests

Se agregaron pruebas unitarias para:

- `required`.
- `catalog_required`.
- atributos opcionales.

No se agregaron dependencias ni migraciones.
