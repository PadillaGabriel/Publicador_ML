import type { PricingCalculation, PricingTarget } from "./types";

type Props = { calculation: PricingCalculation; onUseRecommendedPrice: (price: number) => void; currencyId?: string };

function money(value: number, currencyId: string) {
  return new Intl.NumberFormat("es-AR", { style: "currency", currency: currencyId, maximumFractionDigits: 2 }).format(value);
}

function TargetCard({ title, target, currencyId }: { title: string; target: PricingTarget | null; currencyId: string }) {
  if (!target) return null;
  return <div className="pricingTarget"><span>{title}</span><b>{money(target.grossPrice, currencyId)}</b><small>MC logrado: {target.achievedMarginPct.toFixed(2)}%</small></div>;
}

export function PricingTargets({ calculation, onUseRecommendedPrice, currencyId = "ARS" }: Props) {
  return <section className="card pricingTargets">
    <div className="sectionTitle"><span>4</span> Objetivos de margen</div>
    <div className="pricingTargetsGrid">
      <TargetCard title="Margen de contribución: 0%" target={calculation.mc0} currencyId={currencyId} />
      <TargetCard title="Margen de contribución: 15%" target={calculation.mc15} currencyId={currencyId} />
      <TargetCard title="Margen de contribución: 20%" target={calculation.mc20} currencyId={currencyId} />
      <TargetCard title="Margen objetivo personalizado" target={calculation.custom} currencyId={currencyId} />
    </div>
    <div className="pricingRecommended"><div><span>Precio económico recomendado</span><b>{money(calculation.recommendedPrice, currencyId)}</b></div><button type="button" onClick={() => onUseRecommendedPrice(Number(calculation.recommendedPrice))}>Usar precio recomendado</button></div>
  </section>;
}
