import { useEffect, useState } from "react";
import { api } from "../api";
import { PricingBreakdown } from "./PricingBreakdown";
import { PricingTargets } from "./PricingTargets";
import { normalizeCalculation, type PricingCalculation, type PricingCalculatorApiResponse } from "./types";

type Props = {
  onUseRecommendedPrice: (price: number, calculation: PricingCalculation) => void;
  accountId?: string;
};
type Mode = "existing" | "new";

const initialForm = { accountId: "", grossCmv: "", targetMarginPct: "", adsRatePct: "", iibbRatePct: "", refundRatePct: "", itemId: "", mlaId: "", sku: "", categoryId: "", listingTypeId: "", dimensions: "", weight: "", logisticType: "", shippingMode: "" };

function optionalNumber(value: string) { return value.trim() ? Number(value) : undefined; }

export function PriceCalculator({ onUseRecommendedPrice, accountId = "" }: Props) {
  const [mode, setMode] = useState<Mode>("new");
  const [form, setForm] = useState({ ...initialForm, accountId });
  const [result, setResult] = useState<PricingCalculation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (name: keyof typeof form, value: string) => setForm(current => ({ ...current, [name]: value }));

  useEffect(() => {
    setForm(current => current.accountId === accountId ? current : { ...current, accountId });
  }, [accountId]);

  async function calculate() {
    setBusy(true); setError(""); setResult(null);
    try {
      const overrides = {
        ads_rate_pct: optionalNumber(form.adsRatePct), iibb_rate_pct: optionalNumber(form.iibbRatePct), refund_rate_pct: optionalNumber(form.refundRatePct),
      };
      const base = { account_id: form.accountId || null, sku: form.sku || null, gross_cmv: optionalNumber(form.grossCmv), target_margin_pct: optionalNumber(form.targetMarginPct), overrides };
      const payload = mode === "existing"
        ? { ...base, item_id: form.itemId || null, mla_id: form.mlaId || null }
        : { ...base, category_id: form.categoryId || null, listing_type_id: form.listingTypeId || null, package: { dimensions: form.dimensions || null, weight: optionalNumber(form.weight), logistic_type: form.logisticType || null, shipping_mode: form.shippingMode || null } };
      const response = await api<PricingCalculatorApiResponse>(mode === "existing" ? "/api/pricing/calculator/existing" : "/api/pricing/calculator/new", { method: "POST", body: JSON.stringify(payload) });
      setResult(normalizeCalculation(response));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible calcular el precio.");
    } finally { setBusy(false); }
  }

  return <>
    <header><div><h1>Calculadora de Precio</h1><p>Estimá un precio económico con costos configurados y datos reales de Mercado Libre. La calculadora no crea borradores ni publica.</p></div></header>
    <section className="card priceCalculator">
      <div className="pricingModeTabs"><button type="button" className={mode === "existing" ? "active" : ""} onClick={() => { setMode("existing"); setResult(null); }}>Publicación existente</button><button type="button" className={mode === "new" ? "active" : ""} onClick={() => { setMode("new"); setResult(null); }}>Producto nuevo</button></div>
      <p className="pricingScenario">Escenario base: <b>1 unidad</b></p>
      <div className="grid3">
        <label>ID de cuenta ML<input value={form.accountId} onChange={event => update("accountId", event.target.value)} placeholder="UUID de la cuenta" /></label>
        <label>CMV bruto con IVA<input type="number" min="0" step="0.01" value={form.grossCmv} onChange={event => update("grossCmv", event.target.value)} /></label>
        <label>MC personalizado %<input type="number" min="0" max="99" step="0.01" value={form.targetMarginPct} onChange={event => update("targetMarginPct", event.target.value)} /></label>
      </div>
      <div className="grid3">
        <label>Override Ads %<input type="number" min="0" max="99" step="0.01" value={form.adsRatePct} onChange={event => update("adsRatePct", event.target.value)} /></label>
        <label>Override IIBB %<input type="number" min="0" max="99" step="0.01" value={form.iibbRatePct} onChange={event => update("iibbRatePct", event.target.value)} /></label>
        <label>Override reintegros %<input type="number" min="0" max="99" step="0.01" value={form.refundRatePct} onChange={event => update("refundRatePct", event.target.value)} /></label>
      </div>
      {mode === "existing" ? <div className="grid3"><label>ID de publicación<input value={form.itemId} onChange={event => update("itemId", event.target.value)} placeholder="MLA123..." /></label><label>MLA alternativo<input value={form.mlaId} onChange={event => update("mlaId", event.target.value)} placeholder="MLA123..." /></label><label>SKU<input value={form.sku} onChange={event => update("sku", event.target.value)} /></label></div> : <><div className="grid3"><label>SKU<input value={form.sku} onChange={event => update("sku", event.target.value)} /></label><label>Categoría ML<input value={form.categoryId} onChange={event => update("categoryId", event.target.value)} placeholder="MLA..." /></label><label>Tipo de publicación<input value={form.listingTypeId} onChange={event => update("listingTypeId", event.target.value)} placeholder="gold_special" /></label></div><div className="grid4"><label>Dimensiones<input value={form.dimensions} onChange={event => update("dimensions", event.target.value)} placeholder="30x20x10" /></label><label>Peso<input type="number" min="0" step="0.01" value={form.weight} onChange={event => update("weight", event.target.value)} /></label><label>Tipo logístico<input value={form.logisticType} onChange={event => update("logisticType", event.target.value)} placeholder="drop_off" /></label><label>Modo de envío<input value={form.shippingMode} onChange={event => update("shippingMode", event.target.value)} placeholder="me2" /></label></div></>}
      <button type="button" disabled={busy || !form.accountId || !form.grossCmv} onClick={calculate}>{busy ? "Calculando…" : "Calcular precio"}</button>
      {error && <div className="notice pricingError">{error}</div>}
    </section>
    {result && <><PricingBreakdown breakdown={result.analyzed} /><PricingTargets calculation={result} onUseRecommendedPrice={price => onUseRecommendedPrice(price, result)} /></>}
  </>;
}
