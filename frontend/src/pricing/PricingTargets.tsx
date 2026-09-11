import { pricingScenarioOptions } from "./scenarios";
import type { PricingCalculation } from "./types";

type Props = { calculation: PricingCalculation; onUseRecommendedPrice: (price: number) => void; currencyId?: string };

function money(value: number, currencyId: string) {
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: currencyId,
    maximumFractionDigits: 2,
  }).format(value);
}

export function PricingTargets({ calculation, onUseRecommendedPrice, currencyId = "ARS" }: Props) {
  return <section className="card pricingTargets">
    <div className="pricingSectionHeader"><h2>Opciones de precio</h2><p>Compará los márgenes. El precio recomendado queda resaltado según tu configuración.</p></div>
    <div className="pricingTargetsGrid">
      {pricingScenarioOptions(calculation).map(({ key, label, target, recommended }) => <div key={key} className={`pricingTarget${recommended ? " pricingTarget--recommended" : ""}`}>
        <div className="pricingTargetHeading"><span>{label}</span>{recommended && <em>Recomendado</em>}</div>
        <b>{money(target.grossPrice, currencyId)}</b>
        <small>Margen logrado: {target.achievedMarginPct.toFixed(2)}%</small>
        {recommended && <button type="button" onClick={() => onUseRecommendedPrice(Number(calculation.recommendedPrice))}>Usar este precio</button>}
      </div>)}
    </div>
  </section>;
}
