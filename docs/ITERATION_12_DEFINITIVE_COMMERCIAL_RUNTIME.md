# Iteration 12 — Commercial contract + automatic runtime

## Objetivo

Cerrar la operación manual del worker y reemplazar la distribución artificial 1/3/6/9/12 cuotas por modalidades comerciales informadas realmente por Mercado Libre.

## Runtime

`python -m app.run` supervisa FastAPI y `app.worker` como procesos independientes. El worker no se incrusta en hooks de FastAPI para evitar duplicación bajo reload/múltiples workers HTTP.

## Modalidades

El frontend sólo presenta los `listing_type_id` que devuelve Mercado Libre para la combinación vendedor/categoría. El operador distribuye el lote entre esas opciones y la suma debe coincidir exactamente con la cantidad total.

- `gold_special`: Clásica cuando está disponible.
- `gold_pro`: Premium cuando está disponible.

Las cantidades de cuotas no se inventan. La financiación del producto Premium queda bajo las condiciones vigentes de Mercado Libre.

## Naming contract

Los intentos live de esta cuenta demostraron esta secuencia contractual:

1. ML exigió `listing_type_id` y `family_name`.
2. Con ambos presentes, ML rechazó `title` como campo inválido para la llamada.

Por esa evidencia operativa, la creación omite `title` y utiliza el nombre generado como `family_name`. La aplicación conserva el título generado internamente para revisión, ranking, auditoría y exportación; ML define el título externo final.

## Compatibilidad

No se agregó migración. Se reutiliza `PublicationDraft.commercial_config` como contrato comercial por draft. El campo histórico `installments` permanece por compatibilidad de esquema pero los nuevos lotes se generan con valor 1 y no gobierna la modalidad comercial.
