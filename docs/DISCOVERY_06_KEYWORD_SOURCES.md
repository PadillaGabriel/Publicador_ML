# Discovery 0.x — Fuentes Mercado Libre para Keyword Intelligence

## Objetivo

Comprobar, con la cuenta Mercado Libre ya conectada, qué recursos pueden aportar evidencia legítima para el futuro `Keyword Intelligence` sin incorporar scraping ni promover endpoints no verificados al código productivo.

## Principio de seguridad

El probe reutiliza el token cifrado persistido por la aplicación y no imprime `access_token`, `refresh_token`, `client_secret`, `code`, `state` ni claves de configuración.

## Probes

| Probe | Uso | Estado contractual antes de la prueba |
|---|---|---|
| `/users/me` | Verificar autenticación/contexto | CONFIRMED_IN_CURRENT_PROJECT |
| `/sites/{site}/domain_discovery/search` | Resolver categoría candidata | CONFIRMED_IN_CURRENT_PROJECT |
| `/categories/{id}` | Metadata de categoría | CONFIRMED_IN_CURRENT_PROJECT |
| `/categories/{id}/attributes` | Atributos de categoría | CONFIRMED_IN_CURRENT_PROJECT |
| `/sites/{site}/search` | Títulos/resultados del marketplace | DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT |
| `/highlights/{site}/category/{id}` | Candidato para destacados/más vendidos | DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT |
| `/trends/{site}/{id}` | Candidato para términos de tendencia | DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT |
| `/sites/{site}/trends/search` | Endpoint histórico/legacy a descartar o confirmar | LEGACY_CANDIDATE_DO_NOT_INTEGRATE |

Un HTTP 200 demuestra disponibilidad empírica para la cuenta en el momento de la prueba, pero **no convierte por sí solo un endpoint no documentado en contrato productivo aprobado**. Antes de integrar una fuente marcada `DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT`, debe verificarse la documentación oficial vigente.

## Ejecución

Desde `backend`:

```powershell
python -m scripts.probe_ml_keyword_sources --query "mate imperial calabaza cuero vacuno"
```

Si hay más de una cuenta activa, el script indicará los UUID disponibles y deberá repetirse con:

```powershell
python -m scripts.probe_ml_keyword_sources --account-id <UUID> --query "mate imperial calabaza cuero vacuno"
```

Para conservar el resultado:

```powershell
python -m scripts.probe_ml_keyword_sources --query "mate imperial calabaza cuero vacuno" --output ml_keyword_probe.json
```

## Clasificación posterior

Cada fuente deberá quedar clasificada como una de:

- `CONFIRMADO`: contrato oficial vigente y prueba satisfactoria.
- `DEPENDIENTE_DE_CUENTA`: contrato válido, pero acceso condicionado por cuenta/app/permisos.
- `NO_CONFIRMADO`: respuesta empírica o referencia insuficiente sin contrato oficial vigente comprobado.
- `FUERA_DE_ALCANCE`: recurso no apropiado para la V1.

No se implementará scraping mientras existan fuentes oficiales suficientes para resolver la necesidad.
