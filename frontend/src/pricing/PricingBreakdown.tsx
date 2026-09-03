import type { PricingBreakdown as Breakdown } from "./types";

type Props = { breakdown: Breakdown; currencyId?: string };

function money(value: number, currencyId: string) {
  return new Intl.NumberFormat("es-AR", { style: "currency", currency: currencyId, maximumFractionDigits: 2 }).format(value);
}

export function PricingBreakdown({ breakdown, currencyId = "ARS" }: Props) {
  const rows: [string, number][] = [
    ["Precio bruto", breakdown.grossPrice], ["Precio neto sin IVA", breakdown.netPrice],
    ["Costo del producto (con IVA)", breakdown.grossCmv], ["Costo del producto (sin IVA)", breakdown.netCmv],
    ["Comisión Mercado Libre neta", breakdown.mlCommissionNet], ["Cargo fijo ML neto", breakdown.mlFixedFeeNet],
    ["Envío", breakdown.shippingCost], ["Bonificación de envío", breakdown.shippingSubsidy],
    ["Envío cobrado al comprador", breakdown.buyerShippingAmount], ["Resultado logístico neto", breakdown.netLogisticCost],
    ["IIBB", breakdown.iibb], ["Publicidad esperada", breakdown.adsExpected], ["Reintegros esperados", breakdown.refundsExpected],
  ];
  return <section className="card pricingBreakdown">
    <div className="sectionTitle"><span>3</span> Desglose económico auditable</div>
    <div className="pricingBreakdownGrid">{rows.map(([label, value]) => <div key={label}><span>{label}</span><b>{money(value, currencyId)}</b></div>)}</div>
    <div className="pricingContribution"><span>Margen de contribución</span><b>{money(breakdown.contributionMargin, currencyId)}</b><small>{breakdown.contributionMarginPct.toFixed(2)}%</small></div>
  </section>;
}
