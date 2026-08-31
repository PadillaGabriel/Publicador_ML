import logging
import time
from enum import StrEnum

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger("ml-trend-semantic-analysis")


class OpenAITrendAnalysisError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class TrendClassification(StrEnum):
    DIRECT_MATCH = "DIRECT_MATCH"
    SYNONYM = "SYNONYM"
    RELATED_INTENT = "RELATED_INTENT"
    UNSUPPORTED = "UNSUPPORTED"


class TrendAssessment(BaseModel):
    term: str
    classification: TrendClassification
    maps_to: str | None = None
    reason: str


class TrendAssessmentResult(BaseModel):
    assessments: list[TrendAssessment] = Field(default_factory=list)


class OpenAITrendSemanticAnalyzer:
    prompt_version = "trend_semantic_assessment_v1"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to analyze Mercado Libre trends.")
        if not settings.openai_model:
            raise RuntimeError("OPENAI_MODEL must be configured explicitly.")
        self.model = settings.openai_model
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_request_timeout_seconds,
        )

    def assess(
        self,
        *,
        category_name: str,
        product_name: str,
        description: str,
        attributes: dict,
        discovery_context: dict,
        trend_candidates: list[dict],
    ) -> tuple[TrendAssessmentResult, dict]:
        safe_attributes = {
            key: value
            for key, value in attributes.items()
            if value not in (None, "", [], {})
        }
        safe_context = {
            key: value
            for key, value in (discovery_context or {}).items()
            if key in {"brand", "model", "characteristics"} and value not in (None, "", [], {})
        }
        clean_description = (description or "").strip()

        system = (
            "Sos un analista semántico especializado en búsquedas de Mercado Libre Argentina. "
            "Tu tarea es clasificar tendencias reales de búsqueda para un producto concreto usando EXCLUSIVAMENTE "
            "los datos factuales de la ficha provista. NO DATA = NO CLAIM. "
            "Una similitud léxica o de embeddings baja NO implica incompatibilidad: un término puede ser un sinónimo "
            "comercial válido aunque use palabras distintas. "
            "Clasificá DIRECT_MATCH cuando el término describe explícitamente el mismo producto o una formulación directa; "
            "SYNONYM cuando expresa el mismo concepto comercial con vocabulario diferente sin agregar propiedades; "
            "RELATED_INTENT cuando representa una intención de búsqueda cercana que puede usarse sin afirmar materiales, "
            "funciones, medidas, compatibilidades, marcas o prestaciones no informadas; "
            "UNSUPPORTED cuando introduce cualquier claim no respaldado, otra clase de producto o una característica desconocida. "
            "Los campos de similitud, cobertura y unsupported_tokens son señales deterministas auxiliares, no una verdad semántica. "
            "No inventes tendencias, no reformules los términos de entrada y clasificá cada término exactamente una vez."
        )
        user = (
            f"Categoría: {category_name}\n"
            f"Producto: {product_name}\n"
            f"Descripción factual: {clean_description}\n"
            f"Atributos autorizados: {safe_attributes}\n"
            f"Contexto factual adicional: {safe_context}\n"
            f"Tendencias a evaluar: {trend_candidates}\n"
            "Para SYNONYM, maps_to debe indicar brevemente el concepto factual equivalente de la ficha. "
            "Para DIRECT_MATCH o RELATED_INTENT, maps_to puede ser null si no agrega claridad. "
            "Para UNSUPPORTED, explicá qué afirmación o concepto no está respaldado."
        )

        started = time.perf_counter()
        logger.info(
            "openai_trend_analysis_started model=%s candidates=%d",
            self.model,
            len(trend_candidates),
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text_format=TrendAssessmentResult,
            )
        except RateLimitError as exc:
            error_code = getattr(exc, "code", None)
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                error = body.get("error") or body
                if isinstance(error, dict):
                    error_code = error.get("code") or error_code
            if error_code in {"credit_balance_exhausted", "insufficient_quota"}:
                raise OpenAITrendAnalysisError(
                    "La cuenta de OpenAI no tiene crédito disponible para analizar tendencias.",
                    code="AI_TREND_ANALYSIS_QUOTA_EXHAUSTED",
                    retryable=False,
                    status_code=429,
                ) from exc
            raise OpenAITrendAnalysisError(
                "OpenAI alcanzó temporalmente un límite al analizar tendencias.",
                code="AI_TREND_ANALYSIS_RATE_LIMIT",
                retryable=True,
                status_code=429,
            ) from exc
        except APIConnectionError as exc:
            raise OpenAITrendAnalysisError(
                "No se pudo conectar con OpenAI para analizar tendencias.",
                code="AI_TREND_ANALYSIS_NETWORK_ERROR",
                retryable=True,
            ) from exc
        except APIStatusError as exc:
            raise OpenAITrendAnalysisError(
                f"OpenAI rechazó el análisis semántico de tendencias (HTTP {exc.status_code}).",
                code="AI_TREND_ANALYSIS_PROVIDER_ERROR",
                retryable=exc.status_code >= 500,
                status_code=exc.status_code,
            ) from exc

        parsed = response.output_parsed
        if parsed is None:
            raise OpenAITrendAnalysisError(
                "OpenAI no devolvió un análisis estructurado válido de tendencias.",
                code="AI_TREND_ANALYSIS_INVALID_RESPONSE",
                retryable=False,
            )

        expected_terms = [str(item["term"]) for item in trend_candidates]
        by_normalized = {term.casefold().strip(): term for term in expected_terms}
        seen: set[str] = set()
        canonical_assessments: list[TrendAssessment] = []
        for assessment in parsed.assessments:
            key = assessment.term.casefold().strip()
            canonical = by_normalized.get(key)
            if canonical is None or key in seen:
                raise OpenAITrendAnalysisError(
                    "OpenAI devolvió tendencias inexistentes o duplicadas en el análisis semántico.",
                    code="AI_TREND_ANALYSIS_INVALID_RESPONSE",
                    retryable=False,
                )
            seen.add(key)
            canonical_assessments.append(
                assessment.model_copy(update={"term": canonical})
            )

        if len(canonical_assessments) != len(expected_terms):
            raise OpenAITrendAnalysisError(
                "OpenAI no clasificó todas las tendencias recibidas.",
                code="AI_TREND_ANALYSIS_INCOMPLETE_RESPONSE",
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
            "openai_trend_analysis_completed model=%s candidates=%d usable=%d duration_ms=%d input_tokens=%s output_tokens=%s",
            self.model,
            len(canonical_assessments),
            sum(
                assessment.classification != TrendClassification.UNSUPPORTED
                for assessment in canonical_assessments
            ),
            round((time.perf_counter() - started) * 1000),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )
        return TrendAssessmentResult(assessments=canonical_assessments), {
            "request_id": getattr(response, "id", None),
            "usage": usage,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }
