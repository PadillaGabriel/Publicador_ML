# Iteración 07 — Ficha técnica por nivel de importancia

## Objetivo

Evitar los dos extremos detectados en la ficha dinámica: mostrar sólo los atributos obligatorios o exponer decenas de opcionales sin jerarquía. Mercado Libre continúa siendo la fuente de verdad y la UI clasifica únicamente señales presentes en la metadata oficial de la categoría.

## Clasificación

- `required`: `required` o `catalog_required`, excluyendo atributos ocultos/read-only.
- `recommended`: atributos visibles no obligatorios con `relevance > 0`, atributos `number_unit` (medidas/cantidades con unidad) y atributos booleanos/Sí-No.
- `secondary`: resto de atributos visibles.
- `system`: atributos `hidden` o `read_only`, no presentados al operador.

No existe hardcoding por categoría ni por ID de atributo.

## Entrada manual

Los atributos de tipo `string`, `number` y `number_unit` pueden aceptar `Otro valor…` aunque Mercado Libre haya enviado valores sugeridos. El valor se conserva como `value_name`/texto y sigue sujeto a las validaciones posteriores del marketplace. Listas cerradas y booleanos permanecen como selección controlada.

## UX

La ficha presenta:

1. Datos imprescindibles.
2. Completar para mejorar la publicación.
3. Más características, plegadas por defecto.

Esto conserva medidas y booleanos útiles sin volver a exponer una lista masiva como carga principal.
