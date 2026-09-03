import {useEffect, useMemo, useRef, useState} from "react";
import {api} from "../api";
import type {TitleAssistantProps, TitleRecommendationResponse} from "./types";

function factualAttributeValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }

  if (!value || typeof value !== "object") return "";

  const record = value as Record<string, unknown>;
  for (const key of ["value_name", "name", "value_id"]) {
    const candidate = record[key];
    if (typeof candidate === "string" || typeof candidate === "number") {
      const text = String(candidate).trim();
      if (text) return text;
    }
  }

  return "";
}

function factualAttributes(attributes: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(attributes)
      .map(([key, value]) => [key, factualAttributeValue(value)] as const)
      .filter(([, value]) => Boolean(value))
      .slice(0, 50)
  );
}

export function TitleAssistant({
  accountId,
  categoryId,
  productText,
  attributes,
  maxLength,
  onUseTitle,
}: TitleAssistantProps) {
  const [result, setResult] = useState<TitleRecommendationResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const requestGeneration = useRef(0);
  const normalizedAttributes = useMemo(() => factualAttributes(attributes), [attributes]);
  const attributeSignature = JSON.stringify(normalizedAttributes);
  const productName = productText.trim();
  const inputSignature = JSON.stringify({accountId, attributeSignature, categoryId, maxLength, productName});
  const currentInputSignature = useRef(inputSignature);
  if (currentInputSignature.current !== inputSignature) {
    currentInputSignature.current = inputSignature;
    requestGeneration.current += 1;
  }
  const hasPositiveLimit = typeof maxLength === "number" && Number.isFinite(maxLength) && maxLength > 0;
  const canGenerate = Boolean(accountId && categoryId && productName && hasPositiveLimit);

  useEffect(() => {
    requestGeneration.current += 1;
    setResult(null);
    setError("");
    setLoading(false);
  }, [inputSignature]);

  async function generateTitle() {
    if (!canGenerate || !maxLength) return;

    const generation = requestGeneration.current + 1;
    const requestSignature = inputSignature;
    requestGeneration.current = generation;
    setLoading(true);
    setError("");
    try {
      const response = await api<TitleRecommendationResponse>("/api/title-intelligence/generate", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          category_id: categoryId,
          product_name: productName,
          attributes: normalizedAttributes,
          max_length: maxLength,
        }),
      });
      if (generation !== requestGeneration.current || requestSignature !== currentInputSignature.current) return;
      setResult(response);
    } catch (requestError) {
      if (generation !== requestGeneration.current || requestSignature !== currentInputSignature.current) return;
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : "No se pudo generar el título.");
    } finally {
      if (generation === requestGeneration.current && requestSignature === currentInputSignature.current) setLoading(false);
    }
  }

  const missingPrerequisites = [
    !accountId ? "una cuenta" : "",
    !categoryId ? "una categoría hoja" : "",
    !productName ? "un nombre o título de producto" : "",
    !hasPositiveLimit ? "el límite de título de la categoría" : "",
  ].filter(Boolean);

  return <section className="titleAssistant" aria-label="Asistente de títulos">
    <div className="titleAssistantHeader">
      <div>
        <h3>Asistente de título</h3>
        <p>Genera opciones usando sólo los datos factuales del producto y el límite informado por Mercado Libre.</p>
      </div>
      {hasPositiveLimit && <span className="titleLimit">Máximo {maxLength} caracteres</span>}
    </div>

    <button type="button" disabled={!canGenerate || loading} onClick={generateTitle}>
      {loading ? "Generando título…" : "Generar sugerencia de título"}
    </button>

    {!canGenerate && <p className="titleAssistantState">Para generar una sugerencia, completá {missingPrerequisites.join(", ")}.</p>}
    {error && <p className="titleAssistantError" role="alert">{error}</p>}

    {result && <div className="titleAssistantResult">
      <div className="titleRecommendation">
        <div>
          <span>Recomendación</span>
          <b>{result.recommended_title}</b>
        </div>
        <button type="button" onClick={() => onUseTitle(result.recommended_title)}>Usar título</button>
      </div>

      <div className="titleSignals">
        {result.confidence === "TREND_SUPPORTED"
          ? <p><b>Señal de tendencia compatible:</b> {result.matched_trends.join(" · ")}</p>
          : <p><b>Señal factual:</b> no hubo una tendencia compatible; se usaron sólo datos del producto.</p>}
        {result.fallback_used && <p className="titleFallback">Se aplicó el modo factual de respaldo para mantener la sugerencia dentro del límite de la categoría.</p>}
      </div>

      {result.alternatives.length > 0 && <div className="titleAlternatives">
        <span>Alternativas</span>
        {result.alternatives.map((title) => <div key={title}>
          <b>{title}</b>
          <button type="button" className="secondary tiny" onClick={() => onUseTitle(title)}>Usar título</button>
        </div>)}
      </div>}
    </div>}

    <p className="titleSafetyNotice">Esta acción no crea borradores ni inicia publicaciones.</p>
  </section>;
}
