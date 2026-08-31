import logging
import time

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.drafts.intelligence import title_target_min_length

logger = logging.getLogger("ml-title-generation")


class OpenAIProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class GeneratedTitle(BaseModel):
    title: str
    intent: str
    keywords_used: list[str] = Field(default_factory=list)


class TitleGenerationResult(BaseModel):
    titles: list[GeneratedTitle]


class OpenAITitleGenerator:
    prompt_version = "title_generation_v4_semantic_trends"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to generate titles.")
        if not settings.openai_model:
            raise RuntimeError("OPENAI_MODEL must be configured explicitly.")
        self.model = settings.openai_model
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_request_timeout_seconds,
        )

    def generate(
        self,
        *,
        category_name: str,
        product_name: str,
        description: str,
        attributes: dict,
        discovery_context: dict,
        keywords: list[str],
        count: int,
        max_length: int,
    ) -> tuple[TitleGenerationResult, dict]:
        safe_attributes = {
            key: value for key, value in attributes.items()
            if value not in (None, "", [], {})
        }
        safe_context = {
            key: value for key, value in (discovery_context or {}).items()
            if key in {"brand", "model", "characteristics"} and value not in (None, "", [], {})
        }
        clean_description = (description or "").strip()
        target_min = title_target_min_length(max_length)
        system = (
            "Sos un especialista en títulos de Mercado Libre Argentina. "
            "Generá variantes reales de intención de búsqueda para EL MISMO producto. "
            "No inventes atributos. NO DATA = NO CLAIM. "
            "No uses promociones, envío gratis, cuotas, 'mejor', 'número 1' ni claims no provistos. "
            f"Cada título debe tener como máximo {max_length} caracteres y, cuando exista información factual útil, "
            f"apuntar al rango {target_min}-{max_length} caracteres. "
            "Nunca agregues relleno, palabras irrelevantes ni keyword stuffing sólo para alcanzar longitud. "
            "Podés variar formulaciones y usar sinónimos lingüísticos únicamente cuando preserven exactamente el significado "
            "de datos explícitos de la ficha; nunca uses un sinónimo para introducir una característica nueva. "
            "Los términos de tendencia recibidos ya fueron evaluados semánticamente contra la ficha y pueden incluir coincidencias directas, sinónimos o intenciones relacionadas seguras. "
            "Usalos como señal comercial de priorización sin convertirlos en claims adicionales. "
            "Si la lista está vacía, generá usando exclusivamente los datos factuales provistos. "
            "Evitá simples permutaciones de las mismas palabras."
        )
        user = (
            f"Categoría: {category_name}\n"
            f"Producto: {product_name}\n"
            f"Descripción factual: {clean_description}\n"
            f"Atributos autorizados: {safe_attributes}\n"
            f"Contexto factual adicional: {safe_context}\n"
            f"Términos populares de Mercado Libre aprobados semánticamente para este producto (puede estar vacío): {keywords}\n"
            f"Cantidad requerida: {count}\n"
            "Priorizá cobertura de términos útiles y claridad comercial sin introducir conceptos no respaldados. "
            "Devolvé exactamente esa cantidad si existen suficientes variantes válidas."
        )

        started = time.perf_counter()
        logger.info(
            "openai_title_generation_started model=%s requested=%d max_length=%d target_min=%d",
            self.model,
            count,
            max_length,
            target_min,
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text_format=TitleGenerationResult,
            )
        except RateLimitError as exc:
            error_code = getattr(exc, "code", None)
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                error = body.get("error") or body
                if isinstance(error, dict):
                    error_code = error.get("code") or error_code
            if error_code in {"credit_balance_exhausted", "insufficient_quota"}:
                raise OpenAIProviderError(
                    "La cuenta de OpenAI no tiene crédito disponible. Verificá la facturación de la API y volvé a intentarlo.",
                    code="AI_PROVIDER_QUOTA_EXHAUSTED",
                    retryable=False,
                    status_code=429,
                ) from exc
            raise OpenAIProviderError(
                "OpenAI alcanzó temporalmente un límite de uso. Volvé a intentarlo más tarde.",
                code="AI_PROVIDER_RATE_LIMIT",
                retryable=True,
                status_code=429,
            ) from exc
        except APIConnectionError as exc:
            raise OpenAIProviderError(
                "No se pudo conectar con OpenAI.",
                code="AI_PROVIDER_NETWORK_ERROR",
                retryable=True,
            ) from exc
        except APIStatusError as exc:
            raise OpenAIProviderError(
                f"OpenAI rechazó la generación (HTTP {exc.status_code}).",
                code="AI_PROVIDER_ERROR",
                retryable=exc.status_code >= 500,
                status_code=exc.status_code,
            ) from exc

        parsed = response.output_parsed
        if parsed is None:
            raise OpenAIProviderError(
                "OpenAI no devolvió una respuesta estructurada válida.",
                code="AI_PROVIDER_INVALID_RESPONSE",
                retryable=False,
            )
        usage = {}
        if getattr(response, "usage", None):
            usage_obj = response.usage
            usage = {
                "input_tokens": getattr(usage_obj, "input_tokens", None),
                "output_tokens": getattr(usage_obj, "output_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
        logger.info(
            "openai_title_generation_completed model=%s received=%d duration_ms=%d input_tokens=%s output_tokens=%s",
            self.model,
            len(parsed.titles),
            round((time.perf_counter() - started) * 1000),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )
        return parsed, {
            "request_id": getattr(response, "id", None),
            "usage": usage,
            "model": self.model,
        }
