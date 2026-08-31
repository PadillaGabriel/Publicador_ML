from functools import lru_cache


class SemanticModelError(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - deployment/configuration failure
        raise SemanticModelError(
            "sentence-transformers no está instalado. Instalá las dependencias del backend."
        ) from exc

    try:
        return SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - depends on local model cache/network
        raise SemanticModelError(
            f"No se pudo cargar el modelo semántico local '{model_name}'."
        ) from exc


class LocalSemanticRanker:
    """Computes local semantic similarity; it never decides factual eligibility."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def similarities(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        model = _load_model(self.model_name)
        try:
            embeddings = model.encode(
                [query, *candidates],
                convert_to_tensor=True,
                normalize_embeddings=True,
            )
            scores = model.similarity(embeddings[:1], embeddings[1:])[0]
            return [float(value) for value in scores.tolist()]
        except Exception as exc:  # pragma: no cover - provider/library runtime failure
            raise SemanticModelError("Falló el cálculo local de similitud semántica.") from exc
