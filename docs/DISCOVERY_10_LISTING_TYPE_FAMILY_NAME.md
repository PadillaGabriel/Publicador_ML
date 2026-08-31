# Discovery 10 — listing_type_id + family_name

## Motivo

El primer POST live real a `/items` llegó a Mercado Libre pero fue rechazado con `HTTP 400 / body.required_fields`, indicando que faltaban `listing_type_id` y `family_name`.

## Objetivo

Obtener evidencia de cuenta real antes de modificar el payload productivo:

1. Qué listing types expone el site.
2. Qué listing types admite la cuenta/categoría, si el recurso candidato sigue disponible.
3. Qué campos `listing_type_id`, `family_name` y `user_product_id` aparecen en publicaciones activas reales de la cuenta.
4. Si la metadata de categoría/atributos aporta una fuente explícita para `family_name`.

## Regla

Un endpoint candidato que responde 200 aporta evidencia operacional, pero no se considera contrato documentado por ese solo hecho. No se modifica el publication engine hasta revisar el resultado del probe.

## Ejecución

Desde `backend`:

```powershell
python -m scripts.probe_ml_publication_contract --category-id MLA392279
```

O resolviendo categoría desde texto:

```powershell
python -m scripts.probe_ml_publication_contract --query "Kit Boca Juniors mate con yerbera"
```

El script no crea publicaciones y no imprime tokens ni secretos.
