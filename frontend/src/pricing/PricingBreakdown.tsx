import { useEffect, useMemo, useState } from "react";
import { pricingScenarioOptions, recommendedScenario } from "./scenarios";
import type { PricingBreakdown as PricingBreakdownData, PricingCalculation } from "./types";

type Props = { calculation: PricingCalculation; currencyId?: string; showCurrentPrice?: boolean };
type LedgerRow = { label: string; effect: number };

type BreakdownScenario = {
  key: string;
  label: string;
  breakdown: PricingBreakdownData;
  recommended: boolean;
};

const ZERO_TOLERANCE = 0.005;

function money(value: number, currencyId: string) {
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: currencyId,
    maximumFractionDigits: 2,
  }).format(value);
}

function currentPriceStory(calculation: PricingCalculation) {
  const margin = calculation.analyzed.contributionMarginPct;
  const minimum = calculation.audit.minimumMarginPct;
  const recommended = calculation.audit.recommendedTargetMarginPct;

  if (margin < 0) {
    return {
      tone: "danger",
      title: "Este precio genera pérdida",
      message: "El precio actual no alcanza a cubrir todos los costos considerados. Conviene corregirlo antes de publicar.",
    };
  }
  if (margin < minimum) {
    return {
      tone: "warning",
      title: "Es rentable, pero queda por debajo del mínimo",
      message: `El margen actual es ${margin.toFixed(2)}%. Tu mínimo configurado es ${minimum.toFixed(2)}%.`,
    };
  }
  if (margin < recommended) {
    return {
      tone: "warning",
      title: "El precio es rentable, pero todavía puede mejorar",
      message: `Hoy obtenés ${margin.toFixed(2)}% de margen. El objetivo recomendado es ${recommended.toFixed(2)}%.`,
    };
  }
  return {
    tone: "success",
    title: "El precio actual ya cumple el objetivo",
    message: `El margen actual es ${margin.toFixed(2)}%, por encima del objetivo recomendado de ${recommended.toFixed(2)}%.`,
  };
}

function ledgerRows(breakdown: PricingBreakdownData): LedgerRow[] {
  const rows: LedgerRow[] = [
    { label: "Costo del producto neto", effect: -breakdown.netCmv },
    { label: "Comisión Mercado Libre neta", effect: -breakdown.mlCommissionNet },
    { label: "Financiación Mercado Libre neta", effect: -breakdown.financingNet },
    { label: "Cargo fijo Mercado Libre neto", effect: -breakdown.mlFixedFeeNet },
    { label: "Resultado logístico neto", effect: -breakdown.netLogisticCost },
    { label: "Ingresos Brutos", effect: -breakdown.iibb },
    { label: "Publicidad esperada", effect: -breakdown.adsExpected },
    { label: "Costo esperado por reintegros", effect: -breakdown.refundsExpected },
    { label: "Otros costos configurados", effect: -breakdown.additionalUnitCostNet },
  ];
  return rows.filter(row => Math.abs(row.effect) >= ZERO_TOLERANCE);
}

function scenarios(calculation: PricingCalculation, showCurrentPrice: boolean): BreakdownScenario[] {
  const proposalScenarios = pricingScenarioOptions(calculation).map(item => ({
    key: item.key,
    label: item.label,
    breakdown: item.breakdown,
    recommended: item.recommended,
  }));
  if (!showCurrentPrice) return proposalScenarios;
  return [
    { key: "analyzed", label: "Precio actual", breakdown: calculation.analyzed, recommended: false },
    ...proposalScenarios,
  ];
}

export function PricingBreakdown({ calculation, currencyId = "ARS", showCurrentPrice = false }: Props) {
  const story = currentPriceStory(calculation);
  const options = useMemo(() => scenarios(calculation, showCurrentPrice), [calculation, showCurrentPrice]);
  const recommendedKey = recommendedScenario(calculation)?.key ?? options[0]?.key ?? "analyzed";
  const [selectedKey, setSelectedKey] = useState(recommendedKey);

  useEffect(() => {
    setSelectedKey(recommendedKey);
  }, [recommendedKey, calculation]);

  const selected = options.find(option => option.key === selectedKey) ?? options[0];
  if (!selected) return null;

  const breakdown = selected.breakdown;
  const rows = ledgerRows(breakdown);

  return <section className="card pricingCurrentStory">
    {showCurrentPrice && <>
      <div className="pricingSectionHeader"><h2>Tu precio actual</h2><p>Primero vemos dónde estás hoy; después, las alternativas de margen.</p></div>
      <div className={`pricingStory pricingStory--${story.tone}`}>
        <div><b>{story.title}</b><p>{story.message}</p></div>
        <strong>{calculation.analyzed.contributionMarginPct.toFixed(2)}% MC</strong>
      </div>
      <div className="pricingCurrentGrid">
        <div><span>Precio analizado</span><b>{money(calculation.analyzed.grossPrice, currencyId)}</b></div>
        <div><span>Costo del producto</span><b>{money(calculation.analyzed.grossCmv, currencyId)}</b></div>
        <div><span>Disponible para costos fijos</span><b>{money(calculation.analyzed.contributionMargin, currencyId)}</b></div>
        <div><span>Margen actual</span><b>{calculation.analyzed.contributionMarginPct.toFixed(2)}%</b></div>
      </div>
    </>}

    <details className="pricingTechnicalDetails">
      <summary>Ver cómo se calcula</summary>
      <div className="pricingBreakdownHeader">
        <div>
          <h3>Cuenta neta por venta</h3>
          <p>Elegí una propuesta para ver exactamente qué entra, qué sale y cuánto queda.</p>
        </div>
        <div className="pricingScenarioSelector" role="group" aria-label="Escenario económico">
          {options.map(option => <button
            key={option.key}
            type="button"
            className={`${selected.key === option.key ? "active" : ""}${option.recommended ? " recommended" : ""}`}
            onClick={() => setSelectedKey(option.key)}
          >{option.label}{option.recommended && <small>Recomendado</small>}</button>)}
        </div>
      </div>

      <div className="pricingLedgerSummary">
        <div><span>Precio de venta</span><b>{money(breakdown.grossPrice, currencyId)}</b></div>
        <div><span>Precio neto sin IVA</span><b>{money(breakdown.netPrice, currencyId)}</b></div>
        <div><span>Cargo fijo ML informado</span><b>{money(breakdown.fixedFee, currencyId)}</b></div>
        <div><span>Margen</span><b>{breakdown.contributionMarginPct.toFixed(2)}%</b></div>
      </div>

      <div className="pricingLedger" aria-label={`Desglose ${selected.label}`}>
        <div className="pricingLedgerRow pricingLedgerRow--income">
          <span className="pricingLedgerSign">+</span>
          <span className="pricingLedgerLabel">Precio neto sin IVA</span>
          <b>{money(breakdown.netPrice, currencyId)}</b>
        </div>
        {rows.map(row => {
          const positive = row.effect > 0;
          return <div key={row.label} className="pricingLedgerRow">
            <span className={`pricingLedgerSign ${positive ? "positive" : "negative"}`}>{positive ? "+" : "−"}</span>
            <span className="pricingLedgerLabel">{row.label}</span>
            <b>{money(Math.abs(row.effect), currencyId)}</b>
          </div>;
        })}
        <div className={`pricingLedgerTotal${breakdown.contributionMargin < 0 ? " negative" : ""}`}>
          <div>
            <span>Disponible para cubrir costos fijos</span>
            <small>Margen de contribución que deja esta venta después de los costos considerados.</small>
          </div>
          <div>
            <b>{money(breakdown.contributionMargin, currencyId)}</b>
            <small>{breakdown.contributionMarginPct.toFixed(2)}% del precio neto</small>
          </div>
        </div>
      </div>
    </details>
  </section>;
}
